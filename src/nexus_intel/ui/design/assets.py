"""Fontes e ícones embutidos.

Ícones: Lucide (ISC), SVG com `currentColor`, recoloridos conforme o token pedido.
Fontes: Inter e JetBrains Mono (SIL OFL 1.1). Se algum arquivo faltar, o app segue
com as fontes do sistema e um ícone neutro, nunca falha por causa disso.
"""

from __future__ import annotations

import hashlib
import tempfile
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from nexus_intel.ui.design import tokens

ASSETS = Path(__file__).resolve().parent.parent / "assets"
ICON_DIR = ASSETS / "icons"
FONT_DIR = ASSETS / "fonts"

# Um ícone por item de navegação, tipo de entidade e status (fonte única de verdade).
NAV_ICONS = {
    "home": "layout-dashboard", "entities": "database", "graph": "network", "sources": "library",
    "quality": "shield-check", "trash": "trash-2", "audit": "scroll-text", "projects": "folder",
    "settings": "settings", "lock": "lock", "search": "search", "ai": "sparkles",
}
TYPE_ICONS = {
    "person": "user", "company": "building-2", "organization": "landmark", "website": "globe",
    "domain": "at-sign", "ip": "network", "subject": "hash", "project": "folder-kanban",
    "object": "box", "vehicle": "car", "location": "map-pin", "event": "calendar",
    "document": "file-text", "account": "at-sign", "other": "circle",
}
STATUS_ICONS = {
    "verified": "circle-check", "reported": "message-circle", "unverified": "circle-dashed",
    "hypothesis": "circle-help", "conflicting": "triangle-alert", "refuted": "circle-x",
}
TONE_ICONS = {"success": "circle-check", "warning": "triangle-alert", "danger": "circle-alert",
              "info": "info", "neutral": "info", "accent": "sparkles"}

_fonts_loaded: dict[str, str] = {}


def load_fonts() -> dict[str, str]:
    """Registra as fontes embutidas. Devolve {"ui": família, "mono": família}."""
    if _fonts_loaded:
        return _fonts_loaded
    families: set[str] = set()
    for path in sorted(FONT_DIR.glob("*.ttf")):
        fid = QFontDatabase.addApplicationFont(str(path))
        if fid >= 0:
            families.update(QFontDatabase.applicationFontFamilies(fid))
    _fonts_loaded["ui"] = tokens.FONT_UI if tokens.FONT_UI in families else tokens.FONT_FALLBACK_UI[0]
    _fonts_loaded["mono"] = tokens.FONT_MONO if tokens.FONT_MONO in families else tokens.FONT_FALLBACK_MONO[0]
    return _fonts_loaded


def font_family(kind: str = "ui") -> str:
    return load_fonts().get(kind, tokens.FONT_FALLBACK_UI[0])


@lru_cache(maxsize=256)
def _svg_source(name: str) -> str | None:
    path = ICON_DIR / f"{name}.svg"
    return path.read_text("utf-8") if path.exists() else None


def svg_data(name: str, color: str, stroke: float = 2.0) -> bytes:
    src = _svg_source(name)
    if src is None:  # ícone ausente: círculo neutro
        src = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
               'stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="8"/></svg>')
    return (src.replace("currentColor", color)
            .replace('stroke-width="2"', f'stroke-width="{stroke:g}"')).encode("utf-8")


@lru_cache(maxsize=1024)
def pixmap(name: str, color: str, size: int = 16, dpr: float = 2.0, stroke: float = 2.0) -> QPixmap:
    px = QPixmap(QSize(round(size * dpr), round(size * dpr)))
    px.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg_data(name, color, stroke)))
    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, px.width(), px.height()))
    painter.end()
    px.setDevicePixelRatio(dpr)
    return px


def icon(name: str, color: str | None = None, size: int = 16, active_color: str | None = None) -> QIcon:
    """Ícone com estados normal, ativo (hover/selecionado) e desabilitado."""
    t = tokens.current()
    ic = QIcon()
    ic.addPixmap(pixmap(name, color or t.text_secondary, size), QIcon.Mode.Normal)
    ic.addPixmap(pixmap(name, active_color or color or t.text_primary, size), QIcon.Mode.Active)
    ic.addPixmap(pixmap(name, active_color or color or t.text_primary, size), QIcon.Mode.Selected)
    ic.addPixmap(pixmap(name, t.text_disabled, size), QIcon.Mode.Disabled)
    return ic


def qcolor(color: str, alpha: float = 1.0) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


_CACHE_DIR = Path(tempfile.gettempdir()) / "nexus-intel-icons"


def icon_file(name: str, color: str, size: int = 12) -> str:
    """Caminho de um SVG recolorido, para uso em `url()` do QSS (setas, marcas de seleção)."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data = svg_data(name, color, 2.5)
    digest = hashlib.sha1(data).hexdigest()[:12]  # noqa: S324 - nome de cache, não segurança
    path = _CACHE_DIR / f"{name}-{digest}.svg"
    if not path.exists():
        path.write_bytes(data.replace(b'width="24"', f'width="{size}"'.encode())
                         .replace(b'height="24"', f'height="{size}"'.encode()))
    return path.as_posix()
