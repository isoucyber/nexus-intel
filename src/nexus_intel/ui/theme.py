"""Tokens de design e geração de QSS (seção 11.4). Três temas na v0.1."""

from __future__ import annotations

THEMES: dict[str, dict[str, str]] = {
    "nexus": {
        "label": "Nexus (escuro)",
        "bg.base": "#0b1220", "bg.surface": "#111a2e", "bg.elevated": "#18233b",
        "bg.input": "#0e1729", "fg.primary": "#e6edf7", "fg.muted": "#93a3bd",
        "accent": "#2dd4bf", "accent.fg": "#04201c", "border": "#24324f",
        "focus": "#5eead4", "danger": "#f87171", "warning": "#fbbf24",
        "success": "#34d399", "graph.bg": "#0b1220", "graph.edge": "#4b5d80",
    },
    "clean": {
        "label": "Clean (claro)",
        "bg.base": "#f6f7f9", "bg.surface": "#ffffff", "bg.elevated": "#ffffff",
        "bg.input": "#ffffff", "fg.primary": "#111827", "fg.muted": "#4b5563",
        "accent": "#2563eb", "accent.fg": "#ffffff", "border": "#d6dae1",
        "focus": "#1d4ed8", "danger": "#b91c1c", "warning": "#92400e",
        "success": "#047857", "graph.bg": "#ffffff", "graph.edge": "#9aa4b2",
    },
    "midnight": {
        "label": "Midnight (alto contraste)",
        "bg.base": "#000000", "bg.surface": "#0a0a0a", "bg.elevated": "#141414",
        "bg.input": "#000000", "fg.primary": "#ffffff", "fg.muted": "#c7c7c7",
        "accent": "#60a5fa", "accent.fg": "#000000", "border": "#5a5a5a",
        "focus": "#93c5fd", "danger": "#ff8a8a", "warning": "#ffd166",
        "success": "#6ee7b7", "graph.bg": "#000000", "graph.edge": "#8a8a8a",
    },
}

STATUS_COLORS = {
    "verified": "#22c55e",
    "reported": "#38bdf8",
    "unverified": "#94a3b8",
    "hypothesis": "#a78bfa",
    "conflicting": "#ef4444",
    "refuted": "#6b7280",
}

STATUS_ICONS = {
    "verified": "✔",
    "reported": "◐",
    "unverified": "○",
    "hypothesis": "?",
    "conflicting": "⚠",
    "refuted": "✖",
}


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    rgb = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def check_theme(t: dict[str, str]) -> list[str]:
    """Pares texto/fundo abaixo de 4,5:1 (WCAG AA)."""
    pairs = [
        ("fg.primary", "bg.base"), ("fg.primary", "bg.surface"), ("fg.muted", "bg.surface"),
        ("fg.muted", "bg.base"), ("accent.fg", "accent"), ("fg.primary", "bg.input"),
    ]
    return [f"{a}/{b}" for a, b in pairs if contrast(t[a], t[b]) < 4.5]


def stylesheet(name: str, scale: float = 1.0) -> str:
    t = THEMES.get(name, THEMES["nexus"])
    fs = round(13 * scale)
    return f"""
* {{ font-family: "Segoe UI", "Inter", sans-serif; font-size: {fs}px; color: {t['fg.primary']}; }}
QMainWindow, QDialog, QWidget#Page {{ background: {t['bg.base']}; }}
QWidget {{ background: transparent; }}
QFrame#Card, QFrame#Sidebar, QFrame#TopBar {{ background: {t['bg.surface']}; border: 1px solid {t['border']};
    border-radius: 10px; }}
QFrame#Sidebar {{ border-radius: 0; border-width: 0 1px 0 0; }}
QFrame#TopBar {{ border-radius: 0; border-width: 0 0 1px 0; }}
QLabel#Muted {{ color: {t['fg.muted']}; }}
QLabel#H1 {{ font-size: {round(fs * 1.7)}px; font-weight: 600; }}
QLabel#H2 {{ font-size: {round(fs * 1.3)}px; font-weight: 600; }}
QLabel#Danger {{ color: {t['danger']}; }}
QLabel#Warning {{ color: {t['warning']}; }}
QLabel#Brand {{ font-size: {round(fs * 1.25)}px; font-weight: 700; color: {t['accent']}; letter-spacing: 2px; }}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDateEdit {{
    background: {t['bg.input']}; border: 1px solid {t['border']}; border-radius: 6px; padding: 6px 8px;
    selection-background-color: {t['accent']}; selection-color: {t['accent.fg']}; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border: 1px solid {t['focus']}; }}
QComboBox QAbstractItemView {{ background: {t['bg.elevated']}; border: 1px solid {t['border']};
    selection-background-color: {t['accent']}; selection-color: {t['accent.fg']}; }}
QPushButton {{ background: {t['bg.elevated']}; border: 1px solid {t['border']}; border-radius: 6px;
    padding: 6px 14px; }}
QPushButton:hover {{ border-color: {t['accent']}; }}
QPushButton:focus {{ border: 1px solid {t['focus']}; }}
QPushButton#Primary {{ background: {t['accent']}; color: {t['accent.fg']}; border: none; font-weight: 600; }}
QPushButton#Danger {{ color: {t['danger']}; }}
QPushButton#Nav {{ text-align: left; border: none; border-radius: 6px; padding: 8px 12px; }}
QPushButton#Nav:checked {{ background: {t['bg.elevated']}; color: {t['accent']}; font-weight: 600; }}
QPushButton:disabled {{ color: {t['fg.muted']}; }}
QTableWidget, QTreeWidget, QListWidget {{ background: {t['bg.surface']}; border: 1px solid {t['border']};
    border-radius: 8px; gridline-color: {t['border']}; alternate-background-color: {t['bg.elevated']}; }}
QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {t['accent']}; color: {t['accent.fg']}; }}
QHeaderView::section {{ background: {t['bg.elevated']}; border: none; border-bottom: 1px solid {t['border']};
    padding: 6px; font-weight: 600; }}
QTabWidget::pane {{ border: 1px solid {t['border']}; border-radius: 8px; top: -1px; }}
QTabBar::tab {{ background: {t['bg.surface']}; border: 1px solid {t['border']}; padding: 6px 12px;
    border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {t['bg.elevated']}; color: {t['accent']}; }}
QScrollArea {{ border: none; }}
QToolTip {{ background: {t['bg.elevated']}; color: {t['fg.primary']}; border: 1px solid {t['border']}; }}
QMenu {{ background: {t['bg.elevated']}; border: 1px solid {t['border']}; }}
QMenu::item:selected {{ background: {t['accent']}; color: {t['accent.fg']}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; }}
"""
