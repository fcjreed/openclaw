"""Comprehensive tests for Context Commander Phase 1.

Covers:
- All cc_db.py methods (ContextCommanderDB)
- CLI commands via subprocess
- Staleness detection workflow
- Pruning
- Edge cases (duplicate tags, missing files, invalid ranges)
"""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Ensure scripts/ is importable
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from cc_db import ContextCommanderDB  # noqa: E402

CC_PY = _SCRIPTS_DIR / "cc.py"


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def db(tmp_path: Path) -> ContextCommanderDB:
    """Provide an initialised in-memory-ish DB in a temp directory."""
    db_path = tmp_path / "test.db"
    d = ContextCommanderDB(db_path=db_path)
    d.init_db()
    yield d
    d.close()


@pytest.fixture()
def sample_file(tmp_path: Path) -> Path:
    """Create a small sample file for fingerprint testing."""
    p = tmp_path / "sample.txt"
    p.write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")
    return p


# ===========================================================================
# cc_db.py — ContextCommanderDB
# ===========================================================================


class TestAddRef:
    def test_add_file_ref(self, db: ContextCommanderDB) -> None:
        ref_id = db.add_ref("file", location="/tmp/foo.py", range_start=1, range_end=10)
        assert ref_id is not None
        assert ref_id > 0

    def test_add_snippet_ref(self, db: ContextCommanderDB) -> None:
        ref_id = db.add_ref("snippet", snippet="Ship upgrades are permanent")
        assert ref_id > 0

    def test_add_web_ref(self, db: ContextCommanderDB) -> None:
        ref_id = db.add_ref("web", location="https://example.com", fingerprint="abc123")
        assert ref_id > 0

    def test_invalid_type_raises(self, db: ContextCommanderDB) -> None:
        with pytest.raises(ValueError, match="Invalid ref type"):
            db.add_ref("video")


class TestGetRef:
    def test_get_existing(self, db: ContextCommanderDB) -> None:
        ref_id = db.add_ref("snippet", snippet="hello")
        ref = db.get_ref(ref_id)
        assert ref is not None
        assert ref["type"] == "snippet"
        assert ref["snippet"] == "hello"
        assert ref["tags"] == []

    def test_get_nonexistent(self, db: ContextCommanderDB) -> None:
        assert db.get_ref(9999) is None

    def test_get_with_tags(self, db: ContextCommanderDB) -> None:
        ref_id = db.add_ref("snippet", snippet="tagged")
        tag_id = db.add_tag("test-tag")
        db.tag_ref(ref_id, tag_id, 0.9)

        ref = db.get_ref(ref_id)
        assert ref is not None
        assert len(ref["tags"]) == 1
        assert ref["tags"][0]["name"] == "test-tag"
        assert ref["tags"][0]["score"] == pytest.approx(0.9)


class TestDeleteRef:
    def test_delete_existing(self, db: ContextCommanderDB) -> None:
        ref_id = db.add_ref("snippet", snippet="bye")
        assert db.delete_ref(ref_id) is True
        assert db.get_ref(ref_id) is None

    def test_delete_nonexistent(self, db: ContextCommanderDB) -> None:
        assert db.delete_ref(9999) is False

    def test_cascade_deletes_tags(self, db: ContextCommanderDB) -> None:
        ref_id = db.add_ref("snippet", snippet="cascade")
        tag_id = db.add_tag("will-cascade")
        db.tag_ref(ref_id, tag_id, 0.5)
        db.delete_ref(ref_id)
        # Tag still exists, but link is gone
        ref = db.get_ref(ref_id)
        assert ref is None


