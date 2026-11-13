"""Síntese de fala (texto → voz), sempre no próprio computador.

Mecanismos, em ordem de preferência:
1. **Piper** (voz neural, natural). Roda como PROGRAMA SEPARADO (subprocesso): o NEXUS não
   embute o Piper nem o espeak-ng (GPL), só conversa com o executável que o usuário instalou.
   Voz padrão: `pt_BR-cadu-medium` (masculina, ~137 Hz; dados CC0). Alternativa: `jeff`.
2. **Voz do Windows** (SAPI, via PowerShell e System.Speech): prefere uma voz masculina pt-BR
   (ex.: "Microsoft Daniel"). Não precisa instalar nada.
3. **espeak-ng** (Linux, para desenvolvimento).

O texto vai pela entrada padrão do subprocesso, nunca pela linha de comando (sem injeção e
sem aparecer na lista de processos). Nada é gravado em disco.
"""

from __future__ import annotations

import json
import shutil
import subprocess  # noqa: S404 - mecanismos de voz externos, sem shell
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from nexus_intel.infrastructure.voice import effects
from nexus_intel.infrastructure.voice.audio import Player

DEFAULT_VOICE = "pt_BR-cadu-medium"
MAX_SPEAK_CHARS = 1500
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW


@dataclass
class VoiceSettings:
    engine: str = "auto"  # auto, piper, windows, espeak, off
    piper_command: str = ""  # caminho do executável piper (vazio = procurar)
    voice_dir: str = ""  # pasta com os modelos .onnx
    voice: str = DEFAULT_VOICE
    timbre: bool = True  # "assistente digital"
    deepen: float = 0.94
    speed: float = 1.0  # >1 = mais rápido

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> VoiceSettings:
        d = d or {}
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)


# ======================================================================= Piper
def piper_command(configured: str = "") -> list[str] | None:
    if configured and Path(configured).is_file():
        return [configured]
    found = shutil.which("piper")
    if found:
        return [found]
    if not getattr(sys, "frozen", False):  # rodando do código-fonte: `python -m piper` instalado à parte
        try:
            import importlib.util

            if importlib.util.find_spec("piper") is not None:
                return [sys.executable, "-m", "piper"]
        except (ImportError, ValueError):
            pass
    return None


def voice_files(voice_dir: Path, voice: str) -> tuple[Path, Path] | None:
    model = voice_dir / f"{voice}.onnx"
    config = voice_dir / f"{voice}.onnx.json"
    return (model, config) if model.is_file() and config.is_file() else None


def installed_voices(voice_dir: Path) -> list[str]:
    if not voice_dir.is_dir():
        return []
    return sorted(p.name[:-5] for p in voice_dir.glob("*.onnx") if (voice_dir / f"{p.name}.json").is_file())


