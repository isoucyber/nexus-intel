"""Sugestões e aprovações · Busca semântica."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from nexus_intel.application.project_store import ProjectStore
from nexus_intel.application.semantic import SemanticIndex
from nexus_intel.application.suggestions import SuggestionBox
from nexus_intel.domain.errors import NexusError
from nexus_intel.infrastructure.ai.client import LocalLlmClient
from nexus_intel.ui import format as fmt
from nexus_intel.ui.ai_common import PrefsStore, pick_embed_model, run_async
from nexus_intel.ui.common import Page
from nexus_intel.ui.design.components import (
    Badge,
    Button,
    Card,
    EmptyState,
    Input,
    SectionHeader,
    Select,
    notify,
    text,
)

STATUS = {"pending": ("Pendente", "warning"), "approved": ("Aprovada", "success"), "rejected": ("Rejeitada", "neutral")}


def _scroll() -> tuple[QScrollArea, QVBoxLayout]:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 8, 0)
    lay.setSpacing(8)
    area.setWidget(host)
    return area, lay


def _clear(lay: QVBoxLayout) -> None:
    while lay.count():
        item = lay.takeAt(0)
        if item.widget():
            item.widget().deleteLater()


# ================================================================= sugestões
class SuggestionsPage(Page):
    open_entity = Signal(str)
    changed = Signal()
    count_changed = Signal(int)

    def __init__(self, store: ProjectStore) -> None:
        super().__init__()
        self.store = store
        self.box = SuggestionBox(store)
        self.filter = Select([("Pendentes", "pending"), ("Aprovadas", "approved"), ("Rejeitadas", "rejected"),
                              ("Todas", None)], "pending")
        self.filter.currentIndexChanged.connect(lambda *_: self.refresh())
        self.layout_.addWidget(SectionHeader(
            "Sugestões e aprovações",
            "O que a IA propôs. Nada entra no projeto sem a sua aprovação; cada decisão vai para a auditoria.",
            [self.filter]))
        area, self.list = _scroll()
        self.layout_.addWidget(area, 1)

    def refresh(self) -> None:
        _clear(self.list)
        items = self.box.list(self.filter.value())
        self.count_changed.emit(self.box.count_pending())
        if not items:
            self.list.addWidget(EmptyState("git-merge", "Nenhuma sugestão aqui",
                                           "Peça à IA, por exemplo: \"leia este documento\" ou "
                                           "\"liga a Helena à Aurora\"."))
            self.list.addStretch(1)
            return
        for s in items:
            self.list.addWidget(self._card(s))
        self.list.addStretch(1)

    def _card(self, s: Any) -> Card:
        label, tone = STATUS[s.status]
        card = Card(s.summary, f"{s.label} · {s.origin} · {fmt.relative(s.created_at)}",
                    actions=[Badge(label, tone)], icon="git-merge", padding="md")
        if s.rationale:
            card.add(text(f"Justificativa da IA: {s.rationale}", "secondary", wrap=True))
        if s.payload.get("excerpt"):
            ok = s.payload.get("excerpt_checked")
            row = QHBoxLayout()
            row.addWidget(Badge("Trecho conferido no documento" if ok else "Trecho não conferido",
                                "success" if ok else "warning"))
            row.addWidget(text(f"“{s.payload['excerpt']}”", "muted", wrap=True), 1)
            card.body.addLayout(row)
        if s.decision_note:
            card.add(text(f"Decisão: {s.decision_note}", "caption", wrap=True))
        if s.status == "pending":
            row = QHBoxLayout()
            reason = Input("Motivo da rejeição (opcional)")
            row.addWidget(reason, 1)
            row.addWidget(Button("Rejeitar", "ghost", "x", on_click=lambda: self._reject(s.id, reason.text())))
            row.addWidget(Button("Aprovar", "primary", "check", on_click=lambda: self._approve(s.id)))
            card.body.addLayout(row)
        elif s.status == "approved" and s.result_id and s.kind == "entity":
            card.add(Button("Abrir entidade criada", "ghost", "arrow-up-right",
                            on_click=lambda: self.open_entity.emit(s.result_id), size="sm"))
        return card

    def _approve(self, sid: str) -> None:
        try:
            self.box.approve(sid)
        except NexusError as exc:
            notify(self, exc.user_message, "danger")
            return
        notify(self, "Sugestão aprovada e aplicada.", "success")
        self.changed.emit()
        self.refresh()

    def _reject(self, sid: str, reason: str) -> None:
        try:
            self.box.reject(sid, reason)
        except NexusError as exc:
            notify(self, exc.user_message, "danger")
            return
        notify(self, "Sugestão rejeitada.", "info")
        self.refresh()


# ========================================================== busca semântica
class SemanticPage(Page):
    open_entity = Signal(str)

    def __init__(self, store: ProjectStore, prefs: PrefsStore | None = None, client_factory: Any = LocalLlmClient,
                 ) -> None:
        super().__init__()
        self.store = store
        self.prefs_store = prefs or PrefsStore()
        self.client_factory = client_factory
        self.index: SemanticIndex | None = None
        self.status = Badge("Verificando…", "neutral", "file-search")
        self.index_btn = Button("Indexar agora", "secondary", "refresh-cw", on_click=self.reindex)
        self.layout_.addWidget(SectionHeader(
            "Busca semântica", "Encontre pelo significado (\"empresas de transporte\", \"quem trabalha no porto\"). "
            "O índice fica dentro do arquivo cifrado do projeto.", [self.status, self.index_btn]))
        self.query = Input("Descreva o que procura…", icon="search")
        self.query.returnPressed.connect(self.search)
        row = QHBoxLayout()
        row.addWidget(self.query, 1)
        row.addWidget(Button("Buscar", "primary", "search", on_click=self.search))
        self.layout_.addLayout(row)
        self.info = text("", "caption", wrap=True)
        self.layout_.addWidget(self.info)
        area, self.results = _scroll()
        self.layout_.addWidget(area, 1)

    def refresh(self) -> None:
        prefs = self.prefs_store.load()
        try:
            client = self.client_factory(prefs.base_url)
        except NexusError as exc:
            self._unavailable(exc.user_message)
            return

        def done(st: Any) -> None:
            model = pick_embed_model(st.models, prefs.embed_model) if st.available else ""
            if not model:
                self._unavailable(st.detail or "Nenhum modelo de vetores instalado. No Ollama: ollama pull bge-m3")
                return
            self.index = SemanticIndex(self.store, lambda texts: client.embed(model, texts), model,
                                       include_sensitive=prefs.include_sensitive)
            self._update_counts()

        run_async(self, client.status, done, self._unavailable)

    def _unavailable(self, why: str) -> None:
        self.index = None
        self.status.set_text("Indisponível")
        self.status.setToolTip(why)
        self.info.setText(why)
        self.index_btn.setEnabled(False)

    def _update_counts(self) -> None:
        assert self.index is not None
        done, pending = self.index.indexed_count(), len(self.index.pending())
        self.status.set_text(f"{fmt.number(done)} indexada(s)" + (f" · {pending} pendente(s)" if pending else ""))
        self.status.setToolTip(f"Modelo de vetores: {self.index.model}")
        self.index_btn.setEnabled(pending > 0)
        self.info.setText("" if not pending else "Há entidades novas ou alteradas: clique em Indexar agora.")

    def reindex(self) -> None:
        """Indexa em lotes, um lote por vez em segundo plano (o banco é lido na thread da interface)."""
        if self.index is None:
            return
        idx = self.index
        todo = idx.pending()
        if not todo:
            return
        self.index_btn.setEnabled(False)

        def step(start: int) -> None:
            chunk = todo[start:start + 16]
            if not chunk:
                self._update_counts()
                notify(self, "Índice semântico atualizado.", "success")
                return
            texts = [idx.entity_text(e) for e in chunk]
            self.status.set_text(f"Indexando {start + len(chunk)}/{len(todo)}…")
            run_async(self, lambda: idx.embed(texts), lambda vecs: (idx.store_vectors(chunk, vecs), step(start + 16)),
                      self._unavailable)

        step(0)

    def search(self) -> None:
        q = self.query.text().strip()
        if not q or self.index is None:
            return
        idx = self.index
        run_async(self, lambda: idx.embed([q])[0], lambda vec: self._show(idx.search_vector(vec, k=20)),
                  lambda m: notify(self, m, "danger"))

    def _show(self, hits: list[Any]) -> None:
        _clear(self.results)
        if not hits:
            self.results.addWidget(EmptyState("file-search", "Nada parecido encontrado",
                                              "Indexe o projeto ou descreva de outro jeito."))
        for h in hits:
            row = QHBoxLayout()
            row.addWidget(Badge(f"{h.score:.0%}", "accent"))
            row.addWidget(text(f"{h.display_name}  ·  {h.type_label}"), 1)
            row.addWidget(Button("Abrir", "ghost", "arrow-up-right", size="sm",
                                 on_click=lambda e=h.entity_id: self.open_entity.emit(e)))
            w = QWidget()
            w.setLayout(row)
            self.results.addWidget(w)
        self.results.addStretch(1)