class TestTags:
    def test_add_tag_returns_id(self, db: ContextCommanderDB) -> None:
        tag_id = db.add_tag("my-tag")
        assert tag_id > 0

    def test_upsert_returns_same_id(self, db: ContextCommanderDB) -> None:
        id1 = db.add_tag("dupe")
        id2 = db.add_tag("dupe")
        assert id1 == id2

    def test_tag_ref(self, db: ContextCommanderDB) -> None:
        ref_id = db.add_ref("snippet", snippet="x")
        tag_id = db.add_tag("t")
        db.tag_ref(ref_id, tag_id, 0.7)
        ref = db.get_ref(ref_id)
        assert ref is not None
        assert ref["tags"][0]["score"] == pytest.approx(0.7)

    def test_tag_ref_update_score(self, db: ContextCommanderDB) -> None:
        """Re-tagging updates the score (upsert on ref_tags)."""
        ref_id = db.add_ref("snippet", snippet="x")
        tag_id = db.add_tag("t")
        db.tag_ref(ref_id, tag_id, 0.3)
        db.tag_ref(ref_id, tag_id, 0.9)
        ref = db.get_ref(ref_id)
        assert ref["tags"][0]["score"] == pytest.approx(0.9)

    def test_list_tags(self, db: ContextCommanderDB) -> None:
        ref_id = db.add_ref("snippet", snippet="x")
        t1 = db.add_tag("alpha")
        t2 = db.add_tag("beta")
        db.tag_ref(ref_id, t1, 0.5)
        db.tag_ref(ref_id, t2, 0.5)

        tags = db.list_tags()
        names = [t["name"] for t in tags]
        assert "alpha" in names
        assert "beta" in names
        for t in tags:
            if t["name"] in ("alpha", "beta"):
                assert t["ref_count"] == 1


class TestQueryByTags:
    def test_basic_query(self, db: ContextCommanderDB) -> None:
        r1 = db.add_ref("snippet", snippet="relevant")
        r2 = db.add_ref("snippet", snippet="irrelevant")
        t1 = db.add_tag("target")
        t2 = db.add_tag("other")
        db.tag_ref(r1, t1, 0.9)
        db.tag_ref(r2, t2, 0.9)

        results = db.query_by_tags(["target"])
        assert len(results) == 1
        assert results[0]["id"] == r1

    def test_min_score_filter(self, db: ContextCommanderDB) -> None:
        r1 = db.add_ref("snippet", snippet="high")
        r2 = db.add_ref("snippet", snippet="low")
        t = db.add_tag("scored")
        db.tag_ref(r1, t, 0.9)
        db.tag_ref(r2, t, 0.2)

        results = db.query_by_tags(["scored"], min_score=0.5)
        assert len(results) == 1
        assert results[0]["snippet"] == "high"

    def test_excludes_stale_by_default(self, db: ContextCommanderDB) -> None:
        r1 = db.add_ref("snippet", snippet="fresh")
        r2 = db.add_ref("snippet", snippet="stale")
        t = db.add_tag("mixed")
        db.tag_ref(r1, t, 0.8)
        db.tag_ref(r2, t, 0.8)
        db.mark_stale(r2)

        results = db.query_by_tags(["mixed"])
        assert len(results) == 1
        assert results[0]["snippet"] == "fresh"

    def test_include_stale(self, db: ContextCommanderDB) -> None:
        r1 = db.add_ref("snippet", snippet="fresh")
        r2 = db.add_ref("snippet", snippet="stale")
        t = db.add_tag("mixed")
        db.tag_ref(r1, t, 0.8)
        db.tag_ref(r2, t, 0.8)
        db.mark_stale(r2)

        results = db.query_by_tags(["mixed"], include_stale=True)
        assert len(results) == 2

    def test_limit(self, db: ContextCommanderDB) -> None:
        t = db.add_tag("bulk")
        for i in range(20):
            r = db.add_ref("snippet", snippet=f"item-{i}")
            db.tag_ref(r, t, 0.5)

        results = db.query_by_tags(["bulk"], limit=5)
        assert len(results) == 5

    def test_empty_tags_returns_empty(self, db: ContextCommanderDB) -> None:
        assert db.query_by_tags([]) == []

    def test_multi_tag_query(self, db: ContextCommanderDB) -> None:
        r1 = db.add_ref("snippet", snippet="a")
        r2 = db.add_ref("snippet", snippet="b")
        t1 = db.add_tag("tag-a")
        t2 = db.add_tag("tag-b")
        db.tag_ref(r1, t1, 0.8)
        db.tag_ref(r2, t2, 0.8)

        results = db.query_by_tags(["tag-a", "tag-b"])
        assert len(results) == 2

    def test_ordered_by_score(self, db: ContextCommanderDB) -> None:
        r1 = db.add_ref("snippet", snippet="low")
        r2 = db.add_ref("snippet", snippet="high")
        t = db.add_tag("ordered")
        db.tag_ref(r1, t, 0.3)
        db.tag_ref(r2, t, 0.9)

        results = db.query_by_tags(["ordered"])
        assert results[0]["snippet"] == "high"
        assert results[1]["snippet"] == "low"


