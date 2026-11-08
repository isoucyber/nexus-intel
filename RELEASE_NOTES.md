## NEXUS INTEL 0.3.3 — cortar relações e links clicáveis

**Baixe** `NexusIntel-Setup-*.exe` abaixo e execute. Se o Windows SmartScreen avisar, clique em **Mais informações → Executar assim mesmo**. Seus usuários e projetos continuam funcionando.

### Novidades
- **Cortar relação**: pelo botão direito na relação (na ficha da entidade ou numa linha do grafo) ou pelo botão “Cortar relação”. A confirmação mostra as duas pontas; as entidades nunca são apagadas
- **Relações na lixeira**: relações cortadas ficam na Lixeira, de onde podem ser restauradas ou excluídas de vez (junto com as fontes ligadas a elas, sem deixar vínculos órfãos)
- **Grafo**: clique numa linha para ver o tipo, o status e as fontes da relação; ao cortar, a linha some na hora e os nós ficam no lugar
- **Links clicáveis**: endereços em fontes e atributos (Site, URL do perfil…) abrem no navegador padrão do Windows ao clicar. Só http e https são aceitos; link inválido mostra um aviso

### Segurança
- Nenhum link abre sem um clique seu; o restante do aplicativo continua 100% offline

### Acabamento
- Janelas de cadastro e edição (fonte, entidade, afirmação, relação, projeto, senha, configurações) seguem o mesmo visual: título no topo, botão de fechar e espaçamento padrão
- Ícones das abas mudam de cor junto com o tema
- Menu lateral mais compacto: cabe melhor em telas de 768 px de altura
- Ao abrir um projeto, o primeiro item do menu não aparece mais com contorno de foco
- O número de entidades no cartão do projeto é atualizado também ao abrir o projeto

### Correções
- O histórico de uma entidade às vezes mostrava duas alterações do mesmo segundo fora de ordem
- Trocar o tema depois de fechar um projeto podia mostrar uma mensagem de erro inesperado
