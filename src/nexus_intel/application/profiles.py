"""Perfis locais: várias pessoas no mesmo computador, cada uma com seu ambiente (0.3.4).

Layout em disco (pasta de dados do NEXUS):

    profiles.json                 índice PÚBLICO (lido antes do login): id, nome de
                                  exibição, se há avatar, impressões digitais públicas
    profiles/<id>/vault.json      cofre do perfil (Argon2id + AES-256-GCM)
    profiles/<id>/app.nxdb        banco do perfil (SQLCipher, chave do perfil)
    profiles/<id>/projects/...    projetos do perfil (cada um com chave própria)
    profiles/<id>/avatar.png      imagem do perfil (pública, aparece na seleção)

Isolamento: cada perfil tem a própria chave mestra. Os bancos, projetos,
fotografias e chaves privadas de um perfil são cifrados com chaves derivadas
dela; sem a senha (ou a chave de recuperação) daquele perfil nada é legível.
O caminho de um perfil é sempre recalculado a partir do ID validado (ULID),
nunca lido de um arquivo, para impedir que um perfil aponte para a pasta de
outro.

Limitação: todos os perfis usam a mesma conta do sistema operacional. O
Windows não impede um perfil de VER os arquivos do outro; o que impede a
leitura é a criptografia. Perfis criados sem cifragem (“só login”) ficam
protegidos apenas pela tela de entrada do NEXUS.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nexus_intel.application.session import Session, now_iso
from nexus_intel.domain.errors import InvalidCredentials, ProfileError
from nexus_intel.domain.ids import is_ulid, new_ulid
from nexus_intel.infrastructure.crypto.keys import KdfParams
from nexus_intel.infrastructure.crypto.vault import CRYPTO_FULL, Vault
from nexus_intel.infrastructure.fsutil import atomic_write_bytes, atomic_write_json
from nexus_intel.infrastructure.media.images import inspect_image, render_png
from nexus_intel.infrastructure.paths import AppPaths

INDEX_FORMAT = 1
AVATAR_SIDE = 256
MAX_DISPLAY_NAME = 60
_LEGACY_MARK = "migration-0.3.4.json"


@dataclass(frozen=True)
class ProfileInfo:
    id: str
    display_name: str
    username: str
    created_at: str
    avatar_path: Path | None
    encrypted: bool
    fingerprint: str


class ProfileManager:
    def __init__(self, root: AppPaths, kdf_params: KdfParams | None = None) -> None:
        self.root = root.ensure()
        self._kdf = kdf_params
        self.root.profiles_root.mkdir(parents=True, exist_ok=True)
        self.migrate_legacy()

    # ------------------------------------------------------------ caminhos
    def _dir(self, profile_id: str) -> Path:
        """Pasta do perfil, validada: ID ULID e exatamente <dados>/profiles/<id>."""
        if not isinstance(profile_id, str) or not is_ulid(profile_id):
            raise ProfileError("Perfil inválido.")
        folder = (self.root.profiles_root / profile_id).resolve()
        if folder.parent != self.root.profiles_root.resolve():
            raise ProfileError("Perfil inválido.")
        return folder

    def paths_for(self, profile_id: str) -> AppPaths:
        self._dir(profile_id)
        return self.root.for_profile(profile_id)

    # ------------------------------------------------------------ índice
    def _load_index(self) -> dict[str, Any]:
        path = self.root.profiles_index
        if not path.exists():
            return {"format": INDEX_FORMAT, "profiles": []}
        try:
            data = json.loads(path.read_text("utf-8"))
            if data.get("format") != INDEX_FORMAT or not isinstance(data.get("profiles"), list):
                raise ValueError
        except (ValueError, OSError) as exc:
            raise ProfileError("A lista de perfis está corrompida. Restaure um backup da pasta de dados.") from exc
        data["profiles"] = [p for p in data["profiles"] if isinstance(p, dict) and is_ulid(str(p.get("id", "")))]
        return data

    def _save_index(self, data: dict[str, Any]) -> None:
        atomic_write_json(self.root.profiles_index, data)

    def _entry(self, profile_id: str) -> dict[str, Any]:
        for p in self._load_index()["profiles"]:
            if p["id"] == profile_id:
                return dict(p)
        raise ProfileError("Perfil não encontrado.")

    def list(self) -> list[ProfileInfo]:
        out = []
        for p in self._load_index()["profiles"]:
            folder = self._dir(p["id"])
            vault = Vault(folder / "vault.json")
            if not vault.exists():
                continue  # criação interrompida: ignora sem expor nada
            try:
                username, mode = vault.username(), vault.crypto_mode()
            except Exception:  # noqa: BLE001 - cofre corrompido não derruba a seleção
                username, mode = "?", CRYPTO_FULL
            avatar = folder / "avatar.png"
            out.append(ProfileInfo(
                id=p["id"], display_name=str(p.get("display_name") or username)[:MAX_DISPLAY_NAME],
                username=username, created_at=str(p.get("created_at", "")),
                avatar_path=avatar if avatar.exists() else None, encrypted=mode == CRYPTO_FULL,
                fingerprint=str(p.get("fingerprint", ""))))
        return out

    def get(self, profile_id: str) -> ProfileInfo:
        for p in self.list():
            if p.id == profile_id:
                return p
        raise ProfileError("Perfil não encontrado.")

    # ------------------------------------------------------------ sessão
    def session_for(self, profile_id: str) -> Session:
        self.get(profile_id)
        return Session(self.paths_for(profile_id), kdf_params=self._kdf, profile_id=profile_id)

    def _require_owner(self, session: Session, profile_id: str) -> None:
        """Toda alteração de perfil exige a sessão DESBLOQUEADA do próprio perfil."""
        if not session.unlocked or session.profile_id != profile_id:
            raise ProfileError("Só o próprio perfil, com a sessão aberta, pode alterar ou excluir seus dados.")

    # ------------------------------------------------------------ criação
    def create(self, display_name: str, username: str, password: str, encrypt: bool = True,
               avatar: bytes | None = None) -> tuple[Session, str]:
        """Cria o perfil e devolve (sessão já aberta, chave de recuperação)."""
        display = (display_name or "").strip()[:MAX_DISPLAY_NAME] or username.strip()
        uname = username.strip()
        if not uname:
            raise ProfileError("Informe um nome de usuário.")
        if any(p.username.lower() == uname.lower() for p in self.list()):
            raise ProfileError("Já existe um perfil com esse nome de usuário neste computador.")
        avatar_png = self._avatar_png(avatar) if avatar else None
        pid = new_ulid()
        folder = self._dir(pid)
        session = Session(self.root.for_profile(pid), kdf_params=self._kdf, profile_id=pid)
        try:
            recovery = session.setup(uname, password, encrypt=encrypt)
            if avatar_png:
                atomic_write_bytes(folder / "avatar.png", avatar_png)
            data = self._load_index()
            data["profiles"].append({"id": pid, "display_name": display, "created_at": now_iso(),
                                     "fingerprint": session.fingerprint()})
            self._save_index(data)
        except BaseException:
            session.lock()
            shutil.rmtree(folder, ignore_errors=True)
            raise
        return session, recovery

    @staticmethod
    def _avatar_png(data: bytes) -> bytes:
        inspect_image(data)  # mesmo controle das fotografias: conteúdo real, tamanho, pixels
        return render_png(data, AVATAR_SIDE)

    # ------------------------------------------------------------ edição
    def update(self, session: Session, display_name: str | None = None, avatar: bytes | None = None,
               remove_avatar: bool = False) -> None:
        pid = session.profile_id or ""
        self._require_owner(session, pid)
        folder = self._dir(pid)
        data = self._load_index()
        entry = next((p for p in data["profiles"] if p["id"] == pid), None)
        if entry is None:
            raise ProfileError("Perfil não encontrado.")
        if display_name is not None:
            name = display_name.strip()[:MAX_DISPLAY_NAME]
            if not name:
                raise ProfileError("O nome de exibição não pode ficar vazio.")
            entry["display_name"] = name
        if avatar is not None:
            atomic_write_bytes(folder / "avatar.png", self._avatar_png(avatar))
        elif remove_avatar:
            with contextlib.suppress(FileNotFoundError):
                (folder / "avatar.png").unlink()
        entry["fingerprint"] = session.fingerprint()
        self._save_index(data)
        session.security_event("profile.update", "nome/imagem")

    def delete(self, session: Session, password: str) -> None:
        """Exclui o perfil inteiro (cofre, banco, projetos, fotos). Exige a senha do próprio perfil."""
        pid = session.profile_id or ""
        self._require_owner(session, pid)
        folder = self._dir(pid)
        try:
            session.vault.unlock(session.username or "", password).master_key.wipe()
        except InvalidCredentials:
            raise InvalidCredentials("Senha incorreta. O perfil não foi excluído.") from None
        session.lock()
        data = self._load_index()
        data["profiles"] = [p for p in data["profiles"] if p["id"] != pid]
        self._save_index(data)  # primeiro some da lista; depois os arquivos
        shutil.rmtree(folder, ignore_errors=True)

    # ------------------------------------------------- migração da 0.3.3
    def migrate_legacy(self) -> str | None:
        """Instalação de usuário único (até 0.3.3) vira o primeiro perfil, sem apagar nada.

        Move vault.json, app.nxdb (com WAL e cópias de migração) e a pasta
        projects/ para profiles/<id>/. Uma marca em disco permite retomar se o
        computador desligar no meio. Os caminhos dos projetos não precisam ser
        reescritos: eles são recalculados a partir da pasta do perfil.
        """
        data_dir = self.root.data
        mark = data_dir / _LEGACY_MARK
        legacy_vault = data_dir / "vault.json"
        if mark.exists():
            pid = json.loads(mark.read_text("utf-8"))["id"]
        elif legacy_vault.exists():
            pid = new_ulid()
            atomic_write_json(mark, {"id": pid, "started_at": now_iso()})
        else:
            return None
        dest = self._dir(pid)
        dest.mkdir(parents=True, exist_ok=True)
        names = ["vault.json", "projects"]
        names += [p.name for p in data_dir.glob("app*.nxdb*")]
        for name in names:
            src = data_dir / name
            if src.exists():
                target = dest / name
                if target.exists() and target.is_dir() and src.is_dir():
                    for child in src.iterdir():
                        os.replace(child, target / child.name)
                    src.rmdir()
                else:
                    os.replace(src, target)
        idx = self._load_index()
        if not any(p["id"] == pid for p in idx["profiles"]):
            vault = Vault(dest / "vault.json")
            name = vault.username() if vault.exists() else "Perfil"
            idx["profiles"].append({"id": pid, "display_name": name, "created_at": now_iso(),
                                    "migrated_from": "0.3.3"})
            self._save_index(idx)
        mark.unlink()
        return pid
