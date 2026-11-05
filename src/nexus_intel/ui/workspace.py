"""Área de trabalho de um projeto: navegação, central de informações e páginas auxiliares."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from nexus_intel.application.project_store import ProjectStore
from nexus_intel.domain.model import EPISTEMIC_LABELS, SOURCE_KINDS, Epistemic
from nexus_intel.ui.common import (
    Page,
    button,
    card,
    confirm,
    fmt_ts,
    guarded,
    hbox,
    label,
)
from nexus_intel.ui.dialogs import NewEntityDialog, SourceDialog
from nexus_intel.ui.entity_page import EntityPage
from nexus_intel.ui.graph_view import GraphPage
from nexus_intel.ui.theme import STATUS_COLORS

_ROLE = Qt.ItemDataRole.UserRole


def _ro(text: Any, data: Any = None) -> QTableWidgetItem:
    it = QTableWidgetItem("" if text is None else str(text))
    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if data is not None:
        it.setData(_ROLE, data)
    return it


def _table(headers: list[str], stretch: int = 0) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setAlternatingRowColors(True)
    t.verticalHeader().hide()
    t.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
    t.setSortingEnabled(False)
    return t


# ------------------------------------------------------------------- início
class DashboardPage(Page):
    open_entity = Signal(str)

    def __init__(self, store: ProjectStore) -> None:
        super().__init__()
        self.store = store
        self.layout_.addWidget(label("Início", "H1"))
        self.counters = hbox()
        self.layout_.addWidget(self.counters)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        self.recent = QListWidget()
        self.recent.itemDoubleClicked.connect(lambda it: self.open_entity.emit(it.data(_ROLE)))
        self.types = QListWidget()
        self.statuses = QListWidget()
        for title, w in (("Atualizadas recentemente", self.recent), ("Entidades por tipo", self.types),
                         ("Afirmações por status", self.statuses)):
            rl.addWidget(card(label(title, "H2"), w))
        self.layout_.addWidget(row, 1)

    def refresh(self) -> None:
        s = guarded(self, self.store.stats)
        if not s:
            return
        lay = self.counters.layout()
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for text, n in (("Entidades", s["entities"]), ("Relações", s["relations"]),
                        ("Afirmações", s["claims"]), ("Fontes", s["sources"]), ("Na lixeira", s["trashed"])):
            big = label(str(n), "H1")
            lay.addWidget(card(big, label(text, "Muted")))
        lay.addStretch(1)
        self.recent.clear()
        for r in s["recent"]:
            it = QListWidgetItem(f"{r['display_name']}  ·  {r['type_label']}  ·  {fmt_ts(r['updated_at'])}")
            it.setData(_ROLE, r["id"])
            self.recent.addItem(it)
        self.types.clear()
        total = max(1, sum(r["n"] for r in s["by_type"]))
        for r in s["by_type"]:
            bar = "█" * max(1, round(20 * r["n"] / total))
            it = QListWidgetItem(f"{r['label']:<16} {bar} {r['n']}")
            it.setForeground(QColor(r["color"]))
            self.types.addItem(it)
        self.statuses.clear()
        for r in s["by_status"]:
            st = r["epistemic_status"]
            it = QListWidgetItem(f"{EPISTEMIC_LABELS.get(Epistemic(st), st)}: {r['n']}")
            it.setForeground(QColor(STATUS_COLORS.get(st, "#94a3b8")))
            self.statuses.addItem(it)


# ------------------------------------------------------------------- central
class EntitiesPage(Page):
    open_entity = Signal(str)
    changed = Signal()

    PAGE = 200

    def __init__(self, store: ProjectStore) -> None:
        super().__init__()
        self.store = store
        self.offset = 0
        self.type = QComboBox()
        self.type.addItem("Todos os tipos", None)
        for t in store.entity_types():
            self.type.addItem(t["label"], t["id"])
        self.status = QComboBox()
        for k, v in (("active", "Ativas"), ("archived", "Arquivadas")):
            self.status.addItem(v, k)
        self.order = QComboBox()
        for k, v in (("updated", "Atualização"), ("name", "Nome"), ("created", "Criação"),
                     ("importance", "Importância")):
            self.order.addItem(f"Ordenar: {v}", k)
        self.filter_text = QLineEdit()
        self.filter_text.setPlaceholderText("Filtrar (busca textual, tipo:pessoa, tag:italia)…")
        self.no_source = QComboBox()
        self.no_source.addItem("Com e sem fonte", False)
        self.no_source.addItem("Só sem nenhuma fonte", True)
        self.fav = QComboBox()
        self.fav.addItem("Todos", False)
        self.fav.addItem("Só favoritos", True)
        for c in (self.type, self.status, self.order, self.no_source, self.fav):
            c.currentIndexChanged.connect(lambda _: self.reset())
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self.reset)
        self.filter_text.textChanged.connect(lambda _: self._debounce.start())

        self.layout_.addWidget(hbox(label("Central de Informações", "H1"), None,
                                    button("+ Nova entidade  (Ctrl+N)", self.new_entity, "Primary")))
        self.layout_.addWidget(hbox(self.filter_text, self.type, self.status, self.no_source, self.fav, self.order))
        self.table = _table(["Nome", "Tipo", "Relações", "Importância", "Resumo", "Atualizada"], 0)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(lambda r, _c: self.open_entity.emit(self.table.item(r, 0).data(_ROLE)))
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.layout_.addWidget(self.table, 1)
        self.more = button("Carregar mais", self._more)
        self.count = label("", "Muted")
        self.layout_.addWidget(hbox(self.count, None, button("Arquivar selecionadas", lambda: self._bulk("archived")),
                                    button("Mover selecionadas para a lixeira", lambda: self._bulk("trashed"), "Danger"),
                                    self.more))

    def reset(self) -> None:
        self.offset = 0
        self.table.setRowCount(0)
        self._load()

    def _more(self) -> None:
        self.offset += self.PAGE
        self._load()

    def _load(self) -> None:
        text = self.filter_text.text().strip()
        if text:
            rows = guarded(self, lambda: self.store.search(text, 500)) or []
            self.more.hide()
            rows = [dict(r, relation_count="", importance="", updated_at="") for r in rows]
        else:
            rows = guarded(self, lambda: self.store.list_entities(
                type_id=self.type.currentData(), status=self.status.currentData(),
                favorites_only=self.fav.currentData(), without_evidence=self.no_source.currentData(),
                order=self.order.currentData(), limit=self.PAGE, offset=self.offset)) or []
            self.more.setVisible(len(rows) == self.PAGE)
        start = self.table.rowCount()
        self.table.setRowCount(start + len(rows))
        for i, r in enumerate(rows, start):
            name = _ro(("★ " if r.get("is_favorite") else "") + r["display_name"], r["id"])
            name.setForeground(QColor(r["effective_color"]))
            self.table.setItem(i, 0, name)
            self.table.setItem(i, 1, _ro(r["type_label"]))
            self.table.setItem(i, 2, _ro(r.get("relation_count")))
            self.table.setItem(i, 3, _ro(r.get("importance")))
            self.table.setItem(i, 4, _ro(r.get("snippet") or r["summary"]))
            self.table.setItem(i, 5, _ro(fmt_ts(r.get("updated_at"))))
        self.table.resizeColumnToContents(1)
        self.count.setText(f"{self.table.rowCount()} exibidas · {self.store.count_entities()} ativas no projeto")

    def _selected_ids(self) -> list[str]:
        rows = {i.row() for i in self.table.selectedIndexes()}
        return [self.table.item(r, 0).data(_ROLE) for r in sorted(rows)]

    def _bulk(self, status: str) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        verb = "arquivar" if status == "archived" else "mover para a lixeira"
        if confirm(self, "Ação em lote", f"{verb.capitalize()} {len(ids)} entidade(s)?", status == "trashed"):
            for eid in ids:
                guarded(self, lambda eid=eid: self.store.set_entity_status(eid, status))
            self.reset()
            self.changed.emit()

    def new_entity(self, name: str = "") -> None:
        dlg = NewEntityDialog(self.store, self, name=name)
        if dlg.exec():
            target = dlg.entity_id or dlg.existing_id
            self.reset()
            self.changed.emit()
            if target:
                self.open_entity.emit(target)


# ------------------------------------------------------------------- fontes
class SourcesPage(Page):
    open_entity = Signal(str)

    def __init__(self, store: ProjectStore) -> None:
        super().__init__()
        self.store = store
        self.q = QLineEdit()
        self.q.setPlaceholderText("Filtrar por título ou URL…")
        self.q.textChanged.connect(lambda _: self.refresh())
        self.layout_.addWidget(hbox(label("Fontes", "H1"), None, button("+ Nova fonte", self._new, "Primary")))
        self.layout_.addWidget(label("Confiabilidade da fonte (A–F) e credibilidade da informação (1–6) seguem a "
                                     "escala do Almirantado e são sempre definidas por você.", "Muted", wrap=True))
        self.layout_.addWidget(self.q)
        self.table = _table(["Título", "Tipo", "Confiab.", "Usos", "URL", "Consultada"], 0)
        self.table.cellDoubleClicked.connect(lambda r, _c: self._edit(self.table.item(r, 0).data(_ROLE)))
        self.table.currentCellChanged.connect(lambda r, *_: self._usages(r))
        self.layout_.addWidget(self.table, 2)
        self.layout_.addWidget(label("Onde esta fonte é usada (duplo clique abre a entidade):", "Muted"))
        self.uses = QListWidget()
        self.uses.itemDoubleClicked.connect(lambda it: self.open_entity.emit(it.data(_ROLE)))
        self.layout_.addWidget(self.uses, 1)

    def refresh(self) -> None:
        rows = guarded(self, lambda: self.store.list_sources(self.q.text())) or []
        self.table.setRowCount(len(rows))
        for i, s in enumerate(rows):
            t = _ro(s["title"] + ("  (desacreditada)" if s["is_discredited"] else ""), s["id"])
            if s["is_discredited"]:
                t.setForeground(QColor(STATUS_COLORS["refuted"]))
            self.table.setItem(i, 0, t)
            self.table.setItem(i, 1, _ro(SOURCE_KINDS.get(s["kind"], s["kind"])))
            self.table.setItem(i, 2, _ro(s["reliability"] or "—"))
            self.table.setItem(i, 3, _ro(s["uses"]))
            self.table.setItem(i, 4, _ro(s["url"] or ""))
            self.table.setItem(i, 5, _ro(s["accessed_at"] or ""))
        self.uses.clear()

    def _usages(self, row: int) -> None:
        self.uses.clear()
        if row < 0 or not self.table.item(row, 0):
            return
        for u in self.store.source_usages(self.table.item(row, 0).data(_ROLE)):
            ex = f" — “{u['excerpt']}”" if u["excerpt"] else ""
            it = QListWidgetItem(f"{u['label'] or '(removido)'}{ex}")
            it.setData(_ROLE, u["entity_id"])
            self.uses.addItem(it)

    def _new(self) -> None:
        if SourceDialog(self.store, self).exec():
            self.refresh()

    def _edit(self, sid: str) -> None:
        if SourceDialog(self.store, self, source=self.store.get_source(sid)).exec():
            self.refresh()


# ------------------------------------------------------------------- qualidade
class QualityPage(Page):
    open_entity = Signal(str)
    changed = Signal()

    def __init__(self, store: ProjectStore) -> None:
        super().__init__()
        self.store = store
        self.layout_.addWidget(label("Qualidade dos dados", "H1"))
        self.counters = label("", "Muted", wrap=True)
        self.layout_.addWidget(self.counters)
        tabs = QTabWidget()
        self.conflicts = _table(["Entidade", "Campo em conflito"], 0)
        self.conflicts.cellDoubleClicked.connect(lambda r, _c: self.open_entity.emit(self.conflicts.item(r, 0).data(_ROLE)))
        self.orphans = _table(["Entidade sem nenhuma fonte", "Tipo"], 0)
        self.orphans.cellDoubleClicked.connect(lambda r, _c: self.open_entity.emit(self.orphans.item(r, 0).data(_ROLE)))
        dup_page = QWidget()
        dl = QVBoxLayout(dup_page)
        self.dups = _table(["Entidade A", "Entidade B", "Semelhança", "Motivos"], 3)
        dl.addWidget(hbox(button("Procurar duplicatas", self._scan, "Primary"), None,
                          button("São diferentes", self._different), button("Mesclar B em A", self._merge)))
        dl.addWidget(self.dups, 1)
        tabs.addTab(self.conflicts, "Conflitos")
        tabs.addTab(self.orphans, "Sem fonte")
        tabs.addTab(dup_page, "Possíveis duplicatas")
        self.layout_.addWidget(tabs, 1)

    def refresh(self) -> None:
        q = guarded(self, self.store.quality)
        if not q:
            return
        self.counters.setText(
            f"Afirmações sem fonte: {q['claims_without_source']} · Relações sem fonte: {q['relations_without_source']} · "
            f"Entidades sem relação: {q['orphans']} · Revisões vencidas: {q['review_due']} · "
            f"Fontes desacreditadas: {q['discredited_sources']}")
        rows = self.store.conflicting_entities()
        self.conflicts.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.conflicts.setItem(i, 0, _ro(r["display_name"], r["entity_id"]))
            self.conflicts.setItem(i, 1, _ro(r["field"]))
        rows = self.store.list_entities(without_evidence=True, limit=500)
        self.orphans.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.orphans.setItem(i, 0, _ro(r["display_name"], r["id"]))
            self.orphans.setItem(i, 1, _ro(r["type_label"]))

    def _scan(self) -> None:
        pairs = guarded(self, self.store.scan_duplicates) or []
        self.dups.setRowCount(len(pairs))
        for i, (a, c) in enumerate(pairs):
            self.dups.setItem(i, 0, _ro(a["display_name"], a["id"]))
            self.dups.setItem(i, 1, _ro(c.display_name, c.entity_id))
            self.dups.setItem(i, 2, _ro(f"{c.score}%"))
            self.dups.setItem(i, 3, _ro("; ".join(c.reasons)))
        if not pairs:
            self.dups.setRowCount(1)
            self.dups.setItem(0, 0, _ro("Nenhuma duplicata provável encontrada."))

    def _pair(self) -> tuple[str, str] | None:
        r = self.dups.currentRow()
        a, b = self.dups.item(r, 0), self.dups.item(r, 1)
        if r < 0 or not a or not b or not a.data(_ROLE):
            return None
        return a.data(_ROLE), b.data(_ROLE)

    def _different(self) -> None:
        p = self._pair()
        if p:
            guarded(self, lambda: self.store.record_dedupe_decision(p[0], p[1], "different"))
            self.dups.removeRow(self.dups.currentRow())

    def _merge(self) -> None:
        p = self._pair()
        if p and confirm(self, "Mesclar entidades",
                         "Mesclar B em A? Afirmações, relações, fontes, nomes e etiquetas de B passam para A, "
                         "e B vai para a lixeira. Dá para desfazer pelo histórico de A."):
            guarded(self, lambda: self.store.merge_entities(p[0], p[1]))
            self.dups.removeRow(self.dups.currentRow())
            self.changed.emit()
            self.open_entity.emit(p[0])


# ------------------------------------------------------------------- lixeira
class TrashPage(Page):
    changed = Signal()

    def __init__(self, store: ProjectStore) -> None:
        super().__init__()
        self.store = store
        self.layout_.addWidget(hbox(label("Lixeira", "H1"), None,
                                    button("Restaurar selecionada", self._restore, "Primary"),
                                    button("Excluir definitivamente", self._purge, "Danger"),
                                    button("Esvaziar lixeira", self._empty, "Danger")))
        self.layout_.addWidget(label("Itens na lixeira não aparecem na busca, no grafo nem nas listas. "
                                     "Restaurar devolve relações e afirmações.", "Muted", wrap=True))
        self.table = _table(["Nome", "Tipo", "Na lixeira desde"], 0)
        self.layout_.addWidget(self.table, 1)

    def refresh(self) -> None:
        rows = guarded(self, lambda: self.store.list_entities(status="trashed", limit=1000)) or []
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.table.setItem(i, 0, _ro(r["display_name"], r["id"]))
            self.table.setItem(i, 1, _ro(r["type_label"]))
            self.table.setItem(i, 2, _ro(fmt_ts(r["updated_at"])))

    def _current(self) -> str | None:
        it = self.table.item(self.table.currentRow(), 0)
        return it.data(_ROLE) if it else None

    def _restore(self) -> None:
        eid = self._current()
        if eid:
            guarded(self, lambda: self.store.restore_entity(eid))
            self.refresh()
            self.changed.emit()

    def _purge(self) -> None:
        eid = self._current()
        if eid and confirm(self, "Excluir definitivamente", "Esta ação não pode ser desfeita. Continuar?", True):
            guarded(self, lambda: self.store.delete_entity_permanently(eid))
            self.refresh()

    def _empty(self) -> None:
        if confirm(self, "Esvaziar lixeira", "Excluir definitivamente tudo que está na lixeira?", True):
            n = guarded(self, self.store.empty_trash)
            self.refresh()
            self.changed.emit()
            del n


# ------------------------------------------------------------------- auditoria
class AuditPage(Page):
    def __init__(self, store: ProjectStore) -> None:
        super().__init__()
        self.store = store
        self.result = label("", "Muted")
        self.layout_.addWidget(hbox(label("Auditoria", "H1"), None, self.result,
                                    button("Verificar integridade", self._verify, "Primary")))
        self.layout_.addWidget(label("Cada linha guarda o hash da anterior. A verificação detecta linhas "
                                     "alteradas ou apagadas depois de gravadas.", "Muted", wrap=True))
        self.table = _table(["Quando", "Ação", "Objeto", "Resumo", "Usuário"], 3)
        self.layout_.addWidget(self.table, 1)

    def refresh(self) -> None:
        rows = guarded(self, lambda: self.store.audit_entries(500)) or []
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, v in enumerate((fmt_ts(r["ts"]), r["action"], r["object_kind"] or "", r["summary"], r["actor"])):
                self.table.setItem(i, j, _ro(v))

    def _verify(self) -> None:
        bad = guarded(self, self.store.verify_audit)
        self.result.setText("Cadeia íntegra ✔" if bad is None else f"Adulteração detectada na linha {bad} ✖")
        self.result.setObjectName("Muted" if bad is None else "Danger")
        self.result.setStyleSheet("")


# ------------------------------------------------------------------- busca global
class SearchBox(QLineEdit):
    """Busca global (Ctrl+K) com captura rápida: “Nome · tipo” + Enter cria a entidade."""

    open_entity = Signal(str)
    created = Signal()

    def __init__(self, store: ProjectStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.setPlaceholderText("Buscar ou criar…  (Ctrl+K)   ex.: Maria Souza · pessoa")
        self.setMinimumWidth(420)
        self.popup = QListWidget()
        self.popup.setWindowFlags(Qt.WindowType.ToolTip)
        self.popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.popup.itemClicked.connect(self._choose)
        self.popup.setMouseTracking(True)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._search)
        self.textEdited.connect(lambda _: self._timer.start())
        self.returnPressed.connect(self._enter)

    def _search(self) -> None:
        text = self.text().strip()
        self.popup.clear()
        if not text:
            self.popup.hide()
            return
        for r in self.store.search(text.split("·")[0], 12):
            it = QListWidgetItem(f"{r['display_name']}   ·  {r['type_label']}")
            it.setData(_ROLE, r["id"])
            self.popup.addItem(it)
        create = QListWidgetItem(f"+ Criar “{text}”")
        create.setData(_ROLE, None)
        self.popup.addItem(create)
        self.popup.setCurrentRow(0)
        pos = self.mapToGlobal(self.rect().bottomLeft())
        self.popup.setGeometry(pos.x(), pos.y() + 2, self.width(), min(320, 26 * self.popup.count() + 8))
        self.popup.show()

    def keyPressEvent(self, event: Any) -> None:
        if self.popup.isVisible() and event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            row = self.popup.currentRow() + (1 if event.key() == Qt.Key.Key_Down else -1)
            self.popup.setCurrentRow(max(0, min(self.popup.count() - 1, row)))
            return
        if event.key() == Qt.Key.Key_Escape:
            self.popup.hide()
            self.clear()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event: Any) -> None:
        QTimer.singleShot(200, self.popup.hide)
        super().focusOutEvent(event)

    def _enter(self) -> None:
        if self.popup.isVisible() and self.popup.currentItem():
            self._choose(self.popup.currentItem())
        elif self.text().strip():
            self._create()

    def _choose(self, item: QListWidgetItem) -> None:
        eid = item.data(_ROLE)
        if eid:
            self.open_entity.emit(eid)
            self.popup.hide()
            self.clear()
        else:
            self._create()

    def _create(self) -> None:
        text = self.text().strip()
        self.popup.hide()
        eid = guarded(self, lambda: self.store.quick_capture(text))
        if eid:
            self.clear()
            self.created.emit()
            self.open_entity.emit(eid)


# ------------------------------------------------------------------- espaço
class Workspace(QWidget):
    back_to_projects = Signal()
    lock_requested = Signal()

    NAV = (("home", "Início"), ("entities", "Central de Informações"), ("graph", "Grafo"),
           ("sources", "Fontes"), ("quality", "Qualidade"), ("trash", "Lixeira"), ("audit", "Auditoria"))

    def __init__(self, store: ProjectStore, project_name: str, color: str, theme: str) -> None:
        super().__init__()
        self.store = store
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(220)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(12, 16, 12, 12)
        brand = label("NEXUS INTEL", "Brand")
        sl.addWidget(brand)
        pname = label(project_name, "H2")
        pname.setWordWrap(True)
        pname.setStyleSheet(f"border-left: 4px solid {color}; padding-left: 8px;")
        sl.addWidget(pname)
        sl.addSpacing(12)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons: dict[str, Any] = {}
        for key, text in self.NAV:
            b = button(text, lambda k=key: self.go(k), "Nav")
            b.setCheckable(True)
            self.nav_group.addButton(b)
            self.nav_buttons[key] = b
            sl.addWidget(b)
        sl.addStretch(1)
        sl.addWidget(button("← Projetos", self.back_to_projects.emit))
        sl.addWidget(button("Bloquear  (Ctrl+L)", self.lock_requested.emit))
        root.addWidget(side)

        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)
        top = QFrame()
        top.setObjectName("TopBar")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(16, 8, 16, 8)
        self.search = SearchBox(store)
        tl.addWidget(self.search)
        tl.addStretch(1)
        tl.addWidget(label("● local · offline", "Muted"))
        ml.addWidget(top)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.stack = QStackedWidget()
        self.pages: dict[str, Any] = {
            "home": DashboardPage(store),
            "entities": EntitiesPage(store),
            "graph": GraphPage(store, theme),
            "sources": SourcesPage(store),
            "quality": QualityPage(store),
            "trash": TrashPage(store),
            "audit": AuditPage(store),
        }
        for key, page in self.pages.items():
            self.stack.addWidget(page)
            if hasattr(page, "open_entity"):
                page.open_entity.connect(self.open_entity)
            if hasattr(page, "changed"):
                page.changed.connect(self._data_changed)
        self.tabs.addTab(self.stack, "Painel")
        self.tabs.tabBar().setTabButton(0, self.tabs.tabBar().ButtonPosition.RightSide, None)
        ml.addWidget(self.tabs, 1)
        root.addWidget(main, 1)

        self.search.open_entity.connect(self.open_entity)
        self.search.created.connect(self._data_changed)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=lambda: (self.search.setFocus(), self.search.selectAll()))
        QShortcut(QKeySequence("Ctrl+N"), self, activated=lambda: (self.go("entities"), self.pages["entities"].new_entity()))
        QShortcut(QKeySequence("Ctrl+G"), self, activated=lambda: self.go("graph"))
        QShortcut(QKeySequence("Ctrl+W"), self, activated=lambda: self._close_tab(self.tabs.currentIndex()))
        self._loaded: set[str] = set()
        self.go("home" if store.count_entities() else "entities")

    def go(self, key: str) -> None:
        self.nav_buttons[key].setChecked(True)
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        self.tabs.setCurrentIndex(0)
        if key == "graph":
            if key not in self._loaded:
                page.reload()
        elif key == "entities":
            page.reset()
        else:
            page.refresh()
        self._loaded.add(key)

    def open_entity(self, eid: str) -> None:
        for i in range(1, self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, EntityPage) and w.entity_id == eid:
                w.refresh()
                self.tabs.setCurrentIndex(i)
                return
        page = EntityPage(self.store, eid)
        page.open_entity.connect(self.open_entity)
        page.changed.connect(self._data_changed)
        page.show_in_graph.connect(self._show_in_graph)
        name = page.entity.get("display_name", "Entidade")
        idx = self.tabs.addTab(page, name if len(name) < 24 else name[:22] + "…")
        self.tabs.setTabToolTip(idx, name)
        self.tabs.setCurrentIndex(idx)
        if self.tabs.count() > 12:  # limite de abas abertas
            self._close_tab(1)

    def _show_in_graph(self, eid: str) -> None:
        self.go("graph")
        self.pages["graph"].focus(eid)

    def _close_tab(self, index: int) -> None:
        if index > 0:
            w = self.tabs.widget(index)
            self.tabs.removeTab(index)
            w.deleteLater()

    def _data_changed(self) -> None:
        # Marca páginas para recarregar ao voltar; atualiza a visível agora.
        self._loaded.discard("graph")
        for i in range(1, self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, EntityPage) and w is not self.tabs.currentWidget():
                w.refresh()
        current = self.stack.currentWidget()
        if current is self.pages["entities"]:
            current.reset()
        elif current is self.pages["home"]:
            current.refresh()
