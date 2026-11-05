from __future__ import annotations

import sqlite3

import pytest

from nexus_intel.application.project_store import ConcurrentEdit
from nexus_intel.application.projects import ProjectManager
from nexus_intel.application.session import Session
from nexus_intel.domain.errors import NexusError, ProjectLocked, SessionLocked
from tests.conftest import FAST_KDF, PASSWORD, requires_sqlcipher


def test_example_project_scenario(manager):
    info = manager.create("Exemplo", template="example")
    s = manager.open(info.id)
    joao = s.search("joao")[0]
    assert "João" in joao["display_name"]
    rels = s.relations_for(joao["id"])
    assert {r["phrase"] for r in rels} == {"possui", "trabalha em"}
    # Veneza alcançável a 2 saltos (João → veículo → Veneza), sem relação gravada direta.
    near = {c["display_name"]: c["depth"] for c in s.connections(joao["id"])}
    assert near["Veneza"] == 2
    groups = {g.field_def["key"]: g for g in s.claims_for(joao["id"])}
    assert groups["nascimento"].has_conflict
    assert len(groups["nascimento"].claims) == 2
    assert s.verify_audit() is None


def test_isolation_between_projects(manager):
    a = manager.create("A")
    b = manager.create("B")
    sa = manager.open(a.id)
    sa.create_entity("person", "Maria Teste")
    sb = manager.open(b.id)
    assert sb.search("maria") == []
    sb.create_entity("person", "Maria Teste")
    assert len(sb.search("maria")) == 1
    assert len(sb.list_entities()) == 1


def test_single_instance_lock(manager, session):
    info = manager.create("Travado")
    manager.open(info.id)
    other = ProjectManager(session)
    with pytest.raises(ProjectLocked):
        other.open(info.id)


def test_lock_closes_everything(session, manager):
    info = manager.create("X")
    manager.open(info.id)
    session.lock()
    assert manager.current is None
    with pytest.raises(SessionLocked):
        _ = session.master
    session.login("arthur", PASSWORD)
    assert [p.name for p in manager.list()] == ["X"]


def test_recovery_login_requires_new_password(paths):
    s = Session(paths, kdf_params=FAST_KDF)
    rk = s.setup("arthur", PASSWORD, encrypt=Session.encryption_supported())
    s.lock()
    s.login_with_recovery(rk)
    assert s.must_change_password
    s.set_new_password("nova-senha-segura-2026")
    s.lock()
    s.login("arthur", "nova-senha-segura-2026")
    s.lock()


def test_crud_trash_restore_purge(store):
    eid = store.create_entity("company", "Empresa Alfa", summary="teste")
    e = store.get_entity(eid)
    v = store.update_entity(eid, e["version"], summary="novo resumo", importance=5)
    with pytest.raises(ConcurrentEdit):
        store.update_entity(eid, e["version"], summary="concorrente")
    store.trash_entity(eid)
    assert store.list_entities() == []
    assert store.search("alfa") == []
    assert store.count_entities("trashed") == 1
    store.restore_entity(eid)
    assert store.get_entity(eid)["version"] > v
    assert store.search("alfa")[0]["id"] == eid
    store.trash_entity(eid)
    store.delete_entity_permanently(eid)
    with pytest.raises(NexusError):
        store.get_entity(eid)


def test_purge_requires_trash(store):
    eid = store.create_entity("person", "Fulano")
    with pytest.raises(NexusError):
        store.delete_entity_permanently(eid)


def test_revision_restore(store):
    eid = store.create_entity("person", "Nome Original")
    first = store.history("entity", eid)[-1]["id"]
    store.update_entity(eid, 1, display_name="Nome Errado")
    store.restore_entity_revision(first)
    assert store.get_entity(eid)["display_name"] == "Nome Original"


def test_claims_typed_and_evidence(store):
    p = store.create_entity("person", "Ana")
    src = store.create_source("Certidão", kind="official", reliability="A")
    cid = store.add_claim(p, "nascimento", "15/03/1990", source_id=src, excerpt="nasc. 15/03/1990")
    g = {g.field_def["key"]: g for g in store.claims_for(p)}["nascimento"]
    cv = g.claims[0]
    assert cv.display_value == "15/03/1990" and cv.evidence_count == 1
    assert cv.row["epistemic_status"] == "reported"
    store.update_source(src, 1, is_discredited=1)
    cv = {g.field_def["key"]: g for g in store.claims_for(p)}["nascimento"].claims[0]
    assert cv.only_discredited
    with pytest.raises(NexusError):
        store.add_claim(p, "email", "nao-e-email")
    store.delete_claim(cid)
    assert store.quality()["claims_without_source"] == 0


