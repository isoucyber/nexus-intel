-- 0.3.4: Nexus Notepad e fotografias das entidades.
-- Só cria tabelas novas: nenhum dado existente é alterado.

CREATE TABLE note (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    entity_id TEXT REFERENCES entity(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX ix_note_updated ON note(updated_at);
CREATE INDEX ix_note_entity ON note(entity_id);

-- Um arquivo físico por conteúdo (SHA-256): a mesma imagem em duas entidades
-- ocupa um único arquivo cifrado em <projeto>/blobs/.
CREATE TABLE attachment (
    id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE CHECK (length(sha256) = 64),
    kind TEXT NOT NULL DEFAULT 'image' CHECK (kind IN ('image')),
    mime TEXT NOT NULL,
    size INTEGER NOT NULL,
    width INTEGER,
    height INTEGER,
    original_name TEXT NOT NULL DEFAULT '',
    has_exif INTEGER NOT NULL DEFAULT 0,
    has_gps INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE entity_photo (
    id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    attachment_id TEXT NOT NULL REFERENCES attachment(id),
    position INTEGER NOT NULL DEFAULT 0,
    caption TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (entity_id, attachment_id)
);
CREATE INDEX ix_photo_entity ON entity_photo(entity_id, position);
CREATE INDEX ix_photo_attachment ON entity_photo(attachment_id);
