# NEXUS INTEL

Central local de conhecimento e análise. Cada informação é registrada com a sua origem,
conectada a outras e explorada como grafo. Tudo fica no seu computador, cifrado, e funciona
sem internet.

> **Versão 0.1 (núcleo).** Esta versão entrega a base completa: login cifrado, projetos,
> entidades, afirmações com fonte, relações, busca, grafo, qualidade dos dados, lixeira,
> histórico e auditoria. Mapa, linha do tempo, anexos, IA e relatórios entram nas próximas
> versões (veja o [roteiro](#roteiro)).

## Instalar (Windows 10/11)

1. Abra a página de [Releases](https://github.com/isoucyber/nexus-intel/releases) e baixe
   `NexusIntel-Setup-<versão>.exe`.
2. Execute o instalador. Não precisa ser administrador.
3. Na primeira execução, o Windows SmartScreen pode avisar “Windows protegeu o computador”,
   porque o instalador ainda não tem assinatura de código. Clique em **Mais informações →
   Executar assim mesmo**. Se quiser conferir o arquivo, compare o hash com o `SHA256SUMS.txt`
   da mesma Release (`Get-FileHash .\NexusIntel-Setup-*.exe` no PowerShell).

Também há uma versão portátil (`NexusIntel-portatil-<versão>.zip`): descompacte e abra
`NexusIntel.exe`.

## Primeiro uso

1. **Crie seu usuário e senha** (mínimo de 12 caracteres).
2. **Anote a chave de recuperação.** Ela aparece uma única vez e é a única forma de abrir os
   dados se você esquecer a senha. Sem senha e sem chave, os dados cifrados são irrecuperáveis.
3. Crie um projeto. Para aprender, use o modelo **Exemplo guiado**: ele traz dados fictícios
   (João → veículo → Veneza) com fontes, status e um conflito entre fontes.

## O que já funciona

| Área | Recursos |
|---|---|
| Segurança | Argon2id + AES-256-GCM; banco SQLCipher por projeto com chave própria; chave de recuperação; atraso progressivo após senhas erradas (persiste ao reiniciar); bloqueio manual (Ctrl+L) e por inatividade |
| Projetos | Um arquivo por projeto; isolamento total entre projetos; trava contra abrir o mesmo projeto duas vezes; modelos de projeto; finalidade e base legal (LGPD) |
| Entidades | 15 tipos padrão com campos tipados; outros nomes; identificadores (CPF, CNPJ, domínio, placa…); etiquetas hierárquicas; importância; favoritos; observações privadas |
| Afirmações | Cada valor tem fonte, trecho, status (verificado, relatado, não verificado, hipótese, conflitante, refutado), credibilidade 1–6, validade e data de revisão; datas imprecisas (“03/1998”, “década de 1990”, “c. 1850”); conflitos detectados automaticamente sem apagar nada |
| Fontes | Confiabilidade A–F; fonte desacreditada sinaliza tudo que depende só dela; “onde esta fonte é usada” |
| Relações | 25 tipos padrão com rótulo inverso; validade; fontes; conexões indiretas até 3 saltos (calculadas, nunca gravadas) |
| Grafo | Visão geral com limite de nós, modo Foco, filtros por tipo e “só verificadas”, linhas por status, arrastar, zoom, criar relação, exportar PNG |
| Busca | Ctrl+K em qualquer tela; sem acento e sem maiúscula; `"frase exata"`, `prefixo*`, `-excluir`, `tipo:pessoa`, `tag:italia`; captura rápida `Nome · tipo` |
| Qualidade | Conflitos, entidades sem fonte, contadores; busca de duplicatas com mesclagem reversível |
| Histórico | Revisão a cada alteração com restauração; lixeira; log de auditoria encadeado por hash com verificação |
| Aparência | Temas Nexus (escuro), Clean (claro) e Midnight (alto contraste), todos com contraste WCAG AA; tamanho do texto ajustável |

## Atalhos

| Atalho | Ação |
|---|---|
| Ctrl+K | Buscar / criar rápido |
| Ctrl+N | Nova entidade |
| Ctrl+G | Grafo |
| Ctrl+W | Fechar aba |
| Ctrl+L | Bloquear |
| Ctrl+J | Assistente de IA |
| Ctrl+Shift+Espaço | Falar com o assistente (liga/desliga o microfone) |

## Assistente de IA e voz (0.4, em desenvolvimento)

O **NEXUS** é um assistente de análise que roda **no seu computador**. Você pergunta ou dá
ordens, por texto ou voz, por exemplo: “quem é Helena Prado?”, “há ligação entre a Aurora e a
Vértice?”, “abre a ficha da Helena”, “mostra a Aurora no grafo”, “lê este documento”.

- **Cada frase leva um selo:** *Documentado* (cita uma fonte do projeto, com link), *Interpretação
  da IA* ou *Não verificado*. Citações inventadas pelo modelo são removidas.
- **Nada entra no projeto sem você:** quando a IA quer criar ou ligar algo, ela registra uma
  sugestão em **Sugestões e aprovações**; aprovar ou rejeitar fica na auditoria.
- **Busca semântica:** encontra pelo significado (“empresas de transporte”).
- **Voz humana:** responde em voz alta com a voz neural masculina **Kokoro (Alex)**, que começa a
  falar já na primeira frase; ouve pelo microfone só quando você manda (botão ou Ctrl+Shift+Espaço).
  Alternativas: Piper (mais leve) ou a voz do Windows (robótica).

### Como ligar

1. Instale o [Ollama](https://ollama.com) e baixe os modelos (uma vez, com internet):
   ```powershell
   ollama pull qwen2.5:7b
   ollama pull bge-m3
   ```
   **Sem placa de vídeo, prefira `qwen2.5:3b`**: responde cerca de 2 vezes mais rápido que o 7b.
   Com placa de vídeo (NVIDIA ou AMD), o Ollama a usa sozinho e o 7b responde em 1–2 s.
   LM Studio e llama.cpp também funcionam (IA e análises → Configurar → Endereço).
2. Voz e microfone (opcional, rodando a partir do código):
   ```powershell
   pip install -e ".[voz]"
   python tools/baixar_voz.py
   ```
   O script baixa a voz Kokoro e o modelo de fala (~800 MB) numa versão fixa, confere o SHA-256 de
   cada arquivo e cria um ambiente separado para a voz. `--piper` instala também a voz Piper.
3. No projeto: **Inteligência → IA e análises** (Ctrl+J).

Só endereços deste computador são aceitos para a IA; observações privadas nunca vão para ela;
dados sensíveis (saúde, religião) só se você permitir. Decisões e limites:
[ADR-0004](docs/adr/0004-assistente-ia-e-voz.md).

## Onde ficam os dados

`%APPDATA%\NexusIntel\` (Windows). O desinstalador **não** apaga essa pasta. Para usar uma
pasta diferente (ex.: pendrive), defina a variável de ambiente `NEXUS_INTEL_HOME`.

## Rodar a partir do código

Requer Python 3.12.

```powershell
git clone https://github.com/isoucyber/nexus-intel
cd nexus-intel
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python -m nexus_intel
```

Testes: `pytest` · Testes de interface sem tela: `set QT_QPA_PLATFORM=offscreen` antes.

## Gerar o instalador

O instalador é gerado pelo GitHub Actions ao criar uma tag `vX.Y.Z`
([release.yml](.github/workflows/release.yml)). Localmente, no Windows:

```powershell
pip install . pyinstaller
python packaging/make_icon.py packaging/nexus.ico
pyinstaller packaging/nexus_intel.spec --noconfirm
dist\NexusIntel\NexusIntel.exe --self-test
```

## Limites de segurança (leia)

- Protege contra quem copia os arquivos ou rouba o computador desligado. **Não** protege contra
  malware rodando no seu usuário enquanto o programa está desbloqueado.
- O Python não garante apagar todas as cópias de chaves da memória; o bloqueio descarta as
  referências, mas é uma mitigação, não uma garantia.
- O contador de tentativas erradas fica num arquivo que quem tem acesso ao disco consegue
  editar. A defesa real contra ataque à senha é o custo do Argon2id (≈1 s por tentativa).

## Uso responsável

O NEXUS INTEL organiza informações que você obteve de forma legítima. Ele não tem, e não terá,
recursos de invasão de contas, raspagem de redes sociais, bases vazadas, reconhecimento facial
ou rastreamento de pessoas. Ao tratar dados pessoais, você é responsável por cumprir a LGPD.

## Roteiro

| Versão | Entrega |
|---|---|
| **0.1** (esta) | Núcleo: segurança, projetos, entidades, afirmações, fontes, relações, busca, grafo, qualidade, histórico |
| 0.2 | Anexos cifrados, mapa offline (Veneza sem internet), linha do tempo, importação/exportação, backup automático |
| 0.3 | IA local/externa com citações verificadas, busca semântica, sugestões com aprovação |
| 0.4 (em desenvolvimento) | Assistente de IA local com citações conferidas, sugestões com aprovação, busca semântica e voz |
| 0.5+ | Revisor de qualidade e hipóteses concorrentes com IA, métricas de rede, globo 3D, OCR, relatórios PDF |

Decisões técnicas estão registradas em [docs/adr](docs/adr).

## Licença

Apache-2.0. Componentes de terceiros em [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
