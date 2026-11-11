# NEXUS INTEL — Auditoria de segurança e relatório de riscos (0.3.4)

Método: leitura do código de todas as camadas (domínio, infraestrutura, aplicação, interface),
dos fluxos de autenticação, armazenamento, importação/exportação, e do processo de build;
referência OWASP ASVS 4.0 (V2 autenticação, V3 sessão, V6 criptografia, V7 logs, V8 dados,
V12 arquivos, V14 configuração) adaptada a um aplicativo de desktop sem rede. Ferramentas:
`ruff` com regras de segurança (Bandit, S*), `pip-audit` (base OSV/PyPI) e testes automatizados.

Arquitetura confirmada: **Qt Widgets (PySide6), não Electron**. Não há navegador embutido, IPC,
servidor nem porta aberta; itens específicos de Electron (contextIsolation, CSP, preload) não se
aplicam. O equivalente em Qt — rótulos que interpretam HTML — foi auditado (achado A1).

Classificação: Crítico · Alto · Médio · Baixo. **Status só é “Corrigido” quando há teste
automatizado que comprova a correção** (arquivos citados), rodando no CI em Windows e Linux.

## Achados

| ID | Crit. | Achado | Status | Evidência (teste) |
|---|---|---|---|---|
| A1 | **Alto** | Rótulos, caixas de confirmação e dicas do Qt interpretavam como HTML qualquer texto que “parecesse” HTML. Um `.nexus` malicioso poderia trazer nomes como `<img src=file:///…>` ou links falsos “Verificado” e falsificar a interface ou carregar arquivos locais em rótulos | Corrigido: texto puro em `text()`, `label()`, `ElidedLabel`, erros de campo e `QMessageBox`; `safe_tooltip()` escapa dicas; HTML intencional (fontes/links) já era escapado | `tests/ui/test_v034_security_ui.py` |
| A2 | **Alto** | Chave de recuperação copiada ficava indefinidamente na área de transferência e no Histórico do Windows (Win+V) | Corrigido: cópia marcada para não entrar no histórico/nuvem e apagada em 60 s; limpeza também ao bloquear/trocar de perfil | `test_recovery_key_copy_is_cleared` |
| A3 | **Alto** | Operações sensíveis sem reautenticação: com uma sessão esquecida aberta era possível exportar o projeto inteiro, gerar nova chave de recuperação (acesso permanente) ou excluir projetos | Corrigido no **backend** (`Session.require_recent_auth`, janela de 2 min) e na interface (`ReauthDialog`): exportar, nova chave de recuperação, nova chave de identidade, excluir projeto; excluir perfil já exigia senha | `test_sensitive_operations_require_recent_password`, `test_export_asks_password_again_when_session_is_old` |
| A4 | Médio | SQLite podia gravar tabelas temporárias (ordenações, índices transitórios) em arquivos temporários | Corrigido: `PRAGMA temp_store = MEMORY`; `secure_delete = ON` zera conteúdo apagado | `test_no_plaintext_leaks_to_profile_files_logs_or_temp` |
| A5 | Médio | Tentativas de senha erradas não ficavam visíveis ao dono do perfil | Corrigido: contagem desde o último acesso, aviso após entrar e registro no log de segurança | `test_failed_attempts_are_reported_on_next_login` |
| A6 | Médio | Não havia registro de eventos de segurança | Corrigido: tabela `security_event` no banco cifrado do perfil, encadeada por SHA-256 (adulteração detectável), visível em Configurações; nunca recebe senhas, chaves ou conteúdo | `test_security_log_is_chained_and_tamper_evident` |
| A7 | Médio | Reimportação/repetição de um mesmo pacote passava despercebida | Corrigido: `package_id` aleatório no manifesto e registro de pacotes importados; a prévia avisa | `test_reimport_of_same_package_is_detected` |
| A8 | Médio | Itens do `.nexus` lidos inteiros na memória com limite alto (1 GiB por tabela) | Corrigido: 256 MiB por tabela, 64 MiB por arquivo, 8 GiB no total, teto nos parâmetros do Argon2id | `test_kdf_bounds_block_denial_of_service`, `test_invalid_crypto_parameters_in_header_are_rejected` |
| A9 | Médio | Backup/exportação não era conferido depois de gravado | Corrigido: o arquivo é relido, decifrado e verificado (SHA-256 + assinatura) antes de ser entregue | `test_export_verifies_package_before_delivering` |
| A10 | Médio | Importação interrompida (queda de energia) deixava pasta de preparação | Corrigido: removida ao abrir a lista de projetos; nunca vira projeto | `test_interrupted_import_leftovers_are_removed` |
| A11 | Médio | Impressão digital mostrada nas Configurações vinha do índice público (editável) | Corrigido: lida do banco cifrado do perfil | revisão de código |
| A12 | Médio | Cadeia de suprimentos sem verificação automática | Corrigido em parte: `pip-audit` (sem vulnerabilidades conhecidas em 10/11/2026), regras de segurança no CI, atestado de procedência Sigstore nos instaladores | job “Dependências” do CI |
| A13 | Baixo | Rotação da chave de identidade inexistente | Corrigido: “Gerar nova chave de identidade” (exige senha) | `test_sensitive_operations_require_recent_password` |
| A14 | Baixo | SQL dinâmico sinalizado pela análise estática (7 pontos) | Revisado: só junta constantes e marcadores `?`; valores sempre parametrizados; ordenações por lista fixa | `test_sql_injection_payloads_are_plain_data` |

Verificações sem achado (com teste): acesso cruzado entre perfis por ID/caminho/registro
copiado (`test_profiles_isolation.py`), manipulação de IDs de projeto (`test_identifier_manipulation_is_rejected`),
`.nexus` com senha errada, byte alterado, truncado, com dados extras, re-cifrado com foto trocada,
manifesto alterado, nomes de caminho maliciosos, versão incompatível (`test_nexus_package.py`),
imagens falsas/truncadas/gigantes e arquivo corrompido no disco (`test_notes_photos.py`).

## Pendências (riscos aceitos ou planejados)

| ID | Crit. | Item | Plano |
|---|---|---|---|
| P1 | Médio | Dependências do build não fixadas com hash (`pip install .` resolve na hora) | Arquivo de travamento com hashes (`--require-hashes`) no build de release |
| P2 | Médio | Instalador sem assinatura de código (Windows SmartScreen) | Requer certificado de assinatura de código (pago); enquanto isso: SHA256SUMS + atestado Sigstore (`gh attestation verify NexusIntel-Setup-0.3.4.exe --repo isoucyber/nexus-intel`) |
| P3 | Médio | Perfil “sem cifragem” protegido só pela tela de login | Aviso explícito na criação; avaliar bloquear a criação quando o SQLCipher estiver disponível |
| P4 | Baixo | Exclusão de perfil não fica registrada (o registro pertence ao perfil apagado) | Registro global mínimo, sem dados pessoais |
| P5 | Baixo | Remoção de EXIF ao importar/exportar fotos | Opção por foto e na exportação |
| P6 | Baixo | Interface para enviar `.nexus` a destinatários (modo X25519 já implementado e testado) | Catálogo de contatos com impressão digital conferida |
| P7 | — | Backup automático agendado | Módulo Backup (0.3.5+), reaproveitando a exportação verificada |
| P8 | — | Bloquear ao bloquear a tela/suspender o Windows | Hoje: bloqueio por inatividade (padrão 10 min) e Ctrl+L |

Nenhum software é 100% seguro. Os limites do modelo estão em `modelo-de-ameacas.md`.
