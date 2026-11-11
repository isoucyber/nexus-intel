"""Testes de segurança da 0.3.4 (hardening): injeção, reautenticação, registros, repetição, vazamentos."""

from __future__ import annotations

import io
import json
import os
import tempfile

import pytest

from nexus_intel.application.projects import ProjectManager
from nexus_intel.application.sharing import export_project, import_package, preview_package
from nexus_intel.domain.errors import (
    InvalidCredentials,
    PackageError,
    ProjectNotFound,
    ReauthRequired,
)
from nexus_intel.infrastructure.crypto.keys import KdfParams
from nexus_intel.infrastructure.package import container
from tests.conftest import PASSWORD, requires_sqlcipher
from tests.imagefactory import make_image

KDF = KdfParams(memory_kib=8 * 1024, iterations=1, lanes=1)
PKG_PW = "senha-do-pacote-segura"
SECRET = "Investigado Confidencial Omega"


def _expire_auth(session):
    session._auth_at = session._clock() - 10_000


# ------------------------------------------------------------ SQL injection
INJECTIONS = ["'; DROP TABLE entity; --", "\" OR 1=1 --", "x') UNION SELECT sqlite_version() --",
              "%' OR '1'='1", "*", "NEAR(a b)", "a\x00b", "' OR 1=1; DELETE FROM note; --"]


def test_sql_injection_payloads_are_plain_data(store):
    eid = store.create_entity("person", INJECTIONS[0])
    store.create_note(INJECTIONS[1], INJECTIONS[2], entity_id=eid)
    for payload in INJECTIONS:
        store.search(payload)
        store.list_entities(tag=payload, order=payload)
        store.list_notes(payload)
        store.list_sources(payload)
        store.find_duplicates(payload, None)
        store.list_notes(order=payload)  # ordem desconhecida cai no padrão, nunca vai para o SQL
    tables = {r["name"] for r in store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"entity", "note", "relation"} <= tables
    assert store.get_entity(eid)["display_name"] == INJECTIONS[0]
    assert len(store.list_notes()) == 1


def test_identifier_manipulation_is_rejected(manager):
    for bad in ("../outro", "..\\..\\x", "01ABC", "", "C:/Windows/System32"):
        with pytest.raises(ProjectNotFound):
            manager.get(bad)
        with pytest.raises(ProjectNotFound):
            manager.open(bad)


# ------------------------------------------------------- reautenticação
def test_sensitive_operations_require_recent_password(manager, store, tmp_path):
    session = manager.session
    _expire_auth(session)
    with pytest.raises(ReauthRequired):
        export_project(manager, store, tmp_path / "x.nexus", PKG_PW, KDF)
    with pytest.raises(ReauthRequired):
        session.rotate_recovery_key()
    with pytest.raises(ReauthRequired):
        session.rotate_identity()
    info = manager.create("Outro")
    with pytest.raises(ReauthRequired):
        manager.delete(info.id)
    with pytest.raises(InvalidCredentials):
        session.verify_password("senha-errada-qualquer")
    session.vault._clock = lambda: 1e12  # pula o atraso progressivo
    session.verify_password(PASSWORD)
    manager.delete(info.id)
    old = session.fingerprint()
    assert session.rotate_identity() != old
    kinds = [e["kind"] for e in session.security_events()]
    assert {"reauth.fail", "reauth.ok", "project.delete", "identity.rotate"} <= set(kinds)


# ------------------------------------------------- registro de segurança
def test_security_log_is_chained_and_tamper_evident(session):
    session.security_event("teste", "evento 1")
    session.security_event("teste", "evento 2")
    assert session.verify_security_log() is None
    row = session.security_events(1)[0]
    session.app_db.execute("UPDATE security_event SET detail='apagado' WHERE seq=?", (row["seq"],))
    assert session.verify_security_log() == row["seq"]


def test_failed_attempts_are_reported_on_next_login(session):
    user = session.username
    session.lock()
    for i in range(2):
        session.vault._clock = lambda i=i: 1e12 + 1000 * i  # sem esperar o atraso entre tentativas
        with pytest.raises(InvalidCredentials):
            session.login(user, "senha-errada-123456")
    session.vault._clock = lambda: 2e12
    session.login(user, PASSWORD)
    assert session.failed_before_login == 2
    ev = session.security_events(1)[0]
    assert ev["kind"] == "login" and "2 tentativa" in ev["detail"]
    log = json.dumps(session.security_events(100))
    assert PASSWORD not in log and "senha-errada" not in log  # senhas nunca vão para o registro


