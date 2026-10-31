#!/usr/bin/env python3
"""
scripts/reset_vector_db.py — Fix embedding dimension mismatch in LocalMind's vector DB.

WHY THIS EXISTS
───────────────
sqlite-vec virtual tables bake the embedding dimension into the schema at creation time.
If the active Ollama embed model was swapped (or the model was re-pulled and now returns
a different dim), every subsequent embed call produces a vector whose length mismatches
the frozen schema — causing silent write failures or cryptic errors.

WHAT THIS SCRIPT DOES
──────────────────────
1. Probe the currently-configured embed model to get its actual dim.
2. Read the dim recorded in vector_meta AND the dim frozen in the vec0 table's
   DDL — the table is what sqlite-vec enforces, so a stale meta row must not
   mask a real mismatch.
3. If the vec0 table already matches the embedder: exit cleanly (a stale meta
   row alone is repaired by VectorStore at startup).
4. Otherwise:
   a. Export all stored facts (text only — embeddings are recomputed fresh).
   b. Drop vector_embeddings, embed_cache, and the dim row in vector_meta.
   c. Re-embed all facts at the correct dim and re-insert them.

USAGE
─────
    # Just check — print the mismatch, do nothing:
    python scripts/reset_vector_db.py --probe-only

    # Fix it (asks for confirmation unless --yes):
    python scripts/reset_vector_db.py --yes

    # Point at a non-default DB:
    python scripts/reset_vector_db.py --db ./path/to/localmind.db --yes
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sqlite3
import struct
import sys
from pathlib import Path

# Make the project root importable
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

# Suppress noisy startup logs during the script run
import os
os.environ.setdefault("LOCALMIND_LOG_LEVEL", "WARNING")

from core.config import settings


# ── Helpers ────────────────────────────────────────────────────────────────────

def _probe_dim(base_url: str, embed_model: str) -> int | None:
    """Return the actual embedding dimension from the live Ollama model, or None."""
    try:
        resp = httpx.post(
            f"{base_url.rstrip('/')}/api/embeddings",
            json={"model": embed_model, "prompt": "dim_probe"},
            timeout=15,
        )
        if resp.status_code == 200:
            vec = resp.json().get("embedding")
            if vec:
                return len(vec)
        print(f"  Ollama returned HTTP {resp.status_code} for model '{embed_model}'.")
        print(f"  Is that model pulled?  Run: ollama pull {embed_model}")
    except httpx.ConnectError:
        print(f"  Cannot reach Ollama at {base_url}. Is it running?")
    except Exception as exc:
        print(f"  Probe failed: {exc}")
    return None


def _get_stored_dim(db_path: str) -> int | None:
    """Read the dim recorded in vector_meta, or None if the table/row doesn't exist."""
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT value FROM vector_meta WHERE key = 'dim'"
        ).fetchone()
        conn.close()
        return int(row[0]) if row else None
    except Exception:
        return None


def _get_vec_table_dim(db_path: str) -> int | None:
    """Read the dim frozen into the vec0 table's DDL, or None if it doesn't exist.

    This is the dimension sqlite-vec actually enforces on INSERT — vector_meta
    can say something else (a stale row), and comparing only the meta row is
    how this script once reported "dims match" while every write failed.
    """
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'vector_embeddings'"
        ).fetchone()
        conn.close()
        if not row or not row[0]:
            return None
        match = re.search(r"float\[(\d+)\]", row[0])
        return int(match.group(1)) if match else None
    except Exception:
        return None


def _export_facts(db_path: str) -> list[tuple[str, str, str]]:
    """Return [(id, content, metadata_json), ...] from vector_facts."""
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT id, content, metadata FROM vector_facts ORDER BY rowid"
        ).fetchall()
        conn.close()
        return [(r[0], r[1], r[2]) for r in rows]
    except Exception as exc:
        print(f"  Warning: could not export facts: {exc}")
        return []


