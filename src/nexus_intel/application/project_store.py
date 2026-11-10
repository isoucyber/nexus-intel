"""Casos de uso de um projeto aberto.

Cada operação de escrita roda numa transação única que também grava a
revisão (histórico) e a linha do log de auditoria encadeado (seção 8.4).
A conexão só enxerga o arquivo deste projeto: isolamento por construção.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from nexus_intel.domain import catalog
from nexus_intel.domain.dates import from_storage, parse_fuzzy_date
from nexus_intel.domain.errors import NexusError
from nexus_intel.domain.ids import new_ulid
from nexus_intel.domain.model import (
    require_name,
    IDENTIFIER_SCHEMES,
    Epistemic,
    normalize_identifier,
    normalize_name,
    strip_accents,
)
from nexus_intel.domain.rules import (
    DUPLICATE_THRESHOLD,
    DuplicateCandidate,
    find_conflicts,
    score_duplicate,
)
from nexus_intel.infrastructure.db.connection import Tx
from nexus_intel.infrastructure.media.blobs import BlobStore
from nexus_intel.infrastructure.media.images import inspect_image

GENESIS_HASH = "0" * 64
_ENTITY_EDITABLE = {
    "display_name", "summary", "description_md", "private_note", "color", "icon",
    "importance", "is_favorite", "type_id",
}
_CLAIM_EDITABLE = {"epistemic_status", "credibility", "valid_from", "valid_to", "note", "review_at", "is_sensitive"}
_RELATION_EDITABLE = {"type_id", "description", "valid_from", "valid_to", "epistemic_status", "credibility"}
_SOURCE_EDITABLE = {"title", "kind", "url", "author", "published_at", "accessed_at", "reliability", "note", "is_discredited"}


class ConcurrentEdit(NexusError):
    user_message = "Este registro foi alterado em outro lugar. Recarregue e tente de novo."


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class ClaimView:
    row: dict[str, Any]
    field_label: str
    datatype: str
    display_value: str
    evidence_count: int
    in_conflict: bool
    only_discredited: bool


@dataclass
class FieldGroup:
    field_def: dict[str, Any]
    claims: list[ClaimView] = field(default_factory=list)

    @property
    def has_conflict(self) -> bool:
        return any(c.in_conflict for c in self.claims)


class ProjectStore:
    def __init__(self, conn: Any, project_id: str, actor: str, blobs: BlobStore | None = None) -> None:
        self.conn = conn
        self.project_id = project_id
        self.actor = actor
        self.blobs = blobs

    def close(self) -> None:
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            self.conn.close()
            if self.blobs is not None:
                self.blobs.close()

    # ================================================================ util
    def _one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        row: dict[str, Any] | None = self.conn.execute(sql, params).fetchone()
        return row

    def _all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return list(self.conn.execute(sql, params).fetchall())

    def audit(self, action: str, kind: str | None, obj_id: str | None, summary: str = "") -> None:
        last = self._one("SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1")
        prev = last["hash"] if last else GENESIS_HASH
        aid, ts = new_ulid(), now_iso()
        payload = json.dumps([aid, ts, self.actor, action, kind, obj_id, summary], ensure_ascii=False)
        digest = hashlib.sha256((prev + payload).encode("utf-8")).hexdigest()
        self.conn.execute(
            "INSERT INTO audit_log(id, ts, actor, action, object_kind, object_id, summary, prev_hash, hash)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (aid, ts, self.actor, action, kind, obj_id, summary[:500], prev, digest),
        )

    def verify_audit(self) -> int | None:
        """Devolve o `seq` da primeira linha adulterada, ou None se a cadeia está íntegra."""
        prev = GENESIS_HASH
        for r in self._all("SELECT * FROM audit_log ORDER BY seq"):
            payload = json.dumps(
                [r["id"], r["ts"], r["actor"], r["action"], r["object_kind"], r["object_id"], r["summary"]],
                ensure_ascii=False,
            )
            expected = hashlib.sha256((prev + payload).encode("utf-8")).hexdigest()
            if r["prev_hash"] != prev or r["hash"] != expected:
                return int(r["seq"])
            prev = r["hash"]
        return None

    def audit_entries(self, limit: int = 200) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM audit_log ORDER BY seq DESC LIMIT ?", (limit,))

    def _revision(self, kind: str, obj_id: str, change: str, snapshot: dict[str, Any] | None = None) -> None:
        table = {"entity": "entity", "claim": "claim", "relation": "relation", "source": "source"}.get(kind)
        if snapshot is None and table:
            snapshot = self._one(f"SELECT * FROM {table} WHERE id=?", (obj_id,)) or {}  # noqa: S608
        snapshot = snapshot or {}
        self.conn.execute(
            "INSERT INTO revision(id, object_kind, object_id, version, snapshot_json, changed_at, change_kind)"
            " VALUES (?,?,?,?,?,?,?)",
            (new_ulid(), kind, obj_id, int(snapshot.get("version", 0)),
             json.dumps(snapshot, ensure_ascii=False, default=str), now_iso(), change),
        )

    def history(self, kind: str, obj_id: str) -> list[dict[str, Any]]:
        return self._all(
            "SELECT * FROM revision WHERE object_kind=? AND object_id=? ORDER BY changed_at DESC, rowid DESC",
            (kind, obj_id),
        )

    # ============================================================ criação
    def initialize(self, name: str, template: str, purpose: str, legal_basis: str) -> None:
        with Tx(self.conn):
            self.conn.execute(
                "INSERT INTO project_meta(id, name, purpose, legal_basis, created_at) VALUES (?,?,?,?,?)",
                (self.project_id, name, purpose, legal_basis, now_iso()),
            )
            for t in catalog.ENTITY_TYPES:
                tid = new_ulid()
                self.conn.execute(
                    "INSERT INTO entity_type(id, key, label, icon, color, is_builtin) VALUES (?,?,?,?,?,1)",
                    (tid, t.key, t.label, t.icon, t.color),
                )
                for order, f in enumerate(t.fields):
                    self.conn.execute(
                        "INSERT INTO field_def(id, entity_type_id, key, label, datatype, cardinality,"
                        " conflict_rule, enum_options_json, sort_order, is_sensitive)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (new_ulid(), tid, f.key, f.label, f.datatype,
                         "many" if f.conflict_rule == "multi" else "one", f.conflict_rule,
                         json.dumps(list(f.options)) if f.options else None, order, int(f.sensitive)),
                    )
            for key, label, inverse, directed in catalog.RELATION_TYPES:
                self.conn.execute(
                    "INSERT INTO relation_type(id, key, label, inverse_label, directed, is_builtin)"
                    " VALUES (?,?,?,?,?,1)",
                    (new_ulid(), key, label, inverse, int(directed)),
                )
            self.audit("project.create", "project", self.project_id, f"{name} ({template})")
        if template == "example":
            self._seed_example()

    def _seed_example(self) -> None:
        """Exemplo guiado: pessoa → veículo → cidade, com fontes fictícias e sem nomes reais."""
        joao = self.create_entity("person", "Pessoa Exemplo (fictícia)", summary="Pessoa de exemplo.",
                                  aliases=["P. Exemplo"])
        carro = self.create_entity("vehicle", "Fiat Uno placa XYZ-0000 (fictício)")
        veneza = self.create_entity("location", "Veneza", summary="Cidade no nordeste da Itália.")
        empresa = self.create_entity("company", "Acme Transportes Ltda. (fictícia)")
        doc = self.create_source("Certidão fictícia de registro do veículo", kind="official",
                                 reliability="B", accessed_at="2026-01-10")
        news = self.create_source("Reportagem fictícia sobre a Acme", kind="news",
                                  url="https://exemplo.invalid/reportagem", reliability="C")
        self.create_relation("owns", joao, carro, status="verified", evidence_source=doc,
                             excerpt="Proprietário: Pessoa Exemplo", valid_from="2024-01-01")
        self.create_relation("located_in", carro, veneza, status="reported", evidence_source=news,
                             excerpt="O veículo foi visto em Veneza")
        self.create_relation("works_at", joao, empresa, status="unverified")
        self.add_claim(joao, "nascimento", "03/1985", status="reported", source_id=doc)
        self.add_claim(joao, "nascimento", "1986", status="reported", source_id=news,
                       note="Fontes divergem: exemplo de conflito.")
        self.add_claim(carro, "marca", "Fiat", status="verified", source_id=doc)
        self.add_claim(veneza, "pais", "Itália", status="verified")
        self.set_tags(veneza, ["regiao/europa/italia"])

    # ============================================================== tipos
    def entity_types(self) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM entity_type ORDER BY is_builtin DESC, label")

    def entity_type(self, key_or_id: str) -> dict[str, Any]:
        row = self._one("SELECT * FROM entity_type WHERE id=? OR key=?", (key_or_id, key_or_id))
        if not row:
            raise NexusError(f"Tipo de entidade desconhecido: {key_or_id}")
        return row

    def find_type_by_label(self, text: str) -> dict[str, Any] | None:
        norm = normalize_name(text)
        for t in self.entity_types():
            if norm in {normalize_name(t["label"]), t["key"]}:
                return t
        for t in self.entity_types():
            if normalize_name(t["label"]).startswith(norm):
                return t
        return None

    def fields_for_type(self, type_id: str) -> list[dict[str, Any]]:
        chain, current = [], self.entity_type(type_id)
        while current:
            chain.append(current["id"])
            current = self._one("SELECT * FROM entity_type WHERE id=?", (current["parent_id"],)) if current["parent_id"] else None
        marks = ",".join("?" * len(chain))
        return self._all(
            f"SELECT * FROM field_def WHERE entity_type_id IN ({marks}) ORDER BY sort_order, label",  # noqa: S608
            tuple(chain),
        )

    def add_field(self, type_id: str, label: str, datatype: str = "text", conflict_rule: str = "single") -> str:
        label = require_name(label, "O nome do campo")
        key = re.sub(r"[^a-z0-9]+", "_", strip_accents(label).lower()).strip("_") or "campo"
        fid = new_ulid()
        with Tx(self.conn):
            self.conn.execute(
                "INSERT INTO field_def(id, entity_type_id, key, label, datatype, cardinality, conflict_rule, sort_order)"
                " VALUES (?,?,?,?,?,?,?,1000)",
                (fid, type_id, key, label.strip(), datatype,
                 "many" if conflict_rule == "multi" else "one", conflict_rule),
            )
            self.audit("field.create", "field_def", fid, label)
        return fid

    def create_entity_type(self, label: str, parent_key: str | None = None, color: str = "#94a3b8") -> str:
        label = require_name(label, "O nome do tipo")
        key = re.sub(r"[^a-z0-9]+", "_", strip_accents(label).lower()).strip("_")
        parent = self.entity_type(parent_key)["id"] if parent_key else None
        tid = new_ulid()
        with Tx(self.conn):
            self.conn.execute(
                "INSERT INTO entity_type(id, key, label, parent_id, color) VALUES (?,?,?,?,?)",
                (tid, key, label.strip(), parent, color),
            )
            self.audit("entity_type.create", "entity_type", tid, label)
        return tid

    def relation_types(self) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM relation_type ORDER BY label")

    def relation_type(self, key_or_id: str) -> dict[str, Any]:
        row = self._one("SELECT * FROM relation_type WHERE id=? OR key=?", (key_or_id, key_or_id))
        if not row:
            raise NexusError(f"Tipo de relação desconhecido: {key_or_id}")
        return row

    # =========================================================== entidades
    def create_entity(
        self,
        type_key: str,
        display_name: str,
        *,
        summary: str = "",
        description_md: str = "",
        importance: int = 3,
        aliases: list[str] | None = None,
        identifiers: list[tuple[str, str]] | None = None,
    ) -> str:
        name = require_name(display_name)
        t = self.entity_type(type_key)
        eid, ts = new_ulid(), now_iso()
        with Tx(self.conn):
            self.conn.execute(
                "INSERT INTO entity(id, type_id, display_name, display_name_norm, summary, description_md,"
                " importance, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (eid, t["id"], name, normalize_name(name), summary, description_md,
                 max(1, min(5, importance)), ts, ts),
            )
            for a in aliases or []:
                self._add_alias(eid, a)
            for scheme, value in identifiers or []:
                self._add_identifier(eid, scheme, value)
            self._reindex(eid)
            self._revision("entity", eid, "create")
            self.audit("entity.create", "entity", eid, f"{t['label']}: {name}")
        return eid

    def quick_capture(self, text: str) -> str:
        """"João Silva · pessoa" (ou "João Silva, pessoa" / "João Silva | pessoa")."""
        parts = re.split(r"\s*[·|;]\s*|\s*,\s*(?=[^,]*$)", text.strip(), maxsplit=1)
        name = parts[0].strip()
        type_row = self.find_type_by_label(parts[1]) if len(parts) > 1 and parts[1].strip() else None
        if len(parts) > 1 and type_row is None:
            # Vírgula pode fazer parte do nome ("Silva, João"): só trata como tipo se reconhecido.
            name = text.strip()
        return self.create_entity(type_row["key"] if type_row else "other", name)

    def get_entity(self, eid: str) -> dict[str, Any]:
        row = self._one(
            "SELECT e.*, t.label AS type_label, t.key AS type_key, t.icon AS type_icon,"
            " coalesce(e.color, t.color) AS effective_color FROM entity e"
            " JOIN entity_type t ON t.id = e.type_id WHERE e.id=?",
            (eid,),
        )
        if not row:
            raise NexusError("Entidade não encontrada.")
        row["aliases"] = self._all("SELECT * FROM entity_alias WHERE entity_id=? ORDER BY alias", (eid,))
        row["identifiers"] = self._all(
            "SELECT * FROM entity_identifier WHERE entity_id=? ORDER BY scheme", (eid,)
        )
        row["tags"] = [r["path"] for r in self._all(
            "SELECT t.path FROM tag t JOIN entity_tag et ON et.tag_id=t.id WHERE et.entity_id=? ORDER BY t.path",
            (eid,),
        )]
        return row

    def update_entity(self, eid: str, expected_version: int, **changes: Any) -> int:
        bad = set(changes) - _ENTITY_EDITABLE
        if bad:
            raise ValueError(f"campos não editáveis: {bad}")
        if "display_name" in changes:
            changes["display_name"] = require_name(changes["display_name"])
            changes["display_name_norm"] = normalize_name(changes["display_name"])
        if "importance" in changes:
            changes["importance"] = max(1, min(5, int(changes["importance"])))
        sets = ", ".join(f"{k}=?" for k in changes)
        with Tx(self.conn):
            cur = self.conn.execute(
                f"UPDATE entity SET {sets}, updated_at=?, version=version+1 WHERE id=? AND version=?",  # noqa: S608
                (*changes.values(), now_iso(), eid, expected_version),
            )
            if cur.rowcount != 1:
                raise ConcurrentEdit()
            self._reindex(eid)
            self._revision("entity", eid, "update")
            self.audit("entity.update", "entity", eid, ", ".join(sorted(changes)))
        return expected_version + 1

    def set_entity_status(self, eid: str, status: str) -> None:
        if status not in {"active", "archived", "trashed"}:
            raise ValueError(status)
        with Tx(self.conn):
            self.conn.execute(
                "UPDATE entity SET record_status=?, trashed_at=?, updated_at=?, version=version+1 WHERE id=?",
                (status, now_iso() if status == "trashed" else None, now_iso(), eid),
            )
            self._revision("entity", eid, status)
            self.audit(f"entity.{status}", "entity", eid)

    def trash_entity(self, eid: str) -> None:
        self.set_entity_status(eid, "trashed")

    def restore_entity(self, eid: str) -> None:
        self.set_entity_status(eid, "active")

    def delete_entity_permanently(self, eid: str) -> None:
        row = self._one("SELECT record_status, display_name FROM entity WHERE id=?", (eid,))
        if not row:
            return
        if row["record_status"] != "trashed":
            raise NexusError("Mova para a lixeira antes de excluir definitivamente.")
        with Tx(self.conn):
            self._revision("entity", eid, "purge")
            claim_ids = [r["id"] for r in self._all("SELECT id FROM claim WHERE subject_id=?", (eid,))]
            rel_ids = [r["id"] for r in self._all(
                "SELECT id FROM relation WHERE source_id=? OR target_id=?", (eid, eid))]
            for cid in claim_ids:
                self.conn.execute("DELETE FROM evidence WHERE target_kind='claim' AND target_id=?", (cid,))
            for rid in rel_ids:
                self.conn.execute("DELETE FROM evidence WHERE target_kind='relation' AND target_id=?", (rid,))
            self.conn.execute("DELETE FROM evidence WHERE target_kind='entity' AND target_id=?", (eid,))
            self.conn.execute("UPDATE claim SET value_entity_id=NULL WHERE value_entity_id=?", (eid,))
            self.conn.execute("DELETE FROM entity_fts WHERE entity_id=?", (eid,))
            self.conn.execute("DELETE FROM entity WHERE id=?", (eid,))
            self.audit("entity.purge", "entity", eid, row["display_name"])
        self._gc_attachments()

    def empty_trash(self, older_than_days: int | None = None) -> int:
        sql, params = "SELECT id FROM entity WHERE record_status='trashed'", ()
        if older_than_days is not None:
            limit = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat(timespec="seconds")
            sql += " AND trashed_at <= ?"
            params = (limit,)
        ids = [r["id"] for r in self._all(sql, params)]
        for eid in ids:
            self.delete_entity_permanently(eid)
        rels = [r["id"] for r in self._all("SELECT id FROM relation WHERE record_status='trashed'")]
        for rid in rels:
            self.delete_relation_permanently(rid)
        return len(ids) + len(rels)

    def list_entities(
        self,
        *,
        type_id: str | None = None,
        status: str = "active",
        tag: str | None = None,
        favorites_only: bool = False,
        without_evidence: bool = False,
        order: str = "updated",
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where, params = ["e.record_status=?"], [status]
        if type_id:
            where.append("e.type_id=?")
            params.append(type_id)
        if favorites_only:
            where.append("e.is_favorite=1")
        if tag:
            where.append("e.id IN (SELECT et.entity_id FROM entity_tag et JOIN tag t ON t.id=et.tag_id"
                         " WHERE t.path=? OR t.path LIKE ?)")
            params += [tag, f"{tag}/%"]
        if without_evidence:
            where.append(
                "NOT EXISTS (SELECT 1 FROM evidence v WHERE (v.target_kind='entity' AND v.target_id=e.id)"
                " OR (v.target_kind='claim' AND v.target_id IN (SELECT id FROM claim WHERE subject_id=e.id))"
                " OR (v.target_kind='relation' AND v.target_id IN"
                " (SELECT id FROM relation WHERE source_id=e.id OR target_id=e.id)))"
            )
        order_sql = {
            "updated": "e.updated_at DESC",
            "name": "e.display_name_norm ASC",
            "created": "e.created_at DESC",
            "importance": "e.importance DESC, e.display_name_norm",
        }.get(order, "e.updated_at DESC")
        sql = (
            "SELECT e.id, e.display_name, e.summary, e.importance, e.is_favorite, e.updated_at,"
            " e.created_at, e.record_status, e.version, t.label AS type_label, t.key AS type_key,"
            " coalesce(e.color, t.color) AS effective_color,"
            " (SELECT count(*) FROM relation r WHERE r.record_status='active' AND"
            "   (r.source_id=e.id OR r.target_id=e.id)) AS relation_count"
            f" FROM entity e JOIN entity_type t ON t.id=e.type_id WHERE {' AND '.join(where)}"
            f" ORDER BY {order_sql} LIMIT ? OFFSET ?"
        )
        return self._all(sql, (*params, limit, offset))  # noqa: S608

    def count_entities(self, status: str = "active") -> int:
        row = self._one("SELECT count(*) AS n FROM entity WHERE record_status=?", (status,))
        return int(row["n"]) if row else 0

    # ------------------------------------------------------- nomes e ids
    def _add_alias(self, eid: str, alias: str) -> None:
        alias = alias.strip()
        if alias:
            self.conn.execute(
                "INSERT INTO entity_alias(id, entity_id, alias, alias_norm) VALUES (?,?,?,?)",
                (new_ulid(), eid, alias, normalize_name(alias)),
            )

    def _add_identifier(self, eid: str, scheme: str, value: str) -> None:
        if scheme not in IDENTIFIER_SCHEMES:
            raise NexusError(f"Tipo de identificador desconhecido: {scheme}")
        norm = normalize_identifier(scheme, value)
        if norm:
            self.conn.execute(
                "INSERT INTO entity_identifier(id, entity_id, scheme, value_norm) VALUES (?,?,?,?)",
                (new_ulid(), eid, scheme, norm),
            )

    def set_aliases(self, eid: str, aliases: list[str]) -> None:
        with Tx(self.conn):
            self.conn.execute("DELETE FROM entity_alias WHERE entity_id=?", (eid,))
            for a in dict.fromkeys(a.strip() for a in aliases if a.strip()):
                self._add_alias(eid, a)
            self._touch(eid)
            self.audit("entity.aliases", "entity", eid)

    def set_identifiers(self, eid: str, identifiers: list[tuple[str, str]]) -> None:
        with Tx(self.conn):
            self.conn.execute("DELETE FROM entity_identifier WHERE entity_id=?", (eid,))
            for scheme, value in identifiers:
                self._add_identifier(eid, scheme, value)
            self._touch(eid)
            self.audit("entity.identifiers", "entity", eid)

    def set_tags(self, eid: str, paths: list[str]) -> None:
        clean = []
        for p in paths:
            p = "/".join(seg.strip() for seg in p.strip().strip("/").split("/") if seg.strip())
            if p:
                clean.append(p)
        with Tx(self.conn):
            self.conn.execute("DELETE FROM entity_tag WHERE entity_id=?", (eid,))
            for p in dict.fromkeys(clean):
                row = self._one("SELECT id FROM tag WHERE path=?", (p,))
                tid = row["id"] if row else new_ulid()
                if not row:
                    self.conn.execute("INSERT INTO tag(id, path) VALUES (?,?)", (tid, p))
                self.conn.execute("INSERT INTO entity_tag(entity_id, tag_id) VALUES (?,?)", (eid, tid))
            self._touch(eid)
            self.audit("entity.tags", "entity", eid, ", ".join(clean))

    def all_tags(self) -> list[dict[str, Any]]:
        return self._all(
            "SELECT t.path, t.color, count(et.entity_id) AS n FROM tag t"
            " LEFT JOIN entity_tag et ON et.tag_id=t.id GROUP BY t.id ORDER BY t.path"
        )

    def _touch(self, eid: str) -> None:
        self.conn.execute("UPDATE entity SET updated_at=?, version=version+1 WHERE id=?", (now_iso(), eid))
        self._reindex(eid)

    def _reindex(self, eid: str) -> None:
        e = self._one("SELECT display_name, summary, description_md, record_status FROM entity WHERE id=?", (eid,))
        self.conn.execute("DELETE FROM entity_fts WHERE entity_id=?", (eid,))
        if not e:
            return
        aliases = " ".join(r["alias"] for r in self._all("SELECT alias FROM entity_alias WHERE entity_id=?", (eid,)))
        idents = " ".join(r["value_norm"] for r in self._all(
            "SELECT value_norm FROM entity_identifier WHERE entity_id=?", (eid,)))
        tags = " ".join(r["path"].replace("/", " ") for r in self._all(
            "SELECT t.path FROM tag t JOIN entity_tag et ON et.tag_id=t.id WHERE et.entity_id=?", (eid,)))
        claims = " ".join(r["value_text"] for r in self._all(
            "SELECT value_text FROM claim WHERE subject_id=? AND value_text IS NOT NULL", (eid,)))
        body = " ".join([e["summary"], e["description_md"], tags, claims])
        self.conn.execute(
            "INSERT INTO entity_fts(entity_id, name, aliases, body) VALUES (?,?,?,?)",
            (eid, e["display_name"], f"{aliases} {idents}", body),
        )

    # ========================================================== afirmações
    def _field_for(self, subject_id: str, field_key_or_id: str) -> dict[str, Any]:
        type_id = self.get_entity(subject_id)["type_id"]
        for f in self.fields_for_type(type_id):
            if field_key_or_id in (f["id"], f["key"]):
                return f
        raise NexusError(f"Campo '{field_key_or_id}' não existe para este tipo.")

    @staticmethod
    def parse_value(datatype: str, raw: Any) -> dict[str, Any]:
        """Converte a entrada do usuário para as colunas tipadas de `claim`."""
        out: dict[str, Any] = {k: None for k in (
            "value_text", "value_num", "value_date_start", "value_date_end",
            "value_date_precision", "value_bool", "value_entity_id")}
        text = str(raw).strip() if raw is not None else ""
        if datatype == "date":
            d = parse_fuzzy_date(text)
            out.update(value_date_start=d.start.isoformat(), value_date_end=d.end.isoformat(),
                       value_date_precision=d.precision, value_text=text)
        elif datatype == "number":
            try:
                out["value_num"] = float(text.replace(".", "").replace(",", ".")) if "," in text else float(text)
            except ValueError as exc:
                raise NexusError(f"Número inválido: {text!r}") from exc
            out["value_text"] = text
        elif datatype == "bool":
            out["value_bool"] = int(text.lower() in {"1", "sim", "s", "true", "verdadeiro", "yes"})
            out["value_text"] = "Sim" if out["value_bool"] else "Não"
        elif datatype == "entity":
            out["value_entity_id"] = text
        else:
            if not text:
                raise NexusError("Informe um valor.")
            if datatype == "email" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", text):
                raise NexusError("E-mail inválido.")
            if datatype == "url" and not re.match(r"^[a-z][a-z0-9+.-]*://", text, re.I):
                text = "https://" + text
            out["value_text"] = text
        return out

    def add_claim(
        self,
        subject_id: str,
        field_key: str,
        value: Any,
        *,
        status: str = "",
        credibility: int | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
        note: str = "",
        source_id: str | None = None,
        excerpt: str = "",
        locator: str = "",
        origin: str = "manual",
        review_at: str | None = None,
    ) -> str:
        f = self._field_for(subject_id, field_key)
        values = self.parse_value(f["datatype"], value)
        status = status or (Epistemic.REPORTED if source_id else Epistemic.UNVERIFIED)
        Epistemic(status)
        cid, ts = new_ulid(), now_iso()
        with Tx(self.conn):
            self.conn.execute(
                "INSERT INTO claim(id, subject_id, field_def_id, value_text, value_num, value_date_start,"
                " value_date_end, value_date_precision, value_bool, value_entity_id, valid_from, valid_to,"
                " epistemic_status, credibility, is_sensitive, note, origin, recorded_at, updated_at, review_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, subject_id, f["id"], values["value_text"], values["value_num"],
                 values["value_date_start"], values["value_date_end"], values["value_date_precision"],
                 values["value_bool"], values["value_entity_id"], valid_from or None, valid_to or None,
                 str(status), credibility, f["is_sensitive"], note, origin, ts, ts, review_at or None),
            )
            if source_id:
                self._add_evidence(source_id, "claim", cid, excerpt, locator)
            self._touch(subject_id)
            self._revision("claim", cid, "create")
            self.audit("claim.create", "claim", cid, f"{f['label']} de {subject_id}")
        return cid

    def update_claim(self, cid: str, expected_version: int, *, value: Any = None, **changes: Any) -> None:
        bad = set(changes) - _CLAIM_EDITABLE
        if bad:
            raise ValueError(f"campos não editáveis: {bad}")
        row = self._one("SELECT * FROM claim WHERE id=?", (cid,))
        if not row:
            raise NexusError("Afirmação não encontrada.")
        if "epistemic_status" in changes:
            Epistemic(changes["epistemic_status"])
        if value is not None:
            f = self._one("SELECT datatype FROM field_def WHERE id=?", (row["field_def_id"],))
            changes.update(self.parse_value(f["datatype"] if f else "text", value))
        sets = ", ".join(f"{k}=?" for k in changes)
        with Tx(self.conn):
            cur = self.conn.execute(
                f"UPDATE claim SET {sets}, updated_at=?, version=version+1 WHERE id=? AND version=?",  # noqa: S608
                (*changes.values(), now_iso(), cid, expected_version),
            )
            if cur.rowcount != 1:
                raise ConcurrentEdit()
            self._touch(row["subject_id"])
            self._revision("claim", cid, "update")
            self.audit("claim.update", "claim", cid, ", ".join(sorted(changes)))

    def set_preferred_claim(self, cid: str) -> None:
        row = self._one("SELECT subject_id, field_def_id FROM claim WHERE id=?", (cid,))
        if not row:
            return
        with Tx(self.conn):
            self.conn.execute(
                "UPDATE claim SET is_preferred=0 WHERE subject_id=? AND field_def_id=?",
                (row["subject_id"], row["field_def_id"]),
            )
            self.conn.execute("UPDATE claim SET is_preferred=1, version=version+1 WHERE id=?", (cid,))
            self.audit("claim.prefer", "claim", cid)

    def delete_claim(self, cid: str) -> None:
        row = self._one("SELECT subject_id FROM claim WHERE id=?", (cid,))
        if not row:
            return
        with Tx(self.conn):
            self._revision("claim", cid, "delete")
            self.conn.execute("DELETE FROM evidence WHERE target_kind='claim' AND target_id=?", (cid,))
            self.conn.execute("DELETE FROM claim WHERE id=?", (cid,))
            self._touch(row["subject_id"])
            self.audit("claim.delete", "claim", cid)

    def claims_for(self, subject_id: str) -> list[FieldGroup]:
        entity = self.get_entity(subject_id)
        groups: dict[str, FieldGroup] = {
            f["id"]: FieldGroup(f) for f in self.fields_for_type(entity["type_id"])
        }
        rows = self._all(
            "SELECT c.*,"
            " (SELECT count(*) FROM evidence v WHERE v.target_kind='claim' AND v.target_id=c.id) AS ev_count,"
            " (SELECT count(*) FROM evidence v JOIN source s ON s.id=v.source_id"
            "   WHERE v.target_kind='claim' AND v.target_id=c.id AND s.is_discredited=0) AS ev_good,"
            " (SELECT display_name FROM entity x WHERE x.id=c.value_entity_id) AS value_entity_name"
            " FROM claim c WHERE c.subject_id=? ORDER BY c.is_preferred DESC, c.recorded_at",
            (subject_id,),
        )
        by_field: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            by_field.setdefault(r["field_def_id"], []).append(r)
        for fid, claims in by_field.items():
            group = groups.get(fid)
            if group is None:  # campo de outro tipo (após conversão de tipo)
                fd = self._one("SELECT * FROM field_def WHERE id=?", (fid,))
                if not fd:
                    continue
                group = groups[fid] = FieldGroup(fd)
            conflicts = find_conflicts(claims, group.field_def["conflict_rule"])
            for c in claims:
                group.claims.append(ClaimView(
                    row=c,
                    field_label=group.field_def["label"],
                    datatype=group.field_def["datatype"],
                    display_value=self.display_claim_value(c, group.field_def["datatype"]),
                    evidence_count=c["ev_count"],
                    in_conflict=c["id"] in conflicts,
                    only_discredited=c["ev_count"] > 0 and c["ev_good"] == 0,
                ))
        return list(groups.values())

    @staticmethod
    def display_claim_value(c: dict[str, Any], datatype: str) -> str:
        if datatype == "date":
            d = from_storage(c.get("value_date_start"), c.get("value_date_end"), c.get("value_date_precision"))
            return d.display() if d else ""
        if datatype == "entity":
            return str(c.get("value_entity_name") or "(entidade removida)")
        if datatype == "bool":
            return "Sim" if c.get("value_bool") else "Não"
        return str(c.get("value_text") or "")

    # ============================================================ relações
    def create_relation(
        self,
        type_key: str,
        source_id: str,
        target_id: str,
        *,
        status: str = "",
        description: str = "",
        valid_from: str | None = None,
        valid_to: str | None = None,
        credibility: int | None = None,
        evidence_source: str | None = None,
        excerpt: str = "",
        locator: str = "",
        origin: str = "manual",
    ) -> str:
        """`source_id`/`target_id` são entidades; `evidence_source` é a fonte que sustenta."""
        if source_id == target_id:
            raise NexusError("Uma relação precisa ligar duas entidades diferentes.")
        rt = self.relation_type(type_key)
        status = status or (Epistemic.REPORTED if evidence_source else Epistemic.UNVERIFIED)
        Epistemic(status)
        rid, ts = new_ulid(), now_iso()
        with Tx(self.conn):
            self.conn.execute(
                "INSERT INTO relation(id, type_id, source_id, target_id, description, valid_from, valid_to,"
                " epistemic_status, credibility, origin, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (rid, rt["id"], source_id, target_id, description, valid_from or None, valid_to or None,
                 str(status), credibility, origin, ts, ts),
            )
            if evidence_source:
                self._add_evidence(evidence_source, "relation", rid, excerpt, locator)
            self.conn.execute("UPDATE entity SET updated_at=? WHERE id IN (?,?)", (ts, source_id, target_id))
            self._revision("relation", rid, "create")
            self.audit("relation.create", "relation", rid, f"{source_id} {rt['label']} {target_id}")
        return rid

    def update_relation(self, rid: str, expected_version: int, **changes: Any) -> None:
        bad = set(changes) - _RELATION_EDITABLE
        if bad:
            raise ValueError(f"campos não editáveis: {bad}")
        if "epistemic_status" in changes:
            Epistemic(changes["epistemic_status"])
        if "type_id" in changes:
            changes["type_id"] = self.relation_type(changes["type_id"])["id"]
        sets = ", ".join(f"{k}=?" for k in changes)
        with Tx(self.conn):
            cur = self.conn.execute(
                f"UPDATE relation SET {sets}, updated_at=?, version=version+1 WHERE id=? AND version=?",  # noqa: S608
                (*changes.values(), now_iso(), rid, expected_version),
            )
            if cur.rowcount != 1:
                raise ConcurrentEdit()
            self._revision("relation", rid, "update")
            self.audit("relation.update", "relation", rid, ", ".join(sorted(changes)))

    def set_relation_status(self, rid: str, record_status: str) -> None:
        with Tx(self.conn):
            self.conn.execute(
                "UPDATE relation SET record_status=?, updated_at=?, version=version+1 WHERE id=?",
                (record_status, now_iso(), rid),
            )
            self._revision("relation", rid, record_status)
            self.audit(f"relation.{record_status}", "relation", rid)

    def get_relation(self, rid: str) -> dict[str, Any]:
        """Relação com nomes das pontas, tipo e número de fontes (para painéis de detalhe)."""
        row = self._one(
            "SELECT r.*, rt.label, rt.inverse_label, rt.directed, rt.key AS type_key,"
            " s.display_name AS source_name, t.display_name AS target_name,"
            " (SELECT count(*) FROM evidence v WHERE v.target_kind='relation' AND v.target_id=r.id) AS ev_count"
            " FROM relation r JOIN relation_type rt ON rt.id=r.type_id"
            " JOIN entity s ON s.id=r.source_id JOIN entity t ON t.id=r.target_id WHERE r.id=?",
            (rid,))
        if not row:
            raise NexusError("Relação não encontrada: ela pode ter sido excluída definitivamente.")
        row["phrase"] = f"{row['source_name']} {row['label']} {row['target_name']}"
        return row

    def cut_relation(self, rid: str) -> None:
        """Corta a relação: ela vai para a lixeira (recuperável). As entidades não mudam."""
        rel = self.get_relation(rid)
        if rel["record_status"] == "trashed":
            return
        self.set_relation_status(rid, "trashed")

    def restore_relation(self, rid: str) -> None:
        rel = self.get_relation(rid)
        if rel["record_status"] != "trashed":
            return
        self.set_relation_status(rid, "active")

    def list_trashed_relations(self) -> list[dict[str, Any]]:
        rows = self._all(
            "SELECT r.id, r.updated_at, r.epistemic_status, rt.label, s.display_name AS source_name,"
            " t.display_name AS target_name, s.record_status AS source_status, t.record_status AS target_status"
            " FROM relation r JOIN relation_type rt ON rt.id=r.type_id"
            " JOIN entity s ON s.id=r.source_id JOIN entity t ON t.id=r.target_id"
            " WHERE r.record_status='trashed' ORDER BY r.updated_at DESC")
        for r in rows:
            r["phrase"] = f"{r['source_name']} {r['label']} {r['target_name']}"
        return rows

    def delete_relation_permanently(self, rid: str) -> None:
        """Exclui de vez uma relação cortada, com as evidências dela (nada fica órfão).
        As entidades das pontas continuam intactas."""
        rel = self._one("SELECT record_status FROM relation WHERE id=?", (rid,))
        if not rel:
            return
        if rel["record_status"] != "trashed":
            raise NexusError("Corte a relação (mova para a lixeira) antes de excluí-la definitivamente.")
        with Tx(self.conn):
            self._revision("relation", rid, "purge")
            self.conn.execute("DELETE FROM evidence WHERE target_kind='relation' AND target_id=?", (rid,))
            self.conn.execute("DELETE FROM relation WHERE id=?", (rid,))
            self.audit("relation.purge", "relation", rid)

    def relations_for(self, eid: str, include_trashed: bool = False) -> list[dict[str, Any]]:
        status_sql = "" if include_trashed else "AND r.record_status='active'"
        rows = self._all(
            "SELECT r.*, rt.label, rt.inverse_label, rt.directed, rt.key AS type_key,"
            " s.display_name AS source_name, t.display_name AS target_name,"
            " s.record_status AS source_status, t.record_status AS target_status,"
            " (SELECT count(*) FROM evidence v WHERE v.target_kind='relation' AND v.target_id=r.id) AS ev_count"
            " FROM relation r JOIN relation_type rt ON rt.id=r.type_id"
            " JOIN entity s ON s.id=r.source_id JOIN entity t ON t.id=r.target_id"
            f" WHERE (r.source_id=? OR r.target_id=?) {status_sql} ORDER BY rt.label, r.created_at",
            (eid, eid),
        )
        for r in rows:
            outgoing = r["source_id"] == eid
            r["other_id"] = r["target_id"] if outgoing else r["source_id"]
            r["other_name"] = r["target_name"] if outgoing else r["source_name"]
            r["phrase"] = r["label"] if outgoing or not r["directed"] else r["inverse_label"]
            r["other_trashed"] = (r["target_status"] if outgoing else r["source_status"]) == "trashed"
        return rows

    # =============================================================== fontes
    def create_source(
        self,
        title: str,
        *,
        kind: str = "other",
        url: str | None = None,
        author: str | None = None,
        published_at: str | None = None,
        accessed_at: str | None = None,
        reliability: str | None = None,
        note: str = "",
    ) -> str:
        title = require_name(title, "O título da fonte")
        sid, ts = new_ulid(), now_iso()
        with Tx(self.conn):
            self.conn.execute(
                "INSERT INTO source(id, title, kind, url, author, published_at, accessed_at, reliability,"
                " note, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (sid, title, kind, url or None, author or None, published_at or None,
                 accessed_at or None, reliability or None, note, ts, ts),
            )
            self._revision("source", sid, "create")
            self.audit("source.create", "source", sid, title)
        return sid

    def update_source(self, sid: str, expected_version: int, **changes: Any) -> None:
        bad = set(changes) - _SOURCE_EDITABLE
        if bad:
            raise ValueError(f"campos não editáveis: {bad}")
        if "title" in changes:
            changes["title"] = require_name(changes["title"], "O título da fonte")
        changes = {k: (v if v != "" or k in {"note", "title"} else None) for k, v in changes.items()}
        sets = ", ".join(f"{k}=?" for k in changes)
        with Tx(self.conn):
            cur = self.conn.execute(
                f"UPDATE source SET {sets}, updated_at=?, version=version+1 WHERE id=? AND version=?",  # noqa: S608
                (*changes.values(), now_iso(), sid, expected_version),
            )
            if cur.rowcount != 1:
                raise ConcurrentEdit()
            self._revision("source", sid, "update")
            self.audit("source.update", "source", sid, ", ".join(sorted(changes)))

    def source_link_counts(self, sid: str) -> dict[str, int]:
        """Quantos vínculos (evidências) a fonte tem, por tipo de alvo."""
        rows = self._all("SELECT target_kind, count(*) AS n FROM evidence WHERE source_id=? GROUP BY target_kind",
                         (sid,))
        counts = {"claim": 0, "relation": 0, "entity": 0}
        counts.update({r["target_kind"]: r["n"] for r in rows})
        return counts

    def delete_source(self, sid: str) -> dict[str, int]:
        """Exclui a fonte e DESVINCULA o que dependia dela: as evidências que apontam para a
        fonte são removidas; afirmações e relações continuam (as que ficarem sem fonte passam
        a aparecer em Qualidade). Um retrato da fonte fica no histórico e a ação, na auditoria.
        Devolve as contagens de vínculos removidos."""
        src = self.get_source(sid)
        counts = self.source_link_counts(sid)
        with Tx(self.conn):
            self._revision("source", sid, "delete")
            self.conn.execute("DELETE FROM evidence WHERE source_id=?", (sid,))
            self.conn.execute("DELETE FROM source WHERE id=?", (sid,))
            self.audit("source.delete", "source", sid,
                       f"{src['title']} (vínculos removidos: {sum(counts.values())})")
        return counts

    def get_source(self, sid: str) -> dict[str, Any]:
        row = self._one("SELECT * FROM source WHERE id=?", (sid,))
        if not row:
            raise NexusError("Fonte não encontrada.")
        return row

    def list_sources(self, query: str = "") -> list[dict[str, Any]]:
        q = f"%{query.strip()}%"
        return self._all(
            "SELECT s.*, (SELECT count(*) FROM evidence v WHERE v.source_id=s.id) AS uses"
            " FROM source s WHERE s.record_status='active' AND (s.title LIKE ? OR coalesce(s.url,'') LIKE ?)"
            " ORDER BY s.updated_at DESC",
            (q, q),
        )

    def _add_evidence(self, source_id: str, kind: str, target_id: str, excerpt: str, locator: str) -> str:
        if not self._one("SELECT id FROM source WHERE id=?", (source_id,)):
            raise NexusError("Fonte não encontrada.")
        vid = new_ulid()
        self.conn.execute(
            "INSERT INTO evidence(id, source_id, target_kind, target_id, excerpt, locator, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (vid, source_id, kind, target_id, excerpt, locator, now_iso()),
        )
        return vid

    def add_evidence(self, source_id: str, kind: str, target_id: str, excerpt: str = "", locator: str = "") -> str:
        with Tx(self.conn):
            vid = self._add_evidence(source_id, kind, target_id, excerpt, locator)
            self.audit("evidence.create", kind, target_id, source_id)
        return vid

    def remove_evidence(self, vid: str) -> None:
        with Tx(self.conn):
            self.conn.execute("DELETE FROM evidence WHERE id=?", (vid,))
            self.audit("evidence.delete", "evidence", vid)

    def evidence_for(self, kind: str, target_id: str) -> list[dict[str, Any]]:
        return self._all(
            "SELECT v.*, s.title, s.url, s.reliability, s.is_discredited, s.kind AS source_kind"
            " FROM evidence v JOIN source s ON s.id=v.source_id"
            " WHERE v.target_kind=? AND v.target_id=? ORDER BY v.created_at",
            (kind, target_id),
        )

    def source_usages(self, sid: str) -> list[dict[str, Any]]:
        return self._all(
            "SELECT v.*, CASE v.target_kind"
            "  WHEN 'claim' THEN (SELECT e.display_name || ' — ' || f.label FROM claim c"
            "     JOIN entity e ON e.id=c.subject_id JOIN field_def f ON f.id=c.field_def_id WHERE c.id=v.target_id)"
            "  WHEN 'relation' THEN (SELECT s.display_name || ' ' || rt.label || ' ' || t.display_name"
            "     FROM relation r JOIN relation_type rt ON rt.id=r.type_id JOIN entity s ON s.id=r.source_id"
            "     JOIN entity t ON t.id=r.target_id WHERE r.id=v.target_id)"
            "  ELSE (SELECT display_name FROM entity WHERE id=v.target_id) END AS label,"
            " CASE v.target_kind WHEN 'claim' THEN (SELECT subject_id FROM claim WHERE id=v.target_id)"
            "  WHEN 'relation' THEN (SELECT source_id FROM relation WHERE id=v.target_id)"
            "  ELSE v.target_id END AS entity_id"
            " FROM evidence v WHERE v.source_id=? ORDER BY v.created_at DESC",
            (sid,),
        )

    # ================================================================ busca
    _FILTER = re.compile(r"\b(tipo|tag|status):(\S+)", re.I)

    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """Busca FTS5 com prefixo, frase exata, exclusão e filtros tipo:/tag:."""
        filters = {k.lower(): v for k, v in self._FILTER.findall(query)}
        text = self._FILTER.sub(" ", query).strip()
        where, params = ["e.record_status='active'"], []
        if "tipo" in filters:
            t = self.find_type_by_label(filters["tipo"])
            where.append("e.type_id=?")
            params.append(t["id"] if t else "-")
        if "tag" in filters:
            where.append("e.id IN (SELECT et.entity_id FROM entity_tag et JOIN tag t ON t.id=et.tag_id"
                         " WHERE t.path=? OR t.path LIKE ?)")
            params += [filters["tag"], f"{filters['tag']}/%"]
        base = (
            "SELECT e.id, e.display_name, e.summary, t.label AS type_label, t.key AS type_key,"
            " coalesce(e.color, t.color) AS effective_color{snippet}"
            " FROM entity e JOIN entity_type t ON t.id=e.type_id {join}"
            " WHERE {where} ORDER BY {order} LIMIT ?"
        )
        match = self._fts_query(text)
        if match:
            sql = base.format(
                snippet=", snippet(entity_fts, 3, '[', ']', '…', 12) AS snippet",
                join="JOIN entity_fts f ON f.entity_id=e.id",
                where=" AND ".join(["entity_fts MATCH ?", *where]),
                order="bm25(entity_fts, 0, 10.0, 5.0, 1.0)",
            )
            return self._all(sql, (match, *params, limit))
        if filters:
            sql = base.format(snippet=", '' AS snippet", join="", where=" AND ".join(where),
                              order="e.display_name_norm")
            return self._all(sql, (*params, limit))
        return []

    @staticmethod
    def _fts_query(text: str) -> str:
        parts: list[str] = []
        for phrase in re.findall(r'"([^"]+)"', text):
            parts.append('"' + phrase.replace('"', "") + '"')
        text = re.sub(r'"[^"]*"', " ", text)
        for tok in text.split():
            neg = tok.startswith("-") and len(tok) > 1
            word = re.sub(r"[^\w*]", "", tok.lstrip("-"), flags=re.UNICODE).rstrip("*")
            if not word:
                continue
            term = f'"{word}"*'
            parts.append(f"NOT {term}" if neg else term)
        if parts and parts[0].startswith("NOT "):
            return ""  # FTS5 não aceita consulta só negativa
        return " ".join(parts)

    # =========================================================== duplicatas
    def find_duplicates(
        self,
        name: str,
        type_id: str | None = None,
        identifiers: list[tuple[str, str]] | None = None,
        exclude_id: str | None = None,
    ) -> list[DuplicateCandidate]:
        norm = normalize_name(name)
        if not norm:
            return []
        found: dict[str, DuplicateCandidate] = {}
        decided = {
            (r["entity_a"], r["entity_b"])
            for r in self._all("SELECT entity_a, entity_b FROM dedupe_decision WHERE decision='different'")
        }

        def consider(eid: str, display: str, other_norm: str, *, ident: bool = False, alias: bool = False) -> None:
            if eid == exclude_id:
                return
            if exclude_id and (tuple(sorted((eid, exclude_id))) in decided):
                return
            score, reasons = score_duplicate(norm, other_norm, same_identifier=ident, alias_match=alias)
            prev = found.get(eid)
            if prev is None or score > prev.score:
                found[eid] = DuplicateCandidate(eid, display, score, reasons)

        for scheme, value in identifiers or []:
            v = normalize_identifier(scheme, value)
            for r in self._all(
                "SELECT e.id, e.display_name, e.display_name_norm FROM entity_identifier i"
                " JOIN entity e ON e.id=i.entity_id WHERE i.scheme=? AND i.value_norm=?"
                " AND e.record_status!='trashed'", (scheme, v)):
                consider(r["id"], r["display_name"], r["display_name_norm"], ident=True)

        block = norm[:3]
        type_sql, tparams = ("AND e.type_id=?", (type_id,)) if type_id else ("", ())
        for r in self._all(
            "SELECT e.id, e.display_name, e.display_name_norm FROM entity e WHERE e.record_status!='trashed'"
            f" AND (e.display_name_norm LIKE ? OR e.display_name_norm = ?) {type_sql} LIMIT 500",
            (f"{block}%", norm, *tparams)):
            consider(r["id"], r["display_name"], r["display_name_norm"])
        for r in self._all(
            "SELECT e.id, e.display_name, e.display_name_norm FROM entity_alias a JOIN entity e ON e.id=a.entity_id"
            f" WHERE a.alias_norm=? AND e.record_status!='trashed' {type_sql}", (norm, *tparams)):
            consider(r["id"], r["display_name"], r["display_name_norm"], alias=True)
        return sorted((c for c in found.values() if c.score >= DUPLICATE_THRESHOLD),
                      key=lambda c: -c.score)

    def record_dedupe_decision(self, a: str, b: str, decision: str) -> None:
        x, y = sorted((a, b))
        with Tx(self.conn):
            self.conn.execute(
                "INSERT INTO dedupe_decision(entity_a, entity_b, decision, decided_at) VALUES (?,?,?,?)"
                " ON CONFLICT(entity_a, entity_b) DO UPDATE SET decision=excluded.decision,"
                " decided_at=excluded.decided_at",
                (x, y, decision, now_iso()),
            )
            self.audit("dedupe.decision", "entity", x, f"{y}: {decision}")

    def scan_duplicates(self, limit: int = 200) -> list[tuple[dict[str, Any], DuplicateCandidate]]:
        pairs, seen = [], set()
        for e in self._all("SELECT id, display_name, type_id FROM entity WHERE record_status='active'"):
            ids = [(r["scheme"], r["value_norm"]) for r in self._all(
                "SELECT scheme, value_norm FROM entity_identifier WHERE entity_id=?", (e["id"],))]
            for c in self.find_duplicates(e["display_name"], e["type_id"], ids, exclude_id=e["id"]):
                key = tuple(sorted((e["id"], c.entity_id)))
                if key not in seen:
                    seen.add(key)
                    pairs.append((e, c))
            if len(pairs) >= limit:
                break
        return pairs

    def merge_entities(self, keep_id: str, remove_id: str) -> str:
        """Une `remove_id` em `keep_id`. Devolve o ID da revisão que permite desfazer."""
        if keep_id == remove_id:
            raise NexusError("Escolha duas entidades diferentes.")
        keep, gone = self.get_entity(keep_id), self.get_entity(remove_id)
        record: dict[str, Any] = {"keep": keep_id, "removed": remove_id, "removed_name": gone["display_name"]}
        with Tx(self.conn):
            rels = self._all("SELECT id, source_id, target_id FROM relation WHERE source_id=? OR target_id=?",
                             (remove_id, remove_id))
            record["relations"] = rels
            self_loops = []
            for r in rels:
                src = keep_id if r["source_id"] == remove_id else r["source_id"]
                dst = keep_id if r["target_id"] == remove_id else r["target_id"]
                if src == dst:
                    self_loops.append(r["id"])
                    self.conn.execute("UPDATE relation SET record_status='trashed' WHERE id=?", (r["id"],))
                    # Mantém origem/destino para que o desfazer funcione.
                    continue
                self.conn.execute("UPDATE relation SET source_id=?, target_id=?, version=version+1 WHERE id=?",
                                  (src, dst, r["id"]))
            record["self_loops"] = self_loops
            record["claims"] = [r["id"] for r in self._all("SELECT id FROM claim WHERE subject_id=?", (remove_id,))]
            self.conn.execute("UPDATE claim SET subject_id=? WHERE subject_id=?", (keep_id, remove_id))
            record["value_refs"] = [r["id"] for r in self._all(
                "SELECT id FROM claim WHERE value_entity_id=?", (remove_id,))]
            self.conn.execute("UPDATE claim SET value_entity_id=? WHERE value_entity_id=?", (keep_id, remove_id))
            record["aliases"] = [r["id"] for r in self._all("SELECT id FROM entity_alias WHERE entity_id=?", (remove_id,))]
            self.conn.execute("UPDATE entity_alias SET entity_id=? WHERE entity_id=?", (keep_id, remove_id))
            existing_alias = {a["alias_norm"] for a in keep["aliases"]}
            if normalize_name(gone["display_name"]) not in existing_alias | {keep["display_name_norm"]}:
                alias_id = new_ulid()
                self.conn.execute(
                    "INSERT INTO entity_alias(id, entity_id, alias, alias_norm) VALUES (?,?,?,?)",
                    (alias_id, keep_id, gone["display_name"], normalize_name(gone["display_name"])))
                record["added_alias"] = alias_id
            record["identifiers"] = [r["id"] for r in self._all(
                "SELECT id FROM entity_identifier WHERE entity_id=?", (remove_id,))]
            self.conn.execute("UPDATE entity_identifier SET entity_id=? WHERE entity_id=?", (keep_id, remove_id))
            record["evidence"] = [r["id"] for r in self._all(
                "SELECT id FROM evidence WHERE target_kind='entity' AND target_id=?", (remove_id,))]
            self.conn.execute("UPDATE evidence SET target_id=? WHERE target_kind='entity' AND target_id=?",
                              (keep_id, remove_id))
            moved_tags = [r["tag_id"] for r in self._all(
                "SELECT tag_id FROM entity_tag WHERE entity_id=? AND tag_id NOT IN"
                " (SELECT tag_id FROM entity_tag WHERE entity_id=?)", (remove_id, keep_id))]
            record["tags"] = moved_tags
            for tid in moved_tags:
                self.conn.execute("INSERT INTO entity_tag(entity_id, tag_id) VALUES (?,?)", (keep_id, tid))
            self.conn.execute(
                "UPDATE entity SET record_status='trashed', trashed_at=?, version=version+1 WHERE id=?",
                (now_iso(), remove_id))
            self.record_dedupe_decision_inner(keep_id, remove_id, "same")
            self._touch(keep_id)
            self._reindex(remove_id)
            rev_id = new_ulid()
            self.conn.execute(
                "INSERT INTO revision(id, object_kind, object_id, version, snapshot_json, changed_at, change_kind)"
                " VALUES (?,?,?,?,?,?,?)",
                (rev_id, "entity", keep_id, 0, json.dumps(record), now_iso(), "merge"))
            self.audit("entity.merge", "entity", keep_id, f"{gone['display_name']} → {keep['display_name']}")
        return rev_id

    def record_dedupe_decision_inner(self, a: str, b: str, decision: str) -> None:
        x, y = sorted((a, b))
        self.conn.execute(
            "INSERT INTO dedupe_decision(entity_a, entity_b, decision, decided_at) VALUES (?,?,?,?)"
            " ON CONFLICT(entity_a, entity_b) DO UPDATE SET decision=excluded.decision",
            (x, y, decision, now_iso()))

    def undo_merge(self, revision_id: str) -> None:
        rev = self._one("SELECT * FROM revision WHERE id=? AND change_kind='merge'", (revision_id,))
        if not rev:
            raise NexusError("Mesclagem não encontrada.")
        rec = json.loads(rev["snapshot_json"])
        keep, removed = rec["keep"], rec["removed"]
        with Tx(self.conn):
            for r in rec["relations"]:
                self.conn.execute(
                    "UPDATE relation SET source_id=?, target_id=?, version=version+1 WHERE id=?",
                    (r["source_id"], r["target_id"], r["id"]))
            for rid in rec.get("self_loops", []):
                self.conn.execute("UPDATE relation SET record_status='active' WHERE id=?", (rid,))
            self._move_ids("claim", "subject_id", rec["claims"], removed)
            self._move_ids("claim", "value_entity_id", rec["value_refs"], removed)
            self._move_ids("entity_alias", "entity_id", rec["aliases"], removed)
            self._move_ids("entity_identifier", "entity_id", rec["identifiers"], removed)
            self._move_ids("evidence", "target_id", rec["evidence"], removed)
            for tid in rec["tags"]:
                self.conn.execute("DELETE FROM entity_tag WHERE entity_id=? AND tag_id=?", (keep, tid))
            if rec.get("added_alias"):
                self.conn.execute("DELETE FROM entity_alias WHERE id=?", (rec["added_alias"],))
            self.conn.execute(
                "UPDATE entity SET record_status='active', trashed_at=NULL, version=version+1 WHERE id=?",
                (removed,))
            x, y = sorted((keep, removed))
            self.conn.execute("DELETE FROM dedupe_decision WHERE entity_a=? AND entity_b=?", (x, y))
            self.conn.execute("UPDATE revision SET change_kind='merge_undone' WHERE id=?", (revision_id,))
            self._touch(keep)
            self._touch(removed)
            self.audit("entity.unmerge", "entity", keep, removed)

    def _move_ids(self, table: str, column: str, ids: list[str], value: str) -> None:
        for chunk in range(0, len(ids), 500):
            part = ids[chunk:chunk + 500]
            marks = ",".join("?" * len(part))
            self.conn.execute(f"UPDATE {table} SET {column}=? WHERE id IN ({marks})", (value, *part))  # noqa: S608

    def last_merge_revision(self, keep_id: str) -> str | None:
        row = self._one(
            "SELECT id FROM revision WHERE object_id=? AND change_kind='merge' ORDER BY changed_at DESC, rowid DESC LIMIT 1",
            (keep_id,))
        return row["id"] if row else None

    # ============================================================ histórico
    def restore_entity_revision(self, revision_id: str) -> None:
        rev = self._one("SELECT * FROM revision WHERE id=? AND object_kind='entity'", (revision_id,))
        if not rev or rev["change_kind"] in {"merge", "merge_undone"}:
            raise NexusError("Revisão não pode ser restaurada.")
        snap = json.loads(rev["snapshot_json"])
        current = self._one("SELECT version FROM entity WHERE id=?", (rev["object_id"],))
        if not current:
            raise NexusError("A entidade foi excluída definitivamente.")
        changes = {k: snap[k] for k in ("display_name", "summary", "description_md", "private_note",
                                         "color", "icon", "importance", "is_favorite", "type_id") if k in snap}
        self.update_entity(rev["object_id"], current["version"], **changes)
        status = snap.get("record_status", "active")
        if status != "trashed":
            self.set_entity_status(rev["object_id"], status)

    # ================================================================ grafo
    def graph_data(
        self,
        *,
        center_id: str | None = None,
        depth: int = 1,
        type_ids: list[str] | None = None,
        statuses: list[str] | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Nós e arestas para o grafo. Com `center_id`, vizinhança de até `depth` saltos."""
        rel_where, rparams = ["r.record_status='active'"], []
        if statuses:
            rel_where.append(f"r.epistemic_status IN ({','.join('?' * len(statuses))})")
            rparams += statuses
        rel_sql = " AND ".join(rel_where)

        if center_id:
            ids = {center_id}
            frontier = {center_id}
            for _ in range(max(1, depth)):
                if not frontier or len(ids) >= limit:
                    break
                marks = ",".join("?" * len(frontier))
                rows = self._all(
                    f"SELECT source_id, target_id FROM relation r WHERE {rel_sql} AND"  # noqa: S608
                    f" (source_id IN ({marks}) OR target_id IN ({marks}))",
                    (*rparams, *frontier, *frontier))
                nxt = {x for r in rows for x in (r["source_id"], r["target_id"])} - ids
                room = limit - len(ids)
                nxt = set(sorted(nxt)[:room])
                ids |= nxt
                frontier = nxt
            marks = ",".join("?" * len(ids))
            nodes = self._all(
                "SELECT e.id, e.display_name, e.importance, e.type_id, t.label AS type_label, t.key AS type_key,"
                " coalesce(e.color, t.color) AS color FROM entity e JOIN entity_type t ON t.id=e.type_id"
                f" WHERE e.record_status='active' AND e.id IN ({marks})", tuple(ids))  # noqa: S608
        else:
            nodes = self._all(
                "SELECT e.id, e.display_name, e.importance, e.type_id, t.label AS type_label, t.key AS type_key,"
                " coalesce(e.color, t.color) AS color,"
                " (SELECT count(*) FROM relation r WHERE r.record_status='active'"
                "   AND (r.source_id=e.id OR r.target_id=e.id)) AS degree"
                " FROM entity e JOIN entity_type t ON t.id=e.type_id WHERE e.record_status='active'"
                " ORDER BY degree DESC, e.importance DESC, e.updated_at DESC LIMIT ?", (limit,))
        if type_ids:
            nodes = [n for n in nodes if n["type_id"] in type_ids or n["id"] == center_id]
        node_ids = {n["id"] for n in nodes}
        total = self.count_entities()
        if not node_ids:
            return {"nodes": [], "edges": [], "total_entities": total, "truncated": False}
        marks = ",".join("?" * len(node_ids))
        edges = self._all(
            "SELECT r.id, r.source_id, r.target_id, r.epistemic_status, rt.label, rt.directed, rt.color"
            f" FROM relation r JOIN relation_type rt ON rt.id=r.type_id WHERE {rel_sql}"  # noqa: S608
            f" AND r.source_id IN ({marks}) AND r.target_id IN ({marks})",
            (*rparams, *node_ids, *node_ids))
        return {"nodes": nodes, "edges": edges, "total_entities": total,
                "truncated": len(nodes) >= limit and total > len(nodes)}

    def connections(self, eid: str, max_depth: int = 3) -> list[dict[str, Any]]:
        """Vizinhos até `max_depth` saltos com a distância (CTE recursiva)."""
        return self._all(
            "WITH RECURSIVE edges(a, b) AS ("
            "  SELECT source_id, target_id FROM relation WHERE record_status='active'"
            "  UNION ALL SELECT target_id, source_id FROM relation WHERE record_status='active'),"
            " walk(id, depth) AS (SELECT ?, 0 UNION SELECT e.b, w.depth+1 FROM walk w"
            "  JOIN edges e ON e.a=w.id WHERE w.depth < ?)"
            " SELECT x.id, x.display_name, t.label AS type_label, min(w.depth) AS depth"
            " FROM walk w JOIN entity x ON x.id=w.id JOIN entity_type t ON t.id=x.type_id"
            " WHERE w.id != ? AND x.record_status='active' GROUP BY x.id ORDER BY depth, x.display_name_norm",
            (eid, max_depth, eid))

    # ============================================================ painéis
    def stats(self) -> dict[str, Any]:
        one = lambda sql: (self._one(sql) or {"n": 0})["n"]  # noqa: E731
        return {
            "entities": one("SELECT count(*) AS n FROM entity WHERE record_status='active'"),
            "relations": one("SELECT count(*) AS n FROM relation WHERE record_status='active'"),
            "sources": one("SELECT count(*) AS n FROM source WHERE record_status='active'"),
            "claims": one("SELECT count(*) AS n FROM claim"),
            "trashed": one("SELECT count(*) AS n FROM entity WHERE record_status='trashed'"),
            "by_type": self._all(
                "SELECT t.key AS type_key, t.label, count(e.id) AS n FROM entity_type t"
                " LEFT JOIN entity e ON e.type_id=t.id AND e.record_status='active'"
                " GROUP BY t.id HAVING n > 0 ORDER BY n DESC"),
            "by_status": self._all(
                "SELECT epistemic_status, count(*) AS n FROM claim GROUP BY epistemic_status"),
            "recent": self._all(
                "SELECT e.id, e.display_name, t.label AS type_label, t.key AS type_key, e.updated_at FROM entity e"
                " JOIN entity_type t ON t.id=e.type_id WHERE e.record_status='active'"
                " ORDER BY e.updated_at DESC LIMIT 10"),
        }

    def quality(self) -> dict[str, int]:
        one = lambda sql: (self._one(sql) or {"n": 0})["n"]  # noqa: E731
        return {
            "claims_without_source": one(
                "SELECT count(*) AS n FROM claim c JOIN entity e ON e.id=c.subject_id AND e.record_status='active'"
                " WHERE NOT EXISTS (SELECT 1 FROM evidence v WHERE v.target_kind='claim' AND v.target_id=c.id)"),
            "relations_without_source": one(
                "SELECT count(*) AS n FROM relation r WHERE r.record_status='active' AND NOT EXISTS"
                " (SELECT 1 FROM evidence v WHERE v.target_kind='relation' AND v.target_id=r.id)"),
            "orphans": one(
                "SELECT count(*) AS n FROM entity e WHERE e.record_status='active' AND NOT EXISTS"
                " (SELECT 1 FROM relation r WHERE r.record_status='active' AND (r.source_id=e.id OR r.target_id=e.id))"),
            "review_due": one(
                "SELECT count(*) AS n FROM claim WHERE review_at IS NOT NULL AND review_at <= date('now')"),
            "discredited_sources": one(
                "SELECT count(*) AS n FROM source WHERE is_discredited=1 AND record_status='active'"),
        }

    def conflicting_entities(self) -> list[dict[str, Any]]:
        out = []
        rows = self._all(
            "SELECT c.subject_id, c.field_def_id, f.conflict_rule, f.label, count(*) AS n FROM claim c"
            " JOIN field_def f ON f.id=c.field_def_id JOIN entity e ON e.id=c.subject_id"
            " WHERE e.record_status='active' AND f.conflict_rule!='multi'"
            " GROUP BY c.subject_id, c.field_def_id HAVING n > 1")
        for r in rows:
            claims = self._all("SELECT * FROM claim WHERE subject_id=? AND field_def_id=?",
                               (r["subject_id"], r["field_def_id"]))
            if find_conflicts(claims, r["conflict_rule"]):
                e = self._one("SELECT display_name FROM entity WHERE id=?", (r["subject_id"],))
                out.append({"entity_id": r["subject_id"], "display_name": e["display_name"] if e else "?",
                            "field": r["label"]})
        return out

    # ============================================================== notas
    def list_notes(self, query: str = "", entity_id: str | None = None,
                   order: str = "updated") -> list[dict[str, Any]]:
        where, params = ["1=1"], []
        if query.strip():
            like = f"%{query.strip().lower()}%"
            where.append("(lower(n.title) LIKE ? OR lower(n.body) LIKE ?)")
            params += [like, like]
        if entity_id:
            where.append("n.entity_id=?")
            params.append(entity_id)
        order_sql = {"updated": "n.updated_at DESC, n.rowid DESC", "created": "n.created_at DESC, n.rowid DESC",
                     "title": "lower(n.title), n.updated_at DESC"}.get(order, "n.updated_at DESC")
        return self._all(
            "SELECT n.*, e.display_name AS entity_name, substr(n.body, 1, 200) AS preview FROM note n"
            f" LEFT JOIN entity e ON e.id=n.entity_id WHERE {' AND '.join(where)} ORDER BY {order_sql}",  # noqa: S608
            tuple(params))

    def get_note(self, nid: str) -> dict[str, Any]:
        row = self._one("SELECT n.*, e.display_name AS entity_name FROM note n"
                        " LEFT JOIN entity e ON e.id=n.entity_id WHERE n.id=?", (nid,))
        if not row:
            raise NexusError("Nota não encontrada.")
        return row

    def _check_note_entity(self, entity_id: str | None) -> str | None:
        if not entity_id:
            return None
        if not self._one("SELECT id FROM entity WHERE id=?", (entity_id,)):
            raise NexusError("A entidade vinculada não existe mais.")
        return entity_id

    @staticmethod
    def _note_ts() -> str:
        # Microssegundos: o salvamento automático acontece várias vezes no mesmo segundo.
        return datetime.now(UTC).isoformat(timespec="microseconds")

    def create_note(self, title: str = "", body: str = "", entity_id: str | None = None) -> str:
        nid, ts = new_ulid(), self._note_ts()
        with Tx(self.conn):
            self.conn.execute(
                "INSERT INTO note(id, title, body, entity_id, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (nid, title.strip(), body, self._check_note_entity(entity_id), ts, ts))
            self.audit("note.create", "note", nid, title.strip()[:80])
        return nid

    def update_note(self, nid: str, title: str, body: str, entity_id: str | None = None) -> None:
        """Salvamento automático: grava título, texto e vínculo; sem entrada de auditoria a cada tecla."""
        self.get_note(nid)
        self.conn.execute("UPDATE note SET title=?, body=?, entity_id=?, updated_at=? WHERE id=?",
                          (title.strip(), body, self._check_note_entity(entity_id), self._note_ts(), nid))

    def delete_note(self, nid: str) -> None:
        note = self.get_note(nid)
        with Tx(self.conn):
            self.conn.execute("DELETE FROM note WHERE id=?", (nid,))
            self.audit("note.delete", "note", nid, note["title"][:80])

    # ========================================================= fotografias
    def _require_blobs(self) -> BlobStore:
        if self.blobs is None:
            raise NexusError("O armazenamento de arquivos deste projeto não está disponível.")
        return self.blobs

    def _store_image(self, data: bytes, original_name: str) -> str:
        """Valida pelo conteúdo, guarda o arquivo (deduplicado) e devolve o id do attachment."""
        info = inspect_image(data)
        sha = self._require_blobs().put(data)
        row = self._one("SELECT id FROM attachment WHERE sha256=?", (sha,))
        if row:
            return str(row["id"])
        aid = new_ulid()
        name = re.sub(r"[\\/\x00-\x1f]", "_", original_name)[-200:]
        self.conn.execute(
            "INSERT INTO attachment(id, sha256, kind, mime, size, width, height, original_name, has_exif,"
            " has_gps, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (aid, sha, "image", info.mime, len(data), info.width, info.height, name,
             int(info.has_exif), int(info.has_gps), now_iso()))
        return aid

    def add_photo(self, entity_id: str, data: bytes, original_name: str = "") -> str:
        ent = self.get_entity(entity_id)
        if self._one("SELECT p.id FROM entity_photo p JOIN attachment a ON a.id=p.attachment_id"
                     " WHERE p.entity_id=? AND a.sha256=?", (entity_id, hashlib.sha256(data).hexdigest())):
            raise NexusError("Esta imagem já está nas fotografias desta entidade.")
        with Tx(self.conn):
            aid = self._store_image(data, original_name)
            if self._one("SELECT id FROM entity_photo WHERE entity_id=? AND attachment_id=?", (entity_id, aid)):
                raise NexusError("Esta imagem já está nas fotografias desta entidade.")
            pos = self._one("SELECT coalesce(max(position), -1) + 1 AS p FROM entity_photo WHERE entity_id=?",
                            (entity_id,))
            pid = new_ulid()
            self.conn.execute(
                "INSERT INTO entity_photo(id, entity_id, attachment_id, position, created_at) VALUES (?,?,?,?,?)",
                (pid, entity_id, aid, pos["p"] if pos else 0, now_iso()))
            self.audit("photo.add", "entity", entity_id, f"{ent['display_name']}: {original_name}"[:200])
        return pid

    def list_photos(self, entity_id: str) -> list[dict[str, Any]]:
        return self._all(
            "SELECT p.id, p.entity_id, p.position, p.caption, p.created_at, a.id AS attachment_id, a.sha256,"
            " a.mime, a.size, a.width, a.height, a.original_name, a.has_exif, a.has_gps, e.display_name AS entity_name"
            " FROM entity_photo p JOIN attachment a ON a.id=p.attachment_id JOIN entity e ON e.id=p.entity_id"
            " WHERE p.entity_id=? ORDER BY p.position, p.created_at", (entity_id,))

    def get_photo(self, photo_id: str) -> dict[str, Any]:
        row = self._one(
            "SELECT p.*, a.sha256, a.mime, a.original_name FROM entity_photo p"
            " JOIN attachment a ON a.id=p.attachment_id WHERE p.id=?", (photo_id,))
        if not row:
            raise NexusError("Fotografia não encontrada.")
        return row

    def photo_count(self, entity_id: str) -> int:
        row = self._one("SELECT count(*) AS n FROM entity_photo WHERE entity_id=?", (entity_id,))
        return int(row["n"]) if row else 0

    def photo_bytes(self, photo_id: str) -> bytes:
        return self._require_blobs().get(self.get_photo(photo_id)["sha256"])

    def remove_photo(self, photo_id: str) -> None:
        photo = self.get_photo(photo_id)
        with Tx(self.conn):
            self.conn.execute("DELETE FROM entity_photo WHERE id=?", (photo_id,))
            self.audit("photo.remove", "entity", photo["entity_id"], photo["original_name"][:200])
        self._gc_attachments()

    def replace_photo(self, photo_id: str, data: bytes, original_name: str = "") -> None:
        photo = self.get_photo(photo_id)
        with Tx(self.conn):
            aid = self._store_image(data, original_name)
            if aid == photo["attachment_id"]:
                return
            if self._one("SELECT id FROM entity_photo WHERE entity_id=? AND attachment_id=?",
                         (photo["entity_id"], aid)):
                raise NexusError("Esta imagem já está nas fotografias desta entidade.")
            self.conn.execute("UPDATE entity_photo SET attachment_id=? WHERE id=?", (aid, photo_id))
            self.audit("photo.replace", "entity", photo["entity_id"], original_name[:200])
        self._gc_attachments()

    def _gc_attachments(self) -> int:
        """Apaga registros e arquivos de imagens que nenhuma entidade usa mais."""
        orphans = self._all("SELECT id, sha256 FROM attachment WHERE id NOT IN"
                            " (SELECT attachment_id FROM entity_photo)")
        for row in orphans:
            self.conn.execute("DELETE FROM attachment WHERE id=?", (row["id"],))
            if self.blobs is not None:
                self.blobs.delete(row["sha256"])
        if self.blobs is not None:  # arquivos sem registro (ex.: operação interrompida)
            known = {r["sha256"] for r in self._all("SELECT sha256 FROM attachment")}
            for sha in self.blobs.list_shas():
                if sha not in known:
                    self.blobs.delete(sha)
        return len(orphans)