# ------------------------------------------------------- pacotes .nexus
def test_reimport_of_same_package_is_detected(manager, store, tmp_path):
    store.create_entity("person", "Alguém")
    res = export_project(manager, store, tmp_path / "a.nexus", PKG_PW, KDF)
    import_package(manager, res.path, PKG_PW)
    pv = preview_package(manager, res.path, PKG_PW)
    assert any("já foi importado" in n for n in pv.notes)


def test_rejected_import_is_logged_without_details(manager, store, tmp_path):
    res = export_project(manager, store, tmp_path / "a.nexus", PKG_PW, KDF)
    with pytest.raises(PackageError):
        preview_package(manager, res.path, "senha-errada-do-pacote")
    ev = manager.session.security_events(1)[0]
    assert ev["kind"] == "import.rejected" and "senha" not in ev["detail"].lower()


def test_invalid_crypto_parameters_in_header_are_rejected(tmp_path):
    buf = io.BytesIO()
    w = container.PackageWriter(buf, container.wrap_with_password(PKG_PW, KDF), "0.3.4", "0.3.4")
    w.add("manifest.json", b"{}")
    w.close()
    raw = buf.getvalue()
    hlen = int.from_bytes(raw[9:13], "big")
    header = json.loads(raw[13:13 + hlen])
    for mutate in (lambda h: h.update(nonce_prefix="AAAA"),                       # nonce com tamanho errado
                   lambda h: h["key_wrap"]["kdf"].update(m=1),                    # Argon2id abaixo do piso
                   lambda h: h["key_wrap"]["kdf"].update(t=1000),                 # acima do teto (DoS)
                   lambda h: h.update(cipher="AES-128-CBC"),                      # rebaixamento de cifra
                   lambda h: h["key_wrap"].update(mode="nenhum")):
        h = json.loads(json.dumps(header))
        mutate(h)
        hb = json.dumps(h).encode()
        data = raw[:9] + len(hb).to_bytes(4, "big") + hb + raw[13 + hlen:]
        with pytest.raises(PackageError):
            hdr, hbytes = container.read_header(io.BytesIO(data))
            key = container.unwrap_with_password(hdr, PKG_PW)
            inp = io.BytesIO(data)
            container.read_header(inp)
            list(container.iter_records(inp, hdr, hbytes, key))


def test_interrupted_import_leftovers_are_removed(session):
    leftover = session.paths.projects / ".import-0123456789abcdef"
    (leftover / "blobs").mkdir(parents=True)
    (leftover / "project.nxdb").write_bytes(b"\x00" * 64)
    ProjectManager(session)
    assert not leftover.exists()


def test_export_verifies_package_before_delivering(manager, store, tmp_path, monkeypatch):
    from nexus_intel.application import sharing

    calls = []
    real = sharing._verify_file
    monkeypatch.setattr(sharing, "_verify_file", lambda p, pw: calls.append(p) or real(p, pw))
    res = export_project(manager, store, tmp_path / "v.nexus", PKG_PW, KDF)
    assert calls and res.path.exists() and not list(tmp_path.glob("*.part"))


# ------------------------------------------------- vazamento em disco/log
@requires_sqlcipher
def test_no_plaintext_leaks_to_profile_files_logs_or_temp(manager, store, tmp_path):
    session = manager.session
    temp_before = set(os.listdir(tempfile.gettempdir()))
    eid = store.create_entity("person", SECRET)
    store.create_note("nota", f"conteúdo sobre {SECRET}")
    store.add_photo(eid, make_image("PNG"), "foto.png")
    res = export_project(manager, store, tmp_path / "s.nexus", PKG_PW, KDF)
    import_package(manager, res.path, PKG_PW)
    store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    needle = SECRET.encode()
    roots = [session.paths.data, session.paths.logs, res.path.parent]
    for root in roots:
        for f in root.rglob("*"):
            if f.is_file():
                assert needle not in f.read_bytes(), f
    tmp = tempfile.gettempdir()
    for name in set(os.listdir(tmp)) - temp_before:
        path = os.path.join(tmp, name)
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                assert needle not in fh.read(), path
