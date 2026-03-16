---
name: context-commander
description: "Retrieval-based working memory for AI agents. Index pointers to files, web pages, and snippets with tags and relevance scores. Query by tag to pull in context on demand. Validate staleness via SHA-256 fingerprinting. Use when: (1) starting a task and need relevant context, (2) after significant work to index what was done, (3) periodic validation of stale references. NOT for: ephemeral throwaway context or brute-force context stuffing."
metadata:
  openclaw:
    emoji: "🧠"
---

# Context Commander

Retrieval-based working memory for AI agents. Store pointers to relevant context — not the content itself — and fetch on demand.

## Quick Reference

```bash
# Index a file reference
python scripts/cc.py index --type file --location "path/to/file.py" --range 10-50 --tag "auth-system" --score 0.9

# Index a snippet (inline content with no source file)
python scripts/cc.py index --type snippet --snippet "JWT tokens expire after 24h, refresh after 12h" --tag "auth-decisions" --score 1.0

# Index a web reference
python scripts/cc.py index --type web --location "https://docs.example.com/api" --tag "api-docs" --score 0.7

# Query by tags
python scripts/cc.py query --tags "auth-system,auth-decisions" --min-score 0.5 --limit 10

# Check for stale references
python scripts/cc.py validate

# Clean up
python scripts/cc.py prune --stale
python scripts/cc.py prune --older-than 30

# Browse
python scripts/cc.py tags
python scripts/cc.py show 42
```

## When to Index

Index after:

- **Significant code changes** — new modules, refactored architecture, critical bug fixes
- **Design decisions** — use snippet type to capture the _why_ behind choices
- **Discovery of important patterns** — how auth works, where config lives, build quirks
- **External references** — docs, Stack Overflow answers, API specs that informed decisions

Do NOT index:

- Trivial changes (typo fixes, import reordering)
- Temporary debug code
- Content that will be outdated within the same session

## When to Query

Query at:

- **Session start** — pull in context for the area you'll be working in
- **Task switch** — when pivoting to a different subsystem, query its tags first
- **Before making changes** — check if there are indexed design decisions or patterns for the area
- **When stuck** — query broadly to find related context you may have forgotten

## Tag Naming Conventions

Tags use **hierarchical paths** with `/` as delimiter. Queries automatically expand to match all children (prefix matching via indexed range scans).

- **Lowercase, hyphenated segments**: `project/roguelike/design/scaling`
- **Descriptive but concise**: prefer `project/roguelike` over `p/r` or `the-roguelike-game-project`
- **Use `--exact` flag** when you need only the literal tag, no children

### Querying Hierarchy

```bash
# Broad: everything under project/
cc query --tags project

# Narrow: just the roguelike game
cc query --tags project/roguelike

# Precise: just scaling decisions
cc query --tags project/roguelike/design/scaling

# Exact match only (no children)
cc query --tags project/roguelike --exact
```

### Standard Taxonomy

| Path                              | Use for                                            |
| --------------------------------- | -------------------------------------------------- |
| `project/{name}`                  | Top-level project reference                        |
| `project/{name}/tech`             | Stack, dependencies, build config                  |
| `project/{name}/design`           | Architecture, design decisions                     |
| `project/{name}/design/{topic}`   | Specific design areas (scaling, progression)       |
| `project/{name}/systems/{system}` | Game/app subsystems (loot, auth, payments)         |
| `project/{name}/status`           | Current state, blockers, next steps                |
| `people/{name}`                   | Person-specific context (permissions, preferences) |
| `env/{topic}`                     | Environment: workspace, tools, paths               |
| `concept/{domain}`                | Domain knowledge (ai, gamedev, insurance)          |
| `concept/{domain}/{sub}`          | Specific subtopics (ai/anthropic, gamedev/godot)   |

## Score Guidelines

| Score       | Meaning                              | Example                                 |
| ----------- | ------------------------------------ | --------------------------------------- |
| **1.0**     | Critical — must-read for this tag    | Core auth middleware, main schema file  |
| **0.8–0.9** | Important — very relevant            | Key utility functions, important config |
| **0.5–0.7** | Reference — useful but not essential | Related tests, secondary docs           |
| **0.3–0.4** | Background — for completeness        | Tangentially related files              |
| **< 0.3**   | Low — may be pruned aggressively     | Rarely needed, contextual only          |

## Staleness Management

### How Fingerprinting Works

- When a file ref is indexed, a SHA-256 hash of the content at the specified line range is stored
- `cc validate` re-reads the file, re-hashes, and compares to the stored fingerprint
- Mismatches → ref is flagged stale
- Missing files → ref is flagged stale

### Validation Cadence

- Run `cc validate` at the **start of each session**
- Run after **significant file changes** (large refactors, branch switches)
- Consider periodic validation if sessions run for extended periods

### Handling Stale Refs

1. Query results **exclude stale refs by default** (use `--include-stale` to see them)
2. Review stale refs: they may need re-indexing with updated ranges
3. Prune refs that are no longer relevant: `cc prune --stale`

## Example Workflows

### Starting a New Feature

```bash
# 1. Query for related context
python scripts/cc.py query --tags "auth-system,user-model" --min-score 0.5

# 2. Read the referenced files to build understanding

# 3. After implementation, index the new code
python scripts/cc.py index --type file --location "src/features/oauth.py" --range 1-80 --tag "auth-system,oauth" --score 0.9

# 4. Record the design decision
python scripts/cc.py index --type snippet --snippet "OAuth chosen over SAML for simplicity; tokens stored in httpOnly cookies" --tag "auth-decisions,oauth" --score 1.0
```

### Resuming a Session

```bash
# 1. Validate existing refs
python scripts/cc.py validate

# 2. Prune anything broken
python scripts/cc.py prune --stale

# 3. Query for your working area
python scripts/cc.py query --tags "current-task,backend-api" --limit 20

# 4. Read referenced files and resume work
```

### Exploring the Index

```bash
# See what's been tracked
python scripts/cc.py tags

# Dive into a specific area
python scripts/cc.py query --tags "database-schema" --include-stale

# Inspect a specific reference
python scripts/cc.py show 15
```

## Architecture Notes

- **Storage**: SQLite (single file at `db/context-commander.db`)
- **Abstraction**: `scripts/cc_db.py` — clean Python API, designed to be swappable to another backend
- **CLI**: `scripts/cc.py` — stdlib only (argparse, sqlite3, hashlib, pathlib)
- **No external dependencies** — runs anywhere Python 3.11+ is available
