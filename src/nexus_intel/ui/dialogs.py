"""Diálogos de cadastro: entidade (com aviso de duplicata), afirmação, relação e fonte."""

from __future__ import annotations

from shiboken6 import isValid

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from nexus_intel.application.project_store import ProjectStore
from nexus_intel.domain.errors import NexusError
from nexus_intel.domain.model import (
    CREDIBILITY_LABELS,
    EPISTEMIC_LABELS,
    IDENTIFIER_SCHEMES,
    RELIABILITY_LABELS,
    SOURCE_KINDS,
    Epistemic,
)
from nexus_intel.ui.common import button, hbox, label, show_error


def status_combo(default: str = "unverified") -> QComboBox:
    c = QComboBox()
    for st in Epistemic:
        c.addItem(EPISTEMIC_LABELS[st], st.value)
    c.setCurrentIndex(max(0, c.findData(default)))
    return c


def credibility_combo() -> QComboBox:
    c = QComboBox()
    c.addItem("— não avaliada —", None)
    for k, v in CREDIBILITY_LABELS.items():
        c.addItem(v, k)
    return c


class SourcePicker(QWidget):
    """Escolhe uma fonte existente ou cria uma nova na hora."""

    def __init__(self, store: ProjectStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.combo = QComboBox()
        self.combo.setMinimumWidth(260)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(hbox(self.combo, button("Nova fonte…", self._new)))
        self._fill()

    def _fill(self, select: str | None = None) -> None:
        self.combo.clear()
        self.combo.addItem("— sem fonte —", None)
        for s in self.store.list_sources():
            mark = " (desacreditada)" if s["is_discredited"] else ""
            rel = f"[{s['reliability']}] " if s["reliability"] else ""
            self.combo.addItem(f"{rel}{s['title']}{mark}", s["id"])
        if select:
            self.combo.setCurrentIndex(self.combo.findData(select))

    def _new(self) -> None:
        dlg = SourceDialog(self.store, self)
        if dlg.exec() and dlg.source_id:
            self._fill(dlg.source_id)

    def value(self) -> str | None:
        data = self.combo.currentData()
        return str(data) if data else None


class EntityPicker(QWidget):
    """Busca e seleção de uma entidade do projeto."""

    def __init__(self, store: ProjectStore, exclude: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.exclude = exclude
        self.query = QLineEdit()
        self.query.setPlaceholderText("Digite para buscar…")
        self.results = QListWidget()
        self.results.setFixedHeight(140)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.query)
        lay.addWidget(self.results)
        self.query.textChanged.connect(self._search)
        self._search("")

    def _search(self, text: str) -> None:
        self.results.clear()
        rows = self.store.search(text, 30) if text.strip() else self.store.list_entities(limit=30)
        for r in rows:
            if r["id"] == self.exclude:
                continue
            item = QListWidgetItem(f"{r['display_name']}  ·  {r['type_label']}")
            item.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.results.addItem(item)
        if self.results.count():
            self.results.setCurrentRow(0)

    def value(self) -> str | None:
        item = self.results.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None


class SourceDialog(QDialog):
    def __init__(self, store: ProjectStore, parent: QWidget | None = None, source: dict[str, Any] | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.source = source
        self.source_id: str | None = source["id"] if source else None
        self.setWindowTitle("Editar fonte" if source else "Nova fonte")
        self.setMinimumWidth(520)
        s = source or {}
        self.title = QLineEdit(s.get("title", ""))
        self.kind = QComboBox()
        for k, v in SOURCE_KINDS.items():
            self.kind.addItem(v, k)
        self.kind.setCurrentIndex(max(0, self.kind.findData(s.get("kind", "other"))))
        self.url = QLineEdit(s.get("url") or "")
        self.author = QLineEdit(s.get("author") or "")
        self.published = QLineEdit(s.get("published_at") or "")
        self.published.setPlaceholderText("ex.: 2025-03-14")
        self.accessed = QLineEdit(s.get("accessed_at") or "")
        self.accessed.setPlaceholderText("data em que você consultou")
        self.reliability = QComboBox()
        self.reliability.addItem("— não avaliada —", None)
        for k, v in RELIABILITY_LABELS.items():
            self.reliability.addItem(v, k)
        if s.get("reliability"):
            self.reliability.setCurrentIndex(self.reliability.findData(s["reliability"]))
        self.note = QPlainTextEdit(s.get("note", ""))
        self.note.setFixedHeight(70)
        from PySide6.QtWidgets import QCheckBox

        self.discredited = QCheckBox("Fonte desacreditada (afirmações que dependem só dela serão sinalizadas)")
        self.discredited.setChecked(bool(s.get("is_discredited")))
        form = QFormLayout(self)
        form.addRow("Título *", self.title)
        form.addRow("Tipo", self.kind)
        form.addRow("URL", self.url)
        form.addRow("Autor", self.author)
        form.addRow("Publicada em", self.published)
        form.addRow("Consultada em", self.accessed)
        form.addRow("Confiabilidade", self.reliability)
        form.addRow("Observações", self.note)
        if source:
            form.addRow(self.discredited)
        form.addRow(hbox(None, button("Cancelar", self.reject), button("Salvar", self.accept, "Primary")))

    def accept(self) -> None:
        data = dict(
            title=self.title.text(), kind=self.kind.currentData(), url=self.url.text().strip(),
            author=self.author.text().strip(), published_at=self.published.text().strip(),
            accessed_at=self.accessed.text().strip(), reliability=self.reliability.currentData(),
            note=self.note.toPlainText(),
        )
        try:
            if self.source:
                self.store.update_source(self.source["id"], self.source["version"],
                                         is_discredited=int(self.discredited.isChecked()), **data)
            else:
                self.source_id = self.store.create_source(**data)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc)
            return
        super().accept()


class NewEntityDialog(QDialog):
    """Cadastro com verificação de duplicatas antes de gravar (seção 9.4)."""

    def __init__(self, store: ProjectStore, parent: QWidget | None = None, type_key: str | None = None,
                 name: str = "") -> None:
        super().__init__(parent)
        self.store = store
        self.entity_id: str | None = None
        self.existing_id: str | None = None
        self.setWindowTitle("Nova entidade")
        self.setMinimumWidth(520)
        self.type = QComboBox()
        for t in store.entity_types():
            self.type.addItem(t["label"], t["key"])
        if type_key:
            self.type.setCurrentIndex(self.type.findData(type_key))
        self.name = QLineEdit(name)
        self.summary = QLineEdit()
        self.aliases = QLineEdit()
        self.aliases.setPlaceholderText("separados por ponto e vírgula")
        self.id_scheme = QComboBox()
        self.id_scheme.addItem("— nenhum —", None)
        for k, v in IDENTIFIER_SCHEMES.items():
            self.id_scheme.addItem(v, k)
        self.id_value = QLineEdit()
        self.importance = QSpinBox()
        self.importance.setRange(1, 5)
        self.importance.setValue(3)
        self.warning = label("", "Warning", wrap=True)
        self.candidates = QListWidget()
        self.candidates.hide()
        self.use_existing = button("Abrir a existente", self._use_existing)
        self.use_existing.hide()
        self.save = button("Criar", self.accept, "Primary")
        form = QFormLayout(self)
        form.addRow("Tipo", self.type)
        form.addRow("Nome *", self.name)
        form.addRow("Resumo", self.summary)
        form.addRow("Outros nomes", self.aliases)
        form.addRow("Identificador", hbox(self.id_scheme, self.id_value))
        form.addRow("Importância (1–5)", self.importance)
        form.addRow(self.warning)
        form.addRow(self.candidates)
        form.addRow(hbox(self.use_existing, None, button("Cancelar", self.reject), self.save))
        self._checked = False
        self.name.textChanged.connect(self._reset_check)
        self.id_value.textChanged.connect(self._reset_check)

    def _reset_check(self) -> None:
        self._checked = False
        self.save.setText("Criar")

    def _identifiers(self) -> list[tuple[str, str]]:
        scheme = self.id_scheme.currentData()
        return [(scheme, self.id_value.text())] if scheme and self.id_value.text().strip() else []

    def _use_existing(self) -> None:
        item = self.candidates.currentItem()
        if item:
            self.existing_id = item.data(Qt.ItemDataRole.UserRole)
            super().accept()

    def accept(self) -> None:
        if not self.name.text().strip():
            self.name.setFocus()
            return
        if not self._checked:
            tid = self.store.entity_type(self.type.currentData())["id"]
            cands = self.store.find_duplicates(self.name.text(), tid, self._identifiers())
            self._checked = True
            if cands:
                self.candidates.clear()
                for c in cands[:8]:
                    item = QListWidgetItem(f"{c.display_name}  —  {c.score}%  ({'; '.join(c.reasons)})")
                    item.setData(Qt.ItemDataRole.UserRole, c.entity_id)
                    self.candidates.addItem(item)
                self.candidates.setCurrentRow(0)
                self.candidates.show()
                self.use_existing.show()
                self.warning.setText("Possível duplicata: já existe algo parecido. Abra a existente "
                                     "ou clique de novo para criar mesmo assim.")
                self.save.setText("Criar mesmo assim")
                return
        try:
            self.entity_id = self.store.create_entity(
                self.type.currentData(), self.name.text(), summary=self.summary.text(),
                importance=self.importance.value(),
                aliases=[a for a in self.aliases.text().split(";") if a.strip()],
                identifiers=self._identifiers())
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc)
            return
        super().accept()