class TestStaleness:
    def test_mark_stale(self, db: ContextCommanderDB) -> None:
        ref_id = db.add_ref("file", location="/tmp/x")
        db.mark_stale(ref_id)
        ref = db.get_ref(ref_id)
        assert ref["stale"] == 1

    def test_mark_fresh(self, db: ContextCommanderDB) -> None:
        ref_id = db.add_ref("file", location="/tmp/x")
        db.mark_stale(ref_id)
        db.mark_fresh(ref_id, "new-fp")
        ref = db.get_ref(ref_id)
        assert ref["stale"] == 0
        assert ref["fingerprint"] == "new-fp"
        assert ref["last_validated"] is not None

    def test_update_fingerprint(self, db: ContextCommanderDB) -> None:
        ref_id = db.add_ref("file", location="/tmp/x", fingerprint="old")
        db.update_fingerprint(ref_id, "new")
        ref = db.get_ref(ref_id)
        assert ref["fingerprint"] == "new"


class TestPrune:
    def test_prune_all(self, db: ContextCommanderDB) -> None:
        db.add_ref("snippet", snippet="a")
        db.add_ref("snippet", snippet="b")
        count = db.prune()
        assert count == 2

    def test_prune_stale_only(self, db: ContextCommanderDB) -> None:
        r1 = db.add_ref("snippet", snippet="fresh")
        r2 = db.add_ref("snippet", snippet="stale")
        db.mark_stale(r2)

        count = db.prune(stale_only=True)
        assert count == 1
        assert db.get_ref(r1) is not None
        assert db.get_ref(r2) is None

    def test_prune_older_than(self, db: ContextCommanderDB) -> None:
        # Insert a ref and manually backdate it
        ref_id = db.add_ref("snippet", snippet="old")
        db._conn.execute(
            "UPDATE refs SET created_at = datetime('now', '-60 days') WHERE id = ?",
            (ref_id,),
        )
        db._conn.commit()
        r_fresh = db.add_ref("snippet", snippet="new")

        count = db.prune(older_than_days=30)
        assert count == 1
        assert db.get_ref(ref_id) is None
        assert db.get_ref(r_fresh) is not None


class TestOrigins:
    def test_add_origin(self, db: ContextCommanderDB) -> None:
        ref_id = db.add_ref("snippet", snippet="x")
        origin_id = db.add_origin(ref_id, session_id="sess-1", reason="test")
        assert origin_id > 0


class TestAllFileRefs:
    def test_returns_only_file_type(self, db: ContextCommanderDB) -> None:
        db.add_ref("file", location="/a")
        db.add_ref("snippet", snippet="b")
        db.add_ref("web", location="https://c")
        refs = db.all_file_refs()
        assert len(refs) == 1
        assert refs[0]["type"] == "file"


# ===========================================================================
# CLI tests (via subprocess)
# ===========================================================================


def _run_cc(*args: str, db_path: str | None = None) -> subprocess.CompletedProcess:
    """Run cc.py with the given args and return the result."""
    cmd = [sys.executable, str(CC_PY)]
    if db_path:
        cmd += ["--db", db_path]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


