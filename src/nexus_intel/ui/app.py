"""Janela principal, navegação entre telas e bloqueio por inatividade (seção 6.1)."""

from __future__ import annotations

from dataclasses import replace

import logging
import sys
from typing import Any

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QMainWindow,
    QSpinBox,
    QStackedWidget,
    QWidget,
)

from nexus_intel import __version__
from nexus_intel.application.projects import ProjectManager
from nexus_intel.application.session import Session
from nexus_intel.infrastructure.crypto.vault import CRYPTO_FULL
from nexus_intel.infrastructure.paths import AppPaths, default_paths
from nexus_intel.ui.auth import ChangePasswordDialog, LoginPage, RecoveryKeyDialog, SetupPage
from nexus_intel.ui.common import button, confirm, guarded, hbox, label, show_error
from nexus_intel.ui.projects_page import ProjectsPage
from nexus_intel.ui.design import tokens
from nexus_intel.ui.design.manager import apply_appearance
from nexus_intel.ui.workspace import Workspace

log = logging.getLogger("nexus_intel")

DEFAULTS: dict[str, Any] = {"idle_minutes": 10}

THIRD_PARTY = (
    "Qt / PySide6 — LGPL-3.0 · cryptography — Apache-2.0/BSD · SQLCipher — BSD · "
    "Pydantic — MIT · platformdirs — MIT · NumPy — BSD-3-Clause · SQLite — domínio público"
)


class IdleWatcher(QObject):
    """Qualquer tecla ou movimento do mouse reinicia o contador de inatividade."""

    def __init__(self, timeout_ms: int, on_idle: Any) -> None:
        super().__init__()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(on_idle)
        self.set_timeout(timeout_ms)

    def set_timeout(self, ms: int) -> None:
        self.timer.setInterval(max(60_000, ms))

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress,
                            QEvent.Type.Wheel) and self.timer.isActive():
            self.timer.start()
        return False


class SettingsDialog(QDialog):
    def __init__(self, win: MainWindow) -> None:
        super().__init__(win)
        self.win = win
        s = win.session
        self.setWindowTitle("Configurações")
        self.setMinimumWidth(520)
        current = win.appearance()
        self.theme = QComboBox()
        for k, t in tokens.THEMES.items():
            self.theme.addItem(t.label, k)
        self.theme.setCurrentIndex(self.theme.findData(current.theme))
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.9, 1.25)
        self.scale.setSingleStep(0.05)
        self.scale.setValue(current.scale)
        self.idle = QSpinBox()
        self.idle.setRange(1, 240)
        self.idle.setSuffix(" min")
        self.idle.setValue(int(win.pref("idle_minutes")))
        form = QFormLayout(self)
        form.addRow(label("Aparência", "H2"))
        form.addRow("Tema", self.theme)
        form.addRow("Tamanho do texto", self.scale)
        form.addRow(label("Segurança", "H2"))
        form.addRow("Bloquear após inatividade", self.idle)
        mode = "Dados cifrados (SQLCipher + AES-256)" if s.crypto_mode == CRYPTO_FULL else \
            "Sem cifragem: só o login protege. Use BitLocker no disco."
        form.addRow("Criptografia", label(mode, "Muted" if s.crypto_mode == CRYPTO_FULL else "Warning", wrap=True))
        form.addRow(hbox(button("Trocar senha…", self._change_pw), button("Gerar nova chave de recuperação…",
                                                                          self._rotate), None))
        form.addRow(label("Sobre", "H2"))
        form.addRow(label(f"NEXUS INTEL {__version__} · Apache-2.0\nPasta de dados: {s.paths.data}\n\n"
                          f"Componentes de terceiros: {THIRD_PARTY}", "Muted", wrap=True))
        form.addRow(hbox(None, button("Cancelar", self.reject), button("Salvar", self.accept, "Primary")))

    def _change_pw(self) -> None:
        ChangePasswordDialog(self.win.session, self).exec()

    def _rotate(self) -> None:
        if confirm(self, "Nova chave de recuperação",
                   "A chave atual deixará de funcionar. Gerar uma nova agora?"):
            key = guarded(self, self.win.session.rotate_recovery_key)
            if key:
                RecoveryKeyDialog(key, self).exec()

    def accept(self) -> None:
        self.win.set_appearance(replace(self.win.appearance(), theme=self.theme.currentData(),
                                        scale=round(self.scale.value(), 2)))
        self.win.set_pref("idle_minutes", self.idle.value())
        self.win.apply_prefs()
        super().accept()


