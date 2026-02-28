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

CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name);
CREATE INDEX IF NOT EXISTS idx_ref_tags_tag ON ref_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_refs_location ON refs(location);
CREATE INDEX IF NOT EXISTS idx_refs_stale ON refs(stale);
