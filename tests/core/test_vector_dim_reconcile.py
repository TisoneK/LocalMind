"""Vec0 table dimension is the ground truth, not vector_meta.

The failure this covers: an index whose vec0 table is frozen at 768 while
`vector_meta.dim` and the active embedder (mxbai-embed-large) are 1024. The
startup probe compared the embedder against the *meta row* only, so it saw
1024 == 1024 and declared the store healthy; every write then died at runtime
with sqlite-vec's "Dimension mismatch: Expected 768 dimensions but received
1024". `scripts/reset_vector_db.py` repeated the same meta-only comparison and
reported "Dims match — nothing to reset."

sqlite-vec freezes a vec0 table's dimension at CREATE time (IF NOT EXISTS never
alters it), so the table's DDL is what INSERTs are checked against. These tests
pin the reconciliation rules:

  * stale *empty* index -> rebuilt at the embedder's dimension, meta repaired;
  * populated index     -> trusted over a stale meta row (meta corrected);
  * populated index + embedder at another dim -> writes/recall refused loudly;
  * a runtime embed width change is caught before sqlite-vec sees it;
  * a failed embed model never falls back to the chat model.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3

import pytest

os.environ.setdefault("LOCALMIND_HOME", ".")

import httpx

import storage.vector as v
from core.config import settings


def _vec_for(text: str, dim: int) -> list[float]:
    return [
        (hashlib.sha256(f"{text}|{i}".encode()).digest()[0] - 127) / 128.0
        for i in range(dim)
    ]


class _FakeResp:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def json(self) -> dict:
        return self._payload


class _FakeNet:
    """Ollama-shaped fake: probes answer `probe_dim`, texts answer `text_dim`."""

    def __init__(self, probe_dim: int | None, text_dim: int | None = None):
        self.probe_dim = probe_dim
        self.text_dim = probe_dim if text_dim is None else text_dim
        self.calls: list[dict] = []

    def handle(self, url: str, body: dict) -> _FakeResp:
        self.calls.append(body)
        if self.probe_dim is None:
            raise httpx.ConnectError("All connection attempts failed")
        if body.get("prompt") == "dim_probe":
            return _FakeResp({"embedding": _vec_for("dim_probe", self.probe_dim)})
        if self.text_dim is None:
            raise httpx.ConnectError("All connection attempts failed")
        return _FakeResp(
            {"embedding": _vec_for(str(body.get("prompt", "")), self.text_dim)}
        )

    async def apost(self, url, json=None, headers=None, **kw):
        return self.handle(url, json or {})

    def spost(self, url, json=None, headers=None, timeout=None):
        return self.handle(url, json or {})


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.setattr(v, "_USE_CLOUD", False)
    v._embed_cached.cache_clear()
    monkeypatch.setattr(settings, "localmind_embed_adapter", "")
    monkeypatch.setattr(settings, "localmind_embed_base_url", "")
    monkeypatch.setattr(settings, "localmind_embed_model", "")
    monkeypatch.setattr(settings, "localmind_embed_key_provider", "openai")
    monkeypatch.setattr(settings, "_runtime_api_keys", {}, raising=False)
    monkeypatch.setattr(settings, "ollama_embed_model", "test-embed")
    monkeypatch.setattr(settings, "ollama_model", "chat-model")
    monkeypatch.setattr(settings, "ollama_base_url", "http://localhost:11434")
    yield
    v._embed_cached.cache_clear()


def _wire(monkeypatch, net: _FakeNet):
    monkeypatch.setattr(v.httpx, "post", net.spost)

    async def _client():
        return net

    monkeypatch.setattr(v, "_get_async_client", _client)


def _make_db(
    path,
    *,
    table_dim: int | None,
    meta_dim: int | None,
    facts: int = 0,
    vectors: int = 0,
    backend_id: str | None = None,
) -> str:
    """Build a DB in the exact shape VectorStore expects, with table/meta dims
    set independently so the stale states can be reproduced."""
    db_path = str(path)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS vector_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vector_facts (
            id          TEXT PRIMARY KEY,
            content     TEXT NOT NULL,
            metadata    TEXT NOT NULL DEFAULT '{}',
            created_at  REAL NOT NULL DEFAULT (unixepoch('now'))
        )
        """
    )
    conn.execute("CREATE TABLE IF NOT EXISTS embed_cache (key TEXT PRIMARY KEY, vec BLOB NOT NULL)")
    if meta_dim is not None:
        conn.execute(
            "INSERT OR REPLACE INTO vector_meta(key, value) VALUES ('dim', ?)", (str(meta_dim),)
        )
    if backend_id is not None:
        conn.execute(
            "INSERT OR REPLACE INTO vector_meta(key, value) VALUES ('embed_backend_id', ?)",
            (backend_id,),
        )
    for i in range(facts):
        conn.execute(
            "INSERT INTO vector_facts(id, content, metadata) VALUES (?, ?, ?)",
            (f"fact{i}", f"stored fact {i}", "{}"),
        )
    if table_dim is not None:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute(
            f"CREATE VIRTUAL TABLE vector_embeddings USING vec0(embedding float[{table_dim}])"
        )
        for i in range(vectors):
            blob = v._pack(v._normalise(_vec_for(f"stored fact {i}", table_dim)))
            conn.execute(
                "INSERT INTO vector_embeddings(rowid, embedding) VALUES (?, ?)",
                (i + 1, blob),
            )
    conn.commit()
    conn.close()
    return db_path


