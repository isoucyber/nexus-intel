"""A linha do tempo usa só dados reais existentes (sem consultas novas no backend)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")  # o módulo fica na camada de interface

from nexus_intel.ui.timeline_page import RELATION_END, RELATION_START, collect_events  # noqa: E402


def test_events_come_from_dated_claims_and_relation_validity(store):
    ana = store.create_entity("person", "Ana Teste")
    acme = store.create_entity("company", "Acme Teste")
    src = store.create_source("Certidão", kind="official", reliability="A")
    store.add_claim(ana, "nascimento", "15/03/1990", source_id=src)
    store.add_claim(acme, "fundacao", "2001")
    store.add_claim(ana, "profissao", "Contadora")  # não é data: não entra
    store.create_relation("works_at", ana, acme, valid_from="2015-02", valid_to="2019",
                          evidence_source=src)
    store.create_relation("knows", ana, acme, valid_from="na época da faculdade")  # texto livre: ignorado

    events = collect_events(store)
    assert [(e.when.display(), e.kind) for e in events] == [
        ("15/03/1990", "Data de nascimento"),
        ("2001", "Data de fundação"),
        ("fev/2015", RELATION_START),
        ("2019", RELATION_END),
    ]
    assert events[0].evidence_count == 1 and events[0].entity_id == ana
    assert events[2].target_kind == "relation" and events[2].other_id == acme


def test_trashed_entities_do_not_appear(store):
    e = store.create_entity("person", "Lixo")
    store.add_claim(e, "nascimento", "1970")
    store.trash_entity(e)
    assert collect_events(store) == []
