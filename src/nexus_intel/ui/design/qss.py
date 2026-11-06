"""Folha de estilo Qt gerada a partir dos tokens. Não contém nenhuma cor literal.

Variantes de componente usam propriedades dinâmicas, por exemplo:
    QPushButton[variant="primary"], QFrame[card="true"], QLabel[role="muted"].
"""

from __future__ import annotations

from nexus_intel.ui.design.assets import font_family, icon_file
from nexus_intel.ui.design.color import rgba
from nexus_intel.ui.design.tokens import Tokens


def build(t: Tokens) -> str:
    ui, mono = font_family("ui"), font_family("mono")
    fs = t.font_px("sm")
    pad_y, pad_x = t.space("sm") - 1, t.space("md")
    r_sm, r_md, r_lg = t.radius("sm"), t.radius("md"), t.radius("lg")
    row = t.space("sm") - 2
    chev_down = icon_file("chevron-down", t.text_secondary)
    chev_up = icon_file("chevron-up", t.text_secondary)
    check = icon_file("check", t.accent_fg)
    return f"""
* {{
    font-family: "{ui}", "Segoe UI", sans-serif;
    font-size: {fs}px;
    color: {t.text_primary};
    selection-background-color: {t.selection};
    selection-color: {t.selection_text};
    outline: none;
}}
QWidget {{ background: transparent; }}
QMainWindow, QDialog, QWidget[page="true"] {{ background: {t.bg}; }}
QDialog {{ background: {t.surface}; }}

/* ---------- tipografia */
QLabel[role="display"], QLabel#Display {{ font-size: {t.font_px("display")}px; font-weight: 600; }}
QLabel[role="h1"], QLabel#H1 {{ font-size: {t.font_px("xxl")}px; font-weight: 600; }}
QLabel[role="h2"], QLabel#H2 {{ font-size: {t.font_px("lg")}px; font-weight: 600; }}
QLabel[role="h3"], QLabel#H3 {{ font-size: {t.font_px("md")}px; font-weight: 600; }}
QLabel[role="muted"], QLabel#Muted {{ color: {t.text_muted}; }}
QLabel[role="secondary"], QLabel#Secondary {{ color: {t.text_secondary}; }}
QLabel[role="caption"], QLabel#Caption {{ color: {t.text_muted}; font-size: {t.font_px("xs")}px; }}
QLabel[role="overline"] {{ color: {t.text_muted}; font-size: {t.font_px("xs")}px; font-weight: 600;
    letter-spacing: 0.6px; }}
QLabel[role="danger"], QLabel#Danger {{ color: {t.danger}; }}
QLabel[role="warning"], QLabel#Warning {{ color: {t.warning}; }}
QLabel[role="success"], QLabel#Success {{ color: {t.success}; }}
QLabel[role="mono"], QLabel#Mono {{ font-family: "{mono}", monospace; color: {t.text_secondary}; }}
QLabel[role="brand"], QLabel#Brand {{ color: {t.accent_text}; font-weight: 700; letter-spacing: 2px;
    font-size: {t.font_px("md")}px; }}
QLabel a {{ color: {t.accent_text}; }}

/* ---------- superfícies */
QFrame[card="true"], QFrame#Card {{ background: {t.surface}; border: 1px solid {t.border};
    border-radius: {r_lg}px; }}
QFrame[card="elevated"] {{ background: {t.surface_elevated}; border: 1px solid {t.border_strong};
    border-radius: {r_lg}px; }}
QFrame[sidebar="true"], QFrame#Sidebar {{ background: {t.surface}; border: none;
    border-right: 1px solid {t.border}; }}
QFrame[topbar="true"], QFrame#TopBar {{ background: {t.bg}; border: none;
    border-bottom: 1px solid {t.border}; }}
QFrame[divider="true"] {{ background: {t.border}; border: none; max-height: 1px; min-height: 1px; }}
QFrame[scrim="true"] {{ background: {rgba(t.overlay, 0.55)}; }}

/* ---------- botões */
QPushButton, QToolButton {{
    background: {t.surface_elevated}; color: {t.text_primary};
    border: 1px solid {t.border_strong}; border-radius: {r_md}px;
    padding: {pad_y}px {pad_x}px; font-weight: 500;
}}
QToolButton {{ padding: {max(2, pad_y - 1)}px; }}
QPushButton:hover, QToolButton:hover {{ background: {t.surface_hover}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {t.surface_active}; }}
QPushButton:focus, QToolButton:focus {{ border: 2px solid {t.focus}; padding: {pad_y - 1}px {pad_x - 1}px; }}
QToolButton:focus {{ padding: {max(1, pad_y - 2)}px; }}
QPushButton:disabled, QToolButton:disabled {{ color: {t.text_disabled}; border-color: {t.border}; }}
QPushButton[variant="primary"] {{ background: {t.accent}; color: {t.accent_fg}; border-color: {t.accent}; }}
QPushButton[variant="primary"]:hover {{ background: {t.accent_hover}; border-color: {t.accent_hover}; }}
QPushButton[variant="primary"]:pressed {{ background: {t.accent_active}; }}
QPushButton[variant="primary"]:focus {{ border: 2px solid {t.focus}; }}
QPushButton[variant="primary"]:disabled {{ background: {t.surface_active}; color: {t.text_disabled};
    border-color: {t.border}; }}
QPushButton[variant="ghost"], QToolButton[variant="ghost"] {{ background: transparent; border-color: transparent; }}
QPushButton[variant="ghost"]:hover, QToolButton[variant="ghost"]:hover {{ background: {t.surface_hover}; }}
QPushButton[variant="ghost"]:pressed, QToolButton[variant="ghost"]:pressed {{ background: {t.surface_active}; }}
QPushButton[variant="ghost"]:focus, QToolButton[variant="ghost"]:focus {{ border: 2px solid {t.focus}; }}
QPushButton[variant="danger"] {{ color: {t.danger}; }}
QPushButton[variant="danger"]:hover {{ background: {t.danger_subtle}; border-color: {t.danger}; }}
QPushButton[variant="nav"] {{
    background: transparent; border: 1px solid transparent; text-align: left;
    color: {t.text_secondary}; padding: {pad_y}px {t.space("sm") + 2}px; border-radius: {r_md}px;
}}
QPushButton[variant="nav"]:hover {{ background: {t.surface_hover}; color: {t.text_primary}; }}
QPushButton[variant="nav"]:checked {{ background: {t.accent_subtle}; color: {t.text_primary}; font-weight: 600; }}
QPushButton[variant="nav"]:focus {{ border: 2px solid {t.focus}; padding: {pad_y - 1}px {t.space("sm") + 1}px; }}
QPushButton[size="sm"] {{ padding: {max(2, pad_y - 3)}px {t.space("sm")}px; font-size: {t.font_px("xs")}px; }}

/* ---------- campos */
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{
    background: {t.surface_sunken}; color: {t.text_primary};
    border: 1px solid {t.input_border}; border-radius: {r_md}px;
    padding: {pad_y - 1}px {t.space("sm") + 2}px;
}}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover, QComboBox:hover, QSpinBox:hover,
QDoubleSpinBox:hover {{ border-color: {t.text_muted}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QDateEdit:focus {{ border: 2px solid {t.focus}; padding: {pad_y - 2}px {t.space("sm") + 1}px; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {t.text_disabled}; border-color: {t.border}; }}
QLineEdit[search="true"] {{ background: {t.surface}; border-radius: {r_md}px; padding-left: {t.space("sm")}px; }}
QComboBox {{ padding-right: 28px; }}
QComboBox::drop-down {{ border: none; width: 26px; subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url("{chev_down}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {t.surface_elevated}; border: 1px solid {t.border_strong}; border-radius: {r_md}px;
    padding: 4px; selection-background-color: {t.selection}; selection-color: {t.selection_text};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::down-button {{
    border: none; width: 18px; background: transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{chev_up}"); width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{chev_down}"); width: 10px; height: 10px; }}

QCheckBox, QRadioButton {{ spacing: 8px; color: {t.text_primary}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px; border: 1px solid {t.input_border}; background: {t.surface_sunken};
}}
QCheckBox::indicator {{ border-radius: {r_sm}px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {t.text_muted}; }}
QCheckBox::indicator:focus, QRadioButton::indicator:focus {{ border: 2px solid {t.focus}; }}
QCheckBox::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; image: url("{check}"); }}
QRadioButton::indicator:checked {{ background: {t.accent}; border: 4px solid {t.surface_sunken}; }}
QCheckBox:disabled {{ color: {t.text_disabled}; }}

/* ---------- listas, tabelas e árvores (seleção sempre legível) */
QAbstractItemView {{
    background: {t.surface}; alternate-background-color: {t.surface_sunken};
    border: 1px solid {t.border}; border-radius: {r_md}px; gridline-color: {t.border};
    selection-background-color: {t.selection}; selection-color: {t.selection_text};
}}
QAbstractItemView:focus {{ border: 1px solid {t.focus}; }}
QAbstractItemView::item {{ padding: {row}px {t.space("sm")}px; border: none; }}
QAbstractItemView::item:hover {{ background: {t.surface_hover}; }}
QAbstractItemView::item:selected {{ background: {t.selection}; color: {t.selection_text}; }}
QAbstractItemView::item:selected:!active {{ background: {t.surface_active}; color: {t.text_primary}; }}
QTreeView::branch {{ background: transparent; }}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{
    background: {t.surface}; color: {t.text_muted}; border: none; border-bottom: 1px solid {t.border};
    padding: {row + 1}px {t.space("sm")}px; font-size: {t.font_px("xs")}px; font-weight: 600;
}}
QHeaderView::section:hover {{ color: {t.text_primary}; }}
QTableCornerButton::section {{ background: {t.surface}; border: none; }}

/* ---------- barras de rolagem do tema */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t.border_strong}; border-radius: 3px; min-height: 32px; margin: 0 2px; }}
QScrollBar::handle:horizontal {{ background: {t.border_strong}; border-radius: 3px; min-width: 32px; margin: 2px 0; }}
QScrollBar::handle:hover, QScrollBar::handle:pressed {{ background: {t.text_muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* ---------- abas (sublinhado) */
QTabWidget::pane {{ border: none; border-top: 1px solid {t.border}; top: -1px; background: transparent; }}
QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent; color: {t.text_secondary}; border: none;
    border-bottom: 2px solid transparent; padding: {pad_y}px {t.space("md")}px; margin-right: 2px;
}}
QTabBar::tab:hover {{ color: {t.text_primary}; }}
QTabBar::tab:selected {{ color: {t.text_primary}; border-bottom: 2px solid {t.accent}; font-weight: 600; }}
QTabBar::tab:focus {{ color: {t.text_primary}; }}
QTabBar::close-button {{ subcontrol-position: right; }}

/* ---------- menus, dicas e diálogos */
QMenu {{ background: {t.surface_elevated}; border: 1px solid {t.border_strong}; border-radius: {r_md}px; padding: 4px; }}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: {r_sm}px; color: {t.text_primary}; }}
QMenu::item:selected {{ background: {t.surface_hover}; }}
QMenu::item:disabled {{ color: {t.text_disabled}; }}
QMenu::separator {{ height: 1px; background: {t.border}; margin: 4px 6px; }}
QToolTip {{ background: {t.surface_elevated}; color: {t.text_primary}; border: 1px solid {t.border_strong};
    border-radius: {r_sm}px; padding: 5px 8px; font-size: {t.font_px("xs")}px; }}
QMessageBox QLabel {{ color: {t.text_primary}; }}
QSplitter::handle {{ background: {t.border}; }}
QSplitter::handle:hover {{ background: {t.accent}; }}
QProgressBar {{ background: {t.surface_sunken}; border: none; border-radius: 3px; height: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {t.accent}; border-radius: 3px; }}
QLabel[formLabel="true"] {{ color: {t.text_secondary}; }}
"""