def _store(db_path: str):
    return v.VectorStore(db_path=db_path)


def _meta_dim(db_path: str) -> int | None:
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT value FROM vector_meta WHERE key = 'dim'").fetchone()
    conn.close()
    return int(row[0]) if row else None


def _table_dim(db_path: str) -> int | None:
    conn = sqlite3.connect(db_path)
    try:
        return v._vec_table_dim(conn)
    finally:
        conn.close()


# ── Startup reconciliation ───────────────────────────────────────────────────


class TestStartupReconcile:
    def test_stale_empty_table_rebuilt_at_probe_dim(self, tmp_path, monkeypatch):
        """The reported state: table 768, meta 1024, embedder 1024, 4 facts and
        no vectors. Startup must repair the index instead of passing a meta-only
        comparison and failing on every write."""
        net = _FakeNet(probe_dim=1024)
        _wire(monkeypatch, net)
        db = _make_db(
            tmp_path / "localmind.db", table_dim=768, meta_dim=1024, facts=4, vectors=0
        )

        store = _store(db)
        assert store._ready is True
        assert store._dim == 1024
        assert store._dim_mismatch is None
        assert _table_dim(db) == 1024
        assert _meta_dim(db) == 1024

        assert asyncio.run(store.store("User likes dark mode", "s1")) is True
        assert "User likes dark mode" in asyncio.run(store.recall("dark mode"))

    def test_empty_table_without_meta_is_rebuilt_and_tracked(self, tmp_path, monkeypatch):
        """A lost meta row must not let a later _set_dim recreate the table at a
        different dimension: the table dim is adopted and recorded."""
        net = _FakeNet(probe_dim=512)
        _wire(monkeypatch, net)
        db = _make_db(tmp_path / "localmind.db", table_dim=768, meta_dim=None, facts=1)

        store = _store(db)
        assert store._ready is True
        assert store._dim == 512
        assert _table_dim(db) == 512
        assert _meta_dim(db) == 512
        assert asyncio.run(store.store("a fresh fact", "s1")) is True

    def test_populated_table_trusted_over_stale_meta(self, tmp_path, monkeypatch):
        """Vectors on disk define the space actually present; when the probe
        agrees with the table, only the meta row was stale."""
        net = _FakeNet(probe_dim=8)
        _wire(monkeypatch, net)
        db = _make_db(
            tmp_path / "localmind.db", table_dim=8, meta_dim=1024, facts=1, vectors=1
        )

        store = _store(db)
        assert store._ready is True
        assert store._dim == 8
        assert _meta_dim(db) == 8
        assert _table_dim(db) == 8
        assert "stored fact 0" in asyncio.run(store.recall("stored fact 0"))

    def test_populated_table_refuses_different_embedder(self, tmp_path, monkeypatch):
        """A real mismatch must stay loud: writes refused, recall empty, and the
        table is left untouched for a reset rather than silently rewritten."""
        net = _FakeNet(probe_dim=16)
        _wire(monkeypatch, net)
        db = _make_db(tmp_path / "localmind.db", table_dim=8, meta_dim=8, facts=1, vectors=1)

        store = _store(db)
        assert store._ready is False
        assert store._dim_mismatch == (8, 16)
        assert asyncio.run(store.store("new fact", "s1")) is False
        assert asyncio.run(store.recall("stored fact 0")) == []
        assert _table_dim(db) == 8
        assert _meta_dim(db) == 8

    def test_empty_index_ignores_stale_backend_id(self, tmp_path, monkeypatch):
        """A recorded backend id with no vectors left must not block the
        rebuild behind the embedding-space guard."""
        net = _FakeNet(probe_dim=1024)
        _wire(monkeypatch, net)
        db = _make_db(
            tmp_path / "localmind.db",
            table_dim=768,
            meta_dim=1024,
            facts=2,
            vectors=0,
            backend_id="ollama|http://localhost:11434|nomic-embed-text",
        )

        store = _store(db)
        assert store._ready is True
        assert store._dim_mismatch is None
        assert asyncio.run(store.store("User prefers vim", "s1")) is True


