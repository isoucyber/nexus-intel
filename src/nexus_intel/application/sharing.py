"""Exportação e importação de projetos em `.nexus` (0.3.4).

Conteúdo do pacote (dentro da parte cifrada; ver infrastructure/package/container.py):

    manifest.json            versão do formato, versão mínima do app, ID e nome do
                             projeto, data, contagens, lista de itens com SHA-256,
                             informação de criptografia e de assinatura
    tables/<tabela>.json     todas as linhas de cada tabela do projeto (IDs preservados)
    files/<sha256>           cada fotografia/anexo, o arquivo real (não um caminho)
    signature.json           Ed25519 do perfil que exportou, sobre o manifesto

Importação: tudo é decifrado e verificado (GCM de cada bloco, SHA-256 de cada
item, assinatura, chaves estrangeiras, conteúdo das imagens) numa pasta de
preparação DENTRO do perfil ativo, já gravando com as chaves novas do perfil
destinatário. Só no fim, com tudo válido, a pasta vira um projeto e entra no
registro. Em qualquer falha a preparação é apagada e nada aparece.
Um projeto existente nunca é sobrescrito: se o ID já existir, entra como cópia.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature

from nexus_intel import __version__
from nexus_intel.application.project_store import ProjectStore
from nexus_intel.application.projects import ProjectInfo, ProjectManager
from nexus_intel.application.session import now_iso
from nexus_intel.domain.catalog import TEMPLATES
from nexus_intel.domain.errors import NexusError, PackageError, PackageIncompatible
from nexus_intel.domain.ids import is_ulid, new_ulid
from nexus_intel.infrastructure.crypto import identity
from nexus_intel.infrastructure.crypto.keys import KdfParams, SecretKey, hkdf, wrap
from nexus_intel.infrastructure.crypto.vault import CRYPTO_FULL, MIN_PASSWORD_LEN
from nexus_intel.infrastructure.db.connection import open_database
from nexus_intel.infrastructure.db.migrate import current_version, latest_version, migrate
from nexus_intel.infrastructure.media.blobs import BlobStore, check_sha
from nexus_intel.infrastructure.media.images import inspect_image
from nexus_intel.infrastructure.package import container

MANIFEST_FORMAT = 1
MIN_APP_VERSION = "0.3.4"
EXTENSION = ".nexus"
_SKIP_TABLES = re.compile(r"^(sqlite_|entity_fts)")
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _version_tuple(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split(".")[:3])
    except ValueError:
        return (999,)


def _tables(conn: Any) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    return [r["name"] for r in rows if not _SKIP_TABLES.match(r["name"])]


def _columns(conn: Any, table: str) -> list[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]  # noqa: S608


# =================================================================== exportar
@dataclass
class ExportResult:
    path: Path
    size: int
    counts: dict[str, int]
    files: int
    fingerprint: str


def _counts(store: ProjectStore) -> dict[str, int]:
    def n(sql: str) -> int:
        row = store.conn.execute(sql).fetchone()
        return int(row["n"]) if row else 0

    return {
        "entities": n("SELECT count(*) AS n FROM entity WHERE record_status!='trashed'"),
        "relations": n("SELECT count(*) AS n FROM relation WHERE record_status!='trashed'"),
        "sources": n("SELECT count(*) AS n FROM source"),
        "photos": n("SELECT count(*) AS n FROM entity_photo"),
        "notes": n("SELECT count(*) AS n FROM note"),
        "claims": n("SELECT count(*) AS n FROM claim"),
    }


def export_project(manager: ProjectManager, store: ProjectStore, dest: Path, password: str,
                   kdf_params: KdfParams | None = None) -> ExportResult:
    """Grava o projeto aberto em `dest` (.nexus), cifrado pela senha e assinado pelo perfil."""
    if len(password) < MIN_PASSWORD_LEN:
        raise NexusError(f"A senha do arquivo precisa ter pelo menos {MIN_PASSWORD_LEN} caracteres.")
    session = manager.session
    info = manager.get(store.project_id)
    dest = Path(dest)
    if dest.suffix.lower() != EXTENSION:
        dest = dest.with_suffix(EXTENSION)
    blobs = store._require_blobs()
    store.conn.execute("PRAGMA wal_checkpoint(PASSIVE)")

    entries: list[dict[str, Any]] = []
    payload: list[tuple[str, bytes]] = []
    for table in _tables(store.conn):
        cols = _columns(store.conn, table)
        rows = store.conn.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
        data = json.dumps({"columns": cols, "rows": [[r[c] for c in cols] for r in rows]},
                          ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        payload.append((f"tables/{table}.json", data))
    shas = [r["sha256"] for r in store.conn.execute("SELECT sha256 FROM attachment ORDER BY sha256").fetchall()]
    for name, data in payload:
        entries.append({"name": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    file_sizes = {}
    for sha in shas:  # lê uma vez para conferir integridade e tamanho
        file_sizes[sha] = len(blobs.get(sha))
        entries.append({"name": f"files/{sha}", "size": file_sizes[sha], "sha256": sha})

    ed_pub = session.identity_public("ed25519")
    manifest = {
        "format": MANIFEST_FORMAT, "kind": "nexus-project", "app_version": __version__,
        "min_app_version": MIN_APP_VERSION, "exported_at": now_iso(),
        "schema_version": current_version(store.conn),
        "project": {"id": info.id, "name": info.name, "color": info.color, "icon": info.icon,
                    "template": info.template},
        "counts": _counts(store), "entries": entries,
        "crypto": {"content": "AES-256-GCM", "key_protection": "password/argon2id", "integrity": "SHA-256",
                   "signature": "Ed25519"},
        "signer": {"alg": "ed25519", "public_key": base64.b64encode(ed_pub).decode(),
                   "fingerprint": identity.fingerprint(ed_pub)},
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
    priv = session.identity_private("ed25519")
    try:
        sig = identity.ed25519_private(priv).sign(hashlib.sha256(manifest_bytes).digest())
    finally:
        priv = b"\x00" * len(priv)
    signature = json.dumps({"alg": "ed25519", "public_key": manifest["signer"]["public_key"],
                            "signature": base64.b64encode(sig).decode(), "over": "sha256(manifest.json)"})

    key_wrap = container.wrap_with_password(password, kdf_params or KdfParams())
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".part", dir=dest.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            writer = container.PackageWriter(out, key_wrap, __version__, MIN_APP_VERSION)
            writer.add("manifest.json", manifest_bytes)
            for name, data in payload:
                writer.add(name, data)
            for sha in shas:
                writer.add(f"files/{sha}", blobs.get(sha))
            writer.add("signature.json", signature.encode("utf-8"))
            writer.close()
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, dest)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise
    store.audit("project.export", "project", info.id, f"{dest.name} ({len(shas)} arquivos)")
    return ExportResult(dest, dest.stat().st_size, manifest["counts"], len(shas), manifest["signer"]["fingerprint"])


# =================================================================== verificar
@dataclass
class PackagePreview:
    path: Path
    project_id: str
    name: str
    color: str
    template: str
    exported_at: str
    app_version: str
    counts: dict[str, int]
    files: int
    files_bytes: int
    signer_fingerprint: str
    signed_by_me: bool
    already_exists: bool
    notes: list[str] = field(default_factory=list)


class _Verifier:
    """Confere, em ordem, cada registro contra o manifesto e a assinatura no fim."""

    def __init__(self) -> None:
        self.manifest: dict[str, Any] | None = None
        self.manifest_bytes = b""
        self.expected: dict[str, dict[str, Any]] = {}
        self.seen: set[str] = set()
        self.signature_ok = False
        self.signer_raw = b""

    def take(self, name: str, data: bytes) -> None:
        if self.manifest is None:
            if name != "manifest.json":
                raise PackageError("O arquivo .nexus não começa pelo manifesto.")
            self.manifest_bytes = data
            self.manifest = _parse_manifest(data)
            self.expected = {e["name"]: e for e in self.manifest["entries"]}
            return
        if name == "signature.json":
            self._check_signature(data)
            return
        if self.signature_ok:
            raise PackageError("Há itens depois da assinatura do arquivo .nexus.")
        entry = self.expected.get(name)
        if entry is None:
            raise PackageError("O arquivo .nexus contém um item que não está no manifesto.")
        if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise PackageError(f"O item {name} não confere com o manifesto (SHA-256). Nada foi importado.")
        self.seen.add(name)

    def _check_signature(self, data: bytes) -> None:
        assert self.manifest is not None
        try:
            sig = json.loads(data.decode("utf-8"))
            pub = base64.b64decode(sig["public_key"], validate=True)
            if sig.get("alg") != "ed25519" or sig["public_key"] != self.manifest["signer"]["public_key"]:
                raise ValueError
            identity.ed25519_public(pub).verify(base64.b64decode(sig["signature"], validate=True),
                                                hashlib.sha256(self.manifest_bytes).digest())
        except (InvalidSignature, ValueError, KeyError, TypeError, UnicodeDecodeError):
            raise PackageError("A assinatura digital do arquivo .nexus é inválida. Nada foi importado.") from None
        self.signature_ok = True
        self.signer_raw = pub

    def finish(self) -> dict[str, Any]:
        if self.manifest is None:
            raise PackageError()
        if set(self.expected) != self.seen:
            raise PackageError("Faltam itens no arquivo .nexus. Nada foi importado.")
        if not self.signature_ok:
            raise PackageError("O arquivo .nexus não tem assinatura válida. Nada foi importado.")
        return self.manifest


def _parse_manifest(data: bytes) -> dict[str, Any]:
    try:
        m = json.loads(data.decode("utf-8"))
        if not isinstance(m, dict) or m.get("kind") != "nexus-project":
            raise ValueError
        if m.get("format") != MANIFEST_FORMAT:
            raise PackageIncompatible()
        if _version_tuple(str(m.get("min_app_version", "999"))) > _version_tuple(__version__):
            raise PackageIncompatible()
        if int(m["schema_version"]) > latest_version("project"):
            raise PackageIncompatible()
        p = m["project"]
        if not is_ulid(str(p["id"])) or not str(p["name"]).strip():
            raise ValueError
        names = set()
        for e in m["entries"]:
            container.check_name(e["name"])
            if e["name"] in ("manifest.json", "signature.json") or e["name"] in names:
                raise ValueError
            names.add(e["name"])
            if not isinstance(e["size"], int) or e["size"] < 0 or not re.fullmatch(r"[0-9a-f]{64}", e["sha256"]):
                raise ValueError
            if e["name"].startswith("files/") and e["name"][6:] != e["sha256"]:
                raise ValueError
        m["signer"]["public_key"]  # noqa: B018 - obrigatório
    except PackageIncompatible:
        raise
    except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise PackageError("O manifesto do arquivo .nexus é inválido.") from exc
    return m


def _open_records(path: Path, password: str) -> tuple[Any, Any]:
    fh = open(path, "rb")  # noqa: SIM115 - fechado por quem chama
    try:
        header, header_bytes = container.read_header(fh)
        key = container.unwrap_with_password(header, password)
        return fh, container.iter_records(fh, header, header_bytes, key)
    except BaseException:
        fh.close()
        raise


def preview_package(manager: ProjectManager, path: Path, password: str) -> PackagePreview:
    """Decifra e verifica o pacote inteiro sem gravar nada; devolve o resumo para confirmação."""
    path = Path(path)
    v = _Verifier()
    fh, records = _open_records(path, password)
    files_bytes = 0
    with fh:
        for name, data in records:
            v.take(name, data)
            if name.startswith("files/"):
                inspect_image(data)
                files_bytes += len(data)
    m = v.finish()
    p = m["project"]
    my_pub = manager.session.identity_public("ed25519")
    existing = {i.id for i in manager.list()}
    notes = []
    if p["id"] in existing:
        notes.append("Já existe um projeto com este identificador neste perfil: a importação criará uma cópia "
                     "separada e não altera o projeto existente.")
    return PackagePreview(
        path=path, project_id=p["id"], name=str(p["name"])[:200], color=str(p.get("color", "")),
        template=str(p.get("template", "blank")), exported_at=str(m.get("exported_at", "")),
        app_version=str(m.get("app_version", "")), counts={k: int(v_) for k, v_ in m.get("counts", {}).items()},
        files=sum(1 for e in m["entries"] if e["name"].startswith("files/")), files_bytes=files_bytes,
        signer_fingerprint=identity.fingerprint(v.signer_raw), signed_by_me=v.signer_raw == my_pub,
        already_exists=p["id"] in existing, notes=notes)


# =================================================================== importar
def import_package(manager: ProjectManager, path: Path, password: str) -> ProjectInfo:
    """Reconstrói o projeto no perfil ativo. Nunca sobrescreve: ID repetido vira cópia."""
    session = manager.session
    path = Path(path)
    root = session.paths.projects
    staging = root / f".import-{secrets_token()}"
    staging.mkdir(parents=True)
    encrypted = session.crypto_mode == CRYPTO_FULL
    project_key = SecretKey.generate() if encrypted else None
    db_key = hkdf(project_key, "nexus-intel/project-db/v1") if project_key else None
    blob_key = hkdf(project_key, "nexus-intel/project-blobs/v1") if project_key else None
    blobs = BlobStore(staging / "blobs", blob_key)
    conn = None
    try:
        conn = open_database(staging / "project.nxdb", db_key)
        migrate(conn, "project")
        allowed = {t: set(_columns(conn, t)) for t in _tables(conn)}
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN IMMEDIATE")
        v = _Verifier()
        fh, records = _open_records(path, password)
        with fh:
            for name, data in records:
                v.take(name, data)
                if name.startswith("tables/"):
                    _insert_table(conn, allowed, name[7:-5], data)
                elif name.startswith("files/"):
                    inspect_image(data)
                    if blobs.put(data) != check_sha(name[6:]):
                        raise PackageError()
        m = v.finish()
        problems = conn.execute("PRAGMA foreign_key_check").fetchall()
        if problems:
            raise PackageError("O projeto do arquivo .nexus tem referências quebradas. Nada foi importado.")
        attached = {r["sha256"] for r in conn.execute("SELECT sha256 FROM attachment").fetchall()}
        packaged = {e["name"][6:] for e in m["entries"] if e["name"].startswith("files/")}
        if attached != packaged:
            raise PackageError("As fotografias do arquivo .nexus não conferem com os registros. Nada foi importado.")
        conn.execute("COMMIT")
        conn.execute("PRAGMA foreign_keys = ON")

        src = m["project"]
        existing = {i.id for i in manager.list()}
        pid = src["id"] if src["id"] not in existing and not (root / src["id"]).exists() else new_ulid()
        name = str(src["name"]).strip()[:200] + (" (importado)" if pid != src["id"] else "")
        store = ProjectStore(conn, pid, session.username or "?", blobs)
        for row in conn.execute("SELECT id FROM entity").fetchall():
            store._reindex(row["id"])
        signer = identity.fingerprint(v.signer_raw)
        store.audit("project.import", "project", pid, f"{path.name} · assinado por {signer}")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        conn = None
        blobs.close()

        wrapped = None
        if project_key is not None:
            blob = wrap(session.master, project_key.bytes(), f"nexus-intel/project/{pid}".encode())
            wrapped = f"{blob['nonce']}:{blob['ct']}"
        final = root / pid
        os.replace(staging, final)
        color = src.get("color") if _HEX_COLOR.match(str(src.get("color", ""))) else "#2dd4bf"
        template = src.get("template") if src.get("template") in TEMPLATES else "blank"
        try:
            session.app_db.execute(
                "INSERT INTO project_registry(id, name, path, color, template, encrypted, wrapped_project_key,"
                " created_at) VALUES (?,?,?,?,?,?,?,?)",
                (pid, name, str(final / "project.nxdb"), color, template, int(encrypted), wrapped, now_iso()))
        except BaseException:
            shutil.rmtree(final, ignore_errors=True)
            raise
        session.app_db.execute("UPDATE project_registry SET entity_count=? WHERE id=?",
                               (int(m.get("counts", {}).get("entities", 0)), pid))
        return manager.get(pid)
    except BaseException:
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()
        blobs.close()
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        for k in (project_key, db_key, blob_key):
            if k is not None:
                k.wipe()


def secrets_token() -> str:
    import secrets

    return secrets.token_hex(8)


def _insert_table(conn: Any, allowed: dict[str, set[str]], table: str, data: bytes) -> None:
    if table not in allowed:
        raise PackageError("O arquivo .nexus contém uma tabela desconhecida. Nada foi importado.")
    try:
        obj = json.loads(data.decode("utf-8"))
        cols, rows = obj["columns"], obj["rows"]
        if not isinstance(cols, list) or not isinstance(rows, list) or not cols:
            raise ValueError
    except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise PackageError("Dados de tabela inválidos no arquivo .nexus.") from exc
    if len(set(cols)) != len(cols) or not set(cols) <= allowed[table]:
        raise PackageError("O arquivo .nexus tem colunas que esta versão não conhece. Nada foi importado.")
    if table == "project_meta":
        conn.execute("DELETE FROM project_meta")
    sql = f"INSERT INTO {table}({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"  # noqa: S608
    for row in rows:
        if not isinstance(row, list) or len(row) != len(cols):
            raise PackageError("Linha inválida no arquivo .nexus.")
        for value in row:
            if not (value is None or isinstance(value, str | int | float)):
                raise PackageError("Valor inválido no arquivo .nexus.")
        try:
            conn.execute(sql, row)
        except Exception as exc:  # noqa: BLE001 - restrição violada = pacote inválido
            raise PackageError("Os dados do arquivo .nexus violam as regras do banco. Nada foi importado.") from exc
