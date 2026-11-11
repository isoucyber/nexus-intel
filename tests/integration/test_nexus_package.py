"""Critérios de aceitação 2 e 3: pacote .nexus leva tudo (inclusive fotos) e resiste a adulteração."""

from __future__ import annotations

import io
import struct

import pytest

from nexus_intel.application.profiles import ProfileManager
from nexus_intel.application.projects import ProjectManager
from nexus_intel.application.sharing import export_project, import_package, preview_package
from nexus_intel.domain.errors import NexusError, PackageAuthError, PackageError, PackageIncompatible
from nexus_intel.infrastructure.crypto.keys import KdfParams
from nexus_intel.infrastructure.package import container
from nexus_intel.infrastructure.paths import AppPaths
from tests.conftest import ENCRYPT, FAST_KDF, PASSWORD
from tests.imagefactory import make_image

PKG_PW = "senha-do-pacote-compartilhado"
PKG_KDF = KdfParams(memory_kib=8 * 1024, iterations=1, lanes=1)


def _install(base) -> ProfileManager:
    """Uma 'instalação' independente do NEXUS (pasta de dados própria)."""
    return ProfileManager(AppPaths(base / "data", base / "config", base / "logs"), kdf_params=FAST_KDF)


@pytest.fixture
def origin(tmp_path):
    profiles = _install(tmp_path / "pc-origem")
    session, _ = profiles.create("Origem", "origem", PASSWORD, encrypt=ENCRYPT)
    manager = ProjectManager(session)
    info = manager.create("Operação Teste", color="#7c3aed")
    store = manager.open(info.id)
    ids = {}
    images = {}
    for i, (name, fmt) in enumerate([("Pessoa A", "PNG"), ("Pessoa B", "JPEG"), ("Empresa C", "WEBP"),
                                     ("Pessoa D", "TIFF")]):
        kind = "company" if name.startswith("Empresa") else "person"
        ids[name] = store.create_entity(kind, name)
        img = make_image(fmt, color=(40 * i, 90, 200 - 30 * i), gps=(fmt == "JPEG"))
        images[name] = img
        store.add_photo(ids[name], img, f"{name}.{fmt.lower()}")
    shared = make_image("GIF", color=(1, 2, 3))
    store.add_photo(ids["Pessoa A"], shared, "compartilhada.gif")
    store.add_photo(ids["Pessoa B"], shared, "compartilhada.gif")
    src = store.create_source("Documento de origem", kind="official", url="https://exemplo.invalid/doc")
    store.create_relation("works_at", ids["Pessoa A"], ids["Empresa C"], evidence_source=src, excerpt="trecho")
    store.create_relation("knows", ids["Pessoa A"], ids["Pessoa B"])
    store.add_claim(ids["Pessoa A"], "nascimento", "03/1985", source_id=src)
    store.create_note("Hipótese", "texto da nota", entity_id=ids["Pessoa B"])
    yield {"profiles": profiles, "session": session, "manager": manager, "store": store, "info": info,
           "ids": ids, "images": images, "shared": shared}
    manager.close_current()
    session.lock()


def _export(origin, tmp_path):
    return export_project(origin["manager"], origin["store"], tmp_path / "transferencia" / "caso.nexus",
                          PKG_PW, PKG_KDF)


def test_full_round_trip_to_another_installation(origin, tmp_path):
    res = _export(origin, tmp_path)
    assert res.path.exists() and res.files == 5

    # Outra instalação, outro perfil, outro computador (pasta). A origem pode até sumir.
    dest_profiles = _install(tmp_path / "pc-destino")
    session, _ = dest_profiles.create("Destino", "destino", "senha-do-destino-1234", encrypt=ENCRYPT)
    manager = ProjectManager(session)
    origin["manager"].close_current()
    origin["session"].lock()  # fecha o banco do perfil de origem (no Windows, arquivo aberto não se apaga)
    import shutil

    shutil.rmtree(tmp_path / "pc-origem")  # nenhum caminho de origem é necessário

    pv = preview_package(manager, res.path, PKG_PW)
    assert pv.name == "Operação Teste" and pv.files == 5 and not pv.signed_by_me
    assert pv.counts["entities"] == 4 and pv.counts["photos"] == 6 and pv.counts["notes"] == 1
    assert pv.signer_fingerprint == res.fingerprint

    info = import_package(manager, res.path, PKG_PW)
    assert info.id == origin["info"].id  # identificador preservado
    assert info.color == "#7c3aed"
    store = manager.open(info.id)
    ids = origin["ids"]
    for name, eid in ids.items():
        assert store.get_entity(eid)["display_name"] == name  # IDs internos preservados
        photos = store.list_photos(eid)
        assert photos and store.photo_bytes(photos[0]["id"]) == origin["images"][name]
    shared_a = [p for p in store.list_photos(ids["Pessoa A"]) if p["original_name"] == "compartilhada.gif"]
    assert store.photo_bytes(shared_a[0]["id"]) == origin["shared"]
    assert len(store.blobs.list_shas()) == 5  # deduplicação preservada
    assert len(store.relations_for(ids["Pessoa A"])) == 2
    assert store.evidence_for("relation", store.relations_for(ids["Pessoa A"])[0]["id"]) is not None
    assert store.list_notes()[0]["entity_id"] == ids["Pessoa B"]
    assert store.search("pessoa a")  # índice de busca reconstruído
    assert store.verify_audit() is None  # cadeia de auditoria íntegra, com a importação registrada
    jpeg = next(p for p in store.list_photos(ids["Pessoa B"]) if p["original_name"].endswith(".jpeg"))
    assert jpeg["has_gps"] == 1  # metadados preservados
    # Arquivos ficam no perfil de destino, cifrados com a chave nova (não a da origem).
    assert store.blobs.root.is_relative_to(session.paths.projects)
    manager.close_current()
    session.lock()


