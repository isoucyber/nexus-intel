"""Componentes do design system e fluxos críticos pela interface (rodam sem tela no CI)."""

from __future__ import annotations

import time

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

pytestmark = pytest.mark.qt


@pytest.fixture(autouse=True)
def default_theme(qapp):
    from nexus_intel.ui.design import tokens
    from nexus_intel.ui.design.manager import apply_appearance

    apply_appearance(tokens.Appearance())
    yield
    apply_appearance(tokens.Appearance())


def test_fonts_and_icons_load():
    from nexus_intel.ui.design import assets

    fams = assets.load_fonts()
    assert fams["ui"] == "Inter" and fams["mono"] == "JetBrains Mono"
    missing = [n for n in {*assets.NAV_ICONS.values(), *assets.TYPE_ICONS.values(), *assets.STATUS_ICONS.values()}
               if not (assets.ICON_DIR / f"{n}.svg").exists()]
    assert missing == []
    assert not assets.pixmap("search", "#ffffff", 16).isNull()  # noqa: S105


def test_live_theme_switch_updates_stylesheet_and_widgets(qtbot):
    from PySide6.QtWidgets import QApplication

    from nexus_intel.ui.design import tokens
    from nexus_intel.ui.design.components import BarList, BarRow, Button, StatusBadge
    from nexus_intel.ui.design.manager import apply_appearance

    b = Button("Salvar", "primary", "check")
    chip = StatusBadge("verified")
    bars = BarList([BarRow("person", "Pessoa", 3, lambda t: t.type_color("person"))])
    for w in (b, chip, bars):
        qtbot.addWidget(w)
        w.show()
    dark_qss = QApplication.instance().styleSheet()
    apply_appearance(tokens.Appearance(theme="claro", accent="#7c3aed", density="compacta"))
    assert tokens.current().key == "claro"
    assert QApplication.instance().styleSheet() != dark_qss
    assert tokens.current().accent in QApplication.instance().styleSheet()
    for w in (b, chip, bars):
        assert not w.grab().isNull()


def test_data_table_handles_ten_thousand_rows_lazily(qtbot):
    from nexus_intel.ui.design.table import Column, DataTable

    rows = [{"id": str(i), "display_name": f"Entidade {i:05d}", "type_key": "person",
             "updated_at": "2026-01-01T00:00:00+00:00"} for i in range(10_000)]
    calls = []

    def fetch(offset: int, limit: int):
        calls.append(offset)
        return rows[offset:offset + limit]

    table = DataTable([Column("display_name", "Nome", "entity", stretch=True),
                       Column("updated_at", "Atualizada", "reltime", width=100)], page_size=500)
    qtbot.addWidget(table)
    table.resize(800, 600)
    table.show()
    start = time.perf_counter()
    table.load(fetch)
    assert table.row_count() == 500 and calls == [0]
    while table.model_.canFetchMore():
        table.model_.fetchMore()
    table.scrollToBottom()
    qtbot.wait(10)
    assert table.row_count() == 10_000
    assert time.perf_counter() - start < 5
    activated = []
    table.row_activated.connect(activated.append)
    table.selectRow(9_999)
    table.row_activated.emit(table.current_row())
    assert activated[0]["id"] == "9999"


def test_elided_label_shows_full_text_in_tooltip(qtbot):
    from nexus_intel.ui.design.components import ElidedLabel

    lb = ElidedLabel("Um nome de empresa realmente muito comprido para caber aqui")
    qtbot.addWidget(lb)
    lb.resize(80, 24)
    lb.show()
    qtbot.wait(5)
    assert lb.toolTip() == lb.full_text()
    lb.resize(2000, 24)
    qtbot.wait(5)
    assert lb.toolTip() == ""


def test_toast_drawer_modal_and_reduced_motion(qtbot):
    from PySide6.QtWidgets import QWidget

    from nexus_intel.ui.design import tokens
    from nexus_intel.ui.design.components import Drawer, Modal, notify
    from nexus_intel.ui.design.manager import apply_appearance

    apply_appearance(tokens.Appearance(motion="desligadas"))
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(900, 600)
    host.show()
    toast = notify(host, "Entidade criada.", "success")
    assert toast is not None and toast.isVisible()
    toast.dismiss()
    qtbot.waitUntil(lambda: not host._toast_host.toasts, timeout=1000)

    drawer = Drawer(host, "Detalhes")
    drawer.open_drawer()
    assert drawer.isVisible() and drawer.geometry().right() == host.width() - 1
    drawer.close_drawer()
    assert not drawer.isVisible()

    m = Modal("Teste", host)
    ok = m.add_button("Salvar", "primary", m.accept)
    assert ok.isDefault()
    m.close()


def test_critical_flows_create_search_trash_lock(qtbot, paths, monkeypatch):
    from PySide6.QtWidgets import QWidget

    from nexus_intel.ui import app, auth, common, workspace
    from tests.conftest import PASSWORD

    monkeypatch.setattr(auth.RecoveryKeyDialog, "exec", lambda self: 1)
    for mod in (app, common, workspace):
        monkeypatch.setattr(mod, "confirm", lambda *a, **k: True, raising=False)
    win = app.MainWindow(paths)
    qtbot.addWidget(win)
    win.show()
    sp = win.setup_page
    sp.user.setText("investigador")
    sp.pw.setText(PASSWORD)
    sp.pw2.setText(PASSWORD)
    sp.terms.setChecked(True)
    sp._create()
    win.projects_page._create("Fluxos", "blank")
    ws = win.workspace

    # módulos sem backend aparecem desabilitados e explicados, nunca com dados simulados
    assert set(ws.pending_items) == {"attachments", "map", "ai", "semantic", "suggestions", "backup"}
    for row in ws.pending_items.values():
        assert "em preparação" in row.toolTip().lower()
    assert set(ws.nav_buttons) == {k for k, _ in ws.NAV} and len(ws.NAV) == 16  # + Notas (0.3.4)
    for key, _ in ws.NAV:  # todos os módulos abrem e voltam sem erro
        ws.go(key)
        assert ws.stack.currentWidget() is ws.pages[key]
    ws.go("ai")
    assert "Indisponível" in " ".join(w.accessibleName() for w in ws.pages["ai"].findChildren(QWidget))
    ws.go("backup")
    assert ws.pages["backup"].count == 0  # projeto novo: nenhuma cópia real encontrada

    # criar (captura rápida) e buscar
    ws.search.setText("Clara Nunes Teste · pessoa")
    ws.search._create()
    hits = ws.store.search("clara nunes")
    assert hits and hits[0]["type_key"] == "person"
    ws.go("entities")
    page = ws.pages["entities"]
    assert page.table.row_count() == 1
    page.filter_text.setText("clara")
    page.reset()
    assert page.table.row_count() == 1

    # lixeira e restauração
    page.filter_text.clear()
    page.reset()
    page.table.selectRow(0)
    page._bulk("trashed")
    assert ws.store.search("clara nunes") == []
    ws.go("trash")
    trash = ws.pages["trash"]
    assert trash.table.row_count() == 1
    trash.table.selectRow(0)
    trash._restore()
    assert ws.store.search("clara nunes")

    # tela inicial com dados e bloqueio
    ws.go("home")
    assert ws.pages["home"].stack.currentWidget() is ws.pages["home"].content
    win.lock()
    assert not win.session.unlocked and win.workspace is None
