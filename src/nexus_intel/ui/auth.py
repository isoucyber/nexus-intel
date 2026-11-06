"""Telas de primeiro uso, login, recuperação e troca de senha (seção 6.1)."""

from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from nexus_intel.application.session import Session
from nexus_intel.domain.errors import NexusError, ThrottledError
from nexus_intel.infrastructure.crypto.vault import check_password_strength
from nexus_intel.ui.common import Page, button, card, hbox, label, show_error

TERMS = (
    "O NEXUS INTEL organiza informações que você obteve de forma legítima. Ele não é "
    "ferramenta de coleta de dados sobre pessoas e não deve ser usado para vigilância, "
    "perseguição, invasão de contas ou qualquer finalidade ilegal. Ao tratar dados de "
    "pessoas, você é responsável por cumprir a LGPD (finalidade, base legal, segurança e "
    "direitos do titular)."
)


def _password(placeholder: str) -> QLineEdit:
    e = QLineEdit()
    e.setEchoMode(QLineEdit.EchoMode.Password)
    e.setPlaceholderText(placeholder)
    return e


def _busy(fn):  # type: ignore[no-untyped-def]
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        return fn()
    finally:
        QApplication.restoreOverrideCursor()


class RecoveryKeyDialog(QDialog):
    """Mostra a chave uma única vez e exige confirmação de que foi anotada."""

    def __init__(self, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sua chave de recuperação")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.addWidget(label("Guarde esta chave de recuperação", "H2"))
        lay.addWidget(label(
            "Ela é a ÚNICA forma de abrir seus dados se você esquecer a senha. Ela não será "
            "mostrada de novo. Anote em papel ou guarde num gerenciador de senhas, longe deste "
            "computador.", "Muted", wrap=True))
        box = QPlainTextEdit(key)
        box.setReadOnly(True)
        box.setFixedHeight(70)
        box.setStyleSheet("font-family: Consolas, 'JetBrains Mono', monospace; font-size: 16px;")
        lay.addWidget(box)
        copy = button("Copiar", lambda: QGuiApplication.clipboard().setText(key))
        lay.addWidget(hbox(copy, None))
        self.ack = QCheckBox("Anotei a chave em um lugar seguro")
        lay.addWidget(self.ack)
        self.ok = button("Continuar", self.accept, "Primary")
        self.ok.setEnabled(False)
        self.ack.toggled.connect(self.ok.setEnabled)
        lay.addWidget(hbox(None, self.ok))

    def reject(self) -> None:  # não deixa fechar sem confirmar
        if self.ack.isChecked():
            super().reject()


class SetupPage(Page):
    done = Signal()

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session
        self.user = QLineEdit()
        self.user.setPlaceholderText("ex.: arthur")
        self.pw = _password("mínimo de 12 caracteres")
        self.pw2 = _password("repita a senha")
        self.encrypt = QCheckBox("Cifrar todos os dados (recomendado)")
        self.encrypt.setChecked(Session.encryption_supported())
        self.encrypt.setEnabled(Session.encryption_supported())
        self.terms = QCheckBox("Li e aceito o termo de uso responsável")
        self.error = label("", "Danger", wrap=True)
        self.strength = label("", "Muted")
        self.pw.textChanged.connect(self._strength)

        form = QFormLayout()
        form.addRow("Usuário", self.user)
        form.addRow("Senha", self.pw)
        form.addRow("", self.strength)
        form.addRow("Confirmar senha", self.pw2)
        holder = QWidget()
        holder.setLayout(form)

        warn = "" if Session.encryption_supported() else (
            "Atenção: o componente de criptografia (SQLCipher) não foi encontrado nesta "
            "instalação. Os dados ficarão sem cifragem; use a criptografia do disco (BitLocker)."
        )
        create = button("Criar usuário", self._create, "Primary")
        self.pw2.returnPressed.connect(self._create)
        body = card(
            label("NEXUS INTEL", "Brand"),
            label("Bem-vindo. Vamos criar seu usuário local.", "H2"),
            label("Tudo fica neste computador. Nenhuma conta online é necessária.", "Muted", wrap=True),
            holder, self.encrypt, label(warn, "Warning", wrap=True),
            label(TERMS, "Muted", wrap=True), self.terms, self.error, hbox(None, create),
        )
        body.setFixedWidth(560)
        self.layout_.addStretch(1)
        self.layout_.addWidget(hbox(None, body, None))
        self.layout_.addStretch(1)

    def _strength(self, text: str) -> None:
        classes = sum(any(f(c) for c in text) for f in (str.islower, str.isupper, str.isdigit,
                                                        lambda c: not c.isalnum()))
        if len(text) < 12:
            msg = f"{len(text)}/12 caracteres"
        elif len(text) >= 16 and classes >= 3:
            msg = "forte"
        else:
            msg = "aceitável — frases longas são mais fortes"
        self.strength.setText(msg)

    def _create(self) -> None:
        self.error.setText("")
        if self.pw.text() != self.pw2.text():
            self.error.setText("As senhas não coincidem.")
            return
        if not self.terms.isChecked():
            self.error.setText("É preciso aceitar o termo de uso responsável.")
            return
        try:
            check_password_strength(self.pw.text(), self.user.text())
            key = _busy(lambda: self.session.setup(self.user.text(), self.pw.text(),
                                                   encrypt=self.encrypt.isChecked()))
        except NexusError as exc:
            self.error.setText(exc.user_message)
            return
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc)
            return
        self.session.set_setting("terms_accepted_at", datetime.now(UTC).isoformat(timespec="seconds"))
        RecoveryKeyDialog(key, self).exec()
        self.pw.clear()
        self.pw2.clear()
        self.done.emit()


