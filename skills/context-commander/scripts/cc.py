"""Context Commander — CLI tool.

Provides commands: index, query, validate, prune, show, tags.
No external dependencies beyond the Python standard library.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path

# Ensure the scripts directory is on sys.path so cc_db can be imported
# regardless of how the script is invoked.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from cc_db import ContextCommanderDB  # noqa: E402


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _fingerprint_file(location: str, range_start: int | None, range_end: int | None) -> str | None:
    """Compute a SHA-256 fingerprint for a file (or a line range within it).

    Returns a base64-encoded hash string, or None if the file cannot be read.
    """
    path = Path(location)
    if not path.is_file():
        return None

    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeDecodeError):
        return None

    if range_start is not None and range_end is not None:
        # Line numbers are 1-based inclusive
        start = max(range_start - 1, 0)
        end = range_end
        lines = lines[start:end]

    content = "".join(lines)
    digest = hashlib.sha256(content.encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def _parse_range(range_str: str | None) -> tuple[int | None, int | None]:
    """Parse a 'START-END' range string into (start, end)."""
    if not range_str:
        return None, None
    parts = range_str.split("-", 1)
    if len(parts) != 2:
        print(f"Error: Invalid range format '{range_str}'. Expected START-END (e.g. 8-50).", file=sys.stderr)
        sys.exit(1)
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        print(f"Error: Range values must be integers, got '{range_str}'.", file=sys.stderr)
        sys.exit(1)


def _get_db(args: argparse.Namespace) -> ContextCommanderDB:
    """Create and initialise a DB connection from CLI args."""
    db = ContextCommanderDB(db_path=args.db)
    db.init_db()
    return db


def _serialize_ref(ref: dict) -> dict:
    """Normalize a ref dict for JSON serialization."""
    return {
        "id": ref.get("id"),
        "type": ref.get("type"),
        "location": ref.get("location"),
        "range_start": ref.get("range_start"),
        "range_end": ref.get("range_end"),
        "fingerprint": ref.get("fingerprint"),
        "snippet": ref.get("snippet"),
        "stale": bool(ref.get("stale")),
        "created_at": ref.get("created_at"),
        "last_validated": ref.get("last_validated"),
        "tags": ref.get("tags", []),
    }


# ------------------------------------------------------------------
# Commands
# ------------------------------------------------------------------


def cmd_index(args: argparse.Namespace) -> None:
    """Index a new reference."""
    db = _get_db(args)
    try:
        range_start, range_end = _parse_range(args.range)

        fingerprint = args.fingerprint
        if fingerprint is None and args.type == "file" and args.location:
            fingerprint = _fingerprint_file(args.location, range_start, range_end)
            if fingerprint is None:
                print(f"Warning: Could not fingerprint '{args.location}'. File may not exist.", file=sys.stderr)

        ref_id = db.add_ref(
            type=args.type,
            location=args.location,
            range_start=range_start,
            range_end=range_end,
            fingerprint=fingerprint,
            snippet=args.snippet,
        )

        # Handle tags (comma-separated)
        if args.tag:
            for tag_name in args.tag.split(","):
                tag_name = tag_name.strip()
                if not tag_name:
                    continue
                tag_id = db.add_tag(tag_name)
                db.tag_ref(ref_id, tag_id, score=args.score)

        if args.json:
            ref = db.get_ref(ref_id)
            print(json.dumps({"ok": True, "ref": _serialize_ref(ref) if ref else {"id": ref_id}}))
        else:
            print(f"Indexed ref #{ref_id} [{args.type}]", end="")
            if args.location:
                print(f" -> {args.location}", end="")
            if range_start is not None:
                print(f" (lines {range_start}-{range_end})", end="")
            print()
    finally:
        db.close()


def cmd_query(args: argparse.Namespace) -> None:
    """Query the index by tags."""
    db = _get_db(args)
    try:
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        if not tags:
            if args.json:
                print(json.dumps({"ok": False, "error": "No tags provided."}))
                return
            print("Error: No tags provided.", file=sys.stderr)
            sys.exit(1)

        results = db.query_by_tags(
            tags=tags,
            min_score=args.min_score,
            limit=args.limit,
            include_stale=args.include_stale,
            exact=args.exact,
        )

        if args.json:
            print(json.dumps({"ok": True, "refs": [_serialize_ref(r) for r in results]}))
        else:
            if not results:
                print("No matching references found.")
                return
            for ref in results:
                _print_ref_summary(ref)
    finally:
        db.close()


def cmd_validate(args: argparse.Namespace) -> None:
    """Re-hash all file refs and flag stale ones."""
    db = _get_db(args)
    try:
        file_refs = db.all_file_refs()
        if not file_refs:
            if args.json:
                print(json.dumps({"ok": True, "total": 0, "fresh": 0, "stale": 0, "details": []}))
            else:
                print("No file references to validate.")
            return

        stale_count = 0
        fresh_count = 0
        details = []

        for ref in file_refs:
            current_fp = _fingerprint_file(ref["location"], ref["range_start"], ref["range_end"])

            if current_fp is None:
                # File missing or unreadable
                db.mark_stale(ref["id"])
                stale_count += 1
                details.append({"id": ref["id"], "status": "stale", "reason": "file missing", "location": ref["location"]})
                if not args.json:
                    print(f"  STALE  #{ref['id']} — file missing: {ref['location']}")
            elif current_fp != ref["fingerprint"]:
                db.mark_stale(ref["id"])
                stale_count += 1
                details.append({"id": ref["id"], "status": "stale", "reason": "content changed", "location": ref["location"]})
                if not args.json:
                    print(f"  STALE  #{ref['id']} — content changed: {ref['location']}")
            else:
                db.mark_fresh(ref["id"], current_fp)
                fresh_count += 1
                details.append({"id": ref["id"], "status": "fresh", "location": ref["location"]})

        if args.json:
            print(json.dumps({"ok": True, "total": len(file_refs), "fresh": fresh_count, "stale": stale_count, "details": details}))
        else:
            print(f"\nValidated {len(file_refs)} file refs: {fresh_count} fresh, {stale_count} stale.")
    finally:
        db.close()


def cmd_prune(args: argparse.Namespace) -> None:
    """Delete stale or old references."""
    db = _get_db(args)
    try:
        count = db.prune(
            stale_only=args.stale,
            older_than_days=args.older_than,
        )
        if args.json:
            print(json.dumps({"ok": True, "pruned": count}))
        else:
            print(f"Pruned {count} reference(s).")
    finally:
        db.close()


def cmd_show(args: argparse.Namespace) -> None:
    """Show full details for a single reference."""
    db = _get_db(args)
    try:
        ref = db.get_ref(args.ref_id)
        if ref is None:
            if args.json:
                print(json.dumps({"ok": False, "error": f"Reference #{args.ref_id} not found."}))
                return
            print(f"Error: Reference #{args.ref_id} not found.", file=sys.stderr)
            sys.exit(1)
        if args.json:
            print(json.dumps({"ok": True, "ref": _serialize_ref(ref)}))
        else:
            _print_ref_detail(ref)
    finally:
        db.close()


def cmd_tags(args: argparse.Namespace) -> None:
    """List all tags with ref counts."""
    db = _get_db(args)
    try:
        tags = db.list_tags()
        if args.json:
            print(json.dumps({"ok": True, "tags": tags}))
        else:
            if not tags:
                print("No tags found.")
                return
            max_name = max(len(t["name"]) for t in tags)
            for t in tags:
                print(f"  {t['name']:<{max_name}}  ({t['ref_count']} refs)")
    finally:
        db.close()


def cmd_delete(args: argparse.Namespace) -> None:
    """Delete a single reference by ID."""
    db = _get_db(args)
    try:
        deleted = db.delete_ref(args.ref_id)
        if args.json:
            print(json.dumps({"ok": True, "deleted": deleted, "ref_id": args.ref_id}))
        else:
            if deleted:
                print(f"Deleted ref #{args.ref_id}.")
            else:
                print(f"Reference #{args.ref_id} not found.")
    finally:
        db.close()


def cmd_stats(args: argparse.Namespace) -> None:
    """Show aggregate statistics about the reference index."""
    db = _get_db(args)
    try:
        s = db.stats()
        if args.json:
            print(json.dumps({"ok": True, "stats": s}))
        else:
            print(f"Context Commander Stats")
            print(f"{'=' * 40}")
            print(f"  Total refs:       {s['total_refs']}")
            for rtype, count in s.get("refs_by_type", {}).items():
                print(f"    {rtype}:          {count}")
            print(f"  Total tags:       {s['total_tags']}")
            print(f"  Tag assignments:  {s['total_tag_assignments']}")
            print(f"  Orphan tags:      {s['orphan_tags']}")
            print(f"  Fresh:            {s['fresh_count']}")
            print(f"  Stale:            {s['stale_count']}")
            print()
            print(f"  Avg score:        {s['avg_score']}")
            print(f"  Score range:      {s['min_score']} — {s['max_score']}")
            dist = s.get("score_distribution", {})
            if dist:
                print(f"  Score distribution:")
                for label, count in dist.items():
                    print(f"    {label:<10}  {count}")
            print()
            print(f"  Oldest ref:       {s['oldest_ref']}")
            print(f"  Newest ref:       {s['newest_ref']}")
            activity = s.get("recent_activity", [])
            if activity:
                print(f"  Recent activity (7 days):")
                for a in activity:
                    print(f"    {a['day']}: {a['count']} ref(s)")
            top = s.get("top_tags", [])
            if top:
                print(f"  Top tags:")
                for t in top:
                    print(f"    {t['name']} ({t['ref_count']})")
            if s.get("db_size_bytes") is not None:
                kb = s["db_size_bytes"] / 1024
                print(f"  DB size:          {kb:.1f} KB")
    finally:
        db.close()


# ------------------------------------------------------------------
# Display helpers
# ------------------------------------------------------------------


def _print_ref_summary(ref: dict) -> None:
    """Print a one-line summary of a reference."""
    stale_marker = " [STALE]" if ref.get("stale") else ""
    tag_str = ", ".join(f"{t['name']}({t['score']:.1f})" for t in ref.get("tags", []))
    loc = ref.get("location") or "(snippet)"
    range_str = ""
    if ref.get("range_start") is not None:
        range_str = f" L{ref['range_start']}-{ref['range_end']}"

    print(f"  #{ref['id']:>4} [{ref['type']}] {loc}{range_str}{stale_marker}  tags: {tag_str}")


def _print_ref_detail(ref: dict) -> None:
    """Print full details of a reference."""
    print(f"Reference #{ref['id']}")
    print(f"  Type:       {ref['type']}")
    print(f"  Location:   {ref.get('location') or '(none)'}")
    if ref.get("range_start") is not None:
        print(f"  Range:      {ref['range_start']}-{ref['range_end']}")
    if ref.get("fingerprint"):
        print(f"  Fingerprint:{ref['fingerprint']}")
    if ref.get("snippet"):
        print(f"  Snippet:    {ref['snippet'][:200]}{'...' if len(ref.get('snippet', '')) > 200 else ''}")
    print(f"  Stale:      {'Yes' if ref.get('stale') else 'No'}")
    print(f"  Created:    {ref.get('created_at')}")
    print(f"  Validated:  {ref.get('last_validated') or 'never'}")
    if ref.get("tags"):
        print(f"  Tags:")
        for t in ref["tags"]:
            print(f"    - {t['name']} (score: {t['score']:.2f})")
    else:
        print(f"  Tags:       (none)")


# ------------------------------------------------------------------
# Argument parser
# ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="cc",
        description="Context Commander — retrieval-based working memory for AI agents.",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Path to the SQLite database (default: db/context-commander.db)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output results as JSON instead of human-readable text",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- index ---
    p_index = sub.add_parser("index", help="Index a new reference")
    p_index.add_argument("--tag", type=str, help="Comma-separated tag(s)")
    p_index.add_argument("--type", type=str, required=True, choices=["file", "web", "snippet"])
    p_index.add_argument("--location", type=str, default=None)
    p_index.add_argument("--range", type=str, default=None, help="Line range as START-END")
    p_index.add_argument("--snippet", type=str, default=None)
    p_index.add_argument("--fingerprint", type=str, default=None)
    p_index.add_argument("--score", type=float, default=0.8)

    # --- query ---
    p_query = sub.add_parser("query", help="Query the index by tags")
    p_query.add_argument("--tags", type=str, required=True, help="Comma-separated tags")
    p_query.add_argument("--min-score", type=float, default=0.0)
    p_query.add_argument("--limit", type=int, default=10)
    p_query.add_argument("--include-stale", action="store_true")
    p_query.add_argument("--exact", action="store_true", help="Match exact tag names only (no hierarchy expansion)")

    # --- validate ---
    sub.add_parser("validate", help="Re-hash file refs and flag stale ones")

    # --- prune ---
    p_prune = sub.add_parser("prune", help="Delete stale or old references")
    p_prune.add_argument("--stale", action="store_true", help="Only prune stale refs")
    p_prune.add_argument("--older-than", type=int, default=None, metavar="DAYS", help="Only prune refs older than N days")

    # --- show ---
    p_show = sub.add_parser("show", help="Show full details for a reference")
    p_show.add_argument("ref_id", type=int, help="Reference ID")

    # --- tags ---
    sub.add_parser("tags", help="List all tags with ref counts")

    # --- delete ---
    p_delete = sub.add_parser("delete", help="Delete a single reference by ID")
    p_delete.add_argument("ref_id", type=int, help="Reference ID to delete")

    # --- stats ---
    sub.add_parser("stats", help="Show aggregate statistics about the index")

    return parser


def main() -> None:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "index": cmd_index,
        "query": cmd_query,
        "validate": cmd_validate,
        "prune": cmd_prune,
        "show": cmd_show,
        "tags": cmd_tags,
        "delete": cmd_delete,
        "stats": cmd_stats,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
