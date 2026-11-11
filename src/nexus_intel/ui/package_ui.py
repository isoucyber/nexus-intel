"""Telas de exportação e importação de projetos .nexus (0.3.4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QLineEdit, QWidget

from nexus_intel.application.project_store import ProjectStore
from nexus_intel.application.projects import ProjectManager
from nexus_intel.application.sharing import (
    EXTENSION,
    PackagePreview,
    export_project,
    import_package,
    preview_package,
)
from nexus_intel.domain.errors import NexusError
from nexus_intel.infrastructure.crypto.keys import KdfParams
from nexus_intel.infrastructure.crypto.vault import MIN_PASSWORD_LEN
from nexus_intel.ui import format as fmt
from nexus_intel.ui.common import button, hbox, label, show_error
from nexus_intel.ui.design.components import dialog_form, notify

FILTER = f"Projeto NEXUS (*{EXTENSION})"


def _busy(fn):  # type: ignore[no-untyped-def]
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        return fn()
    finally:
        QApplication.restoreOverrideCursor()


def _pw(placeholder: str) -> QLineEdit:
    e = QLineEdit()
    e.setEchoMode(QLineEdit.EchoMode.Password)
    e.setPlaceholderText(placeholder)
    return e


def _size(n: int) -> str:
    return f"{fmt.number(round(n / 1024 / 1024, 1))} MB" if n >= 1024 * 1024 else f"{fmt.number(n // 1024)} KB"


# =================================================================== exportar
class ExportDialog(QDialog):
    def __init__(self, manager: ProjectManager, store: ProjectStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.store = store
        self.result_path: Path | None = None
        info = manager.get(store.project_id)
        self.dest = QLineEdit(str(Path.home() / f"{_safe_name(info.name)}{EXTENSION}"))
        self.pw = _pw(f"Senha do arquivo (mín. {MIN_PASSWORD_LEN} caracteres)")
        self.pw2 = _pw("Confirme a senha")
        self.error = label("", "Danger", wrap=True)
        form = dialog_form(self, "Exportar projeto (.nexus)", 540)
        form.addRow(label(
            "O arquivo leva entidades, relações, fontes, linha do tempo, notas e todas as fotografias. Ele é "
            "cifrado com AES-256-GCM pela senha abaixo e assinado digitalmente pelo seu perfil. Envie a senha "
            "por um canal diferente do arquivo.", "Muted", wrap=True))
        form.addRow("Salvar em", hbox(self.dest, button("Escolher…", self._choose)))
        form.addRow("Senha", self.pw)
        form.addRow("Confirmar", self.pw2)
        form.addRow(self.error)
        self.ok = button("Exportar", self._export, "Primary", icon="download")
        form.addRow(hbox(None, button("Cancelar", self.reject), self.ok))

    def _choose(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Salvar projeto", self.dest.text(), FILTER)
        if path:
            self.dest.setText(path)

    def _export(self) -> None:
        self.error.setText("")
        if self.pw.text() != self.pw2.text():
            self.error.setText("As senhas não coincidem.")
            return
        if len(self.pw.text()) < MIN_PASSWORD_LEN:
            self.error.setText(f"A senha precisa ter pelo menos {MIN_PASSWORD_LEN} caracteres.")
            return
        dest = Path(self.dest.text().strip())
        if dest.suffix.lower() != EXTENSION:
            dest = dest.with_suffix(EXTENSION)
        kdf = getattr(self.manager.session, "_kdf_override", None) or KdfParams()
        try:
            res = _busy(lambda: export_project(self.manager, self.store, dest, self.pw.text(), kdf))
        except NexusError as exc:
            self.error.setText(exc.user_message)
            return
        except OSError:
            self.error.setText("Não foi possível gravar nesse local. Escolha outra pasta.")
            return
        self.pw.clear()
        self.pw2.clear()
        self.result_path = res.path
        notify(self.parentWidget() or self, f"Projeto exportado: {res.path.name} ({_size(res.size)}, "
               f"{res.files} arquivo(s)). Pasta: {res.path.parent}", "success")
        self.accept()


def _safe_name(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()
    return keep[:80] or "projeto"


def export_flow(parent: QWidget, manager: ProjectManager, store: ProjectStore) -> Path | None:
    dlg = ExportDialog(manager, store, parent)
    return dlg.result_path if dlg.exec() else None


# =================================================================== importar
class PasswordDialog(QDialog):
    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.pw = _pw("Senha recebida com o arquivo")
        self.error = label("", "Danger", wrap=True)
        form = dialog_form(self, "Abrir arquivo .nexus", 460)
        form.addRow(label(f"Arquivo: {path.name}", "Muted", wrap=True))
        form.addRow("Senha", self.pw)
        form.addRow(self.error)
        self.ok = button("Verificar", self.accept, "Primary", icon="shield-check")
        self.pw.returnPressed.connect(self.accept)
        form.addRow(hbox(None, button("Cancelar", self.reject), self.ok))


class PreviewDialog(QDialog):
    """Pré-visualização: o pacote já foi decifrado e verificado; nada foi gravado ainda."""

    def __init__(self, pv: PackagePreview, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        c = pv.counts
        form = dialog_form(self, "Importar projeto", 540)
        form.addRow(label("Arquivo íntegro: senha correta, conteúdo e assinatura verificados.", "Success", wrap=True))
        form.addRow("Projeto", label(pv.name, "H3"))
        form.addRow("Exportado em", label(f"{fmt.absolute(pv.exported_at)} · NEXUS {pv.app_version}", "Muted"))
        form.addRow("Conteúdo", label(
            f"{c.get('entities', 0)} entidades · {c.get('relations', 0)} relações · {c.get('sources', 0)} fontes · "
            f"{c.get('claims', 0)} atributos · {c.get('notes', 0)} notas", "Muted", wrap=True))
        form.addRow("Fotografias", label(f"{c.get('photos', 0)} vínculos · {pv.files} arquivos "
                                         f"({_size(pv.files_bytes)})", "Muted"))
        who = "você (este perfil)" if pv.signed_by_me else "outro perfil"
        form.addRow("Assinado por", label(f"{who}\n{pv.signer_fingerprint}", "Muted", wrap=True))
        if not pv.signed_by_me:
            form.addRow(label("Confira essa impressão digital com quem enviou o arquivo (por telefone, por "
                              "exemplo) para ter certeza de quem o criou.", "Muted", wrap=True))
        for note in pv.notes:
            form.addRow(label(note, "Warning", wrap=True))
        self.ok = button("Importar", self.accept, "Primary", icon="download")
        form.addRow(hbox(None, button("Cancelar", self.reject), self.ok))


def import_flow(win: Any, path: str | None = None) -> str | None:
    """Escolher arquivo → senha → pré-visualização verificada → importar. Devolve o ID do projeto."""
    manager: ProjectManager | None = getattr(win, "manager", None)
    if manager is None:
        return None
    if path is None:
        path, _ = QFileDialog.getOpenFileName(win, "Importar projeto", str(Path.home()), FILTER)
        if not path:
            return None
    file = Path(path)
    pw_dlg = PasswordDialog(file, win)
    while True:
        if not pw_dlg.exec():
            return None
        password = pw_dlg.pw.text()
        try:
            pv = _busy(lambda: preview_package(manager, file, password))
            break
        except NexusError as exc:
            pw_dlg.error.setText(exc.user_message)
            pw_dlg.pw.selectAll()
        except OSError:
            pw_dlg.error.setText("Não foi possível ler o arquivo.")
    if not PreviewDialog(pv, win).exec():
        return None
    try:
        info = _busy(lambda: import_package(manager, file, password))
    except Exception as exc:  # noqa: BLE001
        show_error(win, exc)
        return None
    notify(win, f"Projeto “{info.name}” importado com {pv.files} fotografia(s).", "success")
    return info.id