class TestCLIIndex:
    def test_index_snippet(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "cli.db")
        result = _run_cc(
            "index", "--type", "snippet", "--snippet", "test content", "--tag", "test",
            db_path=db_path,
        )
        assert result.returncode == 0
        assert "Indexed ref #1" in result.stdout

    def test_index_file_with_range(self, tmp_path: Path, sample_file: Path) -> None:
        db_path = str(tmp_path / "cli.db")
        result = _run_cc(
            "index", "--type", "file", "--location", str(sample_file),
            "--range", "1-3", "--tag", "sample", "--score", "0.9",
            db_path=db_path,
        )
        assert result.returncode == 0
        assert "Indexed ref #1" in result.stdout

    def test_index_multiple_tags(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "cli.db")
        result = _run_cc(
            "index", "--type", "snippet", "--snippet", "multi",
            "--tag", "alpha,beta,gamma",
            db_path=db_path,
        )
        assert result.returncode == 0

        # Verify all tags exist
        result2 = _run_cc("tags", db_path=db_path)
        assert "alpha" in result2.stdout
        assert "beta" in result2.stdout
        assert "gamma" in result2.stdout


class TestCLIQuery:
    def test_query_returns_results(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "cli.db")
        _run_cc(
            "index", "--type", "snippet", "--snippet", "findme", "--tag", "search",
            db_path=db_path,
        )
        result = _run_cc("query", "--tags", "search", db_path=db_path)
        assert result.returncode == 0
        assert "findme" not in result.stdout  # summary doesn't show snippet
        assert "#" in result.stdout

    def test_query_no_results(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "cli.db")
        # init the db first
        _run_cc(
            "index", "--type", "snippet", "--snippet", "x", "--tag", "other",
            db_path=db_path,
        )
        result = _run_cc("query", "--tags", "nonexistent", db_path=db_path)
        assert result.returncode == 0
        assert "No matching" in result.stdout


class TestCLIShow:
    def test_show_existing(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "cli.db")
        _run_cc(
            "index", "--type", "snippet", "--snippet", "detail", "--tag", "show-test",
            db_path=db_path,
        )
        result = _run_cc("show", "1", db_path=db_path)
        assert result.returncode == 0
        assert "Reference #1" in result.stdout
        assert "snippet" in result.stdout
        assert "show-test" in result.stdout

    def test_show_nonexistent(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "cli.db")
        # init db
        _run_cc(
            "index", "--type", "snippet", "--snippet", "x", "--tag", "y",
            db_path=db_path,
        )
        result = _run_cc("show", "999", db_path=db_path)
        assert result.returncode != 0
        assert "not found" in result.stderr


class TestCLITags:
    def test_tags_list(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "cli.db")
        _run_cc(
            "index", "--type", "snippet", "--snippet", "a", "--tag", "aaa",
            db_path=db_path,
        )
        _run_cc(
            "index", "--type", "snippet", "--snippet", "b", "--tag", "bbb",
            db_path=db_path,
        )
        result = _run_cc("tags", db_path=db_path)
        assert result.returncode == 0
        assert "aaa" in result.stdout
        assert "bbb" in result.stdout
        assert "1 refs" in result.stdout


class TestCLIValidate:
    def test_validate_fresh_file(self, tmp_path: Path, sample_file: Path) -> None:
        db_path = str(tmp_path / "cli.db")
        _run_cc(
            "index", "--type", "file", "--location", str(sample_file),
            "--range", "1-3", "--tag", "validate-test",
            db_path=db_path,
        )
        result = _run_cc("validate", db_path=db_path)
        assert result.returncode == 0
        assert "1 fresh" in result.stdout
        assert "0 stale" in result.stdout

    def test_validate_detects_modification(self, tmp_path: Path, sample_file: Path) -> None:
        db_path = str(tmp_path / "cli.db")
        _run_cc(
            "index", "--type", "file", "--location", str(sample_file),
            "--range", "1-3", "--tag", "validate-test",
            db_path=db_path,
        )
        # Modify the file
        sample_file.write_text("CHANGED\nline2\nline3\nline4\nline5\n", encoding="utf-8")

        result = _run_cc("validate", db_path=db_path)
        assert result.returncode == 0
        assert "1 stale" in result.stdout

    def test_validate_detects_missing_file(self, tmp_path: Path, sample_file: Path) -> None:
        db_path = str(tmp_path / "cli.db")
        _run_cc(
            "index", "--type", "file", "--location", str(sample_file),
            "--tag", "validate-test",
            db_path=db_path,
        )
        # Delete the file
        sample_file.unlink()

        result = _run_cc("validate", db_path=db_path)
        assert result.returncode == 0
        assert "1 stale" in result.stdout
        assert "file missing" in result.stdout


