# ADR-0003 — Perfis locais, fotografias e pacote `.nexus` (0.3.4)

Status: aceito · Versão: 0.3.4

## 1. Contexto

Até a 0.3.3 havia **um usuário por instalação** (`vault.json` + `app.nxdb` +
`projects/` na pasta de dados). Não existiam anexos, notas nem forma de levar
um projeto para outro computador. A 0.3.4 pede: vários perfis isolados no mesmo
computador, fotografias nas entidades, Notepad e compartilhamento cifrado.

## 2. Decisões

### 2.1 Perfis = um ambiente cifrado por pessoa

```
<dados>/profiles.json             índice público (id, nome de exibição, impressão digital)
<dados>/profiles/<id>/vault.json  cofre do perfil
<dados>/profiles/<id>/app.nxdb    banco do perfil (SQLCipher)
<dados>/profiles/<id>/projects/   projetos do perfil
<dados>/profiles/<id>/avatar.png  imagem do perfil (pública)
```

- Cada perfil tem **chave mestra própria** (256 bits aleatórios), protegida pelo
  cofre (Argon2id → AES-256-GCM, mesmo desenho da 0.1). O banco do perfil, as
  chaves dos projetos, as fotografias e as chaves privadas de identidade são
  cifrados com chaves derivadas dela. Sem a senha (ou a chave de recuperação)
  daquele perfil, nada é legível — o isolamento é **criptográfico**, não só de
  interface.
- A `Session` continua igual; ela apenas recebe as pastas do perfil
  (`AppPaths.for_profile`). Isso reaproveitou todo o código já testado.
- O caminho de um perfil e o de um projeto **nunca vêm de um arquivo**: o ID é
  validado como ULID e o caminho é recalculado (`profiles/<id>`,
  `projects/<id>`) e conferido com `resolve()`. Um registro adulterado não
  aponta para a pasta de outro perfil.
- A chave de cada projeto é embrulhada com a chave mestra do perfil com AAD
  `nexus-intel/project/<id>`: copiar o registro de um perfil para outro não abre
  o projeto (teste `test_copied_registry_row_does_not_open_other_profile_project`).
- Editar ou excluir um perfil exige a **sessão desbloqueada do próprio perfil**;
  excluir exige ainda a senha e digitar o nome.
- Trocar de perfil fecha o projeto, apaga as chaves da memória, limpa o cache
  de imagens do Qt e a área de transferência (se o conteúdo for do NEXUS) e
  destrói as telas do perfil anterior.

**Limitação registrada.** Todos os perfis usam a mesma conta do Windows. O
sistema operacional não impede um perfil de *ver* os arquivos do outro; o que
impede a *leitura* é a criptografia. Um perfil criado **sem cifragem** (“só
login”, quando o SQLCipher não está disponível ou o usuário desmarca) fica
protegido apenas pela tela de entrada — a tela de criação avisa isso. O nome de
exibição e o avatar ficam no índice público porque aparecem antes do login,
como na tela de entrada do Windows.

### 2.2 Migração da 0.3.3

Na primeira abertura da 0.3.4, `ProfileManager.migrate_legacy()` move
`vault.json`, `app.nxdb*` (com WAL e cópias de migração) e `projects/` para
`profiles/<novo id>/` com `os.replace` (mesmo disco: instantâneo, sem copiar).
Uma marca (`migration-0.3.4.json`) permite retomar se o computador desligar no
meio. **Nada é apagado.** Os caminhos gravados no registro de projetos deixaram
de ser usados (são recalculados), então não precisam ser reescritos.

Migrações de banco (só criam tabelas novas):

| Banco    | Migração                 | Conteúdo                                   |
|----------|--------------------------|--------------------------------------------|
| projeto  | `0002_notas_fotos.sql`   | `note`, `attachment`, `entity_photo`        |
| perfil   | `0002_identidade.sql`    | `identity_key` (privadas cifradas)          |

Antes de migrar um banco existente, o NEXUS já faz uma cópia cifrada do arquivo
(mecanismo da 0.1, aparece na tela Backup).

### 2.3 Fotografias

- Armazenamento por conteúdo: `projects/<id>/blobs/<aa>/<sha256>.blob`. A mesma
  imagem em duas entidades ocupa um arquivo; a remoção só apaga o arquivo quando
  nenhuma entidade usa mais (coleta em `_gc_attachments`).
