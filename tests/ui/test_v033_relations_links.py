"""0.3.3: cortar relação (ficha, grafo, lixeira) e links abrindo no navegador."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

pytestmark = pytest.mark.qt


@pytest.fixture
def opened(monkeypatch):
    """Registra os links abertos em vez de chamar o navegador de verdade."""
    from PySide6.QtGui import QDesktopServices

    calls: list[str] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda q: calls.append(q.toString()) or True))
    return calls


@pytest.fixture
def yes(monkeypatch):
    from nexus_intel.ui import common, workspace

    asked: list[str] = []
    fake = lambda _p, _t, msg, danger=False: asked.append(msg) or True  # noqa: E731
    monkeypatch.setattr(common, "confirm", fake)
    monkeypatch.setattr(workspace, "confirm", fake)  # a Lixeira importa confirm diretamente
    return asked


@pytest.fixture
def ws(qtbot, store):
    from nexus_intel.ui.workspace import Workspace

    w = Workspace(store, "Projeto", "#2dd4bf")
    qtbot.addWidget(w)
    w.resize(1366, 768)
    w.show()
    yield w
    w.shutdown()


def test_open_external_link_validates(qtbot, opened):
    from PySide6.QtWidgets import QWidget

    from nexus_intel.ui.links import open_external_link

    host = QWidget()
    qtbot.addWidget(host)
    host.show()
    assert open_external_link("exemplo.com/a", host)
    assert opened == ["https://exemplo.com/a"]
    assert not open_external_link("javascript:alert(1)", host)
    assert not open_external_link("file:///C:/Windows", host)
    assert opened == ["https://exemplo.com/a"]  # nada além do link válido foi aberto
    assert host._toast_host.toasts  # aviso amigável


def test_cut_from_entity_page_keeps_entities(qtbot, store, yes):
    from nexus_intel.ui.entity_page import EntityPage

    a = store.create_entity("person", "Helena")
    b = store.create_entity("company", "Aurora")
    rid = store.create_relation("works_at", a, b)
    page = EntityPage(store, a)
    qtbot.addWidget(page)
    page.show()
    assert not page.cut_btn.isEnabled()
    page.relations.setCurrentItem(page.relations.topLevelItem(0))
    assert page.cut_btn.isEnabled()
    page._cut_selected()
    assert "Helena trabalha em Aurora" in yes[-1] and "não são apagadas" in yes[-1]
    assert page.relations.topLevelItemCount() == 0
    assert store.get_entity(b)["record_status"] == "active"
    assert store.list_trashed_relations()[0]["id"] == rid


def test_graph_edge_select_details_and_cut_in_place(qtbot, ws, store, yes):
    from nexus_intel.ui.graph_view import EdgeItem, NodeItem

    a = store.create_entity("person", "Helena")
    b = store.create_entity("company", "Aurora")
    c = store.create_entity("location", "Veneza")
    src = store.create_source("Ficha", url="https://exemplo.com/ficha")
    rid = store.create_relation("works_at", a, b, evidence_source=src)
    store.create_relation("located_in", b, c)
    ws.go("graph")
    graph = ws.pages["graph"]
    scene = graph.view.scene()
    pos_before = {i.data_["id"]: i.pos() for i in scene.items() if isinstance(i, NodeItem)}
    edge = next(i for i in scene.items() if isinstance(i, EdgeItem) and i.data_["id"] == rid)

    edge.setSelected(True)
    assert graph.edge_panel.isVisible()
    assert "Helena trabalha em Aurora" in graph.edge_text.text()
    assert 'href="https://exemplo.com/ficha"' in graph.edge_text.text()

    graph.cut_edge(edge)
    edges = [i for i in scene.items() if isinstance(i, EdgeItem)]
    assert [e.data_["id"] for e in edges] != [] and rid not in [e.data_["id"] for e in edges]
    pos_after = {i.data_["id"]: i.pos() for i in scene.items() if isinstance(i, NodeItem)}
    assert pos_after == pos_before  # nós no mesmo lugar, grafo não reconstruído
    assert store.list_trashed_relations()[0]["id"] == rid


def test_trash_relations_tab_restore_and_purge(ws, store, yes):
    a = store.create_entity("person", "Helena")
    b = store.create_entity("company", "Aurora")
    r1 = store.create_relation("works_at", a, b)
    r2 = store.create_relation("knows", a, b)
    store.cut_relation(r1)
    store.cut_relation(r2)
    ws.go("trash")
    trash = ws.pages["trash"]
    assert trash.tabs.tabText(1) == "Relações (2)"
    trash.tabs.setCurrentIndex(1)
    row = next(i for i, r in enumerate(trash.rel_table.model_.rows) if r["id"] == r1)
    trash.rel_table.selectRow(row)
    trash._restore()
    assert [r["id"] for r in store.relations_for(a)] == [r1]
    trash.rel_table.selectRow(0)
    trash._purge()
    assert store.list_trashed_relations() == []
    assert store.get_entity(a) and store.get_entity(b)


def test_source_list_and_claim_links_open_on_click(qtbot, ws, store, opened):
    from PySide6.QtCore import Qt

    from nexus_intel.ui.entity_page import EntityPage

    store.create_source("Reportagem", url="https://jornal.example/materia")
    ws.go("sources")
    table = ws.pages["sources"].table
    col = [c.key for c in table.model_.columns].index("url")
    table.link_clicked.emit(table._link_at(table.model_.index(0, col)))
    assert opened == ["https://jornal.example/materia"]

    e = store.create_entity("company", "Aurora")
    store.add_claim(e, "site", "aurora.example")
    page = EntityPage(store, e)
    qtbot.addWidget(page)
    item = page.claims.topLevelItem(0).child(0)
    assert page._url_of(item) == "https://aurora.example"
    page._claim_clicked(item, 0)
    assert opened[-1] == "https://aurora.example"
    assert item.foreground(0).color().name() != "#000000"
    assert Qt.ItemDataRole.UserRole  # sanidade
