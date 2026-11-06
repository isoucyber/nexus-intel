# ADR-0002 — Design system em Qt Widgets

Data: 2026-11-06 · Status: aceito

## Contexto

A v0.1 tinha estilos espalhados e cores fixas nas telas. O plano de evolução pede temas
dinâmicos, cor de destaque livre, wallpaper com vidro fosco, animações, painel de IA e listas
fluidas com 10 mil+ entidades. Avaliamos três caminhos: manter Qt Widgets, migrar para QML ou
para uma interface web. Escolhemos **manter Qt Widgets** com uma camada de design system
(diagnóstico aprovado em 2026-11-06).

## Decisão

- `ui/design/tokens.py` é a única fonte de cores, tipografia, espaçamento, raios, sombras e
  durações. Um teste falha se qualquer outro módulo de `ui/` escrever uma cor literal.
- Temas declaram só as cores base; `resolve()` deriva hover, active, subtle, foco e texto sobre
  destaque e **ajusta automaticamente** qualquer cor que fique abaixo de 4,5:1 (texto) ou 3:1
  (foco e componentes). Isso vale também para a cor de destaque escolhida pelo usuário e para
  tipos de entidade novos (cor automática estável derivada do nome).
- A folha de estilo é gerada a partir dos tokens; variantes usam propriedades dinâmicas
  (`variant="primary"`, `card="true"`, `role="muted"`).
- `ThemeManager` aplica tudo ao vivo e emite `changed`; componentes desenhados à mão se
  redesenham sem recriar telas.
- Ícones Lucide (ISC) embutidos como SVG e recoloridos por token; fontes Inter e JetBrains Mono
  (OFL) embutidas, com os nomes internos normalizados para agrupar os pesos numa só família.
- Listas usam `DataTable` (QTableView + modelo com paginação sob demanda), que desenha só as
  linhas visíveis.

## Consequências

- Trocar tema, destaque, escala, densidade e movimento não exige reiniciar.
- Seleção em listas usa fundo sutil + texto normal, legível em todos os temas.
- Animações respeitam a preferência de movimento (completas, reduzidas, desligadas).
- O Mica/Acrylic nativo do Windows não é usado: ele desfoca a área de trabalho, não um wallpaper
  próprio. O vidro fosco da Fase 3 será desenhado pelo app.
