"""Reconhecimento de fala (voz → texto), no próprio computador.

Usa o `faster-whisper` (MIT) com um modelo Whisper (MIT) baixado UMA vez para a pasta de
modelos do NEXUS (`tools/baixar_voz.py`). O NEXUS abre o modelo só da pasta local
(`local_files_only`): durante o uso, nenhum áudio nem texto sai do computador.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_MODEL = "whisper-small"
_REQUIRED = ("model.bin", "config.json")


def model_ready(model_dir: Path) -> bool:
    return model_dir.is_dir() and all((model_dir / f).is_file() for f in _REQUIRED)


def whisper_available() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("faster_whisper") is not None
    except (ImportError, ValueError):
        return False


def describe(model_dir: Path) -> tuple[bool, str]:
    if not whisper_available():
        return False, "Reconhecimento de fala não instalado: pip install \"nexus-intel[voz]\"."
    if not model_ready(model_dir):
        return False, f"Modelo de fala ausente em {model_dir}. Rode: python tools/baixar_voz.py"
    return True, f"Whisper local ({model_dir.name})"


class Transcriber:
    def __init__(self, model_dir: Path, threads: int = 4) -> None:
        self.model_dir = model_dir
        self.threads = threads
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(str(self.model_dir), device="cpu", compute_type="int8",
                                       cpu_threads=self.threads, local_files_only=True)
        return self._model

    def transcribe(self, audio: np.ndarray, language: str = "pt") -> str:
        """`audio`: float32 mono a 16 kHz."""
        if audio.size < 16000 * 0.3:  # menos de 0,3 s: nada a reconhecer
            return ""
        segments, _info = self._load().transcribe(
            audio.astype(np.float32), language=language, beam_size=1, vad_filter=True,
            initial_prompt="Comandos e perguntas para o assistente NEXUS sobre uma investigação.")
        return " ".join(s.text.strip() for s in segments).strip()
