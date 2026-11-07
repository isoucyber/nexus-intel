"""Página da entidade (seção 6.4): atributos com fonte, relações, conexões e histórico."""

from __future__ import annotations

import html

import json
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from nexus_intel.application.project_store import ProjectStore
from nexus_intel.domain.model import IDENTIFIER_SCHEMES
from nexus_intel.ui.common import (
    Page,
    button,
    card,
    confirm,
    fmt_ts,
    guarded,
    hbox,
    label,
)
from nexus_intel.ui.dialogs import ClaimDialog, EvidenceDialog, RelationDialog, cut_relation_flow
from nexus_intel.ui.links import link_html, open_external_link, safe_http_url
from nexus_intel.ui.design import assets, tokens
from nexus_intel.ui.design.components import (
    require_text,
    STATUS_LABELS,
    Badge,
    ElidedLabel,
    EntityAvatar,
    SectionHeader,
    StatusBadge,
    notify,
)

_ROLE = Qt.ItemDataRole.UserRole


def evidence_line_html(v: dict[str, Any]) -> str:
    """Uma fonte em HTML seguro; o título vira link quando a fonte tem URL http/https."""
    rel = f"[{html.escape(v['reliability'])}] " if v.get("reliability") else ""
    title = link_html(v.get("url"), v["title"]) if v.get("url") else html.escape(v["title"])
    bad = " — DESACREDITADA" if v.get("is_discredited") else ""
    ex = f" — “{html.escape(v['excerpt'])}”" if v.get("excerpt") else ""
    loc = f" ({html.escape(v['locator'])})" if v.get("locator") else ""
    return f"• {rel}{title}{bad}{ex}{loc}"


def _item(text: str, data: Any = None, color: str | None = None) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if data is not None:
        it.setData(_ROLE, data)
    if color:
        it.setForeground(assets.qcolor(color))
    return it


