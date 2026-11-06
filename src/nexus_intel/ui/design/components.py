"""Componentes base do design system. Todas as cores vêm de `tokens.current()`.

Cada componente que pinta a si mesmo escuta `theme_manager().changed` para se
atualizar quando o usuário troca tema, destaque, escala ou densidade.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from nexus_intel.ui.design import assets, tokens
from nexus_intel.ui.design.color import ensure_contrast
from nexus_intel.ui.design.manager import theme_manager
from nexus_intel.ui.design.tokens import Tokens

ColorFn = Callable[[Tokens], str]


def _on_theme(widget: QObject, slot: Callable[[Tokens], Any]) -> None:
    """Chama `slot` a cada troca de tema enquanto `widget` existir."""

    def guarded(t: Tokens) -> None:
        try:
            slot(t)
        except RuntimeError:  # objeto C++ já destruído
            _safe_disconnect(guarded)

    theme_manager().changed.connect(guarded)
    widget.destroyed.connect(lambda *_: _safe_disconnect(guarded))


on_theme = _on_theme


def _safe_disconnect(slot: Callable[..., Any]) -> None:
    try:
        theme_manager().changed.disconnect(slot)
    except (RuntimeError, TypeError):
        pass


def repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def shadow(widget: QWidget, level: str = "md") -> None:
    blur, dy, alpha = tokens.SHADOW[level]
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    eff.setColor(assets.qcolor(tokens.current().overlay, alpha))
    widget.setGraphicsEffect(eff)


# ====================================================================== botões
class Button(QPushButton):
    """Botão com variantes: primary, secondary, ghost, danger, nav."""

    def __init__(self, text: str = "", variant: str = "secondary", icon: str | None = None,
                 on_click: Callable[[], Any] | None = None, tooltip: str = "", shortcut: str | None = None,
                 size: str = "md", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._icon = icon
        self.setProperty("variant", variant)
        if size != "md":
            self.setProperty("size", size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)  # anel de foco só ao navegar pelo teclado
        tip = tooltip or ""
        if shortcut:
            tip = f"{tip}  ({shortcut})".strip() if tip else shortcut
        if tip:
            self.setToolTip(tip)
        if on_click is not None:
            self.clicked.connect(lambda *_: on_click())
        self._apply_icon(tokens.current())
        _on_theme(self, self._apply_icon)

    def set_variant(self, variant: str) -> None:
        self.setProperty("variant", variant)
        self._apply_icon(tokens.current())
        repolish(self)

    def set_icon(self, name: str | None) -> None:
        self._icon = name
        self._apply_icon(tokens.current())

    def _apply_icon(self, t: Tokens) -> None:
        if not self._icon:
            return
        variant = self.property("variant")
        color = {"primary": t.accent_fg, "danger": t.danger}.get(variant, t.text_secondary)
        active = {"primary": t.accent_fg, "danger": t.danger}.get(variant, t.text_primary)
        self.setIcon(assets.icon(self._icon, color, 16, active))
        self.setIconSize(QSize(16, 16))


class IconButton(QToolButton):
    """Botão só com ícone. A dica (tooltip) é obrigatória: é também o nome acessível."""

    def __init__(self, icon: str, tooltip: str, on_click: Callable[[], Any] | None = None,
                 variant: str = "ghost", size: int = 16, checkable: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon, self._size = icon, size
        self.setProperty("variant", variant)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setIconSize(QSize(size, size))
        if on_click is not None:
            self.clicked.connect(lambda *_: on_click())
        self._apply(tokens.current())
        _on_theme(self, self._apply)

    def set_icon(self, name: str) -> None:
        self._icon = name
        self._apply(tokens.current())

    def _apply(self, t: Tokens) -> None:
        self.setIcon(assets.icon(self._icon, t.text_secondary, self._size, t.text_primary))


# ====================================================================== campos
class Input(QLineEdit):
    def __init__(self, placeholder: str = "", icon: str | None = None, text: str = "",
                 clearable: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(clearable)
        self._icon = icon
        self._action = None
        if icon:
            self._action = self.addAction(assets.icon(icon, tokens.current().text_muted),
                                          QLineEdit.ActionPosition.LeadingPosition)
            _on_theme(self, self._retint)

    def _retint(self, t: Tokens) -> None:
        if self._action is not None and self._icon:
            self._action.setIcon(assets.icon(self._icon, t.text_muted))


class Select(QComboBox):
    def __init__(self, items: Sequence[tuple[str, Any]] = (), current: Any = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        for text, data in items:
            self.addItem(text, data)
        if current is not None:
            self.set_value(current)

    def value(self) -> Any:
        return self.currentData()

    def set_value(self, data: Any) -> None:
        idx = self.findData(data)
        if idx >= 0:
            self.setCurrentIndex(idx)


# ====================================================================== texto
class ElidedLabel(QLabel):
    """Rótulo de uma linha que corta com reticências e mostra o texto inteiro na dica."""

    def __init__(self, text: str = "", role: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        if role:
            self.setProperty("role", role)
        self._full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(24)

    def setText(self, text: str) -> None:  # noqa: N802 - API do Qt
        self._full = text
        super().setText(text)
        self._update_tip()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_tip()

    def _update_tip(self) -> None:
        elided = self.fontMetrics().horizontalAdvance(self._full) > self.contentsRect().width()
        self.setToolTip(self._full if elided else "")

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(24, super().minimumSizeHint().height())

    def paintEvent(self, event: Any) -> None:  # noqa: N802
        p = QPainter(self)
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, rect.width())
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        p.drawText(rect, int(self.alignment() | Qt.AlignmentFlag.AlignVCenter), text)


def text(content: str, role: str | None = None, wrap: bool = False, selectable: bool = False) -> QLabel:
    lb = QLabel(content)
    if role:
        lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    if selectable:
        lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lb


# ====================================================================== chips
class Chip(QWidget):
    """Etiqueta compacta com ícone opcional. A cor vem de uma função de tokens."""

    def __init__(self, label: str, color: ColorFn, icon: str | None = None, tooltip: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label, self._color, self._icon = label, color, icon
        if tooltip:
            self.setToolTip(tooltip)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(label)
        _on_theme(self, lambda _t: (self.updateGeometry(), self.update()))

    def set_text(self, label: str) -> None:
        self._label = label
        self.setAccessibleName(label)
        self.updateGeometry()
        self.update()

    def _font(self) -> QFont:
        f = QFont(self.font())
        f.setPixelSize(tokens.current().font_px("xs"))
        f.setWeight(QFont.Weight.Medium)
        return f

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(self._font())
        w = fm.horizontalAdvance(self._label) + 16 + (16 if self._icon else 0)
        return QSize(w, fm.height() + 8)

    def paintEvent(self, event: Any) -> None:  # noqa: N802
        t = tokens.current()
        base = self._color(t)
        bg = t.subtle(base)
        fg = ensure_contrast(base, bg, 4.5)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = r.height() / 2 if t.rounded else 3
        p.setPen(QPen(assets.qcolor(fg, 0.35), 1))
        p.setBrush(assets.qcolor(bg))
        p.drawRoundedRect(r, radius, radius)
        x = 8
        if self._icon:
            px = assets.pixmap(self._icon, fg, 12)
            p.drawPixmap(QPoint(x, (self.height() - 12) // 2), px)
            x += 16
        p.setPen(assets.qcolor(fg))
        p.setFont(self._font())
        p.drawText(QRect(x, 0, self.width() - x - 6, self.height()),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self._label)


TONES: dict[str, ColorFn] = {
    "neutral": lambda t: t.text_secondary,
    "accent": lambda t: t.accent_text,
    "success": lambda t: t.success,
    "warning": lambda t: t.warning,
    "danger": lambda t: t.danger,
    "info": lambda t: t.info,
}


def Badge(label: str, tone: str = "neutral", icon: str | None = None, tooltip: str = "") -> Chip:  # noqa: N802
    return Chip(label, TONES.get(tone, TONES["neutral"]), icon, tooltip)


STATUS_LABELS = {
    "verified": "Verificado", "reported": "Relatado", "unverified": "Não verificado",
    "hypothesis": "Hipótese", "conflicting": "Conflitante", "refuted": "Refutado",
}


def StatusBadge(status: str, count: int | None = None) -> Chip:  # noqa: N802
    label = STATUS_LABELS.get(status, status)
    shown = f"{label}: {count}" if count is not None else label
    return Chip(shown, lambda t: t.status_color(status), assets.STATUS_ICONS.get(status),
                f"Status epistêmico: {label}")


def EntityTypeChip(type_key: str, label: str) -> Chip:  # noqa: N802
    return Chip(label, lambda t: t.type_color(type_key), assets.TYPE_ICONS.get(type_key, "circle"))


class EntityAvatar(QWidget):
    """Círculo com o ícone do tipo da entidade."""

    def __init__(self, type_key: str, size: int = 28, tooltip: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.type_key = type_key
        self.setFixedSize(size, size)
        if tooltip:
            self.setToolTip(tooltip)
        _on_theme(self, lambda _t: self.update())

    def set_type(self, type_key: str) -> None:
        self.type_key = type_key
        self.update()

    def paintEvent(self, event: Any) -> None:  # noqa: N802
        paint_avatar(QPainter(self), QRectF(self.rect()), self.type_key)


def paint_avatar(p: QPainter, rect: QRectF, type_key: str, ring: str | None = None) -> None:
    t = tokens.current()
    color = t.type_color(type_key)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(assets.qcolor(ring), 2) if ring else Qt.PenStyle.NoPen)
    p.setBrush(assets.qcolor(t.subtle(color, 0.28 if t.dark else 0.18)))
    p.drawEllipse(rect.adjusted(1, 1, -1, -1))
    size = max(10, int(rect.width() * 0.5))
    px = assets.pixmap(assets.TYPE_ICONS.get(type_key, "circle"), color, size)
    p.drawPixmap(int(rect.center().x() - size / 2), int(rect.center().y() - size / 2), px)


class Kbd(QWidget):
    """Atalho de teclado: “Ctrl+K” vira as teclas Ctrl e K desenhadas."""

    def __init__(self, keys: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.keys = [k for k in keys.replace(" ", "").split("+") if k]
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setToolTip(keys)
        _on_theme(self, lambda _t: (self.updateGeometry(), self.update()))

    def _font(self) -> QFont:
        f = QFont(assets.font_family("mono"))
        f.setPixelSize(max(10, tokens.current().font_px("xs") - 1))
        return f

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(self._font())
        w = sum(max(18, fm.horizontalAdvance(k) + 10) for k in self.keys) + 3 * (len(self.keys) - 1)
        return QSize(w, fm.height() + 6)

    def paintEvent(self, event: Any) -> None:  # noqa: N802
        t = tokens.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(self._font())
        fm = p.fontMetrics()
        x = 0
        for k in self.keys:
            w = max(18, fm.horizontalAdvance(k) + 10)
            r = QRectF(x + 0.5, 0.5, w - 1, self.height() - 1)
            p.setPen(QPen(assets.qcolor(t.border_strong), 1))
            p.setBrush(assets.qcolor(t.surface_elevated))
            p.drawRoundedRect(r, 4, 4)
            p.setPen(assets.qcolor(t.text_secondary))
            p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), k)
            x += w + 3


# ====================================================================== estrutura
class Card(QFrame):
    """Cartão com cabeçalho opcional (título, subtítulo, ações) e corpo em `self.body`."""

    def __init__(self, title: str | None = None, subtitle: str | None = None,
                 actions: Sequence[QWidget] = (), icon: str | None = None, elevated: bool = False,
                 padding: str = "lg", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", "elevated" if elevated else "true")
        t = tokens.current()
        outer = QVBoxLayout(self)
        pad = t.space(padding)
        outer.setContentsMargins(pad, pad - 2, pad, pad)
        outer.setSpacing(t.space("md"))
        if title or actions:
            head = QHBoxLayout()
            head.setSpacing(t.space("sm"))
            if icon:
                ic = QLabel()
                ic.setPixmap(assets.pixmap(icon, t.text_muted, 16))
                head.addWidget(ic)
            col = QVBoxLayout()
            col.setSpacing(2)
            if title:
                self.title = ElidedLabel(title, "h3")
                col.addWidget(self.title)
            if subtitle:
                col.addWidget(text(subtitle, "caption", wrap=True))
            head.addLayout(col, 1)
            for a in actions:
                head.addWidget(a)
            outer.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(t.space("sm"))
        outer.addLayout(self.body, 1)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.body.addWidget(widget, stretch)
        return widget


class Divider(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("divider", "true")


class SectionHeader(QWidget):
    def __init__(self, title: str, subtitle: str | None = None, actions: Sequence[QWidget] = (),
                 role: str = "h1", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(tokens.current().space("sm"))
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = ElidedLabel(title, role)
        if title:
            col.addWidget(self.title)
        if subtitle:
            self.subtitle = text(subtitle, "muted", wrap=True)
            col.addWidget(self.subtitle)
        lay.addLayout(col, 1)
        for a in actions:
            lay.addWidget(a, 0, Qt.AlignmentFlag.AlignVCenter)


class EmptyState(QWidget):
    """Estado vazio amigável com ícone, título, explicação e ação."""

    def __init__(self, icon: str, title: str, message: str = "", action: str | None = None,
                 on_action: Callable[[], Any] | None = None, secondary: str | None = None,
                 on_secondary: Callable[[], Any] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon = icon
        t = tokens.current()
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(t.space("md"))
        self.badge = QLabel()
        self.badge.setFixedSize(56, 56)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignHCenter)
        title_lb = text(title, "h2")
        title_lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title_lb)
        if message:
            msg = text(message, "muted", wrap=True)
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setMaximumWidth(440)
            lay.addWidget(msg, 0, Qt.AlignmentFlag.AlignHCenter)
        if action or secondary:
            row = QHBoxLayout()
            row.addStretch(1)
            if secondary:
                row.addWidget(Button(secondary, "secondary", on_click=on_secondary))
            if action:
                row.addWidget(Button(action, "primary", on_click=on_action))
            row.addStretch(1)
            lay.addLayout(row)
        self._paint_badge(t)
        _on_theme(self, self._paint_badge)

    def _paint_badge(self, t: Tokens) -> None:
        self.badge.setPixmap(assets.pixmap(self._icon, t.accent_text, 26))
        self.badge.setStyleSheet(f"background: {t.accent_subtle}; border-radius: 28px;")


# ====================================================================== carregamento
class Skeleton(QWidget):
    """Placeholder animado de carregamento. Fica estático se o usuário reduzir o movimento."""

    def __init__(self, lines: int = 3, widths: Sequence[float] = (1.0, 0.86, 0.62), line_height: int = 12,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.lines, self.widths, self.line_height = lines, list(widths), line_height
        self.phase = 0.0
        self.anim = QVariantAnimation(self)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setDuration(1200)
        self.anim.setLoopCount(-1)
        self.anim.valueChanged.connect(self._tick)
        self.setMinimumHeight(lines * (line_height + 10))
        _on_theme(self, lambda _t: self._sync())
        self._sync()

    def _sync(self) -> None:
        if tokens.current().animate and self.isVisible():
            self.anim.start()
        else:
            self.anim.stop()
        self.update()

    def showEvent(self, event: Any) -> None:  # noqa: N802
        super().showEvent(event)
        self._sync()

    def hideEvent(self, event: Any) -> None:  # noqa: N802
        self.anim.stop()
        super().hideEvent(event)

    def _tick(self, v: Any) -> None:
        self.phase = float(v)
        self.update()

    def paintEvent(self, event: Any) -> None:  # noqa: N802
        t = tokens.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        base, shine = assets.qcolor(t.surface_hover), assets.qcolor(t.surface_active)
        for i in range(self.lines):
            w = self.width() * self.widths[i % len(self.widths)]
            r = QRectF(0, i * (self.line_height + 10), w, self.line_height)
            grad = QLinearGradient(r.topLeft(), r.topRight())
            c = self.phase
            grad.setColorAt(0, base)
            grad.setColorAt(max(0.0, min(1.0, c)), shine if t.animate else base)
            grad.setColorAt(1, base)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawRoundedRect(r, 4, 4)


# ====================================================================== gráficos simples
@dataclass
class BarRow:
    key: str
    label: str
    value: float
    color: ColorFn
    icon: str | None = None


class BarList(QWidget):
    """Barras horizontais legíveis (rótulo, barra, valor). Não é selecionável;
    clique em uma linha emite `activated(key)`."""

    activated = Signal(str)

    def __init__(self, rows: Sequence[BarRow] = (), empty_text: str = "Sem dados ainda.",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: list[BarRow] = list(rows)
        self.empty_text = empty_text
        self._hover = -1
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        _on_theme(self, lambda _t: (self.updateGeometry(), self.update()))

    def set_rows(self, rows: Sequence[BarRow]) -> None:
        self.rows = list(rows)
        self.updateGeometry()
        self.update()

    def _row_h(self) -> int:
        return max(26, round(30 * tokens.current().density))

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(280, max(1, len(self.rows)) * self._row_h() + 4)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(160, self.sizeHint().height())

    def _row_at(self, y: float) -> int:
        i = int(y // self._row_h())
        return i if 0 <= i < len(self.rows) else -1

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
        i = self._row_at(event.position().y())
        if i != self._hover:
            self._hover = i
            if i >= 0:
                r = self.rows[i]
                total = sum(x.value for x in self.rows) or 1
                self.setToolTip(f"{r.label}: {r.value:g} ({round(100 * r.value / total)}%)")
            self.setCursor(Qt.CursorShape.PointingHandCursor if i >= 0 else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, event: Any) -> None:  # noqa: N802
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        i = self._row_at(event.position().y())
        if i >= 0:
            self.activated.emit(self.rows[i].key)

    def paintEvent(self, event: Any) -> None:  # noqa: N802
        t = tokens.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.rows:
            p.setPen(assets.qcolor(t.text_muted))
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), self.empty_text)
            return
        h = self._row_h()
        fm = p.fontMetrics()
        label_w = min(int(self.width() * 0.38), max(fm.horizontalAdvance(r.label) for r in self.rows) + 26)
        value_w = max(fm.horizontalAdvance(f"{r.value:g}") for r in self.rows) + 8
        top = max(r.value for r in self.rows) or 1
        bar_x = label_w + 8
        bar_w = max(10, self.width() - bar_x - value_w - 8)
        for i, r in enumerate(self.rows):
            y = i * h
            if i == self._hover:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(assets.qcolor(t.surface_hover))
                p.drawRoundedRect(QRectF(0, y + 1, self.width(), h - 2), 4, 4)
            color = r.color(t)
            x = 4
            if r.icon:
                p.drawPixmap(QPoint(x, y + (h - 14) // 2), assets.pixmap(r.icon, color, 14))
                x += 20
            p.setPen(assets.qcolor(t.text_secondary))
            p.drawText(QRect(x, y, label_w - x, h), int(Qt.AlignmentFlag.AlignVCenter),
                       fm.elidedText(r.label, Qt.TextElideMode.ElideRight, label_w - x))
            track = QRectF(bar_x, y + h / 2 - 4, bar_w, 8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(assets.qcolor(t.surface_sunken if not t.high_contrast else t.surface_elevated))
            p.drawRoundedRect(track, 4, 4)
            fill = QRectF(track.x(), track.y(), max(6.0, track.width() * r.value / top), track.height())
            p.setBrush(assets.qcolor(color))
            p.drawRoundedRect(fill, 4, 4)
            p.setPen(assets.qcolor(t.text_primary))
            p.drawText(QRect(int(bar_x + bar_w + 8), y, value_w, h),
                       int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), f"{r.value:g}")


# ====================================================================== avisos (toasts)
class Toast(QFrame):
    closed = Signal()

    def __init__(self, message: str, tone: str, action: tuple[str, Callable[[], Any]] | None,
                 parent: QWidget) -> None:
        super().__init__(parent)
        t = tokens.current()
        self.setProperty("card", "elevated")
        self.setMinimumWidth(300)
        self.setMaximumWidth(420)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 8, 10)
        lay.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(assets.pixmap(assets.TONE_ICONS.get(tone, "info"), TONES.get(tone, TONES["info"])(t), 18))
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        msg = text(message, wrap=True)
        lay.addWidget(msg, 1)
        if action:
            label, cb = action
            btn = Button(label, "ghost", size="sm", on_click=lambda: (cb(), self.dismiss()))
            lay.addWidget(btn)
        lay.addWidget(IconButton("x", "Fechar aviso", self.dismiss, size=14))
        self.setAccessibleName(message)
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._timer.start(7000 if tone in ("danger", "warning") else 4000)
        self._closing = False

    def enterEvent(self, event: Any) -> None:  # noqa: N802
        self._timer.stop()  # pausa enquanto o mouse está em cima

    def leaveEvent(self, event: Any) -> None:  # noqa: N802
        self._timer.start(2500)

    def appear(self) -> None:
        t = tokens.current()
        if t.duration("base"):
            self._anim = QPropertyAnimation(self._opacity, b"opacity", self)
            self._anim.setDuration(t.duration("base"))
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
            self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._anim.start()

    def dismiss(self) -> None:
        if self._closing:
            return
        self._closing = True
        t = tokens.current()
        if t.duration("fast"):
            anim = QPropertyAnimation(self._opacity, b"opacity", self)
            anim.setDuration(t.duration("fast"))
            anim.setStartValue(self._opacity.opacity())
            anim.setEndValue(0.0)
            anim.finished.connect(self._finish)
            anim.start()
            self._anim = anim
        else:
            self._finish()

    def _finish(self) -> None:
        self.hide()
        self.closed.emit()
        self.deleteLater()


class ToastHost(QObject):
    """Empilha avisos no canto inferior direito da janela."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.window = window
        self.toasts: list[Toast] = []
        window.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if obj is self.window and event.type() == QEvent.Type.Resize:
            self._layout()
        return False

    def show(self, message: str, tone: str = "success",
             action: tuple[str, Callable[[], Any]] | None = None) -> Toast:
        toast = Toast(message, tone, action, self.window)
        toast.closed.connect(lambda: self._remove(toast))
        self.toasts.append(toast)
        if len(self.toasts) > 4:
            self.toasts[0].dismiss()
        toast.adjustSize()
        toast.show()
        toast.raise_()
        self._layout()
        toast.appear()
        return toast

    def _remove(self, toast: Toast) -> None:
        if toast in self.toasts:
            self.toasts.remove(toast)
        self._layout()

    def _layout(self) -> None:
        margin = 20
        y = self.window.height() - margin
        for toast in reversed(self.toasts):
            toast.adjustSize()
            y -= toast.height()
            toast.move(self.window.width() - toast.width() - margin, y)
            y -= 8


