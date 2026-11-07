"""Nome obrigatório (criação e edição) e exclusão de fonte com desvinculação."""

from __future__ import annotations

import pytest

from nexus_intel.domain.errors import NexusError

BLANKS = ["", "   ", "\t \n"]


@pytest.mark.parametrize("blank", BLANKS)
def test_entity_name_required_on_create_and_edit(store, blank):
    with pytest.raises(NexusError, match="não pode ficar vazio"):
        store.create_entity("person", blank)
    eid = store.create_entity("person", "  Ana  ")
    assert store.get_entity(eid)["display_name"] == "Ana"  # espaços das pontas removidos
    with pytest.raises(NexusError, match="não pode ficar vazio"):
        store.update_entity(eid, 1, display_name=blank)
    assert store.get_entity(eid)["display_name"] == "Ana"


@pytest.mark.parametrize("blank", BLANKS)
def test_source_title_required_on_create_and_edit(store, blank):
    with pytest.raises(NexusError, match="título da fonte"):
        store.create_source(blank)
    sid = store.create_source("  Certidão  ")
    assert store.get_source(sid)["title"] == "Certidão"
    with pytest.raises(NexusError, match="título da fonte"):
        store.update_source(sid, 1, title=blank)
    assert store.get_source(sid)["title"] == "Certidão"


@pytest.mark.parametrize("blank", BLANKS)
def test_project_type_and_field_names_required(manager, store, blank):
    with pytest.raises(NexusError):
        manager.create(blank)
    info = manager.list()[0]
    with pytest.raises(NexusError):
        manager.update_appearance(info.id, blank, info.color)
    with pytest.raises(NexusError):
        store.create_entity_type(blank)
    with pytest.raises(NexusError):
        store.add_field(store.entity_type("person")["id"], blank)


def test_delete_source_unlinks_and_keeps_claims(store):
    p = store.create_entity("person", "Bruno")
    c = store.create_entity("company", "Firma")
    src = store.create_source("Reportagem", kind="news")
    other = store.create_source("Ofício", kind="official")
    claim = store.add_claim(p, "profissao", "Contador", source_id=src)
    store.add_evidence(other, "claim", claim)
    rel = store.create_relation("works_at", p, c, evidence_source=src)

    assert store.source_link_counts(src) == {"claim": 1, "relation": 1, "entity": 0}
    removed = store.delete_source(src)
    assert removed["claim"] == 1 and removed["relation"] == 1

    with pytest.raises(NexusError):
        store.get_source(src)
    assert [s["id"] for s in store.list_sources()] == [other]
    # afirmação e relação continuam; a afirmação mantém a outra fonte
    assert [v["source_id"] for v in store.evidence_for("claim", claim)] == [other]
    assert store.evidence_for("relation", rel) == []
    assert store.relations_for(p)[0]["id"] == rel
    assert store.quality()["relations_without_source"] == 1
    assert store.history("source", src)[0]["change_kind"] == "delete"
    assert store.audit_entries(1)[0]["action"] == "source.delete"
    assert store.verify_audit() is None
