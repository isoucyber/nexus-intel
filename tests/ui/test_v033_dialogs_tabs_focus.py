"""0.3.3: diálogos com cabeçalho padrão, ícones de aba que seguem o tema e foco inicial."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

pytestmark = pytest.mark.qt


@pytest.fixture(autouse=True)
def default_theme():
    from nexus_intel.ui.design import tokens
    from nexus_intel.ui.design.manager import apply_appearance

    apply_appearance(tokens.Appearance())
    yield
    apply_appearance(tokens.Appearance())


def test_form_dialogs_share_header_and_close_button(qtbot, store):
    from nexus_intel.ui.design.components import ElidedLabel, IconButton
    from nexus_intel.ui.dialogs import NewEntityDialog, SourceDialog

    for dlg in (NewEntityDialog(store), SourceDialog(store)):
        qtbot.addWidget(dlg)
        titles = [w.full_text() if hasattr(w, "full_text") else w.text() for w in dlg.findChildren(ElidedLabel)]
        assert dlg.windowTitle() in titles
        close = [b for b in dlg.findChildren(IconButton) if b.toolTip() == "Fechar"]
        assert close, "diálogo sem botão de fechar no cabeçalho"
        dlg.show()
        close[0].click()
        assert not dlg.isVisible()


def test_tab_icons_follow_theme(qtbot):
    from PySide6.QtWidgets import QTabWidget, QWidget

    from nexus_intel.ui.design import tokens
    from nexus_intel.ui.design.components import set_tab_icon
    from nexus_intel.ui.design.manager import apply_appearance

    tabs = QTabWidget()
    qtbot.addWidget(tabs)
    set_tab_icon(tabs, tabs.addTab(QWidget(), "A"), "database")
    set_tab_icon(tabs, tabs.addTab(QWidget(), "B"), "user", "person")
    before = [tabs.tabIcon(i).pixmap(16, 16).toImage() for i in range(2)]
    other = "claro" if tokens.DEFAULT_THEME != "claro" else next(k for k in tokens.THEMES if k != "claro")
    apply_appearance(tokens.Appearance(theme=other))
    after = [tabs.tabIcon(i).pixmap(16, 16).toImage() for i in range(2)]
    assert before[0] != after[0]
    assert tabs.tabBar().tabData(1) == "icon:user|person"


def test_workspace_opens_without_nav_focus_ring(qtbot, store):
    from nexus_intel.ui.workspace import Workspace

    w = Workspace(store, "Projeto", "#2dd4bf")
    qtbot.addWidget(w)
    w.resize(1366, 768)
    w.show()
    qtbot.waitUntil(lambda: w.tabs.hasFocus() or w.tabs.isAncestorOf(w.focusWidget()), timeout=2000)
    assert not any(b.hasFocus() for b in w.nav_buttons.values())
    w.shutdown()


def test_project_card_count_refreshes_on_open(manager):
    info = manager.create("Contagem")
    store = manager.open(info.id)
    store.create_entity("person", "Maria Teste")
    # simula registro desatualizado (ex.: projeto vindo de backup)
    manager.session.app_db.execute("UPDATE project_registry SET entity_count=0 WHERE id=?", (info.id,))
    manager.close_current()
    manager.session.app_db.execute("UPDATE project_registry SET entity_count=0 WHERE id=?", (info.id,))
    manager.open(info.id)
    assert manager.get(info.id).entity_count == 1