def notify(widget: QWidget | None, message: str, tone: str = "success",
           action: tuple[str, Callable[[], Any]] | None = None) -> Toast | None:
    """Mostra um aviso não bloqueante na janela que contém `widget`."""
    if widget is None:
        return None
    window = widget.window()
    host = getattr(window, "_toast_host", None)
    if host is None:
        host = ToastHost(window)
        window._toast_host = host  # type: ignore[attr-defined]
    return host.show(message, tone, action)


# ====================================================================== janelas
class Modal(QDialog):
    """Diálogo padrão: título, botão de fechar, corpo (`body`) e rodapé (`footer`)."""

    def __init__(self, title: str, parent: QWidget | None = None, width: int = 520) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        t = tokens.current()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(t.space("xl"), t.space("lg"), t.space("xl"), t.space("lg"))
        outer.setSpacing(t.space("lg"))
        head = QHBoxLayout()
        head.addWidget(ElidedLabel(title, "h2"), 1)
        head.addWidget(IconButton("x", "Fechar", self.reject))
        outer.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(t.space("md"))
        outer.addLayout(self.body, 1)
        self.footer = QHBoxLayout()
        self.footer.setSpacing(t.space("sm"))
        self.footer.addStretch(1)
        outer.addLayout(self.footer)

    def add_button(self, label: str, variant: str = "secondary",
                   on_click: Callable[[], Any] | None = None) -> Button:
        btn = Button(label, variant, on_click=on_click)
        self.footer.addWidget(btn)
        if variant == "primary":
            btn.setDefault(True)
        return btn


