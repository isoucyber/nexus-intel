"""Módulos do projeto que ainda não têm backend (0.3, seções 7 e 8).

Regra: nenhuma informação simulada. Cada página mostra o que já existe de verdade,
o que falta e o próximo passo concreto. Importação/Exportação e Backup também
exibem o que o sistema realmente oferece hoje.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from nexus_intel.ui import format as fmt
from nexus_intel.ui.common import Page
from nexus_intel.ui.design import assets, tokens
from nexus_intel.ui.design.components import (
    Badge,
    Button,
    Card,
    CitationBadge,
    SectionHeader,
    text,
)
from nexus_intel.ui.design.table import Column, DataTable


@dataclass(frozen=True)
class ModuleSpec:
    key: str
    title: str
    icon: str
    summary: str
    exists: tuple[str, ...]
    missing: tuple[str, ...]
    next_step: str


SPECS: dict[str, ModuleSpec] = {s.key: s for s in (
    ModuleSpec(
        "attachments", "Anexos cifrados", "file-text",
        "Guardar documentos, imagens e áudios dentro do projeto, cifrados com a chave do próprio projeto.",
        ("Chave exclusiva por projeto e cifragem AES-256-GCM já usadas pelo banco do projeto.",
         "Fontes e evidências que poderão apontar para um anexo."),
        ("Armazenamento de arquivos cifrados por projeto (tabela e pasta).",
         "Fluxo para abrir um anexo decifrando-o só na memória.",
         "Verificação de integridade (hash) de cada arquivo."),
        "Criar o armazenamento cifrado de anexos e a tabela de metadados (nome, tipo, tamanho, data, hash)."),
    ModuleSpec(
        "map", "Mapa offline", "map-pin",
        "Ver localizações do projeto (como Veneza) num mapa que funciona sem internet.",
        ("Entidades do tipo Localização com campos de latitude e longitude.",),
        ("Dados cartográficos locais (ex.: arquivo MBTiles da região) instalados no computador.",
         "Componente que desenha o mapa a partir desses dados, sem nenhuma requisição de rede.",
         "Ligação entre pontos do mapa, entidades e evidências."),
        "Escolher o pacote cartográfico local e o renderizador offline; validar com a rede desligada."),
    ModuleSpec(
        "ai", "IA e análises", "sparkles",
        "Perguntar sobre o projeto e receber respostas com citações das fontes.",
        ("Proveniência completa: cada afirmação e relação já aponta para fontes, trechos e status.",
         "Decisão registrada: Ollama local por padrão; nuvem opcional, desligada, com chave no cofre."),
        ("Conexão com o mecanismo de IA (Ollama local) e detecção de disponibilidade.",
         "Ferramentas de consulta aos dados do projeto para a IA (sem enviar o banco inteiro).",
         "Painel de conversa com respostas citadas."),
        "Integrar o Ollama local com detecção de disponibilidade e as ferramentas de leitura do projeto."),
    ModuleSpec(
        "semantic", "Busca semântica", "file-search",
        "Encontrar informações pelo significado, não só pelas palavras exatas.",
        ("Busca textual completa (Ctrl+K), sem acento, com prefixo, frase exata e filtros por tipo e etiqueta.",),
        ("Geração de embeddings (vetores) com um modelo local.",
         "Índice vetorial por projeto, cifrado junto com o projeto.",
         "Estados de indexação e reindexação."),
        "Escolher o modelo local de embeddings e criar o índice dentro do arquivo do projeto."),
    ModuleSpec(
        "suggestions", "Sugestões e aprovações", "git-merge",
        "A IA propõe conexões e pontos a investigar; nada entra no projeto sem a sua aprovação.",
        ("Fluxo humano de mesclagem de duplicatas com decisões registradas.",
         "Log de auditoria encadeado, onde cada aprovação ou rejeição será registrada."),
        ("Geração de sugestões pela IA (depende do módulo IA e análises).",
         "Registro de sugestões com estado pendente, aprovada ou rejeitada, justificativa e motivo.",
         "Aplicar uma sugestão aprovada pelo fluxo normal de criação de relações."),
        "Depois da integração com a IA, criar o registro de sugestões e o histórico de decisões."),
)}

NEXT_PREFIX = "Próximo passo: "


def _bullets(items: tuple[str, ...], icon: str, color: str) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    for it in items:
        row = QHBoxLayout()
        row.setSpacing(8)
        ic = QLabel()
        ic.setPixmap(assets.pixmap(icon, color, 14))
        row.addWidget(ic, 0)
        row.addWidget(text(it, "secondary", wrap=True), 1)
        lay.addLayout(row)
    return w


class PendingModulePage(Page):
    """Contêiner honesto de um módulo em preparação."""

    def __init__(self, spec: ModuleSpec, extra: QWidget | None = None) -> None:
        super().__init__()
        self.spec = spec
        t = tokens.current()
        self.status = Badge("Em preparação", "neutral", "clock",
                            "Este módulo ainda não foi implementado; nada aqui é simulado")
        self.layout_.addWidget(SectionHeader(spec.title, spec.summary, [self.status]))
        if extra is not None:
            self.layout_.addWidget(extra)
        row = QHBoxLayout()
        row.setSpacing(12)
        have = Card("O que já existe", icon="circle-check")
        have.add(_bullets(spec.exists, "check", t.success))
        have.body.addStretch(1)
        need = Card("O que falta", icon="circle-dashed")
        need.add(_bullets(spec.missing, "minus", t.text_muted))
        need.body.addStretch(1)
        row.addWidget(have, 1)
        row.addWidget(need, 1)
        self.layout_.addLayout(row)
        self.next_label = text(NEXT_PREFIX + spec.next_step, "muted", wrap=True)
        self.layout_.addWidget(self.next_label)
        self.layout_.addStretch(1)

    def refresh(self) -> None:
        """Nada a carregar: não há fonte de dados para este módulo."""


def ai_engine_indicator() -> QWidget:
    """Mecanismo de IA: hoje sempre “Indisponível” (não há integração para consultar)."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    lay.addWidget(text("Mecanismo de IA:", "secondary"))
    lay.addWidget(Badge("Indisponível — não implementado", "neutral", "circle-x",
                        "Nenhum mecanismo de IA está integrado. Quando estiver, aparecerá aqui se é Local "
                        "(no seu computador) ou Externo (dados enviados a um serviço remoto)."))
    lay.addStretch(1)
    return w


