"""0.3.4 na interface: perfis, Backspace no grafo, Notepad, fotografias e .nexus."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from tests.conftest import PASSWORD  # noqa: E402
from tests.imagefactory import make_image  # noqa: E402

pytestmark = pytest.mark.qt
PW_B = "senha-do-segundo-perfil-99"


@pytest.fixture
def win(qtbot, paths, monkeypatch):
    from nexus_intel.ui import app, auth

    monkeypatch.setattr(auth.RecoveryKeyDialog, "exec", lambda self: 1)
    monkeypatch.setattr(app, "confirm", lambda *a, **k: True)
    w = app.MainWindow(paths)
    qtbot.addWidget(w)
    w.resize(1366, 768)
    w.show()
    return w


def _create_profile(win, name, user, pw):
    sp = win.setup_page
    assert win.stack.currentWidget() is sp
    sp.name.setText(name)
    sp.user.setText(user)
    sp.pw.setText(pw)
    sp.pw2.setText(pw)
    sp.terms.setChecked(True)
    sp._create()
    assert sp.error.text() == "", sp.error.text()


def test_setup_has_generic_placeholders_only(win):
    sp = win.setup_page
    texts = [sp.name.placeholderText(), sp.user.placeholderText(), sp.pw.placeholderText(),
             sp.pw2.placeholderText()]
    assert texts[0] == "Digite seu nome" and texts[1] == "Nome de usuário"
    assert all("arthur" not in t.lower() for t in texts)
    assert sp.user.text() == "" and sp.name.text() == ""


def test_two_profiles_switch_and_isolation_in_ui(win, qtbot):
    _create_profile(win, "Perfil A", "perfil_a", PASSWORD)
    assert win.stack.currentWidget() is win.projects_page
    assert win.projects_page.profile_btn.text() == "Perfil A"
    win.projects_page._create("Caso de A", "blank")
    win.workspace.store.create_entity("person", "Entidade de A")
    win.show_projects()

    win.switch_profile()
    assert win.session is None
    assert win.stack.currentWidget() is win.profiles_page
    assert [t.info.display_name for t in win.profiles_page.tiles] == ["Perfil A"]
    win.show_setup(first=False)
    _create_profile(win, "Perfil B", "perfil_b", PW_B)
    assert win.projects_page.projects == []  # B não vê o projeto de A

    win.switch_profile()
    assert sorted(t.info.display_name for t in win.profiles_page.tiles) == ["Perfil A", "Perfil B"]
    tile_a = next(t for t in win.profiles_page.tiles if t.info.display_name == "Perfil A")
    tile_a.activated.emit(tile_a.info.id)
    assert win.stack.currentWidget() is win.login_page
    assert win.login_page.who.text() == "Perfil A"
    win.login_page.pw.setText(PASSWORD)
    win.login_page._login()
    assert [p.name for p in win.projects_page.projects] == ["Caso de A"]

    win.lock()  # bloqueio volta para a entrada do MESMO perfil
    assert win.stack.currentWidget() is win.login_page and win.login_page.who.text() == "Perfil A"


def test_backspace_cuts_only_selected_relation_with_undo(qtbot, store):
    from PySide6.QtCore import Qt

    from nexus_intel.ui.graph_view import EdgeItem
    from nexus_intel.ui.workspace import Workspace

    a = store.create_entity("person", "Ponta A")
    b = store.create_entity("person", "Ponta B")
    rid = store.create_relation("knows", a, b)
    ws = Workspace(store, "P", "#2dd4bf")
    qtbot.addWidget(ws)
    ws.resize(1366, 768)
    ws.show()
    ws.go("graph")
    graph = ws.pages["graph"]
    qtbot.keyClick(graph.view, Qt.Key.Key_Backspace)  # nada selecionado: nada acontece
    assert store.get_relation(rid)["record_status"] == "active"

    ws.search.setFocus()
    edge = next(i for i in graph.view.scene().items() if isinstance(i, EdgeItem))
    edge.setSelected(True)
    qtbot.keyClick(ws.search, Qt.Key.Key_Backspace)  # digitando num campo: não corta
    assert store.get_relation(rid)["record_status"] == "active"

    qtbot.keyClick(graph.view, Qt.Key.Key_Backspace)
    assert store.get_relation(rid)["record_status"] == "trashed"
    assert store.get_entity(a)["record_status"] == "active" and store.get_entity(b)["record_status"] == "active"
    assert not [i for i in graph.view.scene().items() if isinstance(i, EdgeItem)]
    graph.undo_cut(rid)
    assert store.get_relation(rid)["record_status"] == "active"
    ws.shutdown()


def test_notepad_autosave_search_and_entity_link(qtbot, store, monkeypatch):
    from nexus_intel.ui import notes_page
    from nexus_intel.ui.workspace import Workspace

    monkeypatch.setattr(notes_page, "confirm", lambda *a, **k: True)
    eid = store.create_entity("person", "Pessoa Nota")
    ws = Workspace(store, "P", "#2dd4bf")
    qtbot.addWidget(ws)
    ws.show()
    ws.go("notes")
    page = ws.pages["notes"]
    nid = page.new_note()
    page.title.setText("Reunião")
    page.title.textEdited.emit("Reunião")
    page.body.setPlainText("Linha longa " * 2000)
    page.entity.set_value(eid)
    qtbot.waitUntil(lambda: page.status.text() == "Salvo", timeout=3000)
    note = store.get_note(nid)
    assert note["title"] == "Reunião" and note["entity_id"] == eid and len(note["body"]) > 20000
    page.search.setText("nada-disso")
    assert page.table.row_count() == 0
    page.search.setText("reuni")
    assert page.table.row_count() == 1
    # Nova nota a partir da ficha da entidade já vem vinculada
    ws._new_note_for(eid)
    assert store.get_note(page.current_id)["entity_id"] == eid
    page.delete_current()
    assert len(store.list_notes()) == 1
    ws.shutdown()


def test_photo_gallery_add_view_replace_remove(qtbot, store, tmp_path, monkeypatch):
    from nexus_intel.ui import photos
    from nexus_intel.ui.entity_page import EntityPage

    monkeypatch.setattr(photos, "confirm", lambda *a, **k: True)
    eid = store.create_entity("person", "Pessoa Foto")
    files = []
    for fmt, ext in (("PNG", "png"), ("WEBP", "webp"), ("TIFF", "tif")):
        f = tmp_path / f"foto.{ext}"
        f.write_bytes(make_image(fmt, color=(10, len(files) * 80, 90)))
        files.append(str(f))
    fake = tmp_path / "virus.jpg"
    fake.write_bytes(b"MZ nao sou imagem")
    page = EntityPage(store, eid)
    qtbot.addWidget(page)
    page.resize(1200, 760)
    page.show()
    gal = page.photos
    assert gal.stack.currentWidget() is gal.empty
    assert gal.add_files([*files, str(fake)]) == 3
    assert gal.grid.count() == 3 and page.tabs.tabText(1) == "Fotografias (3)"
    viewer = photos.PhotoViewer(store, gal.rows, 0, page)
    viewer.show()
    viewer.go(1)
    assert viewer.index == 1 and "Pessoa Foto" in viewer.info.text()
    viewer.go(5)  # navegação circular
    viewer.close()
    new = tmp_path / "nova.gif"
    new.write_bytes(make_image("GIF"))
    assert gal.replace_with(0, str(new))
    assert gal.rows[0]["original_name"] == "nova.gif"
    gal.grid.setCurrentRow(0)
    gal.remove(0)
    assert gal.grid.count() == 2 and store.photo_count(eid) == 2


def test_export_and_import_dialogs(qtbot, manager, store, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QWidget

    from nexus_intel.ui import package_ui

    eid = store.create_entity("person", "Exportada")
    store.add_photo(eid, make_image("PNG"), "x.png")
    dlg = package_ui.ExportDialog(manager, store)
    qtbot.addWidget(dlg)
    dlg.dest.setText(str(tmp_path / "saida"))
    dlg.pw.setText("senha-do-arquivo-123")
    dlg.pw2.setText("outra-coisa-qualquer")
    dlg._export()
    assert "coincidem" in dlg.error.text()
    dlg.pw2.setText("senha-do-arquivo-123")
    dlg._export()
    assert dlg.result_path == tmp_path / "saida.nexus" and dlg.result_path.exists()

    host = QWidget()
    qtbot.addWidget(host)
    host.manager = manager
    attempts = iter(["senha-errada-do-arquivo", "senha-do-arquivo-123"])
    monkeypatch.setattr(package_ui.PasswordDialog, "exec",
                        lambda self: (self.pw.setText(next(attempts)), 1)[1])
    monkeypatch.setattr(package_ui.PreviewDialog, "exec", lambda self: 1)
    pid = package_ui.import_flow(host, str(dlg.result_path))
    assert pid and pid != store.project_id  # mesmo perfil: entra como cópia
    assert manager.get(pid).name.endswith("(importado)")