class Drawer(QFrame):
    """Painel que desliza da direita sobre a janela, com fundo escurecido. Esc fecha."""

    closed = Signal()

    def __init__(self, host: QWidget, title: str, width: int = 420) -> None:
        super().__init__(host)
        self.host = host
        self.panel_width = width
        self.scrim = QFrame(host)
        self.scrim.setProperty("scrim", "true")
        self.scrim.hide()
        self.scrim.mousePressEvent = lambda _e: self.close_drawer()  # type: ignore[method-assign]
        self.setProperty("card", "elevated")
        self.hide()
        t = tokens.current()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(t.space("lg"), t.space("lg"), t.space("lg"), t.space("lg"))
        head = QHBoxLayout()
        head.addWidget(ElidedLabel(title, "h2"), 1)
        head.addWidget(IconButton("x", "Fechar painel", self.close_drawer))
        lay.addLayout(head)
        self.body = QVBoxLayout()
        lay.addLayout(self.body, 1)
        host.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if obj is self.host and event.type() == QEvent.Type.Resize and self.isVisible():
            self._place(open_=True)
        return False

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close_drawer()
        else:
            super().keyPressEvent(event)

    def _place(self, open_: bool) -> QRect:
        h = self.host.height()
        w = min(self.panel_width, self.host.width())
        self.scrim.setGeometry(0, 0, self.host.width(), h)
        x = self.host.width() - w if open_ else self.host.width()
        rect = QRect(x, 0, w, h)
        self.setGeometry(rect)
        return rect

    def open_drawer(self) -> None:
        self.scrim.show()
        self.scrim.raise_()
        start = self._place(open_=False)
        end = QRect(self.host.width() - start.width(), 0, start.width(), start.height())
        self.show()
        self.raise_()
        self.setFocus()
        self._animate(start, end)

    def close_drawer(self) -> None:
        if not self.isVisible():
            return
        end = QRect(self.host.width(), 0, self.width(), self.height())
        anim = self._animate(self.geometry(), end)
        if anim is None:
            self._hide_all()
        else:
            anim.finished.connect(self._hide_all)

    def _hide_all(self) -> None:
        self.hide()
        self.scrim.hide()
        self.closed.emit()

    def _animate(self, start: QRect, end: QRect) -> QPropertyAnimation | None:
        d = tokens.current().duration("slow")
        if not d:
            self.setGeometry(end)
            return None
        anim = QPropertyAnimation(self, b"geometry", self)
        anim.setDuration(d)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._anim = anim
        return anim


def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


__all__ = [
    "BarList", "BarRow", "Badge", "Button", "Card", "Chip", "Divider", "Drawer", "ElidedLabel",
    "EmptyState", "EntityAvatar", "EntityTypeChip", "IconButton", "Input", "Kbd", "Modal",
    "SectionHeader", "Select", "Skeleton", "StatusBadge", "Toast", "ToastHost", "notify",
    "paint_avatar", "repolish", "shadow", "text", "QColor",
]
