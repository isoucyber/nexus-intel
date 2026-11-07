"""Fotografa as telas principais com dados fictícios.

Uso: python tools/screenshots.py <pasta-de-saída> [largura altura]

Roda no CI (Windows) para registrar o "antes/depois" de cada fase. Usa uma pasta
de dados temporária: nunca toca nos dados reais.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]


def main() -> int:
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    width = int(sys.argv[2]) if len(sys.argv) > 2 else 1440
    height = int(sys.argv[3]) if len(sys.argv) > 3 else 900
    tmp = tempfile.mkdtemp(prefix="nexus-shots-")
    os.environ["NEXUS_INTEL_HOME"] = tmp

    from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])

    from nexus_intel.infrastructure.paths import default_paths
    from nexus_intel.ui import app as ui_app
    from nexus_intel.ui import auth
    from tools.demo_data import seed

    auth.RecoveryKeyDialog.exec = lambda self: 1  # type: ignore[method-assign]
    if hasattr(ui_app, "confirm"):
        ui_app.confirm = lambda *a, **k: True  # type: ignore[assignment]

    def settle(ms: int = 250) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()
        QCoreApplication.processEvents()

    count = 0

    def shot(widget, name: str) -> None:  # type: ignore[no-untyped-def]
        nonlocal count
        settle()
        count += 1
        path = out / f"{count:02d}-{name}.png"
        widget.grab().save(str(path))
        print("captura", path.name)

    win = ui_app.MainWindow(default_paths())
    win.resize(width, height)
    win.show()
    shot(win, "primeiro-uso")

    sp = win.setup_page
    sp.user.setText("analista")
    sp.pw.setText("senha-de-demonstracao-2026")
    sp.pw2.setText("senha-de-demonstracao-2026")
    sp.terms.setChecked(True)
    sp._create()
    shot(win, "projetos-vazio")

    win.projects_page._create("Operação Maré Alta", "example")
    ws = win.workspace
    seed(ws.store)
    win.show_projects()
    shot(win, "projetos")

    # Grade de projetos em várias larguras (critério F1 da 0.3).
    from PySide6.QtCore import Qt as _Qt

    from nexus_intel.ui.projects_page import ProjectsPage

    for i, (name, tpl) in enumerate([("Auditoria de fornecedores 2026", "investigation"),
                                     ("Pesquisa — redes logísticas do Adriático", "research"),
                                     ("Inventário de domínios", "it_assets"),
                                     ("Família Prado (genealogia)", "genealogy"),
                                     ("Um projeto com nome propositalmente muito longo para testar reticências",
                                      "blank")]):
        win.manager.create(name, tpl)
    for w, h in ((1024, 768), (1366, 768), (1920, 1080), (2560, 1440), (700, 900)):
        page = ProjectsPage(win.manager)
        page.setAttribute(_Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        page.resize(w, h)
        page.show()
        page.refresh()
        shot(page, f"projetos-{w}x{h}")
        print(f"  {w}px: {page.grid.columns} colunas, card {page.grid.item_width(page.grid.width())}x{page.grid.item_h}")
        page.close()

    projects = win.manager.list()
    win.open_project(next(p.id for p in projects if p.name == "Operação Maré Alta"))
    ws = win.workspace
    for key, name in (("home", "inicio"), ("entities", "central"), ("graph", "grafo"),
                      ("sources", "fontes"), ("quality", "qualidade"), ("trash", "lixeira"),
                      ("audit", "auditoria")):
        ws.go(key)
        if key == "quality" and hasattr(ws.pages[key], "_scan"):
            ws.pages[key]._scan()
        shot(win, name)

    helena = ws.store.search("helena prado")[0]["id"]
    ws.open_entity(helena)
    shot(win, "entidade-resumo")
    page = ws.tabs.currentWidget() if hasattr(ws, "tabs") else None
    if page is not None and hasattr(page, "tabs"):
        for i, name in ((1, "entidade-atributos"), (2, "entidade-relacoes")):
            page.tabs.setCurrentIndex(i)
            shot(win, name)

    if hasattr(ws, "search"):
        ws.search.setFocus()
        ws.search.setText("hel")
        if hasattr(ws.search, "_search"):
            ws.search._search()
        shot(win, "busca")
        ws.search.clear()

    settings_cls = getattr(ui_app, "SettingsDialog", None)
    if settings_cls is not None:
        dlg = settings_cls(win)
        dlg.show()
        shot(dlg, "configuracoes")
        dlg.close()

    gallery = getattr(sys.modules.get("nexus_intel.ui.design.gallery"), "Gallery", None)
    if gallery is None:
        try:
            from nexus_intel.ui.design.gallery import Gallery as gallery  # type: ignore[no-redef]
        except ImportError:
            gallery = None
    if gallery is not None:
        from nexus_intel.ui.design import tokens

        for theme in tokens.THEMES:
            g = gallery(theme)
            g.resize(width, height)
            g.show()
            shot(g, f"componentes-{theme}")
            g.close()

    win.lock()
    shot(win, "bloqueado")
    win.close()
    app.processEvents()
    print(f"{count} capturas em {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
