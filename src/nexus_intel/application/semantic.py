"""Busca semântica: encontra entidades pelo significado (ADR-0004).

Cada entidade vira um texto (nome, tipo, outros nomes, resumo, descrição, valores
das afirmações e etiquetas), que um modelo local de vetores (embeddings) transforma
num vetor. Os vetores ficam na tabela `embedding`, dentro do arquivo cifrado do
projeto. A busca compara o vetor da pergunta com todos (cosseno, NumPy).

Privacidade por padrão: observações privadas nunca entram no texto; afirmações
marcadas como sensíveis (saúde, religião...) só entram se `include_sensitive`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from nexus_intel.application.project_store import ProjectStore, now_iso
from nexus_intel.infrastructure.db.connection import Tx

Embedder = Callable[[list[str]], list[list[float]]]
MAX_TEXT = 2000


@dataclass
class SemanticHit:
    entity_id: str
    display_name: str
    type_label: str
    score: float


class SemanticIndex:
    def __init__(self, store: ProjectStore, embed: Embedder, model: str, *, include_sensitive: bool = False) -> None:
        self.store = store
        self.embed = embed
        self.model = model
        self.include_sensitive = include_sensitive

    # ---------------------------------------------------------------- textos
    def entity_text(self, eid: str) -> str:
        e = self.store.get_entity(eid)
        parts = [f"{e['display_name']} ({e['type_label']})"]
        if e["aliases"]:
            parts.append("Outros nomes: " + "; ".join(a["alias"] for a in e["aliases"]))
        for key in ("summary", "description_md"):
            if e.get(key):
                parts.append(str(e[key]))
        sens = "" if self.include_sensitive else " AND c.is_sensitive=0"
        rows = self.store._all(
            "SELECT f.label, c.value_text, c.value_num, c.value_date_start,"  # noqa: S608
            " (SELECT display_name FROM entity x WHERE x.id=c.value_entity_id) AS ent"
            " FROM claim c JOIN field_def f ON f.id=c.field_def_id"
            f" WHERE c.subject_id=? AND c.epistemic_status!='refuted'{sens} ORDER BY f.label", (eid,))
        for r in rows:
            val = r["value_text"] or r["ent"] or r["value_date_start"] or (
                "" if r["value_num"] is None else str(r["value_num"]))
            if val:
                parts.append(f"{r['label']}: {val}")
        if e["tags"]:
            parts.append("Etiquetas: " + ", ".join(e["tags"]))
        return "\n".join(parts)[:MAX_TEXT]

    # ---------------------------------------------------------------- índice
    def pending(self) -> list[str]:
        """Entidades ativas sem vetor deste modelo ou com texto alterado desde a indexação."""
        current = {r["entity_id"]: r["text_sha256"] for r in self.store._all(
            "SELECT entity_id, text_sha256 FROM embedding WHERE model=?", (self.model,))}
        out = []
        for r in self.store._all("SELECT id FROM entity WHERE record_status='active' ORDER BY updated_at"):
            sha = hashlib.sha256(self.entity_text(r["id"]).encode("utf-8")).hexdigest()
            if current.get(r["id"]) != sha:
                out.append(r["id"])
        return out

    def indexed_count(self) -> int:
        row = self.store._one(
            "SELECT count(*) AS n FROM embedding v JOIN entity e ON e.id=v.entity_id"
            " WHERE v.model=? AND e.record_status='active'", (self.model,))
        return int(row["n"]) if row else 0

    def update(self, ids: list[str] | None = None, batch: int = 16,
               progress: Callable[[int, int], Any] | None = None) -> int:
        """(Re)indexa as entidades pendentes. Devolve quantas foram gravadas."""
        todo = self.pending() if ids is None else ids
        done = 0
        for i in range(0, len(todo), batch):
            chunk = todo[i:i + batch]
            self.store_vectors(chunk, self.embed([self.entity_text(eid) for eid in chunk]))
            done += len(chunk)
            if progress:
                progress(done, len(todo))
        return done

    def store_vectors(self, ids: list[str], vectors: list[list[float]]) -> None:
        """Grava vetores já calculados (o cálculo pode ter rodado em outra thread)."""
        if len(vectors) != len(ids):
            raise ValueError("o modelo de vetores devolveu uma quantidade diferente de vetores")
        with Tx(self.store.conn):
            for eid, vec in zip(ids, vectors, strict=True):
                txt = self.entity_text(eid)
                arr = _unit(np.asarray(vec, dtype=np.float32))
                self.store.conn.execute(
                    "INSERT INTO embedding(entity_id, model, dim, text_sha256, vector, updated_at)"
                    " VALUES (?,?,?,?,?,?) ON CONFLICT(entity_id, model) DO UPDATE SET"
                    " dim=excluded.dim, text_sha256=excluded.text_sha256, vector=excluded.vector,"
                    " updated_at=excluded.updated_at",
                    (eid, self.model, int(arr.size), hashlib.sha256(txt.encode("utf-8")).hexdigest(),
                     arr.tobytes(), now_iso()))

    # ----------------------------------------------------------------- busca
    def search(self, query: str, k: int = 10, min_score: float = 0.2) -> list[SemanticHit]:
        query = query.strip()
        if not query or not self.indexed_count():
            return []
        return self.search_vector(self.embed([query])[0], k, min_score)

    def search_vector(self, vector: list[float], k: int = 10, min_score: float = 0.2) -> list[SemanticHit]:
        rows = self.store._all(
            "SELECT v.entity_id, v.dim, v.vector, e.display_name, t.label AS type_label FROM embedding v"
            " JOIN entity e ON e.id=v.entity_id JOIN entity_type t ON t.id=e.type_id"
            " WHERE v.model=? AND e.record_status='active'", (self.model,))
        if not rows:
            return []
        q = _unit(np.asarray(vector, dtype=np.float32))
        rows = [r for r in rows if r["dim"] == q.size]
        if not rows:
            return []
        mat = np.vstack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
        scores = mat @ q
        order = np.argsort(-scores)[:k]
        return [SemanticHit(rows[i]["entity_id"], rows[i]["display_name"], rows[i]["type_label"],
                            float(scores[i])) for i in order if scores[i] >= min_score]


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v
