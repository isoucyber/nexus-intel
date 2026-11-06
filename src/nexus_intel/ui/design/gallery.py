"""Vitrine do design system: todos os componentes num tema.

Uso para desenvolvimento: python -m nexus_intel.ui.design.gallery [tema]
Também é fotografada pelo CI (tools/screenshots.py) em cada tema.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QCheckBox, QGridLayout, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from nexus_intel.ui.design import components as c
from nexus_intel.ui.design import tokens
from nexus_intel.ui.design.manager import apply_appearance
from nexus_intel.ui.design.table import Column, DataTable


class Gallery(QWidget):
    def __init__(self, theme: str = tokens.DEFAULT_THEME) -> None:
        super().__init__()
        apply_appearance(tokens.Appearance(theme=theme))
        t = tokens.current()
        self.setWindowTitle(f"Componentes — {t.label}")
        self.setProperty("page", "true")
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        root.addWidget(c.SectionHeader(f"Design system · {t.label}",
                                       "Tokens, componentes e estados. Todas as cores vêm dos tokens."))

        grid = QGridLayout()
        grid.setSpacing(16)
        root.addLayout(grid, 1)

        buttons = c.Card("Botões", icon="zap")
        row = QHBoxLayout()
        for label, variant, icon in (("Primário", "primary", "plus"), ("Secundário", "secondary", "filter"),
                                     ("Fantasma", "ghost", "refresh-cw"), ("Excluir", "danger", "trash-2")):
            row.addWidget(c.Button(label, variant, icon))
        disabled = c.Button("Desabilitado", "primary")
        disabled.setEnabled(False)
        row.addWidget(disabled)
        row.addWidget(c.IconButton("settings", "Configurações", variant="secondary"))
        row.addStretch(1)
        buttons.body.addLayout(row)
        kb = QHBoxLayout()
        for k in ("Ctrl+K", "Ctrl+N", "Ctrl+L", "Ctrl+J"):
            kb.addWidget(c.Kbd(k))
        kb.addStretch(1)
        buttons.body.addLayout(kb)
        grid.addWidget(buttons, 0, 0)

        fields = c.Card("Campos", icon="type")
        fields.add(c.Input("Buscar entidades…", icon="search", clearable=True))
        fields.add(c.Select([("Pessoa", "person"), ("Empresa", "company")], current="company"))
        cb = QCheckBox("Só relações verificadas")
        cb.setChecked(True)
        fields.add(cb)
        grid.addWidget(fields, 0, 1)

        chips = c.Card("Status e tipos", icon="layers")
        st = QHBoxLayout()
        for s in ("verified", "reported", "unverified", "hypothesis", "conflicting", "refuted"):
            st.addWidget(c.StatusBadge(s))
        st.addStretch(1)
        chips.body.addLayout(st)
        ty = QHBoxLayout()
        for k, label in (("person", "Pessoa"), ("company", "Empresa"), ("vehicle", "Veículo"),
                         ("location", "Localização"), ("domain", "Domínio")):
            ty.addWidget(c.EntityAvatar(k, 26, label))
            ty.addWidget(c.EntityTypeChip(k, label))
        ty.addStretch(1)
        chips.body.addLayout(ty)
        tones = QHBoxLayout()
        for tone in ("neutral", "accent", "success", "warning", "danger", "info"):
            tones.addWidget(c.Badge(tone.capitalize(), tone))
        tones.addStretch(1)
        chips.body.addLayout(tones)
        grid.addWidget(chips, 1, 0)

        bars = c.Card("Entidades por tipo", icon="list")
        bars.add(c.BarList([
            c.BarRow("person", "Pessoa", 11, lambda t: t.type_color("person"), "user"),
            c.BarRow("location", "Localização", 6, lambda t: t.type_color("location"), "map-pin"),
            c.BarRow("company", "Empresa", 6, lambda t: t.type_color("company"), "building-2"),
            c.BarRow("vehicle", "Veículo", 3, lambda t: t.type_color("vehicle"), "car"),
        ]))
        grid.addWidget(bars, 1, 1)

        table = c.Card("Tabela virtualizada", icon="database")
        dt = DataTable([Column("display_name", "Nome", "entity", stretch=True),
                        Column("status", "Status", "status", width=150),
                        Column("updated_at", "Atualizada", "reltime", width=110)])
        dt.set_rows([
            {"display_name": "Helena Prado", "type_key": "person", "status": "verified",
             "updated_at": "2026-11-06T10:00:00+00:00"},
            {"display_name": "Aurora Logística Ltda. — um nome bem comprido para testar reticências",
             "type_key": "company", "status": "reported", "updated_at": "2026-11-01T10:00:00+00:00"},
            {"display_name": "Veneza", "type_key": "location", "status": "hypothesis", "updated_at": None},
        ])
        dt.setMinimumHeight(150)
        table.add(dt)
        grid.addWidget(table, 2, 0)

        states = c.Card("Estados", icon="inbox")
        states.add(c.Skeleton(3))
        states.add(c.EmptyState("inbox", "Nada por aqui ainda", "Crie a primeira entidade para começar.",
                                "Nova entidade"))
        grid.addWidget(states, 2, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)


def main() -> int:
    app = QApplication(sys.argv[:1])
    g = Gallery(sys.argv[1] if len(sys.argv) > 1 else tokens.DEFAULT_THEME)
    scroll = QScrollArea()
    scroll.setWidget(g)
    scroll.setWidgetResizable(True)
    scroll.resize(1280, 860)
    scroll.show()
    c.notify(g, "Entidade criada com sucesso.", "success")
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
