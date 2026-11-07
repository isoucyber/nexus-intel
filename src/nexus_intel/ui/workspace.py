"""Área de trabalho de um projeto: navegação, central de informações e páginas auxiliares."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from shiboken6 import isValid
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from nexus_intel.application.project_store import ProjectStore
from nexus_intel.domain.errors import NexusError
from nexus_intel.domain.model import SOURCE_KINDS
from nexus_intel.ui import format as fmt
from nexus_intel.ui.common import Page, button, confirm, guarded, hbox, label
from nexus_intel.ui.design import assets, tokens
from nexus_intel.ui.design.components import (
    STATUS_LABELS,
    BarList,
    BarRow,
    Card,
    ElidedLabel,
    EmptyState,
    Input,
    Kbd,
    SectionHeader,
    Select,
    notify,
    on_theme,
    text,
)
from nexus_intel.ui.design.table import Column, DataTable
from nexus_intel.ui.dialogs import NewEntityDialog, SourceDialog, delete_source_flow
from nexus_intel.ui.entity_page import EntityPage
from nexus_intel.ui.graph_view import GraphPage
from nexus_intel.ui.links import open_external_link
from nexus_intel.ui.module_pages import SPECS, BackupPage, ImportExportPage, make_pending
from nexus_intel.ui.timeline_page import TimelinePage

_ROLE = Qt.ItemDataRole.UserRole


def _stack(*widgets: QWidget) -> QStackedWidget:
    st = QStackedWidget()
    for w in widgets:
        st.addWidget(w)
    return st


# ------------------------------------------------------------------- início
class KpiCard(Card):
    """Número do Início. Clicável: leva ao lugar onde a informação está."""

    activated = Signal()

    def __init__(self, icon: str, caption: str, destination: str) -> None:
        super().__init__(padding="lg")
        self._icon, self.caption, self.destination = icon, caption, destination
        self.setProperty("clickable", "true")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setToolTip(f"Abrir {destination}")
        row = QHBoxLayout()
        row.setSpacing(12)
        self.badge = text("")
        self.badge.setFixedSize(36, 36)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.badge)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.value = text("0", "h1")
        col.addWidget(self.value)
        col.addWidget(text(caption, "muted"))
        row.addLayout(col, 1)
        self.arrow = text("")
        row.addWidget(self.arrow, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(row)
        self._paint(tokens.current())
        on_theme(self, self._paint)

    def _paint(self, t: tokens.Tokens) -> None:
        self.badge.setPixmap(assets.pixmap(self._icon, t.accent_text, 18))
        self.badge.setStyleSheet(f"background: {t.accent_subtle}; border-radius: {t.radius('md')}px;")
        self.arrow.setPixmap(assets.pixmap("arrow-up-right", t.text_muted, 14))

    def set_value(self, n: int) -> None:
        self.value.setText(fmt.number(n))
        self.setAccessibleName(f"{self.caption}: {n}. Abrir {self.destination}")

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.activated.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit()
            return
        super().keyPressEvent(event)


class DashboardPage(Page):
    open_entity = Signal(str)
    go_to = Signal(str)

    def __init__(self, store: ProjectStore) -> None:
        super().__init__()
        self.store = store
        self.layout_.addWidget(SectionHeader("Início", "Visão geral do projeto aberto."))
        kpis = QHBoxLayout()
        kpis.setSpacing(12)
        # número → (ícone, rótulo, destino legível, chave do módulo de destino)
        targets = {
            "entities": ("database", "Entidades", "a lista de entidades", "entities"),
            "relations": ("network", "Relações", "o grafo de relações", "graph"),
            "claims": ("list", "Afirmações", "Qualidade (conflitos e afirmações sem fonte)", "quality"),
            "sources": ("library", "Fontes", "a lista de fontes", "sources"),
            "trashed": ("trash-2", "Na lixeira", "a lixeira", "trash"),
        }
        self.kpi = {}
        for key, (icon, caption, readable, dest) in targets.items():
            card = KpiCard(icon, caption, readable)
            card.activated.connect(lambda d=dest: self.go_to.emit(d))
            self.kpi[key] = card
            kpis.addWidget(card, 1)
        self.layout_.addLayout(kpis)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.recent = DataTable([Column("display_name", "Nome", "entity", stretch=True),
                                 Column("type_label", "Tipo", "muted", width=120),
                                 Column("updated_at", "Atualizada", "reltime", width=100)])
        self.recent.row_activated.connect(lambda r: self.open_entity.emit(r["id"]))
        self.recent.setProperty("frameless", "true")
        recent_card = Card("Atualizadas recentemente", icon="clock",
                           actions=[button("Ver todas", lambda: self.go_to.emit("entities"), "Ghost")])
        recent_card.add(self.recent, 1)
        self.types = BarList(empty_text="Nenhuma entidade ainda.")
        self.types.activated.connect(lambda key: self.go_to.emit(f"entities:type:{key}"))
        self.types.setToolTip("Clique num tipo para ver as entidades dele")
        types_card = Card("Entidades por tipo", icon="layers")
        types_card.add(self.types)
        types_card.body.addStretch(1)
        self.statuses = BarList(empty_text="Nenhuma afirmação ainda.")
        self.statuses.activated.connect(lambda _k: self.go_to.emit("quality"))
        status_card = Card("Afirmações por status", icon="shield-check",
                           subtitle="Relatado ≠ verificado: confirme com uma segunda fonte.")
        status_card.add(self.statuses)
        status_card.body.addStretch(1)
        grid.addWidget(recent_card, 0, 0, 2, 1)
        grid.addWidget(types_card, 0, 1)
        grid.addWidget(status_card, 1, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        self.content = QWidget()
        self.content.setLayout(grid)
        self.empty = EmptyState(
            "inbox", "Este projeto ainda está vazio",
            "Cadastre a primeira entidade (pessoa, empresa, veículo, local…) e ligue as informações às "
            "fontes. Dica: Ctrl+K busca ou cria em qualquer tela.",
            "Nova entidade", lambda: self.go_to.emit("entities:new"))
        self.stack = _stack(self.content, self.empty)
        self.layout_.addWidget(self.stack, 1)

    def refresh(self) -> None:
        s = guarded(self, self.store.stats)
        if not s:
            return
        for key, card in self.kpi.items():
            card.set_value(s[key])
        self.stack.setCurrentWidget(self.content if s["entities"] else self.empty)
        self.recent.set_rows(s["recent"])
        self.types.set_rows([
            BarRow(r["type_key"], r["label"], r["n"], lambda t, k=r["type_key"]: t.type_color(k),
                   assets.TYPE_ICONS.get(r["type_key"], "circle"))
            for r in s["by_type"]
        ])
        order = ["verified", "reported", "unverified", "hypothesis", "conflicting", "refuted"]
        rows = sorted(s["by_status"], key=lambda r: order.index(r["epistemic_status"])
                      if r["epistemic_status"] in order else 99)
        self.statuses.set_rows([
            BarRow(r["epistemic_status"], STATUS_LABELS.get(r["epistemic_status"], r["epistemic_status"]),
                   r["n"], lambda t, k=r["epistemic_status"]: t.status_color(k),
                   assets.STATUS_ICONS.get(r["epistemic_status"]))
            for r in rows
        ])


# ------------------------------------------------------------------- central
class EntitiesPage(Page):
    open_entity = Signal(str)
    changed = Signal()

    PAGE = 200

    def __init__(self, store: ProjectStore) -> None:
        super().__init__()
        self.store = store
        self.type = Select([("Todos os tipos", None)] + [(t["label"], t["id"]) for t in store.entity_types()])
        self.status = Select([("Ativas", "active"), ("Arquivadas", "archived")])
        self.order = Select([(f"Ordenar: {v}", k) for k, v in (("updated", "atualização"), ("name", "nome"),
                                                                 ("created", "criação"), ("importance", "importância"))])
        self.filter_text = Input("Filtrar: texto, tipo:pessoa, tag:italia…", icon="search", clearable=True)
        self.no_source = Select([("Com e sem fonte", False), ("Só sem nenhuma fonte", True)])
        self.fav = Select([("Todas", False), ("Só favoritas", True)])
        for c in (self.type, self.status, self.order, self.no_source, self.fav):
            c.currentIndexChanged.connect(lambda _: self.reset())
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self.reset)
        self.filter_text.textChanged.connect(lambda _: self._debounce.start())

        new_btn = button("Nova entidade", self.new_entity, "Primary", icon="plus")
        new_btn.setToolTip("Nova entidade (Ctrl+N)")
        self.layout_.addWidget(SectionHeader("Central de Informações",
                                             "Todas as entidades do projeto. Duplo clique ou Enter abre a ficha.",
                                             [new_btn]))
        self.filter_text.setMinimumWidth(280)
        self.layout_.addWidget(hbox(self.filter_text, self.type, self.status, self.no_source, self.fav,
                                    None, self.order))
        self.table = DataTable([
            Column("display_name", "Nome", "entity", stretch=True,
                   getter=lambda r: ("★ " if r.get("is_favorite") else "") + r["display_name"]),
            Column("type_label", "Tipo", "muted", width=130),
            Column("relation_count", "Relações", "number", width=90),
            Column("importance", "Import.", "number", width=80),
            Column("summary", "Resumo", getter=lambda r: r.get("snippet") or r.get("summary"), width=320),
            Column("updated_at", "Atualizada", "reltime", width=110),
        ], page_size=self.PAGE)
        self.table.row_activated.connect(lambda r: self.open_entity.emit(r["id"]))
        self.empty = EmptyState("search", "Nenhuma entidade encontrada",
                                "Ajuste os filtros, ou cadastre uma entidade nova.", "Nova entidade",
                                self.new_entity)
        self.stack = _stack(self.table, self.empty)
        self.layout_.addWidget(self.stack, 1)
        self.count = label("", "Muted")
        self.layout_.addWidget(hbox(self.count, None,
                                    button("Arquivar selecionadas", lambda: self._bulk("archived"), icon="archive"),
                                    button("Mover para a lixeira", lambda: self._bulk("trashed"), "Danger",
                                           icon="trash-2")))

    def _fetch(self, offset: int, limit: int) -> list[dict[str, Any]]:
        return self.store.list_entities(
            type_id=self.type.value(), status=self.status.value(), favorites_only=self.fav.value(),
            without_evidence=self.no_source.value(), order=self.order.value(), limit=limit, offset=offset)

    def reset(self) -> None:
        # Caixas de seleção avisam “mudei” enquanto a tela é destruída (ao bloquear):
        # nesse caso não há o que recarregar.
        if not isValid(self) or not isValid(self.stack):
            return
        q = self.filter_text.text().strip()
        if q:
            rows = guarded(self, lambda: self.store.search(q, 500)) or []
            self.table.set_rows(rows)
        else:
            guarded(self, lambda: self.table.load(self._fetch))
        shown = self.table.row_count()
        self.stack.setCurrentWidget(self.table if shown else self.empty)
        total = self.store.count_entities()
        more = " (role para carregar mais)" if self.table.model_.canFetchMore() else ""
        self.count.setText(f"{fmt.number(shown)} exibidas de {fmt.number(total)} ativas{more}")

    def _bulk(self, status: str) -> None:
        ids = [r["id"] for r in self.table.selected_rows()]
        if not ids:
            notify(self, "Selecione uma ou mais linhas primeiro.", "info")
            return
        verb = "arquivar" if status == "archived" else "mover para a lixeira"
        if confirm(self, "Ação em lote", f"{verb.capitalize()} {len(ids)} entidade(s)?", status == "trashed"):
            for eid in ids:
                guarded(self, lambda eid=eid: self.store.set_entity_status(eid, status))
            self.reset()
            self.changed.emit()
            notify(self, f"{len(ids)} entidade(s) {'arquivada(s)' if status == 'archived' else 'na lixeira'}.",
                   "success")

    def new_entity(self, name: str = "") -> None:
        dlg = NewEntityDialog(self.store, self, name=name)
        if dlg.exec():
            target = dlg.entity_id or dlg.existing_id
            self.reset()
            self.changed.emit()
            if dlg.entity_id:
                notify(self, "Entidade criada.", "success")
            if target:
                self.open_entity.emit(target)


# ------------------------------------------------------------------- fontes
class SourcesPage(Page):
    open_entity = Signal(str)
    changed = Signal()

    def __init__(self, store: ProjectStore) -> None:
        super().__init__()
        self.store = store
        self.q = Input("Filtrar por título ou URL…", icon="search", clearable=True)
        self.q.textChanged.connect(lambda _: self.refresh())
        self.layout_.addWidget(SectionHeader(
            "Fontes", "Confiabilidade da fonte (A–F) e credibilidade da informação (1–6) seguem a escala do "
            "Almirantado e são sempre definidas por você.",
            [self._delete_btn(), button("Nova fonte", self._new, "Primary", icon="plus")]))
        self.layout_.addWidget(self.q)
        self.table = DataTable([
            Column("title", "Título", stretch=True,
                   getter=lambda s: s["title"] + ("  (desacreditada)" if s["is_discredited"] else "")),
            Column("kind", "Tipo", "muted", width=150, getter=lambda s: SOURCE_KINDS.get(s["kind"], s["kind"])),
            Column("reliability", "Confiab.", width=80, getter=lambda s: s["reliability"] or "—"),
            Column("uses", "Usos", "number", width=70),
            Column("url", "URL", "link", width=240),
            Column("accessed_at", "Consultada", "muted", width=110),
        ])
        self.table.row_activated.connect(lambda s: self._edit(s["id"]))
        self.table.link_clicked.connect(lambda url: open_external_link(url, self))
        self.table.selectionModel().currentRowChanged.connect(lambda *_: self._usages())
        self.empty = EmptyState("library", "Nenhuma fonte cadastrada",
                                "Fontes são a base de tudo: cada afirmação deve apontar de onde veio.",
                                "Nova fonte", self._new)
        self.stack = _stack(self.table, self.empty)
        self.layout_.addWidget(self.stack, 2)
        self.layout_.addWidget(text("Onde a fonte selecionada é usada (duplo clique abre a entidade):", "muted"))
        self.uses = QListWidget()
        self.uses.itemDoubleClicked.connect(lambda it: self.open_entity.emit(it.data(_ROLE)))
        self.layout_.addWidget(self.uses, 1)

    def _delete_btn(self) -> Any:
        self.delete_btn = button("Excluir fonte", self._delete, "Danger", icon="trash-2",
                                 tip="Excluir a fonte selecionada")
        self.delete_btn.setEnabled(False)
        return self.delete_btn

    def _delete(self) -> None:
        s = self.table.current_row()
        if not s:
            notify(self, "Selecione uma fonte na lista primeiro.", "info")
            return
        if delete_source_flow(self.store, s, self):
            self.refresh()
            self.changed.emit()
            notify(self, f"Fonte “{s['title']}” excluída.", "success")

    def refresh(self) -> None:
        rows = guarded(self, lambda: self.store.list_sources(self.q.text())) or []
        self.delete_btn.setEnabled(False)
        self.table.set_rows(rows)
        self.stack.setCurrentWidget(self.table if rows or self.q.text() else self.empty)
        self.uses.clear()

    def _usages(self) -> None:
        self.uses.clear()
        s = self.table.current_row()
        self.delete_btn.setEnabled(s is not None)
        if not s:
            return
        for u in self.store.source_usages(s["id"]):
            ex = f" — “{u['excerpt']}”" if u["excerpt"] else ""
            it = QListWidgetItem(f"{u['label'] or '(removido)'}{ex}")
            it.setData(_ROLE, u["entity_id"])
            it.setToolTip(it.text())
            self.uses.addItem(it)

    def _new(self) -> None:
        if SourceDialog(self.store, self).exec():
            self.refresh()
            notify(self, "Fonte cadastrada.", "success")

    def _edit(self, sid: str) -> None:
        try:
            source = self.store.get_source(sid)
        except NexusError:
            notify(self, "Essa fonte não existe mais.", "info")
            self.refresh()
            return
        dlg = SourceDialog(self.store, self, source=source)
        if dlg.exec():
            self.refresh()
            self.changed.emit()
            if dlg.deleted:
                notify(self, f"Fonte “{source['title']}” excluída.", "success")


# ------------------------------------------------------------------- qualidade
class QualityPage(Page):
    open_entity = Signal(str)
    changed = Signal()

    def __init__(self, store: ProjectStore) -> None:
        super().__init__()
        self.store = store
        self.layout_.addWidget(SectionHeader("Qualidade dos dados",
                                             "Conflitos, lacunas de fonte e possíveis duplicatas."))
        self.counters = label("", "Muted", wrap=True)
        self.layout_.addWidget(self.counters)
        tabs = QTabWidget()
        self.conflicts = DataTable([Column("display_name", "Entidade", stretch=True),
                                    Column("field", "Campo em conflito", width=220)])
        self.conflicts.row_activated.connect(lambda r: self.open_entity.emit(r["entity_id"]))
        self.orphans = DataTable([Column("display_name", "Entidade sem nenhuma fonte", "entity", stretch=True),
                                  Column("type_label", "Tipo", "muted", width=140)])
        self.orphans.row_activated.connect(lambda r: self.open_entity.emit(r["id"]))
        dup_page = QWidget()
        dl = QVBoxLayout(dup_page)
        dl.setContentsMargins(0, 12, 0, 0)
        self.dups = DataTable([Column("a_name", "Entidade A", stretch=True), Column("b_name", "Entidade B", stretch=True),
                               Column("score", "Semelhança", "number", width=100, getter=lambda r: f"{r['score']}%"),
                               Column("reasons", "Motivos", "muted", width=260)])
        self.dups.setSelectionMode(DataTable.SelectionMode.SingleSelection)
        dl.addWidget(hbox(button("Procurar duplicatas", self._scan, "Primary", icon="search"), None,
                          button("São diferentes", self._different, icon="x"),
                          button("Mesclar B em A", self._merge, icon="git-merge")))
        dl.addWidget(self.dups, 1)
        tabs.addTab(self.conflicts, assets.icon("triangle-alert"), "Conflitos")
        tabs.addTab(self.orphans, assets.icon("circle-dashed"), "Sem fonte")
        tabs.addTab(dup_page, assets.icon("git-merge"), "Possíveis duplicatas")
        self.layout_.addWidget(tabs, 1)

    def refresh(self) -> None:
        q = guarded(self, self.store.quality)
        if not q:
            return
        self.counters.setText(
            f"Afirmações sem fonte: {q['claims_without_source']} · Relações sem fonte: {q['relations_without_source']} · "
            f"Entidades sem relação: {q['orphans']} · Revisões vencidas: {q['review_due']} · "
            f"Fontes desacreditadas: {q['discredited_sources']}")
        self.conflicts.set_rows(self.store.conflicting_entities())
        self.orphans.set_rows(self.store.list_entities(without_evidence=True, limit=500))

    def _scan(self) -> None:
        pairs = guarded(self, self.store.scan_duplicates) or []
        self.dups.set_rows([{"a_id": a["id"], "a_name": a["display_name"], "b_id": c.entity_id,
                             "b_name": c.display_name, "score": c.score, "reasons": "; ".join(c.reasons)}
                            for a, c in pairs])
        if not pairs:
            notify(self, "Nenhuma duplicata provável encontrada.", "info")

    def _different(self) -> None:
        r = self.dups.current_row()
        if r:
            guarded(self, lambda: self.store.record_dedupe_decision(r["a_id"], r["b_id"], "different"))
            self._scan()

    def _merge(self) -> None:
        r = self.dups.current_row()
        if r and confirm(self, "Mesclar entidades",
                         "Mesclar B em A? Afirmações, relações, fontes, nomes e etiquetas de B passam para A, "
                         "e B vai para a lixeira. Dá para desfazer pelo histórico de A."):
            guarded(self, lambda: self.store.merge_entities(r["a_id"], r["b_id"]))
            self._scan()
            self.changed.emit()
            self.open_entity.emit(r["a_id"])


# ------------------------------------------------------------------- lixeira
class TrashPage(Page):
    """Lixeira com duas abas: entidades e relações cortadas. Os botões agem na aba aberta."""

    changed = Signal()

    def __init__(self, store: ProjectStore) -> None:
        super().__init__()
        self.store = store
        self.layout_.addWidget(SectionHeader(
            "Lixeira", "Itens na lixeira não aparecem na busca, no grafo nem nas listas. Restaurar uma entidade "
            "devolve as relações e afirmações dela; uma relação cortada volta ao grafo.",
            [button("Restaurar", self._restore, "Primary", icon="undo-2"),
             button("Excluir definitivamente", self._purge, "Danger", icon="x"),
             button("Esvaziar lixeira", self._empty, "Danger", icon="trash-2")]))
        self.table = DataTable([Column("display_name", "Nome", "entity", stretch=True),
                                Column("type_label", "Tipo", "muted", width=140),
                                Column("updated_at", "Na lixeira desde", "reltime", width=140)])
        self.empty = EmptyState("trash-2", "Nenhuma entidade na lixeira", "Entidades excluídas ficam aqui até "
                                "você restaurar ou excluir definitivamente.")
        self.stack = _stack(self.table, self.empty)
        self.rel_table = DataTable([Column("phrase", "Relação cortada", stretch=True),
                                    Column("ends", "Pontas", "muted", width=200,
                                           getter=lambda r: "entidade na lixeira" if "trashed" in
                                           (r["source_status"], r["target_status"]) else "ativas"),
                                    Column("updated_at", "Cortada", "reltime", width=120)])
        self.rel_empty = EmptyState("network", "Nenhuma relação cortada",
                                    "Relações cortadas na ficha da entidade ou no grafo ficam aqui. As entidades "
                                    "das pontas nunca são apagadas.")
        self.rel_stack = _stack(self.rel_table, self.rel_empty)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.stack, assets.icon("database"), "Entidades")
        self.tabs.addTab(self.rel_stack, assets.icon("network"), "Relações")
        self.layout_.addWidget(self.tabs, 1)

    def refresh(self) -> None:
        rows = guarded(self, lambda: self.store.list_entities(status="trashed", limit=1000)) or []
        self.table.set_rows(rows)
        self.stack.setCurrentWidget(self.table if rows else self.empty)
        rels = guarded(self, self.store.list_trashed_relations) or []
        self.rel_table.set_rows(rels)
        self.rel_stack.setCurrentWidget(self.rel_table if rels else self.rel_empty)
        self.tabs.setTabText(0, f"Entidades ({len(rows)})")
        self.tabs.setTabText(1, f"Relações ({len(rels)})")

    def _on_relations(self) -> bool:
        return self.tabs.currentIndex() == 1

    def _selected(self) -> list[dict[str, Any]]:
        table = self.rel_table if self._on_relations() else self.table
        rows = table.selected_rows()
        if not rows:
            notify(self, "Selecione um ou mais itens na lista primeiro.", "info")
        return rows

    def _restore(self) -> None:
        rows = self._selected()
        if not rows:
            return
        if self._on_relations():
            for r in rows:
                guarded(self, lambda r=r: self.store.restore_relation(r["id"]))
            msg = f"{len(rows)} relação(ões) restaurada(s)."
        else:
            for r in rows:
                guarded(self, lambda r=r: self.store.restore_entity(r["id"]))
            msg = f"{len(rows)} entidade(s) restaurada(s)."
        self.refresh()
        self.changed.emit()
        notify(self, msg, "success")

    def _purge(self) -> None:
        rows = self._selected()
        if not rows:
            return
        if self._on_relations():
            names = "\n".join(f"• {r['phrase']}" for r in rows[:5]) + ("\n…" if len(rows) > 5 else "")
            text = (f"Excluir definitivamente {len(rows)} relação(ões)?\n\n{names}\n\nAs fontes ligadas a elas "
                    "são desvinculadas. As entidades das pontas continuam. Esta ação não pode ser desfeita.")
            action = self.store.delete_relation_permanently
        else:
            names = "\n".join(f"• {r['display_name']}" for r in rows[:5]) + ("\n…" if len(rows) > 5 else "")
            text = f"Excluir definitivamente {len(rows)} entidade(s)?\n\n{names}\n\nEsta ação não pode ser desfeita."
            action = self.store.delete_entity_permanently
        if confirm(self, "Excluir definitivamente", text, True):
            for r in rows:
                guarded(self, lambda r=r: action(r["id"]))
            self.refresh()
            self.changed.emit()
            notify(self, f"{len(rows)} item(ns) excluído(s) definitivamente.", "success")

    def _empty(self) -> None:
        if confirm(self, "Esvaziar lixeira", "Excluir definitivamente todas as entidades e relações da lixeira? "
                   "Esta ação não pode ser desfeita.", True):
            n = guarded(self, self.store.empty_trash) or 0
            self.refresh()
            self.changed.emit()
            notify(self, f"{n} item(ns) excluído(s) definitivamente.", "success")


# ------------------------------------------------------------------- auditoria
class AuditPage(Page):
    def __init__(self, store: ProjectStore) -> None:
        super().__init__()
        self.store = store
        self.result = label("", "Muted")
        self.layout_.addWidget(SectionHeader(
            "Auditoria", "Cada linha guarda o hash da anterior. A verificação detecta linhas alteradas ou "
            "apagadas depois de gravadas.",
            [self.result, button("Verificar integridade", self._verify, "Primary", icon="shield-check")]))
        self.table = DataTable([Column("ts", "Quando", "reltime", width=110),
                                Column("action", "Ação", "mono", width=170),
                                Column("object_kind", "Objeto", "muted", width=100),
                                Column("summary", "Resumo", stretch=True),
                                Column("actor", "Usuário", "muted", width=110)])
        self.layout_.addWidget(self.table, 1)

    def refresh(self) -> None:
        self.table.set_rows(guarded(self, lambda: self.store.audit_entries(1000)) or [])

    def _verify(self) -> None:
        bad = guarded(self, self.store.verify_audit)
        if bad is None:
            self.result.setText("Cadeia íntegra")
            self.result.setProperty("role", "success")
            notify(self, "Auditoria íntegra: nenhuma linha alterada.", "success")
        else:
            self.result.setText(f"Adulteração na linha {bad}")
            self.result.setProperty("role", "danger")
            notify(self, f"Adulteração detectada na linha {bad} do log.", "danger")
        self.result.style().unpolish(self.result)
        self.result.style().polish(self.result)


# ------------------------------------------------------------------- busca global
class SearchBox(Input):
    """Busca global (Ctrl+K) com captura rápida: “Nome · tipo” + Enter cria a entidade."""

    open_entity = Signal(str)
    created = Signal()

    def __init__(self, store: ProjectStore, parent: QWidget | None = None) -> None:
        super().__init__("Buscar ou criar…   ex.: Maria Souza · pessoa", icon="search", parent=parent)
        self.store = store
        self.setProperty("search", "true")
        self.setMinimumWidth(460)
        self.setToolTip("Buscar ou criar (Ctrl+K)")
        self.popup = QListWidget(self)
        self.popup.setWindowFlags(Qt.WindowType.ToolTip)
        self.popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.popup.itemClicked.connect(self._choose)
        self.popup.setMouseTracking(True)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._search)
        self.textEdited.connect(lambda _: self._timer.start())
        self.returnPressed.connect(self._enter)

    def _search(self) -> None:
        q = self.text().strip()
        self.popup.clear()
        if not q:
            self.popup.hide()
            return
        t = tokens.current()
        for r in self.store.search(q.split("·")[0], 12):
            it = QListWidgetItem(f"{r['display_name']}   ·  {r['type_label']}")
            it.setIcon(assets.icon(assets.TYPE_ICONS.get(r["type_key"], "circle"), t.type_color(r["type_key"])))
            it.setData(_ROLE, r["id"])
            self.popup.addItem(it)
        create = QListWidgetItem(f"Criar “{q}”")
        create.setIcon(assets.icon("plus", t.accent_text))
        create.setData(_ROLE, None)
        self.popup.addItem(create)
        self.popup.setCurrentRow(0)
        pos = self.mapToGlobal(self.rect().bottomLeft())
        self.popup.setGeometry(pos.x(), pos.y() + 4, self.width(), min(360, 34 * self.popup.count() + 10))
        self.popup.show()

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802
        if self.popup.isVisible() and event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            row = self.popup.currentRow() + (1 if event.key() == Qt.Key.Key_Down else -1)
            self.popup.setCurrentRow(max(0, min(self.popup.count() - 1, row)))
            return
        if event.key() == Qt.Key.Key_Escape:
            self.popup.hide()
            self.clear()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event: Any) -> None:  # noqa: N802
        QTimer.singleShot(200, self.popup.hide)
        super().focusOutEvent(event)

    def _enter(self) -> None:
        if self.popup.isVisible() and self.popup.currentItem():
            self._choose(self.popup.currentItem())
        elif self.text().strip():
            self._create()

    def _choose(self, item: QListWidgetItem) -> None:
        eid = item.data(_ROLE)
        if eid:
            self.open_entity.emit(eid)
            self.popup.hide()
            self.clear()
        else:
            self._create()

    def _create(self) -> None:
        q = self.text().strip()
        self.popup.hide()
        eid = guarded(self, lambda: self.store.quick_capture(q))
        if eid:
            self.clear()
            self.created.emit()
            notify(self, f"“{self.store.get_entity(eid)['display_name']}” criada.", "success")
            self.open_entity.emit(eid)


# ------------------------------------------------------------------- espaço
class Workspace(QWidget):
    back_to_projects = Signal()
    lock_requested = Signal()

    # Grupos da navegação: (chave, rótulo, ícone, em_preparação). Módulos em preparação
    # abrem uma página que explica o que existe e o que falta, sem dados simulados.
    GROUPS: tuple[tuple[str, tuple[tuple[str, str, str, bool], ...]], ...] = (
        ("Investigação", (
            ("home", "Visão geral", "layout-dashboard", False),
            ("entities", "Entidades", "database", False),
            ("graph", "Grafo", "network", False),
            ("sources", "Fontes", "library", False),
            ("timeline", "Linha do tempo", "clock", False),
            ("attachments", "Anexos cifrados", "file-text", True),
            ("map", "Mapa offline", "map-pin", True),
        )),
        ("Inteligência", (
            ("ai", "IA e análises", "sparkles", True),
            ("semantic", "Busca semântica", "file-search", True),
            ("suggestions", "Sugestões e aprovações", "git-merge", True),
        )),
        ("Dados", (
            ("quality", "Qualidade", "shield-check", False),
            ("io", "Importação e exportação", "upload", False),
            ("backup", "Backup", "history", True),
            ("trash", "Lixeira", "trash-2", False),
            ("audit", "Auditoria", "scroll-text", False),
        )),
    )
    LABELS = {k: lb for _g, items in GROUPS for k, lb, _i, _p in items}
    ICONS = {k: ic for _g, items in GROUPS for k, _l, ic, _p in items}
    NAV = tuple((k, lb) for _g, items in GROUPS for k, lb, _i, _p in items)

    def __init__(self, store: ProjectStore, project_name: str, color: str,
                 project_path: Path | None = None) -> None:
        super().__init__()
        self.store = store
        self.setProperty("page", "true")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        side = QFrame()
        side.setProperty("sidebar", "true")
        side.setFixedWidth(236)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(12, 16, 12, 12)
        sl.setSpacing(2)
        sl.addWidget(label("NEXUS INTEL", "Brand"))
        sl.addSpacing(10)
        sl.addWidget(text("PROJETO", "overline"))
        pname = ElidedLabel(project_name, "h3")
        pname.setStyleSheet(f"border-left: 3px solid {color}; padding-left: 8px;")
        sl.addWidget(pname)
        sl.addSpacing(8)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons: dict[str, Any] = {}
        self.pending_items: dict[str, Any] = {}
        nav_host = QWidget()
        nl = QVBoxLayout(nav_host)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(1)
        for group, items in self.GROUPS:
            nl.addSpacing(8)
            nl.addWidget(text(group.upper(), "overline"))
            nl.addSpacing(2)
            for key, label_, icon, pending in items:
                b = button(label_, lambda k=key: self.go(k), "Nav", icon=icon)
                b.setCheckable(True)
                self.nav_group.addButton(b)
                self.nav_buttons[key] = b
                nl.addWidget(self._pending_item(key, b) if pending else b)
        nl.addStretch(1)
        nav_scroll = QScrollArea()
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        nav_scroll.setWidget(nav_host)
        sl.addWidget(nav_scroll, 1)
        sl.addWidget(button("Projetos", self.back_to_projects.emit, "Nav", icon="folder"))
        lock = button("Bloquear", self.lock_requested.emit, "Nav", icon="lock", tip="Bloquear (Ctrl+L)")
        sl.addWidget(lock)
        root.addWidget(side)

        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)
        top = QFrame()
        top.setProperty("topbar", "true")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(20, 10, 20, 10)
        tl.setSpacing(8)
        self.search = SearchBox(store)
        tl.addWidget(self.search)
        tl.addWidget(Kbd("Ctrl+K"))
        tl.addStretch(1)
        offline = text("Local · offline", "caption")
        offline.setToolTip("Nenhum dado sai deste computador.")
        tl.addWidget(offline)
        ml.addWidget(top)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.stack = QStackedWidget()
        self.pages: dict[str, Any] = {
            "home": DashboardPage(store),
            "entities": EntitiesPage(store),
            "graph": GraphPage(store),
            "sources": SourcesPage(store),
            "quality": QualityPage(store),
            "trash": TrashPage(store),
            "audit": AuditPage(store),
            "timeline": TimelinePage(store),
            "io": ImportExportPage(lambda: self.pages["graph"].export_png()),
            "backup": BackupPage(project_path),
            **{k: make_pending(k) for k in ("attachments", "map", "ai", "semantic", "suggestions")},
        }
        for page in self.pages.values():
            self.stack.addWidget(page)
            if hasattr(page, "open_entity"):
                page.open_entity.connect(self.open_entity)
            if hasattr(page, "changed"):
                page.changed.connect(self._data_changed)
        self.pages["home"].go_to.connect(self._go_to)
        self.tabs.addTab(self.stack, "")
        self.tabs.tabBar().setTabButton(0, self.tabs.tabBar().ButtonPosition.RightSide, None)
        ml.addWidget(self.tabs, 1)
        root.addWidget(main, 1)

        self.search.open_entity.connect(self.open_entity)
        self.search.created.connect(self._data_changed)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=lambda: (self.search.setFocus(), self.search.selectAll()))
        QShortcut(QKeySequence("Ctrl+N"), self, activated=lambda: (self.go("entities"), self.pages["entities"].new_entity()))
        QShortcut(QKeySequence("Ctrl+G"), self, activated=lambda: self.go("graph"))
        QShortcut(QKeySequence("Ctrl+W"), self, activated=lambda: self._close_tab(self.tabs.currentIndex()))
        self._loaded: set[str] = set()
        self._graph_dirty = False
        self._current = "home"
        on_theme(self, lambda _t: self._label_section_tab())
        self.go("home" if store.count_entities() else "entities")

    def _pending_item(self, key: str, b: Any) -> QWidget:
        """Item de módulo em preparação: texto em cinza + rótulo, abre a página explicativa."""
        row = QWidget()
        lay = QVBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 2)
        lay.setSpacing(0)
        b.setProperty("pending", "true")
        lay.addWidget(b)
        caption = text("Em preparação", "caption")
        caption.setContentsMargins(37, 0, 0, 0)  # alinhado ao texto do botão, depois do ícone
        caption.setStyleSheet(f"font-size: {tokens.current().font_px('xs') - 1}px;")
        lay.addWidget(caption)
        spec = SPECS.get(key)
        missing = " ".join(spec.missing) if spec else "Backup agendado com registro de estado."
        tip = f"{self.LABELS[key]}: em preparação. Falta: {missing}"
        row.setToolTip(tip)
        b.setToolTip(tip)
        b.setAccessibleName(f"{self.LABELS[key]}, em preparação")
        self.pending_items[key] = row
        return row

    def shutdown(self) -> None:
        """Silencia sinais e timers antes da destruição (bloqueio, troca de projeto, fechar).

        Sem isso, caixas de seleção destruídas avisam “mudei” e disparam recargas
        sobre widgets que já não existem.
        """
        for obj in [self, *self.findChildren(QObject)]:
            obj.blockSignals(True)
            if isinstance(obj, QTimer):
                obj.stop()
        self.search.popup.hide()

    def _go_to(self, target: str) -> None:
        if target == "entities:new":
            self.go("entities")
            self.pages["entities"].new_entity()
        elif target.startswith("entities:type:"):
            type_key = target.rsplit(":", 1)[1]
            types = {t["key"]: t["id"] for t in self.store.entity_types()}
            if type_key not in types:
                notify(self, "Esse tipo de entidade não existe mais.", "info")
                return
            page = self.pages["entities"]
            page.type.set_value(types[type_key])  # o filtro recarrega a lista
            self.go("entities")
        elif target in self.pages:
            self.go(target)
        else:
            notify(self, "Esse destino não está disponível nesta versão.", "info")

    def _label_section_tab(self) -> None:
        self.tabs.setTabText(0, self.LABELS[self._current])
        self.tabs.setTabIcon(0, assets.icon(self.ICONS[self._current]))

    def go(self, key: str) -> None:
        self._current = key
        self.nav_buttons[key].setChecked(True)
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        self.tabs.setCurrentIndex(0)
        self._label_section_tab()
        if key == "graph":
            if key not in self._loaded:
                page.reload()  # primeira visita: layout completo
            elif self._graph_dirty:
                page.reload(keep_positions=True)  # dados mudaram em outra tela: mantém os nós no lugar
            self._graph_dirty = False
        elif key == "entities":
            page.reset()
        else:
            page.refresh()
        self._loaded.add(key)

    def open_entity(self, eid: str) -> None:
        try:
            self.store.get_entity(eid)
        except NexusError:
            notify(self, "Essa entidade não existe mais: ela foi excluída definitivamente.", "info")
            self._data_changed()
            return
        for i in range(1, self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, EntityPage) and w.entity_id == eid:
                w.refresh()
                self.tabs.setCurrentIndex(i)
                return
        page = EntityPage(self.store, eid)
        page.open_entity.connect(self.open_entity)
        page.changed.connect(self._data_changed)
        page.show_in_graph.connect(self._show_in_graph)
        name = page.entity.get("display_name", "Entidade")
        type_key = page.entity.get("type_key", "other")
        idx = self.tabs.addTab(page, name if len(name) < 24 else name[:22] + "…")
        self.tabs.setTabIcon(idx, assets.icon(assets.TYPE_ICONS.get(type_key, "circle"),
                                              tokens.current().type_color(type_key)))
        self.tabs.setTabToolTip(idx, name)
        self.tabs.setCurrentIndex(idx)
        if self.tabs.count() > 12:  # limite de abas abertas
            self._close_tab(1)

    def _show_in_graph(self, eid: str) -> None:
        self.go("graph")
        self.pages["graph"].focus(eid)

    def _close_tab(self, index: int) -> None:
        if index > 0:
            w = self.tabs.widget(index)
            self.tabs.removeTab(index)
            w.deleteLater()

    def _data_changed(self) -> None:
        # Marca páginas para recarregar ao voltar; atualiza a visível agora.
        self._graph_dirty = True
        for i in range(1, self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, EntityPage) and w is not self.tabs.currentWidget():
                w.refresh()
        current = self.stack.currentWidget()
        if current is self.pages["entities"]:
            current.reset()
        elif current is self.pages["home"]:
            current.refresh()
