"""Percorre a interface inteira sem tela (QT_QPA_PLATFORM=offscreen), no CI."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytestqt = pytest.importorskip("pytestqt")

from tests.conftest import PASSWORD  # noqa: E402

pytestmark = pytest.mark.qt


@pytest.fixture
def win(qtbot, paths, monkeypatch):
    from nexus_intel.ui import app, auth

    monkeypatch.setattr(auth.RecoveryKeyDialog, "exec", lambda self: 1)
    monkeypatch.setattr(app, "confirm", lambda *a, **k: True)
    w = app.MainWindow(paths)
    qtbot.addWidget(w)
    w.show()
    return w


def test_full_flow(win, qtbot):
    from nexus_intel.ui.app import SettingsDialog
    from nexus_intel.ui.dialogs import ClaimDialog, NewEntityDialog, RelationDialog, SourceDialog
    from nexus_intel.ui.entity_page import EntityPage

    sp = win.setup_page
    assert win.stack.currentWidget() is sp
    sp.user.setText("arthur")
    sp.pw.setText(PASSWORD)
    sp.pw2.setText(PASSWORD)
    sp.terms.setChecked(True)
    sp._create()
    assert sp.error.text() == ""
    assert win.stack.currentWidget() is win.projects_page

    win.projects_page.refresh()
    win.projects_page._create("Exemplo", "example")
    ws = win.workspace
    assert ws is not None and win.stack.currentWidget() is ws

    for key, _ in ws.NAV:
        ws.go(key)
    graph = ws.pages["graph"]
    assert graph.view.scene().items(), "grafo vazio"

    store = ws.store
    joao = store.search("joao")[0]["id"]
    ws.open_entity(joao)
    page = ws.tabs.currentWidget()
    assert isinstance(page, EntityPage)
    assert page.claims.topLevelItemCount() > 0
    assert page.relations.topLevelItemCount() == 2
    page.f_summary.setText("resumo alterado pela interface")
    page._save()
    assert store.get_entity(joao)["summary"] == "resumo alterado pela interface"
    ws._show_in_graph(joao)
    assert graph.view.center_id == joao

    for dlg in (NewEntityDialog(store, ws, name="Teste"), ClaimDialog(store, joao, ws),
                RelationDialog(store, joao, ws), SourceDialog(store, ws)):
        dlg.close()

    ws.search.setText("Nova Pessoa · pessoa")
    ws.search._create()
    assert store.search("nova pessoa")

    ws.pages["quality"]._scan()
    s = SettingsDialog(win)
    s.theme.setCurrentIndex(s.theme.findData("claro"))
    s.accept()
    assert win.appearance().theme == "claro"
    from nexus_intel.ui.design import tokens

    assert tokens.current().key == "claro"

    win.lock()
    assert not win.session.unlocked
    assert win.stack.currentWidget() is win.login_page
    lp = win.login_page
    lp.pw.setText("senha-errada-qualquer")
    lp._login()
    assert lp.error.text()
    win.session.vault._clock = lambda: 1e12  # pula o atraso no teste
    lp.go.setEnabled(True)
    lp.pw.setText(PASSWORD)
    lp._login()
    assert win.session.unlocked
    assert win.stack.currentWidget() is win.projects_page


def test_gallery_renders_every_theme(qtbot):
    from nexus_intel.ui.design import tokens
    from nexus_intel.ui.design.gallery import Gallery

    for theme in tokens.THEMES:
        g = Gallery(theme)
        qtbot.addWidget(g)
        g.resize(1200, 800)
        g.show()
        assert not g.grab().isNull()
        assert tokens.current().key == theme
