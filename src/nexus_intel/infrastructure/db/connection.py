"""Abertura de bancos SQLite/SQLCipher com as PRAGMAs da seção 8.4.

Regra de segurança: se uma chave é informada e o SQLCipher não está
disponível, a abertura FALHA. Nunca cai silenciosamente para texto puro.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from nexus_intel.domain.errors import EncryptionUnavailable
from nexus_intel.infrastructure.crypto.keys import SecretKey

try:  # pragma: no cover - depende do ambiente
    from sqlcipher3 import dbapi2 as _sqlcipher
except ImportError:  # pragma: no cover
    _sqlcipher = None


def sqlcipher_available() -> bool:
    return _sqlcipher is not None


def _row_factory(cursor: Any, row: tuple[Any, ...]) -> dict[str, Any]:
    return {d[0]: row[i] for i, d in enumerate(cursor.description)}


def open_database(path: Path, key: SecretKey | None) -> Any:
    """Abre (ou cria) o banco. `key=None` = banco em texto puro."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if key is not None:
        if _sqlcipher is None:
            raise EncryptionUnavailable()
        conn = _sqlcipher.connect(str(path), isolation_level=None, check_same_thread=False)
        # Chave bruta de 256 bits: sem a derivação PBKDF2 interna do SQLCipher.
        conn.execute(f"PRAGMA key = \"x'{key.hex()}'\"")
        # cipher_memory_security fica no padrão (desligado): ligado, ele troca o alocador
        # de memória do SQLite e estourou a pilha no Windows (CI, sqlcipher3-wheels).
        try:
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except _sqlcipher.DatabaseError as exc:
            conn.close()
            raise EncryptionUnavailable(
                "Não foi possível abrir o banco: chave incorreta ou arquivo corrompido."
            ) from exc
    else:
        conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    conn.row_factory = _row_factory
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


class Tx:
    """Transação explícita (`BEGIN IMMEDIATE`), aninhável por SAVEPOINT."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn
        self._sp: str | None = None

    def __enter__(self) -> Any:
        if self.conn.in_transaction:
            self._sp = f"sp_{id(self)}"
            self.conn.execute(f"SAVEPOINT {self._sp}")
        else:
            self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._sp:
            if exc_type is None:
                self.conn.execute(f"RELEASE {self._sp}")
            else:
                self.conn.execute(f"ROLLBACK TO {self._sp}")
                self.conn.execute(f"RELEASE {self._sp}")
        elif exc_type is None:
            self.conn.execute("COMMIT")
        else:
            self.conn.execute("ROLLBACK")
