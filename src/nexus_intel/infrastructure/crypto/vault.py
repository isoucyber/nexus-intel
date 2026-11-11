"""Cofre de chaves (`vault.json`), seção 12.2 com as correções da revisão.

O arquivo fica em texto puro porque precisa ser lido ANTES do login. Ele não
contém segredos em claro, só:

- usuário e parâmetros do Argon2id;
- dois "slots" (senha e recuperação), cada um com a MESMA chave mestra
  cifrada em AES-256-GCM pela respectiva KEK;
- o contador de tentativas erradas (atraso persistido).

A verificação da senha é o próprio desembrulho do slot: a tag GCM falha se a
senha estiver errada. Não existe hash de senha separado para atacar.

O banco da aplicação é cifrado com HKDF(chave mestra), por isso a chave de
recuperação também consegue abri-lo, e trocar a senha não re-cifra nada além
do slot de senha.

O contador de tentativas pode ser zerado por quem edita o arquivo; o atraso é
uma barreira contra tentativa pela interface. A barreira real contra ataque
offline é o custo do Argon2id.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nexus_intel.domain.errors import (
    InvalidCredentials,
    InvalidRecoveryKey,
    ThrottledError,
    VaultAlreadyInitialized,
    VaultNotInitialized,
    VaultTampered,
    WeakPassword,
)
from nexus_intel.infrastructure.crypto.keys import (
    InvalidTag,
    KdfParams,
    SecretKey,
    b64d,
    b64e,
    derive_password_kek,
    format_recovery_key,
    hkdf,
    new_recovery_secret,
    parse_recovery_key,
    unwrap,
    wrap,
)
from nexus_intel.infrastructure.fsutil import atomic_write_json

VAULT_FORMAT = 1
MIN_PASSWORD_LEN = 12
MAX_DELAY_SECONDS = 300.0

CRYPTO_FULL = "full"  # banco SQLCipher + anexos cifrados
CRYPTO_NONE = "none"  # só login; confia na criptografia do disco


def delay_for_failures(failures: int) -> float:
    """1 s, 2 s, 4 s… até 5 min. A partir de 10 falhas, sempre 5 min."""
    if failures <= 0:
        return 0.0
    if failures >= 10:
        return MAX_DELAY_SECONDS
    return min(float(2 ** (failures - 1)), MAX_DELAY_SECONDS)


def check_password_strength(password: str, username: str) -> None:
    if len(password) < MIN_PASSWORD_LEN:
        raise WeakPassword(f"A senha precisa ter pelo menos {MIN_PASSWORD_LEN} caracteres.")
    if password.strip().lower() == username.strip().lower():
        raise WeakPassword("A senha não pode ser igual ao nome de usuário.")
    if len(set(password)) < 5:
        raise WeakPassword("A senha tem caracteres repetidos demais.")


@dataclass
class UnlockResult:
    master_key: SecretKey
    username: str
    crypto_mode: str
    failed_before: int = 0  # tentativas erradas desde o último acesso (mostradas ao usuário)


@dataclass
class SetupResult:
    master_key: SecretKey
    recovery_key_text: str  # exibir UMA vez ao usuário


def _aad(kind: str, username: str) -> bytes:
    return f"nexus-intel/slot/{kind}/v{VAULT_FORMAT}/{username}".encode()


class Vault:
    def __init__(self, path: Path, clock: Any = time.time) -> None:
        self.path = path
        self._clock = clock

    # --- leitura ---------------------------------------------------------
    def exists(self) -> bool:
        return self.path.exists()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            raise VaultNotInitialized()
        try:
            data = json.loads(self.path.read_text("utf-8"))
            if data.get("format") != VAULT_FORMAT:
                raise VaultTampered()
            KdfParams.from_json(data["kdf"]).check_floor()
            b64d(data["kdf"]["salt"])
            _ = data["slots"]["password"], data["slots"]["recovery"], data["username"]
        except (ValueError, KeyError, TypeError) as exc:
            raise VaultTampered() from exc
        return data

    def username(self) -> str:
        return str(self._load()["username"])

    def crypto_mode(self) -> str:
        return str(self._load().get("crypto_mode", CRYPTO_FULL))

    def seconds_until_allowed(self) -> float:
        data = self._load()
        next_at = float(data.get("throttle", {}).get("next_allowed_at", 0))
        return max(0.0, next_at - self._clock())

    # --- criação ---------------------------------------------------------
    def setup(
        self,
        username: str,
        password: str,
        kdf_params: KdfParams | None = None,
        crypto_mode: str = CRYPTO_FULL,
    ) -> SetupResult:
        if self.exists():
            raise VaultAlreadyInitialized()
        username = username.strip()
        if not username:
            raise WeakPassword("Informe um nome de usuário.")
        check_password_strength(password, username)
        if crypto_mode not in (CRYPTO_FULL, CRYPTO_NONE):
            raise ValueError("modo de criptografia desconhecido")
        params = kdf_params or KdfParams()
        params.check_floor()

        master = SecretKey.generate()
        salt = os.urandom(16)
        kek = derive_password_kek(password, salt, params)
        recovery_secret = new_recovery_secret()
        recovery_salt = os.urandom(16)
        rkek = hkdf(SecretKey(recovery_secret), "nexus-intel/recovery-kek/v1", recovery_salt)
        try:
            data = {
                "format": VAULT_FORMAT,
                "username": username,
                "created_at": datetime.now(UTC).isoformat(),
                "crypto_mode": crypto_mode,
                "kdf": {**params.to_json(), "salt": b64e(salt)},
                "slots": {
                    "password": wrap(kek, master.bytes(), _aad("password", username)),
                    "recovery": {
                        "salt": b64e(recovery_salt),
                        **wrap(rkek, master.bytes(), _aad("recovery", username)),
                    },
                },
                "throttle": {"failures": 0, "next_allowed_at": 0},
            }
            atomic_write_json(self.path, data)
        finally:
            kek.wipe()
            rkek.wipe()
        return SetupResult(master_key=master, recovery_key_text=format_recovery_key(recovery_secret))

    # --- desbloqueio -----------------------------------------------------
    def _check_throttle(self, data: dict[str, Any]) -> None:
        wait = float(data.get("throttle", {}).get("next_allowed_at", 0)) - self._clock()
        if wait > 0:
            raise ThrottledError(wait)

    def _register_failure(self, data: dict[str, Any]) -> None:
        failures = int(data.get("throttle", {}).get("failures", 0)) + 1
        data["throttle"] = {
            "failures": failures,
            "next_allowed_at": self._clock() + delay_for_failures(failures),
        }
        atomic_write_json(self.path, data)

    def _register_success(self, data: dict[str, Any]) -> None:
        if data.get("throttle", {}).get("failures", 0):
            data["throttle"] = {"failures": 0, "next_allowed_at": 0}
            atomic_write_json(self.path, data)

    def unlock(self, username: str, password: str) -> UnlockResult:
        data = self._load()
        self._check_throttle(data)
        stored_user = data["username"]
        params = KdfParams.from_json(data["kdf"])
        kek = derive_password_kek(password, b64d(data["kdf"]["salt"]), params)
        try:
            # Sempre deriva e tenta, mesmo com usuário errado: mesmo custo de tempo.
            master = unwrap(kek, data["slots"]["password"], _aad("password", stored_user))
            if username.strip() != stored_user:
                raise InvalidTag()
        except InvalidTag:
            self._register_failure(data)
            raise InvalidCredentials() from None
        finally:
            kek.wipe()
        failed = int(data.get("throttle", {}).get("failures", 0))
        self._register_success(data)
        return UnlockResult(SecretKey(master), stored_user, data.get("crypto_mode", CRYPTO_FULL), failed)

    def unlock_with_recovery(self, recovery_text: str) -> UnlockResult:
        data = self._load()
        self._check_throttle(data)
        try:
            secret = parse_recovery_key(recovery_text)
        except ValueError as exc:
            self._register_failure(data)
            raise InvalidRecoveryKey() from exc
        slot = data["slots"]["recovery"]
        rkek = hkdf(SecretKey(secret), "nexus-intel/recovery-kek/v1", b64d(slot["salt"]))
        try:
            master = unwrap(rkek, slot, _aad("recovery", data["username"]))
        except InvalidTag:
            self._register_failure(data)
            raise InvalidRecoveryKey() from None
        finally:
            rkek.wipe()
        failed = int(data.get("throttle", {}).get("failures", 0))
        self._register_success(data)
        return UnlockResult(SecretKey(master), data["username"], data.get("crypto_mode", CRYPTO_FULL), failed)

    # --- troca de senha --------------------------------------------------
    def set_password(
        self, master: SecretKey, new_password: str, kdf_params: KdfParams | None = None
    ) -> None:
        """Re-cifra só o slot de senha. Exige a chave mestra já desbloqueada."""
        data = self._load()
        username = data["username"]
        check_password_strength(new_password, username)
        params = kdf_params or KdfParams.from_json(data["kdf"])
        salt = os.urandom(16)
        kek = derive_password_kek(new_password, salt, params)
        try:
            data["kdf"] = {**params.to_json(), "salt": b64e(salt)}
            data["slots"]["password"] = wrap(kek, master.bytes(), _aad("password", username))
            data["throttle"] = {"failures": 0, "next_allowed_at": 0}
            atomic_write_json(self.path, data)
        finally:
            kek.wipe()

    def rotate_recovery_key(self, master: SecretKey) -> str:
        """Gera nova chave de recuperação; a anterior deixa de funcionar."""
        data = self._load()
        secret = new_recovery_secret()
        salt = os.urandom(16)
        rkek = hkdf(SecretKey(secret), "nexus-intel/recovery-kek/v1", salt)
        try:
            data["slots"]["recovery"] = {
                "salt": b64e(salt),
                **wrap(rkek, master.bytes(), _aad("recovery", data["username"])),
            }
            atomic_write_json(self.path, data)
        finally:
            rkek.wipe()
        return format_recovery_key(secret)
