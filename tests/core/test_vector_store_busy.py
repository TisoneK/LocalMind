"""Session 366 — VectorStore WAL busy race (B-2026-08-23-14).

Root cause: `_persist` ran a deferred `BEGIN`, then a dedup SELECT (which
takes a WAL read snapshot), then INSERTs. If any other connection commits
between the read and the first write, the deferred transaction's upgrade to
a write lock fails INSTANTLY with `database is locked` (SQLITE_BUSY) — the
busy timeout does not apply to snapshot upgrades. Because the memory store
shares the app's SQLite file (sessions, embed cache, todos all write to it),
this surfaced as intermittent 503s on POST /api/memory and silent drops of
the agent's own fact writes.

Fix: `BEGIN IMMEDIATE` in `_persist` (and the embed-cache batch flush) so
the write lock is acquired up front; WAL still allows concurrent readers.

The first test reproduces the race deterministically at the SQL level:
BEGIN → read snapshot → (other connection commits) → write. It proves plain
BEGIN dies with SQLITE_BUSY while BEGIN IMMEDIATE survives — the exact
mechanism the fix changed. The second test exercises store() end to end
under a concurrent writer.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time

import pytest

os.environ.setdefault("LOCALMIND_HOME", ".")

from core.config import settings


def _make_store(db_path: str):
    from storage.vector import VectorStore

    return VectorStore(db_path=str(db_path))


class TestUpdateContent:
    def test_update_content_rembeds_and_preserves_metadata(self, tmp_path, monkeypatch):
        """Editing a fact replaces its content, migrates the row to the new
        content-derived id, and keeps the original source/timestamp metadata."""
        monkeypatch.setattr(settings, "localmind_db_path", str(tmp_path / "localmind.db"))
        monkeypatch.setattr(settings, "ollama_embed_model", "test-embed")
        store = _make_store(str(tmp_path / "localmind.db"))

        import storage.vector as vector_mod

        async def _fake_embed(text):
            # Distinct embeddings per text so ids differ and recall works.
            seed = sum(ord(c) for c in text)
            return vector_mod._normalise([0.1 * ((seed + i) % 7 + 1) for i in range(8)])

        monkeypatch.setattr(store, "_embed", _fake_embed)

        import asyncio

        assert asyncio.run(store.store("User likes dark mode", "manual", source="user")) is True
        facts = asyncio.run(store.list_all_with_metadata())
        assert len(facts) == 1
        old_id = facts[0]["id"]
        assert facts[0]["source"] == "user"
        old_ts = facts[0].get("timestamp")

        new_id = asyncio.run(store.update_content(old_id, "User likes dark mode with warm accents"))
        assert new_id and new_id != old_id

        facts = asyncio.run(store.list_all_with_metadata())
        assert len(facts) == 1
        assert facts[0]["id"] == new_id
        assert facts[0]["fact"] == "User likes dark mode with warm accents"
        assert facts[0]["source"] == "user"
        assert facts[0].get("timestamp") == old_ts, "edit must preserve the original timestamp"

    def test_update_content_missing_fact_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "localmind_db_path", str(tmp_path / "localmind.db"))
        monkeypatch.setattr(settings, "ollama_embed_model", "test-embed")
        store = _make_store(str(tmp_path / "localmind.db"))

        import asyncio

        assert asyncio.run(store.update_content("nope", "anything")) is None


class TestPersistBusyRace:
    def test_plain_begin_fails_snapshot_upgrade(self, tmp_path):
        """Documents the bug: a deferred BEGIN that reads then writes dies
        instantly when another connection commits in between."""
        db = str(tmp_path / "race.db")
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("CREATE TABLE t (k TEXT PRIMARY KEY, v BLOB)")
        conn.commit()

        conn.execute("BEGIN")  # deferred — the old _persist behavior
        conn.execute("SELECT COUNT(*) FROM t").fetchone()  # read snapshot

        # Concurrent writer commits between our read and our write.
        other = sqlite3.connect(db)
        other.execute("PRAGMA journal_mode = WAL")
        other.execute("BEGIN IMMEDIATE")
        other.execute("INSERT OR IGNORE INTO t(k, v) VALUES ('other', x'00')")
        other.commit()
        other.close()

        with pytest.raises(sqlite3.OperationalError) as exc:
            conn.execute("INSERT OR IGNORE INTO t(k, v) VALUES ('mine', x'00')")
        assert "locked" in str(exc.value)
        conn.close()

    def test_immediate_begin_survives_snapshot_upgrade(self, tmp_path):
        """The fix: taking the write lock up front makes the same interleaving
        succeed — the concurrent writer simply waits for our commit and then
        writes, instead of breaking our read→write transaction."""
        db = str(tmp_path / "race.db")
        conn = sqlite3.connect(db, timeout=5.0)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("CREATE TABLE t (k TEXT PRIMARY KEY, v BLOB)")
        conn.commit()

        conn.execute("BEGIN IMMEDIATE")  # the fixed _persist behavior
        conn.execute("SELECT COUNT(*) FROM t").fetchone()  # read

        # A concurrent writer starts while we hold the write lock. Under the
        # old code our later INSERT would fail; under the fix it waits for our
        # commit and succeeds — no error anywhere.
        results = {}

        def other_writer():
            try:
                o = sqlite3.connect(db, timeout=10.0)
                o.execute("PRAGMA journal_mode = WAL")
                o.execute("BEGIN IMMEDIATE")
                o.execute("INSERT OR IGNORE INTO t(k, v) VALUES ('other', x'00')")
                o.commit()
                o.close()
                results["ok"] = True
            except Exception as exc:  # pragma: no cover - failure path
                results["err"] = str(exc)

        t = threading.Thread(target=other_writer)
        t.start()
        time.sleep(0.2)  # let the writer hit our lock

        conn.execute("INSERT OR IGNORE INTO t(k, v) VALUES ('mine', x'00')")
        conn.execute("COMMIT")
        conn.close()
        t.join(timeout=15)

        assert "err" not in results, f"concurrent writer failed: {results.get('err')}"
        check = sqlite3.connect(db)
        rows = check.execute("SELECT k FROM t ORDER BY k").fetchall()
        assert [r[0] for r in rows] == ["mine", "other"]
        check.close()

    def test_store_succeeds_under_concurrent_writer(self, tmp_path, monkeypatch):
        """End-to-end store() survives a real concurrent writer hammering the
        same SQLite file (the live-server condition behind the 503s)."""
        monkeypatch.setattr(settings, "localmind_db_path", str(tmp_path / "localmind.db"))
        monkeypatch.setattr(settings, "ollama_embed_model", "test-embed")
        store = _make_store(str(tmp_path / "localmind.db"))

        import storage.vector as vector_mod

        async def _fake_embed(text):
            return vector_mod._normalise([0.1] * 8)

        monkeypatch.setattr(store, "_embed", _fake_embed)

        stop = threading.Event()

        def raw_writer():
            while not stop.is_set():
                try:
                    c = sqlite3.connect(str(tmp_path / "localmind.db"), timeout=1.0)
                    c.execute("PRAGMA journal_mode = WAL")
                    c.execute(
                        "INSERT OR IGNORE INTO embed_cache(key, vec) VALUES (?, ?)",
                        (f"k{time.monotonic_ns()}", b"\x00" * 100),
                    )
                    c.commit()
                    c.close()
                except Exception:
                    pass
                time.sleep(0.002)

        t = threading.Thread(target=raw_writer)
        t.start()
        try:
            import asyncio

            for i in range(15):
                ok = asyncio.run(
                    store.store(f"concurrent fact {i}", "manual", source="manual")
                )
                assert ok is True, f"store({i}) failed under concurrent writer"
        finally:
            stop.set()
            t.join(timeout=10)
