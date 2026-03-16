# Context Commander — Design Document

**Problem:** Long-running agent sessions fill context space and abort mid-task, losing work. Individual agents can't monitor their own context usage — they don't have visibility into it. Verbose tool output (Maven logs, git warnings, large diffs) accelerates the problem.

**Goal:** A retrieval-based working memory system. NOT brute-force 1M context. Tag/classify context continuously, evict by relevance not age, fetch by tag when needed. "Forgetting is a feature."

**Philosophy:** Don't store content — store pointers. The index is tiny; the content lives at the source and is fetched on demand, always fresh.

---

## Architecture

### Two Layers

1. **Skill (Phase 1)** — Behavioral self-monitoring. Agents self-index during work, query the index for relevant context, validate stale entries. Works with current OpenClaw.
2. **Gateway-level retrieval (Phase 2)** — Built into OpenClaw core. Transparent to agents and users. Web dashboard for visibility.

### Core Concept: Metadata Pointers

```
tag -> [{ location, contextMatch, score, fingerprint }, ...]
```

- **Location**: file path, URL, or inline snippet
- **Context match**: line range (files), section anchor / text fingerprint (web)
- **Score**: relevance to the tag (0.0–1.0)
- **Fingerprint**: base64-encoded content hash for staleness detection

References point to content — they don't duplicate it. When the agent needs context, it fetches from the source. This keeps the index tiny and content always fresh.

---

## Storage

### Current: SQLite

Single file, zero infrastructure, structured queries. Lives in the workspace.

**Plan to swap later** — SQLite won't scale if the index grows exponentially. Clean abstraction layer (`cc_db.py`) means the backend can be swapped to Postgres, a vector DB, or whatever without changing the skill or agent behavior.

### Schema

```sql
-- Core reference store
CREATE TABLE refs (
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
CREATE TABLE tags (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

-- Join table: score lives here (same ref can have different relevance per tag)
CREATE TABLE ref_tags (
    ref_id INTEGER NOT NULL REFERENCES refs(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    score  REAL NOT NULL DEFAULT 0.5,
    PRIMARY KEY (ref_id, tag_id)
);

-- Provenance: why was this indexed?
CREATE TABLE ref_origins (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_id     INTEGER NOT NULL REFERENCES refs(id) ON DELETE CASCADE,
    session_id TEXT,               -- which session triggered indexing
    reason     TEXT,               -- brief note on why
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_tags_name ON tags(name);
CREATE INDEX idx_ref_tags_tag ON ref_tags(tag_id);
CREATE INDEX idx_refs_location ON refs(location);
CREATE INDEX idx_refs_stale ON refs(stale);
```

### Key Schema Decisions

- **Score on the join table** — same reference can have different relevance to different tags
- **Fingerprint** — base64 hash of content at the referenced range. Fetch + rehash to detect drift.
- **ref_origins** — tracks provenance (which session, why) without cluttering the main table
- **Three types**: `file` (path + line range), `web` (URL + fingerprint), `snippet` (inline content for ephemeral/sourceless context like decisions, preferences, verbal agreements)

---

## Skill Structure

```
context-commander/
├── SKILL.md              # Agent behavioral instructions (when/how to self-index)
├── db/
│   └── schema.sql        # SQLite schema
├── scripts/
│   ├── cc.py             # CLI wrapper: index, query, validate, prune
│   └── cc_db.py          # Abstraction layer (swap this for Postgres later)
└── plans/
    └── roadmap.md        # Future: embeddings, vector search, dashboard
```

### CLI (`cc.py`)

```
cc index --tag AI --type file --location "path/to/file" --range 8-50
cc index --tag "design-decisions" --type snippet --snippet "Ship upgrades are permanent progression"
cc index --tag research --type web --location "https://..." --fingerprint <base64>

cc query --tag AI --min-score 0.7 --limit 5
cc query --tags "AI,design-decisions" --limit 10

cc validate                          # re-hash all non-snippet refs, flag stale
cc prune --stale --older-than 30d    # clean up stale/old entries
```

### Agent Behavior (SKILL.md)

Agents should:

1. **During work** — recognize when something is worth indexing, add it with appropriate tags and score
2. **When starting a task** — query the index for relevant tags to pull in context
3. **Periodically** — validate stale entries (cron or heartbeat)

---

## Staleness Detection

- On index: hash the content at the referenced range, store as `fingerprint` (base64)
- On fetch: re-hash the live content, compare to stored fingerprint
- If mismatch: flag `stale = 1`, optionally re-score or update the range
- Periodic `cc validate` sweeps catch drift without waiting for fetch-time checks

### Web Content Fingerprinting

- Base64-encode a hash of the text content around the match
- On re-fetch, extract text and rehash to relocate the relevant section
- If page structure changes but content is findable, update the reference
- If content is gone, flag stale

---

## Context Monitoring (Original Scope)

Still relevant as a complementary feature within the skill:

### Commander Role

- Monitor context depth (token count) per active session via `session_status` / `sessions_list`
- Thresholds: warning (70%), critical (85%), emergency (95%)
- Poke agents approaching limits to save state via `sessions_send`

### Agent Poke / Interrupt

- Inject "[CONTEXT_WARNING]" message into running sessions
- Agent saves durable state (memory files, checkpoints) and acknowledges
- If no ack within timeout, force-compact anyway

### Checkpoint Convention

- `CHECKPOINT.md` or `memory/session-state.json`
- Standard format: task, branch, files touched, next steps
- On session restart, agent reads checkpoint and resumes without re-asking user

---

## Implementation Phases

### Phase 1: Skill (NOW)

- [ ] SQLite schema + `cc_db.py` abstraction layer
- [ ] `cc.py` CLI with index/query/validate/prune
- [ ] SKILL.md with agent self-indexing instructions
- [ ] Context monitoring via session_status
- [ ] Poke mechanism via sessions_send
- [ ] Checkpoint convention (CHECKPOINT.md)

### Phase 2: Gateway Integration (LATER)

- [ ] Propose as OpenClaw feature (context-aware session management)
- [ ] Auto-truncation of tool output in gateway config
- [ ] Smart compaction that preserves semantic meaning
- [ ] Gateway-level retrieval system (tag-based context fetch built into prompt assembly)

### Phase 3: Intelligence (FUTURE)

- [ ] Embeddings for semantic search (not just tag matching)
- [ ] Auto-scoring based on recency + access frequency + semantic similarity
- [ ] Web dashboard for Jeremy to see what the agent "knows"
- [ ] Score decay over time (old references naturally lose relevance)
- [ ] Cross-session knowledge sharing (agent A indexes, agent B retrieves)

---

## Open Questions

- [ ] Duplicate message handling — does OpenClaw deduplicate inbound messages?
- [ ] Optimal tag granularity — too broad is useless, too narrow fragments knowledge
- [ ] When to cache a snippet vs. always fetch live — tradeoff between freshness and reliability
- [ ] How to handle multi-agent scenarios (shared index? per-agent partitions?)

---

_Created: 2026-02-18 by Nyx_
_Updated: 2026-02-20 — Full schema design, storage decisions, skill structure, CLI spec_
_Origin: Jeremy noticed sessions aborting during product catalog build due to context overflow from verbose Maven/git output_
