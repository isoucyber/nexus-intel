"""IA e análises: conversa com o assistente NEXUS, por texto ou voz.

- Perguntas e ordens ("abre a ficha da Helena", "liga a Aurora à Vértice") por texto ou microfone.
- Respostas com o selo de cada frase (Documentado, Interpretação da IA, Não verificado) e as
  citações clicáveis; marcas inventadas pelo modelo são removidas e contadas.
- Sugestões da IA aparecem na própria resposta com Aprovar / Rejeitar.
- A resposta pode ser lida em voz alta (voz masculina, timbre de assistente).
Todo texto vindo do modelo ou do projeto é exibido como TEXTO PURO (nunca HTML).
"""

from __future__ import annotations

import re
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from nexus_intel.application.assistant import Assistant, AssistantReply, Segment, quick_command
from nexus_intel.application.project_store import ProjectStore
from nexus_intel.application.semantic import SemanticIndex
from nexus_intel.application.suggestions import SuggestionBox
from nexus_intel.domain.errors import NexusError
from nexus_intel.infrastructure.ai.client import EngineStatus, LocalLlmClient
from nexus_intel.infrastructure.voice import audio, stt, tts
from nexus_intel.ui.ai_common import AiPrefs, PrefsStore, pick_chat_model, pick_embed_model, run_async
from nexus_intel.ui.ai_settings import AiSettingsDialog
from nexus_intel.ui.common import Page
from nexus_intel.ui.design.components import (
    Badge,
    Button,
    Card,
    CitationBadge,
    IconButton,
    Input,
    SectionHeader,
    Select,
    dialog_form,
    notify,
    text,
)

EXAMPLES = ("Resuma o projeto", "Há conflitos ou dados sem fonte para revisar?", "Abre o grafo",
            "Quais fontes têm baixa confiabilidade?")
_MD = re.compile(r"\*\*|__|`")
CITE_ICONS = {"c": "file-text", "r": "network", "f": "library", "e": "circle", "n": "pencil"}


def display_text(s: str) -> str:
    """Texto do modelo para a tela: sem marcas de citação (viram botões) nem ênfase Markdown."""
    from nexus_intel.application.assistant import CITE

    return re.sub(r"[ \t]+([,.;:!?])", r"\1", _MD.sub("", CITE.sub("", s))).strip()


