"""0.4: telas de IA — conversa, citações clicáveis, comandos, sugestões, busca semântica e voz."""

from __future__ import annotations

import pytest

from nexus_intel.infrastructure.ai.client import ChatMessage, EngineStatus, ToolCall

pytest.importorskip("PySide6")


class FakeClient:
    """Mecanismo de IA falso: responde segundo `script` (lista de ChatMessage ou funções)."""

    script: list = []
    available = True
    warmups = 0

    def __init__(self, base_url: str = "") -> None:
        self.base_url = base_url

    def status(self) -> EngineStatus:
        if not FakeClient.available:
            return EngineStatus(False, "http://127.0.0.1:11434", True, detail="O mecanismo de IA local não respondeu.")
        return EngineStatus(True, "http://127.0.0.1:11434", True, "Ollama", ["bge-m3", "qwen2.5:7b"])

    def chat(self, model, messages, tools=None, temperature=0.2, *, on_text=None, max_tokens=None):
        if max_tokens == 1:  # aquecimento
            FakeClient.warmups += 1
            return ChatMessage("")
        step = FakeClient.script.pop(0)
        msg = step(messages) if callable(step) else step
        if on_text and msg.content:
            for word in msg.content.split(" "):
                on_text(word + " ")
        return msg

    def warmup(self, model, messages, tools=None):
        self.chat(model, messages, tools, max_tokens=1)

    def embed(self, model, texts):
        vocab = ["contadora", "logística", "pessoa", "empresa"]
        return [[float(t.lower().count(w)) + 0.01 for w in vocab] for t in texts]


@pytest.fixture
def ws(qtbot, store):
    from nexus_intel.ui.workspace import Workspace

    FakeClient.script, FakeClient.available = [], True
    w = Workspace(store, "Projeto", "#2dd4bf", ai_client=FakeClient, user_name="Ana")
    qtbot.addWidget(w)
    w.show()
    return w


@pytest.fixture
def data(store):
    src = store.create_source("Junta comercial (fictícia)", kind="official", reliability="A")
    helena = store.create_entity("person", "Helena Prado")
    aurora = store.create_entity("company", "Aurora Logística Ltda.")
    prof = store.add_claim(helena, "profissao", "Contadora", source_id=src, status="verified")
    return {"helena": helena, "aurora": aurora, "prof": prof, "src": src}


def texts(widget):
    from PySide6.QtWidgets import QLabel, QWidget

    return " ".join([lb.text() for lb in widget.findChildren(QLabel)]
                    + [w.accessibleName() for w in widget.findChildren(QWidget)])


def ready(qtbot, page):
    page.refresh()
    qtbot.waitUntil(lambda: page.assistant is not None, timeout=5000)


def test_ai_modules_are_real_now(ws):
    assert {"ai", "semantic", "suggestions"}.isdisjoint(ws.pending_items)


def test_engine_badge_shows_local_model_or_unavailable(qtbot, ws):
    page = ws.pages["ai"]
    ready(qtbot, page)
    assert page.model == "qwen2.5:7b"  # nunca escolhe o modelo de vetores para conversar
    assert "Local · qwen2.5:7b" in texts(page)
    FakeClient.available = False
    page.refresh()
    qtbot.waitUntil(lambda: page.assistant is None, timeout=5000)
    assert "IA indisponível" in texts(page)
    page.ask("Quem é Helena?")
    assert "não está disponível" in texts(page)


def test_answer_with_verified_citation_and_click_opens_entity(qtbot, ws, data):
    page = ws.pages["ai"]
    ready(qtbot, page)
    FakeClient.script = [
        ChatMessage("", [ToolCall("1", "ver_entidade", {"entidade_id": data["helena"]})]),
        lambda msgs: ChatMessage(f"Helena Prado é contadora {page.assistant.mark('c', data['prof'])}. "
                                 "Interpreto que <b>ela</b> é central."),
    ]
    page.ask("Quem é Helena Prado?")
    qtbot.waitUntil(lambda: not page.busy and "Documentado" in texts(page), timeout=5000)
    shown = texts(page)
    assert "Interpretação da IA" in shown and "<b>ela</b>" in shown  # HTML do modelo: texto puro
    assert page.assistant.mark("c", data["prof"]) not in shown  # a marca vira botão
    from nexus_intel.ui.design.components import Button

    cite = [b for b in page.findChildren(Button) if b.toolTip().startswith("Abrir: Helena Prado")][0]
    cite.click()
    assert ws.tabs.count() == 2 and ws.tabs.currentWidget().entity_id == data["helena"]


def test_quick_command_navigates_without_model(qtbot, ws, data):
    FakeClient.available = False
    page = ws.pages["ai"]
    page.refresh()
    page.ask("abre a ficha da Helena Prado")
    assert ws.tabs.currentWidget().entity_id == data["helena"]
    page.ask("vai para o grafo")
    assert ws.stack.currentWidget() is ws.pages["graph"]


