"""Projetos: um arquivo de banco por projeto, com chave própria (seções 6.2 e 12.2)."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nexus_intel.application.project_store import ProjectStore
from nexus_intel.application.session import Session, now_iso
from nexus_intel.domain.catalog import TEMPLATES
from nexus_intel.domain.errors import NexusError, ProjectLocked, ProjectNotFound
from nexus_intel.domain.ids import new_ulid
from nexus_intel.domain.model import require_name
from nexus_intel.infrastructure.crypto.keys import SecretKey, hkdf, unwrap, wrap
from nexus_intel.infrastructure.crypto.vault import CRYPTO_FULL
from nexus_intel.infrastructure.db.connection import open_database
from nexus_intel.infrastructure.db.migrate import migrate
from nexus_intel.infrastructure.fsutil import InstanceLock


@dataclass
class ProjectInfo:
    id: str
    name: str
    path: Path
    color: str
    icon: str
    template: str
    encrypted: bool
    created_at: str
    last_opened_at: str | None
    entity_count: int


def _info(row: dict[str, Any]) -> ProjectInfo:
    return ProjectInfo(
        id=row["id"],
        name=row["name"],
        path=Path(row["path"]),
        color=row["color"],
        icon=row["icon"],
        template=row["template"],
        encrypted=bool(row["encrypted"]),
        created_at=row["created_at"],
        last_opened_at=row["last_opened_at"],
        entity_count=row["entity_count"],
    )


class ProjectManager:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.current: ProjectStore | None = None
        self._lock: InstanceLock | None = None
        session.on_lock(self.close_current)

    # --- lista -----------------------------------------------------------
    def list(self) -> list[ProjectInfo]:
        rows = self.session.app_db.execute(
            "SELECT * FROM project_registry ORDER BY coalesce(last_opened_at, created_at) DESC"
        ).fetchall()
        return [_info(r) for r in rows]

    def get(self, project_id: str) -> ProjectInfo:
        row = self.session.app_db.execute(
            "SELECT * FROM project_registry WHERE id=?", (project_id,)
        ).fetchone()
        if not row:
            raise ProjectNotFound()
        return _info(row)

    # --- criação ---------------------------------------------------------
    def create(
        self,
        name: str,
        template: str = "blank",
        color: str = "#2dd4bf",
        purpose: str = "",
        legal_basis: str = "",
    ) -> ProjectInfo:
        name = require_name(name, "O nome do projeto")
        if template not in TEMPLATES:
            raise NexusError("Modelo de projeto desconhecido.")
        pid = new_ulid()
        folder = self.session.paths.projects / pid
        db_path = folder / "project.nxdb"
        encrypted = self.session.crypto_mode == CRYPTO_FULL
        project_key = SecretKey.generate() if encrypted else None
        wrapped = None
        if project_key is not None:
            blob = wrap(self.session.master, project_key.bytes(), f"nexus-intel/project/{pid}".encode())
            wrapped = f"{blob['nonce']}:{blob['ct']}"

        db_key = hkdf(project_key, "nexus-intel/project-db/v1") if project_key else None
        try:
            conn = open_database(db_path, db_key)
            try:
                migrate(conn, "project", db_path)
                store = ProjectStore(conn, pid, self.session.username or "?")
                store.initialize(name, template, purpose, legal_basis)
            finally:
                conn.close()
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        finally:
            if db_key:
                db_key.wipe()
            if project_key:
                project_key.wipe()

        self.session.app_db.execute(
            "INSERT INTO project_registry(id, name, path, color, template, encrypted, "
            "wrapped_project_key, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (pid, name, str(db_path), color, template, int(encrypted), wrapped, now_iso()),
        )
        return self.get(pid)

    # --- abertura --------------------------------------------------------
    def _project_db_key(self, info: ProjectInfo) -> SecretKey | None:
        if not info.encrypted:
            return None
        row = self.session.app_db.execute(
            "SELECT wrapped_project_key FROM project_registry WHERE id=?", (info.id,)
        ).fetchone()
        nonce, ct = row["wrapped_project_key"].split(":", 1)
        raw = unwrap(self.session.master, {"nonce": nonce, "ct": ct}, f"nexus-intel/project/{info.id}".encode())
        project_key = SecretKey(raw)
        try:
            return hkdf(project_key, "nexus-intel/project-db/v1")
        finally:
            project_key.wipe()

    def open(self, project_id: str) -> ProjectStore:
        info = self.get(project_id)
        self.close_current()
        if not info.path.exists():
            raise ProjectNotFound(f"O arquivo do projeto não foi encontrado em {info.path}.")
        lock = InstanceLock(info.path.with_suffix(".lock"))
        if not lock.acquire():
            raise ProjectLocked()
        key = self._project_db_key(info)
        try:
            conn = open_database(info.path, key)
            migrate(conn, "project", info.path)
        except BaseException:
            lock.release()
            raise
        finally:
            if key:
                key.wipe()
        self._lock = lock
        self.current = ProjectStore(conn, info.id, self.session.username or "?")
        self.current.audit("project.open", "project", info.id, info.name)
        self.session.app_db.execute(
            "UPDATE project_registry SET last_opened_at=? WHERE id=?", (now_iso(), info.id)
        )
        return self.current

    def close_current(self) -> None:
        if self.current is not None:
            try:
                count = self.current.count_entities()
                if self.session.unlocked:
                    self.session.app_db.execute(
                        "UPDATE project_registry SET entity_count=? WHERE id=?",
                        (count, self.current.project_id),
                    )
            except Exception:  # noqa: S110 - fechar sempre completa
                pass
            self.current.close()
            self.current = None
        if self._lock is not None:
            self._lock.release()
            self._lock = None

    # --- manutenção ------------------------------------------------------
    def update_appearance(self, project_id: str, name: str, color: str) -> None:
        name = require_name(name, "O nome do projeto")
        self.session.app_db.execute(
            "UPDATE project_registry SET name=?, color=? WHERE id=?", (name, color, project_id)
        )

    def delete(self, project_id: str) -> None:
        """Exclusão definitiva: apaga o arquivo e a pasta do projeto."""
        info = self.get(project_id)
        if self.current and self.current.project_id == project_id:
            self.close_current()
        folder = info.path.parent.resolve()
        root = self.session.paths.projects.resolve()
        # Só apaga a pasta se ela for exatamente <projetos>/<id>; nunca outra coisa.
        if folder.parent == root and folder.name == project_id:
            shutil.rmtree(folder, ignore_errors=True)
        self.session.app_db.execute("DELETE FROM project_registry WHERE id=?", (project_id,))
