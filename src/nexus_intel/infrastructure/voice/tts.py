"""Síntese de fala (texto → voz), sempre no próprio computador.

Mecanismos, em ordem de preferência no modo "auto":
1. **Kokoro** (voz neural, a mais humana): modelo Apache-2.0, voz masculina `pm_alex`
   (~133 Hz). Roda como PROCESSO SEPARADO e PERSISTENTE, no ambiente Python próprio criado por
   `tools/baixar_voz.py` (com o `kokoro-onnx` e o espeak-ng, GPL, instalados à parte): o modelo
   carrega uma vez e cada frase sai em fração de segundo.
2. **Piper** (voz neural): programa separado; voz `pt_BR-cadu-medium` (masculina, ~137 Hz, CC0).
3. **Voz do Windows** (SAPI via PowerShell): sem instalação, mas soa robótica.
4. **espeak-ng** (Linux, desenvolvimento).

Latência: o texto é dividido em trechos de uma ou poucas frases; o primeiro trecho começa a
tocar enquanto os seguintes ainda estão sendo sintetizados (fila de síntese + fila de áudio).

O texto vai aos mecanismos pela entrada padrão, nunca pela linha de comando. Nada vai para o disco.
"""

from __future__ import annotations

import atexit
import json
import os
import queue
import re
import shutil
import struct
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

DEFAULT_VOICE = "pt_BR-cadu-medium"  # Piper
DEFAULT_KOKORO_VOICE = "pm_alex"
KOKORO_VOICES = {"pm_alex": "Alex (masculina, padrão)", "pm_santa": "Santa (masculina)", "pf_dora": "Dora (feminina)"}
KOKORO_RATE = 24000
MAX_SPEAK_CHARS = 3000
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
_WORKER = Path(__file__).with_name("kokoro_worker.py")


@dataclass
class VoiceSettings:
    engine: str = "auto"  # auto, kokoro, piper, windows, espeak, off
    root: str = ""  # pasta "voz" (vozes, modelos e ambientes separados)
    kokoro_voice: str = DEFAULT_KOKORO_VOICE
    piper_command: str = ""  # executável do piper (vazio = procurar)
    voice_dir: str = ""  # pasta das vozes do Piper (vazio = <root>/vozes)
    voice: str = DEFAULT_VOICE  # voz do Piper
    timbre: bool = False  # "assistente digital": ecos curtos e voz mais grave (soa mais sintético)
    deepen: float = 0.94
    speed: float = 1.0  # >1 = mais rápido

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> VoiceSettings:
        d = d or {}
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)

    @property
    def root_path(self) -> Path | None:
        return Path(self.root) if self.root else None

    @property
    def piper_voices(self) -> Path | None:
        if self.voice_dir:
            return Path(self.voice_dir)
        return self.root_path / "vozes" if self.root_path else None


def _venv_exe(env: Path, name: str) -> Path:
    return env / ("Scripts" if os.name == "nt" else "bin") / (f"{name}.exe" if os.name == "nt" else name)


# ====================================================================== Kokoro
def kokoro_files(root: Path | None) -> tuple[Path, Path, Path] | None:
    """(python do ambiente separado, modelo, vozes) se o Kokoro estiver instalado."""
    if root is None:
        return None
    py = _venv_exe(root / "kokoro-venv", "python")
    model, voices = root / "kokoro" / "model.onnx", root / "kokoro" / "voices-ptbr.npz"
    return (py, model, voices) if py.is_file() and model.is_file() and voices.is_file() else None


class KokoroEngine:
    """Conversa com um processo Kokoro persistente (um por modelo, compartilhado)."""

    name = "Kokoro (voz neural humana)"
    rate = KOKORO_RATE
    chunked = True
    _procs: dict[tuple[str, str, str], subprocess.Popen[bytes]] = {}
    _lock = threading.Lock()

    def __init__(self, python: Path, model: Path, voices: Path, *, voice: str = DEFAULT_KOKORO_VOICE,
                 speed: float = 1.0, timbre: bool = False, deepen: float = 0.94) -> None:
        self.key = (str(python), str(model), str(voices))
        self.voice = voice if voice in KOKORO_VOICES else DEFAULT_KOKORO_VOICE
        self.speed = max(0.6, min(1.6, speed))
        self.timbre, self.deepen = timbre, deepen

    def _proc(self) -> subprocess.Popen[bytes]:
        p = self._procs.get(self.key)
        if p is not None and p.poll() is None:
            return p
        p = subprocess.Popen([self.key[0], str(_WORKER), self.key[1], self.key[2]],  # noqa: S603
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             creationflags=_NO_WINDOW)
        assert p.stdout is not None
        if _read_exact(p.stdout, 4) is None:  # sinal de pronto (modelo carregado)
            p.kill()
            raise RuntimeError("O Kokoro não iniciou. Rode de novo: python tools/baixar_voz.py")
        self._procs[self.key] = p
        return p

    def warm(self) -> None:
        with self._lock:
            self._proc()

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        with self._lock:
            p = self._proc()
            assert p.stdin is not None and p.stdout is not None
            speed = self.speed * (self.deepen if self.timbre else 1.0)
            line = json.dumps({"text": text, "voice": self.voice, "speed": speed}, ensure_ascii=False)
            p.stdin.write(line.encode("utf-8") + b"\n")
            p.stdin.flush()
            head = _read_exact(p.stdout, 4)
            if head is None:
                raise RuntimeError("O processo de voz Kokoro terminou inesperadamente.")
            raw = _read_exact(p.stdout, struct.unpack("<I", head)[0]) or b""
        pcm = np.frombuffer(raw, dtype="<i2").astype(np.int16)
        if self.timbre:
            pcm = effects.assistant_timbre(pcm, self.rate, deepen=self.deepen)
        return pcm, self.rate

    def stop(self) -> None:
        """Não encerra o processo (fica pronto para a próxima fala); a fila descarta o resto."""

    @classmethod
    def shutdown_all(cls) -> None:
        for p in cls._procs.values():
            if p.poll() is None:
                p.kill()
        cls._procs.clear()


