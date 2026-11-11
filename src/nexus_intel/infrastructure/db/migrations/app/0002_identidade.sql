-- 0.3.4: par de chaves de identidade do perfil (privadas cifradas pela chave mestra).

CREATE TABLE identity_key (
    kind TEXT PRIMARY KEY CHECK (kind IN ('x25519','ed25519')),
    public_key TEXT NOT NULL,
    wrapped_private TEXT NOT NULL,
    created_at TEXT NOT NULL
);
