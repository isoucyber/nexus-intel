"""Nexus Notepad: notas do projeto com salvamento automático (0.3.4).

Lista à esquerda (busca, ordem, nova nota) e editor à direita. Cada nota pode
ficar ligada a uma entidade. O texto é salvo sozinho pouco depois de você
parar de digitar, ao trocar de nota e ao sair da tela.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QSplitter, QStackedWidget, QVBoxLayout, QWidget
from shiboken6 import isValid

from nexus_intel.application.project_store import ProjectStore
from nexus_intel.domain.errors import NexusError
from nexus_intel.ui import format as fmt
from nexus_intel.ui.common import Page, confirm, guarded
from nexus_intel.ui.design.components import (
    Button,
    EmptyState,
    Input,
    SectionHeader,
    Select,
    notify,
    text,
)
from nexus_intel.ui.design.table import Column, DataTable

AUTOSAVE_MS = 700


def _title_of(row: dict[str, Any]) -> str:
    return row.get("title") or "Nota sem título"


class NotesPage(Page):
    open_entity = Signal(str)

    def __init__(self, store: ProjectStore) -> None:
        super().__init__()
        self.store = store
        self.current_id: str | None = None
        self._loading = False
        self._dirty = False
        self.layout_.addWidget(SectionHeader(
            "Notas", "Observações, ideias e informações preliminares da investigação. Salvas automaticamente.",
            [Button("Nova nota", "primary", "plus", on_click=self.new_note, tooltip="Nova nota")]))

        # ---- lista
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(8)
        self.search = Input("Pesquisar notas…", icon="search", clearable=True)
        self.search.textChanged.connect(lambda _t: self.refresh())
        self.order = Select([("Atualizadas recentemente", "updated"), ("Criadas recentemente", "created"),
                             ("Título (A–Z)", "title")])
        self.order.currentIndexChanged.connect(lambda _i: self.refresh())
        ll.addWidget(self.search)
        ll.addWidget(self.order)
        self.table = DataTable([Column("title", "Título", stretch=True, getter=_title_of),
                                Column("updated_at", "Atualizada", "reltime", width=100)])
        self.table.setSelectionMode(DataTable.SelectionMode.SingleSelection)
        self.table.selectionModel().currentRowChanged.connect(lambda cur, _p: self._pick(cur.row()))
        self.list_empty = text("Nenhuma nota encontrada.", "muted", wrap=True)
        ll.addWidget(self.table, 1)
        ll.addWidget(self.list_empty)

        # ---- editor
        editor = QWidget()
        el = QVBoxLayout(editor)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(8)
        self.title = Input("Título da nota")
        self.entity = Select()
        self.entity.setToolTip("Entidade relacionada a esta nota (opcional)")
        self.open_btn = Button("Abrir entidade", "ghost", "arrow-up-right", size="sm",
                               on_click=self._open_linked)
        row = QHBoxLayout()
        row.addWidget(text("Vinculada a", "caption"))
        row.addWidget(self.entity, 1)
        row.addWidget(self.open_btn)
        self.body = QPlainTextEdit()
        self.body.setPlaceholderText("Escreva aqui…")
        self.body.setTabChangesFocus(False)
        self.meta = text("", "caption")
        self.status = text("", "caption")
        self.delete_btn = Button("Excluir nota", "ghost", "trash-2", size="sm", tone="danger",
                                 on_click=self.delete_current)
        foot = QHBoxLayout()
        foot.addWidget(self.meta, 1)
        foot.addWidget(self.status)
        foot.addWidget(self.delete_btn)
        el.addWidget(self.title)
        el.addLayout(row)
        el.addWidget(self.body, 1)
        el.addLayout(foot)

        self.editor_stack = QStackedWidget()
        self.editor_stack.addWidget(editor)
        self.no_note = EmptyState("pencil", "Nenhuma nota selecionada",
                                  "Crie uma nota para registrar observações sem sair do NEXUS.",
                                  "Nova nota", self.new_note)
        self.editor_stack.addWidget(self.no_note)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left)
        split.addWidget(self.editor_stack)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 700])
        split.setChildrenCollapsible(False)
        left.setMinimumWidth(240)
        self.layout_.addWidget(split, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(AUTOSAVE_MS)
        self._timer.timeout.connect(self.save_now)
        self.title.textEdited.connect(self._changed)
        self.body.textChanged.connect(self._changed)
        self.entity.currentIndexChanged.connect(lambda _i: (self._changed(), self._sync_open_btn()))
        self.editor_stack.setCurrentWidget(self.no_note)

    # ------------------------------------------------------------ dados
    def _fill_entities(self, current: str | None) -> None:
        self.entity.blockSignals(True)
        self.entity.clear()
        self.entity.addItem("Sem vínculo", None)
        rows = guarded(self, lambda: self.store.list_entities(limit=2000)) or []
        for e in sorted(rows, key=lambda r: r["display_name"].lower()):
            self.entity.addItem(f"{e['display_name']} · {e.get('type_label', '')}".rstrip(" ·"), e["id"])
        if current and self.entity.findData(current) < 0:  # vinculada a entidade na lixeira
            ent = guarded(self, lambda: self.store.get_entity(current))
            if ent:
                self.entity.addItem(f"{ent['display_name']} (na lixeira)", current)
        self.entity.set_value(current)
        self.entity.blockSignals(False)
        self._sync_open_btn()

    def _sync_open_btn(self) -> None:
        self.open_btn.setEnabled(bool(self.entity.value()))

    def refresh(self) -> None:
        self.save_now()
        rows = guarded(self, lambda: self.store.list_notes(self.search.text(), order=self.order.value())) or []
        self.table.set_rows(rows)
        self.list_empty.setVisible(not rows)
        self.list_empty.setText("Nenhuma nota encontrada." if self.search.text().strip()
                                else "Ainda não há notas neste projeto.")
        ids = [r["id"] for r in rows]
        if self.current_id in ids:
            self._select_row(ids.index(self.current_id))
        elif self.current_id is None or not ids:
            if self.current_id is not None and not self._exists(self.current_id):
                self._show(None)
        self.count = len(rows)

    def _exists(self, nid: str) -> bool:
        try:
            self.store.get_note(nid)
        except NexusError:
            return False
        return True

    def _select_row(self, i: int) -> None:
        sm = self.table.selectionModel()
        sm.blockSignals(True)
        self.table.selectRow(i)
        sm.blockSignals(False)

    def _pick(self, i: int) -> None:
        if i < 0 or i >= self.table.row_count():
            return
        nid = self.table.model().row(i)["id"]
        if nid != self.current_id:
            self.save_now()
            self._show(nid)

    def _show(self, nid: str | None) -> None:
        self._timer.stop()
        self.current_id = nid
        if nid is None:
            self.editor_stack.setCurrentWidget(self.no_note)
            return
        note = guarded(self, lambda: self.store.get_note(nid))
        if note is None:
            self.current_id = None
            self.editor_stack.setCurrentWidget(self.no_note)
            return
        self._loading = True
        self.title.setText(note["title"])
        self.body.setPlainText(note["body"])
        self._fill_entities(note["entity_id"])
        self._loading = False
        self._dirty = False
        self._meta(note)
        self.status.setText("")
        self.editor_stack.setCurrentWidget(self.editor_stack.widget(0))

    def _meta(self, note: dict[str, Any]) -> None:
        self.meta.setText(f"Criada em {fmt.absolute(note['created_at'])} · "
                          f"atualizada em {fmt.absolute(note['updated_at'])}")

    # ------------------------------------------------------------ edição
    def _changed(self, *_: Any) -> None:
        if self._loading or self.current_id is None:
            return
        self._dirty = True
        self.status.setText("Salvando…")
        self._timer.start()

    def save_now(self) -> None:
        if not self._dirty or self.current_id is None or not isValid(self):
            return
        self._timer.stop()
        nid = self.current_id
        try:
            self.store.update_note(nid, self.title.text(), self.body.toPlainText(), self.entity.value())
        except NexusError as exc:
            self.status.setText("Não salvo")
            notify(self, exc.user_message, "danger")
            return
        self._dirty = False
        self.status.setText("Salvo")
        note = guarded(self, lambda: self.store.get_note(nid))
        if note:
            self._meta(note)
            for i in range(self.table.row_count()):
                if self.table.model().row(i)["id"] == nid:
                    self.table.model().row(i).update(title=note["title"], updated_at=note["updated_at"])
                    self.table.viewport().update()

    def new_note(self, entity_id: str | None = None) -> str | None:
        self.save_now()
        nid = guarded(self, lambda: self.store.create_note("", "", entity_id))
        if nid is None:
            return None
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.current_id = nid
        self.refresh()
        self._show(nid)
        self.title.setFocus()
        return nid

    def delete_current(self) -> None:
        if self.current_id is None:
            return
        note = guarded(self, lambda: self.store.get_note(self.current_id or ""))
        if note is None:
            return
        if not confirm(self, "Excluir nota", f"Excluir a nota “{_title_of(note)}”? Esta ação não pode ser "
                       "desfeita.", danger=True):
            return
        self._dirty = False
        if guarded(self, lambda: self.store.delete_note(note["id"])) is None and self._exists(note["id"]):
            return
        self.current_id = None
        self._show(None)
        self.refresh()
        notify(self, "Nota excluída.", "success")

    def _open_linked(self) -> None:
        eid = self.entity.value()
        if eid:
            self.save_now()
            self.open_entity.emit(eid)

    def hideEvent(self, event: Any) -> None:  # noqa: N802
        self.save_now()
        super().hideEvent(event)

    def shutdown(self) -> None:
        self.save_now()
