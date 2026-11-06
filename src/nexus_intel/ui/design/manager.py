"""Aplica a aparência ao vivo: folha de estilo, paleta, fonte e aviso aos componentes.

Componentes que se desenham sozinhos (grafo, barras, avatares) conectam-se a
`theme_manager().changed` e se redesenham, sem reiniciar o app.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from nexus_intel.ui.design import assets, qss, tokens
from nexus_intel.ui.design.tokens import Appearance, Tokens


class ThemeManager(QObject):
    changed = Signal(object)  # Tokens

    def apply(self, app: Appearance | None = None) -> Tokens:
        t = tokens.set_appearance(app or tokens.appearance())
        qapp = QApplication.instance()
        if qapp is None:
            return t
        assets.load_fonts()
        assets.pixmap.cache_clear()
        font = QFont(assets.font_family("ui"))
        font.setPixelSize(t.font_px("sm"))
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        qapp.setFont(font)
        qapp.setPalette(_palette(t))
        qapp.setStyleSheet(qss.build(t))
        self.changed.emit(t)
        return t


def _palette(t: Tokens) -> QPalette:
    p = QPalette()
    c = assets.qcolor
    roles = {
        QPalette.ColorRole.Window: t.bg, QPalette.ColorRole.WindowText: t.text_primary,
        QPalette.ColorRole.Base: t.surface_sunken, QPalette.ColorRole.AlternateBase: t.surface,
        QPalette.ColorRole.Text: t.text_primary, QPalette.ColorRole.Button: t.surface_elevated,
        QPalette.ColorRole.ButtonText: t.text_primary, QPalette.ColorRole.Highlight: t.selection,
        QPalette.ColorRole.HighlightedText: t.selection_text, QPalette.ColorRole.ToolTipBase: t.surface_elevated,
        QPalette.ColorRole.ToolTipText: t.text_primary, QPalette.ColorRole.PlaceholderText: t.text_muted,
        QPalette.ColorRole.Link: t.accent_text, QPalette.ColorRole.LinkVisited: t.accent_text,
        QPalette.ColorRole.BrightText: t.text_primary, QPalette.ColorRole.Mid: t.border,
        QPalette.ColorRole.Dark: t.border_strong, QPalette.ColorRole.Light: t.surface_hover,
        QPalette.ColorRole.Midlight: t.surface_elevated, QPalette.ColorRole.Shadow: t.bg,
        QPalette.ColorRole.Accent: t.accent,
    }
    for role, value in roles.items():
        p.setColor(role, c(value))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, c(t.text_disabled))
    return p


_manager: ThemeManager | None = None


def theme_manager() -> ThemeManager:
    global _manager
    if _manager is None:
        _manager = ThemeManager()
    return _manager


def apply_appearance(app: Appearance | None = None) -> Tokens:
    return theme_manager().apply(app)


def screen_dpr() -> float:
    screen = QGuiApplication.primaryScreen()
    return float(screen.devicePixelRatio()) if screen else 1.0