def test_duplicates_and_merge_undo(store):
    a = store.create_entity("person", "João Silva", identifiers=[("cpf", "529.982.247-25")])
    b = store.create_entity("person", "Joao  Silva")
    c = store.create_entity("company", "Firma")
    store.create_relation("works_at", b, c, evidence_source=store.create_source("Fonte"))
    store.create_relation("knows", a, b)
    store.set_tags(b, ["pessoas/alvo"])
    store.add_claim(b, "email", "joao@exemplo.com")
    cands = store.find_duplicates("JOÃO SILVA", store.entity_type("person")["id"])
    assert {x.entity_id for x in cands} == {a, b}
    by_cpf = store.find_duplicates("Outro Nome", None, [("cpf", "52998224725")])
    assert by_cpf[0].entity_id == a and by_cpf[0].score == 100

    rev = store.merge_entities(a, b)
    merged = store.get_entity(a)
    assert merged["aliases"] == []  # grafia equivalente não vira apelido redundante
    assert "pessoas/alvo" in merged["tags"]
    assert [r["other_id"] for r in store.relations_for(a)] == [c]  # laço a–b removido
    assert any(g.claims for g in store.claims_for(a) if g.field_def["key"] == "email")

    store.undo_merge(rev)
    assert store.get_entity(b)["record_status"] == "active"
    assert {r["other_id"] for r in store.relations_for(b)} == {a, c}
    assert store.get_entity(a)["tags"] == []
    assert not any(g.claims for g in store.claims_for(a) if g.field_def["key"] == "email")
    assert store.verify_audit() is None


def test_dedupe_decision_suppresses(store):
    a = store.create_entity("person", "Carlos Lima")
    b = store.create_entity("person", "Carlos Lima")
    store.record_dedupe_decision(a, b, "different")
    assert store.find_duplicates("Carlos Lima", exclude_id=a) == []


def test_search_syntax(store):
    store.create_entity("person", "Beatriz Ávila", summary="analista de investimentos")
    store.create_entity("company", "Ávila Investimentos")
    assert len(store.search("avila")) == 2
    assert len(store.search("invest*")) == 2
    assert len(store.search("avila tipo:pessoa")) == 1
    assert len(store.search("avila -beatriz")) == 1
    assert len(store.search('"analista de investimentos"')) == 1


def test_quick_capture(store):
    eid = store.quick_capture("Pedro Alves · pessoa")
    assert store.get_entity(eid)["type_key"] == "person"
    eid2 = store.quick_capture("Silva, Pedro")
    e2 = store.get_entity(eid2)
    assert e2["display_name"] == "Silva, Pedro" and e2["type_key"] == "other"


def test_graph_limit_and_neighborhood(store):
    hub = store.create_entity("person", "Centro")
    ids = [store.create_entity("person", f"N{i}") for i in range(30)]
    for i in ids:
        store.create_relation("knows", hub, i)
    g = store.graph_data(limit=10)
    assert len(g["nodes"]) == 10 and g["truncated"]
    local = store.graph_data(center_id=ids[0], depth=1)
    assert {n["id"] for n in local["nodes"]} == {ids[0], hub}


def test_audit_tamper_detected(store):
    store.create_entity("person", "Teste")
    store.conn.execute("UPDATE audit_log SET summary='alterado' WHERE seq=2")
    assert store.verify_audit() == 2


def test_relation_requires_distinct(store):
    a = store.create_entity("person", "Só")
    with pytest.raises(NexusError):
        store.create_relation("knows", a, a)


@requires_sqlcipher
def test_encrypted_files_unreadable_without_key(manager, session):
    info = manager.create("Cifrado")
    s = manager.open(info.id)
    s.create_entity("person", "Segredo Absoluto")
    manager.close_current()
    raw = info.path.read_bytes()
    assert b"Segredo Absoluto" not in raw and b"SQLite format 3" not in raw[:16]
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(info.path).execute("SELECT * FROM entity").fetchall()
    assert b"SQLite format 3" not in session.paths.app_db.read_bytes()[:16]