class LoginPage(Page):
    done = Signal()

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session
        self.user = QLineEdit()
        self.pw = _password("senha")
        self.recovery = QLineEdit()
        self.recovery.setPlaceholderText("XXXX-XXXX-…  (52 caracteres)")
        self.recovery.hide()
        self.error = label("", "Danger", wrap=True)
        self.title = label("Entrar", "H2")
        self.go = button("Entrar", self._login, "Primary")
        self.toggle = button("Esqueci a senha", self._toggle)
        self.pw.returnPressed.connect(self._login)
        self.recovery.returnPressed.connect(self._login)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        form = QFormLayout()
        form.addRow("Usuário", self.user)
        form.addRow("Senha", self.pw)
        holder = QWidget()
        holder.setLayout(form)
        self.form_holder = holder
        self.recovery_hint = label(
            "Digite a chave de recuperação que você anotou ao criar o usuário. Depois de "
            "entrar, você vai definir uma nova senha.", "Muted", wrap=True)
        self.recovery_hint.hide()
        body = card(label("NEXUS INTEL", "Brand"), self.title, holder, self.recovery_hint,
                    self.recovery, self.error, hbox(self.toggle, None, self.go))
        body.setFixedWidth(440)
        self.layout_.addStretch(1)
        self.layout_.addWidget(hbox(None, body, None))
        self.layout_.addStretch(1)

    def prepare(self) -> None:
        self.user.setText(self.session.vault.username() if self.session.initialized else "")
        self.pw.clear()
        self.recovery.clear()
        self.error.setText("")
        (self.pw if self.user.text() else self.user).setFocus()
        self._tick()

    def _toggle(self) -> None:
        rec = self.recovery.isHidden()
        self.recovery.setVisible(rec)
        self.recovery_hint.setVisible(rec)
        self.form_holder.setVisible(not rec)
        self.title.setText("Entrar com a chave de recuperação" if rec else "Entrar")
        self.toggle.setText("Voltar para senha" if rec else "Esqueci a senha")
        self.error.setText("")

    def _tick(self) -> None:
        wait = self.session.vault.seconds_until_allowed() if self.session.initialized else 0
        if wait > 0:
            self.go.setEnabled(False)
            self.error.setText(f"Muitas tentativas incorretas. Aguarde {int(wait) + 1} s.")
            if not self._timer.isActive():
                self._timer.start(500)
        else:
            self._timer.stop()
            if not self.go.isEnabled():
                self.error.setText("")
            self.go.setEnabled(True)

    def _login(self) -> None:
        if not self.go.isEnabled():
            return
        self.error.setText("")
        try:
            if self.recovery.isVisible():
                _busy(lambda: self.session.login_with_recovery(self.recovery.text()))
            else:
                _busy(lambda: self.session.login(self.user.text(), self.pw.text()))
        except ThrottledError as exc:
            self.error.setText(exc.user_message)
            self._tick()
            return
        except NexusError as exc:
            self.error.setText(exc.user_message)
            self._tick()
            return
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc)
            return
        self.pw.clear()
        self.recovery.clear()
        if self.session.must_change_password:
            dlg = ChangePasswordDialog(self.session, self, require_current=False)
            dlg.exec()
            if self.session.must_change_password:  # recusou: volta a bloquear
                self.session.lock()
                self.error.setText("É preciso definir uma nova senha para continuar.")
                return
        if self.recovery.isVisible():
            self._toggle()
        self.done.emit()


class ChangePasswordDialog(QDialog):
    def __init__(self, session: Session, parent: QWidget | None = None, require_current: bool = True) -> None:
        super().__init__(parent)
        self.session = session
        self.require_current = require_current
        self.setWindowTitle("Definir nova senha" if not require_current else "Trocar senha")
        self.setMinimumWidth(420)
        self.current = _password("senha atual")
        self.new = _password("nova senha (mín. 12)")
        self.new2 = _password("repita a nova senha")
        self.error = label("", "Danger", wrap=True)
        form = QFormLayout(self)
        if require_current:
            form.addRow("Senha atual", self.current)
        form.addRow("Nova senha", self.new)
        form.addRow("Confirmar", self.new2)
        form.addRow(self.error)
        form.addRow(hbox(None, button("Cancelar", self.reject), button("Salvar", self._save, "Primary")))

    def _save(self) -> None:
        if self.new.text() != self.new2.text():
            self.error.setText("As senhas não coincidem.")
            return
        try:
            if self.require_current:
                _busy(lambda: self.session.change_password(self.current.text(), self.new.text()))
            else:
                _busy(lambda: self.session.set_new_password(self.new.text()))
        except NexusError as exc:
            self.error.setText(exc.user_message)
            return
        self.accept()
