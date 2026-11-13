"""Janela principal, navegação entre telas e bloqueio por inatividade (seção 6.1)."""

from __future__ import annotations

from dataclasses import replace

import logging
import sys
from typing import Any

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QFont, QGuiApplication, QKeySequence, QPixmapCache, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QLineEdit,
    QMainWindow,
    QSpinBox,
    QStackedWidget,
    QWidget,
)

from nexus_intel import __version__
from nexus_intel.application.profiles import ProfileManager
from nexus_intel.application.projects import ProjectManager
from nexus_intel.application.session import Session
from nexus_intel.infrastructure.crypto.vault import CRYPTO_FULL
from nexus_intel.infrastructure.paths import AppPaths, default_paths
from nexus_intel.ui.auth import (
    ChangePasswordDialog,
    LoginPage,
    RecoveryKeyDialog,
    SetupPage,
    _password,
    ensure_recent_auth,
)
from nexus_intel.ui import format as fmt
from nexus_intel.ui.common import button, confirm, guarded, hbox, label, show_error
from nexus_intel.ui.projects_page import ProjectsPage
from nexus_intel.ui.design import tokens
from nexus_intel.ui.design.components import dialog_form, notify
from nexus_intel.ui.design.manager import apply_appearance
from nexus_intel.ui.profiles_ui import AvatarPicker, ProfilesPage
from nexus_intel.ui.ai_common import PrefsStore
from nexus_intel.ui.workspace import Workspace

log = logging.getLogger("nexus_intel")

DEFAULTS: dict[str, Any] = {"idle_minutes": 10}

SECURITY_LABELS = {
    "profile.create": "Perfil criado", "login": "Entrada com senha", "login.recovery": "Entrada com chave de recuperação",
    "password.change": "Senha alterada", "reauth.ok": "Senha confirmada", "reauth.fail": "Confirmação de senha falhou",
    "recovery_key.rotate": "Nova chave de recuperação", "identity.rotate": "Nova chave de identidade",
    "export": "Projeto exportado (.nexus)", "import": "Projeto importado (.nexus)",
    "import.rejected": "Importação recusada", "project.delete": "Projeto excluído",
    "profile.update": "Perfil alterado",
}

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
        info = win.profile_info()
        self.display_name = QLineEdit(info.display_name if info else "")
        self.display_name.setMaxLength(60)
        self.avatar = AvatarPicker(info.display_name if info else "", info.avatar_path if info else None)
        form = dialog_form(self, "Configurações", 560, scroll=True)
        form.addRow(label("Perfil", "H2"))
        form.addRow("Nome de exibição", self.display_name)
        form.addRow("Imagem", self.avatar)
        if info:
            form.addRow("Usuário", label(info.username, "Muted"))
            # Lida do banco cifrado do perfil (o índice público poderia ter sido editado).
            form.addRow("Chave de identidade", label(guarded(self, s.fingerprint) or "—", "Muted"))
        form.addRow(hbox(button("Excluir este perfil…", self._delete_profile, "Danger", icon="trash-2"), None))
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
        form.addRow(hbox(button("Gerar nova chave de identidade…", self._rotate_identity), None))
        form.addRow(label("Registro de segurança", "H2"))
        events = guarded(self, lambda: s.security_events(8)) or []
        broken = guarded(self, s.verify_security_log)
        form.addRow(label("Íntegro (cadeia SHA-256 conferida)" if broken is None else
                          f"ALTERADO a partir do evento {broken}: o registro foi editado fora do NEXUS.",
                          "Muted" if broken is None else "Danger", wrap=True))
        for ev in events:
            detail = f" — {ev['detail']}" if ev["detail"] else ""
            form.addRow(label(f"{fmt.absolute(ev['ts'])}  {SECURITY_LABELS.get(ev['kind'], ev['kind'])}{detail}",
                              "Caption", wrap=True))
        form.addRow(label("Sobre", "H2"))
        form.addRow(label(f"NEXUS INTEL {__version__} · Apache-2.0\nPasta de dados: {s.paths.data}\n\n"
                          f"Componentes de terceiros: {THIRD_PARTY}", "Muted", wrap=True))
        form.addRow(hbox(None, button("Cancelar", self.reject), button("Salvar", self.accept, "Primary")))

    def _change_pw(self) -> None:
        ChangePasswordDialog(self.win.session, self).exec()

    def _rotate(self) -> None:
        if not ensure_recent_auth(self, self.win.session, "Gerar uma nova chave de recuperação é uma operação "
                                  "sensível: confirme a senha deste perfil."):
            return
        if confirm(self, "Nova chave de recuperação",
                   "A chave atual deixará de funcionar. Gerar uma nova agora?"):
            key = guarded(self, self.win.session.rotate_recovery_key)
            if key:
                RecoveryKeyDialog(key, self).exec()

    def _rotate_identity(self) -> None:
        if not ensure_recent_auth(self, self.win.session, "Trocar a chave de identidade muda a impressão "
                                  "digital que assina seus arquivos .nexus: confirme a senha."):
            return
        if confirm(self, "Nova chave de identidade",
                   "Os próximos arquivos .nexus serão assinados com uma chave nova. Avise quem confere sua "
                   "impressão digital. Continuar?"):
            fp = guarded(self, self.win.session.rotate_identity)
            if fp:
                guarded(self, lambda: self.win.profiles.update(self.win.session))
                notify(self, f"Nova impressão digital: {fp}", "success")

    def _delete_profile(self) -> None:
        if DeleteProfileDialog(self.win, self).exec():
            self.done(0)

    def accept(self) -> None:
        info = self.win.profile_info()
        name = self.display_name.text().strip()
        if info is not None and name and (name != info.display_name or self.avatar.data is not None
                                          or self.avatar.removed):
            guarded(self, lambda: self.win.profiles.update(
                self.win.session, display_name=name, avatar=self.avatar.data, remove_avatar=self.avatar.removed))
            self.win.refresh_profile_ui()
        self.win.set_appearance(replace(self.win.appearance(), theme=self.theme.currentData(),
                                        scale=round(self.scale.value(), 2)))
        self.win.set_pref("idle_minutes", self.idle.value())
        self.win.apply_prefs()
        super().accept()


