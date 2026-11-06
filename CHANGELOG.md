# Changelog

Formato baseado em Keep a Changelog; versões seguem SemVer.

## [Não lançado] — Fase 1: design system
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