class TestCLIPrune:
    def test_prune_stale(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "cli.db")
        _run_cc(
            "index", "--type", "snippet", "--snippet", "a", "--tag", "x",
            db_path=db_path,
        )
        # Make it stale by modifying db directly (validated separately)
        d = ContextCommanderDB(db_path=db_path)
        d.init_db()
        d.mark_stale(1)
        d.close()

        result = _run_cc("prune", "--stale", db_path=db_path)
        assert result.returncode == 0
        assert "Pruned 1" in result.stdout


class TestCLIEdgeCases:
    def test_invalid_range_format(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "cli.db")
        result = _run_cc(
            "index", "--type", "file", "--location", "/tmp/x",
            "--range", "bad", "--tag", "t",
            db_path=db_path,
        )
        assert result.returncode != 0

    def test_index_missing_file_still_succeeds(self, tmp_path: Path) -> None:
        """Indexing a nonexistent file should work (with a warning)."""
        db_path = str(tmp_path / "cli.db")
        result = _run_cc(
            "index", "--type", "file", "--location", "/tmp/nonexistent_file_12345.py",
            "--tag", "missing",
            db_path=db_path,
        )
        assert result.returncode == 0
        assert "Warning" in result.stderr or "Indexed" in result.stdout


# ===========================================================================
# Integration: full staleness workflow
# ===========================================================================


class TestStalenessWorkflow:
    """End-to-end: create file → index → modify → validate → prune."""

    def test_full_workflow(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "workflow.db")
        test_file = tmp_path / "code.py"
        test_file.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

        # 1. Index the file
        result = _run_cc(
            "index", "--type", "file", "--location", str(test_file),
            "--range", "1-2", "--tag", "functions", "--score", "0.9",
            db_path=db_path,
        )
        assert result.returncode == 0

        # 2. Validate — should be fresh
        result = _run_cc("validate", db_path=db_path)
        assert "1 fresh" in result.stdout

        # 3. Modify the file
        test_file.write_text("def hello():\n    return 'universe'\n", encoding="utf-8")

        # 4. Validate — should be stale now
        result = _run_cc("validate", db_path=db_path)
        assert "1 stale" in result.stdout

        # 5. Query should exclude stale by default
        result = _run_cc("query", "--tags", "functions", db_path=db_path)
        assert "No matching" in result.stdout

        # 6. Query with --include-stale should find it
        result = _run_cc("query", "--tags", "functions", "--include-stale", db_path=db_path)
        assert "#" in result.stdout

        # 7. Prune stale
        result = _run_cc("prune", "--stale", db_path=db_path)
        assert "Pruned 1" in result.stdout

        # 8. Query again — nothing left
        result = _run_cc("query", "--tags", "functions", "--include-stale", db_path=db_path)
        assert "No matching" in result.stdout


# ===========================================================================
# Hierarchical tag tests
# ===========================================================================