def map_data_indicator() -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(Badge("Dados cartográficos ausentes", "neutral", "map-pin",
                        "Nenhum dado de mapa local está instalado. Nenhuma requisição de rede é feita."))
    lay.addStretch(1)
    return w


def citation_legend() -> QWidget:
    """Legenda de como as afirmações da IA serão classificadas (seção 8.4). Não contém dados."""
    card = Card("Como as respostas da IA serão classificadas", icon="shield-check",
                subtitle="Nenhuma saída da IA será apresentada como fato sem evidência.")
    row = QHBoxLayout()
    row.setSpacing(8)
    for kind in ("documented", "interpretation", "unverified"):
        row.addWidget(CitationBadge(kind))
    row.addStretch(1)
    card.body.addLayout(row)
    return card


def make_pending(key: str) -> PendingModulePage:
    extra = {"ai": ai_engine_indicator, "map": map_data_indicator,
             "suggestions": citation_legend}.get(key)
    return PendingModulePage(SPECS[key], extra() if extra else None)


# ------------------------------------------------------------------ importação e exportação
class ImportExportPage(Page):
    """Agrupa o que existe hoje (imagem do grafo) e marca o que não existe."""

    def __init__(self, export_graph: Callable[[], Any]) -> None:
        super().__init__()
        self.layout_.addWidget(SectionHeader(
            "Importação e exportação",
            "Saídas e entradas de dados do projeto. Só aparecem como disponíveis as que já funcionam."))
        exp = Card("Exportação", icon="download")
        self.export_btn = Button("Exportar imagem do grafo (PNG)", "primary", "image", on_click=export_graph)
        exp.add(_line("Imagem do grafo (PNG)", "Disponível", "success", self.export_btn,
                      "Você escolhe a pasta e o nome; o local é mostrado ao concluir."))
        exp.add(_line("Dados do projeto (JSON, CSV)", "Não implementado", "neutral", None,
                      "Ainda não há formato de exportação de dados."))
        imp = Card("Importação", icon="upload")
        imp.add(_line("Planilhas, JSON e outros formatos", "Não implementado", "neutral", None,
                      "Ainda não há importação. Quando houver, nada será sobrescrito sem confirmação."))
        self.layout_.addWidget(exp)
        self.layout_.addWidget(imp)
        self.layout_.addStretch(1)

    def refresh(self) -> None:
        """Estado fixo por natureza: reflete o que está implementado nesta versão."""