class PiperEngine:
    name = "Piper (voz neural)"

    def __init__(self, command: list[str], model: Path, config: Path, *, timbre: bool = True,
                 deepen: float = 0.94, speed: float = 1.0) -> None:
        self.command, self.model, self.timbre, self.deepen = command, model, timbre, deepen
        self.speed = max(0.5, min(2.0, speed))
        cfg = json.loads(config.read_text("utf-8"))
        self.rate = int(cfg.get("audio", {}).get("sample_rate", 22050))
        self._proc: subprocess.Popen[bytes] | None = None

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        length = 1.0 / self.speed
        if self.timbre:
            length *= self.deepen  # compensa o estiramento que deixa a voz mais grave
        args = [*self.command, "--model", str(self.model), "--output-raw", "--length-scale", f"{length:.3f}"]
        self._proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,  # noqa: S603
                                      stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
        try:
            raw, _ = self._proc.communicate(text.encode("utf-8"), timeout=120)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            raise RuntimeError("A síntese de voz demorou demais.") from None
        finally:
            code, self._proc = (self._proc.returncode if self._proc else 0), None
        if code not in (0, None) and not raw:
            raise RuntimeError("O Piper não conseguiu sintetizar a fala. Confira o executável e a voz.")
        pcm = np.frombuffer(raw[: len(raw) // 2 * 2], dtype=np.int16)
        if self.timbre:
            pcm = effects.assistant_timbre(pcm, self.rate, deepen=self.deepen)
        return pcm, self.rate

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.kill()


# ==================================================================== Windows
_SAPI_SCRIPT = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo }
$pick = $v | Where-Object { $_.Culture.Name -eq 'pt-BR' -and $_.Gender -eq 'Male' } | Select-Object -First 1
if (-not $pick) { $pick = $v | Where-Object { $_.Culture.Name -like 'pt*' } | Select-Object -First 1 }
if ($pick) { $s.SelectVoice($pick.Name) }
$s.Rate = [int]$env:NEXUS_TTS_RATE
$s.Speak([Console]::In.ReadToEnd())
"""


class WindowsEngine:
    name = "Voz do Windows"

    def __init__(self, speed: float = 1.0) -> None:
        self.rate = max(-10, min(10, int(round((speed - 1.0) * 10))))
        self._proc: subprocess.Popen[bytes] | None = None

    @staticmethod
    def available() -> bool:
        return sys.platform == "win32" and shutil.which("powershell") is not None

    def speak(self, text: str) -> None:
        import os

        env = {**os.environ, "NEXUS_TTS_RATE": str(self.rate)}
        self._proc = subprocess.Popen(  # noqa: S603
            [shutil.which("powershell") or "powershell", "-NoProfile", "-NonInteractive", "-Command", _SAPI_SCRIPT],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
            creationflags=_NO_WINDOW)
        try:
            self._proc.communicate(text.encode("utf-8"), timeout=300)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        finally:
            self._proc = None

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.kill()


# ===================================================================== espeak
class EspeakEngine:
    name = "espeak-ng"

    def __init__(self, speed: float = 1.0) -> None:
        self.exe = shutil.which("espeak-ng") or shutil.which("espeak")
        self.wpm = int(165 * speed)

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        import io
        import wave

        if not self.exe:
            raise RuntimeError("espeak-ng não instalado.")
        out = subprocess.run([self.exe, "-v", "pt-br+m3", "-s", str(self.wpm), "--stdout"],  # noqa: S603
                             input=text.encode("utf-8"), capture_output=True, timeout=60, check=False).stdout
        with wave.open(io.BytesIO(out)) as w:
            return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16), w.getframerate()

    def stop(self) -> None:
        pass


# ==================================================================== Speaker
def choose_engine(settings: VoiceSettings) -> Any | None:
    """Escolhe o mecanismo conforme a configuração. Devolve None se nenhum estiver disponível."""
    if settings.engine == "off":
        return None
    if settings.engine in ("auto", "piper"):
        cmd = piper_command(settings.piper_command)
        files = voice_files(Path(settings.voice_dir), settings.voice) if settings.voice_dir else None
        if cmd and files:
            return PiperEngine(cmd, *files, timbre=settings.timbre, deepen=settings.deepen, speed=settings.speed)
        if settings.engine == "piper":
            return None
    if settings.engine in ("auto", "windows") and WindowsEngine.available():
        return WindowsEngine(settings.speed)
    if settings.engine in ("auto", "espeak") and (shutil.which("espeak-ng") or shutil.which("espeak")):
        return EspeakEngine(settings.speed)
    return None


def describe(settings: VoiceSettings) -> tuple[bool, str]:
    """(disponível, descrição) para a interface."""
    if settings.engine == "off":
        return False, "Voz desligada"
    eng = choose_engine(settings)
    if eng is None:
        if settings.engine in ("auto", "piper") and not piper_command(settings.piper_command):
            return False, "Nenhuma voz disponível: instale o Piper e a voz pt_BR-cadu (veja Configurar voz)."
        return False, f"Voz {settings.voice} não encontrada na pasta de vozes."
    if isinstance(eng, PiperEngine):
        return True, f"{eng.name}: {settings.voice}" + (" · timbre de assistente" if settings.timbre else "")
    return True, eng.name


class Speaker:
    """Fala um texto por vez, numa thread; uma nova fala interrompe a anterior."""

    def __init__(self, on_state: Callable[[bool], Any] | None = None) -> None:
        self.on_state = on_state
        self.player = Player()
        self._engine: Any = None
        self._thread: threading.Thread | None = None
        self._gen = 0

    def speak(self, text: str, settings: VoiceSettings) -> bool:
        text = " ".join(text.split())[:MAX_SPEAK_CHARS]
        engine = choose_engine(settings)
        if not text or engine is None:
            return False
        self.stop()
        self._gen += 1
        gen = self._gen
        self._engine = engine

        def work() -> None:
            try:
                if self.on_state:
                    self.on_state(True)
                if isinstance(engine, WindowsEngine):
                    engine.speak(text)
                else:
                    pcm, rate = engine.synthesize(text)
                    if gen == self._gen:
                        self.player.play(pcm, rate)
            except Exception:  # noqa: BLE001, S110 - falha de voz nunca derruba o app
                pass
            finally:
                if self.on_state and gen == self._gen:
                    self.on_state(False)

        self._thread = threading.Thread(target=work, name="nexus-voz", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._gen += 1
        if self._engine is not None:
            self._engine.stop()
        self.player.stop()
        if self.on_state:
            self.on_state(False)

    @property
    def speaking(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