- Cada arquivo: `NXB1 || nonce(12) || AES-256-GCM(imagem)` com chave
  HKDF(chave do projeto, "nexus-intel/project-blobs/v1") e AAD
  `nexus-intel/blob/v1/<sha256>`. A leitura confere a tag GCM **e** o SHA-256.
- Validação pelo **conteúdo**: assinatura do arquivo (magic bytes) tem de bater
  com o decodificador do Pillow, a imagem precisa decodificar inteira, limite de
  50 MB e de 80 milhões de pixels (bomba de descompressão). A extensão é
  ignorada. Formatos: JPG, PNG, WEBP, GIF, BMP, TIFF (`images.FORMATS`).
- Metadados guardados: tipo, tamanho, dimensões, nome original, se há EXIF e se
  há GPS. A imagem original é preservada byte a byte; a remoção de EXIF ficou
  preparada (o visualizador já informa quando há localização GPS).
- Miniaturas e visualização são geradas **só na memória**; nada decifrado vai
  para disco.

### 2.4 Pacote `.nexus`

Ver o cabeçalho de `infrastructure/package/container.py` e
`application/sharing.py`. Resumo:

- Não é ZIP: cabeçalho público mínimo + fluxo de blocos AES-256-GCM de 1 MiB.
- Chave de conteúdo K nova por pacote (`secrets`); nonce = prefixo aleatório +
  contador — sem reutilização. AAD de cada bloco amarra o SHA-256 do cabeçalho,
  o índice e a marca de bloco final (detecta troca, remoção e truncamento; bytes
  extras são recusados).
- K protegida por senha (Argon2id, piso **e teto** de parâmetros contra DoS) ou,
  no modo preparado por identidade, por X25519 + HKDF para cada destinatário.
- Dentro: `manifest.json` (formato, versões, ID do projeto, contagens, SHA-256 de
  cada item), `tables/*.json` (todas as linhas, IDs preservados),
  `files/<sha256>` (as **fotografias reais**) e `signature.json` (Ed25519 do
  perfil sobre o SHA-256 do manifesto).
- Importação: verifica tudo enquanto grava numa pasta de preparação **dentro do
  perfil destinatário**, já cifrando com chaves novas; confere chaves
  estrangeiras, a correspondência fotos ↔ registros e a assinatura; só então a
  pasta vira projeto. Falha em qualquer ponto = nada é criado. ID repetido =
  cópia, nunca sobrescrita.
- Nomes internos validados por regex (sem `..`, barras invertidas ou caminhos
  absolutos); limites por item e totais.

## 3. Algoritmos, bibliotecas e parâmetros

| Uso                               | Algoritmo         | Biblioteca           | Parâmetros |
|-----------------------------------|-------------------|----------------------|------------|
| Senha do perfil → KEK             | Argon2id          | `cryptography`       | 256 MiB, t=3, p=4 (calibrado; piso 64 MiB, t=2) |
| Senha do pacote → KEK             | Argon2id          | `cryptography`       | 256 MiB, t=3, p=4; aceita até 1 GiB, t≤10, p≤16 |
| Dados (bancos)                    | AES-256 (SQLCipher 4) | `sqlcipher3-wheels` | chave bruta de 256 bits via HKDF |
| Fotografias, chaves, pacote       | AES-256-GCM       | `cryptography`       | nonce 96 bits, tag 128 bits |
| Subchaves                         | HKDF-SHA256       | `cryptography`       | rótulos distintos por uso |
| Acordo de chaves (destinatários)  | X25519            | `cryptography`       | chave efêmera por destinatário |
| Assinatura do pacote              | Ed25519           | `cryptography`       | sobre SHA-256 do manifesto |
| Integridade / identificação       | SHA-256           | `hashlib`            | arquivos, itens do pacote, impressões digitais |
| Aleatoriedade                     | CSPRNG do SO      | `secrets`/`os.urandom` | chaves, sais, nonces |

Senhas nunca são gravadas nem registradas em log; a verificação é o próprio
desembrulho GCM. `SecretKey` zera o material ao fechar (mitigação: o Python não
garante ausência de cópias na memória).

## 4. Consequências

- Perfis antigos continuam funcionando sem ação do usuário.
- Pacotes exigem NEXUS 0.3.4 ou mais novo; versões futuras recusam com mensagem
  clara se o pacote for de um formato mais novo.
- Pendências conhecidas: interface para escolher destinatários no modo por
  identidade; remoção de EXIF; anexos de documentos (PDF) usando o mesmo
  armazenamento das fotografias.
