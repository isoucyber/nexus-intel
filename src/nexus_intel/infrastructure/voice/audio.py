"""Microfone e alto-falante.

Usa `sounddevice` (PortAudio) quando instalado (extra `[voz]`). Sem ele:
- reprodução no Windows cai para `winsound` (biblioteca padrão), a partir da memória;
- gravação fica indisponível (o botão de microfone explica o motivo).

Nada é gravado em disco: o áudio do microfone e a fala sintetizada ficam só na memória.
O microfone só fica aberto enquanto o usuário mantém a gravação ligada.
"""

from __future__ import annotations

import io
import shutil
import subprocess  # noqa: S404 - reprodutor do sistema, sem shell
import sys
import threading
import wave
from collections.abc import Callable
from typing import Any

import numpy as np

STT_RATE = 16000
MAX_RECORD_SECONDS = 120

try:  # pragma: no cover - depende do ambiente
    import sounddevice as _sd
except Exception:  # noqa: BLE001 - ImportError ou PortAudio ausente (OSError)
    _sd = None


def sounddevice_available() -> bool:
    return _sd is not None


def microphone_available() -> tuple[bool, str]:
    if _sd is None:
        return False, "Instale o suporte de voz: pip install \"nexus-intel[voz]\" (pacote sounddevice)."
    try:
        dev = _sd.query_devices(kind="input")
    except Exception:  # noqa: BLE001
        return False, "Nenhum microfone encontrado."
    return (True, str(dev.get("name", "Microfone"))) if dev else (False, "Nenhum microfone encontrado.")


def wav_bytes(pcm: np.ndarray, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.astype(np.int16).tobytes())
    return buf.getvalue()


class Player:
    """Toca PCM int16 mono, interrompível por `stop()`."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._proc: subprocess.Popen[bytes] | None = None

    def play(self, pcm: np.ndarray, rate: int) -> None:
        """Bloqueia até terminar ou até `stop()`. Rode numa thread."""
        self._stop.clear()
        if pcm.size == 0:
            return
        if _sd is not None:
            _sd.play(pcm, rate)
            duration = pcm.size / rate
            waited = 0.0
            while waited < duration + 0.3 and not self._stop.wait(0.05):
                waited += 0.05
            _sd.stop()
            return
        data = wav_bytes(pcm, rate)
        if sys.platform == "win32":  # pragma: no cover - Windows
            import winsound

            winsound.PlaySound(data, winsound.SND_MEMORY)
            return
        player = shutil.which("aplay") or shutil.which("paplay")
        if player:  # pragma: no cover - Linux de desenvolvimento
            self._proc = subprocess.Popen([player, "-"], stdin=subprocess.PIPE,  # noqa: S603
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                self._proc.communicate(data, timeout=pcm.size / rate + 10)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def stop(self) -> None:
        self._stop.set()
        if _sd is not None:
            try:
                _sd.stop()
            except Exception:  # noqa: BLE001, S110
                pass
        if self._proc is not None and self._proc.poll() is None:
            self._proc.kill()


class Recorder:
    """Grava do microfone em 16 kHz mono (formato do reconhecimento de fala)."""

    def __init__(self, on_level: Callable[[float], Any] | None = None) -> None:
        self.on_level = on_level
        self._chunks: list[np.ndarray] = []
        self._stream: Any = None
        self._lock = threading.Lock()

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        ok, why = microphone_available()
        if not ok:
            raise RuntimeError(why)
        self._chunks = []

        def callback(indata: np.ndarray, frames: int, _time: Any, _status: Any) -> None:
            with self._lock:
                if sum(c.size for c in self._chunks) < MAX_RECORD_SECONDS * STT_RATE:
                    self._chunks.append(indata[:, 0].copy())
            if self.on_level:
                self.on_level(float(np.sqrt(np.mean(indata[:, 0] ** 2))))

        self._stream = _sd.InputStream(samplerate=STT_RATE, channels=1, dtype="float32", callback=callback)
        self._stream.start()

    def stop(self) -> np.ndarray:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None
        with self._lock:
            audio = np.concatenate(self._chunks) if self._chunks else np.zeros(0, np.float32)
            self._chunks = []
        return audio