class ClaimDialog(QDialog):
    """Nova afirmação ou edição (valor, status, credibilidade, validade, fonte)."""

    def __init__(self, store: ProjectStore, entity_id: str, parent: QWidget | None = None,
                 claim: dict[str, Any] | None = None, field_key: str | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.entity_id = entity_id
        self.claim = claim
        self.setWindowTitle("Editar afirmação" if claim else "Nova afirmação")
        self.setMinimumWidth(520)
        e = store.get_entity(entity_id)
        self.fields = store.fields_for_type(e["type_id"])
        self.field = QComboBox()
        for f in self.fields:
            self.field.addItem(f["label"] + (" (sensível)" if f["is_sensitive"] else ""), f["id"])
        if claim:
            self.field.setCurrentIndex(self.field.findData(claim["field_def_id"]))
            self.field.setEnabled(False)
        elif field_key:
            for i, f in enumerate(self.fields):
                if f["key"] == field_key:
                    self.field.setCurrentIndex(i)
        self.value = QLineEdit(claim.get("value_text") or "" if claim else "")
        self.enum = QComboBox()
        self.entity_value = EntityPicker(store, exclude=entity_id)
        self.hint = label("", "Muted")
        self.status = status_combo(claim["epistemic_status"] if claim else "unverified")
        self._status_touched = bool(claim)
        self.status.activated.connect(lambda _: setattr(self, "_status_touched", True))
        self.cred = credibility_combo()
        if claim and claim.get("credibility"):
            self.cred.setCurrentIndex(self.cred.findData(claim["credibility"]))
        self.valid_from = QLineEdit(claim.get("valid_from") or "" if claim else "")
        self.valid_from.setPlaceholderText("desde (opcional, ex.: 2020-05)")
        self.valid_to = QLineEdit(claim.get("valid_to") or "" if claim else "")
        self.valid_to.setPlaceholderText("até (vazio = ainda vale)")
        self.review = QLineEdit(claim.get("review_at") or "" if claim else "")
        self.review.setPlaceholderText("revisar em (AAAA-MM-DD)")
        self.note = QPlainTextEdit(claim.get("note", "") if claim else "")
        self.note.setFixedHeight(60)
        self.source = SourcePicker(store)
        self.excerpt = QLineEdit()
        self.excerpt.setPlaceholderText("trecho da fonte que sustenta o valor")
        self.locator = QLineEdit()
        self.locator.setPlaceholderText("página, minuto, seção…")
        self.source.combo.currentIndexChanged.connect(self._source_changed)

        form = QFormLayout(self)
        form.addRow("Campo", self.field)
        form.addRow("Valor *", self.value)
        form.addRow("", self.enum)
        form.addRow("", self.entity_value)
        form.addRow("", self.hint)
        form.addRow("Status", self.status)
        form.addRow("Credibilidade", self.cred)
        form.addRow("Validade", hbox(self.valid_from, self.valid_to))
        form.addRow("Revisão", self.review)
        form.addRow("Observação", self.note)
        if not claim:
            form.addRow("Fonte", self.source)
            form.addRow("Trecho", self.excerpt)
            form.addRow("Localizador", self.locator)
        form.addRow(hbox(None, button("Cancelar", self.reject), button("Salvar", self.accept, "Primary")))
        self.field.currentIndexChanged.connect(self._field_changed)
        self._field_changed()

    def _current_field(self) -> dict[str, Any]:
        return self.fields[self.field.currentIndex()]

    def _field_changed(self) -> None:
        if not isValid(self) or not isValid(self.hint):
            return
        import json

        f = self._current_field()
        dt = f["datatype"]
        self.value.setVisible(dt not in {"enum", "entity"})
        self.enum.setVisible(dt == "enum")
        self.entity_value.setVisible(dt == "entity")
        if dt == "enum":
            self.enum.clear()
            for opt in json.loads(f["enum_options_json"] or "[]"):
                self.enum.addItem(opt)
            if self.claim and self.claim.get("value_text"):
                self.enum.setCurrentText(self.claim["value_text"])
        hints = {
            "date": "Aceita 1998 · 03/1998 · 15/03/1998 · década de 1990 · c. 1850",
            "number": "Número; vírgula decimal aceita (1.234,56)",
            "bool": "sim / não",
            "email": "nome@dominio.com",
            "url": "https://…",
        }
        self.hint.setText(hints.get(dt, ""))
        self.hint.setVisible(bool(self.hint.text()))
        rule = f["conflict_rule"]
        if rule == "single_per_period":
            self.hint.setText((self.hint.text() + "  ·  " if self.hint.text() else "")
                              + "Pode mudar com o tempo: informe a validade.")
            self.hint.show()

    def _source_changed(self) -> None:
        if not isValid(self) or not isValid(self.status):
            return
        if not self._status_touched:
            self.status.setCurrentIndex(self.status.findData("reported" if self.source.value() else "unverified"))

    def _raw_value(self) -> Any:
        dt = self._current_field()["datatype"]
        if dt == "enum":
            return self.enum.currentText()
        if dt == "entity":
            return self.entity_value.value()
        return self.value.text()

    def accept(self) -> None:
        raw = self._raw_value()
        if raw in (None, ""):
            show_error(self, NexusError("Informe um valor."))
            return
        try:
            if self.claim:
                self.store.update_claim(
                    self.claim["id"], self.claim["version"], value=raw,
                    epistemic_status=self.status.currentData(), credibility=self.cred.currentData(),
                    valid_from=self.valid_from.text().strip() or None,
                    valid_to=self.valid_to.text().strip() or None,
                    review_at=self.review.text().strip() or None, note=self.note.toPlainText())
            else:
                self.store.add_claim(
                    self.entity_id, self._current_field()["id"], raw, status=self.status.currentData(),
                    credibility=self.cred.currentData(), valid_from=self.valid_from.text().strip() or None,
                    valid_to=self.valid_to.text().strip() or None, note=self.note.toPlainText(),
                    source_id=self.source.value(), excerpt=self.excerpt.text(), locator=self.locator.text(),
                    review_at=self.review.text().strip() or None)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc)
            return
        super().accept()


