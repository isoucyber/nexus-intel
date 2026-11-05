# ADR-0001 — Decisões e desvios da v0.1 em relação à especificação

Data: 2026-11-04 · Status: aceito

Registro das decisões tomadas ao implementar a F0/F1, com o motivo de cada desvio da
especificação técnica v1.0.

## 1. Cofre de chaves (`vault.json`) corrigido

**Problema na especificação:** a seção 8.1 cifrava o `app.nxdb` com uma chave derivada da senha
e guardava ali os slots de chave e o contador de tentativas. Assim, a chave de recuperação não
conseguia abrir o banco onde está o próprio slot, e o atraso entre tentativas não podia ser lido
nem gravado antes do login.

**Decisão:** os dois slots (senha e recuperação) e o contador ficam no `vault.json`, em texto puro
(nenhum segredo em claro: os slots são AES-256-GCM). O `app.nxdb` é cifrado por
`HKDF(chave mestra, "app-db")`, então qualquer slot abre tudo, e trocar a senha só re-cifra um slot.
Não existe hash de senha separado: a senha é verificada pelo próprio desembrulho do slot.

## 2. Chave de recuperação: 52 caracteres Base32

256 bits em Base32 sem preenchimento ocupam 52 caracteres (a especificação dizia 40, que dariam
200 bits). Agrupada de 4 em 4, tolerante a espaços, minúsculas e confusões 0/O, 1/I, 8/B.

## 3. Argon2id da biblioteca `cryptography`

A `cryptography` (≥ 44) tem Argon2id nativo, o que elimina a dependência `argon2-cffi`.
Parâmetros: 256 MiB, 3 iterações, 4 vias, calibrados para baixo (até 64 MiB) em máquinas lentas.
Pisos (64 MiB, 2 iterações) são verificados ao ler o cofre, contra rebaixamento por edição do arquivo.

## 4. Acesso a dados com DB-API e migrações SQL numeradas

**Desvio:** a especificação previa SQLAlchemy + Alembic. Na v0.1 o acesso usa a DB-API do
`sqlite3`/`sqlcipher3` com SQL explícito, e as migrações são arquivos `NNNN_nome.sql` aplicados por
`PRAGMA user_version`, com cópia de segurança do arquivo (ainda cifrado) antes de migrar.

**Motivo:** menos uma camada entre o código e o SQLCipher (PRAGMA key, FTS5), menos dependências
no executável e consultas mais previsíveis. A troca para SQLAlchemy Core continua possível porque
todo o SQL está em `application/project_store.py`.

## 5. Grafo nativo em vez de Cytoscape.js na v0.1

**Desvio:** o grafo usa `QGraphicsView` com layout de força vetorizado em NumPy (500 nós em < 1 s),
plano B previsto na seção 22. O QtWebEngine (Chromium, ~150 MB) só entra na v0.2 com mapa e linha
do tempo, quando ele passa a pagar o próprio peso.

## 6. Camadas

A ordem aplicada é `ui → application → infrastructure → domain`, verificada por import-linter no CI.
A interface importa da infraestrutura apenas constantes do cofre e a validação de senha.

## 7. Conflitos calculados na leitura

O status epistêmico gravado é sempre o que o usuário escolheu. O conflito é calculado ao ler, pelas
regras do campo (`single`, `single_per_period`, `multi`), e exibido como “conflitante” sem
sobrescrever a escolha do usuário. Resolver a divergência (refutar ou encerrar a validade de uma
das afirmações) faz o aviso sumir sozinho.
