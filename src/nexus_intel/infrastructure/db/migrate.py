"""Migrações numeradas em SQL (ver ADR-0004).

Cada arquivo `NNNN_nome.sql` em migrations/<alvo>/ leva o banco da versão
NNNN-1 para NNNN. A versão vive em `PRAGMA user_version`. Antes de migrar um
banco existente, faz-se checkpoint do WAL e cópia do arquivo (que continua
cifrado, porque é copiado byte a byte).
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

from nexus_intel.domain.errors import SchemaTooNew

_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def _migrations(target: str) -> list[tuple[int, str]]:
    folder = resources.files("nexus_intel.infrastructure.db") / "migrations" / target
    found = []
    for entry in folder.iterdir():
        m = _NAME.match(entry.name)
        if m:
            found.append((int(m.group(1)), entry.read_text("utf-8")))
    found.sort()
    for expected, (number, _) in enumerate(found, start=1):
        if number != expected:
            raise RuntimeError(f"migração {expected:04d} ausente em {target}")
    return found


def latest_version(target: str) -> int:
    migs = _migrations(target)
    return migs[-1][0] if migs else 0


def current_version(conn: Any) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()["user_version"])


def split_statements(sql: str) -> list[str]:
    """Separa comandos com o próprio parser do SQLite (lida com gatilhos)."""
    statements: list[str] = []
    buf = ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                statements.append(buf.strip())
            buf = ""
    if buf.strip():
        raise ValueError("comando SQL incompleto no fim da migração")
    return statements


def backup_file(conn: Any, db_path: Path, label: str) -> Path:
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = db_path.with_name(f"{db_path.stem}.{label}-{stamp}{db_path.suffix}")
    shutil.copy2(db_path, dest)
    return dest


def migrate(conn: Any, target: str, db_path: Path | None = None) -> int:
    migs = _migrations(target)
    latest = migs[-1][0] if migs else 0
    version = current_version(conn)
    if version > latest:
        raise SchemaTooNew()
    if version == latest:
        return version
    if version > 0 and db_path is not None:
        backup_file(conn, db_path, f"pre-v{latest}")
    for number, sql in migs:
        if number <= version:
            continue
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in split_statements(sql):
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {number}")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return latest