class DocumentDialog(QDialog):
    """Cola um documento para a IA extrair entidades, afirmações e relações como sugestões."""

    def __init__(self, store: ProjectStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        form = dialog_form(self, "Ler documento", 640)
        self.body = QPlainTextEdit()
        self.body.setPlaceholderText("Cole aqui o texto do documento (reportagem, ficha, transcrição…).")
        self.body.setMinimumHeight(260)
        form.addRow(self.body)
        sources = [("— nenhuma (trechos ficam sem fonte) —", "")] + [
            (s["title"], s["id"]) for s in store.list_sources()]
        self.source = Select(sources)
        form.addRow("Fonte do documento", self.source)
        form.addRow("", text("Tudo o que a IA extrair vira sugestão pendente: nada entra no projeto sem a sua "
                             "aprovação. Cada trecho citado é conferido contra o texto colado.", "caption", wrap=True))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(Button("Cancelar", "ghost", on_click=self.reject))
        row.addWidget(Button("Analisar documento", "primary", "sparkles", on_click=self.accept))
        form.addRow(row)


class SuggestionRow(QFrame):
    decided = Signal()

    def __init__(self, box: SuggestionBox, sid: str) -> None:
        super().__init__()
        self.box, self.sid = box, sid
        s = box.get(sid)
        self.setProperty("card", "true")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.addWidget(Badge(s.label, "info", "git-merge"))
        self.summary = text(s.summary, wrap=True)
        lay.addWidget(self.summary, 1)
        if s.payload.get("excerpt"):
            ok = s.payload.get("excerpt_checked")
            lay.addWidget(Badge("Trecho conferido" if ok else "Trecho não conferido", "success" if ok else "warning",
                                tooltip=f"Trecho: {s.payload['excerpt']}"))
        self.approve_btn = Button("Aprovar", "primary", "check", on_click=self.approve, size="sm")
        self.reject_btn = Button("Rejeitar", "ghost", "x", on_click=self.reject, size="sm")
        lay.addWidget(self.approve_btn)
        lay.addWidget(self.reject_btn)
        if s.status != "pending":
            self._done("Aprovada" if s.status == "approved" else "Rejeitada")

    def _done(self, label: str) -> None:
        self.approve_btn.hide()
        self.reject_btn.hide()
        self.layout().addWidget(Badge(label, "success" if label == "Aprovada" else "neutral"))

    def approve(self) -> None:
        try:
            self.box.approve(self.sid)
        except NexusError as exc:
            notify(self, exc.user_message, "danger")
            return
        self._done("Aprovada")
        self.decided.emit()

    def reject(self) -> None:
        try:
            self.box.reject(self.sid, "rejeitada na conversa")
        except NexusError as exc:
            notify(self, exc.user_message, "danger")
            return
        self._done("Rejeitada")
        self.decided.emit()


class AssistantPage(Page):
    open_entity = Signal(str)
    go_to = Signal(str)
    graph_focus = Signal(str)
    changed = Signal()
    speaking_changed = Signal(bool)

    def __init__(self, store: ProjectStore, prefs: PrefsStore | None = None, user_name: str = "",
                 client_factory: Any = LocalLlmClient) -> None:
        super().__init__()
        self.store = store
        self.prefs_store = prefs or PrefsStore()
        self.prefs: AiPrefs = self.prefs_store.load()
        self.user_name = user_name
        self.client_factory = client_factory
        self.suggestions = SuggestionBox(store)
        self.status: EngineStatus | None = None
        self.model = ""
        self.assistant: Assistant | None = None
        self.speaker = tts.Speaker(on_state=self.speaking_changed.emit)
        self.recorder = audio.Recorder()
        self.transcriber: stt.Transcriber | None = None
        self._turn = 0
        self._gen: Any = None
        self.busy = False

        self.engine_badge = Badge("Verificando IA…", "neutral", "server")
        self.voice_badge = Badge("", "neutral", "volume-2")
        settings = Button("Configurar", "secondary", "settings", on_click=self.open_settings)
        new = IconButton("refresh-cw", "Nova conversa", self.new_conversation)
        self.layout_.addWidget(SectionHeader(
            "IA e análises", "Pergunte, peça ou mande abrir. Cada frase mostra se veio de uma fonte do projeto.",
            [self.engine_badge, self.voice_badge, settings, new]))

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        self.feed = QVBoxLayout(host)
        self.feed.setContentsMargins(0, 0, 8, 0)
        self.feed.setSpacing(10)
        self.feed.addStretch(1)
        self.scroll.setWidget(host)
        self.layout_.addWidget(self.scroll, 1)
        self._welcome()

        status_row = QHBoxLayout()
        self.thinking = text("", "caption")
        status_row.addWidget(self.thinking, 1)
        self.cancel_btn = Button("Cancelar", "ghost", "x", on_click=self.cancel, size="sm")
        self.cancel_btn.hide()
        status_row.addWidget(self.cancel_btn)
        self.layout_.addLayout(status_row)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        doc = IconButton("file-text", "Ler documento: a IA extrai entidades e relações como sugestões",
                         self.read_document)
        bar.addWidget(doc)
        self.input = Input("Pergunte ou dê uma ordem…  (Enter envia · Ctrl+Shift+Espaço fala)")
        self.input.returnPressed.connect(self.submit)
        bar.addWidget(self.input, 1)
        self.mic = IconButton("mic", "Falar (Ctrl+Shift+Espaço)", self.toggle_mic, checkable=True)
        bar.addWidget(self.mic)
        self.send_btn = Button("Enviar", "primary", "send", on_click=self.submit)
        bar.addWidget(self.send_btn)
        self.voice_toggle = IconButton("volume-2", "Respostas em voz alta", self._toggle_voice, checkable=True)
        bar.addWidget(self.voice_toggle)
        self.stop_voice = IconButton("square", "Parar de falar", self.speaker.stop)
        self.stop_voice.hide()
        bar.addWidget(self.stop_voice)
        self.layout_.addLayout(bar)
        self.speaking_changed.connect(lambda on: self.stop_voice.setVisible(on))
        self._dots = QTimer(self)
        self._dots.setInterval(450)
        self._dots.timeout.connect(self._tick)
        self._dot_n = 0
        self._apply_prefs()

    # ============================================================== estado
    def _apply_prefs(self) -> None:
        self.voice_toggle.setChecked(self.prefs.auto_speak)
        self.voice_toggle.set_icon("volume-2" if self.prefs.auto_speak else "volume-x")
        ok, desc = tts.describe(self.prefs.voice_settings())
        self.voice_badge.set_text("Voz pronta" if ok else "Sem voz")
        self.voice_badge.setToolTip(desc)
        mic_ok, why = audio.microphone_available()
        stt_ok, why_stt = stt.describe(self.prefs.whisper_dir)
        self.mic.setEnabled(mic_ok and stt_ok)
        self.mic.setToolTip("Falar (Ctrl+Shift+Espaço)" if mic_ok and stt_ok else f"Microfone indisponível: "
                            f"{why if not mic_ok else why_stt}")

    def refresh(self) -> None:
        """Ao abrir a tela: verifica o mecanismo de IA em segundo plano."""
        try:
            client = self.client_factory(self.prefs.base_url)
        except NexusError as exc:
            self._set_engine(EngineStatus(False, self.prefs.base_url, True, detail=exc.user_message))
            return
        run_async(self, client.status, self._set_engine,
                  lambda m: self._set_engine(EngineStatus(False, self.prefs.base_url, True, detail=m)))

    def _set_engine(self, st: EngineStatus) -> None:
        self.status = st
        self.model = pick_chat_model(st.models, self.prefs.model) if st.available else ""
        if st.available and self.model:
            where = "Local" if st.local else "Externo"
            self.engine_badge.set_text(f"{where} · {self.model}")
            self.engine_badge._color = lambda t: t.success  # noqa: SLF001
            self.engine_badge.setToolTip(f"{st.kind} em {st.base_url}. Nenhum dado sai deste computador."
                                         if st.local else f"Os dados vão para {st.base_url}.")
            embed = pick_embed_model(st.models, self.prefs.embed_model)
            semantic = None
            if embed:
                client = self.client_factory(self.prefs.base_url)
                semantic = SemanticIndex(self.store, lambda texts: client.embed(embed, texts), embed,
                                         include_sensitive=self.prefs.include_sensitive)
            history = self.assistant.history if self.assistant else []
            self.assistant = Assistant(self.store, model=self.model, user_name=self.user_name, semantic=semantic,
                                       include_sensitive=self.prefs.include_sensitive)
            self.assistant.history = history
        else:
            self.engine_badge.set_text("IA indisponível")
            self.engine_badge._color = lambda t: t.text_secondary  # noqa: SLF001
            detail = st.detail or "Nenhum modelo instalado."
            self.engine_badge.setToolTip(f"{detail} Comandos de navegação continuam funcionando.")
            self.assistant = None
        self.engine_badge.update()

    # ============================================================== feed
    def _add(self, w: QWidget, align_right: bool = False) -> None:
        row = QHBoxLayout()
        if align_right:
            row.addStretch(1)
        row.addWidget(w, 0 if align_right else 1)
        if not align_right:
            row.addSpacing(60)
        holder = QWidget()
        holder.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        self.feed.insertWidget(self.feed.count() - 1, holder)
        QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def _welcome(self) -> None:
        card = Card("Às suas ordens.", "Sou o NEXUS. Leio o projeto, cito as fontes e só registro mudanças "
                    "como sugestões para você aprovar.", icon="bot")
        row = QHBoxLayout()
        for ex in EXAMPLES:
            row.addWidget(Button(ex, "ghost", on_click=lambda q=ex: self.ask(q), size="sm"))
        row.addStretch(1)
        card.body.addLayout(row)
        self._add(card)

    def _user_bubble(self, q: str) -> None:
        card = Card(padding="md")
        card.setProperty("card", "elevated")
        lb = text(q, wrap=True, selectable=True)
        lb.setMinimumWidth(min(lb.fontMetrics().horizontalAdvance(q) + 6, 520))
        lb.setMaximumWidth(620)
        card.add(lb)
        self._add(card, align_right=True)

    def _segment_row(self, seg: Segment) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        line = QHBoxLayout()
        line.setSpacing(8)
        if seg.kind != "plain":
            badge = CitationBadge(seg.kind)
            if seg.auto_cited:
                badge.setToolTip("Documentado: a frase contém exatamente um dado que a IA leu, e o NEXUS anexou a "
                                 "citação.")
            line.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        body = text(display_text(seg.text), wrap=True, selectable=True)
        line.addWidget(body, 1)
        lay.addLayout(line)
        if seg.citations:
            cites = QHBoxLayout()
            cites.setSpacing(4)
            for c in seg.citations[:6]:
                b = Button(c.label[:48], "ghost", CITE_ICONS.get(c.kind, "link"), size="sm",
                           on_click=lambda c=c: self._open_citation(c))
                b.setToolTip(f"Abrir: {c.label}")
                cites.addWidget(b)
            cites.addStretch(1)
            lay.addLayout(cites)
        return w

    def _open_citation(self, c: Any) -> None:
        if c.entity_id:
            self.open_entity.emit(c.entity_id)
        elif c.kind == "f":
            self.go_to.emit("sources")

    def show_reply(self, reply: AssistantReply) -> None:
        card = Card(padding="md")
        head = QHBoxLayout()
        head.addWidget(text("NEXUS", "overline"))
        head.addStretch(1)
        card.body.addLayout(head)
        for seg in reply.segments:
            card.add(self._segment_row(seg))
        for a in reply.actions:
            card.add(text(f"↪ {a.label}", "caption"))
        if reply.removed_citations:
            card.add(Badge(f"{reply.removed_citations} citação(ões) inválida(s) removida(s)", "warning",
                           "triangle-alert", "O modelo citou algo que não leu no projeto. O trecho ficou como "
                           "Não verificado."))
        for sid in reply.suggestions:
            row = SuggestionRow(self.suggestions, sid)
            row.decided.connect(self.changed.emit)
            card.add(row)
        self._add(card)
        for a in reply.actions:
            {"open_entity": self.open_entity, "go": self.go_to, "graph_focus": self.graph_focus}[a.action].emit(a.target)
        if self.voice_toggle.isChecked():
            self.speaker.speak(reply.spoken_text(), self.prefs.voice_settings())

    def _note(self, message: str, tone: str = "neutral") -> None:
        card = Card(padding="md")
        card.add(Badge("Aviso", tone, "info"))
        card.add(text(message, "secondary", wrap=True))
        self._add(card)

    # ============================================================== perguntas
    def submit(self) -> None:
        q = self.input.text().strip()
        if q:
            self.input.clear()
            self.ask(q)

    def ask(self, question: str, document: str | None = None, source_id: str | None = None) -> None:
        if self.busy:
            notify(self, "Aguarde a resposta anterior (ou cancele).", "info")
            return
        self._user_bubble(question if not document else f"{question}\n[documento com {len(document)} caracteres]")
        quick = quick_command(self.store, question) if not document else None
        if quick is not None:
            self.show_reply(quick)
            return
        if self.assistant is None:
            self._note("O mecanismo de IA não está disponível. Abra o Ollama (ou outro servidor local) e clique em "
                       "Configurar → Verificar. Comandos como \"abre a ficha da …\" funcionam mesmo assim.", "warning")
            return
        self._turn += 1
        turn = self._turn
        try:
            self._gen = self.assistant.turn(question, document=document, source_id=source_id,
                                            on_tool=lambda n: self._set_thinking(f"Consultando o projeto ({n})"))
            req = next(self._gen)
        except NexusError as exc:
            self._note(exc.user_message, "danger")
            return
        self._busy(True)
        self._send(req, turn)

    def _send(self, req: Any, turn: int) -> None:
        client = self.client_factory(self.prefs.base_url)
        model = self.model
        run_async(self, lambda: client.chat(model, req.messages, req.tools),
                  lambda msg: self._on_message(msg, turn), lambda m: self._on_fail(m, turn))

    def _on_message(self, msg: Any, turn: int) -> None:
        if turn != self._turn:
            return  # cancelada
        try:
            req = self._gen.send(msg)
        except StopIteration as stop:
            self._busy(False)
            self.show_reply(stop.value)
            if stop.value.suggestions:
                self.changed.emit()
            return
        except NexusError as exc:
            self._on_fail(exc.user_message, turn)
            return
        self._send(req, turn)

    def _on_fail(self, message: str, turn: int) -> None:
        if turn != self._turn:
            return
        self._busy(False)
        self._note(message, "danger")

    def cancel(self) -> None:
        self._turn += 1
        self._busy(False)
        self._set_thinking("")

    def _busy(self, on: bool) -> None:
        self.busy = on
        self.send_btn.setEnabled(not on)
        self.cancel_btn.setVisible(on)
        if on:
            self._set_thinking("Pensando")
            self._dots.start()
        else:
            self._dots.stop()
            self.thinking.setText("")

    def _set_thinking(self, label: str) -> None:
        self._thinking_label = label
        self.thinking.setText(label)

    def _tick(self) -> None:
        self._dot_n = (self._dot_n + 1) % 4
        self.thinking.setText(getattr(self, "_thinking_label", "Pensando") + "." * self._dot_n)

    def new_conversation(self) -> None:
        self.cancel()
        if self.assistant:
            self.assistant.reset()
        while self.feed.count() > 1:
            item = self.feed.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._welcome()

    def read_document(self) -> None:
        dlg = DocumentDialog(self.store, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        doc = dlg.body.toPlainText().strip()
        if not doc:
            return
        self.ask("Leia o documento e sugira as entidades, afirmações e relações que ele sustenta.",
                 document=doc[:30000], source_id=dlg.source.value() or None)

    # ================================================================= voz
    def _toggle_voice(self) -> None:
        self.prefs.auto_speak = self.voice_toggle.isChecked()
        self.voice_toggle.set_icon("volume-2" if self.prefs.auto_speak else "volume-x")
        if not self.prefs.auto_speak:
            self.speaker.stop()
        self.prefs_store.save(self.prefs)

    def toggle_mic(self) -> None:
        if self.recorder.recording:
            self.mic.setChecked(False)
            self.mic.set_icon("mic")
            audio_data = self.recorder.stop()
            self._set_thinking("Transcrevendo")
            if self.transcriber is None:
                self.transcriber = stt.Transcriber(self.prefs.whisper_dir)
            tr = self.transcriber
            run_async(self, lambda: tr.transcribe(audio_data), self._on_transcript,
                      lambda m: (self._set_thinking(""), notify(self, m, "danger")))
            return
        if not self.mic.isEnabled():
            notify(self, self.mic.toolTip(), "warning")
            self.mic.setChecked(False)
            return
        self.speaker.stop()
        try:
            self.recorder.start()
        except Exception as exc:  # noqa: BLE001 - microfone ocupado, sem permissão…
            self.mic.setChecked(False)
            notify(self, f"Não foi possível abrir o microfone: {exc}", "danger")
            return
        self.mic.setChecked(True)
        self.mic.set_icon("mic-off")
        self._set_thinking("Ouvindo… clique no microfone (ou Ctrl+Shift+Espaço) para enviar")

    def _on_transcript(self, said: str) -> None:
        self._set_thinking("")
        said = said.strip()
        if not said:
            notify(self, "Não entendi. Tente de novo, mais perto do microfone.", "info")
            return
        self.ask(said)

    # ============================================================ configurar
    def open_settings(self) -> None:
        dlg = AiSettingsDialog(self.prefs, self, self.speaker)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.apply_settings(dlg.result_prefs())

    def apply_settings(self, prefs: AiPrefs) -> None:
        self.prefs = prefs
        self.prefs_store.save(prefs)
        self.transcriber = None
        self._apply_prefs()
        self.refresh()

    def shutdown(self) -> None:
        self._turn += 1
        self.speaker.stop()
        if self.recorder.recording:
            self.recorder.stop()
