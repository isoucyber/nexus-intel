"""0.4: cliente de IA (só loopback) e voz (timbre, configuração, texto por stdin)."""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import pytest

from nexus_intel.infrastructure.ai.client import (
    AiAddressRejected,
    AiUnavailable,
    LocalLlmClient,
    is_loopback,
    normalize_base_url,
)
from nexus_intel.infrastructure.voice import effects, tts


# ------------------------------------------------------------------ endereço
@pytest.mark.parametrize("url", ["http://127.0.0.1:11434", "localhost:1234", "http://[::1]:8080/v1",
                                 "http://127.0.0.5:80"])
def test_loopback_addresses_are_accepted(url):
    assert normalize_base_url(url).startswith("http")
    assert not normalize_base_url(url).endswith("/v1")


@pytest.mark.parametrize("url", ["http://exemplo.com:11434", "http://192.168.0.10:11434", "http://10.0.0.1",
                                 "http://127.0.0.1.nip.io:11434", "ftp://127.0.0.1", "http://user:pw@127.0.0.1"])
def test_remote_or_odd_addresses_are_rejected(url):
    with pytest.raises(AiAddressRejected):
        normalize_base_url(url)


def test_remote_needs_explicit_opt_in():
    assert normalize_base_url("https://ia.exemplo.com", allow_remote=True) == "https://ia.exemplo.com"
    assert is_loopback("localhost") and not is_loopback("localhost.exemplo.com")


# ------------------------------------------------------------------ servidor falso
class _Handler(BaseHTTPRequestHandler):
    routes: dict = {}
    seen: list = []

    def log_message(self, *a):  # silencioso
        pass

    def _send(self, code, obj, headers=None):
        body = json.dumps(obj).encode() if not isinstance(obj, bytes) else obj
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        self.seen.append(("GET", self.path, None))
        self._send(*self.routes.get(self.path, (404, {"error": "?"})))

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", 0))
        self.seen.append(("POST", self.path, json.loads(self.rfile.read(n))))
        self._send(*self.routes.get(self.path, (404, {"error": "?"})))