def test_import_twice_creates_copy_and_never_overwrites(origin, tmp_path):
    res = _export(origin, tmp_path)
    manager = origin["manager"]
    first = import_package(manager, res.path, PKG_PW)  # mesmo perfil: ID já existe
    assert first.id != origin["info"].id and first.name.endswith("(importado)")
    assert manager.get(origin["info"].id).name == "Operação Teste"
    second = import_package(manager, res.path, PKG_PW)
    assert len({first.id, second.id, origin["info"].id}) == 3


def test_wrong_password_rejected_and_nothing_created(origin, tmp_path):
    res = _export(origin, tmp_path)
    manager = origin["manager"]
    before = {p.id for p in manager.list()}
    with pytest.raises(PackageAuthError):
        preview_package(manager, res.path, "senha-errada-qualquer")
    with pytest.raises(PackageAuthError):
        import_package(manager, res.path, "senha-errada-qualquer")
    assert {p.id for p in manager.list()} == before
    assert not list(manager.session.paths.projects.glob(".import-*"))


def test_package_is_really_encrypted(origin, tmp_path):
    res = _export(origin, tmp_path)
    raw = res.path.read_bytes()
    assert raw.startswith(b"NEXUSPKG\x01")
    for needle in (b"Pessoa A", b"Operacao", "Operação".encode(), b"texto da nota", b"PK\x03\x04",
                   origin["images"]["Pessoa A"][:64]):
        assert needle not in raw


