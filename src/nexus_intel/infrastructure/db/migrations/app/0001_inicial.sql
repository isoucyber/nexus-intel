-- Banco da aplicação (app.nxdb). Usuário e chaves ficam no vault.json.

CREATE TABLE project_registry (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL DEFAULT '#2dd4bf',
    icon TEXT NOT NULL DEFAULT 'folder',
    template TEXT NOT NULL DEFAULT 'blank',
    encrypted INTEGER NOT NULL DEFAULT 1,
    wrapped_project_key TEXT,
    created_at TEXT NOT NULL,
    last_opened_at TEXT,
    entity_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE app_setting (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);

CREATE TABLE login_event (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    username TEXT NOT NULL,
    success INTEGER NOT NULL,
    reason TEXT
);
