from __future__ import annotations

import json

import pytest

from nexus_intel.domain.errors import (
    InvalidCredentials,
    InvalidRecoveryKey,
    ThrottledError,
    VaultTampered,
    WeakPassword,
)
from nexus_intel.infrastructure.crypto import keys
from nexus_intel.infrastructure.crypto.vault import Vault, delay_for_failures
from tests.conftest import FAST_KDF, PASSWORD


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def vault(tmp_path):
    clock = Clock()
    v = Vault(tmp_path / "vault.json", clock=clock)
    res = v.setup("arthur", PASSWORD, FAST_KDF)
    v.clock = clock
    v.recovery = res.recovery_key_text
    v.master = res.master_key.bytes()
    return v


def test_unlock_returns_same_master(vault):
    assert vault.unlock("arthur", PASSWORD).master_key.bytes() == vault.master


def test_wrong_password_fails_and_persists_delay(vault, tmp_path):
    with pytest.raises(InvalidCredentials):
        vault.unlock("arthur", "senha-errada-123456")
    # Uma nova instância (app reiniciado) continua vendo o atraso.
    fresh = Vault(tmp_path / "vault.json", clock=vault.clock)
    with pytest.raises(ThrottledError):
        fresh.unlock("arthur", PASSWORD)
    vault.clock.t += 1.01
    assert fresh.unlock("arthur", PASSWORD).master_key.bytes() == vault.master


def test_ten_failures_impose_five_minutes(vault):
    for _ in range(10):
        vault.clock.t += 400
        with pytest.raises(InvalidCredentials):
            vault.unlock("arthur", "errada-errada-errada")
    assert vault.seconds_until_allowed() == pytest.approx(300, abs=1)
    assert delay_for_failures(3) == 4
    assert delay_for_failures(15) == 300


def test_wrong_username_is_rejected(vault):
    with pytest.raises(InvalidCredentials):
        vault.unlock("outra", PASSWORD)


def test_recovery_key_unlocks_and_tolerates_formatting(vault):
    sloppy = vault.recovery.replace("-", " ").lower()
    assert vault.unlock_with_recovery(sloppy).master_key.bytes() == vault.master
    assert len(vault.recovery.replace("-", "")) == 52


def test_wrong_recovery_key(vault):
    other = keys.format_recovery_key(keys.new_recovery_secret())
    with pytest.raises(InvalidRecoveryKey):
        vault.unlock_with_recovery(other)


def test_password_change_keeps_master_and_recovery(vault):
    master = keys.SecretKey(vault.master)
    vault.set_password(master, "outra-senha-bem-longa", FAST_KDF)
    with pytest.raises(InvalidCredentials):
        vault.unlock("arthur", PASSWORD)
    vault.clock.t += 10
    assert vault.unlock("arthur", "outra-senha-bem-longa").master_key.bytes() == vault.master
    assert vault.unlock_with_recovery(vault.recovery).master_key.bytes() == vault.master


def test_rotate_recovery_invalidates_old(vault):
    new = vault.rotate_recovery_key(keys.SecretKey(vault.master))
    with pytest.raises(InvalidRecoveryKey):
        vault.unlock_with_recovery(vault.recovery)
    vault.clock.t += 10
    assert vault.unlock_with_recovery(new).master_key.bytes() == vault.master


def test_no_secret_in_vault_file(vault, tmp_path):
    text = (tmp_path / "vault.json").read_text()
    assert PASSWORD not in text
    assert vault.master.hex() not in text
    assert vault.recovery.replace("-", "") not in text


def test_downgraded_kdf_params_are_refused(vault, tmp_path, monkeypatch):
    monkeypatch.setattr(keys, "MIN_MEMORY_KIB", 64 * 1024)
    with pytest.raises(VaultTampered):
        vault.unlock("arthur", PASSWORD)


def test_tampered_slot_fails(vault, tmp_path):
    p = tmp_path / "vault.json"
    data = json.loads(p.read_text())
    ct = bytearray(keys.b64d(data["slots"]["password"]["ct"]))
    ct[0] ^= 1
    data["slots"]["password"]["ct"] = keys.b64e(bytes(ct))
    p.write_text(json.dumps(data))
    with pytest.raises(InvalidCredentials):
        vault.unlock("arthur", PASSWORD)


@pytest.mark.parametrize("pw", ["curta", "arthur", "aaaaaaaaaaaaaaaa"])
def test_weak_passwords(tmp_path, pw):
    with pytest.raises(WeakPassword):
        Vault(tmp_path / "v.json").setup("arthur", pw, FAST_KDF)


def test_secret_key_wipe():
    k = keys.SecretKey.generate()
    k.wipe()
    assert k.wiped
    with pytest.raises(RuntimeError):
        k.bytes()
    assert "***" not in repr(k)