class DeleteProfileDialog(QDialog):
    """Exclusão do perfil: exige a senha do próprio perfil e digitar o nome de exibição."""

    def __init__(self, win: MainWindow, parent: QWidget | None = None) -> None:
        super().__init__(parent or win)
        self.win = win
        info = win.profile_info()
        self.expected = info.display_name if info else ""
        self.pw = _password("Senha deste perfil")
        self.confirm_name = QLineEdit()
        self.confirm_name.setPlaceholderText(self.expected)
        self.error = label("", "Danger", wrap=True)
        form = dialog_form(self, "Excluir perfil", 480)
        form.addRow(label(
            f"Isto apaga DEFINITIVAMENTE o perfil “{self.expected}”: projetos, entidades, fotografias, notas, "
            "preferências e chaves. Outros perfis não são afetados. Não há como desfazer.", "Warning", wrap=True))
        form.addRow("Digite o nome do perfil", self.confirm_name)
        form.addRow("Senha", self.pw)
        form.addRow(self.error)
        self.ok = button("Excluir perfil", self._delete, "Danger")
        self.ok.setEnabled(False)
        self.confirm_name.textChanged.connect(lambda t: self.ok.setEnabled(t.strip() == self.expected))
        form.addRow(hbox(None, button("Cancelar", self.reject), self.ok))

    def _delete(self) -> None:
        from nexus_intel.domain.errors import NexusError

        self.win._drop_workspace()
        if self.win.manager:
            self.win.manager.close_current()
        try:
            self.win.profiles.delete(self.win.session, self.pw.text())
        except NexusError as exc:
            self.error.setText(exc.user_message)
            return
        self.accept()
        self.win.after_profile_deleted()


