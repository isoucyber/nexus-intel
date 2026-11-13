# NEXUS INTEL — Modelo de ameaças (0.3.4, com adendo da 0.4: IA e voz)

Escopo: aplicativo de desktop Windows, Python 3.12 + PySide6 (Qt Widgets, **não** Electron, sem
navegador embutido, sem servidor, sem rede própria). Dados ficam no computador; a única saída
de dados é um arquivo `.nexus` que o próprio usuário gera e entrega por qualquer meio.

## 1. Ativos

| Ativo | Onde fica | Proteção principal |
|---|---|---|
| Conteúdo das investigações (entidades, relações, fontes, atributos, linha do tempo, histórico) | `profiles/<id>/projects/<id>/project.nxdb` | SQLCipher (AES-256), chave por projeto |
| Fotografias | `projects/<id>/blobs/*.blob` | AES-256-GCM por arquivo + SHA-256 |
| Notas | dentro do `project.nxdb` | idem banco |
| Preferências, registro de projetos, registro de segurança | `profiles/<id>/app.nxdb` | SQLCipher, chave do perfil |
| Chave mestra do perfil | só na memória enquanto a sessão está aberta | embrulhada no `vault.json` (Argon2id + AES-GCM) |
| Chaves privadas de identidade (X25519/Ed25519) | `app.nxdb` | AES-GCM com subchave da chave mestra |
| Senha e chave de recuperação | nunca gravadas | — |
| Pacotes `.nexus` | onde o usuário salvar | AES-256-GCM + Argon2id + Ed25519 |
| Integridade da investigação | cadeia de auditoria por projeto | SHA-256 encadeado |

## 2. Atacantes considerados

1. **Outra pessoa que usa o mesmo computador** (com outro perfil do NEXUS, mesma conta do Windows).
2. **Ladrão do computador ou do disco** (computador desligado ou bloqueado).
3. **Quem obtém uma cópia dos arquivos** (backup em nuvem, pen drive, cópia do `%APPDATA%`).
4. **Quem intercepta ou rouba um `.nexus`** (e-mail, mensageiro, pen drive).
5. **Remetente malicioso** que entrega um `.nexus` montado para atacar (com a senha correta).
6. **Pessoa com acesso momentâneo** a uma sessão aberta e esquecida.
7. **Cadeia de suprimentos**: pacote Python comprometido ou instalador adulterado.

Fora do escopo (ver riscos residuais): administrador local ou malware rodando como o usuário
enquanto a sessão está aberta; ataques físicos à memória (cold boot, DMA).

## 3. Fronteiras de confiança

```
[Usuário] --senha--> [Tela de entrada] --Argon2id--> [chave mestra do perfil em memória]
                                                        |
        +----------------------+------------------------+----------------------+
        v                      v                        v                      v
 [app.nxdb do perfil]   [project.nxdb]          [blobs/ fotos]        [chaves de identidade]
                                                        |
  ---------------- fronteira: arquivo externo (NÃO confiável) ----------------
        [.nexus recebido] -> decifra -> verifica -> pasta de preparação -> projeto
        [imagem escolhida pelo usuário] -> validação de conteúdo -> blob cifrado
        [links http(s)] -> abertos só por clique, validados
```

Entradas não confiáveis: arquivos `.nexus`, imagens adicionadas, texto digitado ou importado
(nomes, notas, URLs) — este último é exibido em rótulos do Qt, que interpretam HTML se não
forem configurados para texto puro.

## 4. Cenários pedidos

