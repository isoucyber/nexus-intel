# Changelog

Formato baseado em Keep a Changelog; versões seguem SemVer.

## [0.3.3] — 2026-11-07
### Adicionado
- Cortar relação na ficha da entidade (botão e menu) e no grafo (menu da linha), com confirmação; entidades preservadas.
- Lixeira com aba de relações: restaurar ou excluir de vez (evidências removidas, sem órfãos).
- Grafo: linhas selecionáveis com painel de detalhes; corte remove só a linha e mantém os nós no lugar.
- Links http/https clicáveis em fontes, atributos de link, evidências, painel do grafo e linha do tempo
  (`QDesktopServices.openUrl` com validação; só abre por clique).
### Alterado
- Diálogos de formulário usam o cabeçalho padrão (`dialog_form`: título, botão Fechar, espaçamentos dos tokens).
- Ícones de abas re-tingidos na troca de tema (`set_tab_icon`).
- Menu lateral mais compacto; botões do menu só recebem foco por Tab; foco inicial vai para o conteúdo.
- `entity_count` do projeto atualizado também ao abrir.
### Corrigido
- Histórico ordenava pelo ID aleatório dentro do mesmo segundo.
- Grafo reagia à troca de tema depois de o projeto ser fechado.

## [0.3.2] — 2026-11-07
### Adicionado
- Números do Início e barras de “Entidades por tipo” clicáveis, com mouse e teclado.
- Exclusão de fonte (lista e tela de edição) com confirmação que informa os vínculos afetados.
- Regra única de nome obrigatório (`require_name`) para entidades, fontes, projetos, tipos e campos, na criação e na edição.
### Corrigido
- Editar uma fonte apagando o título gravava título vazio.
- Abrir entidade excluída definitivamente abria uma aba vazia.

## [0.3.1] — 2026-11-07
### Adicionado
- Linha do tempo com datas de afirmações e validade de relações (dados reais), filtros e navegação entre eventos.
- Navegação do projeto em Investigação, Inteligência e Dados; módulos sem backend como "Em preparação".
- Módulo Importação e exportação (PNG do grafo) e módulo Backup com estado real.
- Selo de citação (Documentado, Interpretação da IA, Não verificado) no design system.
- Relatório final da 0.3 em `docs/relatorio-0.3.md`.

## [0.3.0] — 2026-11-07
### Corrigido
- Cards de projeto esticavam até a altura da janela; agora têm altura pelo conteúdo e colunas por largura.
### Adicionado
- Tela de projetos com versão, contador real, pesquisa e estados de carregando, vazio, erro e sem resultados.
- Auditoria da interface em `docs/auditoria-0.3.md`.

## [0.2.0] — 2026-11-06 — Fase 1: design system
### Adicionado
- Tokens centralizados e 6 temas (Escuro, Claro, OLED preto, Alto contraste, Midnight Blue, Graphite)
  com contraste WCAG AA verificado por teste, inclusive para qualquer cor de destaque.
- Fontes Inter e JetBrains Mono e ícones Lucide embutidos; um ícone por item de menu, tipo e status.
- Componentes: botões com variantes, campos, cartões, chips de status e tipo, avatar de entidade,
  teclas de atalho, rótulo com reticências e dica, estado vazio, skeleton, avisos (toasts), modal,
  painel lateral (drawer), barras horizontais e tabela virtualizada.
- Capturas de tela automáticas no CI e vitrine de componentes (`python -m nexus_intel.ui.design.gallery`).

### Alterado
- Todas as telas usam o design system; nenhuma cor fixa fora dos tokens.
- Gráficos do Início viraram barras legíveis (antes: caracteres numa lista selecionável).
- Barras de rolagem, abas, menus, dicas e foco por teclado seguem o tema.
- Listas usam tabela virtualizada com carregamento sob demanda; datas relativas com data completa na dica.
- Grafo: nós com ícone do tipo; componentes desconexas não se afastam mais.
- Tema trocado nas configurações é aplicado ao vivo, inclusive no grafo.

## [0.1.0] — 2026-11-04
### Adicionado
- Cofre de chaves com Argon2id, slots de senha e recuperação, atraso persistido após falhas.
- Banco da aplicação e um banco SQLCipher por projeto, com migrações versionadas.
- Entidades, afirmações com proveniência e datas imprecisas, fontes, evidências, relações.
- Detecção de conflitos, duplicatas, mesclagem reversível, revisões, lixeira, auditoria encadeada.
- Busca FTS5 com filtros e captura rápida; grafo interativo; painel de qualidade.
- Interface PySide6 com três temas (WCAG AA), bloqueio por inatividade, instalador Windows.
