"""Configuração do assistente: mecanismo de IA local, modelos e voz."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QSlider, QWidget

from nexus_intel.domain.errors import NexusError
from nexus_intel.infrastructure.ai.client import LocalLlmClient, normalize_base_url
from nexus_intel.infrastructure.voice import stt, tts
from nexus_intel.ui.ai_common import AiPrefs, pick_chat_model, pick_embed_model, run_async
from nexus_intel.ui.design.components import Button, Input, Select, dialog_form, notify, text

ENGINES = [("Automático (Kokoro, senão Piper, senão Windows)", "auto"), ("Kokoro — voz humana", "kokoro"),
           ("Piper — voz neural leve", "piper"), ("Voz do Windows (robótica)", "windows"),
           ("espeak-ng (Linux)", "espeak"), ("Desligada", "off")]


def _editable_combo(current: str) -> QComboBox:
    box = QComboBox()
    box.setEditable(True)
    if current:
        box.addItem(current)
    box.setCurrentText(current)
    return box


def _slider(lo: int, hi: int, value: int) -> QSlider:
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


class AiSettingsDialog(QDialog):
    def __init__(self, prefs: AiPrefs, parent: QWidget | None = None, speaker: tts.Speaker | None = None) -> None:
        super().__init__(parent)
        self.prefs = prefs
        self.speaker = speaker or tts.Speaker()
        form = dialog_form(self, "Configurar o assistente", 620, scroll=True)

        form.addRow(text("MECANISMO DE IA (NESTE COMPUTADOR)", "overline"))
        self.url = Input("http://127.0.0.1:11434", text=prefs.base_url)
        self.url.setToolTip("Ollama: http://127.0.0.1:11434 · LM Studio: http://127.0.0.1:1234 · "
                            "llama.cpp: http://127.0.0.1:8080. Só endereços deste computador são aceitos.")
        refresh = Button("Verificar", "secondary", "refresh-cw", on_click=self.check_engine)
        row = QHBoxLayout()
        row.addWidget(self.url, 1)
        row.addWidget(refresh)
        form.addRow("Endereço", row)
        self.engine_status = text("Clique em Verificar.", "caption", wrap=True)
        form.addRow("", self.engine_status)
        self.model = _editable_combo(prefs.model)
        self.model.setToolTip("Recomendado: qwen2.5:7b (bom em português e com ferramentas). Em máquinas "
                              "modestas: qwen2.5:3b.")
        form.addRow("Modelo de conversa", self.model)
        self.embed = _editable_combo(prefs.embed_model)
        self.embed.setToolTip("Para a busca semântica. Recomendado: bge-m3 (multilíngue) ou nomic-embed-text.")
        form.addRow("Modelo de vetores", self.embed)
        self.sensitive = QCheckBox("Permitir que a IA leia dados sensíveis (saúde, religião…)")
        self.sensitive.setChecked(prefs.include_sensitive)
        form.addRow("", self.sensitive)
        form.addRow("", text("Observações privadas nunca são enviadas à IA.", "caption", wrap=True))

        form.addRow(text("VOZ", "overline"))
        v = prefs.voice
        self.engine = Select(ENGINES, v.engine)
        form.addRow("Mecanismo de voz", self.engine)
        self.kokoro_voice = Select([(label, key) for key, label in tts.KOKORO_VOICES.items()], v.kokoro_voice)
        form.addRow("Voz Kokoro", self.kokoro_voice)
        voices = tts.installed_voices(prefs.voices_dir) or [v.voice]
        self.voice = Select([(f"{n}{' (masculina)' if n == tts.DEFAULT_VOICE else ''}", n) for n in voices],
                            v.voice)
        form.addRow("Voz Piper", self.voice)
        self.timbre = QCheckBox("Efeito de assistente digital (voz mais grave e metálica; menos natural)")
        self.timbre.setChecked(v.timbre)
        form.addRow("", self.timbre)
        self.deepen = _slider(85, 100, int(round(v.deepen * 100)))
        self.deepen.setToolTip("Mais à esquerda = voz mais grave.")
        form.addRow("Gravidade", self.deepen)
        self.speed = _slider(80, 130, int(round(v.speed * 100)))
        form.addRow("Velocidade", self.speed)
        self.auto_speak = QCheckBox("Falar as respostas em voz alta")
        self.auto_speak.setChecked(prefs.auto_speak)
        form.addRow("", self.auto_speak)
        self.piper = Input("vazio = procurar automaticamente", text=v.piper_command)
        browse = Button("Procurar…", "ghost", on_click=self._browse_piper)
        prow = QHBoxLayout()
        prow.addWidget(self.piper, 1)
        prow.addWidget(browse)
        form.addRow("Executável do Piper", prow)
        self.voice_status = text("", "caption", wrap=True)
        form.addRow("", self.voice_status)
        test = Button("Testar voz", "secondary", "volume-2", on_click=self.test_voice)
        form.addRow("", test)
        ok_stt, why = stt.describe(prefs.whisper_dir)
        form.addRow("Microfone", text(("✓ " if ok_stt else "") + why, "caption", wrap=True))
        form.addRow("", text(f"Vozes e modelo de fala ficam em {prefs.root}. Para instalar a voz humana e o "
                             "microfone: python tools/baixar_voz.py", "caption", wrap=True))

        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(Button("Cancelar", "ghost", on_click=self.reject))
        self.save_btn = Button("Salvar", "primary", on_click=self.accept)
        foot.addWidget(self.save_btn)
        form.addRow(foot)
        for w in (self.engine, self.voice, self.kokoro_voice):
            w.currentIndexChanged.connect(self._update_voice_status)
        self.timbre.toggled.connect(self._update_voice_status)
        self.piper.textChanged.connect(self._update_voice_status)
        self._update_voice_status()

    # ------------------------------------------------------------------ dados
    def result_prefs(self) -> AiPrefs:
        p = AiPrefs.from_dict(self.prefs.to_dict())
        p.base_url = self.url.text().strip() or p.base_url
        p.model = self.model.currentText().strip()
        p.embed_model = self.embed.currentText().strip()
        p.include_sensitive = self.sensitive.isChecked()
        p.auto_speak = self.auto_speak.isChecked()
        p.voice.engine = self.engine.value()
        p.voice.voice = self.voice.value() or p.voice.voice
        p.voice.kokoro_voice = self.kokoro_voice.value() or p.voice.kokoro_voice
        p.voice.timbre = self.timbre.isChecked()
        p.voice.deepen = self.deepen.value() / 100
        p.voice.speed = self.speed.value() / 100
        p.voice.piper_command = self.piper.text().strip()
        return p

    def accept(self) -> None:
        try:
            normalize_base_url(self.url.text())
        except NexusError as exc:
            self.engine_status.setText(exc.user_message)
            return
        super().accept()

    # ---------------------------------------------------------------- ações
    def _browse_piper(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Executável do Piper", "", "Programas (piper*)")
        if path:
            self.piper.setText(path)

    def _update_voice_status(self, *_: Any) -> None:
        ok, desc = tts.describe(self.result_prefs().voice_settings())
        self.voice_status.setText(("✓ " if ok else "") + desc)

    def check_engine(self) -> None:
        try:
            client = LocalLlmClient(self.url.text())
        except NexusError as exc:
            self.engine_status.setText(exc.user_message)
            return
        self.engine_status.setText("Verificando…")

        def done(st: Any) -> None:
            if not st.available:
                self.engine_status.setText(st.detail + " Instale o Ollama (ollama.com) e rode: ollama pull qwen2.5:7b")
                return
            for box, pick in ((self.model, pick_chat_model), (self.embed, pick_embed_model)):
                cur = box.currentText()
                box.clear()
                box.addItems(st.models)
                box.setCurrentText(cur or pick(st.models))
            self.engine_status.setText(f"✓ {st.kind} respondendo · {len(st.models)} modelo(s) instalado(s).")

        run_async(self, client.status, done, lambda m: self.engine_status.setText(m))

    def test_voice(self) -> None:
        s = self.result_prefs().voice_settings()
        if not self.speaker.speak("Olá. Sou o NEXUS, seu assistente de análise. Às suas ordens.", s):
            notify(self, tts.describe(s)[1], "warning")