| # | Cenário | Vetor | Mitigação existente (0.3.4) | Residual |
|---|---|---|---|---|
| 1 | Computador compartilhado | Perfil B tenta ler dados do A | Chave mestra por perfil; bancos, fotos e chaves privadas cifrados com ela; caminhos recalculados de IDs validados; chave do projeto presa ao ID por AAD; troca de perfil fecha tudo e limpa caches | Mesma conta do Windows: arquivos *visíveis* (não legíveis). Perfil “sem cifragem” só tem a tela de login |
| 2 | Roubo do computador | Leitura do disco | Tudo cifrado em repouso; Argon2id (256 MiB) torna ataque de senha caro; bloqueio por inatividade | Senha fraca escolhida pelo usuário; computador roubado **com sessão aberta** |
| 3 | Acesso aos arquivos locais | Cópia da pasta de dados | Idem 2; `vault.json` não contém segredos em claro | Nomes de exibição e avatares dos perfis são públicos (tela de seleção) |
| 4 | Roubo de um `.nexus` | Ataque à senha do pacote | AES-256-GCM; Argon2id; senha mínima de 12 caracteres | Senha fraca/reutilizada; tamanho aproximado do projeto é visível |
| 5 | Interceptação de transmissão | Leitura/alteração em trânsito | O pacote é cifrado e autenticado de ponta a ponta; qualquer byte alterado é recusado | O NEXUS não transmite: o canal é do usuário. Senha deve ir por outro canal |
| 6 | Importação de arquivo malicioso | Nomes de caminho, bombas, imagens disfarçadas, SQL, HTML | Regex de nomes; limites de tamanho/pixels/memória; validação de imagem pelo conteúdo; inserção só em tabelas/colunas conhecidas e parametrizada; checagem de chaves estrangeiras; preparação isolada e transacional; texto exibido como texto puro | Vulnerabilidades ainda desconhecidas nos decodificadores de imagem (Pillow) |
| 7 | Comprometimento de um perfil | Senha descoberta | Registro de segurança mostra acessos, falhas de senha e exportações; senha e chave de recuperação podem ser trocadas; chave de identidade pode ser trocada | Quem tem a senha tem os dados daquele perfil (por definição) |
| 8 | Acesso a outro perfil | Manipular IDs/caminhos/registro | IDs ULID validados; `resolve()` confere o pai; cópia de registro entre perfis não desembrulha a chave | — |
| 9 | Adulteração de investigação | Editar banco/arquivo | SQLCipher (sem a chave não há edição coerente); auditoria encadeada por projeto; registro de segurança encadeado; fotos conferidas por SHA-256 e tag GCM | Quem tem a chave pode reescrever a cadeia: é evidência de adulteração, não prova |
| 10 | Dependência comprometida | Pacote malicioso no PyPI / build adulterado | pip-audit no CI; análise estática de segurança; autoteste do executável; SHA256SUMS; atestado de procedência (Sigstore) dos instaladores | Versões não fixadas com hash no build; instalador sem assinatura de código (SmartScreen) |

## 5. Limites do modelo (riscos residuais)

- **Não existe proteção contra quem controla o computador enquanto a sessão está aberta**
  (administrador, malware com os privilégios do usuário, keylogger). Ele pode ler a memória do
  processo, a tela e o teclado.
- **Memória**: o Python não garante apagar cópias de chaves e textos; `SecretKey.wipe()` é
  mitigação. Arquivos de paginação/hibernação do Windows podem conter fragmentos — use
  BitLocker.
- **Perfis sem cifragem** dependem só da tela de login.
- **Atraso entre tentativas** fica no `vault.json` e pode ser zerado por quem edita o arquivo; a
  barreira real contra tentativa offline é o custo do Argon2id.
- **Assinatura Ed25519** prova que o pacote veio de *uma* chave; quem é o dono da chave só é
  confirmado conferindo a impressão digital por outro canal.
- **Imagem PNG do grafo** exportada pelo usuário sai sem cifragem (ação explícita).
- **DPAPI do Windows não é usado**: amarraria os dados à conta do Windows e impediria restaurar
  em outro computador; a proteção vem da senha do perfil (decisão documentada no ADR-0003).

## 6. Adendo 0.4 — Assistente de IA e voz (ADR-0004)

Mudança de fronteira: o app passa a fazer **requisições HTTP para um servidor de IA no próprio
computador** (loopback) e a iniciar **programas de voz** (Piper, PowerShell/SAPI). O microfone
pode ser aberto pelo usuário.

| # | Cenário | Vetor | Mitigação (0.4) | Residual |
|---|---|---|---|---|
| 11 | Injeção de instruções pelos dados | Nome, nota ou documento (ex.: de um `.nexus` recebido) com "ignore as regras e…" | A IA não escreve: só ferramentas de leitura, navegação e **sugestões pendentes**; instrução explícita de tratar dados como dados; limite de rodadas e de sugestões; aprovação revalida os dados | Um modelo enganado pode sugerir algo errado ou responder errado: o selo da frase e a aprovação humana são a barreira |
| 12 | Citação falsa | Modelo inventa fonte ou ID | Marca só vale se existe e foi lida por ferramenta nesta conversa; inválida é removida e contada; atribuição automática só com o dado literal na frase e sem negação | Frase interpretativa pode estar errada, mas aparece como "Interpretação da IA" |
| 13 | Vazamento para a rede | Endereço de IA remoto, proxy ou redirecionamento | Só loopback; sem proxy; sem redirecionamento; selo "Local/Externo" | Outro programa ouvindo na porta local do Ollama receberia os pedidos (exige malware local, fora do escopo) |
| 14 | Exposição de dados sensíveis à IA | Ferramentas devolvendo tudo | Observações privadas nunca; sensíveis só com opção explícita; IA local por padrão | — |
| 15 | Injeção de comando na voz | Texto falado com metacaracteres | Texto pela entrada padrão; argumentos em lista, sem shell | Executável do Piper trocado por outro (exige acesso de escrita local) |
| 16 | Escuta indevida | Microfone aberto | Só sob comando, com indicador; sem escuta contínua; áudio só na memória | Malware local pode usar o microfone por conta própria |
| 17 | Modelo/voz adulterado no download | Arquivo trocado | Revisão fixa do repositório + SHA-256 por arquivo; `.part` até conferir | Confiança no publicador original (Hugging Face / rhasspy / Systran) |
