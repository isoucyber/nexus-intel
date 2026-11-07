"""Linha do tempo do projeto (0.3, seção 7.4).

Monta os eventos SOMENTE com dados que já existem, lidos pelos métodos públicos do
ProjectStore (nenhuma alteração de backend):
- afirmações de campos do tipo data (nascimento, fundação, data do evento…);
- início e fim da validade de relações.
O sistema guarda datas com precisão (dia, mês, ano, década), não horários; a
coluna mostra exatamente a precisão registrada.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QListWidget, QListWidgetItem, QStackedWidget, QVBoxLayout, QWidget
from shiboken6 import isValid

from nexus_intel.application.project_store import ProjectStore
from nexus_intel.domain.dates import FuzzyDate, from_storage, parse_fuzzy_date
from nexus_intel.ui import format as fmt
from nexus_intel.ui.common import Page, guarded
from nexus_intel.ui.design.components import (
    Button,
    Card,
    EmptyState,
    Input,
    SectionHeader,
    Select,
    Skeleton,
    StatusBadge,
    notify,
    text,
)
from nexus_intel.ui.design.table import Column, DataTable

_ROLE = Qt.ItemDataRole.UserRole
RELATION_START = "Início de relação"
RELATION_END = "Fim de relação"


@dataclass
class TimelineEvent:
    when: FuzzyDate
    kind: str
    title: str
    entity_id: str
    entity_name: str
    type_key: str
    status: str
    evidence_count: int
    target_kind: str  # "claim" ou "relation"
    target_id: str
    other_id: str | None = None

    def row(self) -> dict[str, Any]:
        return {"when": self.when.display(), "sort": self.when.sort_key, "kind": self.kind, "title": self.title,
                "display_name": self.entity_name, "type_key": self.type_key, "status": self.status,
                "evidence": self.evidence_count, "event": self}


def collect_events(store: ProjectStore) -> list[TimelineEvent]:
    """Lê os eventos datados de todas as entidades ativas, em ordem cronológica."""
    events: list[TimelineEvent] = []
    offset, page = 0, 500
    entities: list[dict[str, Any]] = []
    while True:
        chunk = store.list_entities(limit=page, offset=offset, order="name")
        entities.extend(chunk)
        if len(chunk) < page:
            break
        offset += page
    for e in entities:
        for group in store.claims_for(e["id"]):
            if group.field_def["datatype"] != "date":
                continue
            for cv in group.claims:
                c = cv.row
                when = from_storage(c.get("value_date_start"), c.get("value_date_end"), c.get("value_date_precision"))
                if when is None:
                    continue
                status = "conflicting" if cv.in_conflict and c["epistemic_status"] != "refuted" else c["epistemic_status"]
                events.append(TimelineEvent(when, group.field_def["label"], f"{group.field_def['label']} de {e['display_name']}",
                                            e["id"], e["display_name"], e["type_key"], status, cv.evidence_count,
                                            "claim", c["id"]))
        for r in store.relations_for(e["id"]):
            if r["source_id"] != e["id"]:  # cada relação entra uma vez, pela origem
                continue
            phrase = f"{r['source_name']} {r['label']} {r['target_name']}"
            for raw, kind in ((r.get("valid_from"), RELATION_START), (r.get("valid_to"), RELATION_END)):
                if not raw:
                    continue
                try:
                    when = parse_fuzzy_date(str(raw))
                except ValueError:
                    continue  # validade em formato livre que não é data: não inventamos uma
                events.append(TimelineEvent(when, kind, phrase, e["id"], e["display_name"], e["type_key"],
                                            r["epistemic_status"], r["ev_count"], "relation", r["id"], r["target_id"]))
    events.sort(key=lambda ev: (ev.when.start, ev.when.end, ev.title))
    return events


class TimelinePage(Page):
    open_entity = Signal(str)

    def __init__(self, store: ProjectStore) -> None:
        super().__init__()
        self.store = store
        self.events: list[TimelineEvent] = []
        self.layout_.addWidget(SectionHeader(
            "Linha do tempo",
            "Datas registradas em afirmações e na validade das relações, em ordem cronológica. "
            "O sistema guarda datas com precisão de dia, mês, ano ou década (sem horário)."))

        self.kind = Select([("Todos os tipos de evento", None)])
        self.date_from = Input("De (ex.: 2020 ou 03/2021)", icon="calendar", clearable=True)
        self.date_to = Input("Até", icon="calendar", clearable=True)
        for w in (self.date_from, self.date_to):
            w.setFixedWidth(200)
            w.editingFinished.connect(self._apply)
        self.kind.currentIndexChanged.connect(lambda _: self._apply())
        self.count = text("", "muted")
        filters = QHBoxLayout()
        filters.setSpacing(8)
        for w in (self.kind, self.date_from, self.date_to):
            filters.addWidget(w)
        filters.addStretch(1)
        filters.addWidget(self.count)
        self.layout_.addLayout(filters)

        self.table = DataTable([
            Column("when", "Data", "mono", width=120),
            Column("kind", "Evento", width=170),
            Column("title", "Descrição", stretch=True),
            Column("display_name", "Entidade", "entity", width=220),
            Column("status", "Status", "status", width=140),
            Column("evidence", "Fontes", "number", width=70),
        ])
        self.table.setSelectionMode(DataTable.SelectionMode.SingleSelection)
        self.table.row_activated.connect(lambda r: self.open_entity.emit(r["event"].entity_id))
        self.table.clicked.connect(lambda _i: self._show_detail())

        self.detail = Card("Evento selecionado", icon="clock")
        self.detail_title = text("Selecione um evento na tabela.", "secondary", wrap=True)
        self.detail_status = QHBoxLayout()
        self.evidence = QListWidget()
        self.evidence.setMaximumHeight(110)
        self.evidence.itemDoubleClicked.connect(self._open_from_evidence)
        nav = QHBoxLayout()
        self.prev_btn = Button("Anterior", "secondary", "chevron-left", on_click=lambda: self._step(-1), size="sm")
        self.next_btn = Button("Próximo", "secondary", "chevron-right", on_click=lambda: self._step(1), size="sm")
        self.open_btn = Button("Abrir entidade", "primary", "external-link", size="sm",
                               on_click=self._open_selected)
        for b in (self.prev_btn, self.next_btn):
            nav.addWidget(b)
        nav.addStretch(1)
        nav.addWidget(self.open_btn)
        self.detail.add(self.detail_title)
        self.detail.body.addLayout(self.detail_status)
        self.detail.add(text("Fontes que sustentam este evento:", "caption"))
        self.detail.add(self.evidence)
        self.detail.body.addLayout(nav)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.table, 3)
        cl.addWidget(self.detail, 0)
        self.loading = Skeleton(6, (1.0, 0.92, 0.85, 0.95, 0.7, 0.88), 14)
        self.empty = EmptyState(
            "clock", "Nenhuma data registrada ainda",
            "A linha do tempo mostra afirmações de data (nascimento, fundação, data do evento…) e a validade "
            "das relações. Adicione um atributo de data numa entidade para começar.")
        self.no_match = EmptyState("filter", "Nenhum evento no filtro", "Ajuste o tipo ou o intervalo de datas.",
                                   "Limpar filtros", self._clear_filters)
        self.stack = QStackedWidget()
        for w in (self.loading, content, self.empty, self.no_match):
            self.stack.addWidget(w)
        self.content = content
        self.layout_.addWidget(self.stack, 1)
        self._set_nav_enabled()

    # ----------------------------------------------------------------- dados
    def refresh(self) -> None:
        self.stack.setCurrentWidget(self.loading)
        events = guarded(self, lambda: collect_events(self.store))
        if events is None:
            return
        self.events = events
        current = self.kind.value()
        self.kind.blockSignals(True)
        self.kind.clear()
        self.kind.addItem("Todos os tipos de evento", None)
        for k in sorted({ev.kind for ev in events}):
            self.kind.addItem(k, k)
        self.kind.set_value(current)
        self.kind.blockSignals(False)
        self._apply()

    def _range(self) -> tuple[date | None, date | None]:
        lo = hi = None
        try:
            if self.date_from.text().strip():
                lo = parse_fuzzy_date(self.date_from.text()).start
            if self.date_to.text().strip():
                hi = parse_fuzzy_date(self.date_to.text()).end
        except ValueError as exc:
            notify(self, str(exc), "warning")
        return lo, hi

    def _apply(self) -> None:
        if not isValid(self) or not isValid(self.stack):
            return
        if not self.events:
            self.table.set_rows([])
            self.count.setText("")
            self.stack.setCurrentWidget(self.empty)
            return
        kind = self.kind.value()
        lo, hi = self._range()
        shown = [ev for ev in self.events
                 if (kind is None or ev.kind == kind)
                 and (lo is None or ev.when.end >= lo) and (hi is None or ev.when.start <= hi)]
        self.table.set_rows([ev.row() for ev in shown])
        self.count.setText(f"{fmt.number(len(shown))} de {fmt.number(len(self.events))} eventos")
        if not shown:
            self.stack.setCurrentWidget(self.no_match)
            return
        self.stack.setCurrentWidget(self.content)
        self.table.selectRow(0)
        self._show_detail()

    def _clear_filters(self) -> None:
        self.kind.set_value(None)
        self.date_from.clear()
        self.date_to.clear()
        self._apply()

    # ----------------------------------------------------------------- detalhe
    def _selected(self) -> TimelineEvent | None:
        row = self.table.current_row()
        return row["event"] if row else None

    def _show_detail(self) -> None:
        ev = self._selected()
        while self.detail_status.count():
            item = self.detail_status.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.evidence.clear()
        if ev is None:
            self.detail_title.setText("Selecione um evento na tabela.")
            self._set_nav_enabled()
            return
        self.detail_title.setText(f"{ev.when.display()} · {ev.kind}: {ev.title}")
        self.detail_status.addWidget(StatusBadge(ev.status))
        self.detail_status.addStretch(1)
        for v in self.store.evidence_for(ev.target_kind, ev.target_id):
            rel = f"[{v['reliability']}] " if v["reliability"] else ""
            bad = " — desacreditada" if v["is_discredited"] else ""
            ex = f" — “{v['excerpt']}”" if v["excerpt"] else ""
            it = QListWidgetItem(f"{rel}{v['title']}{bad}{ex}")
            it.setToolTip(it.text())
            it.setData(_ROLE, ev.entity_id)
            self.evidence.addItem(it)
        if not self.evidence.count():
            self.evidence.addItem("Sem fonte registrada para este evento.")
        self._set_nav_enabled()

    def _set_nav_enabled(self) -> None:
        row = self.table.currentIndex().row()
        total = self.table.row_count()
        self.prev_btn.setEnabled(row > 0)
        self.next_btn.setEnabled(0 <= row < total - 1)
        self.open_btn.setEnabled(row >= 0)

    def _step(self, delta: int) -> None:
        row = self.table.currentIndex().row() + delta
        if 0 <= row < self.table.row_count():
            self.table.selectRow(row)
            self._show_detail()

    def _open_selected(self) -> None:
        ev = self._selected()
        if ev:
            self.open_entity.emit(ev.entity_id)

    def _open_from_evidence(self, item: QListWidgetItem) -> None:
        eid = item.data(_ROLE)
        if eid:
            self.open_entity.emit(eid)
