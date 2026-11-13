# ADR-0004 — Assistente de IA com citações conferidas, sugestões e voz

Data: 2026-11-13 · Status: aceito · Versão: 0.4 (em desenvolvimento, branch `dev`)

## 1. Contexto

O roteiro previa para a 0.3 a "IA local/externa com citações verificadas, busca semântica e
sugestões com aprovação". A auditoria da 0.3 (`docs/auditoria-0.3.md`) registrou que nada
disso existia, e a decisão de 06/11 foi: **Ollama local por padrão; nuvem opcional, desligada,
com chave no cofre**. O pedido desta fase acrescenta uma **voz humanizada, masculina**, com
comandos falados ou escritos.

Finalidade escolhida (lista priorizada na conversa de 12/11): um assistente de análise que
(1) responde perguntas sobre o projeto com citações conferidas, (2) transforma documentos em
dados estruturados como sugestões, (3) busca pelo significado. As finalidades seguintes
(revisor de qualidade, hipóteses concorrentes, duplicatas por significado, relatório citado)
reaproveitam esta base.

## 2. Decisões

### 2.1 Mecanismo de IA

- **Protocolo compatível com OpenAI** (`/v1/chat/completions`, `/v1/models`, `/v1/embeddings`):
  um cliente serve o **Ollama** (padrão, `127.0.0.1:11434`), o LM Studio e o servidor do llama.cpp.
- **Só loopback** (`127.0.0.1`, `::1`, `localhost`). Outro endereço é recusado
  (`AiAddressRejected`); o modo "Externo" exige `allow_remote=True`, que a interface ainda
  não oferece. O selo da tela mostra sempre **Local** ou **Externo**.
- Sem proxy do sistema, sem seguir redirecionamentos, resposta limitada a 16 MiB.
- Modelos recomendados: `qwen2.5:7b` (português e ferramentas); `qwen2.5:3b` em máquinas
  modestas; vetores `bge-m3` (multilíngue) ou `nomic-embed-text`.

### 2.2 Como o assistente lê o projeto

- **Ferramentas, não o banco inteiro.** O modelo recebe só o que pede: `buscar`,
  `busca_semantica`, `ver_entidade`, `caminho_entre`, `ver_fonte`, `listar_fontes`, `qualidade`,
  `buscar_notas`, `campos_do_tipo`, `resumo_projeto`.
- **Privacidade por padrão:** observações privadas nunca vão para a IA; afirmações marcadas
  como sensíveis (saúde, religião) só com a opção "Permitir dados sensíveis".
- As leituras do banco rodam na thread da interface (dona da conexão); só a chamada HTTP roda
  em segundo plano. A conversa é um gerador (`Assistant.turn`), conduzido pela tela ou, nos
  testes, por `run_turn`.
- Modelos pequenos inventam identificadores: o app entrega prontos os IDs das entidades citadas
  na pergunta, e as ferramentas aceitam o nome no lugar do ID.

### 2.3 Citações conferidas e classificação

- As ferramentas devolvem marcas prontas: `[c:ID]` afirmação, `[r:ID]` relação, `[f:ID]` fonte,
  `[e:ID]` entidade, `[n:ID]` nota.
- Uma marca só vale se **existe no projeto e foi devolvida por uma ferramenta nesta conversa**.
  Marca inventada (mesmo de ID real não lido) é removida e contada na resposta.
- Cada frase recebe um selo (`CitationBadge`, seção 8.4):
  - **Documentado**: cita afirmação ou relação sustentada por fonte não desacreditada, ou cita
    a própria fonte;
  - **Não verificado**: cita algo sem fonte, ou teve marca inválida;
  - **Interpretação da IA**: sem citação (ou só aponta entidades);
  - sem selo: cortesia, perguntas ao usuário, cabeçalhos.
- **Atribuição conferida:** se o modelo não citou, mas a frase contém literalmente o valor de
  uma afirmação lida (ou as duas pontas de uma relação lida), o NEXUS anexa a citação. Frases
  com negação ("não", "nunca", "sem"…) nunca recebem atribuição automática.