# ── Runtime guards ───────────────────────────────────────────────────────────


class TestRuntimeGuards:
    def test_store_refuses_vectors_of_a_new_width(self, tmp_path, monkeypatch):
        net = _FakeNet(probe_dim=4)
        _wire(monkeypatch, net)
        db = _make_db(tmp_path / "localmind.db", table_dim=None, meta_dim=None)

        store = _store(db)
        assert asyncio.run(store.store("first fact", "s1")) is True
        assert store._dim == 4

        # The embedder starts answering at another width mid-session.
        net.text_dim = 6
        net.probe_dim = 6
        v._embed_cached.cache_clear()
        assert asyncio.run(store.store("second fact", "s1")) is False
        assert store._dim_mismatch == (4, 6)
        # An unseen query has no cached vector, so recall reaches the guard.
        assert asyncio.run(store.recall("unseen query")) == []
        assert _table_dim(db) == 4

    def test_no_chat_model_embedding_fallback(self, monkeypatch):
        """A failing embed model must return None, never retry with the chat
        model — that fallback wrote a different space into live indexes."""
        calls: list[dict] = []

        def _post(url, json=None, headers=None, timeout=None):
            calls.append(json or {})
            if (json or {}).get("model") == "chat-model":
                return _FakeResp({"embedding": _vec_for("x", 4)})
            return _FakeResp({}, status_code=404)

        monkeypatch.setattr(v.httpx, "post", _post)
        result = v._embed_cached("hello world", "ollama", "http://localhost:11434", "test-embed")
        assert result is None
        assert all(body.get("model") != "chat-model" for body in calls)


# ── Reset script detection ───────────────────────────────────────────────────


class TestResetScriptDetection:
    @staticmethod
    def _mod():
        import importlib.util
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location(
            "reset_vector_db", root / "scripts" / "reset_vector_db.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_reads_table_dim_not_meta(self, tmp_path):
        mod = self._mod()
        db = _make_db(tmp_path / "localmind.db", table_dim=768, meta_dim=1024, facts=1)
        assert mod._get_stored_dim(db) == 1024
        assert mod._get_vec_table_dim(db) == 768

        clean = _make_db(tmp_path / "clean.db", table_dim=1024, meta_dim=1024)
        assert mod._get_stored_dim(clean) == 1024
        assert mod._get_vec_table_dim(clean) == 1024

    def test_drop_really_removes_the_vec_table(self, tmp_path):
        """The drop runs without the extension loaded once swallowed its error,
        so `IF NOT EXISTS` later kept the stale table at the old dimension."""
        mod = self._mod()
        db = _make_db(tmp_path / "localmind.db", table_dim=768, meta_dim=1024, facts=1)

        mod._drop_vector_tables(db)

        assert mod._get_vec_table_dim(db) is None
        assert mod._get_stored_dim(db) is None
