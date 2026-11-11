"""Seleção de perfis, avatar e escolha de imagem de perfil (0.3.4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from nexus_intel.application.profiles import ProfileInfo, ProfileManager
from nexus_intel.domain.errors import NexusError
from nexus_intel.infrastructure.media.images import MAX_IMAGE_BYTES, inspect_image
from nexus_intel.ui.common import Page, label
from nexus_intel.ui.design import assets, tokens
from nexus_intel.ui.design.components import Button, ElidedLabel, on_theme, text

IMAGE_FILTER = "Imagens (*.jpg *.jpeg *.png *.webp *.gif *.bmp *.tif *.tiff);;Todos os arquivos (*)"


def initials(name: str) -> str:
    parts = [p for p in name.replace("_", " ").replace(".", " ").split() if p]
    if not parts:
        return "?"
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


class ProfileAvatar(QWidget):
    """Círculo com a imagem do perfil ou as iniciais do nome."""

    def __init__(self, size: int = 64, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._pix: QPixmap | None = None
        self._name = ""
        on_theme(self, lambda _t: self.update())

    def set_profile(self, name: str, image: Path | bytes | None) -> None:
        self._name = name
        self._pix = None
        if image is not None:
            pm = QPixmap()
            ok = pm.loadFromData(image) if isinstance(image, bytes) else pm.load(str(image))
            self._pix = pm if ok and not pm.isNull() else None
        self.update()

    def paintEvent(self, _event: Any) -> None:  # noqa: N802
        t = tokens.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addEllipse(r)
        if self._pix is not None:
            p.setClipPath(path)
            side = min(self._pix.width(), self._pix.height())
            src = QRectF((self._pix.width() - side) / 2, (self._pix.height() - side) / 2, side, side)
            p.drawPixmap(r, self._pix, src)
            return
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(assets.qcolor(t.accent_subtle))
        p.drawEllipse(r)
        f = QFont(self.font())
        f.setPixelSize(max(10, int(self.width() * 0.36)))
        f.setBold(True)
        p.setFont(f)
        p.setPen(assets.qcolor(t.accent_text))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, initials(self._name))


class AvatarPicker(QWidget):
    """Escolher, trocar ou remover a imagem do perfil (validada pelo conteúdo)."""

    changed = Signal()

    def __init__(self, name: str = "", current: Path | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.data: bytes | None = None
        self.removed = False
        self._has_current = current is not None
        self.preview = ProfileAvatar(56)
        self.preview.set_profile(name, current)
        self.pick_btn = Button("Escolher imagem…", "secondary", "image", size="sm", on_click=self.pick)
        self.clear_btn = Button("Remover", "ghost", "x", size="sm", on_click=self.clear)
        self.error = text("", "danger", wrap=True)
        self.error.hide()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.preview)
        col = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(self.pick_btn)
        row.addWidget(self.clear_btn)
        row.addStretch(1)
        col.addLayout(row)
        col.addWidget(text("Aparece na tela de seleção de perfis, antes do login.", "caption", wrap=True))
        col.addWidget(self.error)
        lay.addLayout(col, 1)
        self._sync()

    def set_name(self, name: str) -> None:
        self.preview._name = name
        self.preview.update()

    def pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Imagem do perfil", "", IMAGE_FILTER)
        if path:
            self.load_file(path)

    def load_file(self, path: str) -> bool:
        self.error.hide()
        try:
            if Path(path).stat().st_size > MAX_IMAGE_BYTES:
                raise NexusError("A imagem é grande demais (limite de 50 MB).")
            data = Path(path).read_bytes()
            inspect_image(data)
        except NexusError as exc:
            self.error.setText(exc.user_message)
            self.error.show()
            return False
        except OSError:
            self.error.setText("Não foi possível ler o arquivo.")
            self.error.show()
            return False
        from nexus_intel.infrastructure.media.images import render_png

        self.data = data
        self.removed = False
        self.preview.set_profile(self.preview._name, render_png(data, 128))
        self._sync()
        self.changed.emit()
        return True

    def clear(self) -> None:
        self.data = None
        self.removed = self._has_current
        self.preview.set_profile(self.preview._name, None)
        self._sync()
        self.changed.emit()

    def _sync(self) -> None:
        self.clear_btn.setVisible(self.data is not None or (self._has_current and not self.removed))


class ProfileTile(QFrame):
    """Cartão clicável de um perfil na tela de seleção."""

    activated = Signal(str)
    HEIGHT = 176

    def __init__(self, info: ProfileInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.info = info
        self.setProperty("card", "true")
        self.setProperty("interactive", "true")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(180, self.HEIGHT)
        self.setAccessibleName(f"Entrar como {info.display_name}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 16, 12, 12)
        lay.setSpacing(6)
        av = ProfileAvatar(72)
        av.set_profile(info.display_name, info.avatar_path)
        lay.addWidget(av, 0, Qt.AlignmentFlag.AlignHCenter)
        name = ElidedLabel(info.display_name, "h3")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(name)
        cap = text("Dados cifrados" if info.encrypted else "Sem cifragem", "caption")
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(cap)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.activated.emit(self.info.id)

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit(self.info.id)
        else:
            super().keyPressEvent(event)


class ProfilesPage(Page):
    """“Quem está usando o NEXUS INTEL?” — lista os perfis deste computador."""

    chosen = Signal(str)
    create_requested = Signal()

    def __init__(self, profiles: ProfileManager) -> None:
        super().__init__()
        self.profiles = profiles
        self.tiles: list[ProfileTile] = []
        self.layout_.addStretch(1)
        self.layout_.addWidget(label("NEXUS INTEL", "Brand"), 0, Qt.AlignmentFlag.AlignHCenter)
        title = text("Quem está usando o NEXUS INTEL?", "h1")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout_.addWidget(title)
        sub = text("Cada perfil tem projetos, notas, fotografias e preferências próprios, cifrados com a "
                   "senha do perfil.", "muted", wrap=True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout_.addWidget(sub)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(16)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.grid_host)
        self.scroll = scroll
        self.layout_.addWidget(scroll)
        self.new_btn = Button("Novo perfil", "secondary", "plus", on_click=self.create_requested.emit)
        self.layout_.addWidget(self.new_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        self.layout_.addStretch(1)

    def refresh(self) -> None:
        for t in self.tiles:
            t.setParent(None)
            t.deleteLater()
        self.tiles = []
        infos = self.profiles.list()
        cols = 4
        for i, info in enumerate(infos):
            tile = ProfileTile(info)
            tile.activated.connect(self.chosen.emit)
            self.grid.addWidget(tile, i // cols, i % cols)
            self.tiles.append(tile)
        rows = max(1, (len(infos) + cols - 1) // cols)
        # Altura exata das linhas de cartões (até duas linhas visíveis; mais que isso rola).
        self.scroll.setFixedHeight(min(rows, 2) * (ProfileTile.HEIGHT + 16) + 8)
        if self.tiles:
            self.tiles[0].setFocus()