def _line(title: str, state: str, tone: str, action: QWidget | None, hint: str) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 4, 0, 4)
    lay.setSpacing(10)
    col = QVBoxLayout()
    col.setSpacing(2)
    col.addWidget(text(title, "h3"))
    col.addWidget(text(hint, "caption", wrap=True))
    lay.addLayout(col, 1)
    lay.addWidget(Badge(state, tone))
    if action is not None:
        lay.addWidget(action)
    return w


# ------------------------------------------------------------------ backup
def migration_copies(project_path: Path | None) -> list[dict[str, Any]]:
    """Cópias reais criadas antes de atualizar a estrutura do banco (migrate.backup_file).
    Lê só nome, data e tamanho; o conteúdo continua cifrado."""
    if project_path is None or not project_path.parent.exists():
        return []
    rows = []
    for f in sorted(project_path.parent.glob(f"{project_path.stem}.pre-v*{project_path.suffix}")):
        st = f.stat()
        rows.append({"name": f.name, "when": datetime.fromtimestamp(st.st_mtime, UTC).isoformat(),
                     "size": f"{st.st_size / 1024:.0f} KB"})
    rows.sort(key=lambda r: r["when"], reverse=True)
    return rows


class BackupPage(Page):
    def __init__(self, project_path: Path | None) -> None:
        super().__init__()
        self.project_path = project_path
        self.layout_.addWidget(SectionHeader(
            "Backup", "Estado lido do sistema. Nenhum backup é mostrado como concluído sem um registro real.",
            [Badge("Em preparação", "neutral", "clock")]))
        auto = Card("Backup automático", icon="history")
        auto.add(_line("Estado", "Indisponível", "neutral", None,
                       "O backup agendado ainda não foi implementado: não há execuções nem falhas a mostrar."))
        auto.add(_line("Último backup concluído", "Sem registro", "neutral", None,
                       "Não existe registro de backup automático neste projeto."))
        self.layout_.addWidget(auto)
        copies = Card("Cópias automáticas antes de atualizações", icon="layers",
                      subtitle="Criadas pelo próprio NEXUS quando uma nova versão altera a estrutura do banco. "
                               "Ficam na pasta do projeto e continuam cifradas.")
        self.table = DataTable([Column("name", "Arquivo", "mono", stretch=True),
                                Column("when", "Criada", "reltime", width=130),
                                Column("size", "Tamanho", "number", width=90)])
        self.table.setMinimumHeight(120)
        self.none_label = text("Nenhuma cópia encontrada: a estrutura do banco deste projeto ainda não foi "
                               "atualizada desde a criação.", "muted", wrap=True)
        copies.add(self.table)
        copies.add(self.none_label)
        self.layout_.addWidget(copies)
        self.layout_.addStretch(1)

    def refresh(self) -> None:
        rows = migration_copies(self.project_path)
        self.table.set_rows(rows)
        self.table.setVisible(bool(rows))
        self.none_label.setVisible(not rows)
        self.count = len(rows)


__all__ = ["SPECS", "BackupPage", "ImportExportPage", "PendingModulePage", "fmt", "make_pending",
           "migration_copies"]