- Conteúdo HTML do modelo é exibido como texto puro.

### 2.4 Comandos e sugestões

- **Navegação** (abrir ficha, abrir tela, focar no grafo) executa na hora: não muda dados.
  Comandos comuns ("abre a ficha da …", "mostra … no grafo", "vai para fontes") são
  reconhecidos **sem a IA** (`quick_command`): instantâneos e disponíveis com a IA desligada.
- **Escrita:** a IA só registra sugestões pendentes (tabela `suggestion`, migração
  `0003_ia`). Aprovar aplica pelo fluxo normal do `ProjectStore` (revisão + auditoria) **na
  mesma transação** que marca a sugestão; a sugestão é revalidada contra os dados atuais.
  Rejeitar guarda o motivo. Criação, aprovação e rejeição entram na auditoria encadeada.
- **Documento → dados:** o usuário cola um texto e escolhe a fonte; as sugestões levam o trecho,
  que é marcado "conferido" só se aparece literalmente no documento.
- Limites: 8 rodadas de ferramentas por pergunta; 25 sugestões por resposta.

### 2.5 Busca semântica

- Um vetor por entidade e modelo (tabela `embedding`), no banco cifrado do projeto, com o
  SHA-256 do texto indexado: reindexação incremental. Busca por cosseno (NumPy).
- O índice é derivado: **não vai no `.nexus`** (é refeito no destino).

### 2.6 Voz

- **Síntese (texto → voz):**
  1. **Piper** (voz neural) como **programa separado**: o NEXUS (Apache-2.0) não embute o Piper
     nem o espeak-ng (GPL-3.0). Voz padrão **`pt_BR-cadu-medium`**, escolhida por medição:
     frequência fundamental mediana de 137 Hz, faixa masculina (jeff: 151 Hz; faber: 172 Hz).
     Dados das vozes: CC0.
  2. **Voz do Windows** (SAPI via PowerShell), preferindo voz masculina pt-BR; sem instalação.
  3. espeak-ng (Linux, desenvolvimento).
- **Timbre de "assistente digital"** (opcional, ligado por padrão): voz um pouco mais grave
  (síntese mais rápida + estiramento, mantendo a duração; padrão −6%, cerca de 1 semitom), dois
  ecos curtos (brilho metálico), sala pequena e presença. **Não imita a voz de nenhuma pessoa
  real**: clonar a voz de um ator ou personagem sem autorização não é aceitável.
- **Reconhecimento (voz → texto):** `faster-whisper` (MIT) com Whisper *small* (MIT), aberto só
  da pasta local (`local_files_only`).
- **Microfone só sob comando:** botão ou Ctrl+Shift+Espaço; sem palavra de ativação e sem escuta
  contínua. O áudio fica só na memória; nada é gravado em disco.
- O texto falado vai ao mecanismo de voz pela **entrada padrão**, nunca na linha de comando.
- `tools/baixar_voz.py` baixa vozes e modelo de huggingface.co numa **revisão fixa**, confere o
  **SHA-256** de cada arquivo e cria um ambiente separado para o Piper (`--instalar-piper`).
- Dependências de voz são opcionais (`pip install "nexus-intel[voz]"`).

## 3. Consequências

- A IA não altera dados sem aprovação: no pior caso, uma injeção de instruções escondida nos
  dados (por exemplo, num `.nexus` recebido) gera sugestões pendentes ou navegação, ambas visíveis.
- A qualidade das respostas depende do modelo; a honestidade dos selos, não: ela é garantida
  pelo código. Com modelos pequenos (3B), mais frases aparecem como "Interpretação da IA".
- A conversa fica só na memória (não é gravada no projeto); as sugestões, sim.

## 4. Pendências

- Modo "Externo" (nuvem) com chave no cofre do perfil e aviso por projeto.
- Incluir a voz no instalador do Windows (sounddevice, faster-whisper) e um botão "Instalar voz"
  dentro do app.
- Finalidades seguintes: revisor de qualidade, hipóteses concorrentes (ACH), duplicatas por
  significado, relatório citado em PDF, OCR de documentos fotografados (sem análise de rostos).
