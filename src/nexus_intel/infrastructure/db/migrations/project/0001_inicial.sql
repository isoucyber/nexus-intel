-- Banco do projeto (.nxdb) — núcleo da seção 8.2, recorte da v0.1.
-- IDs ULID em texto; datas ISO 8601 em UTC.

CREATE TABLE project_meta (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT '',
    legal_basis TEXT NOT NULL DEFAULT '',
    retention_days INTEGER NOT NULL DEFAULT 30,
    created_at TEXT NOT NULL
);

CREATE TABLE setting (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);

CREATE TABLE entity_type (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    parent_id TEXT REFERENCES entity_type(id),
    icon TEXT NOT NULL DEFAULT 'circle',
    color TEXT NOT NULL DEFAULT '#94a3b8',
    is_builtin INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE field_def (
    id TEXT PRIMARY KEY,
    entity_type_id TEXT NOT NULL REFERENCES entity_type(id),
    key TEXT NOT NULL,
    label TEXT NOT NULL,
    datatype TEXT NOT NULL,          -- text, number, date, bool, url, email, phone, enum, entity, coord
    cardinality TEXT NOT NULL DEFAULT 'one',
    conflict_rule TEXT NOT NULL DEFAULT 'single',
    enum_options_json TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_sensitive INTEGER NOT NULL DEFAULT 0,
    UNIQUE (entity_type_id, key)
);

CREATE TABLE entity (
    id TEXT PRIMARY KEY,
    type_id TEXT NOT NULL REFERENCES entity_type(id),
    display_name TEXT NOT NULL,
    display_name_norm TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    description_md TEXT NOT NULL DEFAULT '',
    private_note TEXT NOT NULL DEFAULT '',
    color TEXT,
    icon TEXT,
    importance INTEGER NOT NULL DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
    record_status TEXT NOT NULL DEFAULT 'active' CHECK (record_status IN ('active','archived','trashed')),
    is_favorite INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    trashed_at TEXT,
    version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX ix_entity_type ON entity(type_id);
CREATE INDEX ix_entity_norm ON entity(display_name_norm);
CREATE INDEX ix_entity_updated ON entity(updated_at);
CREATE INDEX ix_entity_status ON entity(record_status);

CREATE TABLE entity_alias (
    id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    alias_norm TEXT NOT NULL
);
CREATE INDEX ix_alias_norm ON entity_alias(alias_norm);
CREATE INDEX ix_alias_entity ON entity_alias(entity_id);

CREATE TABLE entity_identifier (
    id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    scheme TEXT NOT NULL,
    value_norm TEXT NOT NULL
);
CREATE INDEX ix_identifier ON entity_identifier(scheme, value_norm);
CREATE INDEX ix_identifier_entity ON entity_identifier(entity_id);

CREATE TABLE source (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'other',
    url TEXT,
    author TEXT,
    published_at TEXT,
    accessed_at TEXT,
    reliability TEXT CHECK (reliability IS NULL OR reliability IN ('A','B','C','D','E','F')),
    is_discredited INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    record_status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE claim (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    field_def_id TEXT NOT NULL REFERENCES field_def(id),
    value_text TEXT,
    value_num REAL,
    value_date_start TEXT,
    value_date_end TEXT,
    value_date_precision TEXT,
    value_bool INTEGER,
    value_entity_id TEXT REFERENCES entity(id),
    valid_from TEXT,
    valid_to TEXT,
    epistemic_status TEXT NOT NULL DEFAULT 'unverified'
        CHECK (epistemic_status IN ('verified','reported','unverified','hypothesis','conflicting','refuted')),
    credibility INTEGER CHECK (credibility IS NULL OR credibility BETWEEN 1 AND 6),
    is_preferred INTEGER NOT NULL DEFAULT 0,
    is_sensitive INTEGER NOT NULL DEFAULT 0,
    review_at TEXT,
    note TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'manual',
    recorded_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX ix_claim_subject ON claim(subject_id, field_def_id);
CREATE INDEX ix_claim_value_entity ON claim(value_entity_id);
CREATE INDEX ix_claim_status ON claim(epistemic_status);

CREATE TABLE relation_type (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    inverse_label TEXT NOT NULL,
    directed INTEGER NOT NULL DEFAULT 1,
    color TEXT NOT NULL DEFAULT '#64748b',
    is_builtin INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE relation (
    id TEXT PRIMARY KEY,
    type_id TEXT NOT NULL REFERENCES relation_type(id),
    source_id TEXT NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    description TEXT NOT NULL DEFAULT '',
    valid_from TEXT,
    valid_to TEXT,
    epistemic_status TEXT NOT NULL DEFAULT 'unverified'
        CHECK (epistemic_status IN ('verified','reported','unverified','hypothesis','conflicting','refuted')),
    credibility INTEGER CHECK (credibility IS NULL OR credibility BETWEEN 1 AND 6),
    origin TEXT NOT NULL DEFAULT 'manual',
    record_status TEXT NOT NULL DEFAULT 'active' CHECK (record_status IN ('active','archived','trashed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    CHECK (source_id <> target_id)
);
CREATE INDEX ix_relation_source ON relation(source_id);
CREATE INDEX ix_relation_target ON relation(target_id);
CREATE INDEX ix_relation_type ON relation(type_id);

CREATE TABLE evidence (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source(id),
    target_kind TEXT NOT NULL CHECK (target_kind IN ('claim','relation','entity')),
    target_id TEXT NOT NULL,
    excerpt TEXT NOT NULL DEFAULT '',
    locator TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX ix_evidence_target ON evidence(target_kind, target_id);
CREATE INDEX ix_evidence_source ON evidence(source_id);

CREATE TABLE tag (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL DEFAULT '#64748b'
);

CREATE TABLE entity_tag (
    entity_id TEXT NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    tag_id TEXT NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
    PRIMARY KEY (entity_id, tag_id)
);

CREATE TABLE dedupe_decision (
    entity_a TEXT NOT NULL,
    entity_b TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('same','different')),
    decided_at TEXT NOT NULL,
    PRIMARY KEY (entity_a, entity_b)
);

CREATE TABLE revision (
    id TEXT PRIMARY KEY,
    object_kind TEXT NOT NULL,
    object_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    change_kind TEXT NOT NULL
);
CREATE INDEX ix_revision_object ON revision(object_kind, object_id, version);

CREATE TABLE audit_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    object_kind TEXT,
    object_id TEXT,
    summary TEXT NOT NULL DEFAULT '',
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);

CREATE VIRTUAL TABLE entity_fts USING fts5(
    entity_id UNINDEXED,
    name,
    aliases,
    body,
    tokenize = 'unicode61 remove_diacritics 2'
);
