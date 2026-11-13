"""Pastas do sistema (seção 18.3), resolvidas por platformdirs.

`NEXUS_INTEL_HOME` sobrepõe tudo (usado em testes e instalação portátil).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import PlatformDirs

from nexus_intel import APP_NAME


@dataclass(frozen=True)
class AppPaths:
    data: Path
    config: Path
    logs: Path

    @property
    def vault(self) -> Path:
        return self.data / "vault.json"

    @property
    def app_db(self) -> Path:
        return self.data / "app.nxdb"

    @property
    def projects(self) -> Path:
        return self.data / "projects"

    @property
    def profiles_root(self) -> Path:
        return self.data / "profiles"

    @property
    def profiles_index(self) -> Path:
        return self.data / "profiles.json"

    @property
    def voice(self) -> Path:
        """Vozes e modelos de fala (`tools/baixar_voz.py`). Compartilhados entre perfis: não são dados pessoais."""
        return self.data / "voz"

    def for_profile(self, profile_id: str) -> AppPaths:
        """Pastas privadas de um perfil: cofre, banco e projetos ficam em profiles/<id>/."""
        return AppPaths(self.profiles_root / profile_id, self.config, self.logs)

    def ensure(self) -> AppPaths:
        for p in (self.data, self.config, self.logs, self.projects):
            p.mkdir(parents=True, exist_ok=True)
        return self


def default_paths() -> AppPaths:
    override = os.environ.get("NEXUS_INTEL_HOME")
    if override:
        base = Path(override)
        return AppPaths(base / "data", base / "config", base / "logs")
    d = PlatformDirs(APP_NAME, appauthor=False, roaming=True)
    return AppPaths(Path(d.user_data_dir), Path(d.user_config_dir), Path(d.user_log_dir))
