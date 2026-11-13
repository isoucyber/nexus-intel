"""Conversa com um mecanismo de IA que roda no próprio computador.

Protocolo: a API compatível com OpenAI (`/v1/chat/completions`, `/v1/models`,
`/v1/embeddings`), que o Ollama, o LM Studio e o servidor do llama.cpp atendem.
Um único cliente serve os três; o Ollama é o padrão (ADR-0004).

Regras de segurança (modelo de ameaças, seção "IA"):
- Só endereços de loopback (127.0.0.1, ::1, localhost) são aceitos: os dados do
  projeto não saem do computador. Um servidor remoto exige `allow_remote=True`,
  que a interface só liga com aviso explícito ("Externo").
- Sem proxy do sistema (um proxy configurado poderia receber o tráfego local) e
  sem seguir redirecionamentos (um redirecionamento poderia levar a outro host).
- Respostas maiores que `MAX_RESPONSE_BYTES` são recusadas.
"""

from __future__ import annotations

import ipaddress
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from nexus_intel.domain.errors import NexusError

DEFAULT_BASE_URL = "http://127.0.0.1:11434"  # Ollama
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_LOOPBACK_NAMES = {"localhost"}


class AiUnavailable(NexusError):
    user_message = ("O mecanismo de IA local não respondeu. Verifique se o Ollama (ou outro servidor "
                    "local compatível) está aberto.")


class AiAddressRejected(NexusError):
    user_message = ("Endereço de IA recusado: só servidores neste computador (127.0.0.1 ou localhost) "
                    "são permitidos no modo local.")


def is_loopback(host: str) -> bool:
    host = host.strip("[]").lower()
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def normalize_base_url(raw: str, allow_remote: bool = False) -> str:
    """Valida e normaliza o endereço base (sem `/v1` no fim)."""
    url = (raw or DEFAULT_BASE_URL).strip().rstrip("/")
    if not re.match(r"^https?://", url, re.I):
        url = "http://" + url
    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise AiAddressRejected("Endereço de IA inválido.")
    if parts.username or parts.password:
        raise AiAddressRejected("O endereço da IA não pode conter usuário ou senha.")
    if not allow_remote and not is_loopback(parts.hostname):
        raise AiAddressRejected()
    path = re.sub(r"/v1$", "", parts.path.rstrip("/"))
    return f"{parts.scheme.lower()}://{parts.netloc}{path}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # noqa: D102
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatMessage:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class EngineStatus:
    available: bool
    base_url: str
    local: bool
    kind: str = ""  # "Ollama" ou "Servidor compatível"
    models: list[str] = field(default_factory=list)
    detail: str = ""


TextCallback = Callable[[str], Any]
KEEP_ALIVE = "30m"  # Ollama: mantém o modelo na memória (sem recarregar a cada pergunta)
NUM_CTX = 8192  # Ollama: contexto suficiente para instruções + ferramentas + resultados