class MainWindow(QMainWindow):
    def __init__(self, paths: AppPaths | None = None) -> None:
        super().__init__()
        self.setWindowTitle("NEXUS INTEL")
        self.resize(1360, 860)
        self.session = Session(paths or default_paths())
        self.manager: ProjectManager | None = None
        self.workspace: Workspace | None = None
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.setup_page = SetupPage(self.session)
        self.login_page = LoginPage(self.session)
        self.setup_page.done.connect(self._after_login)
        self.login_page.done.connect(self._after_login)
        self.projects_page: ProjectsPage | None = None
        self.stack.addWidget(self.setup_page)
        self.stack.addWidget(self.login_page)

        self.idle = IdleWatcher(DEFAULTS["idle_minutes"] * 60_000, self.lock)
        QApplication.instance().installEventFilter(self.idle)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.lock)
        apply_appearance(tokens.Appearance())
        self._show_entry()

    # ------------------------------------------------------------ prefs
    def pref(self, key: str) -> Any:
        if not self.session.unlocked:
            return DEFAULTS[key]
        return self.session.get_setting(key, DEFAULTS[key])

    def set_pref(self, key: str, value: Any) -> None:
        self.session.set_setting(key, value)

    def appearance(self) -> tokens.Appearance:
        """Aparência salva; aceita o formato antigo (theme/font_scale) da v0.1."""
        if not self.session.unlocked:
            return tokens.Appearance()
        data = self.session.get_setting("appearance")
        if data is None:
            data = {"theme": self.session.get_setting("theme", tokens.DEFAULT_THEME),
                    "scale": self.session.get_setting("font_scale", 1.0)}
        return tokens.Appearance.from_dict(data)

    def set_appearance(self, app: tokens.Appearance) -> None:
        self.session.set_setting("appearance", app.to_dict())

    def apply_prefs(self) -> None:
        # Aplica ao vivo: componentes e grafo se redesenham sem recriar telas.
        apply_appearance(self.appearance())
        self.idle.set_timeout(int(self.pref("idle_minutes")) * 60_000)

    # ------------------------------------------------------------ fluxo
    def _show_entry(self) -> None:
        if self.session.initialized:
            self.login_page.prepare()
            self.stack.setCurrentWidget(self.login_page)
        else:
            self.stack.setCurrentWidget(self.setup_page)

    def _after_login(self) -> None:
        self.manager = ProjectManager(self.session)
        if self.projects_page is None:
            self.projects_page = ProjectsPage(self.manager)
            self.projects_page.open_project.connect(self.open_project)
            self.projects_page.lock_requested.connect(self.lock)
            self.projects_page.settings_requested.connect(lambda: SettingsDialog(self).exec())
            self.stack.addWidget(self.projects_page)
        else:
            self.projects_page.manager = self.manager
        self.apply_prefs()
        self.idle.timer.start()
        self.show_projects()

    def show_projects(self) -> None:
        if self.manager:
            self.manager.close_current()
        self._drop_workspace()
        assert self.projects_page is not None
        self.projects_page.refresh()
        self.stack.setCurrentWidget(self.projects_page)
        self.setWindowTitle("NEXUS INTEL")

    def open_project(self, project_id: str) -> None:
        assert self.manager is not None
        store = guarded(self, lambda: self.manager.open(project_id))  # type: ignore[union-attr]
        if store is None:
            return
        info = self.manager.get(project_id)
        self._drop_workspace()
        try:
            self.workspace = Workspace(store, info.name, info.color)
        except Exception as exc:  # noqa: BLE001
            self.manager.close_current()
            show_error(self, exc)
            return
        self.workspace.back_to_projects.connect(self.show_projects)
        self.workspace.lock_requested.connect(self.lock)
        self.stack.addWidget(self.workspace)
        self.stack.setCurrentWidget(self.workspace)
        self.setWindowTitle(f"{info.name} — NEXUS INTEL")

    def _drop_workspace(self) -> None:
        if self.workspace is not None:
            self.workspace.shutdown()
            self.stack.removeWidget(self.workspace)
            self.workspace.deleteLater()
            self.workspace = None

    def lock(self) -> None:
        if not self.session.unlocked:
            return
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QDialog) and w.isVisible():
                w.reject()
        self._drop_workspace()
        self.session.lock()  # fecha projeto, banco e apaga chaves
        self.idle.timer.stop()
        apply_appearance(tokens.Appearance())
        self._show_entry()

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        try:
            if self.workspace is not None:
                self.workspace.shutdown()
            if self.manager:
                self.manager.close_current()
            self.session.lock()
        finally:
            super().closeEvent(event)


def _setup_logging(paths: AppPaths) -> None:
    from logging.handlers import RotatingFileHandler

    handler = RotatingFileHandler(paths.logs / "nexus-intel.log", maxBytes=5_000_000, backupCount=10,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter('{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}'))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def run(argv: list[str] | None = None) -> int:
    paths = default_paths().ensure()
    _setup_logging(paths)
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("NEXUS INTEL")
    app.setApplicationVersion(__version__)
    app.setFont(QFont("Segoe UI", 10))

    def excepthook(exc_type: Any, exc: BaseException, tb: Any) -> None:
        log.error("erro não tratado: %s", exc_type.__name__)
        show_error(None, exc)

    sys.excepthook = excepthook
    win = MainWindow(paths)
    win.show()
    log.info("iniciado %s", __version__)
    return int(app.exec())


__all__ = ["MainWindow", "QWidget", "run"]
