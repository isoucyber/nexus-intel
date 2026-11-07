# Auditoria F0 — NEXUS INTEL 0.2.0 → 0.3

Data: 2026-11-07 · Nenhum arquivo de código foi alterado nesta fase.

## 1. Stack e estrutura

| Item | Situação |
|---|---|
| Linguagem | Python 3.12 |
| Interface | **Qt 6 (PySide6) com Qt Widgets**, aplicativo desktop nativo. Não é web, Electron nem Tauri |
| Empacotamento | PyInstaller (modo pasta) + Inno Setup, gerados pelo GitHub Actions |
| Estilos | QSS (a "CSS" do Qt) **gerado** a partir de tokens em `ui/design/tokens.py` → `ui/design/qss.py`. Componentes que se desenham sozinhos leem os tokens diretamente |
| Layout | Gerenciadores de layout do Qt (`QVBoxLayout`, `QHBoxLayout`, `QGridLayout`), não CSS. Os conceitos de `height:100%`, `flex-grow` e `align-items:stretch` têm equivalentes diretos (size policy, stretch, alinhamento por item) |
| Pastas | `domain/` (regras puras) · `application/` (casos de uso, SQL) · `infrastructure/` (cripto, banco, arquivos) · `ui/` (telas) · `ui/design/` (design system) |

## 2. Tela inicial

| Responsabilidade | Arquivo |
|---|---|
| Lista de projetos, cards, novo projeto, excluir | `src/nexus_intel/ui/projects_page.py` (`ProjectsPage`, `_card`, `NewProjectDialog`) |
| Cartão genérico | `src/nexus_intel/ui/design/components.py` (`Card`) via `ui/common.py` (`card()`) |
| Dados dos projetos | `src/nexus_intel/application/projects.py` (`ProjectManager.list()`, tabela `project_registry` do banco da aplicação) |

## 3. Causa-raiz dos cards gigantes

Equivalências CSS entre parênteses.

1. **`projects_page.py:113` — `scroll.setWidgetResizable(True)`**: o contêiner da grade é esticado até a altura da janela (`height: 100%` herdado do pai).
2. **`projects_page.py:111` — `grid.setAlignment(AlignTop | AlignLeft)`**: o alinhamento foi aplicado ao *layout*, não aos *itens*. As linhas do `QGridLayout` continuam dividindo a altura disponível, então uma única linha ocupa a janela inteira (`grid-auto-rows: 1fr` + `align-items: stretch`).
3. **`projects_page.py:135` — `addWidget(card, i // 3, i % 3)`**: os cards são adicionados sem alinhamento por item e com política de tamanho vertical expansível, então crescem até o tamanho da célula (`flex-grow: 1`).
4. **`components.py:436` — `outer.addLayout(self.body, 1)`**: o corpo do `Card` tem fator de esticamento 1, e o espaço extra é distribuído entre título, metadados e botões. Por isso aparecem os grandes vazios internos (`justify-content: space-between` num contêiner esticado).
5. **`projects_page.py:147` — `setFixedWidth(320)`** e **colunas fixas em 3** (`i // 3`): não há responsividade (`grid-template-columns: repeat(3, 320px)`).
6. **`projects_page.py:139`**: a faixa colorida é uma borda do rótulo do título, que também estica junto, formando a barra vertical alta.

## 4. Tokens de design existentes

Centralizados em `ui/design/tokens.py`: 6 temas; cores semânticas (`bg`, `surface`, `surface_elevated`, `border`, `text_*`, `accent*`, `success`, `warning`, `danger`, `info`); cores por status epistêmico e por tipo de entidade; tipografia 12–32 px (Inter e JetBrains Mono); espaçamento 4–32; raios 4–14; sombras sm/md/lg; durações 120/160/200 ms; densidade e preferência de movimento. Um teste impede cores fixas fora dos tokens. **Nada novo será espalhado: o que faltar entra nesse arquivo.**

## 5. Navegação

