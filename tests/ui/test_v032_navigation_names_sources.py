"""0.3.2: números clicáveis, nome obrigatório na interface e exclusão de fonte."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

pytestmark = pytest.mark.qt


@pytest.fixture
def ws(qtbot, store):
    from nexus_intel.ui.workspace import Workspace

    w = Workspace(store, "Projeto de teste", "#2dd4bf")
    qtbot.addWidget(w)
    w.resize(1366, 768)
    w.show()
    yield w
    w.shutdown()


def test_kpi_cards_navigate_by_mouse_and_keyboard(qtbot, ws, store):
    from PySide6.QtCore import Qt

    store.create_entity("person", "Alguém")
    ws.go("home")
    home = ws.pages["home"]
    for key, dest in (("entities", "entities"), ("relations", "graph"), ("claims", "quality"),
                      ("sources", "sources"), ("trashed", "trash")):
        ws.go("home")
        qtbot.mouseClick(home.kpi[key], Qt.MouseButton.LeftButton)
        assert ws.stack.currentWidget() is ws.pages[dest], key
    ws.go("home")
    home.kpi["sources"].setFocus()
    qtbot.keyClick(home.kpi["sources"], Qt.Key.Key_Return)
    assert ws.stack.currentWidget() is ws.pages["sources"]
    assert home.kpi["entities"].property("clickable") == "true"
    assert "Abrir" in home.kpi["entities"].accessibleName()


def test_type_bar_filters_entities_and_missing_targets_are_friendly(ws, store):
    store.create_entity("person", "Pessoa A")
    store.create_entity("company", "Empresa B")
    ws.go("home")
    ws.pages["home"].types.activated.emit("company")
    page = ws.pages["entities"]
    assert ws.stack.currentWidget() is page
    assert [r["display_name"] for r in page.table.model_.rows] == ["Empresa B"]
    ws._go_to("modulo-que-nao-existe")  # não quebra
    ws._go_to("entities:type:tipo_apagado")
    gone = store.create_entity("person", "Apagada")
    store.trash_entity(gone)
    store.delete_entity_permanently(gone)
    tabs = ws.tabs.count()
    ws.open_entity(gone)
    assert ws.tabs.count() == tabs  # nenhuma aba quebrada é aberta
    assert ws.window()._toast_host.toasts


@pytest.mark.parametrize("blank", ["", "   "])
def test_save_disabled_while_name_blank(qtbot, store, blank):
    from nexus_intel.ui.dialogs import NewEntityDialog, SourceDialog
    from nexus_intel.ui.projects_page import NewProjectDialog

    sd = SourceDialog(store)
    qtbot.addWidget(sd)
    assert not sd.save_btn.isEnabled()
    sd.title.setText("Certidão")
    assert sd.save_btn.isEnabled()
    sd.title.clear()
    qtbot.keyClicks(sd.title, blank or " ")
    assert not sd.save_btn.isEnabled()
    sd.accept()  # Enter no campo não salva
    assert store.list_sources() == []

    nd = NewEntityDialog(store)
    qtbot.addWidget(nd)
    assert not nd.save.isEnabled()
    nd.name.setText(blank)
    assert not nd.save.isEnabled()
    nd.name.setText("Maria")
    assert nd.save.isEnabled()

    pd = NewProjectDialog()
    qtbot.addWidget(pd)
    assert not pd.ok.isEnabled()
    pd.name.setText(blank)
    assert not pd.ok.isEnabled()


def test_entity_page_blocks_blank_rename(qtbot, store):
    from nexus_intel.ui.entity_page import EntityPage

    eid = store.create_entity("person", "Nome Original")
    page = EntityPage(store, eid)
    qtbot.addWidget(page)
    page.f_name.setText("   ")
    assert not page.save_btn.isEnabled()
    page._save()
    assert store.get_entity(eid)["display_name"] == "Nome Original"


def test_delete_source_from_list_and_dialog(qtbot, ws, store, monkeypatch):
    from nexus_intel.ui import common
    from nexus_intel.ui.dialogs import SourceDialog

    asked = []
    monkeypatch.setattr(common, "confirm", lambda _p, _t, msg, danger=False: asked.append(msg) or True)
    p = store.create_entity("person", "Bruno")
    a = store.create_source("Fonte A")
    b = store.create_source("Fonte B")
    store.add_claim(p, "profissao", "Contador", source_id=a)

    ws.go("sources")
    page = ws.pages["sources"]
    assert not page.delete_btn.isEnabled()
    row = next(i for i, r in enumerate(page.table.model_.rows) if r["id"] == a)
    page.table.selectRow(row)
    assert page.delete_btn.isEnabled()
    page._delete()
    assert "Fonte A" in asked[-1] and "1 afirmação" in asked[-1]
    assert [s["id"] for s in store.list_sources()] == [b]
    assert [r["id"] for r in page.table.model_.rows] == [b]

    dlg = SourceDialog(store, ws, source=store.get_source(b))
    qtbot.addWidget(dlg)
    dlg._delete()
    assert dlg.deleted and store.list_sources() == []
    assert "não está vinculada" in asked[-1]
