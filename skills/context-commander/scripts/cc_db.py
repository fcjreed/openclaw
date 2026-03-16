"""Context Commander — SQLite abstraction layer.

Clean class-based API for the Context Commander reference index.
Designed with a swappable backend in mind: no SQLite-specific logic
should leak beyond this module.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Default database path (relative to project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB_PATH = _PROJECT_ROOT / "db" / "context-commander.db"
_SCHEMA_PATH = _PROJECT_ROOT / "db" / "schema.sql"


class ContextCommanderDB:
    """Abstraction layer over the Context Commander SQLite store."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        """Open (or create) a database at *db_path*.

        Args:
            db_path: Path to the SQLite database file.
                     Defaults to ``db/context-commander.db`` inside the project.
        """
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def init_db(self) -> None:
        """Create all tables and indexes from the schema file."""
        schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        self._conn.executescript(schema_sql)

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()

    # ------------------------------------------------------------------
    # References
    # ------------------------------------------------------------------

    def add_ref(
        self,
        type: str,
        location: str | None = None,
        range_start: int | None = None,
        range_end: int | None = None,
        fingerprint: str | None = None,
        snippet: str | None = None,
    ) -> int:
        """Insert a new reference and return its id.

        Args:
            type: One of ``'file'``, ``'web'``, ``'snippet'``.
            location: File path or URL (None for pure snippets).
            range_start: Start line / char offset.
            range_end: End line / char offset.
            fingerprint: Base64-encoded content hash.
            snippet: Inline content (required for snippet type).

        Returns:
            The newly created ``ref_id``.

        Raises:
            ValueError: If *type* is not one of the allowed values.
        """
        if type not in ("file", "web", "snippet"):
            raise ValueError(f"Invalid ref type: {type!r}. Must be 'file', 'web', or 'snippet'.")

        cur = self._conn.execute(
            """
            INSERT INTO refs (type, location, range_start, range_end, fingerprint, snippet)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (type, location, range_start, range_end, fingerprint, snippet),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_ref(self, ref_id: int) -> dict[str, Any] | None:
        """Return a single reference with its tags, or *None* if not found.

        The returned dict contains all ``refs`` columns plus a ``tags`` key
        holding a list of ``{"name": ..., "score": ...}`` dicts.
        """
        row = self._conn.execute("SELECT * FROM refs WHERE id = ?", (ref_id,)).fetchone()
        if row is None:
            return None

        ref = dict(row)
        tags = self._conn.execute(
            """
            SELECT t.name, rt.score
            FROM ref_tags rt
            JOIN tags t ON t.id = rt.tag_id
            WHERE rt.ref_id = ?
            ORDER BY rt.score DESC
            """,
            (ref_id,),
        ).fetchall()
        ref["tags"] = [{"name": t["name"], "score": t["score"]} for t in tags]
        return ref

    def delete_ref(self, ref_id: int) -> bool:
        """Delete a reference by id.  Returns True if a row was deleted."""
        cur = self._conn.execute("DELETE FROM refs WHERE id = ?", (ref_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def update_fingerprint(self, ref_id: int, new_fingerprint: str) -> None:
        """Update the stored fingerprint for a reference."""
        self._conn.execute(
            "UPDATE refs SET fingerprint = ? WHERE id = ?",
            (new_fingerprint, ref_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Staleness
    # ------------------------------------------------------------------

    def mark_stale(self, ref_id: int) -> None:
        """Flag a reference as stale."""
        self._conn.execute(
            "UPDATE refs SET stale = 1 WHERE id = ?",
            (ref_id,),
        )
        self._conn.commit()

    def mark_fresh(self, ref_id: int, fingerprint: str) -> None:
        """Mark a reference as fresh with an updated fingerprint and validation timestamp."""
        self._conn.execute(
            "UPDATE refs SET stale = 0, fingerprint = ?, last_validated = datetime('now') WHERE id = ?",
            (fingerprint, ref_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def add_tag(self, name: str) -> int:
        """Insert a tag (or return existing id if it already exists).

        This is an upsert: the tag name is unique, so a conflict simply
        returns the existing row's id.

        Returns:
            The ``tag_id``.
        """
        # Try insert; on conflict do nothing, then select.
        self._conn.execute(
            "INSERT OR IGNORE INTO tags (name) VALUES (?)",
            (name,),
        )
        self._conn.commit()
        row = self._conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        return row["id"]  # type: ignore[index]

    def tag_ref(self, ref_id: int, tag_id: int, score: float = 0.5) -> None:
        """Link a reference to a tag with a relevance score.

        If the link already exists, the score is updated.
        """
        self._conn.execute(
            """
            INSERT INTO ref_tags (ref_id, tag_id, score)
            VALUES (?, ?, ?)
            ON CONFLICT(ref_id, tag_id) DO UPDATE SET score = excluded.score
            """,
            (ref_id, tag_id, score),
        )
        self._conn.commit()

    def list_tags(self) -> list[dict[str, Any]]:
        """Return all tags with their reference counts, sorted by name."""
        rows = self._conn.execute(
            """
            SELECT t.name, COUNT(rt.ref_id) AS ref_count
            FROM tags t
            LEFT JOIN ref_tags rt ON rt.tag_id = t.id
            GROUP BY t.id
            ORDER BY t.name
            """
        ).fetchall()
        return [{"name": r["name"], "ref_count": r["ref_count"]} for r in rows]

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def query_by_tags(
        self,
        tags: list[str],
        min_score: float = 0.0,
        limit: int = 10,
        include_stale: bool = False,
        exact: bool = False,
    ) -> list[dict[str, Any]]:
        """Find references matching any of the given tags.

        By default, tags are matched hierarchically using prefix expansion:
        querying ``ai`` matches ``ai``, ``ai/anthropic``, ``ai/anthropic/claude``, etc.
        Uses indexed range scans (``tag >= 'ai/' AND tag < 'ai0'``) for performance.

        Set *exact=True* to match only the literal tag names (no children).

        Results are ordered by maximum score descending.

        Args:
            tags: Tag names to search for.
            min_score: Minimum score threshold.
            limit: Maximum number of results.
            include_stale: Whether to include stale references.
            exact: If True, match only exact tag names (no prefix expansion).

        Returns:
            List of ref dicts (same shape as :meth:`get_ref`).
        """
        if not tags:
            return []

        stale_clause = "" if include_stale else "AND r.stale = 0"

        if exact:
            # Exact match: use IN clause
            placeholders = ",".join("?" for _ in tags)
            tag_clause = f"t.name IN ({placeholders})"
            tag_params: list[Any] = list(tags)
        else:
            # Hierarchical prefix match: exact OR starts with tag/
            # Uses range scan: tag >= 'prefix/' AND tag < 'prefix0' (0 is char after /)
            conditions = []
            tag_params = []
            for tag in tags:
                # Match exact tag name
                conditions.append("t.name = ?")
                tag_params.append(tag)
                # Match all children: tag/ <= name < tag0
                # chr(ord('/') + 1) = '0', so 'ai/' to 'ai0' covers 'ai/anything'
                conditions.append("(t.name >= ? AND t.name < ?)")
                tag_params.append(tag + "/")
                tag_params.append(tag + "0")  # '0' is next char after '/'
            tag_clause = "(" + " OR ".join(conditions) + ")"

        query = f"""
            SELECT r.*, MAX(rt.score) AS max_score
            FROM refs r
            JOIN ref_tags rt ON rt.ref_id = r.id
            JOIN tags t ON t.id = rt.tag_id
            WHERE {tag_clause}
              AND rt.score >= ?
              {stale_clause}
            GROUP BY r.id
            ORDER BY max_score DESC
            LIMIT ?
        """
        params: list[Any] = tag_params + [min_score, limit]
        rows = self._conn.execute(query, params).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            ref = dict(row)
            ref.pop("max_score", None)
            # Attach tags
            tag_rows = self._conn.execute(
                """
                SELECT t.name, rt.score
                FROM ref_tags rt
                JOIN tags t ON t.id = rt.tag_id
                WHERE rt.ref_id = ?
                ORDER BY rt.score DESC
                """,
                (ref["id"],),
            ).fetchall()
            ref["tags"] = [{"name": t["name"], "score": t["score"]} for t in tag_rows]
            results.append(ref)
        return results

    # ------------------------------------------------------------------
    # Pruning
    # ------------------------------------------------------------------

    def prune(
        self,
        stale_only: bool = False,
        older_than_days: int | None = None,
    ) -> int:
        """Delete references matching the given criteria.

        Args:
            stale_only: If True, only delete stale references.
            older_than_days: If set, only delete refs created more than
                this many days ago.

        Returns:
            Number of references deleted.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if stale_only:
            conditions.append("stale = 1")
        if older_than_days is not None:
            cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            conditions.append("created_at < ?")
            params.append(cutoff)

        if not conditions:
            # No filters → delete everything
            cur = self._conn.execute("DELETE FROM refs")
        else:
            where = " AND ".join(conditions)
            cur = self._conn.execute(f"DELETE FROM refs WHERE {where}", params)

        self._conn.commit()
        return cur.rowcount

    # ------------------------------------------------------------------
    # Origins (provenance)
    # ------------------------------------------------------------------

    def add_origin(
        self,
        ref_id: int,
        session_id: str | None = None,
        reason: str | None = None,
    ) -> int:
        """Record why a reference was indexed.

        Returns:
            The origin row id.
        """
        cur = self._conn.execute(
            "INSERT INTO ref_origins (ref_id, session_id, reason) VALUES (?, ?, ?)",
            (ref_id, session_id, reason),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Bulk helpers (used by validate)
    # ------------------------------------------------------------------

    def all_file_refs(self) -> list[dict[str, Any]]:
        """Return all file-type references (for validation sweeps)."""
        rows = self._conn.execute(
            "SELECT * FROM refs WHERE type = 'file'"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Activity Logging
    # ------------------------------------------------------------------

    def log_activity(
        self,
        operation: str,
        agent_id: str | None = None,
        session_key: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> int:
        """Record an agent memory operation.

        Args:
            operation: The operation type (e.g., 'cc_query', 'memory_search').
            agent_id: Agent identifier (e.g., 'main', 'discord').
            session_key: Full session key.
            details: Optional JSON-serializable dict with operation-specific data.

        Returns:
            The activity_log row id.
        """
        import json as _json

        details_str = _json.dumps(details) if details else None
        cur = self._conn.execute(
            """
            INSERT INTO activity_log (operation, agent_id, session_key, details)
            VALUES (?, ?, ?, ?)
            """,
            (operation, agent_id, session_key, details_str),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_activity(
        self,
        agent_id: str | None = None,
        operation: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query recent activity log entries.

        Args:
            agent_id: Filter by agent (optional).
            operation: Filter by operation type (optional).
            since: ISO datetime string — only return entries after this time.
            limit: Maximum entries to return.

        Returns:
            List of activity log dicts, newest first.
        """
        import json as _json

        conditions: list[str] = []
        params: list[Any] = []

        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)
        if operation:
            conditions.append("operation = ?")
            params.append(operation)
        if since:
            conditions.append("created_at >= ?")
            params.append(since)

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"SELECT * FROM activity_log{where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            entry = dict(row)
            if entry.get("details"):
                try:
                    entry["details"] = _json.loads(entry["details"])
                except (ValueError, TypeError):
                    pass
            results.append(entry)
        return results

    def get_agent_compliance(self, days: int = 7) -> dict[str, Any]:
        """Get per-agent compliance summary over the last N days.

        Returns a dict with:
            agents: list of per-agent stats (reads, writes, cc_queries, cc_indexes, last_active)
            period_days: the number of days covered
            total_operations: total operations in the period
        """
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

        # Get all agents that have any activity
        rows = self._conn.execute(
            """
            SELECT
                COALESCE(agent_id, '(unknown)') AS agent,
                COUNT(*) AS total_ops,
                SUM(CASE WHEN operation IN ('cc_query', 'memory_search', 'memory_get', 'memory_read') THEN 1 ELSE 0 END) AS reads,
                SUM(CASE WHEN operation IN ('cc_index', 'memory_write') THEN 1 ELSE 0 END) AS writes,
                SUM(CASE WHEN operation = 'cc_query' THEN 1 ELSE 0 END) AS cc_queries,
                SUM(CASE WHEN operation = 'cc_index' THEN 1 ELSE 0 END) AS cc_indexes,
                SUM(CASE WHEN operation = 'memory_search' THEN 1 ELSE 0 END) AS memory_searches,
                SUM(CASE WHEN operation = 'memory_get' THEN 1 ELSE 0 END) AS memory_gets,
                SUM(CASE WHEN operation = 'memory_write' THEN 1 ELSE 0 END) AS memory_writes,
                MAX(created_at) AS last_active
            FROM activity_log
            WHERE created_at >= ?
            GROUP BY COALESCE(agent_id, '(unknown)')
            ORDER BY total_ops DESC
            """,
            (cutoff,),
        ).fetchall()

        agents = []
        total_ops = 0
        for row in rows:
            agent_data = dict(row)
            total_ops += agent_data["total_ops"]
            agents.append(agent_data)

        # Activity timeline (operations per day)
        timeline_rows = self._conn.execute(
            """
            SELECT DATE(created_at) AS day,
                   COALESCE(agent_id, '(unknown)') AS agent,
                   COUNT(*) AS count
            FROM activity_log
            WHERE created_at >= ?
            GROUP BY DATE(created_at), COALESCE(agent_id, '(unknown)')
            ORDER BY day DESC
            """,
            (cutoff,),
        ).fetchall()

        timeline = [dict(r) for r in timeline_rows]

        return {
            "agents": agents,
            "period_days": days,
            "total_operations": total_ops,
            "timeline": timeline,
        }

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return aggregate statistics about the reference index.

        Returns a dict with keys:
            total_refs, refs_by_type, total_tags, stale_count, fresh_count,
            avg_score, score_distribution, oldest_ref, newest_ref,
            top_tags (by ref count), recent_activity (refs added last 7 days),
            db_size_bytes, total_tag_assignments, orphan_tags
        """
        s: dict[str, Any] = {}

        # Total refs
        row = self._conn.execute("SELECT COUNT(*) AS c FROM refs").fetchone()
        s["total_refs"] = row["c"]

        # Refs by type
        rows = self._conn.execute(
            "SELECT type, COUNT(*) AS c FROM refs GROUP BY type ORDER BY type"
        ).fetchall()
        s["refs_by_type"] = {r["type"]: r["c"] for r in rows}

        # Total tags
        row = self._conn.execute("SELECT COUNT(*) AS c FROM tags").fetchone()
        s["total_tags"] = row["c"]

        # Stale / fresh counts
        row = self._conn.execute("SELECT COUNT(*) AS c FROM refs WHERE stale = 1").fetchone()
        s["stale_count"] = row["c"]
        s["fresh_count"] = s["total_refs"] - s["stale_count"]

        # Average score across all tag assignments
        row = self._conn.execute("SELECT AVG(score) AS a, MIN(score) AS mn, MAX(score) AS mx FROM ref_tags").fetchone()
        s["avg_score"] = round(row["a"], 3) if row["a"] is not None else None
        s["min_score"] = round(row["mn"], 3) if row["mn"] is not None else None
        s["max_score"] = round(row["mx"], 3) if row["mx"] is not None else None

        # Score distribution (buckets: 0-0.3, 0.3-0.5, 0.5-0.7, 0.7-0.9, 0.9-1.0)
        buckets = [
            ("low", 0.0, 0.3),
            ("medium", 0.3, 0.5),
            ("good", 0.5, 0.7),
            ("high", 0.7, 0.9),
            ("critical", 0.9, 1.01),
        ]
        dist: dict[str, int] = {}
        for label, lo, hi in buckets:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM ref_tags WHERE score >= ? AND score < ?",
                (lo, hi),
            ).fetchone()
            dist[label] = row["c"]
        s["score_distribution"] = dist

        # Total tag assignments (ref_tags rows)
        row = self._conn.execute("SELECT COUNT(*) AS c FROM ref_tags").fetchone()
        s["total_tag_assignments"] = row["c"]

        # Oldest and newest refs
        row = self._conn.execute("SELECT MIN(created_at) AS oldest, MAX(created_at) AS newest FROM refs").fetchone()
        s["oldest_ref"] = row["oldest"]
        s["newest_ref"] = row["newest"]

        # Top tags by ref count (top 10)
        rows = self._conn.execute(
            """
            SELECT t.name, COUNT(rt.ref_id) AS ref_count
            FROM tags t
            JOIN ref_tags rt ON rt.tag_id = t.id
            GROUP BY t.id
            ORDER BY ref_count DESC
            LIMIT 10
            """
        ).fetchall()
        s["top_tags"] = [{"name": r["name"], "ref_count": r["ref_count"]} for r in rows]

        # Recent activity: refs added in last 7 days, grouped by day
        rows = self._conn.execute(
            """
            SELECT DATE(created_at) AS day, COUNT(*) AS c
            FROM refs
            WHERE created_at >= datetime('now', '-7 days')
            GROUP BY DATE(created_at)
            ORDER BY day DESC
            """
        ).fetchall()
        s["recent_activity"] = [{"day": r["day"], "count": r["c"]} for r in rows]

        # Orphan tags (tags with no refs)
        row = self._conn.execute(
            """
            SELECT COUNT(*) AS c FROM tags t
            WHERE NOT EXISTS (SELECT 1 FROM ref_tags rt WHERE rt.tag_id = t.id)
            """
        ).fetchone()
        s["orphan_tags"] = row["c"]

        # DB file size
        import os
        try:
            s["db_size_bytes"] = os.path.getsize(str(self.db_path))
        except OSError:
            s["db_size_bytes"] = None

        # Activity summary (last 7 days)
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM activity_log WHERE created_at >= datetime('now', '-7 days')"
            ).fetchone()
            s["activity_ops_7d"] = row["c"] if row else 0

            rows = self._conn.execute(
                """
                SELECT COALESCE(agent_id, '(unknown)') AS agent, COUNT(*) AS c
                FROM activity_log
                WHERE created_at >= datetime('now', '-7 days')
                GROUP BY COALESCE(agent_id, '(unknown)')
                ORDER BY c DESC
                LIMIT 5
                """
            ).fetchall()
            s["active_agents_7d"] = [{"agent": r["agent"], "count": r["c"]} for r in rows]
        except Exception:
            # Table might not exist yet in older DBs
            s["activity_ops_7d"] = 0
            s["active_agents_7d"] = []

        return s


if __name__ == "__main__":
    # Quick sanity check
    db = ContextCommanderDB()
    db.init_db()
    print(f"Database initialized at {db.db_path}")
    db.close()
