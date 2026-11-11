"""Critério de aceitação 1: dois perfis no mesmo computador não acessam os dados um do outro."""

from __future__ import annotations

import pytest

from nexus_intel.application.profiles import ProfileManager
from nexus_intel.application.projects import ProjectManager
from nexus_intel.application.session import Session
from nexus_intel.domain.errors import InvalidCredentials, NexusError, ProfileError, ProjectNotFound
from tests.conftest import ENCRYPT, FAST_KDF, PASSWORD, requires_sqlcipher
from tests.imagefactory import make_image

PW_B = "outra-senha-bem-diferente-77"
SECRET_NAME = "Alvo Sigiloso Zeta"


@pytest.fixture
def profiles(paths):
    return ProfileManager(paths, kdf_params=FAST_KDF)


@pytest.fixture
def two(profiles):
    sa, _ = profiles.create("Perfil A", "perfil_a", PASSWORD, encrypt=ENCRYPT)
    ma = ProjectManager(sa)
    info = ma.create("Investigação de A")
    store = ma.open(info.id)
    eid = store.create_entity("person", SECRET_NAME)
    store.add_photo(eid, make_image("PNG"), "foto.png")
    store.create_note("Nota privada de A", "conteúdo sigiloso")
    ma.close_current()
    sa.lock()
    sb, _ = profiles.create("Perfil B", "perfil_b", PW_B, encrypt=ENCRYPT)
    yield profiles, sa, sb, info
    sb.lock()


def test_profiles_have_separate_folders_and_index(two):
    profiles, sa, sb, _ = two
    listed = {p.display_name: p for p in profiles.list()}
    assert set(listed) == {"Perfil A", "Perfil B"}
    assert sa.paths.data != sb.paths.data
    assert sa.paths.data.parent == sb.paths.data.parent == profiles.root.profiles_root
    assert listed["Perfil A"].fingerprint and listed["Perfil A"].fingerprint != listed["Perfil B"].fingerprint


def test_other_profile_cannot_list_or_open_projects(two):
    _profiles, _sa, sb, info = two
    mb = ProjectManager(sb)
    assert mb.list() == []
    with pytest.raises(ProjectNotFound):
        mb.get(info.id)
    with pytest.raises(ProjectNotFound):
        mb.open(info.id)


def test_copied_registry_row_does_not_open_other_profile_project(two):
    """Mesmo copiando o registro (com a chave embrulhada) de A para B, B não abre o projeto de A."""
    profiles, sa, sb, info = two
    sa.login("perfil_a", PASSWORD)
    row = sa.app_db.execute("SELECT * FROM project_registry WHERE id=?", (info.id,)).fetchone()
    sa.lock()
    cols = ",".join(row)
    sb.app_db.execute(f"INSERT INTO project_registry({cols}) VALUES ({','.join('?' * len(row))})",  # noqa: S608
                      tuple(row.values()))
    mb = ProjectManager(sb)
    # O caminho é recalculado dentro da pasta de B: o arquivo de A nunca é alcançado.
    assert mb.get(info.id).path.is_relative_to(sb.paths.projects)
    with pytest.raises(Exception):  # noqa: B017 - arquivo inexistente em B ou chave que não abre
        mb.open(info.id)
    if ENCRYPT:  # e a chave de A não se desembrulha com a chave mestra de B
        from nexus_intel.infrastructure.crypto.keys import InvalidTag

        with pytest.raises(InvalidTag):
            mb._project_key(mb.get(info.id))


@requires_sqlcipher
def test_other_profile_key_cannot_open_app_db_and_files_are_ciphertext(two):
    from nexus_intel.infrastructure.db.connection import open_database

    _profiles, sa, sb, _ = two
    key_b = sb.derived_key("app-db")
    with pytest.raises(NexusError):
        open_database(sa.paths.app_db, key_b)
    key_b.wipe()
    for f in sa.paths.data.rglob("*"):
        if f.is_file() and f.name != "avatar.png":
            raw = f.read_bytes()
            assert SECRET_NAME.encode() not in raw, f
            assert b"conte\xc3\xbado sigiloso" not in raw, f


def test_only_owner_session_can_edit_or_delete(two):
    profiles, sa, sb, _ = two
    with pytest.raises(ProfileError):
        profiles.update(sa, display_name="invasão")  # sessão de A bloqueada
    impostor = Session(sb.paths, kdf_params=FAST_KDF, profile_id=sa.profile_id)  # ID de A, cofre de B
    with pytest.raises(ProfileError):
        profiles.delete(impostor, PW_B)  # não desbloqueada
    with pytest.raises(InvalidCredentials):
        profiles.delete(sb, "senha-errada-qualquer")
    assert len(profiles.list()) == 2
    sb.vault._clock = lambda: __import__("time").time() + 10  # passa o atraso da tentativa errada
    profiles.update(sb, display_name="Perfil B renomeado", avatar=make_image("JPEG"))
    assert profiles.get(sb.profile_id).avatar_path is not None
    profiles.delete(sb, PW_B)
    assert [p.display_name for p in profiles.list()] == ["Perfil A"]
    assert not sb.paths.data.exists()
    assert sa.paths.vault.exists()  # A intacto


def test_profile_paths_reject_traversal(profiles):
    for bad in ("..", "../x", "01ABC", "C:/Windows", "01HZZZZZZZZZZZZZZZZZZZZZZZ/../../x"):
        with pytest.raises(ProfileError):
            profiles.paths_for(bad)


def test_duplicate_username_rejected(profiles):
    s, _ = profiles.create("Um", "mesmo_nome", PASSWORD, encrypt=ENCRYPT)
    s.lock()
    with pytest.raises(ProfileError):
        profiles.create("Dois", "MESMO_NOME", PW_B, encrypt=ENCRYPT)


def test_lock_wipes_keys_and_identity_private_needs_session(two):
    _profiles, sa, _sb, _ = two
    sa.login("perfil_a", PASSWORD)
    assert len(sa.identity_private("ed25519")) == 32
    sa.lock()
    with pytest.raises(NexusError):
        _ = sa.master
    with pytest.raises(NexusError):
        sa.identity_private("ed25519")


def test_legacy_single_user_install_becomes_first_profile(paths):
    legacy = Session(paths, kdf_params=FAST_KDF)
    legacy.setup("usuario_antigo", PASSWORD, encrypt=ENCRYPT)
    m = ProjectManager(legacy)
    info = m.create("Projeto antigo")
    m.open(info.id).create_entity("person", "Registro preservado")
    m.close_current()
    legacy.lock()

    profiles = ProfileManager(paths, kdf_params=FAST_KDF)
    (p,) = profiles.list()
    assert p.username == "usuario_antigo"
    assert not (paths.data / "vault.json").exists()
    s = profiles.session_for(p.id)
    s.login("usuario_antigo", PASSWORD)
    m2 = ProjectManager(s)
    store = m2.open(info.id)
    assert store.search("registro preservado")
    m2.close_current()
    s.lock()
    assert ProfileManager(paths, kdf_params=FAST_KDF).list()[0].id == p.id  # idempotente
