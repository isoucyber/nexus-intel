"""Sugestões da IA com aprovação humana (ADR-0004, seção "Sugestões").

A IA nunca escreve nos dados do projeto. Ela só registra uma sugestão pendente;
aprovar aplica pelo fluxo normal do `ProjectStore` (revisão + auditoria encadeada),
na mesma transação que marca a sugestão como aprovada. Rejeitar guarda o motivo.
Criação, aprovação e rejeição entram no log de auditoria.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from nexus_intel.application.project_store import ProjectStore, now_iso
from nexus_intel.domain.errors import NexusError
from nexus_intel.domain.ids import new_ulid
from nexus_intel.domain.model import require_name
from nexus_intel.infrastructure.db.connection import Tx

KINDS = ("entity", "relation", "claim", "note")
KIND_LABELS = {"entity": "Nova entidade", "relation": "Nova relação", "claim": "Nova afirmação", "note": "Nova nota"}
MAX_TEXT = 4000


class SuggestionError(NexusError):
    user_message = "Sugestão inválida."


def _clean(value: Any, limit: int = MAX_TEXT) -> str:
    return str(value or "").strip()[:limit]


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().casefold()


def excerpt_in(excerpt: str, document: str) -> bool:
    """O trecho citado aparece no documento (ignorando espaços e maiúsculas)?"""
    ex = _norm_ws(excerpt)
    return bool(ex) and ex in _norm_ws(document)


@dataclass
class Suggestion:
    id: str
    kind: str
    payload: dict[str, Any]
    summary: str
    rationale: str
    origin: str
    status: str
    created_at: str
    decided_at: str | None
    decision_note: str
    result_id: str | None

    @property
    def label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)


class SuggestionBox:
    def __init__(self, store: ProjectStore) -> None:
        self.store = store

    # ----------------------------------------------------------- validação
    def _entity_name(self, eid: str) -> str:
        row = self.store._one("SELECT display_name FROM entity WHERE id=? AND record_status='active'", (eid,))
        if not row:
            raise SuggestionError(f"A entidade {eid!r} não existe no projeto.")
        return str(row["display_name"])

    def _check_source(self, payload: dict[str, Any], document: str | None) -> None:
        sid = _clean(payload.get("source_id"), 64)
        excerpt = _clean(payload.get("excerpt"))
        payload["source_id"] = sid or None
        payload["excerpt"] = excerpt
        if sid and not self.store._one("SELECT id FROM source WHERE id=?", (sid,)):
            raise SuggestionError(f"A fonte {sid!r} não existe no projeto.")
        # Trecho só conta como conferido se aparece, literalmente, no documento lido.
        payload["excerpt_checked"] = bool(excerpt and document and excerpt_in(excerpt, document))

    def validate(self, kind: str, payload: dict[str, Any], document: str | None = None) -> tuple[dict[str, Any], str]:
        """Confere a sugestão contra os dados reais e devolve (payload limpo, resumo legível)."""
        if kind not in KINDS:
            raise SuggestionError(f"Tipo de sugestão desconhecido: {kind!r}.")
        p = {k: v for k, v in payload.items() if isinstance(k, str)}
        if kind == "entity":
            name = require_name(_clean(p.get("name"), 300))
            type_key = _clean(p.get("type_key"), 64) or "other"
            t = self.store._one("SELECT key, label FROM entity_type WHERE key=? OR id=?", (type_key, type_key)) \
                or self.store.find_type_by_label(type_key)
            if not t:
                raise SuggestionError(f"Tipo de entidade desconhecido: {type_key!r}.")
            clean = {"type_key": t["key"], "name": name, "summary": _clean(p.get("summary"), 1000)}
            return clean, f"{t['label']}: {name}"
        if kind == "relation":
            a, b = _clean(p.get("source_entity_id"), 64), _clean(p.get("target_entity_id"), 64)
            na, nb = self._entity_name(a), self._entity_name(b)
            if a == b:
                raise SuggestionError("Uma relação precisa ligar duas entidades diferentes.")
            rt_key = _clean(p.get("type_key"), 64)
            rt = self.store._one("SELECT key, label FROM relation_type WHERE key=? OR id=? OR lower(label)=lower(?)",
                                 (rt_key, rt_key, rt_key))
            if not rt:
                raise SuggestionError(f"Tipo de relação desconhecido: {rt_key!r}.")
            clean = {"type_key": rt["key"], "source_entity_id": a, "target_entity_id": b,
                     "description": _clean(p.get("description"), 1000),
                     "source_id": p.get("source_id"), "excerpt": p.get("excerpt")}
            self._check_source(clean, document)
            return clean, f"{na} {rt['label']} {nb}"
        if kind == "claim":
            eid = _clean(p.get("entity_id"), 64)
            name = self._entity_name(eid)
            f = self.store._field_for(eid, _clean(p.get("field_key"), 64))
            value = _clean(p.get("value"), 2000)
            if not value:
                raise SuggestionError("A afirmação precisa de um valor.")
            try:
                self.store.parse_value(f["datatype"], value)  # recusa data/número inválidos já aqui
            except ValueError as exc:
                raise SuggestionError(str(exc)) from exc
            clean = {"entity_id": eid, "field_key": f["key"], "value": value,
                     "source_id": p.get("source_id"), "excerpt": p.get("excerpt")}
            self._check_source(clean, document)
            return clean, f"{name} — {f['label']}: {value}"
        # note
        title = _clean(p.get("title"), 300) or "Nota da IA"
        body = _clean(p.get("body"), 20000)
        eid = _clean(p.get("entity_id"), 64) or None
        if eid:
            self._entity_name(eid)
        return {"title": title, "body": body, "entity_id": eid}, f"Nota: {title}"

    # ------------------------------------------------------------- escrita
    def propose(self, kind: str, payload: dict[str, Any], *, rationale: str = "", origin: str = "ai",
                document: str | None = None) -> Suggestion:
        clean, summary = self.validate(kind, payload, document)
        sid, ts = new_ulid(), now_iso()
        with Tx(self.store.conn):
            self.store.conn.execute(
                "INSERT INTO suggestion(id, kind, payload_json, summary, rationale, origin, status, created_at)"
                " VALUES (?,?,?,?,?,?, 'pending', ?)",
                (sid, kind, json.dumps(clean, ensure_ascii=False), summary[:500], _clean(rationale, 2000),
                 _clean(origin, 120) or "ai", ts))
            self.store.audit("suggestion.create", "suggestion", sid, f"{KIND_LABELS[kind]}: {summary}")
        return self.get(sid)

    def approve(self, sid: str, note: str = "") -> str:
        """Aplica a sugestão e devolve o ID do que foi criado."""
        s = self.get(sid)
        if s.status != "pending":
            raise SuggestionError("Esta sugestão já foi decidida.")
        clean, _summary = self.validate(s.kind, s.payload)  # os dados podem ter mudado desde a sugestão
        st = self.store
        with Tx(st.conn):
            if s.kind == "entity":
                rid = st.create_entity(clean["type_key"], clean["name"], summary=clean["summary"])
            elif s.kind == "relation":
                rid = st.create_relation(
                    clean["type_key"], clean["source_entity_id"], clean["target_entity_id"],
                    description=clean["description"], evidence_source=clean["source_id"],
                    excerpt=clean["excerpt"], origin="ai")
            elif s.kind == "claim":
                rid = st.add_claim(clean["entity_id"], clean["field_key"], clean["value"],
                                   source_id=clean["source_id"], excerpt=clean["excerpt"], origin="ai",
                                   note="Sugerida pela IA e aprovada.")
            else:
                rid = st.create_note(clean["title"], clean["body"], clean["entity_id"])
            st.conn.execute(
                "UPDATE suggestion SET status='approved', decided_at=?, decision_note=?, result_id=? WHERE id=?",
                (now_iso(), _clean(note, 1000), rid, sid))
            st.audit("suggestion.approve", "suggestion", sid, f"{s.label}: {s.summary} → {rid}")
        return rid

    def reject(self, sid: str, reason: str = "") -> None:
        s = self.get(sid)
        if s.status != "pending":
            raise SuggestionError("Esta sugestão já foi decidida.")
        with Tx(self.store.conn):
            self.store.conn.execute(
                "UPDATE suggestion SET status='rejected', decided_at=?, decision_note=? WHERE id=?",
                (now_iso(), _clean(reason, 1000), sid))
            self.store.audit("suggestion.reject", "suggestion", sid, f"{s.label}: {s.summary}"
                             + (f" — motivo: {_clean(reason, 200)}" if reason else ""))

    # ------------------------------------------------------------- leitura
    @staticmethod
    def _row(r: dict[str, Any]) -> Suggestion:
        try:
            payload = json.loads(r["payload_json"])
        except json.JSONDecodeError:
            payload = {}
        return Suggestion(r["id"], r["kind"], payload, r["summary"], r["rationale"], r["origin"], r["status"],
                          r["created_at"], r["decided_at"], r["decision_note"], r["result_id"])

    def get(self, sid: str) -> Suggestion:
        r = self.store._one("SELECT * FROM suggestion WHERE id=?", (sid,))
        if not r:
            raise SuggestionError("Sugestão não encontrada.")
        return self._row(r)

    def list(self, status: str | None = "pending", limit: int = 200) -> list[Suggestion]:
        if status:
            rows = self.store._all("SELECT * FROM suggestion WHERE status=? ORDER BY created_at DESC, rowid DESC"
                                   " LIMIT ?", (status, limit))
        else:
            rows = self.store._all("SELECT * FROM suggestion ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,))
        return [self._row(r) for r in rows]

    def count_pending(self) -> int:
        r = self.store._one("SELECT count(*) AS n FROM suggestion WHERE status='pending'")
        return int(r["n"]) if r else 0
