"""Fact identity and deletion at the store level.

Two halves of the same problem:

- Writing the same fact twice must not leave two rows. The store dedups
  paraphrases by vector distance, but that path needs the embedding backend to
  answer — the degraded plain-text path had no identity at all and appended a
  copy per statement. A key gives a fact one durable identity that survives
  re-wording, restarts, and a missing embedder.
- Deleting must find the fact. A content-hash id only matches the exact wording
  that stored it, so "forget X" re-worded matched nothing while the fact sat in
  the store; and an id the agent prints must be an id the agent (or user) can
  act on, which means resolving a unique prefix.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3

os.environ.setdefault("LOCALMIND_HOME", ".")

from core.config import settings


def _make_store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "localmind_db_path", str(tmp_path / "localmind.db"))
    monkeypatch.setattr(settings, "ollama_embed_model", "test-embed")
    from storage.vector import VectorStore

    return VectorStore(db_path=str(tmp_path / "localmind.db"))


def _install_embed(store, monkeypatch, *, same_vector: bool = False):
    """Deterministic embedder. same_vector makes every text equidistant, which
    forces the semantic-dedup path to consider them duplicates."""
    import storage.vector as vector_mod

    async def _embed(text):
        if same_vector:
            return vector_mod._normalise([1.0, 0.0, 0.0, 0.0])
        seed = sum(ord(c) for c in text)
        return vector_mod._normalise([0.1 * ((seed + i) % 7 + 1) for i in range(8)])

    monkeypatch.setattr(store, "_embed", _embed)


_KEY = "subject:location"


class TestKeyedIdentity:
    def test_restating_a_keyed_fact_keeps_one_row(self, tmp_path, monkeypatch):
        store = _make_store(tmp_path, monkeypatch)
        _install_embed(store, monkeypatch)

        assert (
            asyncio.run(
                store.store("I live in Nairobi", "s", extra_metadata={"memory_key": _KEY}, key=_KEY)
            )
            is True
        )
        assert (
            asyncio.run(
                store.store(
                    "I am based in Nairobi, Kenya",
                    "s",
                    extra_metadata={"memory_key": _KEY},
                    key=_KEY,
                )
            )
            is True
        )

        rows = asyncio.run(store.list_all_with_metadata())
        assert len(rows) == 1
        assert rows[0]["fact"] == "I am based in Nairobi, Kenya"
        # The key owns the row id: stable across re-statements, and the same id
        # the read-back looks up.
        assert rows[0]["id"] == store.fact_id_for_key(_KEY)

    def test_keyed_write_supersedes_a_close_unkeyed_row(self, tmp_path, monkeypatch):
        store = _make_store(tmp_path, monkeypatch)
        _install_embed(store, monkeypatch, same_vector=True)

        asyncio.run(store.store("User lives in Nairobi", "s"))
        asyncio.run(
            store.store("I live in Nairobi", "s", extra_metadata={"memory_key": _KEY}, key=_KEY)
        )

        rows = asyncio.run(store.list_all_with_metadata())
        assert len(rows) == 1
        assert rows[0]["id"] == store.fact_id_for_key(_KEY)

    def test_unkeyed_write_keeps_the_dedup_behavior(self, tmp_path, monkeypatch):
        store = _make_store(tmp_path, monkeypatch)
        _install_embed(store, monkeypatch, same_vector=True)

        asyncio.run(store.store("User likes dark mode", "s"))
        asyncio.run(store.store("User likes dark mode a lot", "s"))

        assert asyncio.run(store.count()) == 1


class TestForgetResolution:
    def test_forget_matches_reworded_content(self, tmp_path, monkeypatch):
        store = _make_store(tmp_path, monkeypatch)
        _install_embed(store, monkeypatch)
        asyncio.run(store.store("I prefer Python", "s"))

        assert asyncio.run(store.forget("i prefer python.")) is True
        assert asyncio.run(store.count()) == 0

    def test_forget_resolves_a_unique_id_prefix(self, tmp_path, monkeypatch):
        store = _make_store(tmp_path, monkeypatch)
        _install_embed(store, monkeypatch)
        asyncio.run(store.store("I prefer Python", "s"))
        fact_id = asyncio.run(store.list_all_with_metadata())[0]["id"]

        assert asyncio.run(store.forget_by_id(fact_id[:8])) is True
        assert asyncio.run(store.count()) == 0

    def test_forget_reports_false_when_nothing_matches(self, tmp_path, monkeypatch):
        store = _make_store(tmp_path, monkeypatch)
        _install_embed(store, monkeypatch)
        asyncio.run(store.store("I prefer Python", "s"))

        assert asyncio.run(store.forget("my favourite colour")) is False
        assert asyncio.run(store.count()) == 1


class TestReadBack:
    def test_get_fact_accepts_a_prefix(self, tmp_path, monkeypatch):
        store = _make_store(tmp_path, monkeypatch)
        _install_embed(store, monkeypatch)
        asyncio.run(store.store("I prefer Python", "s"))
        fact_id = asyncio.run(store.list_all_with_metadata())[0]["id"]

        row = asyncio.run(store.get_fact(fact_id[:10]))
        assert row is not None and row["fact"] == "I prefer Python"

    def test_find_by_key_reads_back_a_row_written_without_an_embedder(
        self, tmp_path, monkeypatch
    ):
        """The degraded path writes its own id (no embedding, no vec table hit);
        the key must still find the row, or every read-back would report a
        failed write that actually succeeded."""
        store = _make_store(tmp_path, monkeypatch)
        conn = sqlite3.connect(str(tmp_path / "localmind.db"))
        conn.execute(
            "INSERT INTO vector_facts (id, content, metadata) VALUES (?, ?, ?)",
            ("deadbeefdeadbeef", "I live in Nairobi", json.dumps({"memory_key": _KEY})),
        )
        conn.commit()
        conn.close()

        row = asyncio.run(store.find_by_key(_KEY))
        assert row is not None
        assert row["fact"] == "I live in Nairobi"
        assert asyncio.run(store.find_by_key("subject:name")) is None