def _read_exact(stream: Any, n: int) -> bytes | None:
    buf = b""
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


atexit.register(KokoroEngine.shutdown_all)


# ======================================================================= Piper
def piper_command(configured: str = "", root: Path | None = None) -> list[str] | None:
    if configured and Path(configured).is_file():
        return [configured]
    if root is not None:  # ambiente separado criado por tools/baixar_voz.py --instalar-piper
        exe = _venv_exe(root / "piper-venv", "piper")
        if exe.is_file():
            return [str(exe)]
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
    chunked = False  # cada chamada carrega o modelo: melhor sintetizar o texto inteiro de uma vez

    def __init__(self, command: list[str], model: Path, config: Path, *, timbre: bool = False,
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
    name = "Voz do Windows (robótica)"
    chunked = False

    def __init__(self, speed: float = 1.0) -> None:
        self.rate = max(-10, min(10, int(round((speed - 1.0) * 10))))
        self._proc: subprocess.Popen[bytes] | None = None

    @staticmethod
    def available() -> bool:
        return sys.platform == "win32" and shutil.which("powershell") is not None

    def speak(self, text: str) -> None:
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
    chunked = True

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


# =================================================================== escolha
def choose_engine(settings: VoiceSettings) -> Any | None:
    """Escolhe o mecanismo conforme a configuração. Devolve None se nenhum estiver disponível."""
    eng = settings.engine
    if eng == "off":
        return None
    if eng in ("auto", "kokoro"):
        files = kokoro_files(settings.root_path)
        if files:
            return KokoroEngine(*files, voice=settings.kokoro_voice, speed=settings.speed,
                                timbre=settings.timbre, deepen=settings.deepen)
        if eng == "kokoro":
            return None
    if eng in ("auto", "piper"):
        cmd = piper_command(settings.piper_command, settings.root_path)
        voices = settings.piper_voices
        files2 = voice_files(voices, settings.voice) if voices else None
        if cmd and files2:
            return PiperEngine(cmd, *files2, timbre=settings.timbre, deepen=settings.deepen, speed=settings.speed)
        if eng == "piper":
            return None
    if eng in ("auto", "windows") and WindowsEngine.available():
        return WindowsEngine(settings.speed)
    if eng in ("auto", "espeak") and (shutil.which("espeak-ng") or shutil.which("espeak")):
        return EspeakEngine(settings.speed)
    return None


def describe(settings: VoiceSettings) -> tuple[bool, str]:
    """(disponível, descrição) para a interface."""
    if settings.engine == "off":
        return False, "Voz desligada"
    eng = choose_engine(settings)
    if eng is None:
        if settings.engine == "kokoro":
            return False, "Kokoro não instalado. Rode: python tools/baixar_voz.py"
        if settings.engine == "piper":
            return False, f"Piper ou a voz {settings.voice} não encontrados. Rode: python tools/baixar_voz.py --piper"
        return False, "Nenhuma voz disponível. Rode: python tools/baixar_voz.py"
    if isinstance(eng, KokoroEngine):
        return True, f"{eng.name}: {KOKORO_VOICES.get(eng.voice, eng.voice)}"
    if isinstance(eng, PiperEngine):
        return True, f"{eng.name}: {settings.voice}"
    if isinstance(eng, WindowsEngine):
        return True, f"{eng.name} — para voz humana, rode: python tools/baixar_voz.py"
    return True, eng.name


# =================================================================== frases
_SENT = re.compile(r"(?<=[.!?…:;])\s+")


def split_for_speech(text: str, first_min: int = 12, min_len: int = 80, max_len: int = 260) -> list[str]:
    """Divide em trechos: o primeiro curto (começa a tocar logo), os demais com 80–260 caracteres
    (o Kokoro soa melhor com trechos médios). Frases longas são cortadas em vírgulas."""
    sentences: list[str] = []
    for s in _SENT.split(" ".join(text.split())):
        while len(s) > max_len:
            cut = s.rfind(", ", 0, max_len)
            cut = cut + 1 if cut > max_len // 3 else max_len
            sentences.append(s[:cut].strip())
            s = s[cut:].strip()
        if s:
            sentences.append(s)
    chunks: list[str] = []
    for s in sentences:
        limit = first_min if len(chunks) == 1 else min_len  # o 1º trecho tem limite próprio (toca logo)
        if chunks and len(chunks[-1]) < limit and len(chunks[-1]) + len(s) + 1 <= max_len:
            chunks[-1] += " " + s
        else:
            chunks.append(s)
    if len(chunks) > 2 and len(chunks[-1]) < 25 and len(chunks[-2]) + len(chunks[-1]) + 1 <= max_len:
        last = chunks.pop()  # frase final muito curta soa melhor junto da anterior
        chunks[-1] += " " + last
    return chunks


# =================================================================== Speaker
_END = object()


class Speaker:
    """Fala em fluxo: `begin` → `feed` (quantas vezes quiser) → `finish`. Uma nova fala
    interrompe a anterior. `speak(texto)` faz as três coisas de uma vez."""

    def __init__(self, on_state: Callable[[bool], Any] | None = None) -> None:
        self.on_state = on_state
        self.player = Player()
        self._engine: Any = None
        self._gen = 0
        self._texts: queue.Queue[Any] = queue.Queue()
        self._pending = ""  # texto recebido no fluxo que ainda não fecha uma frase
        self._active = False

    # --------------------------------------------------------------- fluxo
    def begin(self, settings: VoiceSettings) -> bool:
        engine = choose_engine(settings)
        if engine is None:
            return False
        self.stop()
        self._gen += 1
        gen, self._engine, self._pending = self._gen, engine, ""
        texts: queue.Queue[Any] = queue.Queue()
        audio: queue.Queue[Any] = queue.Queue(maxsize=4)
        self._texts = texts
        self._active = True

        def synth() -> None:
            buffer: list[str] = []
            while gen == self._gen:
                item = texts.get()
                if item is _END or not engine.chunked:
                    if item is not _END:
                        buffer.append(item)
                        continue
                    if buffer:  # mecanismos sem trechos: tudo de uma vez no fim
                        self._produce(engine, " ".join(buffer), audio, gen)
                    break
                self._produce(engine, item, audio, gen)
            audio.put(_END)

        def play() -> None:
            if self.on_state:
                self.on_state(True)
            try:
                while gen == self._gen:
                    item = audio.get()
                    if item is _END:
                        break
                    kind, payload, rate = item
                    if gen != self._gen:
                        break
                    if kind == "say":
                        engine.speak(payload)
                    else:
                        self.player.play(payload, rate)
            finally:
                if gen == self._gen:
                    self._active = False
                    if self.on_state:
                        self.on_state(False)

        threading.Thread(target=synth, name="nexus-voz-sintese", daemon=True).start()
        threading.Thread(target=play, name="nexus-voz-som", daemon=True).start()
        return True

    def _produce(self, engine: Any, text: str, audio: queue.Queue[Any], gen: int) -> None:
        if gen != self._gen or not text.strip():
            return
        try:
            if isinstance(engine, WindowsEngine):
                audio.put(("say", text, 0))
            else:
                pcm, rate = engine.synthesize(text)
                if gen == self._gen:
                    audio.put(("pcm", pcm, rate))
        except Exception:  # noqa: BLE001, S110 - falha de voz nunca derruba o app
            pass

    def feed(self, text: str) -> None:
        """Recebe texto (pode ser um pedaço de frase); envia à síntese cada frase completa."""
        if not self._active:
            return
        self._pending += text
        parts = _SENT.split(self._pending)
        if len(parts) > 1:
            done, self._pending = " ".join(parts[:-1]), parts[-1]
            for chunk in split_for_speech(done, first_min=0, min_len=0):
                self._texts.put(chunk)

    def finish(self) -> None:
        if not self._active:
            return
        if self._pending.strip():
            for chunk in split_for_speech(self._pending, first_min=0, min_len=0):
                self._texts.put(chunk)
        self._pending = ""
        self._texts.put(_END)

    def speak(self, text: str, settings: VoiceSettings) -> bool:
        text = " ".join(text.split())[:MAX_SPEAK_CHARS]
        if not text or not self.begin(settings):
            return False
        for chunk in split_for_speech(text):
            self._texts.put(chunk)
        self._texts.put(_END)
        return True

    def stop(self) -> None:
        self._gen += 1
        self._active = False
        self._texts.put(_END)
        if self._engine is not None:
            self._engine.stop()
        self.player.stop()
        if self.on_state:
            self.on_state(False)

    def warm(self, settings: VoiceSettings) -> None:
        """Carrega o mecanismo de voz em segundo plano (a primeira fala sai sem espera)."""
        engine = choose_engine(settings)
        if isinstance(engine, KokoroEngine):
            threading.Thread(target=engine.warm, name="nexus-voz-aquecer", daemon=True).start()

    @property
    def speaking(self) -> bool:
        return self._active
