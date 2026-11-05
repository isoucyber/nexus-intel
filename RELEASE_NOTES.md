## NEXUS INTEL 0.1 — núcleo

Primeira versão utilizável.

**Baixe** `NexusIntel-Setup-*.exe` abaixo e execute. Na primeira vez, o Windows SmartScreen pode
avisar porque o instalador ainda não tem assinatura de código: clique em **Mais informações →
Executar assim mesmo**. Confira o hash no `SHA256SUMS.txt` se quiser.

### Inclui
- Usuário local com senha, chave de recuperação e bloqueio por inatividade; tudo cifrado (SQLCipher + AES-256-GCM)
- Projetos isolados, um arquivo por projeto
- Entidades de 15 tipos, afirmações com fonte e status epistêmico, conflitos entre fontes
- Relações tipadas, conexões indiretas, grafo interativo com modo Foco
- Busca global (Ctrl+K) com captura rápida
- Duplicatas e mesclagem reversível, histórico, lixeira, auditoria com verificação de integridade
- Projeto “Exemplo guiado” com dados fictícios

### Ainda não inclui
Mapa, linha do tempo, anexos, IA, importação/exportação e backup automático (próximas versões).

**Importante:** anote a chave de recuperação na criação do usuário. Sem senha e sem chave, os dados são irrecuperáveis.