class LocalLlmClient:
    """Fala o protocolo compatível com OpenAI e, quando o servidor é o Ollama, a API nativa
    (`/api/chat`), que permite manter o modelo carregado (`keep_alive`) e definir o contexto."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, *, allow_remote: bool = False,
                 timeout: float = 300.0, api_key: str | None = None) -> None:
        self.base_url = normalize_base_url(base_url, allow_remote)
        self.local = is_loopback(urlsplit(self.base_url).hostname or "")
        self.timeout = timeout
        self._api_key = api_key
        self.native = False  # Ollama detectado em status()

    # ------------------------------------------------------------ transporte
    def _open(self, method: str, path: str, body: dict[str, Any] | None, timeout: float | None) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base_url + path, data=data, method=method)  # noqa: S310 - URL validada
        req.add_header("Content-Type", "application/json")
        if self._api_key:
            req.add_header("Authorization", f"Bearer {self._api_key}")
        try:
            return _OPENER.open(req, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read(4096).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001, S110
                pass
            raise AiUnavailable(f"O mecanismo de IA recusou o pedido (HTTP {exc.code}). {detail[:300]}") from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise AiUnavailable() from exc

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None,
                 timeout: float | None = None) -> Any:
        try:
            with self._open(method, path, body, timeout) as resp:
                raw = resp.read(MAX_RESPONSE_BYTES + 1)
        except (OSError, TimeoutError) as exc:
            raise AiUnavailable() from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise AiUnavailable("A resposta do mecanismo de IA é grande demais.")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AiUnavailable("O mecanismo de IA devolveu uma resposta inválida.") from exc

    def _lines(self, path: str, body: dict[str, Any]) -> Any:
        """Lê uma resposta em fluxo, linha a linha (NDJSON do Ollama ou SSE do protocolo OpenAI)."""
        total = 0
        try:
            with self._open("POST", path, body, None) as resp:
                for raw in resp:
                    total += len(raw)
                    if total > MAX_RESPONSE_BYTES:
                        raise AiUnavailable("A resposta do mecanismo de IA é grande demais.")
                    line = raw.decode("utf-8", "replace").strip()
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if not line or line == "[DONE]":
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
        except (OSError, TimeoutError) as exc:
            raise AiUnavailable() from exc

    # ------------------------------------------------------------ consultas
    def status(self) -> EngineStatus:
        st = EngineStatus(False, self.base_url, self.local)
        try:
            models = self._request("GET", "/v1/models", timeout=3)
        except NexusError as exc:
            st.detail = exc.user_message
            return st
        st.available = True
        st.models = sorted(str(m.get("id", "")) for m in models.get("data", []) if m.get("id"))
        try:
            self._request("GET", "/api/version", timeout=2)
            st.kind, self.native = "Ollama", True
        except NexusError:
            st.kind, self.native = "Servidor compatível", False
        return st

    def chat(self, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
             temperature: float = 0.2, *, on_text: TextCallback | None = None,
             max_tokens: int | None = None) -> ChatMessage:
        """Uma rodada de conversa. Com `on_text`, a resposta chega em fluxo (o texto aparece
        enquanto é gerado); trechos de chamada de ferramenta escrita no texto não são repassados."""
        if self.native:
            return self._chat_native(model, messages, tools, temperature, on_text, max_tokens)
        body: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature,
                                "stream": on_text is not None}
        if max_tokens:
            body["max_tokens"] = max_tokens
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if on_text is None:
            resp = self._request("POST", "/v1/chat/completions", body)
            try:
                return parse_message(resp["choices"][0]["message"])
            except (KeyError, IndexError, TypeError) as exc:
                raise AiUnavailable("O mecanismo de IA devolveu uma resposta sem mensagem.") from exc
        content, calls = _Gate(on_text), {}
        for ev in self._lines("/v1/chat/completions", body):
            delta = ((ev.get("choices") or [{}])[0] or {}).get("delta") or {}
            if delta.get("content"):
                content.add(str(delta["content"]))
            for tc in delta.get("tool_calls") or []:
                slot = calls.setdefault(int(tc.get("index", 0)), {"id": "", "name": "", "arguments": ""})
                slot["id"] = tc.get("id") or slot["id"]
                fn = tc.get("function") or {}
                slot["name"] += fn.get("name") or ""
                slot["arguments"] += fn.get("arguments") or ""
        msg = {"content": content.text, "tool_calls": [
            {"id": c["id"] or f"call_{i}", "function": {"name": c["name"], "arguments": c["arguments"]}}
            for i, c in sorted(calls.items())]}
        return parse_message(msg)

    def _chat_native(self, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
                     temperature: float, on_text: TextCallback | None, max_tokens: int | None) -> ChatMessage:
        options: dict[str, Any] = {"temperature": temperature, "num_ctx": NUM_CTX}
        if max_tokens:
            options["num_predict"] = max_tokens
        body: dict[str, Any] = {"model": model, "messages": _to_native(messages), "stream": on_text is not None,
                                "keep_alive": KEEP_ALIVE, "options": options}
        if tools:
            body["tools"] = tools
        if on_text is None:
            resp = self._request("POST", "/api/chat", body)
            return parse_message(_from_native(resp.get("message") or {}))
        content, calls = _Gate(on_text), []
        for ev in self._lines("/api/chat", body):
            m = ev.get("message") or {}
            if m.get("content"):
                content.add(str(m["content"]))
            calls += m.get("tool_calls") or []
            if ev.get("done"):
                break
        return parse_message(_from_native({"content": content.text, "tool_calls": calls}))

    def warmup(self, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> None:
        """Carrega o modelo e processa as instruções antes da primeira pergunta (o servidor guarda
        esse começo em cache e as perguntas seguintes só processam o que mudou)."""
        self.chat(model, messages, tools, max_tokens=1)

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        resp = self._request("POST", "/v1/embeddings", {"model": model, "input": texts})
        try:
            rows = sorted(resp["data"], key=lambda d: d.get("index", 0))
            return [[float(x) for x in r["embedding"]] for r in rows]
        except (KeyError, TypeError, ValueError) as exc:
            raise AiUnavailable("O modelo de vetores devolveu uma resposta inválida.") from exc


class _Gate:
    """Junta o texto em fluxo e só repassa ao `on_text` o que não for chamada de ferramenta escrita."""

    def __init__(self, on_text: TextCallback) -> None:
        self.on_text, self.text, self._open = on_text, "", None

    def add(self, piece: str) -> None:
        self.text += piece
        head = self.text.lstrip()
        if self._open is None:
            if len(head) < len("<tool_call>") and "<tool_call>".startswith(head):
                return  # ainda não dá para saber
            self._open = not head.startswith("<tool_call>")
            if self._open:
                self.on_text(self.text)
            return
        if self._open and "<tool_call>" not in self.text:
            self.on_text(piece)


def _to_native(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mensagens no formato OpenAI → formato nativo do Ollama (argumentos como objeto)."""
    out = []
    for m in messages:
        n: dict[str, Any] = {"role": m["role"], "content": m.get("content") or ""}
        if m.get("tool_calls"):
            n["tool_calls"] = [{"function": {"name": tc["function"]["name"],
                                             "arguments": _args(tc["function"].get("arguments"))}}
                               for tc in m["tool_calls"]]
        if m["role"] == "tool" and m.get("name"):
            n["tool_name"] = m["name"]
        out.append(n)
    return out


