"""Critérios de aceitação F1/F2 da 0.3: cards de projetos e tela inicial."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

pytestmark = pytest.mark.qt

# largura da janela → colunas aceitas (seção 4.2 do pedido)
EXPECTED = {1024: {3}, 1366: {4}, 1920: {5, 6}, 2560: {7, 8}, 700: {1, 2}}


def _page(qtbot, manager):
    from PySide6.QtCore import Qt

    from nexus_intel.ui.projects_page import ProjectsPage

    page = ProjectsPage(manager)
    page.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)  # qualquer tamanho, sem tela
    qtbot.addWidget(page)
    page.show()
    return page


def _sized(qtbot, page, w, h=900):
    page.resize(w, h)
    qtbot.wait(20)
    page.grid.relayout()
    return page.grid


def _cards(page):
    return [c for c in page.grid.items if c.isVisible()]


def test_columns_and_card_size_per_resolution(qtbot, manager):
    for i in range(12):
        manager.create(f"Projeto {i:02d} com um nome razoavelmente comprido para testar")
    page = _page(qtbot, manager)
    page.refresh()
    for width, expected in EXPECTED.items():
        grid = _sized(qtbot, page, width)
        assert grid.columns in expected, (width, grid.columns)
        heights = {c.height() for c in _cards(page)}
        assert len(heights) == 1 and 150 <= heights.pop() <= 190, width
        for c in _cards(page):
            assert 1 <= c.width() <= 340
        print(f"{width}px: {grid.columns} colunas, card {c.width()}x{c.height()}")


def test_single_project_keeps_standard_size(qtbot, manager):
    manager.create("Único")
    page = _page(qtbot, manager)
    page.refresh()
    _sized(qtbot, page, 1366, 1000)
    (card,) = _cards(page)
    assert card.height() <= 190
    assert card.width() == page.grid.item_width(page.grid.width())
    assert page.grid.height() == card.height()  # a grade não estica para a janela


def test_fifty_projects_scroll_without_growing(qtbot, manager):
    for i in range(50):
        manager.create(f"P{i:02d}")
    page = _page(qtbot, manager)
    page.refresh()
    grid = _sized(qtbot, page, 1366, 768)
    assert len(_cards(page)) == 50
    assert grid.height() > page.scroll.viewport().height()
    assert page.scroll.verticalScrollBar().maximum() > 0
    assert len({c.height() for c in _cards(page)}) == 1
    assert page.count.accessibleName() == "50"


def test_states_open_delete_and_search(qtbot, manager, monkeypatch):
    from nexus_intel.ui import projects_page

    page = _page(qtbot, manager)
    assert page.stack.currentIndex() == 0  # carregando antes da primeira leitura
    page.refresh()
    assert page.stack.currentWidget() is page.empty

    a = manager.create("Operação Alfa")
    manager.create("Operação Beta")
    page.refresh()
    assert page.stack.currentWidget() is page.scroll

    opened = []
    page.open_project.connect(opened.append)
    card = next(c for c in _cards(page) if c.project.id == a.id)
    card.open_btn.click()
    assert opened == [a.id]

    page.search.setText("beta")
    assert [c.project.name for c in _cards(page)] == ["Operação Beta"]
    page.search.setText("zzz")
    assert page.stack.currentWidget() is page.no_results
    page.search.clear()

    monkeypatch.setattr(projects_page, "confirm", lambda *a, **k: True)
    page._delete(a)
    assert [p.name for p in manager.list()] == ["Operação Beta"]

    def boom():
        raise RuntimeError("falha simulada no teste")

    monkeypatch.setattr(manager, "list", boom)
    page.refresh()
    assert page.stack.currentWidget() is page.error
