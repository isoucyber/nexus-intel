-- 0.4.0: assistente de IA (ADR-0004).
-- Só cria tabelas novas: nenhum dado existente é alterado.

-- Sugestões da IA. Nada entra no projeto sem aprovação: a IA só grava aqui,
-- com estado pendente; aprovar aplica pelo fluxo normal (com revisão e auditoria).
CREATE TABLE suggestion (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('entity','relation','claim','note')),
    payload_json TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'ai',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    created_at TEXT NOT NULL,
    decided_at TEXT,
    decision_note TEXT NOT NULL DEFAULT '',
    result_id TEXT
);
CREATE INDEX ix_suggestion_status ON suggestion(status, created_at);

-- Índice da busca semântica: um vetor por entidade e modelo. É derivado dos dados
-- (pode ser refeito a qualquer momento), por isso não vai para o pacote .nexus.
CREATE TABLE embedding (
    entity_id TEXT NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    text_sha256 TEXT NOT NULL,
    vector BLOB NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (entity_id, model)
);
