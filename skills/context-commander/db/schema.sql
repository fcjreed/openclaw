-- Context Commander Schema
-- Retrieval-based working memory for AI agents

-- Core reference store
CREATE TABLE IF NOT EXISTS refs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    type            TEXT NOT NULL CHECK(type IN ('file', 'web', 'snippet')),
    location        TEXT,              -- file path or URL (null for pure snippets)
    range_start     INTEGER,           -- line start (files) or char offset
    range_end       INTEGER,           -- line end or char offset
    fingerprint     TEXT,              -- base64 content hash for staleness detection
    snippet         TEXT,              -- stored content (snippets only, or cached excerpt)
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_validated  TEXT,
    stale           INTEGER NOT NULL DEFAULT 0
);

-- Tags (many-to-many)
CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

-- Join table: score lives here (same ref can have different relevance per tag)
CREATE TABLE IF NOT EXISTS ref_tags (
    ref_id INTEGER NOT NULL REFERENCES refs(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    score  REAL NOT NULL DEFAULT 0.5,
    PRIMARY KEY (ref_id, tag_id)
);

-- Provenance: why was this indexed?
CREATE TABLE IF NOT EXISTS ref_origins (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_id     INTEGER NOT NULL REFERENCES refs(id) ON DELETE CASCADE,
    session_id TEXT,               -- which session triggered indexing
    reason     TEXT,               -- brief note on why
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Activity log: tracks all memory operations by agent/session
CREATE TABLE IF NOT EXISTS activity_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    operation   TEXT NOT NULL,       -- 'cc_query', 'cc_index', 'cc_delete', 'cc_validate', 'cc_prune',
                                     -- 'memory_search', 'memory_get', 'memory_read', 'memory_write'
    agent_id    TEXT,                -- e.g., 'main', 'discord', sub-agent label
    session_key TEXT,                -- full session key (e.g., 'agent:main:discord:316355197024600067')
    details     TEXT,                -- JSON blob with operation-specific data
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name);
CREATE INDEX IF NOT EXISTS idx_ref_tags_tag ON ref_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_refs_location ON refs(location);
CREATE INDEX IF NOT EXISTS idx_refs_stale ON refs(stale);
CREATE INDEX IF NOT EXISTS idx_activity_log_agent ON activity_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_activity_log_op ON activity_log(operation);
CREATE INDEX IF NOT EXISTS idx_activity_log_created ON activity_log(created_at DESC);
