"""Fotografias da entidade: galeria de miniaturas, arrastar e soltar, visualizador (0.3.4).

As imagens são decifradas só na memória. Miniaturas ficam num cache do próprio
widget, descartado quando a ficha da entidade fecha ou a sessão é bloqueada.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from nexus_intel.application.project_store import ProjectStore
from nexus_intel.domain.errors import NexusError
from nexus_intel.infrastructure.media.images import MAX_IMAGE_BYTES, display_bytes, render_png
from nexus_intel.ui import format as fmt
from nexus_intel.ui.common import confirm
from nexus_intel.ui.design.components import Button, EmptyState, IconButton, notify, safe_tooltip, text

THUMB = 128
FILE_FILTER = ("Imagens (*.jpg *.jpeg *.png *.webp *.gif *.bmp *.tif *.tiff);;"
               "Todos os arquivos (*)")


def _read_file(path: str) -> bytes:
    if os.path.getsize(path) > MAX_IMAGE_BYTES:
        raise NexusError(f"“{Path(path).name}” passa do limite de 50 MB por imagem.")
    with open(path, "rb") as fh:
        return fh.read()


def _pixmap(data: bytes) -> QPixmap:
    pm = QPixmap()
    pm.loadFromData(data)
    return pm


class PhotoGallery(QWidget):
    """Seção “Fotografias” da ficha da entidade."""

    changed = Signal()

    def __init__(self, store: ProjectStore, entity_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.entity_id = entity_id
        self.rows: list[dict[str, Any]] = []
        self._thumbs: dict[str, QIcon] = {}
        self.setAcceptDrops(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(10)
        head = QHBoxLayout()
        self.summary = text("", "muted")
        head.addWidget(self.summary, 1)
        self.add_btn = Button("Adicionar fotografias", "primary", "plus", on_click=self.pick_files,
                              tooltip="Selecionar imagens do computador (ou arraste para esta área)")
        head.addWidget(self.add_btn)
        lay.addLayout(head)

        self.grid = QListWidget()
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setIconSize(QSize(THUMB, THUMB))
        self.grid.setGridSize(QSize(THUMB + 28, THUMB + 44))
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Static)
        self.grid.setWrapping(True)
        self.grid.setUniformItemSizes(True)
        self.grid.setWordWrap(False)
        self.grid.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.grid.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._menu)
        self.grid.itemActivated.connect(lambda it: self.open_viewer(self.grid.row(it)))
        self.grid.setAcceptDrops(False)

        self.empty = EmptyState("image", "Nenhuma fotografia",
                                "Arraste imagens para cá ou use o botão. Formatos: JPG, PNG, WEBP, GIF, BMP e "
                                "TIFF. As imagens ficam cifradas dentro do projeto.",
                                "Adicionar fotografias", self.pick_files)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.grid)
        self.stack.addWidget(self.empty)
        lay.addWidget(self.stack, 1)

        actions = QHBoxLayout()
        self.open_btn = Button("Ampliar", "secondary", "maximize-2", size="sm",
                               on_click=lambda: self.open_viewer(self.grid.currentRow()))
        self.replace_btn = Button("Substituir…", "secondary", "refresh-cw", size="sm",
                                  on_click=lambda: self.replace(self.grid.currentRow()))
        self.remove_btn = Button("Remover", "ghost", "trash-2", size="sm", tone="danger",
                                 on_click=lambda: self.remove(self.grid.currentRow()))
        actions.addWidget(self.open_btn)
        actions.addWidget(self.replace_btn)
        actions.addWidget(self.remove_btn)
        actions.addStretch(1)
        self.hint = text("Arraste e solte imagens nesta área", "caption")
        actions.addWidget(self.hint)
        lay.addLayout(actions)
        self.grid.currentRowChanged.connect(lambda _r: self._sync_buttons())
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.grid, activated=lambda: self.remove(self.grid.currentRow()))
        self.refresh()

    # ------------------------------------------------------------ dados
    def refresh(self) -> None:
        if not isValid(self):
            return
        try:
            self.rows = self.store.list_photos(self.entity_id)
        except NexusError as exc:
            notify(self, exc.user_message, "danger")
            self.rows = []
        current = self.grid.currentRow()
        self.grid.clear()
        alive = {r["id"] for r in self.rows}
        self._thumbs = {k: v for k, v in self._thumbs.items() if k in alive}
        for r in self.rows:
            item = QListWidgetItem(self._thumb(r), r["original_name"] or "imagem")
            item.setToolTip(safe_tooltip(f"{r['original_name']}\n{r['width']}×{r['height']} · {fmt.number(r['size'] // 1024)} KB"))
            item.setSizeHint(QSize(THUMB + 24, THUMB + 40))
            self.grid.addItem(item)
        n = len(self.rows)
        self.summary.setText(f"{n} fotografia{'s' if n != 1 else ''} desta entidade" if n else
                             "Fotografias desta entidade")
        self.stack.setCurrentWidget(self.grid if n else self.empty)
        if n:
            self.grid.setCurrentRow(min(max(current, 0), n - 1))
        self.hint.setVisible(bool(n))
        self._sync_buttons()

    def _thumb(self, r: dict[str, Any]) -> QIcon:
        icon = self._thumbs.get(r["id"])
        if icon is None:
            try:
                icon = QIcon(_pixmap(render_png(self.store.photo_bytes(r["id"]), THUMB * 2)))
            except NexusError:
                from nexus_intel.ui.design import assets, tokens

                icon = assets.icon("triangle-alert", tokens.current().warning, 48)
            self._thumbs[r["id"]] = icon
        return icon

    def _sync_buttons(self) -> None:
        has = 0 <= self.grid.currentRow() < len(self.rows)
        for b in (self.open_btn, self.replace_btn, self.remove_btn):
            b.setVisible(bool(self.rows))
            b.setEnabled(has)

    # ------------------------------------------------------------ ações
    def add_files(self, paths: list[str]) -> int:
        added, errors = 0, []
        for path in paths:
            name = Path(path).name
            try:
                self.store.add_photo(self.entity_id, _read_file(path), name)
                added += 1
            except NexusError as exc:
                errors.append(f"{name}: {exc.user_message}")
            except OSError:
                errors.append(f"{name}: não foi possível ler o arquivo.")
        self.refresh()
        if added:
            self.changed.emit()
            notify(self, f"{added} fotografia{'s' if added > 1 else ''} adicionada{'s' if added > 1 else ''}.",
                   "success")
        if errors:
            notify(self, "Não adicionadas — " + " · ".join(errors[:3]) + (" …" if len(errors) > 3 else ""),
                   "danger")
        return added

    def pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Adicionar fotografias", "", FILE_FILTER)
        if paths:
            self.add_files(paths)

    def replace(self, row: int) -> None:
        if not 0 <= row < len(self.rows):
            return
        path, _ = QFileDialog.getOpenFileName(self, "Substituir fotografia", "", FILE_FILTER)
        if path:
            self.replace_with(row, path)

    def replace_with(self, row: int, path: str) -> bool:
        try:
            self.store.replace_photo(self.rows[row]["id"], _read_file(path), Path(path).name)
        except NexusError as exc:
            notify(self, exc.user_message, "danger")
            return False
        except OSError:
            notify(self, "Não foi possível ler o arquivo.", "danger")
            return False
        self._thumbs.pop(self.rows[row]["id"], None)
        self.refresh()
        self.changed.emit()
        notify(self, "Fotografia substituída.", "success")
        return True

    def remove(self, row: int) -> None:
        if not 0 <= row < len(self.rows):
            return
        r = self.rows[row]
        if not confirm(self, "Remover fotografia",
                       f"Remover “{r['original_name'] or 'imagem'}” desta entidade?\n\nSe a mesma imagem estiver "
                       "em outra entidade, ela continua lá.", danger=True):
            return
        try:
            self.store.remove_photo(r["id"])
        except NexusError as exc:
            notify(self, exc.user_message, "danger")
            return
        self.refresh()
        self.changed.emit()
        notify(self, "Fotografia removida.", "success")

    def open_viewer(self, row: int) -> None:
        if 0 <= row < len(self.rows):
            PhotoViewer(self.store, self.rows, row, self).exec()

    def _menu(self, pos: Any) -> None:
        item = self.grid.itemAt(pos)
        if item is None:
            return
        row = self.grid.row(item)
        m = QMenu(self)
        m.addAction("Ampliar", lambda: self.open_viewer(row))
        m.addAction("Substituir…", lambda: self.replace(row))
        m.addSeparator()
        m.addAction("Remover desta entidade…", lambda: self.remove(row))
        m.exec(self.grid.viewport().mapToGlobal(pos))

    # ------------------------------------------------- arrastar e soltar
    @staticmethod
    def _local_paths(event: Any) -> list[str]:
        md = event.mimeData()
        if not md.hasUrls():
            return []
        return [u.toLocalFile() for u in md.urls() if u.isLocalFile() and os.path.isfile(u.toLocalFile())]

    def dragEnterEvent(self, event: Any) -> None:  # noqa: N802
        if self._local_paths(event):
            event.acceptProposedAction()

    def dragMoveEvent(self, event: Any) -> None:  # noqa: N802
        if self._local_paths(event):
            event.acceptProposedAction()

    def dropEvent(self, event: Any) -> None:  # noqa: N802
        paths = self._local_paths(event)
        if paths:
            event.acceptProposedAction()
            self.add_files(paths)

    def clear_cache(self) -> None:
        self._thumbs.clear()
        self.grid.clear()


class PhotoViewer(QDialog):
    """Visualização ampliada com navegação (setas do teclado ou botões)."""

    def __init__(self, store: ProjectStore, rows: list[dict[str, Any]], index: int,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.rows = rows
        self.index = index
        self._pix = QPixmap()
        self.setWindowTitle("Fotografia")
        self.resize(960, 700)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        head = QHBoxLayout()
        self.title = text("", "h3")
        head.addWidget(self.title, 1)
        head.addWidget(IconButton("x", "Fechar", self.reject))
        lay.addLayout(head)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.image.setMinimumSize(200, 150)
        lay.addWidget(self.image, 1)
        foot = QHBoxLayout()
        self.prev_btn = Button("Anterior", "secondary", "chevron-left", on_click=lambda: self.go(-1))
        self.next_btn = Button("Próxima", "secondary", "chevron-right", on_click=lambda: self.go(1))
        self.info = text("", "caption", wrap=True)
        foot.addWidget(self.prev_btn)
        foot.addWidget(self.info, 1)
        foot.addWidget(self.next_btn)
        lay.addLayout(foot)
        self.show_index(index)

    def show_index(self, i: int) -> None:
        self.index = i % len(self.rows)
        r = self.rows[self.index]
        try:
            self._pix = _pixmap(display_bytes(self.store.photo_bytes(r["id"]), r["mime"]))
        except NexusError as exc:
            self._pix = QPixmap()
            self.image.setText(exc.user_message)
        self.title.setText(r["original_name"] or "Imagem")
        exif = "com metadados EXIF" + (" (inclui localização GPS)" if r["has_gps"] else "") if r["has_exif"] \
            else "sem metadados EXIF"
        self.info.setText(f"{self.index + 1} de {len(self.rows)} · Entidade: {r['entity_name']} · "
                          f"{r['width']}×{r['height']} · {fmt.number(r['size'] // 1024)} KB · {exif} · "
                          f"adicionada em {fmt.absolute(r['created_at'])}")
        multi = len(self.rows) > 1
        self.prev_btn.setEnabled(multi)
        self.next_btn.setEnabled(multi)
        self._fit()

    def go(self, step: int) -> None:
        self.show_index(self.index + step)

    def _fit(self) -> None:
        if not self._pix.isNull():
            self.image.setPixmap(self._pix.scaled(self.image.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit()

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.go(1)
        elif event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.go(-1)
        else:
            super().keyPressEvent(event)