class TestHierarchicalQueryDB:
    """Test prefix-based hierarchical tag matching at the DB layer."""

    def _seed_hierarchy(self, db: ContextCommanderDB) -> dict[str, int]:
        """Create refs with a tag hierarchy and return tag->ref_id mapping."""
        ids = {}
        for tag, snippet in [
            ("ai", "Top-level AI concept"),
            ("ai/anthropic", "Anthropic-specific context"),
            ("ai/anthropic/claude", "Claude model details"),
            ("ai/openai", "OpenAI-specific context"),
            ("ai/openai/codex", "Codex model details"),
            ("game", "Top-level game concept"),
            ("game/systems/loot", "Loot system details"),
        ]:
            ref_id = db.add_ref("snippet", snippet=snippet)
            tag_id = db.add_tag(tag)
            db.tag_ref(ref_id, tag_id, score=0.8)
            ids[tag] = ref_id
        return ids

    def test_prefix_matches_all_children(self, db: ContextCommanderDB) -> None:
        """Querying 'ai' should return ai, ai/anthropic, ai/anthropic/claude, etc."""
        self._seed_hierarchy(db)
        results = db.query_by_tags(["ai"], limit=20)
        assert len(results) == 5  # ai + ai/anthropic + ai/anthropic/claude + ai/openai + ai/openai/codex

    def test_prefix_matches_subtree(self, db: ContextCommanderDB) -> None:
        """Querying 'ai/anthropic' should return ai/anthropic + ai/anthropic/claude."""
        self._seed_hierarchy(db)
        results = db.query_by_tags(["ai/anthropic"], limit=20)
        assert len(results) == 2

    def test_prefix_matches_leaf(self, db: ContextCommanderDB) -> None:
        """Querying a leaf tag should return only that ref."""
        self._seed_hierarchy(db)
        results = db.query_by_tags(["ai/anthropic/claude"], limit=20)
        assert len(results) == 1
        assert results[0]["snippet"] == "Claude model details"

    def test_exact_mode_no_children(self, db: ContextCommanderDB) -> None:
        """With exact=True, 'ai' should match ONLY 'ai', not children."""
        self._seed_hierarchy(db)
        results = db.query_by_tags(["ai"], exact=True, limit=20)
        assert len(results) == 1
        assert results[0]["snippet"] == "Top-level AI concept"

    def test_exact_mode_leaf(self, db: ContextCommanderDB) -> None:
        """Exact match on a leaf should still work."""
        self._seed_hierarchy(db)
        results = db.query_by_tags(["ai/anthropic/claude"], exact=True, limit=20)
        assert len(results) == 1

    def test_no_false_prefix_match(self, db: ContextCommanderDB) -> None:
        """'game' should NOT match 'ai/...' and vice versa."""
        self._seed_hierarchy(db)
        results = db.query_by_tags(["game"], limit=20)
        tags_found = set()
        for r in results:
            for t in r["tags"]:
                tags_found.add(t["name"])
        for tag in tags_found:
            assert tag.startswith("game"), f"Unexpected tag {tag} in game query"

    def test_multi_prefix_query(self, db: ContextCommanderDB) -> None:
        """Querying multiple prefixes returns the union."""
        self._seed_hierarchy(db)
        results = db.query_by_tags(["ai/anthropic", "game"], limit=20)
        assert len(results) == 4  # ai/anthropic + ai/anthropic/claude + game + game/systems/loot

    def test_no_partial_name_match(self, db: ContextCommanderDB) -> None:
        """'a' should NOT match 'ai' — prefix must be a full path segment."""
        self._seed_hierarchy(db)
        results = db.query_by_tags(["a"], limit=20)
        assert len(results) == 0  # 'a' != 'ai', and 'a/' doesn't prefix 'ai/'


class TestHierarchicalQueryCLI:
    """Test hierarchy via the CLI."""

    def test_cli_prefix_query(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "cli.db")
        # Index three levels
        _run_cc("index", "--type", "snippet", "--snippet", "top", "--tag", "concept/ai", db_path=db_path)
        _run_cc("index", "--type", "snippet", "--snippet", "mid", "--tag", "concept/ai/llm", db_path=db_path)
        _run_cc("index", "--type", "snippet", "--snippet", "leaf", "--tag", "concept/ai/llm/claude", db_path=db_path)

        # Broad query should find all 3
        result = _run_cc("query", "--tags", "concept/ai", db_path=db_path)
        assert result.stdout.count("#") == 3

    def test_cli_exact_flag(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "cli.db")
        _run_cc("index", "--type", "snippet", "--snippet", "top", "--tag", "concept/ai", db_path=db_path)
        _run_cc("index", "--type", "snippet", "--snippet", "child", "--tag", "concept/ai/llm", db_path=db_path)

        # Exact should find only 1
        result = _run_cc("query", "--tags", "concept/ai", "--exact", db_path=db_path)
        assert result.stdout.count("#") == 1
