"""Componentes e utilitários de interface compartilhados."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from nexus_intel.domain.errors import NexusError
from nexus_intel.domain.model import EPISTEMIC_LABELS, Epistemic
from nexus_intel.ui.theme import STATUS_COLORS, STATUS_ICONS


def label(text: str, name: str | None = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lb


def button(text: str, slot: Callable[..., Any] | None = None, name: str | None = None,
           tip: str = "") -> QPushButton:
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    if tip:
        b.setToolTip(tip)
    if slot is not None:
        b.clicked.connect(lambda *_: slot())
    return b


def card(*widgets: QWidget, spacing: int = 8) -> QFrame:
    f = QFrame()
    f.setObjectName("Card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(spacing)
    for w in widgets:
        lay.addWidget(w)
    return f


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


def status_chip(status: str) -> QLabel:
    """Cor + ícone + texto, nunca só cor (seção 11.2)."""
    color = STATUS_COLORS.get(status, "#94a3b8")
    text = EPISTEMIC_LABELS.get(Epistemic(status), status) if status in Epistemic._value2member_map_ else status
    lb = QLabel(f"{STATUS_ICONS.get(status, '•')} {text}")
    lb.setStyleSheet(
        f"color: {color}; border: 1px solid {color}; border-radius: 9px; padding: 1px 8px;"
    )
    lb.setToolTip(f"Status epistêmico: {text}")
    return lb


def status_text(status: str) -> str:
    try:
        return f"{STATUS_ICONS.get(status, '•')} {Epistemic(status).label}"
    except ValueError:
        return status


def fmt_ts(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso).astimezone()
    except ValueError:
        return iso
    return dt.strftime("%d/%m/%Y %H:%M")


def show_error(parent: QWidget | None, exc: BaseException) -> None:
    if isinstance(exc, NexusError):
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
    box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is yes


class Page(QWidget):
    """Página com fundo do tema e margens padrão."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Page")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(24, 20, 24, 20)
        self.layout_.setSpacing(12)
