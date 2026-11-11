"""Sessão do usuário: primeiro uso, login, recuperação, bloqueio (seção 6.1)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from nexus_intel.domain.errors import SessionLocked
from nexus_intel.domain.ids import new_ulid
from nexus_intel.infrastructure.crypto import identity
from nexus_intel.infrastructure.crypto.keys import KdfParams, SecretKey, calibrate_kdf, hkdf
from nexus_intel.infrastructure.crypto.vault import CRYPTO_FULL, CRYPTO_NONE, Vault
from nexus_intel.infrastructure.db.connection import open_database, sqlcipher_available
from nexus_intel.infrastructure.db.migrate import migrate
from nexus_intel.infrastructure.paths import AppPaths


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Session:
    def __init__(self, paths: AppPaths, kdf_params: KdfParams | None = None,
                 profile_id: str | None = None) -> None:
        self.profile_id = profile_id
        self.paths = paths.ensure()
        self.vault = Vault(paths.vault)
        self._kdf_override = kdf_params
        self._master: SecretKey | None = None
        self._app_conn: Any = None
        self.username: str | None = None
        self.crypto_mode: str = CRYPTO_FULL
        self.must_change_password = False
        self._on_lock: list[Callable[[], None]] = []

    # --- estado ----------------------------------------------------------
    @property
    def initialized(self) -> bool:
        return self.vault.exists()

    @property
    def unlocked(self) -> bool:
        return self._master is not None

    @property
    def master(self) -> SecretKey:
        if self._master is None:
            raise SessionLocked()
        return self._master

    @property
    def app_db(self) -> Any:
        if self._app_conn is None:
            raise SessionLocked()
        return self._app_conn

    def on_lock(self, callback: Callable[[], None]) -> None:
        self._on_lock.append(callback)

    @staticmethod
    def encryption_supported() -> bool:
        return sqlcipher_available()

    # --- fluxo -----------------------------------------------------------
    def setup(self, username: str, password: str, encrypt: bool = True) -> str:
        """Cria o usuário. Devolve a chave de recuperação (exibir uma vez)."""
        mode = CRYPTO_FULL if encrypt else CRYPTO_NONE
        if encrypt and not sqlcipher_available():
            from nexus_intel.domain.errors import EncryptionUnavailable

            raise EncryptionUnavailable()
        params = self._kdf_override or calibrate_kdf()
        result = self.vault.setup(username, password, params, crypto_mode=mode)
        self._start(result.master_key, username.strip(), mode)
        self._log_login(True, "primeiro uso")
        return result.recovery_key_text

    def login(self, username: str, password: str) -> None:
        result = self.vault.unlock(username, password)
        self._start(result.master_key, result.username, result.crypto_mode)
        self._log_login(True, "senha")

    def login_with_recovery(self, recovery_key: str) -> None:
        result = self.vault.unlock_with_recovery(recovery_key)
        self._start(result.master_key, result.username, result.crypto_mode)
        self.must_change_password = True
        self._log_login(True, "chave de recuperação")

    def set_new_password(self, new_password: str) -> None:
        self.vault.set_password(self.master, new_password, self._kdf_override)
        self.must_change_password = False

    def change_password(self, current: str, new_password: str) -> None:
        # Confirma a senha atual pelo próprio cofre antes de trocar.
        self.vault.unlock(self.username or "", current).master_key.wipe()
        self.set_new_password(new_password)

    def rotate_recovery_key(self) -> str:
        return self.vault.rotate_recovery_key(self.master)

    def lock(self) -> None:
        for cb in list(self._on_lock):
            try:
                cb()
            except Exception:  # noqa: S110 - bloquear deve sempre completar
                pass
        if self._app_conn is not None:
            self._app_conn.close()
            self._app_conn = None
        if self._master is not None:
            self._master.wipe()
            self._master = None

    # --- internos --------------------------------------------------------
    def derived_key(self, label: str) -> SecretKey:
        return hkdf(self.master, f"nexus-intel/{label}/v1")

    def _start(self, master: SecretKey, username: str, mode: str) -> None:
        self._master = master
        self.username = username
        self.crypto_mode = mode
        key = self.derived_key("app-db") if mode == CRYPTO_FULL else None
        try:
            self._app_conn = open_database(self.paths.app_db, key)
            migrate(self._app_conn, "app", self.paths.app_db)
            self._ensure_identity()
        except BaseException:
            self.lock()
            raise
        finally:
            if key is not None:
                key.wipe()

    # --- identidade (X25519 / Ed25519) -----------------------------------
    def _ensure_identity(self) -> None:
        have = {r["kind"] for r in self.app_db.execute("SELECT kind FROM identity_key").fetchall()}
        for kind in identity.KINDS:
            if kind not in have:
                k = identity.generate(kind, self.master)
                self.app_db.execute(
                    "INSERT INTO identity_key(kind, public_key, wrapped_private, created_at) VALUES (?,?,?,?)",
                    (kind, k.public_b64, json.dumps(k.wrapped), now_iso()))

    def _stored_identity(self, kind: str) -> identity.StoredKey:
        row = self.app_db.execute("SELECT * FROM identity_key WHERE kind=?", (kind,)).fetchone()
        if not row:
            raise SessionLocked()
        return identity.StoredKey(kind, row["public_key"], json.loads(row["wrapped_private"]))

    def identity_public(self, kind: str) -> bytes:
        return identity.public_raw(self._stored_identity(kind))

    def identity_private(self, kind: str) -> bytes:
        """Chave privada decifrada só para uso imediato (assinar / abrir pacote)."""
        return identity.unwrap_private(self._stored_identity(kind), self.master)

    def fingerprint(self, kind: str = "ed25519") -> str:
        return identity.fingerprint(self.identity_public(kind))

    def _log_login(self, success: bool, reason: str) -> None:
        self.app_db.execute(
            "INSERT INTO login_event(id, ts, username, success, reason) VALUES (?,?,?,?,?)",
            (new_ulid(), now_iso(), self.username, int(success), reason),
        )

    # --- preferências ----------------------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.app_db.execute("SELECT value_json FROM app_setting WHERE key=?", (key,)).fetchone()
        return json.loads(row["value_json"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self.app_db.execute(
            "INSERT INTO app_setting(key, value_json) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
            (key, json.dumps(value, ensure_ascii=False)),
        )
