"""Tabela virtualizada (QTableView + modelo) para listas com dezenas de milhares de linhas.

Só as linhas visíveis são desenhadas. Com `fetcher`, as linhas são buscadas no
banco em páginas conforme a rolagem (fetchMore), sem carregar tudo de uma vez.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView, QWidget

from nexus_intel.ui import format as fmt
from nexus_intel.ui.design import assets, tokens
from nexus_intel.ui.design.components import STATUS_LABELS, on_theme

Row = dict[str, Any]
Fetcher = Callable[[int, int], list[Row]]

Index = QModelIndex | QPersistentModelIndex


@dataclass
class Column:
    key: str
    title: str
    kind: str = "text"  # text, mono, number, reltime, datetime, entity, status, muted, link
    width: int | None = None
    stretch: bool = False
    getter: Callable[[Row], Any] | None = None

    def value(self, row: Row) -> Any:
        return self.getter(row) if self.getter else row.get(self.key)


class RecordModel(QAbstractTableModel):
    def __init__(self, columns: Sequence[Column], page_size: int = 200, parent: Any = None) -> None:
        super().__init__(parent)
        self.columns = list(columns)
        self.rows: list[Row] = []
        self.page_size = page_size
        self._fetcher: Fetcher | None = None
        self._exhausted = True

    # --- dados
    def set_rows(self, rows: Sequence[Row], fetcher: Fetcher | None = None) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self._fetcher = fetcher
        self._exhausted = fetcher is None or len(self.rows) < self.page_size
        self.endResetModel()

    def load(self, fetcher: Fetcher) -> None:
        """Começa a paginar a partir do zero."""
        self.set_rows(fetcher(0, self.page_size), fetcher)

    def row(self, i: int) -> Row:
        return self.rows[i]

    def canFetchMore(self, parent: Index = QModelIndex()) -> bool:  # noqa: N802, B008
        return not parent.isValid() and not self._exhausted

    def fetchMore(self, parent: Index = QModelIndex()) -> None:  # noqa: N802, B008
        if self._fetcher is None or self._exhausted:
            return
        more = self._fetcher(len(self.rows), self.page_size)
        if len(more) < self.page_size:
            self._exhausted = True
        if more:
            start = len(self.rows)
            self.beginInsertRows(QModelIndex(), start, start + len(more) - 1)
            self.rows.extend(more)
            self.endInsertRows()

    # --- API do modelo
    def rowCount(self, parent: Index = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: Index = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.columns[section].title.upper()
        return None

    def data(self, index: Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        col = self.columns[index.column()]
        value = col.value(row)
        t = tokens.current()
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(col, value)
        if role == Qt.ItemDataRole.ToolTipRole:
            if col.kind == "link" and value:
                return f"Clique para abrir no navegador: {value}"
            if col.kind in ("reltime", "datetime"):
                return fmt.absolute(value)
            shown = self._display(col, value)
            return shown if shown and len(shown) > 24 else None
        if role == Qt.ItemDataRole.ForegroundRole:
            if col.kind == "status":
                return assets.qcolor(t.status_color(str(value)))
            if col.kind in ("muted", "reltime", "datetime"):
                return assets.qcolor(t.text_muted)
            if col.kind == "mono":
                return assets.qcolor(t.text_secondary)
            if col.kind == "link":
                return assets.qcolor(t.accent_text)
            return None
        if role == Qt.ItemDataRole.DecorationRole:
            if col.kind == "entity":
                return assets.pixmap(assets.TYPE_ICONS.get(row.get("type_key") or "other", "circle"),
                                     t.type_color(row.get("type_key")), 16)
            if col.kind == "status":
                return assets.pixmap(assets.STATUS_ICONS.get(str(value), "circle"), t.status_color(str(value)), 14)
            return None
        if role == Qt.ItemDataRole.FontRole and col.kind == "link" and value:
            f = QFont(assets.font_family("ui"))
            f.setPixelSize(t.font_px("sm"))
            f.setUnderline(True)
            return f
        if role == Qt.ItemDataRole.FontRole and col.kind == "mono":
            f = QFont(assets.font_family("mono"))
            f.setPixelSize(t.font_px("xs"))
            return f
        if role == Qt.ItemDataRole.TextAlignmentRole and col.kind == "number":
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.UserRole:
            return row
        if role == Qt.ItemDataRole.AccessibleTextRole:
            return f"{col.title}: {self._display(col, value)}"
        return None

    @staticmethod
    def _display(col: Column, value: Any) -> str:
        if value is None or value == "":
            return "—" if col.kind in ("number", "reltime", "datetime") else ""
        if col.kind == "reltime":
            return fmt.relative(str(value))
        if col.kind == "datetime":
            return fmt.absolute(str(value))
        if col.kind == "number" and isinstance(value, int | float):
            return fmt.number(value)
        if col.kind == "status":
            return STATUS_LABELS.get(str(value), str(value))
        return str(value)


class DataTable(QTableView):
    """Tabela pronta: linhas de altura fixa, cabeçalho em caixa alta, reticências e dicas."""

    row_activated = Signal(dict)
    link_clicked = Signal(str)  # clique numa célula de coluna do tipo "link"

    def __init__(self, columns: Sequence[Column], page_size: int = 200, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model_ = RecordModel(columns, page_size, self)
        self.setModel(self.model_)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setAlternatingRowColors(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().hide()
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        hh = self.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hh.setStretchLastSection(False)
        for i, c in enumerate(columns):
            if c.stretch:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            elif c.width:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                self.setColumnWidth(i, c.width)
            else:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self.doubleClicked.connect(self._double_clicked)
        self.clicked.connect(self._clicked)
        self.setMouseTracking(True)
        self._sync(tokens.current())
        on_theme(self, self._sync)

    def _sync(self, t: tokens.Tokens) -> None:
        self.verticalHeader().setDefaultSectionSize(max(26, round(34 * t.density)))
        self.setIconSize(QSize(16, 16))
        self.viewport().update()

    def _link_at(self, idx: QModelIndex) -> str | None:
        if not idx.isValid() or self.model_.columns[idx.column()].kind != "link":
            return None
        value = self.model_.columns[idx.column()].value(self.model_.row(idx.row()))
        return str(value) if value else None

    def _clicked(self, idx: QModelIndex) -> None:
        url = self._link_at(idx)
        if url:
            self.link_clicked.emit(url)

    def _double_clicked(self, idx: QModelIndex) -> None:
        if self._link_at(idx):
            return  # o clique simples já abriu o link; não abre a ficha junto
        self.row_activated.emit(self.model_.row(idx.row()))

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
        over_link = self._link_at(self.indexAt(event.position().toPoint())) is not None
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if over_link else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.currentIndex().isValid():
            self.row_activated.emit(self.model_.row(self.currentIndex().row()))
            return
        super().keyPressEvent(event)

    # --- atalhos
    def set_rows(self, rows: Sequence[Row]) -> None:
        self.model_.set_rows(rows)

    def load(self, fetcher: Fetcher) -> None:
        self.model_.load(fetcher)

    def selected_rows(self) -> list[Row]:
        rows = sorted({i.row() for i in self.selectionModel().selectedRows()})
        return [self.model_.row(r) for r in rows]

    def current_row(self) -> Row | None:
        idx = self.currentIndex()
        return self.model_.row(idx.row()) if idx.isValid() else None

    def row_count(self) -> int:
        return self.model_.rowCount()
