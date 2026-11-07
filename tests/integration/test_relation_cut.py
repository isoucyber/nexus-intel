"""Cortar, restaurar e excluir relações sem apagar entidades nem deixar órfãos."""

from __future__ import annotations

import pytest

from nexus_intel.domain.errors import NexusError


@pytest.fixture
def rel(store):
    a = store.create_entity("person", "Helena")
    b = store.create_entity("company", "Aurora")
    src = store.create_source("Ficha cadastral")
    rid = store.create_relation("works_at", a, b, evidence_source=src)
    return store, a, b, rid


def test_cut_moves_to_trash_and_keeps_entities(rel):
    store, a, b, rid = rel
    store.cut_relation(rid)
    assert store.relations_for(a) == [] and store.relations_for(b) == []
    assert store.get_entity(a)["record_status"] == "active"
    assert store.get_entity(b)["record_status"] == "active"
    trashed = store.list_trashed_relations()
    assert [r["phrase"] for r in trashed] == ["Helena trabalha em Aurora"]
    assert store.graph_data()["edges"] == []
    assert len(store.graph_data()["nodes"]) == 2  # as duas entidades seguem no grafo
    store.cut_relation(rid)  # repetir não quebra


def test_restore_brings_relation_back(rel):
    store, a, _b, rid = rel
    store.cut_relation(rid)
    store.restore_relation(rid)
    assert [r["id"] for r in store.relations_for(a)] == [rid]
    assert store.list_trashed_relations() == []


def test_permanent_delete_requires_cut_and_leaves_no_orphans(rel):
    store, a, b, rid = rel
    with pytest.raises(NexusError, match="Corte a relação"):
        store.delete_relation_permanently(rid)
    store.cut_relation(rid)
    store.delete_relation_permanently(rid)
    assert store.conn.execute("SELECT count(*) AS n FROM relation WHERE id=?", (rid,)).fetchone()["n"] == 0
    orphans = store.conn.execute(
        "SELECT count(*) AS n FROM evidence WHERE target_kind='relation' AND target_id=?", (rid,)).fetchone()["n"]
    assert orphans == 0
    assert store.get_entity(a) and store.get_entity(b)
    assert store.list_sources()  # a fonte continua; só o vínculo saiu
    with pytest.raises(NexusError):
        store.get_relation(rid)
    actions = [e["action"] for e in store.audit_entries(5)]
    assert "relation.purge" in actions and "relation.trashed" in actions
    assert store.verify_audit() is None


def test_empty_trash_counts_relations(rel):
    store, _a, _b, rid = rel
    store.cut_relation(rid)
    assert store.empty_trash() == 1
    assert store.list_trashed_relations() == []
