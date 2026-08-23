"""B-2026-08-23-14: the memory API surface the Memory tab relies on.

GET    /api/memory           — list facts in the frontend MemoryFact shape
POST   /api/memory           — store a manual fact (the new UI affordance)
DELETE /api/memory/{id}      — delete a fact; missing id → 404

Also pins two fixes found during live verification:
- timestamps: the metadata written by _persist carries `timestamp`, not
  `created_at` — the route must read it so the UI shows a real time.
- forget_by_id returns False for a missing id so DELETE is a truthful 404
  (was a silent success on nothing).
"""
from __future__ import annotations

import asyncio

import pytest

from api.routes.memory import delete_memory, list_memory, store_memory


def _run(coro):
    return asyncio.run(coro)


class FakeStore:
    """In-memory stand-in for storage.vector.VectorStore."""

    def __init__(self):
        self.facts: dict[str, dict] = {}

    async def list_all_with_metadata(self):
        return list(self.facts.values())

    async def store(self, fact, session_id, source="user", extra_metadata=None):
        import hashlib
        import time

        fid = hashlib.sha256(fact.encode()).hexdigest()[:16]
        self.facts[fid] = {
            "id": fid,
            "fact": fact,
            "session_id": session_id,
            "source": source,
            "timestamp": str(time.time()),
            "memory_type": (extra_metadata or {}).get("memory_type", "semantic"),
        }
        return True

    async def forget_by_id(self, fact_id):
        if fact_id in self.facts:
            del self.facts[fact_id]
            return True
        return False

    async def update_content(self, fact_id, new_content):
        import hashlib

        if fact_id not in self.facts:
            return None
        old = self.facts[fact_id]
        new_id = hashlib.sha256(new_content.encode()).hexdigest()[:16]
        del self.facts[fact_id]
        self.facts[new_id] = {**old, "id": new_id, "fact": new_content}
        return new_id

    async def recall_with_scores(self, query, top_k=10, session_id=None):
        # Deterministic fake: facts whose content contains a query keyword are
        # "relevant"; rank by a fake similarity score.
        q = query.lower()
        hits = [(f["fact"], 0.2, f) for f in self.facts.values() if q in f["fact"].lower()]
        return hits[:top_k]


@pytest.fixture()
def fake_store(monkeypatch):
    store = FakeStore()
    import api.routes.memory as memory_routes

    monkeypatch.setattr(memory_routes, "_store", store)
    return store


class TestMemoryList:
    def test_empty_list(self, fake_store):
        assert _run(list_memory()) == {"facts": []}

    def test_fact_shape(self, fake_store):
        _run(store_memory(type("R", (), {"fact": "User likes python", "session_id": "s1",
                                       "memory_type": "semantic", "importance": 0.9, "source": "manual"})()))
        result = _run(list_memory())["facts"]
        assert len(result) == 1
        f = result[0]
        assert f["content"] == "User likes python"
        assert f["source"] == "manual"
        assert isinstance(f["id"], str) and f["id"]
        assert isinstance(f["relevance"], float)
        assert f["timestamp"], "timestamp missing — route must read metadata 'timestamp'"


class TestMemoryStore:
    def test_store_returns_confirmation(self, fake_store):
        resp = _run(store_memory(type("R", (), {"fact": "note this", "session_id": "s1",
                                          "memory_type": "semantic", "importance": 0.5,
                                          "source": "manual"})()))
        assert resp.stored is True
        assert resp.fact == "note this"


class TestMemoryDelete:
    def test_delete_existing(self, fake_store):
        _run(store_memory(type("R", (), {"fact": "delete me", "session_id": "s1",
                                          "memory_type": "semantic", "importance": 0.5,
                                          "source": "manual"})()))
        fid = list(fake_store.facts)[0]
        resp = _run(delete_memory(fid))
        assert resp.deleted is True
        assert resp.fact_id == fid
        assert fake_store.facts == {}

    def test_delete_missing_404(self, fake_store):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            _run(delete_memory("does-not-exist"))
        assert exc.value.status_code == 404


class TestMemoryUpdate:
    def test_update_existing_fact_returns_new_id(self, fake_store):
        from api.routes.memory import update_memory

        _run(store_memory(type("R", (), {"fact": "User likes dark mode", "session_id": "s1",
                                          "memory_type": "semantic", "importance": 0.5,
                                          "source": "user"})()))
        old_id = list(fake_store.facts)[0]

        resp = _run(update_memory(old_id, type("R", (), {"content": "User likes dark mode with warm accents"})()))
        assert resp.updated is True
        assert resp.fact_id != old_id  # id is content-derived, so it changes
        assert resp.content == "User likes dark mode with warm accents"

        # Old id gone, corrected content present, metadata preserved.
        assert old_id not in fake_store.facts
        facts = _run(list_memory())["facts"]
        assert len(facts) == 1
        assert facts[0]["content"] == "User likes dark mode with warm accents"
        assert facts[0]["source"] == "user"

    def test_update_missing_fact_404(self, fake_store):
        from fastapi import HTTPException

        from api.routes.memory import update_memory

        with pytest.raises(HTTPException) as exc:
            _run(update_memory("does-not-exist", type("R", (), {"content": "x"})()))
        assert exc.value.status_code == 404


class TestMemorySearch:
    def test_semantic_recall_returns_top_k_with_relevance(self, fake_store):
        from api.routes.memory import search_memory

        _run(store_memory(type("R", (), {"fact": "User prefers dark mode", "session_id": "s1",
                                          "memory_type": "semantic", "importance": 0.5,
                                          "source": "user"})()))
        _run(store_memory(type("R", (), {"fact": "The project uses FastAPI", "session_id": "s1",
                                          "memory_type": "semantic", "importance": 0.5,
                                          "source": "agent"})()))

        result = _run(search_memory("dark mode", 5))
        facts = result["facts"]
        assert len(facts) == 1
        assert facts[0]["content"] == "User prefers dark mode"
        # relevance = 1 - distance (0.2) = 0.8, matching the frontend scale.
        assert facts[0]["relevance"] == 0.8
        assert facts[0]["source"] == "user"

    def test_empty_query_returns_no_results(self, fake_store):
        from api.routes.memory import search_memory

        assert _run(search_memory("", 5)) == {"facts": []}

    def test_top_k_is_capped(self, fake_store):
        from api.routes.memory import search_memory

        assert _run(search_memory("query", 500))["facts"] == []  # valid, just empty
        # top_k clamps to [1, 50] — a huge value must not raise.
        assert _run(search_memory("dark", 500))["facts"] == []
