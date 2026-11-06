"""Atalhos de interface usados pelas telas. Tudo delega ao design system (ui/design)."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout, QWidget

from nexus_intel.domain.errors import NexusError
from nexus_intel.domain.model import Epistemic
from nexus_intel.ui import format as fmt
from nexus_intel.ui.design.components import Button, Card, StatusBadge, notify

_VARIANTS = {None: "secondary", "Primary": "primary", "Danger": "danger", "Nav": "nav", "Ghost": "ghost"}
_ROLES = {"H1": "h1", "H2": "h2", "H3": "h3", "Muted": "muted", "Danger": "danger", "Warning": "warning",
          "Success": "success", "Brand": "brand", "Mono": "mono", "Caption": "caption"}


def label(text: str, name: str | None = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
        lb.setProperty("role", _ROLES.get(name, name.lower()))
    lb.setWordWrap(wrap)
    lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lb


def button(text: str, slot: Callable[..., Any] | None = None, name: str | None = None,
           tip: str = "", icon: str | None = None) -> Button:
    return Button(text, _VARIANTS.get(name, (name or "secondary").lower()), icon,
                  on_click=(lambda: slot()) if slot is not None else None, tooltip=tip)


def card(*widgets: QWidget, spacing: int = 8) -> Card:
    c = Card()
    c.body.setSpacing(spacing)
    for w in widgets:
        c.add(w)
    return c


def hbox(*items: QWidget | int | None, margins: int = 0, spacing: int = 8) -> QWidget:
    """Linha horizontal; `None` vira espaço elástico, int vira espaço fixo."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(margins, margins, margins, margins)
    lay.setSpacing(spacing)
    for it in items:
        if it is None:
            lay.addStretch(1)
        elif isinstance(it, int):
            lay.addSpacing(it)
        else:
            lay.addWidget(it)
    return w


def status_chip(status: str) -> QWidget:
    """Cor + ícone + texto, nunca só cor (seção 11.2)."""
    return StatusBadge(status)


_STATUS_MARK = {"verified": "✔", "reported": "◐", "unverified": "○", "hypothesis": "?",
                "conflicting": "⚠", "refuted": "✖"}


def status_text(status: str) -> str:
    try:
        return f"{_STATUS_MARK.get(status, '•')} {Epistemic(status).label}"
    except ValueError:
        return status


def fmt_ts(iso: str | None) -> str:
    return fmt.absolute(iso)


def show_error(parent: QWidget | None, exc: BaseException) -> None:
    if isinstance(exc, NexusError):
        window = parent.window() if parent is not None else None
        if window is not None and not isinstance(window, QDialog) and window.isVisible():
            notify(parent, exc.user_message, "warning")
        else:
            QMessageBox.warning(parent, "NEXUS INTEL", exc.user_message)
        return
    detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("NEXUS INTEL")
    box.setText("Ocorreu um erro inesperado. Nenhum dado parcial foi gravado.")
    box.setDetailedText(detail)
    box.exec()


def guarded(parent: QWidget | None, fn: Callable[[], Any]) -> Any:
    """Executa `fn` e mostra o erro amigável em vez de derrubar o app."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        show_error(parent, exc)
        return None


def confirm(parent: QWidget | None, title: str, text: str, danger: bool = False) -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setText(text)
    yes = box.addButton("Confirmar", QMessageBox.ButtonRole.AcceptRole)
    if danger:
        yes.setProperty("variant", "danger")
    box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is yes


class Page(QWidget):
    """Página com fundo do tema e margens padrão."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Page")
        self.setProperty("page", "true")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(28, 22, 28, 22)
        self.layout_.setSpacing(14)
