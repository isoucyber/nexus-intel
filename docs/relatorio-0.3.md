# Relatório final — NEXUS INTEL 0.3 (evolução do front-end)

Data: 2026-11-07 · Base: v0.2.0 · Entregue em: v0.3.0 (cards e tela inicial) e v0.3.1 (módulos e relatório).
Auditoria prévia (F0): [`docs/auditoria-0.3.md`](auditoria-0.3.md).

## 1. Resumo executivo

Os cards de projeto deixaram de esticar até a altura da janela. Agora têm 150 px de altura e as colunas
variam com a largura (3 colunas em 1024 px, 8 em 2560 px). A tela inicial ganhou contador real, pesquisa e
estados de carregando, vazio, erro e sem resultados. O projeto passou a ter navegação em Investigação,
Inteligência e Dados, com uma linha do tempo nova, feita com dados reais. Os módulos sem backend
(anexos, mapa, IA, busca semântica, sugestões e backup automático) aparecem como "Em preparação",
sem nenhum dado simulado. O backend não foi alterado.

## 2. Causa-raiz dos cards gigantes e correção

A interface é Qt Widgets, não CSS; os equivalentes estão entre parênteses.

| Origem (v0.2.0) | Efeito | Correção |
|---|---|---|
| `projects_page.py:113` `QScrollArea.setWidgetResizable(True)` (`height: 100%`) | contêiner da grade esticado até a altura da janela | a grade fica dentro de um contêiner com espaço elástico **abaixo** dela; a altura da grade é a soma das linhas |
| `projects_page.py:111` alinhamento no *layout* e não nos itens (`grid-auto-rows: 1fr` + `align-items: stretch`) | uma linha ocupava toda a altura | substituído por `ResponsiveGrid` (`ui/design/components.py`), que posiciona cada card com altura fixa (`align-items: start`) |
| `projects_page.py:135` colunas fixas `i // 3` e `:147` largura fixa 320 px (`grid-template-columns: repeat(3, 320px)`) | sem responsividade | colunas = ⌊(largura + espaço) / (280 + espaço)⌋, card entre 280 e 340 px (`repeat(auto-fill, minmax(280px, 340px))`) |
| `components.py:436` corpo do `Card` com fator de esticamento 1 (`flex-grow: 1`) | vazios enormes dentro do card | novo `ProjectCard` compacto; botões na base; altura = conteúdo, limitada a 150–190 px pelo token `CARD` |
| `projects_page.py:139` borda colorida no título | barra vertical alta | ponto de 8 px com a cor do projeto |

As medidas ficam num só lugar, `tokens.CARD` (`ui/design/tokens.py`). Nenhuma regra foi sobrescrita;
a origem foi substituída.

## 3. Arquivos modificados

| Arquivo | Tipo | Motivo |
|---|---|---|
| `src/nexus_intel/ui/design/tokens.py` | alterado | medidas do card (`CARD`) |
| `src/nexus_intel/ui/design/components.py` | alterado | `ResponsiveGrid`; tom discreto de exclusão em `Button`; `CitationBadge` |
| `src/nexus_intel/ui/design/qss.py` | alterado | estilos de exclusão discreta e de item de navegação em preparação |
| `src/nexus_intel/ui/projects_page.py` | reescrito (parcial) | `ProjectCard`, grade responsiva, cabeçalho, pesquisa e estados |
| `src/nexus_intel/ui/workspace.py` | alterado | navegação em grupos; novas páginas; nomes "Visão geral" e "Entidades" |
| `src/nexus_intel/ui/timeline_page.py` | novo | linha do tempo com dados reais |
| `src/nexus_intel/ui/module_pages.py` | novo | Importação/Exportação, Backup e páginas "Em preparação" |
| `src/nexus_intel/ui/graph_view.py` | alterado | exportação PNG informa nome e pasta do arquivo e pode ser chamada do módulo de Dados |
| `src/nexus_intel/ui/app.py` | alterado | passa o caminho do projeto à área de trabalho (para o módulo Backup) |
| `src/nexus_intel/__init__.py`, `pyproject.toml` | alterado | versão |
| `tests/ui/test_projects_grid.py` | novo | critérios de aceitação F1/F2 |
| `tests/integration/test_timeline.py` | novo | linha do tempo usa só dados reais |
| `tests/ui/test_design_components.py` | alterado | navegação por todos os módulos; veracidade de IA e backup |
| `tools/screenshots.py` | alterado | capturas em 5 resoluções e dos novos módulos |
| `docs/auditoria-0.3.md`, `docs/relatorio-0.3.md` | novos | F0 e F5 |

**Backend:** nenhum arquivo em `domain/`, `application/` ou `infrastructure/` foi alterado.

## 4. Recursos integrados (dados reais)

| Recurso | Fonte de dados |
|---|---|
| Card: nome, cor, categoria, cadeado | `project_registry` (`ProjectManager.list()`) |
| Card: número de entidades | `project_registry.entity_count`, gravado ao fechar o projeto |
| Card: última atividade | `last_opened_at` (ou `created_at` se nunca aberto), relativo + data completa na dica |
| Contador e pesquisa de projetos | lista real, filtrada na tela por nome e categoria |
| Linha do tempo | afirmações de campos de data (`claims_for`) e validade de relações (`relations_for`), com status, fontes (`evidence_for`) e link para a entidade |
| Exportação de imagem do grafo (PNG) | exportação já existente, agora também no módulo Dados, com nome e pasta mostrados ao concluir |
| Backup: cópias antes de atualizações | arquivos reais `*.pre-v*` criados por `migrate.backup_file` na pasta do projeto (nome, data, tamanho) |
| Selo de criptografia | campo `encrypted` do registro |

