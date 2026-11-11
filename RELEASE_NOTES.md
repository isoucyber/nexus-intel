## NEXUS INTEL 0.3.4 — perfis, fotografias, notas e projetos compartilháveis

**Baixe** `NexusIntel-Setup-*.exe` abaixo e execute. Se o Windows SmartScreen avisar, clique em **Mais informações → Executar assim mesmo**. Seu usuário atual vira automaticamente o primeiro perfil, com todos os projetos.

### Novidades
- **Vários perfis no mesmo computador**: cada pessoa tem seu perfil com nome, imagem, senha, projetos, notas, fotografias e preferências próprios. Os dados de cada perfil são cifrados com a chave daquele perfil; um não consegue abrir os dados do outro. Trocar de perfil fecha tudo e limpa a memória
- **Fotografias nas entidades**: nova aba “Fotografias” na ficha, com arrastar e soltar, galeria de miniaturas, visualização ampliada com setas, substituir e remover. Aceita JPG, PNG, WEBP, GIF, BMP e TIFF, conferidos pelo conteúdo real do arquivo. As imagens ficam cifradas dentro do projeto
- **Notas**: bloco de notas do projeto com salvamento automático, pesquisa, ordem por título ou data e vínculo opcional com uma entidade (botão de lápis na ficha)
- **Exportar e importar projetos (.nexus)**: um arquivo cifrado por senha (AES-256-GCM) e assinado digitalmente pelo seu perfil, com entidades, relações, fontes, notas e as fotografias de verdade. A importação mostra um resumo verificado antes de gravar e nunca sobrescreve um projeto existente
- **Grafo**: selecione uma linha e pressione **Backspace** para cortar a relação; o aviso traz “Desfazer”. As entidades nunca são apagadas

### Segurança
- Senha errada ou arquivo .nexus alterado em qualquer byte: nada é importado
- Algoritmos e decisões documentados em `docs/adr/0003-perfis-fotos-e-pacote-nexus.md`

### Correções
- A tela de cadastro não mostra mais nomes pessoais como exemplo; o projeto de exemplo usa nomes genéricos
