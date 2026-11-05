from __future__ import annotations

import pytest

from nexus_intel.infrastructure.crypto import keys
from nexus_intel.infrastructure.db.connection import sqlcipher_available

FAST_KDF = keys.KdfParams(memory_kib=8 * 1024, iterations=1, lanes=1)
PASSWORD = "cavalo-correto-bateria-grampo"


@pytest.fixture(autouse=True)
def weak_kdf_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Testes usam Argon2id barato; o piso real continua valendo no app."""
    monkeypatch.setattr(keys, "MIN_MEMORY_KIB", 1024)
    monkeypatch.setattr(keys, "MIN_ITERATIONS", 1)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_INTEL_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


@pytest.fixture
def paths(home):
    from nexus_intel.infrastructure.paths import default_paths

    return default_paths().ensure()


ENCRYPT = sqlcipher_available()


@pytest.fixture
def session(paths):
    from nexus_intel.application.session import Session

    s = Session(paths, kdf_params=FAST_KDF)
    s.recovery_key = s.setup("arthur", PASSWORD, encrypt=ENCRYPT)
    yield s
    s.lock()


@pytest.fixture
def manager(session):
    from nexus_intel.application.projects import ProjectManager

    m = ProjectManager(session)
    yield m
    m.close_current()


@pytest.fixture
def store(manager):
    info = manager.create("Teste")
    return manager.open(info.id)


requires_sqlcipher = pytest.mark.skipif(not ENCRYPT, reason="sqlcipher3 não instalado")
