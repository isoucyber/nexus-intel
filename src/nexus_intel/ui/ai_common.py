"""Peças compartilhadas pelas telas de IA: preferências e execução em segundo plano.

Regra de threads: só a chamada ao mecanismo de IA, a síntese de voz e a transcrição rodam
fora da thread da interface. O banco do projeto é lido sempre na thread da interface.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from shiboken6 import isValid

from nexus_intel.domain.errors import NexusError
from nexus_intel.infrastructure.ai.client import DEFAULT_BASE_URL
from nexus_intel.infrastructure.paths import default_paths
from nexus_intel.infrastructure.voice.tts import VoiceSettings

PREFS_VERSION = 2
_CHAT_HINTS = ("qwen", "llama", "mistral", "gemma", "phi", "granite", "deepseek", "hermes", "command")
_EMBED_HINTS = ("embed", "bge", "nomic", "e5", "minilm", "gte", "arctic")


@dataclass
class AiPrefs:
    base_url: str = DEFAULT_BASE_URL
    model: str = ""  # vazio = escolher automaticamente entre os instalados
    embed_model: str = ""
    include_sensitive: bool = False
    auto_speak: bool = True
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    voice_root: str = ""  # vazio = pasta de dados do NEXUS / voz
    version: int = PREFS_VERSION

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> AiPrefs:
        d = dict(d or {})
        voice = VoiceSettings.from_dict(d.pop("voice", None))
        if int(d.get("version", 1)) < 2:  # 0.4-dev: timbre metálico deixava a voz robótica
            voice.timbre, voice.engine = False, "auto"
        known = {k: d[k] for k in ("base_url", "model", "embed_model", "include_sensitive", "auto_speak",
                                   "voice_root") if k in d}
        return cls(**known, voice=voice)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def root(self) -> Path:
        return Path(self.voice_root) if self.voice_root else default_paths().voice

    @property
    def voices_dir(self) -> Path:
        return self.root / "vozes"

    @property
    def whisper_dir(self) -> Path:
        return self.root / "modelos" / "whisper-small"

    def voice_settings(self) -> VoiceSettings:
        v = VoiceSettings(**asdict(self.voice))
        v.root = str(self.root)
        return v


def pick_chat_model(models: list[str], preferred: str = "") -> str:
    if preferred and preferred in models:
        return preferred
    chat = [m for m in models if not any(h in m.lower() for h in _EMBED_HINTS)]
    for hint in _CHAT_HINTS:
        for m in chat:
            if hint in m.lower():
                return m
    return chat[0] if chat else (preferred or "")


def pick_embed_model(models: list[str], preferred: str = "") -> str:
    if preferred and preferred in models:
        return preferred
    return next((m for m in models if any(h in m.lower() for h in _EMBED_HINTS)), "")


class PrefsStore:
    """Lê e grava as preferências de IA (no banco cifrado do perfil, quando houver sessão)."""

    def __init__(self, get: Callable[[], dict[str, Any] | None] | None = None,
                 put: Callable[[dict[str, Any]], Any] | None = None) -> None:
        self._get, self._put = get, put
        self._mem: dict[str, Any] = {}

    def load(self) -> AiPrefs:
        return AiPrefs.from_dict(self._get() if self._get else self._mem)

    def save(self, prefs: AiPrefs) -> None:
        if self._put:
            self._put(prefs.to_dict())
        else:
            self._mem = prefs.to_dict()


# ------------------------------------------------------------------ threads
class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Job(QRunnable):
    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.fn()
        except NexusError as exc:
            self.signals.failed.emit(exc.user_message)
        except Exception as exc:  # noqa: BLE001 - qualquer falha vira mensagem, nunca derruba a interface
            self.signals.failed.emit(str(exc) or exc.__class__.__name__)
        else:
            self.signals.done.emit(result)


def run_async(owner: QObject, fn: Callable[[], Any], on_done: Callable[[Any], Any],
              on_fail: Callable[[str], Any] | None = None) -> None:
    """Roda `fn` no pool de threads e entrega o resultado na thread da interface,
    só se `owner` ainda existir (a tela pode ter sido fechada ou bloqueada)."""
    job = _Job(fn)
    jobs: set[Any] = owner.__dict__.setdefault("_ai_jobs", set())
    jobs.add(job.signals)

    def finish(cb: Callable[[Any], Any] | None, value: Any) -> None:
        jobs.discard(job.signals)
        if cb is not None and isValid(owner):
            cb(value)

    job.signals.done.connect(lambda r: finish(on_done, r))
    job.signals.failed.connect(lambda m: finish(on_fail, m))
    QThreadPool.globalInstance().start(job)
