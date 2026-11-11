-- 0.3.4 (segurança): registro de eventos de segurança do perfil, encadeado por SHA-256,
-- e pacotes .nexus já importados (detecção de reimportação/repetição).

CREATE TABLE security_event (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);

CREATE TABLE imported_package (
    package_id TEXT PRIMARY KEY,
    imported_at TEXT NOT NULL,
    project_id TEXT NOT NULL,
    signer TEXT NOT NULL DEFAULT ''
);