def test_suggestion_from_conversation_is_approved_inline(qtbot, ws, data):
    page = ws.pages["ai"]
    ready(qtbot, page)
    FakeClient.script = [
        ChatMessage("", [ToolCall("1", "sugerir_relacao", {"origem_id": "Helena Prado", "tipo_relacao": "works_at",
                                                           "destino_id": data["aurora"]})]),
        ChatMessage("Sugestão registrada; aguarda sua aprovação."),
    ]
    n = ws.store.stats()["relations"]
    page.ask("Liga a Helena à Aurora")
    qtbot.waitUntil(lambda: not page.busy, timeout=5000)
    assert ws.store.stats()["relations"] == n  # nada aplicado sem aprovação
    assert "(1)" in ws.nav_buttons["suggestions"].text()
    from nexus_intel.ui.assistant_page import SuggestionRow

    row = page.findChildren(SuggestionRow)[0]
    row.approve()
    assert ws.store.stats()["relations"] == n + 1
    assert "(1)" not in ws.nav_buttons["suggestions"].text()


def test_suggestions_page_approve_and_reject(qtbot, ws, data):
    from nexus_intel.application.suggestions import SuggestionBox

    box = SuggestionBox(ws.store)
    a = box.propose("entity", {"type_key": "person", "name": "Bruno Teixeira"})
    b = box.propose("entity", {"type_key": "person", "name": "Pessoa Errada"})
    ws.go("suggestions")
    page = ws.pages["suggestions"]
    assert "Bruno Teixeira" in texts(page)
    page._approve(a.id)
    page._reject(b.id, "duplicada")
    assert box.get(a.id).status == "approved" and box.get(b.id).decision_note == "duplicada"
    assert ws.store.search("bruno teixeira")


def test_semantic_page_indexes_and_searches(qtbot, ws, data):
    page = ws.pages["semantic"]
    ws.go("semantic")
    qtbot.waitUntil(lambda: page.index is not None, timeout=5000)
    page.reindex()
    qtbot.waitUntil(lambda: page.index.indexed_count() == 2 and page.index_btn.isEnabled() is False, timeout=5000)
    page.query.setText("contadora")
    page.search()
    qtbot.waitUntil(lambda: "Helena Prado" in texts(page), timeout=5000)


def test_settings_dialog_round_trip_and_rejects_remote(qtbot, ws):
    from nexus_intel.ui.ai_settings import AiSettingsDialog

    page = ws.pages["ai"]
    dlg = AiSettingsDialog(page.prefs, page)
    qtbot.addWidget(dlg)
    dlg.model.setCurrentText("qwen2.5:7b")
    dlg.timbre.setChecked(False)
    dlg.deepen.setValue(90)
    p = dlg.result_prefs()
    assert p.model == "qwen2.5:7b" and not p.voice.timbre and p.voice.deepen == 0.9
    dlg.url.setText("http://servidor.exemplo.com:11434")
    dlg.accept()
    assert dlg.result() == 0 and "só servidores neste computador" in dlg.engine_status.text()
    page.apply_settings(p)
    assert page.prefs_store.load().model == "qwen2.5:7b"


def test_reply_is_spoken_when_voice_is_on(qtbot, ws, data, monkeypatch):
    page = ws.pages["ai"]
    spoken = []
    monkeypatch.setattr(page.speaker, "speak", lambda t, s: spoken.append(t) or True)
    page.voice_toggle.setChecked(True)
    page.ask("abre a ficha da Helena Prado")
    assert spoken == ["Abrindo a ficha de Helena Prado."]
    page.voice_toggle.setChecked(False)
    page.ask("vai para fontes")
    assert len(spoken) == 1


def test_microphone_unavailable_is_explained(ws, monkeypatch):
    page = ws.pages["ai"]
    if not page.mic.isEnabled():
        assert "indisponível" in page.mic.toolTip().lower()


def test_lock_shutdown_silences_voice(ws, monkeypatch):
    page = ws.pages["ai"]
    stopped = []
    monkeypatch.setattr(page.speaker, "stop", lambda: stopped.append(1))
    ws.shutdown()
    assert stopped


def test_streamed_answer_is_spoken_sentence_by_sentence_and_model_is_warmed(qtbot, ws, data, monkeypatch):
    page = ws.pages["ai"]
    FakeClient.warmups = 0
    ready(qtbot, page)
    qtbot.waitUntil(lambda: FakeClient.warmups == 1, timeout=5000)  # aquecido ao abrir a tela
    fed, finished = [], []
    monkeypatch.setattr(page.speaker, "begin", lambda s: True)
    monkeypatch.setattr(page.speaker, "feed", lambda t: fed.append(t))
    monkeypatch.setattr(page.speaker, "finish", lambda: finished.append(1))
    page.voice_toggle.setChecked(True)
    FakeClient.script = [lambda msgs: ChatMessage(f"Helena é contadora {page.assistant.mark('c', data['prof'])}. "
                                                  "Trabalha na Aurora. Mais algo?")]
    page.ask("Quem é Helena Prado?")
    qtbot.waitUntil(lambda: not page.busy, timeout=5000)
    spoken = "".join(fed)
    assert "Helena é contadora." in spoken and "[c" not in spoken and "Mais algo?" in spoken
    assert finished == [1] and page._live is None
    assert " s" in texts(page)  # tempo da resposta aparece no cartão