## 5. Recursos apenas preparados

| Recurso | O que existe na interface | O que falta no backend | Próximo passo concreto |
|---|---|---|---|
| Anexos cifrados | página "Em preparação" | armazenamento cifrado por projeto, metadados, hash, decifração em memória | tabela de anexos + pasta cifrada com a chave do projeto |
| Mapa offline | página com indicador "Dados cartográficos ausentes" | dados locais (MBTiles), renderizador offline, ligação a entidades | escolher pacote cartográfico e renderizador; validar com rede desligada |
| Backup automático | estado "Indisponível" e "Sem registro" | agendamento, registro de execuções e falhas | serviço de backup cifrado com registro de estado |
| Importação e exportação de dados | linhas "Não implementado" | formatos (JSON, CSV) | definir formato de exportação completa cifrada |
| IA e análises | indicador "Mecanismo de IA: Indisponível" | integração Ollama, ferramentas de leitura, painel | integrar Ollama com detecção de disponibilidade |
| Busca semântica | página "Em preparação" (a busca textual Ctrl+K segue funcionando) | embeddings e índice vetorial | modelo local de embeddings e índice no arquivo do projeto |
| Sugestões e aprovações | legenda das citações (Documentado, Interpretação da IA, Não verificado) | geração de sugestões, registro de decisões | depois da IA: tabela de sugestões e histórico no log de auditoria |

## 6. Problemas encontrados e tratamento

| Problema | Tratamento |
|---|---|
| Os recursos "0.2" e "0.3" do pedido não existiam no backend | documentado na auditoria; módulos honestos em preparação; nenhum dado simulado |
| "Quantidade de anexos" sem fonte | exibido "Anexos: indisponível" em cinza, com explicação |
| "Descrição curta" fica dentro do arquivo cifrado | o card usa a categoria (modelo), lida do registro |
| Badge "v0.3" fixo violaria a regra de veracidade | o badge mostra a versão real instalada |
| Dados de data não têm horário | a linha do tempo mostra a precisão registrada e explica isso no cabeçalho |
| Validade de relação em texto livre ("na faculdade") | ignorada na linha do tempo, em vez de inventar uma data |
| Rótulo "Em preparação" cortado na barra lateral | passou para uma segunda linha |
| A tag v0.3.0 foi publicada com a versão interna 0.3.0-beta.1 | a próxima Release é v0.3.1, com a versão interna igual |
| F1 e F2 ficaram no mesmo arquivo da tela | commits separados para os componentes (F1) e para a tela (F1/F2); a reversão da tela não afeta o resto |

## 7. Testes realizados

CI no Windows e no Linux: **121 testes aprovados** a cada envio, com lint e verificação de camadas.

| Teste | Resultado | Observação |
|---|---|---|
| 1024×768 | Aprovado | 3 colunas, card 312 × 150 px |
| 1366×768 | Aprovado | 4 colunas, card 315 × 150 px |
| 1920×1080 | Aprovado | 6 colunas, card 297 × 150 px |
| 2560×1440 | Aprovado | 8 colunas, card 299 × 150 px |
| 700 px (estreita) | Aprovado | 2 colunas, card 314 × 150 px |
| 0 projetos | Aprovado | estado vazio com "Criar primeiro projeto" |
| 1 projeto | Aprovado | card no tamanho padrão; a grade não estica |
| 5–6 projetos e nome muito longo | Aprovado | reticências e dica com o nome completo (capturas) |
| 50 projetos | Aprovado | rolagem vertical, alturas idênticas, contador 50 |
| Mesma altura na linha / redimensionar | Aprovado | só o número de colunas muda |
| Criar, abrir, pesquisar, excluir projeto | Aprovado | exclusão com confirmação que nomeia o projeto |
| Estados carregando, erro, sem resultados | Aprovado | erro com "Tentar novamente" |
| Bloquear e desbloquear | Aprovado | sem recargas tardias de telas destruídas |
| Navegar por todos os 15 módulos e voltar | Aprovado | — |
| Veracidade: IA "Indisponível", backup sem cópias em projeto novo | Aprovado | nenhum indicador fixo |
| Linha do tempo só com dados reais | Aprovado | datas, validade de relações, entidades na lixeira excluídas |
| Regressão: criar entidade, busca, lixeira, mesclagem, auditoria, cifragem | Aprovado | suíte existente |
| Offline: mapa e IA | Não se aplica | não implementados; nenhuma requisição de rede existe no app |
| Contraste AA dos 6 temas | Aprovado | teste automático |

## 8. Riscos e recomendações para a 0.4

1. **Implementar o backend dos módulos em preparação**, nesta ordem: backup automático, exportação/importação,
   anexos cifrados, mapa offline e IA (com busca semântica, sugestões e aprovações). Cada um exige
   aprovação explícita, porque altera o backend.
2. A linha do tempo lê todas as entidades ao abrir. Para projetos com dezenas de milhares de entidades,
   convém uma consulta dedicada no backend.
3. A contagem de entidades do card reflete o último fechamento do projeto. Se um projeto for alterado
   fora do app, o número fica desatualizado até a próxima abertura.
4. O grafo ainda usa o layout de força O(n²). Para 10 mil nós, recomenda-se um layout aproximado com nível de detalhe.
5. Assinatura de código do instalador, para eliminar o aviso do SmartScreen.