@pytest.mark.parametrize("where", ["header", "first-chunk", "last-byte", "middle"])
def test_any_altered_byte_is_detected(origin, tmp_path, where):
    res = _export(origin, tmp_path)
    raw = bytearray(res.path.read_bytes())
    hlen = struct.unpack(">I", raw[9:13])[0]
    pos = {"header": 13 + hlen // 2, "first-chunk": 13 + hlen + 40, "last-byte": len(raw) - 1,
           "middle": len(raw) // 2}[where]
    raw[pos] ^= 0x01
    bad = tmp_path / "alterado.nexus"
    bad.write_bytes(bytes(raw))
    with pytest.raises(PackageError):
        import_package(origin["manager"], bad, PKG_PW)


def test_truncated_and_extended_files_are_rejected(origin, tmp_path):
    res = _export(origin, tmp_path)
    raw = res.path.read_bytes()
    for name, data in (("cortado.nexus", raw[: len(raw) - 100]), ("extra.nexus", raw + b"\x00" * 8),
                       ("vazio.nexus", b""), ("zip.nexus", b"PK\x03\x04" + raw[4:])):
        p = tmp_path / name
        p.write_bytes(data)
        with pytest.raises(PackageError):
            import_package(origin["manager"], p, PKG_PW)


def test_two_exports_use_fresh_keys_and_nonces(origin, tmp_path):
    a = export_project(origin["manager"], origin["store"], tmp_path / "a.nexus", PKG_PW, PKG_KDF)
    b = export_project(origin["manager"], origin["store"], tmp_path / "b.nexus", PKG_PW, PKG_KDF)
    ha, _ = container.read_header(io.BytesIO(a.path.read_bytes()))
    hb, _ = container.read_header(io.BytesIO(b.path.read_bytes()))
    assert ha["nonce_prefix"] != hb["nonce_prefix"]
    assert ha["key_wrap"]["kdf"]["salt"] != hb["key_wrap"]["kdf"]["salt"]
    assert a.path.read_bytes()[-200:] != b.path.read_bytes()[-200:]


def _forge(tmp_path, records: list[tuple[str, bytes]], password: str = PKG_PW):
    """Pacote cifrado CORRETAMENTE, mas com conteúdo malicioso dentro."""
    buf = io.BytesIO()
    w = container.PackageWriter(buf, container.wrap_with_password(password, PKG_KDF), "0.3.4", "0.3.4")
    for name, data in records:
        w.add(name, data)
    w.close()
    p = tmp_path / "forjado.nexus"
    p.write_bytes(buf.getvalue())
    return p


def test_malicious_names_rejected_by_writer_and_reader(tmp_path):
    for bad in ("../../evil.exe", "files/../../x", "C:\\Windows\\x", "/etc/passwd", "tables/x/../../y.json"):
        with pytest.raises(PackageError):
            container.check_name(bad)


def test_forged_package_without_valid_signature_is_rejected(origin, tmp_path):
    import json

    manifest = {"format": 1, "kind": "nexus-project", "app_version": "0.3.4", "min_app_version": "0.3.4",
                "schema_version": 1, "project": {"id": "01HZY0000000000000000000AB", "name": "X"},
                "entries": [], "signer": {"public_key": "AAAA"}}
    p = _forge(tmp_path, [("manifest.json", json.dumps(manifest).encode())])
    with pytest.raises(PackageError):
        import_package(origin["manager"], p, PKG_PW)
    newer = dict(manifest, min_app_version="9.0.0")
    p = _forge(tmp_path, [("manifest.json", json.dumps(newer).encode())])
    with pytest.raises(PackageIncompatible):
        import_package(origin["manager"], p, PKG_PW)


def test_tampered_content_with_resigned_wrapper_fails_hash_check(origin, tmp_path):
    """Quem sabe a senha e re-cifra o pacote trocando uma foto é pego pelo SHA-256/assinatura."""
    res = _export(origin, tmp_path)
    fh = open(res.path, "rb")
    header, hb = container.read_header(fh)
    key = container.unwrap_with_password(header, PKG_PW)
    records = list(container.iter_records(fh, header, hb, key))
    fh.close()
    swapped = [(n, make_image("PNG", color=(9, 9, 9)) if n.startswith("files/") else d) for n, d in records]
    with pytest.raises(PackageError):
        import_package(origin["manager"], _forge(tmp_path, swapped), PKG_PW)
    # mexer no manifesto (ex.: nome do projeto) invalida a assinatura Ed25519
    import json

    m = json.loads(records[0][1])
    m["project"]["name"] = "Nome trocado"
    renamed = [("manifest.json", json.dumps(m, sort_keys=True).encode())] + records[1:]
    with pytest.raises(PackageError):
        import_package(origin["manager"], _forge(tmp_path, renamed), PKG_PW)


def test_identity_mode_only_opens_for_recipient(origin, tmp_path):
    """Modo por identidade (preparado): só a chave X25519 do destinatário abre."""
    other_profiles = _install(tmp_path / "pc-b")
    sb, _ = other_profiles.create("B", "destinatario", "senha-do-destinatario-12", encrypt=ENCRYPT)
    sa = origin["session"]
    wrap = container.wrap_for_recipients([sb.identity_public("x25519")])
    buf = io.BytesIO()
    w = container.PackageWriter(buf, wrap, "0.3.4", "0.3.4")
    w.add("manifest.json", b"{}")
    w.close()
    data = buf.getvalue()
    h, hb = container.read_header(io.BytesIO(data))
    key = container.unwrap_with_identity(h, sb.identity_private("x25519"))
    inp = io.BytesIO(data)
    container.read_header(inp)
    assert list(container.iter_records(inp, h, hb, key)) == [("manifest.json", b"{}")]
    with pytest.raises(PackageAuthError):
        container.unwrap_with_identity(h, sa.identity_private("x25519"))
    sb.lock()


def test_kdf_bounds_block_denial_of_service(tmp_path):
    header = {"key_wrap": {"mode": "password", "kdf": {"alg": "argon2id", "m": 64 * 1024 * 1024, "t": 3,
                                                       "p": 4, "salt": "AAAAAAAAAAAAAAAAAAAAAA=="},
                           "nonce": "AAAAAAAAAAAAAAAA", "ct": "AAAA"}}
    with pytest.raises(PackageError):
        container.unwrap_with_password(header, PKG_PW)


def test_short_export_password_refused(origin, tmp_path):
    with pytest.raises(NexusError):
        export_project(origin["manager"], origin["store"], tmp_path / "x.nexus", "curta", PKG_KDF)