def _drop_vector_tables(db_path: str) -> None:
    """Drop the virtual table, embed cache, and stored dim/backend so a fresh
    index can be built at the probed dimension.

    The sqlite-vec extension must be loaded on THIS connection: without its
    module, `DROP TABLE vector_embeddings` fails and the old table survives,
    which made a later `CREATE VIRTUAL TABLE IF NOT EXISTS` silently keep the
    stale dimension. The failure is no longer swallowed for that reason.
    """
    import sqlite_vec

    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("DROP TABLE IF EXISTS vector_embeddings")
    conn.execute("DELETE FROM embed_cache")
    conn.execute("DELETE FROM vector_meta WHERE key IN ('dim', 'embed_backend_id')")
    conn.commit()
    conn.close()


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _embed_sync(base_url: str, embed_model: str, text: str) -> list[float] | None:
    try:
        resp = httpx.post(
            f"{base_url.rstrip('/')}/api/embeddings",
            json={"model": embed_model, "prompt": text},
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json().get("embedding")
    except Exception as exc:
        print(f"  Embed failed: {exc}")
    return None


# ── Main logic ────────────────────────────────────────────────────────────────

def run(db_path: str, probe_only: bool, yes: bool) -> None:
    base_url    = settings.ollama_base_url
    embed_model = settings.ollama_embed_model

    print(f"  DB path    : {db_path}")
    print(f"  Embed model: {embed_model}  (OLLAMA_EMBED_MODEL in .env)")
    print(f"  Ollama URL : {base_url}")
    print()

    stored_dim = _get_stored_dim(db_path)
    table_dim = _get_vec_table_dim(db_path)
    if stored_dim is None and table_dim is None:
        print("  vector_meta has no 'dim' row and no vec0 table — DB is")
        print("  uninitialised or already clean. Nothing to reset.")
        return

    print(f"  vector_meta dim : {stored_dim}")
    print(f"  vec0 table dim  : {table_dim}")
    print(f"  Probing actual dim from Ollama…", end=" ", flush=True)
    actual_dim = _probe_dim(base_url, embed_model)
    if actual_dim is None:
        print()
        print("  Could not determine actual dim. Check Ollama and try again.")
        sys.exit(1)
    print(actual_dim)
    print()

    if table_dim == actual_dim:
        # The index already enforces the right dimension — only the meta row
        # may be stale, and VectorStore repairs that at startup without
        # touching any vectors.
        if stored_dim != actual_dim:
            print(f"  vector_meta dim={stored_dim} is stale, but the vec0 index")
            print(f"  already matches the embedder (dim={actual_dim}); LocalMind")
            print("  corrects the meta row at startup. Nothing to reset.")
        else:
            print("  Dims match — no mismatch detected. Nothing to reset.")
        return

    print(
        f"  MISMATCH: vec0 index={table_dim}  embedder={actual_dim}  "
        f"vector_meta={stored_dim}"
    )
    print()

    if probe_only:
        print("  --probe-only: exiting without making changes.")
        print()
        print("  To fix, run:")
        print("    python scripts/reset_vector_db.py --yes")
        return

    # Export facts before dropping tables
    facts = _export_facts(db_path)
    print(f"  Found {len(facts)} stored facts — will re-embed at dim={actual_dim}.")
    print()

    if not yes:
        print("  This will DROP vector_embeddings and embed_cache and re-embed all facts.")
        confirm = input("  Continue? [y/N] ").strip().lower()
        if confirm not in ("y", "yes"):
            print("  Aborted.")
            return

    print("  Dropping vector tables…", end=" ", flush=True)
    _drop_vector_tables(db_path)
    print("done.")

    if not facts:
        print("  No facts to re-embed. VectorStore will reinitialise on next startup.")
        return

    # Re-embed and re-insert all facts
    import sqlite_vec
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    conn.execute(
        "INSERT OR REPLACE INTO vector_meta(key, value) VALUES ('dim', ?)",
        (str(actual_dim),),
    )
    # Re-embedded vectors come from this Ollama backend: record its identity so
    # restarts know which embedding space the index actually holds.
    from storage.vector import _backend_id

    conn.execute(
        "INSERT OR REPLACE INTO vector_meta(key, value) VALUES ('embed_backend_id', ?)",
        (_backend_id("ollama", base_url, embed_model),),
    )
    conn.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS vector_embeddings
        USING vec0(embedding float[{actual_dim}])
    """)
    created_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'vector_embeddings'"
    ).fetchone()[0]
    if f"float[{actual_dim}]" not in created_sql:
        conn.close()
        print(f"  ERROR: vec0 table was not rebuilt at dim={actual_dim} — aborting.")
        sys.exit(1)
    conn.commit()

    ok = 0
    fail = 0
    for i, (fact_id, content, metadata_json) in enumerate(facts, 1):
        print(f"  [{i:02d}/{len(facts)}] {content[:72]}{'…' if len(content) > 72 else ''}")
        vec = _embed_sync(base_url, embed_model, content)
        if vec is None:
            print("         ↳ embed failed — skipped")
            fail += 1
            continue
        blob = _pack(vec)
        conn.execute(
            "INSERT OR REPLACE INTO vector_facts(id, content, metadata) VALUES (?, ?, ?)",
            (fact_id, content, metadata_json),
        )
        rowid = conn.execute(
            "SELECT rowid FROM vector_facts WHERE id = ?", (fact_id,)
        ).fetchone()[0]
        conn.execute("DELETE FROM vector_embeddings WHERE rowid = ?", (rowid,))
        conn.execute(
            "INSERT INTO vector_embeddings(rowid, embedding) VALUES (?, ?)",
            (rowid, blob),
        )
        ok += 1

    conn.commit()
    conn.close()

    print()
    print(f"  Reset complete. Re-embedded {ok} facts ({fail} failed).")
    print()
    print("  Next steps:")
    print("    python scripts/seed_memory.py --yes")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix vector DB embedding dimension mismatch."
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Path to localmind.db (default: LOCALMIND_DB_PATH from .env)",
    )
    parser.add_argument(
        "--probe-only",
        action="store_true",
        help="Print the mismatch info and exit — make no changes.",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt.",
    )
    args = parser.parse_args()

    db_path = args.db or settings.localmind_db_path or "./localmind.db"

    if not Path(db_path).exists():
        print(f"  DB not found at {db_path}.")
        print("  Run LocalMind once to initialise it, then re-run this script.")
        sys.exit(1)

    run(db_path=db_path, probe_only=args.probe_only, yes=args.yes)


if __name__ == "__main__":
    main()
