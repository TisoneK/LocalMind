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