@pytest.fixture
def server():
    _Handler.routes, _Handler.seen = {}, []
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_compatible_server_chat_stream_and_embed(server):
    _httpd, url = server
    sse = "".join(f"data: {json.dumps(e)}\n\n" for e in [
        {"choices": [{"delta": {"content": "Olá, "}}]},
        {"choices": [{"delta": {"content": "Daniel."}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "x", "function": {"name": "buscar",
                                                                                 "arguments": "{\"consulta\""}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": ": \"a\"}"}}]}}]},
    ]) + "data: [DONE]\n\n"
    _Handler.routes = {
        "/v1/models": (200, {"data": [{"id": "qwen2.5:7b"}, {"id": "bge-m3"}]}),
        "/v1/chat/completions": (200, sse.encode()),
        "/v1/embeddings": (200, {"data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}]}),
    }
    c = LocalLlmClient(url)
    st = c.status()
    assert st.available and st.kind == "Servidor compatível" and not c.native and st.models == ["bge-m3", "qwen2.5:7b"]
    pieces = []
    msg = c.chat("qwen2.5:7b", [{"role": "user", "content": "oi"}], tools=[{"type": "function"}], on_text=pieces.append)
    assert "".join(pieces) == "Olá, Daniel." and msg.content == "Olá, Daniel."
    assert msg.tool_calls[0].name == "buscar" and msg.tool_calls[0].arguments == {"consulta": "a"}
    sent = [s for s in _Handler.seen if s[1] == "/v1/chat/completions"][0][2]
    assert sent["tool_choice"] == "auto" and sent["stream"] is True
    assert c.embed("bge-m3", ["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]


def test_ollama_native_keeps_model_loaded_and_streams(server):
    _httpd, url = server
    nd = "\n".join(json.dumps(e) for e in [
        {"message": {"content": "Abrindo "}, "done": False},
        {"message": {"content": "o grafo."}, "done": False},
        {"message": {"content": "", "tool_calls": [{"function": {"name": "abrir_tela", "arguments": {"tela": "grafo"}}}]},
         "done": True},
    ]) + "\n"
    _Handler.routes = {"/v1/models": (200, {"data": [{"id": "qwen2.5:7b"}]}), "/api/version": (200, {"version": "0.9"}),
                       "/api/chat": (200, nd.encode())}
    c = LocalLlmClient(url)
    assert c.status().kind == "Ollama" and c.native
    pieces = []
    history = [{"role": "user", "content": "abre o grafo"},
               {"role": "assistant", "content": "", "tool_calls": [
                   {"id": "1", "type": "function", "function": {"name": "buscar", "arguments": "{\"consulta\": \"x\"}"}}]},
               {"role": "tool", "tool_call_id": "1", "name": "buscar", "content": "{}"}]
    msg = c.chat("qwen2.5:7b", history, tools=[{"type": "function"}], on_text=pieces.append)
    assert "".join(pieces) == "Abrindo o grafo." and msg.tool_calls[0].arguments == {"tela": "grafo"}
    sent = [s for s in _Handler.seen if s[1] == "/api/chat"][0][2]
    assert sent["keep_alive"] == "30m" and sent["options"]["num_ctx"] >= 8192 and sent["stream"] is True
    assert sent["messages"][1]["tool_calls"][0]["function"]["arguments"] == {"consulta": "x"}  # objeto, não texto
    assert sent["messages"][2]["tool_name"] == "buscar"


def test_tool_call_written_as_text_is_never_streamed_to_screen(server):
    _httpd, url = server
    sse = "".join(f"data: {json.dumps({'choices': [{'delta': {'content': p}}]})}\n\n"
                  for p in ["<tool", "_call>{\"name\": \"buscar\", \"arguments\": {}}", "</tool_call>"])
    _Handler.routes = {"/v1/models": (200, {"data": [{"id": "m"}]}), "/v1/chat/completions": (200, sse.encode())}
    c = LocalLlmClient(url)
    c.status()
    pieces = []
    msg = c.chat("m", [{"role": "user", "content": "x"}], on_text=pieces.append)
    assert pieces == [] and msg.tool_calls[0].name == "buscar"


def test_redirects_are_not_followed(server):
    _httpd, url = server
    _Handler.routes = {"/v1/models": (302, b"", {"Location": "http://exemplo.com/v1/models"})}
    with pytest.raises(AiUnavailable):
        LocalLlmClient(url)._request("GET", "/v1/models")
    assert not LocalLlmClient(url).status().available
    assert all(path.startswith("/") for _m, path, _b in _Handler.seen)  # nunca seguiu para outro host


def test_unreachable_engine_reports_unavailable():
    st = LocalLlmClient("http://127.0.0.1:9").status()  # porta 9: ninguém ouvindo
    assert not st.available and "não respondeu" in st.detail


# ------------------------------------------------------------------ voz
def _tone(freq: float, rate: int = 22050, seconds: float = 1.0) -> np.ndarray:
    t = np.arange(int(rate * seconds)) / rate
    return (0.5 * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)


def test_assistant_timbre_deepens_voice_and_keeps_level_safe():
    pcm = _tone(140)
    out = effects.assistant_timbre(pcm, 22050, deepen=0.9)
    assert out.dtype == np.int16 and np.abs(out).max() <= 32767 * 0.9
    assert out.size == pytest.approx(pcm.size / 0.9, rel=0.01)  # a síntese compensa com length_scale
    assert effects.estimate_pitch(out, 22050) == pytest.approx(140 * 0.9, rel=0.05)
    assert effects.assistant_timbre(np.zeros(0, np.int16), 22050).size == 0


def test_voice_settings_from_partial_dict_and_off():
    s = tts.VoiceSettings.from_dict({"engine": "off", "timbre": False, "desconhecido": 1})
    assert s.engine == "off" and not s.timbre and s.voice == tts.DEFAULT_VOICE
    assert tts.choose_engine(s) is None
    assert tts.describe(s) == (False, "Voz desligada")


def test_piper_engine_gets_text_by_stdin_not_argv(tmp_path):
    """O texto (que pode conter dados do projeto) vai pela entrada padrão, nunca na linha de comando."""
    fake = tmp_path / "fake_piper.py"
    log = tmp_path / "argv.json"
    fake.write_text(
        "import sys, json\n"
        f"json.dump({{'argv': sys.argv, 'stdin': sys.stdin.read()}}, open({str(log)!r}, 'w'))\n"
        "sys.stdout.buffer.write(b'\\x00\\x10' * 2205)\n")
    model, config = tmp_path / "v.onnx", tmp_path / "v.onnx.json"
    model.write_bytes(b"x")
    config.write_text(json.dumps({"audio": {"sample_rate": 22050}}))
    evil = "Olá; rm -rf / && $(echo hack) \"--model\" /etc/passwd"
    eng = tts.PiperEngine([sys.executable, str(fake)], model, config, timbre=True, deepen=0.94)
    pcm, rate = eng.synthesize(evil)
    seen = json.loads(log.read_text())
    assert seen["stdin"] == evil and evil not in " ".join(seen["argv"])
    assert "--output-raw" in seen["argv"] and rate == 22050 and pcm.size > 0
    length = float(seen["argv"][seen["argv"].index("--length-scale") + 1])
    assert length == pytest.approx(0.94, abs=0.001)


def test_installed_voices_lists_only_complete_pairs(tmp_path):
    (tmp_path / "pt_BR-cadu-medium.onnx").write_bytes(b"x")
    (tmp_path / "pt_BR-cadu-medium.onnx.json").write_text("{}")
    (tmp_path / "pt_BR-jeff-medium.onnx").write_bytes(b"x")  # sem .json
    assert tts.installed_voices(tmp_path) == ["pt_BR-cadu-medium"]


# ------------------------------------------------------------------ voz (0.4: Kokoro e fluxo)
def _venv_file(env, name):
    import os

    p = env / ("Scripts" if os.name == "nt" else "bin") / (f"{name}.exe" if os.name == "nt" else name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")
    return p


def test_piper_installed_by_script_is_found(tmp_path):
    """Bug da primeira versão: o Piper instalado em voz/piper-venv não era achado e a voz caía no Windows."""
    exe = _venv_file(tmp_path / "piper-venv", "piper")
    assert tts.piper_command("", tmp_path) == [str(exe)]


def test_kokoro_is_preferred_when_installed(tmp_path):
    assert tts.kokoro_files(tmp_path) is None
    py = _venv_file(tmp_path / "kokoro-venv", "python")
    (tmp_path / "kokoro").mkdir()
    (tmp_path / "kokoro" / "model.onnx").write_bytes(b"x")
    (tmp_path / "kokoro" / "voices-ptbr.npz").write_bytes(b"x")
    assert tts.kokoro_files(tmp_path)[0] == py
    eng = tts.choose_engine(tts.VoiceSettings(root=str(tmp_path)))
    assert isinstance(eng, tts.KokoroEngine) and eng.voice == "pm_alex"
    ok, desc = tts.describe(tts.VoiceSettings(root=str(tmp_path), kokoro_voice="pm_santa"))
    assert ok and "Santa" in desc


def test_old_prefs_with_metallic_timbre_are_reset():
    from nexus_intel.ui.ai_common import AiPrefs

    old = AiPrefs.from_dict({"voice": {"timbre": True, "engine": "windows"}})
    assert not old.voice.timbre and old.voice.engine == "auto"
    new = AiPrefs.from_dict({"version": 2, "voice": {"timbre": True, "engine": "piper"}})
    assert new.voice.timbre and new.voice.engine == "piper"


def test_split_for_speech_starts_short_and_keeps_medium_chunks():
    text = ("Helena é contadora. Ela é sócia da Vértice Importações e trabalha na Aurora Logística. "
            "Interpreto que a data de nascimento merece revisão, porque há relatos conflitantes. Quer ver o grafo?")
    chunks = tts.split_for_speech(text)
    assert chunks[0] == "Helena é contadora."  # o primeiro trecho toca logo
    assert " ".join(chunks) == " ".join(text.split()) and all(len(c) <= 260 for c in chunks)
    long = "palavra, " * 80
    assert all(len(c) <= 260 for c in tts.split_for_speech(long))


def test_speaker_plays_first_chunk_before_synthesizing_the_rest(monkeypatch):
    import time as _time

    events = []

    class Slow:
        name, rate, chunked = "teste", 8000, True

        def synthesize(self, text):
            events.append(("sintetiza", text))
            _time.sleep(0.05)
            return np.zeros(80, np.int16), 8000

        def stop(self):
            pass

    monkeypatch.setattr(tts, "choose_engine", lambda s: Slow())
    sp = tts.Speaker()
    monkeypatch.setattr(sp.player, "play", lambda pcm, rate: events.append(("toca", pcm.size)))
    assert sp.begin(tts.VoiceSettings())
    sp.feed("Primeira frase completa. Segunda fra")
    sp.feed("se chegando aos poucos. ")
    sp.finish()
    deadline = _time.time() + 5
    while sp.speaking and _time.time() < deadline:
        _time.sleep(0.02)
    said = [e[1] for e in events if e[0] == "sintetiza"]
    assert said == ["Primeira frase completa.", "Segunda frase chegando aos poucos."]
    assert events.index(("toca", 80)) < events.index(("sintetiza", said[1])) + 2
    assert [e[0] for e in events].count("toca") == 2