def _from_native(m: dict[str, Any]) -> dict[str, Any]:
    return {"content": m.get("content") or "", "tool_calls": [
        {"id": f"call_{i}", "function": {"name": (tc.get("function") or {}).get("name", ""),
                                         "arguments": (tc.get("function") or {}).get("arguments") or {}}}
        for i, tc in enumerate(m.get("tool_calls") or [])]}


_TOOL_TAG = re.compile(r"<tool_call>\s*(.*?)\s*(?:</tool_call>|\Z)", re.S)


def _args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        text = raw.strip()
        while text.startswith("{{"):  # chaves dobradas por alguns modelos pequenos
            text = text[1:]
        decoder = json.JSONDecoder()
        for extra in ("", "}", "}}"):  # e fechamentos faltando
            try:
                val, _end = decoder.raw_decode(text + extra)
            except json.JSONDecodeError:
                continue
            return val if isinstance(val, dict) else {}
    return {}


def parse_message(msg: dict[str, Any]) -> ChatMessage:
    """Normaliza a mensagem do modelo. Aceita também chamadas de ferramenta escritas no texto
    (`<tool_call>{...}</tool_call>`), comuns em modelos pequenos."""
    content = str(msg.get("content") or "")
    calls: list[ToolCall] = []
    for i, tc in enumerate(msg.get("tool_calls") or []):
        fn = (tc or {}).get("function") or {}
        name = str(fn.get("name") or "")
        if name:
            calls.append(ToolCall(str(tc.get("id") or f"call_{i}"), name, _args(fn.get("arguments"))))
    if not calls and "<tool_call>" in content:
        for i, m in enumerate(_TOOL_TAG.finditer(content)):
            obj = _args(m.group(1))
            if obj.get("name"):
                calls.append(ToolCall(f"call_{i}", str(obj["name"]), _args(obj.get("arguments"))))
    # Marca de ferramenta que não pôde ser lida nunca aparece para o usuário.
    content = _TOOL_TAG.sub("", content).strip() if "<tool_call>" in content else content
    return ChatMessage(content, calls)