class MainWindow(QMainWindow):
    def __init__(self, paths: AppPaths | None = None) -> None:
        super().__init__()
        self.setWindowTitle("NEXUS INTEL")
        self.resize(1360, 860)
        self.root_paths = paths or default_paths()
        self.profiles = ProfileManager(self.root_paths)  # migra a instalação de usuário único, se houver
        self.session: Session | None = None
        self.manager: ProjectManager | None = None
        self.workspace: Workspace | None = None
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.profiles_page = ProfilesPage(self.profiles)
        self.setup_page = SetupPage(self.profiles)
        self.login_page = LoginPage()
        self.profiles_page.chosen.connect(self.choose_profile)
        self.profiles_page.create_requested.connect(lambda: self.show_setup(first=False))
        self.setup_page.done.connect(self._after_setup)
        self.setup_page.back.connect(self.show_profiles_list)
        self.login_page.done.connect(self._after_login)
        self.login_page.switch_profile.connect(self.switch_profile)
        self.projects_page: ProjectsPage | None = None
        for page in (self.profiles_page, self.setup_page, self.login_page):
            self.stack.addWidget(page)

        self.idle = IdleWatcher(DEFAULTS["idle_minutes"] * 60_000, self.lock)
        QApplication.instance().installEventFilter(self.idle)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.lock)
        apply_appearance(tokens.Appearance())
        self._show_entry()

    # ------------------------------------------------------------ prefs
    def pref(self, key: str) -> Any:
        if self.session is None or not self.session.unlocked:
            return DEFAULTS[key]
        return self.session.get_setting(key, DEFAULTS[key])

    def set_pref(self, key: str, value: Any) -> None:
        self.session.set_setting(key, value)

    def appearance(self) -> tokens.Appearance:
        """Aparência salva; aceita o formato antigo (theme/font_scale) da v0.1."""
        if self.session is None or not self.session.unlocked:
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
    def profile_info(self) -> Any:
        if self.session is None or not self.session.profile_id:
            return None
        try:
            return self.profiles.get(self.session.profile_id)
        except Exception:  # noqa: BLE001
            return None

    def _show_entry(self) -> None:
        infos = self.profiles.list()
        if not infos:
            self.session = None
            self.show_setup(first=True)
        elif self.session is not None and self.session.initialized:
            self._show_login()
        elif len(infos) == 1:
            self.choose_profile(infos[0].id)
        else:
            self.show_profiles_list()

    def show_setup(self, first: bool) -> None:
        self.setup_page.prepare(first)
        self.stack.setCurrentWidget(self.setup_page)

    def show_profiles_list(self) -> None:
        self.profiles_page.refresh()
        self.stack.setCurrentWidget(self.profiles_page)
        self.setWindowTitle("NEXUS INTEL")

    def choose_profile(self, profile_id: str) -> None:
        if self.session is not None and self.session.unlocked:
            self.lock(show=False)
        session = guarded(self, lambda: self.profiles.session_for(profile_id))
        if session is None:
            return
        self.session = session
        self._show_login()

    def _show_login(self) -> None:
        assert self.session is not None
        self.login_page.prepare(self.session, self.profile_info())
        self.stack.setCurrentWidget(self.login_page)

    def switch_profile(self) -> None:
        """Encerra a sessão atual (apaga chaves e caches) e volta à seleção de perfis."""
        if self.session is not None and self.session.unlocked:
            self.lock(show=False)
        self.session = None
        self.show_profiles_list()

    def _after_setup(self, session: Session) -> None:
        self.session = session
        self._after_login()

    def after_profile_deleted(self) -> None:
        self._clear_private_caches()
        self.session = None
        self.manager = None
        self.idle.timer.stop()
        apply_appearance(tokens.Appearance())
        if self.projects_page is not None:
            self.projects_page.projects = []
            self.projects_page.grid.set_items([])
        if self.profiles.list():
            self.show_profiles_list()
        else:
            self.show_setup(first=True)

    def refresh_profile_ui(self) -> None:
        info = self.profile_info()
        if self.projects_page is not None and info is not None:
            self.projects_page.set_profile_name(info.display_name)

    def _after_login(self) -> None:
        assert self.session is not None
        self.manager = ProjectManager(self.session)
        if self.projects_page is None:
            self.projects_page = ProjectsPage(self.manager)
            self.projects_page.open_project.connect(self.open_project)
            self.projects_page.lock_requested.connect(self.lock)
            self.projects_page.settings_requested.connect(lambda: SettingsDialog(self).exec())
            self.projects_page.switch_profile_requested.connect(self.switch_profile)
            self.projects_page.import_requested.connect(self.import_package)
            self.stack.addWidget(self.projects_page)
        else:
            self.projects_page.manager = self.manager
        self.refresh_profile_ui()
        self.apply_prefs()
        self.idle.timer.start()
        self.show_projects()
        n = self.session.failed_before_login
        if n:
            notify(self, f"Atenção: {n} tentativa(s) de senha incorreta neste perfil desde o último acesso. "
                         "Veja o registro de segurança em Configurações.", "warning")
            self.session.failed_before_login = 0

    def export_current(self) -> None:
        from nexus_intel.ui.package_ui import export_flow

        if self.manager is not None and self.manager.current is not None and self.workspace is not None:
            export_flow(self.workspace, self.manager, self.manager.current)

    def import_package(self) -> None:
        from nexus_intel.ui.package_ui import import_flow

        pid = import_flow(self)
        if pid and self.workspace is None and self.projects_page is not None:
            self.projects_page.refresh()
        elif pid:
            notify(self, "O projeto importado aparece na lista de projetos.", "info")

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
            session = self.session
            profile = self.profile_info()
            prefs = PrefsStore(lambda: session.get_setting("ai") if session.unlocked else None,
                               lambda d: session.set_setting("ai", d) if session.unlocked else None)
            user = profile.display_name if profile else ""
            self.workspace = Workspace(store, info.name, info.color, info.path, ai_prefs=prefs, user_name=user)
        except Exception as exc:  # noqa: BLE001
            self.manager.close_current()
            show_error(self, exc)
            return
        self.workspace.back_to_projects.connect(self.show_projects)
        self.workspace.lock_requested.connect(self.lock)
        self.workspace.export_package_requested.connect(self.export_current)
        self.workspace.import_package_requested.connect(self.import_package)
        self.stack.addWidget(self.workspace)
        self.stack.setCurrentWidget(self.workspace)
        self.setWindowTitle(f"{info.name} — NEXUS INTEL")

    def _drop_workspace(self) -> None:
        if self.workspace is not None:
            self.workspace.shutdown()
            self.stack.removeWidget(self.workspace)
            self.workspace.deleteLater()
            self.workspace = None

    def _clear_private_caches(self) -> None:
        """Nada de um perfil fica visível para o próximo: imagens em cache e área de transferência."""
        QPixmapCache.clear()
        cb = QGuiApplication.clipboard()
        if cb is not None and cb.ownsClipboard():
            cb.clear()

    def lock(self, show: bool = True) -> None:
        if self.session is None or not self.session.unlocked:
            return
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QDialog) and w.isVisible():
                w.reject()
        self._drop_workspace()
        if self.manager:
            self.manager.close_current()
        self.session.lock()  # fecha projeto, banco e apaga chaves
        self.manager = None
        self._clear_private_caches()
        self.idle.timer.stop()
        apply_appearance(tokens.Appearance())
        if self.projects_page is not None:
            self.projects_page.projects = []
            self.projects_page.grid.set_items([])
        if show:
            self._show_entry()

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        try:
            if self.workspace is not None:
                self.workspace.shutdown()
            if self.manager:
                self.manager.close_current()
            if self.session is not None:
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
