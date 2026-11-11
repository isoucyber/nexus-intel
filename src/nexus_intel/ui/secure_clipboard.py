"""Cópia de segredos (chave de recuperação) para a área de transferência, com limpeza.

- Pede ao Windows para NÃO guardar o conteúdo no Histórico da área de
  transferência (Win+V) nem sincronizar com a nuvem, e para monitores de
  clipboard ignorarem o conteúdo (formatos documentados pela Microsoft:
  ExcludeClipboardContentFromMonitorProcessing, CanIncludeInClipboardHistory = 0,
  CanUploadToCloudClipboard = 0).
- Apaga a área de transferência depois de `seconds`, se ela ainda contiver o
  segredo, e também ao bloquear ou trocar de perfil.

Limite: outro programa em execução pode ler a área de transferência enquanto o
segredo estiver lá. Por isso a cópia é opcional e temporária.
"""

from __future__ import annotations

from PySide6.QtCore import QMimeData, QTimer
from PySide6.QtGui import QGuiApplication

CLEAR_AFTER_SECONDS = 60
_WIN = 'application/x-qt-windows-mime;value="{}"'
_ZERO_DWORD = b"\x00\x00\x00\x00"


def copy_secret(secret: str, seconds: int = CLEAR_AFTER_SECONDS) -> None:
    cb = QGuiApplication.clipboard()
    if cb is None:
        return
    data = QMimeData()
    data.setText(secret)
    data.setData(_WIN.format("ExcludeClipboardContentFromMonitorProcessing"), b"\x01\x00\x00\x00")
    data.setData(_WIN.format("CanIncludeInClipboardHistory"), _ZERO_DWORD)
    data.setData(_WIN.format("CanUploadToCloudClipboard"), _ZERO_DWORD)
    cb.setMimeData(data)

    def clear() -> None:
        board = QGuiApplication.clipboard()
        if board is not None and board.text() == secret:
            board.clear()

    QTimer.singleShot(seconds * 1000, clear)