class RelationDialog(QDialog):
    def __init__(self, store: ProjectStore, source_entity: str, parent: QWidget | None = None,
                 relation: dict[str, Any] | None = None, target_entity: str | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.source_entity = source_entity
        self.relation = relation
        self.setWindowTitle("Editar relação" if relation else "Nova relação")
        self.setMinimumWidth(520)
        src = store.get_entity(source_entity)
        self.type = QComboBox()
        for rt in store.relation_types():
            self.type.addItem(rt["label"], rt["key"])
        self.target = EntityPicker(store, exclude=source_entity)
        self.reverse = QComboBox()
        self.reverse.addItem(f"{src['display_name']}  →  outra", False)
        self.reverse.addItem(f"outra  →  {src['display_name']}", True)
        r = relation or {}
        self.desc = QLineEdit(r.get("description", ""))
        self.status = status_combo(r.get("epistemic_status", "unverified"))
        self._status_touched = bool(relation)
        self.status.activated.connect(lambda _: setattr(self, "_status_touched", True))
        self.cred = credibility_combo()
        if r.get("credibility"):
            self.cred.setCurrentIndex(self.cred.findData(r["credibility"]))
        self.valid_from = QLineEdit(r.get("valid_from") or "")
        self.valid_from.setPlaceholderText("desde (opcional)")
        self.valid_to = QLineEdit(r.get("valid_to") or "")
        self.valid_to.setPlaceholderText("até (vazio = vigente)")
        self.source = SourcePicker(store)
        self.source.combo.currentIndexChanged.connect(self._source_changed)
        self.excerpt = QLineEdit()
        self.excerpt.setPlaceholderText("trecho da fonte")

        form = QFormLayout(self)
        form.addRow("De", label(src["display_name"]))
        form.addRow("Tipo", self.type)
        if relation:
            self.type.setCurrentIndex(self.type.findData(r["type_key"]))
            form.addRow("Para", label(r.get("other_name", "")))
        else:
            form.addRow("Para", self.target)
            form.addRow("Direção", self.reverse)
            if target_entity:
                self.target.query.setText(store.get_entity(target_entity)["display_name"])
        form.addRow("Descrição", self.desc)
        form.addRow("Status", self.status)
        form.addRow("Credibilidade", self.cred)
        form.addRow("Validade", hbox(self.valid_from, self.valid_to))
        if not relation:
            form.addRow("Fonte", self.source)
            form.addRow("Trecho", self.excerpt)
        form.addRow(hbox(None, button("Cancelar", self.reject), button("Salvar", self.accept, "Primary")))

    def _source_changed(self) -> None:
        if not isValid(self) or not isValid(self.status):
            return
        if not self._status_touched:
            self.status.setCurrentIndex(self.status.findData("reported" if self.source.value() else "unverified"))

    def accept(self) -> None:
        try:
            common = dict(description=self.desc.text(), epistemic_status=self.status.currentData(),
                          credibility=self.cred.currentData(),
                          valid_from=self.valid_from.text().strip() or None,
                          valid_to=self.valid_to.text().strip() or None)
            if self.relation:
                self.store.update_relation(self.relation["id"], self.relation["version"],
                                           type_id=self.type.currentData(), **common)
            else:
                other = self.target.value()
                if not other:
                    raise NexusError("Escolha a outra entidade.")
                a, b = (other, self.source_entity) if self.reverse.currentData() else (self.source_entity, other)
                self.store.create_relation(
                    self.type.currentData(), a, b, status=common.pop("epistemic_status"),
                    evidence_source=self.source.value(), excerpt=self.excerpt.text(), **common)
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc)
            return
        super().accept()


class EvidenceDialog(QDialog):
    """Adiciona uma fonte a uma afirmação ou relação existente."""

    def __init__(self, store: ProjectStore, kind: str, target_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store, self.kind, self.target_id = store, kind, target_id
        self.setWindowTitle("Adicionar fonte")
        self.setMinimumWidth(480)
        self.source = SourcePicker(store)
        self.excerpt = QLineEdit()
        self.locator = QLineEdit()
        form = QFormLayout(self)
        form.addRow("Fonte", self.source)
        form.addRow("Trecho", self.excerpt)
        form.addRow("Localizador", self.locator)
        form.addRow(hbox(None, button("Cancelar", self.reject), button("Adicionar", self.accept, "Primary")))

    def accept(self) -> None:
        sid = self.source.value()
        if not sid:
            show_error(self, NexusError("Escolha ou crie uma fonte."))
            return
        try:
            self.store.add_evidence(sid, self.kind, self.target_id, self.excerpt.text(), self.locator.text())
        except Exception as exc:  # noqa: BLE001
            show_error(self, exc)
            return
        super().accept()