class EntityPage(Page):
    open_entity = Signal(str)
    show_in_graph = Signal(str)
    changed = Signal()

    def __init__(self, store: ProjectStore, entity_id: str) -> None:
        super().__init__()
        self.store = store
        self.entity_id = entity_id
        self.entity: dict[str, Any] = {}

        self.avatar = EntityAvatar("other", 40)
        self.title = ElidedLabel("", "h1")
        self.subtitle = label("", "Muted")
        self.chips = hbox()
        self.fav = button("", self._toggle_fav, "Ghost", tip="Favoritar", icon="star")
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(self.avatar)
        head.addWidget(self.title, 1)
        head.addWidget(self.fav)
        head.addSpacing(12)
        head.addWidget(button("Ver no grafo", lambda: self.show_in_graph.emit(self.entity_id), icon="network"))
        head.addWidget(button("Arquivar", self._archive, icon="archive"))
        head.addWidget(button("Lixeira", self._trash, "Danger", icon="trash-2"))
        self.layout_.addLayout(head)
        self.layout_.addWidget(self.subtitle)
        self.layout_.addWidget(self.chips)

        self.tabs = QTabWidget()
        self.layout_.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_overview(), "Resumo")
        self.tabs.addTab(self._build_claims(), "Atributos")
        self.tabs.addTab(self._build_relations(), "Relações")
        self.tabs.addTab(self._build_connections(), "Conexões")
        self.tabs.addTab(self._build_history(), "Histórico")
        self.refresh()

    # ----------------------------------------------------------- resumo
    def _build_overview(self) -> QWidget:
        w = QWidget()
        self.f_name = QLineEdit()
        self.f_type = QComboBox()
        for t in self.store.entity_types():
            self.f_type.addItem(t["label"], t["id"])
        self.f_summary = QLineEdit()
        self.f_importance = QSpinBox()
        self.f_importance.setRange(1, 5)
        self.f_desc = QPlainTextEdit()
        self.f_desc.setPlaceholderText("Descrição em Markdown")
        self.f_private = QPlainTextEdit()
        self.f_private.setPlaceholderText("Observações privadas: nunca exportadas por padrão")
        self.f_private.setFixedHeight(80)
        self.f_aliases = QLineEdit()
        self.f_aliases.setPlaceholderText("outros nomes, separados por ;")
        self.f_tags = QLineEdit()
        self.f_tags.setPlaceholderText("etiquetas, separadas por ; (ex.: regiao/europa/italia)")
        self.f_ids = QLineEdit()
        self.f_ids.setPlaceholderText("cpf:123.456.789-09; domain:exemplo.com")
        self.f_ids.setToolTip("Esquemas: " + ", ".join(f"{k} ({v})" for k, v in IDENTIFIER_SCHEMES.items()))
        form = QFormLayout()
        form.addRow("Nome *", self.f_name)
        form.addRow("", require_text(self.f_name, [], "O nome não pode ficar vazio."))
        form.addRow("Tipo", self.f_type)
        form.addRow("Resumo", self.f_summary)
        form.addRow("Importância", self.f_importance)
        form.addRow("Outros nomes", self.f_aliases)
        form.addRow("Identificadores", self.f_ids)
        form.addRow("Etiquetas", self.f_tags)
        form.addRow("Descrição", self.f_desc)
        form.addRow("Privado", self.f_private)
        self.meta = label("", "Muted")
        self.save_btn = button("Salvar alterações", self._save, "Primary")
        form.addRow(hbox(self.meta, None, self.save_btn))
        self.f_name.textChanged.connect(lambda txt: self.save_btn.setEnabled(bool(txt.strip())))
        w.setLayout(form)
        return w

    def _save(self) -> None:
        if not self.f_name.text().strip():
            return  # nome inválido: botão desabilitado e mensagem no campo

        def run() -> None:
            e = self.entity
            changes: dict[str, Any] = {}
            for key, val in (("display_name", self.f_name.text()), ("summary", self.f_summary.text()),
                             ("importance", self.f_importance.value()),
                             ("description_md", self.f_desc.toPlainText()),
                             ("private_note", self.f_private.toPlainText()),
                             ("type_id", self.f_type.currentData())):
                if val != e[key]:
                    changes[key] = val
            if changes.get("type_id") and not confirm(
                    self, "Converter tipo", "Mudar o tipo mantém todos os dados; atributos que não existem "
                    "no novo tipo continuam visíveis. Continuar?"):
                changes.pop("type_id")
            if changes:
                self.store.update_entity(self.entity_id, e["version"], **changes)
            aliases = [a.strip() for a in self.f_aliases.text().split(";") if a.strip()]
            if aliases != [a["alias"] for a in e["aliases"]]:
                self.store.set_aliases(self.entity_id, aliases)
            tags = [t.strip() for t in self.f_tags.text().split(";") if t.strip()]
            if tags != e["tags"]:
                self.store.set_tags(self.entity_id, tags)
            ids = []
            for part in self.f_ids.text().split(";"):
                if ":" in part:
                    scheme, value = part.split(":", 1)
                    ids.append((scheme.strip().lower(), value.strip()))
            if ids != [(i["scheme"], i["value_norm"]) for i in e["identifiers"]]:
                self.store.set_identifiers(self.entity_id, ids)
        guarded(self, run)
        self.refresh()
        self.changed.emit()

    # ------------------------------------------------------- atributos
    def _build_claims(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(SectionHeader("", "Cada valor tem sua própria fonte e status. Valores conflitantes "
                                    "ficam lado a lado; nada é apagado.",
                                    [button("Atributo", self._add_claim, "Primary", icon="plus")], role="h3"))
        self.claims = QTreeWidget()
        self.claims.setHeaderLabels(["Campo / valor", "Status", "Fontes", "Validade", "Observação"])
        self.claims.setAlternatingRowColors(True)
        self.claims.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.claims.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.claims.customContextMenuRequested.connect(self._claim_menu)
        self.claims.itemDoubleClicked.connect(self._claim_double_clicked)
        self.claims.itemClicked.connect(self._claim_clicked)
        self.claims.setMouseTracking(True)
        self.claims.itemEntered.connect(self._claim_hover)
        lay.addWidget(self.claims, 1)
        self.evidence_box = self._evidence_label()
        lay.addWidget(self.evidence_box)
        self.claims.currentItemChanged.connect(lambda it, _p: self._show_evidence("claim", it))
        return w

    def _fill_claims(self) -> None:
        self.claims.clear()
        show_empty = False
        for g in self.store.claims_for(self.entity_id):
            if not g.claims and not show_empty:
                continue
            parent = QTreeWidgetItem([g.field_def["label"] + ("  ·  conflito" if g.has_conflict else "")])
            if g.has_conflict:
                parent.setIcon(0, assets.icon("triangle-alert", tokens.current().danger, 14))
                parent.setForeground(0, assets.qcolor(tokens.current().danger))
            parent.setData(0, _ROLE, {"field_key": g.field_def["key"]})
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            for cv in g.claims:
                c = cv.row
                status = "conflicting" if cv.in_conflict and c["epistemic_status"] != "refuted" else c["epistemic_status"]
                flags = []
                if c["is_preferred"]:
                    flags.append("★ preferido")
                if cv.only_discredited:
                    flags.append("fonte desacreditada")
                if c["is_sensitive"]:
                    flags.append("sensível")
                validity = " – ".join(x for x in (c["valid_from"] or "", c["valid_to"] or "atual") if x) \
                    if c["valid_from"] or c["valid_to"] else ""
                child = QTreeWidgetItem([
                    cv.display_value + (f"   ({', '.join(flags)})" if flags else ""),
                    STATUS_LABELS.get(status, status),
                    str(cv.evidence_count) if cv.evidence_count else "sem fonte",
                    validity, c["note"],
                ])
                st_color = tokens.current().status_color(status)
                child.setForeground(1, assets.qcolor(st_color))
                child.setIcon(1, assets.icon(assets.STATUS_ICONS.get(status, "circle"), st_color, 14))
                url = safe_http_url(c.get("value_text")) if cv.datatype == "url" else None
                if url:  # link: cor de destaque, sublinhado, clique abre no navegador
                    child.setForeground(0, assets.qcolor(tokens.current().accent_text))
                    f = child.font(0)
                    f.setUnderline(True)
                    child.setFont(0, f)
                    child.setToolTip(0, f"Clique para abrir no navegador: {url}")
                child.setData(0, _ROLE, {"claim": c, "url": url})
                parent.addChild(child)
            self.claims.addTopLevelItem(parent)
            parent.setExpanded(True)
        if self.claims.topLevelItemCount() == 0:
            self.claims.addTopLevelItem(QTreeWidgetItem(["Nenhum atributo registrado. Use “+ Atributo”."]))
        self.claims.resizeColumnToContents(1)

    @staticmethod
    def _url_of(item: QTreeWidgetItem | None) -> str | None:
        data = item.data(0, _ROLE) if item else None
        return data.get("url") if isinstance(data, dict) else None

    def _claim_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        url = self._url_of(item)
        if url and column == 0:
            open_external_link(url, self)

    def _claim_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if self._url_of(item) and column == 0:
            return  # o clique já abriu o link; editar fica no menu do botão direito
        self._edit_claim(item)

    def _claim_hover(self, item: QTreeWidgetItem, column: int) -> None:
        link = self._url_of(item) is not None and column == 0
        self.claims.viewport().setCursor(Qt.CursorShape.PointingHandCursor if link else Qt.CursorShape.ArrowCursor)

    def _evidence_label(self) -> QLabel:
        """Lista de fontes com links clicáveis (abrem no navegador só ao clicar)."""
        lb = QLabel("")
        lb.setProperty("role", "muted")
        lb.setWordWrap(True)
        lb.setTextFormat(Qt.TextFormat.RichText)
        lb.setOpenExternalLinks(False)
        lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        lb.linkActivated.connect(lambda url: open_external_link(url, self))
        return lb

    def _claim_of(self, item: QTreeWidgetItem | None) -> dict[str, Any] | None:
        data = item.data(0, _ROLE) if item else None
        return data.get("claim") if isinstance(data, dict) else None

    def _add_claim(self, field_key: str | None = None) -> None:
        if ClaimDialog(self.store, self.entity_id, self, field_key=field_key).exec():
            self.refresh()
            self.changed.emit()

    def _edit_claim(self, item: QTreeWidgetItem) -> None:
        c = self._claim_of(item)
        if c is None:
            data = item.data(0, _ROLE)
            if isinstance(data, dict) and data.get("field_key"):
                self._add_claim(data["field_key"])
            return
        if ClaimDialog(self.store, self.entity_id, self, claim=c).exec():
            self.refresh()

    def _claim_menu(self, pos: Any) -> None:
        item = self.claims.itemAt(pos)
        c = self._claim_of(item)
        if not c:
            return
        m = QMenu(self)
        url = self._url_of(item)
        if url:
            m.addAction("Abrir link no navegador", lambda: open_external_link(url, self))
        m.addAction("Editar…", lambda: self._edit_claim(item))
        m.addAction("Adicionar fonte…", lambda: self._add_evidence("claim", c["id"]))
        m.addAction("Marcar como preferido", lambda: (guarded(self, lambda: self.store.set_preferred_claim(c["id"])),
                                                      self.refresh()))
        m.addSeparator()
        m.addAction("Excluir afirmação", lambda: self._delete_claim(c))
        m.exec(self.claims.viewport().mapToGlobal(pos))

    def _delete_claim(self, c: dict[str, Any]) -> None:
        if confirm(self, "Excluir afirmação", "Excluir esta afirmação? Ela continua no histórico.", True):
            guarded(self, lambda: self.store.delete_claim(c["id"]))
            self.refresh()

    def _add_evidence(self, kind: str, target_id: str) -> None:
        if EvidenceDialog(self.store, kind, target_id, self).exec():
            self.refresh()

    def _show_evidence(self, kind: str, item: Any) -> None:
        target = None
        if kind == "claim":
            c = self._claim_of(item)
            target = c["id"] if c else None
        else:
            target = item.data(0, _ROLE)["id"] if item is not None and item.data(0, _ROLE) else None
        box = self.evidence_box if kind == "claim" else self.rel_evidence
        if not target:
            box.setText("")
            return
        ev = self.store.evidence_for(kind, target)
        if not ev:
            box.setText("Sem fonte. Clique com o botão direito para adicionar.")
            return
        box.setText("Fontes:<br>" + "<br>".join(evidence_line_html(v) for v in ev))

    # --------------------------------------------------------- relações
    def _build_relations(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.cut_btn = button("Cortar relação", self._cut_selected, "Danger", icon="x",
                              tip="Cortar a relação selecionada (vai para a Lixeira; as entidades ficam)")
        self.cut_btn.setEnabled(False)
        lay.addWidget(SectionHeader("", "No grafo: linha contínua = verificada; tracejada = relatada; "
                                    "pontilhada = hipótese; vermelha = conflitante.",
                                    [self.cut_btn, button("Relação", self._add_relation, "Primary", icon="plus")],
                                    role="h3"))
        self.relations = QTreeWidget()
        self.relations.setHeaderLabels(["Relação", "Entidade", "Status", "Fontes", "Validade", "Descrição"])
        self.relations.setRootIsDecorated(False)
        self.relations.setAlternatingRowColors(True)
        self.relations.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.relations.itemDoubleClicked.connect(
            lambda it, _c: self.open_entity.emit(it.data(0, _ROLE)["other_id"]) if it.data(0, _ROLE) else None)
        self.relations.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.relations.customContextMenuRequested.connect(self._relation_menu)
        lay.addWidget(self.relations, 1)
        self.rel_evidence = self._evidence_label()
        lay.addWidget(self.rel_evidence)
        self.relations.currentItemChanged.connect(lambda it, _p: self._show_evidence("relation", it))
        self.relations.currentItemChanged.connect(
            lambda it, _p: self.cut_btn.setEnabled(bool(it is not None and it.data(0, _ROLE))))
        return w

    def _fill_relations(self) -> None:
        self.relations.clear()
        t = tokens.current()
        for r in self.store.relations_for(self.entity_id):
            validity = f"{r['valid_from'] or ''} – {r['valid_to'] or 'atual'}" if r["valid_from"] or r["valid_to"] else ""
            it = QTreeWidgetItem([r["phrase"], r["other_name"], STATUS_LABELS.get(r["epistemic_status"], ""),
                                  str(r["ev_count"]) if r["ev_count"] else "sem fonte", validity, r["description"]])
            st_color = t.status_color(r["epistemic_status"])
            it.setForeground(2, assets.qcolor(st_color))
            it.setIcon(2, assets.icon(assets.STATUS_ICONS.get(r["epistemic_status"], "circle"), st_color, 14))
            it.setData(0, _ROLE, r)
            it.setToolTip(1, "Duplo clique para abrir")
            self.relations.addTopLevelItem(it)
        for i in range(self.relations.columnCount()):
            if i != 1:
                self.relations.resizeColumnToContents(i)

    def _add_relation(self) -> None:
        if RelationDialog(self.store, self.entity_id, self).exec():
            self.refresh()
            self.changed.emit()

    def _relation_menu(self, pos: Any) -> None:
        item = self.relations.itemAt(pos)
        r = item.data(0, _ROLE) if item else None
        if not r:
            return
        m = QMenu(self)
        m.addAction("Abrir entidade", lambda: self.open_entity.emit(r["other_id"]))
        m.addAction("Editar relação…", lambda: self._edit_relation(r))
        m.addAction("Adicionar fonte…", lambda: self._add_evidence("relation", r["id"]))
        m.addSeparator()
        m.addAction(assets.icon("x", tokens.current().danger), "Cortar relação…", lambda: self._cut_relation(r))
        m.exec(self.relations.viewport().mapToGlobal(pos))

    def _edit_relation(self, r: dict[str, Any]) -> None:
        if RelationDialog(self.store, self.entity_id, self, relation=r).exec():
            self.refresh()

    def _cut_selected(self) -> None:
        item = self.relations.currentItem()
        r = item.data(0, _ROLE) if item else None
        if r:
            self._cut_relation(r)

    def _cut_relation(self, r: dict[str, Any]) -> None:
        if cut_relation_flow(self.store, r["id"], self):
            self.refresh()
            self.changed.emit()
            notify(self, f"Relação cortada: {r['source_name']} {r['label']} {r['target_name']}. "
                         "Ela está na Lixeira.", "success")

    # --------------------------------------------------------- conexões
    def _build_connections(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(label("Entidades ligadas direta ou indiretamente (até 3 saltos). Ligações indiretas "
                            "são calculadas, nunca gravadas como fato.", "Muted", wrap=True))
        self.connections = QTableWidget(0, 3)
        self.connections.setHorizontalHeaderLabels(["Entidade", "Tipo", "Distância"])
        self.connections.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.connections.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.connections.verticalHeader().hide()
        self.connections.cellDoubleClicked.connect(
            lambda row, _c: self.open_entity.emit(self.connections.item(row, 0).data(_ROLE)))
        lay.addWidget(self.connections, 1)
        return w

    def _fill_connections(self) -> None:
        rows = self.store.connections(self.entity_id)
        self.connections.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.connections.setItem(i, 0, _item(r["display_name"], r["id"]))
            self.connections.setItem(i, 1, _item(r["type_label"]))
            self.connections.setItem(i, 2, _item("direta" if r["depth"] == 1 else f"{r['depth']} saltos"))

    # --------------------------------------------------------- histórico
    def _build_history(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.history = QTableWidget(0, 3)
        self.history.setHorizontalHeaderLabels(["Quando", "Alteração", "Nome naquela versão"])
        self.history.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.history.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history.verticalHeader().hide()
        lay.addWidget(self.history, 1)
        self.undo_merge_btn = button("Desfazer última mesclagem", self._undo_merge)
        lay.addWidget(hbox(self.undo_merge_btn, None,
                           button("Restaurar versão selecionada", self._restore_revision)))
        return w

    def _fill_history(self) -> None:
        names = {"create": "criação", "update": "edição", "trashed": "lixeira", "active": "restaurada",
                 "archived": "arquivada", "merge": "mesclagem", "merge_undone": "mesclagem desfeita"}
        revs = self.store.history("entity", self.entity_id)
        self.history.setRowCount(len(revs))
        for i, r in enumerate(revs):
            snap = json.loads(r["snapshot_json"])
            name = snap.get("display_name") or (f"recebeu “{snap.get('removed_name')}”" if r["change_kind"] == "merge" else "")
            self.history.setItem(i, 0, _item(fmt_ts(r["changed_at"]), r["id"]))
            self.history.setItem(i, 1, _item(names.get(r["change_kind"], r["change_kind"])))
            self.history.setItem(i, 2, _item(name))
        self.undo_merge_btn.setVisible(self.store.last_merge_revision(self.entity_id) is not None)

    def _restore_revision(self) -> None:
        row = self.history.currentRow()
        if row < 0:
            return
        rid = self.history.item(row, 0).data(_ROLE)
        if confirm(self, "Restaurar versão", "Restaurar nome, resumo, descrição e tipo desta versão?"):
            guarded(self, lambda: self.store.restore_entity_revision(rid))
            self.refresh()
            self.changed.emit()

    def _undo_merge(self) -> None:
        rid = self.store.last_merge_revision(self.entity_id)
        if rid and confirm(self, "Desfazer mesclagem", "Separar novamente as entidades mescladas?"):
            guarded(self, lambda: self.store.undo_merge(rid))
            self.refresh()
            self.changed.emit()

    # ------------------------------------------------------------ ações
    def _toggle_fav(self) -> None:
        guarded(self, lambda: self.store.update_entity(self.entity_id, self.entity["version"],
                                                       is_favorite=0 if self.entity["is_favorite"] else 1))
        self.refresh()

    def _archive(self) -> None:
        new = "active" if self.entity["record_status"] == "archived" else "archived"
        guarded(self, lambda: self.store.set_entity_status(self.entity_id, new))
        self.refresh()
        self.changed.emit()

    def _trash(self) -> None:
        if confirm(self, "Mover para a lixeira", f"Mover “{self.entity['display_name']}” para a lixeira? "
                   "Você pode restaurar depois."):
            guarded(self, lambda: self.store.trash_entity(self.entity_id))
            self.refresh()
            self.changed.emit()

    def refresh(self) -> None:
        e = guarded(self, lambda: self.store.get_entity(self.entity_id))
        if e is None:
            return
        self.entity = e
        self.title.setText(e["display_name"])
        self.avatar.set_type(e["type_key"])
        self.avatar.setToolTip(e["type_label"])
        status = {"active": "", "archived": " · ARQUIVADA", "trashed": " · NA LIXEIRA"}[e["record_status"]]
        self.subtitle.setText(f"{e['type_label']} · importância {e['importance']}{status} · "
                              f"criada {fmt_ts(e['created_at'])} · atualizada {fmt_ts(e['updated_at'])}")
        self.fav.setToolTip("Remover dos favoritos" if e["is_favorite"] else "Favoritar")
        self.fav.setText("Favorito" if e["is_favorite"] else "")
        lay = self.chips.layout()
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        groups = self.store.claims_for(self.entity_id)
        total = sum(len(g.claims) for g in groups)
        by_status: dict[str, int] = {}
        for g in groups:
            for c in g.claims:
                st = "conflicting" if c.in_conflict else c.row["epistemic_status"]
                by_status[st] = by_status.get(st, 0) + 1
        lay.addWidget(label(f"{total} afirmações", "Muted"))
        for st, n in sorted(by_status.items()):
            lay.addWidget(StatusBadge(st, n))
        for tag in e["tags"]:
            lay.addWidget(Badge(f"#{tag}", "neutral", "hash"))
        lay.addStretch(1)

        self.f_name.setText(e["display_name"])
        self.f_type.setCurrentIndex(self.f_type.findData(e["type_id"]))
        self.f_summary.setText(e["summary"])
        self.f_importance.setValue(e["importance"])
        self.f_desc.setPlainText(e["description_md"])
        self.f_private.setPlainText(e["private_note"])
        self.f_aliases.setText("; ".join(a["alias"] for a in e["aliases"]))
        self.f_tags.setText("; ".join(e["tags"]))
        self.f_ids.setText("; ".join(f"{i['scheme']}:{i['value_norm']}" for i in e["identifiers"]))
        self.meta.setText(f"ID {e['id']} · versão {e['version']}")
        self._fill_claims()
        self._fill_relations()
        self._fill_connections()
        self._fill_history()


__all__ = ["EntityPage", "card"]
