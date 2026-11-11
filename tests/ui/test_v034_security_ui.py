"""Hardening da interface: dado não confiável nunca vira HTML, segredo sai da área de transferência,
operações sensíveis pedem a senha de novo."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

pytestmark = pytest.mark.qt

EVIL = "<img src='file:///C:/Windows/win.ini'><a href='https://x.invalid'>Verificado</a><b>x</b>"


def test_user_text_is_never_rendered_as_html(qtbot, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    from nexus_intel.ui import common
    from nexus_intel.ui.design.components import ElidedLabel, safe_tooltip, text

    for widget in (text(EVIL), common.label(EVIL, "H2"), ElidedLabel(EVIL, "h3")):
        qtbot.addWidget(widget)
        assert widget.textFormat() == Qt.TextFormat.PlainText
    tip = safe_tooltip(EVIL)
    assert "<img" not in tip and "&lt;img" in tip
    assert safe_tooltip("texto normal") == "texto normal"

    seen = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: seen.append(self.textFormat()) or 0)
    common.confirm(None, "Título", EVIL)
    assert seen == [Qt.TextFormat.PlainText]


def test_imported_names_are_plain_in_workspace(qtbot, store):
    from PySide6.QtCore import Qt

    from nexus_intel.ui.graph_view import NodeItem
    from nexus_intel.ui.workspace import Workspace

    eid = store.create_entity("person", EVIL)
    other = store.create_entity("person", "Outra")
    store.create_relation("knows", eid, other)
    ws = Workspace(store, EVIL, "#2dd4bf")
    qtbot.addWidget(ws)
    ws.show()
    ws.open_entity(eid)
    page = ws.tabs.currentWidget()
    assert page.title.textFormat() == Qt.TextFormat.PlainText
    assert "<img" not in ws.tabs.tabToolTip(ws.tabs.currentIndex())
    ws.go("graph")
    node = next(i for i in ws.pages["graph"].view.scene().items() if isinstance(i, NodeItem)
                and i.data_["id"] == eid)
    assert "<img" not in node.toolTip()
    ws.shutdown()


def test_recovery_key_copy_is_cleared(qtbot):
    from PySide6.QtGui import QGuiApplication

    from nexus_intel.ui.secure_clipboard import copy_secret

    cb = QGuiApplication.clipboard()
    copy_secret("ABCD-EFGH-SEGREDO", seconds=0)
    md = cb.mimeData()
    if md is None or md.text() != "ABCD-EFGH-SEGREDO":
        pytest.skip("área de transferência indisponível nesta plataforma de teste")
    qtbot.waitUntil(lambda: cb.text() != "ABCD-EFGH-SEGREDO", timeout=2000)


def test_export_asks_password_again_when_session_is_old(qtbot, manager, store, tmp_path, monkeypatch):
    from nexus_intel.ui import auth, package_ui

    manager.session._auth_at = manager.session._clock() - 10_000
    asked = []
    monkeypatch.setattr(auth.ReauthDialog, "exec", lambda self: asked.append(1) or 0)
    dlg = package_ui.ExportDialog(manager, store)
    qtbot.addWidget(dlg)
    dlg.dest.setText(str(tmp_path / "x"))
    dlg.pw.setText("senha-do-arquivo-123")
    dlg.pw2.setText("senha-do-arquivo-123")
    dlg._export()
    assert asked and dlg.result_path is None and not (tmp_path / "x.nexus").exists()
