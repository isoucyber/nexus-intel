"""Tela inicial: lista de projetos e criação (seção 6.2)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QWidget,
)

from nexus_intel.application.projects import ProjectInfo, ProjectManager
from nexus_intel.domain.catalog import TEMPLATES
from nexus_intel.ui.common import Page, button, card, confirm, fmt_ts, guarded, hbox, label

TEMPLATE_HINTS = {
    "blank": "Só os tipos padrão, sem dados.",
    "investigation": "Tipos padrão; pensado para pessoas, empresas e vínculos.",
    "research": "Tipos padrão; pensado para autores, instituições e documentos.",
    "it_assets": "Tipos padrão; pensado para domínios, IPs e sistemas.",
    "genealogy": "Tipos padrão; pensado para pessoas, lugares e datas imprecisas.",
    "example": "Dados fictícios para aprender: João → veículo → Veneza, com fontes e um conflito.",
}


class NewProjectDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Novo projeto")
        self.setMinimumWidth(480)
        self.color = "#2dd4bf"
        self.name = QLineEdit()
        self.template = QComboBox()
        for k, v in TEMPLATES.items():
            self.template.addItem(v, k)
        self.hint = label(TEMPLATE_HINTS["blank"], "Muted", wrap=True)
        self.template.currentIndexChanged.connect(
            lambda _: self.hint.setText(TEMPLATE_HINTS[self.template.currentData()]))
        self.purpose = QPlainTextEdit()
        self.purpose.setPlaceholderText("Para que servem os dados deste projeto?")
        self.purpose.setFixedHeight(60)
        self.legal = QComboBox()
        for opt in ("", "Uso exclusivamente particular e não econômico (LGPD art. 4º, I)",
                    "Consentimento do titular", "Legítimo interesse", "Cumprimento de obrigação legal",
                    "Exercício regular de direitos", "Atividade jornalística, artística ou acadêmica (art. 4º, II)",
                    "Outra (descrever na finalidade)"):
            self.legal.addItem(opt or "— escolher se houver dados de pessoas —", opt)
        self.color_btn = button("Cor", self._pick)
        self._paint()
        form = QFormLayout(self)
        form.addRow("Nome", self.name)
        form.addRow("Modelo", self.template)
        form.addRow("", self.hint)
        form.addRow("Finalidade", self.purpose)
        form.addRow("Base legal", self.legal)
        form.addRow("Cor", self.color_btn)
        self.ok = button("Criar projeto", self.accept, "Primary")
        form.addRow(hbox(None, button("Cancelar", self.reject), self.ok))
        self.name.setFocus()

    def _pick(self) -> None:
        from PySide6.QtGui import QColor

        c = QColorDialog.getColor(QColor(self.color), self, "Cor do projeto")
        if c.isValid():
            self.color = c.name()
            self._paint()

    def _paint(self) -> None:
        self.color_btn.setStyleSheet(f"background: {self.color}; color: #000; min-width: 60px;")

    def accept(self) -> None:
        if self.name.text().strip():
            super().accept()
        else:
            self.name.setFocus()


class ProjectsPage(Page):
    open_project = Signal(str)
    lock_requested = Signal()
    settings_requested = Signal()

    def __init__(self, manager: ProjectManager) -> None:
        super().__init__()
        self.manager = manager
        header = hbox(
            label("NEXUS INTEL", "Brand"), None,
            button("Configurações", self.settings_requested.emit),
            button("Bloquear  (Ctrl+L)", self.lock_requested.emit),
        )
        self.layout_.addWidget(header)
        self.layout_.addWidget(hbox(label("Projetos", "H1"), None,
                                    button("+ Novo projeto", self._new, "Primary")))
        self.layout_.addWidget(label(
            "Cada projeto é um arquivo separado, com chave própria. Dados de um projeto nunca "
            "aparecem em outro.", "Muted", wrap=True))
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid_host)
        self.layout_.addWidget(scroll, 1)

    def refresh(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        projects = guarded(self, self.manager.list) or []
        if not projects:
            empty = card(
                label("Nenhum projeto ainda", "H2"),
                label("Comece pelo modelo “Exemplo guiado” para ver como fontes, relações e "
                      "conflitos funcionam, ou crie um projeto em branco.", "Muted", wrap=True),
                hbox(button("Criar projeto de exemplo", lambda: self._create("Exemplo guiado", "example"),
                            "Primary"), button("Projeto em branco", self._new), None),
            )
            empty.setMaximumWidth(560)
            self.grid.addWidget(empty, 0, 0)
            return
        for i, p in enumerate(projects):
            self.grid.addWidget(self._card(p), i // 3, i % 3)

    def _card(self, p: ProjectInfo) -> QWidget:
        title = label(p.name, "H2")
        title.setStyleSheet(f"border-left: 4px solid {p.color}; padding-left: 8px;")
        meta = label(
            f"{p.entity_count} entidades · {TEMPLATES.get(p.template, p.template)}\n"
            f"{'Cifrado' if p.encrypted else 'Sem cifragem'} · última abertura: {fmt_ts(p.last_opened_at) or '—'}",
            "Muted")
        open_btn = button("Abrir", lambda pid=p.id: self.open_project.emit(pid), "Primary")
        del_btn = button("Excluir", lambda: self._delete(p), "Danger")
        c = card(title, meta, hbox(del_btn, None, open_btn))
        c.setFixedWidth(320)
        return c

    def _new(self) -> None:
        dlg = NewProjectDialog(self)
        if dlg.exec():
            self._create(dlg.name.text(), dlg.template.currentData(), dlg.color,
                         dlg.purpose.toPlainText(), dlg.legal.currentData() or "")

    def _create(self, name: str, template: str, color: str = "#2dd4bf", purpose: str = "", legal: str = "") -> None:
        info = guarded(self, lambda: self.manager.create(name, template, color, purpose, legal))
        if info:
            self.open_project.emit(info.id)

    def _delete(self, p: ProjectInfo) -> None:
        if confirm(self, "Excluir projeto",
                   f"Excluir definitivamente o projeto “{p.name}”?\n\nO arquivo do projeto será apagado "
                   "deste computador. Backups feitos antes continuam existindo.", danger=True):
            guarded(self, lambda: self.manager.delete(p.id))
            self.refresh()
