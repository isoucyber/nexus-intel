"""Tela inicial: lista de projetos e criação (seção 6.2)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from shiboken6 import isValid

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from nexus_intel import __version__
from nexus_intel.application.projects import ProjectInfo, ProjectManager
from nexus_intel.domain.catalog import TEMPLATES
from nexus_intel.domain.model import normalize_name
from nexus_intel.ui.design import tokens
from nexus_intel.ui.design.color import best_on
from nexus_intel.ui import format as fmt
from nexus_intel.ui.common import Page, button, confirm, guarded, hbox, label
from nexus_intel.ui.design import assets
from nexus_intel.ui.design.components import (
    Badge,
    Button,
    ElidedLabel,
    EmptyState,
    Input,
    ResponsiveGrid,
    Skeleton,
    dialog_form,
    notify,
    require_text,
    text,
)

TEMPLATE_HINTS = {
    "blank": "Só os tipos padrão, sem dados.",
    "investigation": "Tipos padrão; pensado para pessoas, empresas e vínculos.",
    "research": "Tipos padrão; pensado para autores, instituições e documentos.",
    "it_assets": "Tipos padrão; pensado para domínios, IPs e sistemas.",
    "genealogy": "Tipos padrão; pensado para pessoas, lugares e datas imprecisas.",
    "example": "Dados fictícios para aprender: pessoa → veículo → cidade, com fontes e um conflito.",
}


class NewProjectDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.color = tokens.ACCENT_PRESETS["Turquesa"]
        self.name = QLineEdit()
        self.template = QComboBox()
        for k, v in TEMPLATES.items():
            self.template.addItem(v, k)
        self.hint = label(TEMPLATE_HINTS["blank"], "Muted", wrap=True)
        self.template.currentIndexChanged.connect(
            lambda _: isValid(self.hint) and self.hint.setText(TEMPLATE_HINTS.get(self.template.currentData(), "")))
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
        form = dialog_form(self, "Novo projeto", 500)
        self.ok = button("Criar projeto", self.accept, "Primary")
        form.addRow("Nome *", self.name)
        form.addRow("", require_text(self.name, [self.ok], "O nome do projeto não pode ficar vazio."))
        form.addRow("Modelo", self.template)
        form.addRow("", self.hint)
        form.addRow("Finalidade", self.purpose)
        form.addRow("Base legal", self.legal)
        form.addRow("Cor", self.color_btn)
        form.addRow(hbox(None, button("Cancelar", self.reject), self.ok))
        self.name.setFocus()

    def _pick(self) -> None:
        from PySide6.QtGui import QColor

        c = QColorDialog.getColor(QColor(self.color), self, "Cor do projeto")
        if c.isValid():
            self.color = c.name()
            self._paint()

    def _paint(self) -> None:
        self.color_btn.setStyleSheet(f"background: {self.color}; color: {best_on(self.color)}; min-width: 60px;")

    def accept(self) -> None:
        if self.name.text().strip():
            super().accept()
        else:
            self.name.setFocus()


class ProjectCard(QFrame):
    """Card compacto: nome, categoria, números reais, última atividade, Abrir e Excluir."""

    def __init__(self, p: ProjectInfo, on_open: Callable[[str], None], on_delete: Callable[[ProjectInfo], None]) -> None:
        super().__init__()
        self.project = p
        self._on_open = on_open
        self.setProperty("card", "true")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"Projeto {p.name}")
        t = tokens.current()
        lay = QVBoxLayout(self)
        pad = tokens.CARD["pad"]
        lay.setContentsMargins(pad, pad - 2, pad, pad - 4)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"background: {p.color}; border-radius: 4px;")
        dot.setToolTip("Cor do projeto")
        head.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self.title = ElidedLabel(p.name, "h3")
        head.addWidget(self.title, 1)
        lock = QLabel()
        if p.encrypted:
            lock.setPixmap(assets.pixmap("lock", t.success, 14))
            lock.setToolTip("Cifrado: banco SQLCipher com chave própria deste projeto")
        else:
            lock.setPixmap(assets.pixmap("triangle-alert", t.warning, 14))
            lock.setToolTip("Sem cifragem: protegido só pelo login. Use a criptografia do disco")
        lock.setAccessibleName(lock.toolTip())
        head.addWidget(lock, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(head)

        category = text(TEMPLATES.get(p.template, p.template), "muted", wrap=True)
        category.setMaximumHeight(category.fontMetrics().lineSpacing() * 2 + 2)  # no máximo 2 linhas
        lay.addWidget(category)

        stats = QHBoxLayout()
        stats.setSpacing(12)
        stats.addWidget(_stat("database", f"{fmt.number(p.entity_count)} entidades",
                              "Contagem registrada no último fechamento do projeto"))
        stats.addWidget(_stat("file-text", "Anexos: indisponível",
                              "Anexos cifrados ainda não foram implementados", muted=True))
        stats.addStretch(1)
        lay.addLayout(stats)

        when = p.last_opened_at or p.created_at
        verb = "Aberto" if p.last_opened_at else "Criado"
        rel = fmt.relative(when)
        joiner = " " if rel in ("agora", "ontem") or rel.startswith("há") else " em "
        activity = text(f"{verb}{joiner}{rel}", "caption")
        activity.setToolTip(f"{'Última abertura' if p.last_opened_at else 'Criado em'}: {fmt.absolute(when)}")
        lay.addWidget(activity)
        lay.addStretch(1)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        delete = Button("Excluir", "ghost", "trash-2", size="sm", on_click=lambda: on_delete(p),
                        tooltip=f"Excluir o projeto “{p.name}”", tone="danger")
        foot.addWidget(delete)
        foot.addStretch(1)
        self.open_btn = Button("Abrir", "primary", size="sm", on_click=lambda: on_open(p.id),
                               tooltip=f"Abrir “{p.name}”")
        foot.addWidget(self.open_btn)
        lay.addLayout(foot)

    def mouseDoubleClickEvent(self, event: Any) -> None:  # noqa: N802
        self._on_open(self.project.id)


def _stat(icon: str, caption: str, tip: str, muted: bool = False) -> QWidget:
    t = tokens.current()
    w = QWidget()
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    ic = QLabel()
    ic.setPixmap(assets.pixmap(icon, t.text_disabled if muted else t.text_muted, 13))
    row.addWidget(ic)
    row.addWidget(text(caption, "caption" if muted else "secondary"))
    w.setToolTip(tip)
    return w


class SkeletonCard(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setProperty("card", "true")
        lay = QVBoxLayout(self)
        pad = tokens.CARD["pad"]
        lay.setContentsMargins(pad, pad, pad, pad)
        lay.addWidget(Skeleton(4, (0.7, 0.45, 0.8, 0.35), 11))
        lay.addStretch(1)


class ProjectsPage(Page):
    open_project = Signal(str)
    lock_requested = Signal()
    settings_requested = Signal()
    switch_profile_requested = Signal()
    import_requested = Signal()

    def __init__(self, manager: ProjectManager) -> None:
        super().__init__()
        self.manager = manager
        self.projects: list[ProjectInfo] = []

        # 1. barra superior compacta
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(label("NEXUS INTEL", "Brand"))
        top.addWidget(Badge(f"v{__version__}", "accent", tooltip="Versão instalada"))
        top.addStretch(1)
        self.profile_btn = Button("Perfil", "ghost", "users", on_click=self.switch_profile_requested.emit,
                                  tooltip="Perfil ativo — clique para trocar de perfil")
        top.addWidget(self.profile_btn)
        top.addWidget(Button("Configurações", "ghost", "settings", on_click=self.settings_requested.emit))
        top.addWidget(Button("Bloquear", "ghost", "lock", on_click=self.lock_requested.emit, shortcut="Ctrl+L"))
        self.layout_.addLayout(top)

        # 2. título, contador real, pesquisa e novo projeto
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_row.addWidget(text("Projetos", "h1"))
        self.count = Badge("0", "neutral", tooltip="Projetos neste computador")
        title_row.addWidget(self.count, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        self.search = Input("Pesquisar projetos…", icon="search", clearable=True)
        self.search.setFixedWidth(280)
        self.search.textChanged.connect(lambda _: self._render())
        title_row.addWidget(self.search)
        title_row.addWidget(Button("Importar .nexus", "secondary", "download", on_click=self.import_requested.emit,
                                   tooltip="Importar um projeto compartilhado (arquivo .nexus cifrado)"))
        title_row.addWidget(Button("Novo projeto", "primary", "plus", on_click=self._new))
        self.layout_.addLayout(title_row)

        # 3. grade e estados
        c = tokens.CARD
        self.grid = ResponsiveGrid(c["min_w"], c["max_w"], c["min_h"], c["gap"])
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 4, 0, 4)
        hl.addWidget(self.grid)
        hl.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(holder)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.loading = ResponsiveGrid(c["min_w"], c["max_w"], c["min_h"], c["gap"])
        self.loading.set_items([SkeletonCard() for _ in range(3)])
        loading_holder = QWidget()
        ll = QVBoxLayout(loading_holder)
        ll.setContentsMargins(0, 4, 0, 0)
        ll.addWidget(self.loading)
        ll.addStretch(1)

        self.empty = EmptyState(
            "folder-plus", "Nenhum projeto ainda",
            "Cada projeto é um arquivo separado, com chave própria. Comece pelo exemplo guiado para ver "
            "fontes, relações e conflitos funcionando, ou crie um projeto em branco.",
            "Criar primeiro projeto", self._new, "Abrir exemplo guiado",
            lambda: self._create("Exemplo guiado", "example"))
        self.error = EmptyState("circle-alert", "Não foi possível carregar os projetos",
                                "O banco da aplicação não respondeu. Seus arquivos não foram alterados.",
                                "Tentar novamente", self.refresh)
        self.error_detail = text("", "caption", wrap=True)
        self.error.layout().addWidget(self.error_detail, 0, Qt.AlignmentFlag.AlignHCenter)
        self.no_results = EmptyState("search", "Nenhum projeto encontrado",
                                     "Nenhum nome ou categoria corresponde à pesquisa.", "Limpar pesquisa",
                                     self.search.clear)
        self.stack = QStackedWidget()
        for w in (loading_holder, self.scroll, self.empty, self.error, self.no_results):
            self.stack.addWidget(w)
        self.stack.setCurrentIndex(0)  # carregando até a primeira leitura
        self.layout_.addWidget(self.stack, 1)

    def set_profile_name(self, name: str) -> None:
        self.profile_btn.setText(name)

    # ----------------------------------------------------------------- dados
    def refresh(self) -> None:
        self.stack.setCurrentIndex(0)
        try:
            self.projects = self.manager.list()
        except Exception as exc:  # noqa: BLE001 - qualquer falha vira o estado de erro
            self.error_detail.setText(getattr(exc, "user_message", "") or type(exc).__name__)
            self.count.set_text("—")
            self.stack.setCurrentWidget(self.error)
            return
        self.count.set_text(str(len(self.projects)))
        self._render()

    def _filtered(self) -> list[ProjectInfo]:
        q = normalize_name(self.search.text())
        if not q:
            return self.projects
        return [p for p in self.projects
                if q in normalize_name(p.name) or q in normalize_name(TEMPLATES.get(p.template, ""))]

    def _render(self) -> None:
        if not isValid(self) or not isValid(self.grid):
            return
        if not self.projects:
            self.grid.clear()
            self.stack.setCurrentWidget(self.empty)
            return
        shown = self._filtered()
        if not shown:
            self.grid.clear()
            self.stack.setCurrentWidget(self.no_results)
            return
        cards = [ProjectCard(p, self.open_project.emit, self._delete) for p in shown]
        # Altura definida pelo conteúdo, igual para todos e limitada à faixa do token.
        c = tokens.CARD
        natural = max(card.sizeHint().height() for card in cards)
        self.grid.set_item_height(max(c["min_h"], min(c["max_h"], natural)))
        self.grid.set_items(cards)
        self.stack.setCurrentWidget(self.scroll)

    def _new(self) -> None:
        dlg = NewProjectDialog(self)
        if dlg.exec():
            self._create(dlg.name.text(), dlg.template.currentData(), dlg.color,
                         dlg.purpose.toPlainText(), dlg.legal.currentData() or "")

    def _create(self, name: str, template: str, color: str | None = None, purpose: str = "", legal: str = "") -> None:
        color = color or tokens.ACCENT_PRESETS["Turquesa"]
        info = guarded(self, lambda: self.manager.create(name, template, color, purpose, legal))
        if info:
            self.open_project.emit(info.id)

    def _delete(self, p: ProjectInfo) -> None:
        if confirm(self, "Excluir projeto",
                   f"Excluir definitivamente o projeto “{p.name}”?\n\nO arquivo do projeto será apagado "
                   "deste computador. Backups feitos antes continuam existindo.", danger=True):
            if guarded(self, lambda: self.manager.delete(p.id) or True):
                notify(self, f"Projeto “{p.name}” excluído.", "success")
            self.refresh()