Login → **Projetos** (`ProjectsPage`) → *Abrir* → **Área do projeto** (`ui/workspace.py`, `Workspace`), com barra lateral de 7 seções (Início, Central de Informações, Grafo, Fontes, Qualidade, Lixeira, Auditoria). Fichas de entidade abrem em abas. O botão "Projetos" na barra lateral volta à lista. Ctrl+L bloqueia em qualquer tela.

## 6. Inventário de funcionalidades

| Recurso | Versão no pedido | Status | Evidência | Observações |
|---|---|---|---|---|
| Anexos cifrados | 0.2 | **Ausente** | Nenhuma tabela, arquivo ou tela de anexos. `vault.py:62` só menciona anexos num comentário | O modo de criptografia está pronto para cifrar arquivos (AES-256-GCM, chave por projeto), mas não há armazenamento de anexos |
| Mapa offline de Veneza | 0.2 | **Ausente** | Nenhum dado cartográfico (MBTiles/PMTiles/GeoJSON) nem biblioteca de mapa no projeto | Entidades do tipo Localização já têm campos de latitude/longitude |
| Linha do tempo | 0.2 | **Ausente** (dados parciais) | Não há módulo. Existem dados datados: afirmações de data com precisão (`claim.value_date_*`), validade de relações (`relation.valid_from/to`) e entidades do tipo Evento | Daria para montar uma linha do tempo real só com consultas de leitura |
| Importação/Exportação | 0.2 | **Ausente** | Só existe "Exportar PNG" do grafo (`graph_view.py:336`) | Nenhum formato de dados de projeto implementado |
| Backup automático | 0.2 | **Ausente** | Só a cópia de segurança antes de migrar o banco (`migrate.py:62`), que não é backup agendado e não tem registro de estado | Não há onde ler "último backup concluído" |
| IA local / externa | 0.3 | **Ausente** | Nenhum provedor, cliente HTTP ou configuração de IA | Decidido em 06/11: Ollama local por padrão, chave da nuvem no cofre do NEXUS |
| Busca semântica | 0.3 | **Ausente** | Só há busca textual FTS5 (`project_store.search`) | Sem embeddings nem índice vetorial |
| Sugestões inteligentes | 0.3 | **Ausente** | — | — |
| Citações verificadas | 0.3 | **Ausente para IA** | Existe proveniência humana: tabela `evidence` liga afirmações e relações a fontes com trecho e localizador | É a base natural para as citações da IA |
| Aprovação humana | 0.3 | **Ausente para IA** | Existe só para duplicatas (`dedupe_decision`) e o log de auditoria encadeado | O log já registraria decisões |

**Conclusão:** todos os recursos das seções 7.2 a 8.5 do pedido dependem de backend que não existe. A versão 0.2.0 publicada foi a fase de design system, não o roteiro de recursos que o README anunciava para "0.2".

## 7. Riscos e limitações

- **F3 e F4 seguindo o pedido à risca** (backend intocado) resultam em navegação com módulos quase todos em "Em preparação". É honesto, mas entrega pouco valor de uso.
- Implementar os recursos de verdade exige alterar o backend, o que a regra 3 proíbe sem aprovação. **A decisão é do usuário** (veja a pergunta no relatório da fase).
- "Quantidade de anexos" no card não tem fonte de dados e será exibida como **"Indisponível"** (regra 1).
- "Descrição curta" do card: a finalidade do projeto fica dentro do arquivo cifrado do projeto e só pode ser lida com ele aberto. O card usa a **categoria** (modelo do projeto), que fica no registro da aplicação.
- A contagem de entidades no card vem do registro e é atualizada quando o projeto é fechado. É real, mas reflete o último fechamento.
- O badge de versão mostrará a versão real do programa (hoje `0.2.0`), não "v0.3", até a versão ser de fato lançada.
- Os testes de interface rodam no CI (Windows e Linux), não neste ambiente, que não tem Qt.
