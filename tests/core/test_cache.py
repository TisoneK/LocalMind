"""Session 135 addendum — unit tests for the shared core.cache.TTLCache.

Consolidates the TTL-cache behavior previously inlined per-file (dispatcher
plan cache, health reachability, installed-programs) into one tested
primitive. These tests pin the contract the migrated modules rely on:
TTL expiry, bounded FIFO eviction, deep-copy-on-read via copier (including
the copy-failure → miss path), clear, and None-as-miss semantics.
"""

from __future__ import annotations

import time

import pytest
from core.cache import LRUCache, TTLCache


@pytest.fixture(autouse=True)
def _fast_clock(monkeypatch):
    """Deterministic monotonic clock so TTL tests don't sleep."""
    now = {"t": 1000.0}
    monkeypatch.setattr(time, "monotonic", lambda: now["t"])
    yield now


def test_miss_then_hit(_fast_clock):
    cache: TTLCache[str] = TTLCache(ttl_seconds=60.0)
    assert cache.get("k") is None
    cache.set("k", "v")
    assert cache.get("k") == "v"


def test_ttl_expiry(_fast_clock):
    cache: TTLCache[str] = TTLCache(ttl_seconds=60.0)
    cache.set("k", "v")
    _fast_clock["t"] += 60.001
    assert cache.get("k") is None, "entry past TTL must be a miss"
    assert len(cache) == 0, "expired entry must be dropped, not lingering"


def test_set_refreshes_timestamp(_fast_clock):
    cache: TTLCache[str] = TTLCache(ttl_seconds=60.0)
    cache.set("k", "v1")
    _fast_clock["t"] += 30.0
    cache.set("k", "v2")  # refresh
    _fast_clock["t"] += 30.0
    assert cache.get("k") == "v2", "re-set must extend the entry's life"


def test_bounded_fifo_eviction(_fast_clock):
    cache: TTLCache[str] = TTLCache(ttl_seconds=300.0, max_entries=3)
    for i in range(5):
        cache.set(f"k{i}", str(i))
    assert len(cache) == 3
    # Oldest two inserted entries evicted first.
    assert cache.get("k0") is None
    assert cache.get("k1") is None
    assert cache.get("k2") == "2"
    assert cache.get("k3") == "3"
    assert cache.get("k4") == "4"


def test_re_set_moves_entry_to_newest(_fast_clock):
    cache: TTLCache[str] = TTLCache(ttl_seconds=300.0, max_entries=2)
    cache.set("a", "1")
    cache.set("b", "2")
    cache.set("a", "1b")  # refresh 'a' → it becomes newest
    cache.set("c", "3")  # evicts oldest = 'b'
    assert cache.get("a") == "1b"
    assert cache.get("b") is None
    assert cache.get("c") == "3"


def test_copier_returns_fresh_object(_fast_clock):
    stored = {"n": 1}
    cache: TTLCache[dict] = TTLCache(
        ttl_seconds=60.0, copier=lambda d: dict(d)
    )
    cache.set("k", stored)
    got = cache.get("k")
    assert got == stored
    got["n"] = 99  # mutate the copy
    assert cache.get("k")["n"] == 1, "stored object must never be mutated"


def test_copier_failure_is_a_miss(_fast_clock):
    def _boom(_v):
        raise RuntimeError("copy failed")

    cache: TTLCache[str] = TTLCache(ttl_seconds=60.0, copier=_boom)
    cache.set("k", "v")
    assert cache.get("k") is None, "copy failure must be treated as a miss"
    assert len(cache) == 0, "copy-failed entry must be dropped (no shared ref)"


def test_clear(_fast_clock):
    cache: TTLCache[str] = TTLCache(ttl_seconds=60.0)
    cache.set("a", "1")
    cache.set("b", "2")
    cache.clear()
    assert len(cache) == 0
    assert cache.get("a") is None


def test_lru_evicts_least_recently_used():
    cache: LRUCache[str] = LRUCache(max_entries=3)
    cache.set("a", "1")
    cache.set("b", "2")
    cache.set("c", "3")
    cache.get("a")  # refresh 'a' — now 'b' is least-recently-used
    cache.set("d", "4")  # evicts 'b'
    assert cache.get("a") == "1"
    assert cache.get("b") is None
    assert cache.get("c") == "3"
    assert cache.get("d") == "4"


def test_lru_re_set_moves_to_most_recent():
    cache: LRUCache[str] = LRUCache(max_entries=2)
    cache.set("a", "1")
    cache.set("b", "2")
    cache.set("a", "1b")  # refresh
    cache.set("c", "3")  # evicts 'b' (least recently used)
    assert cache.get("a") == "1b"
    assert cache.get("b") is None
    assert cache.get("c") == "3"


def test_lru_clear():
    cache: LRUCache[str] = LRUCache(max_entries=10)
    cache.set("a", "1")
    cache.clear()
    assert len(cache) == 0
    assert cache.get("a") is None


def test_thread_safety_smoke():
    """Concurrent sets/gets must not corrupt the store."""
    import threading

    cache: TTLCache[int] = TTLCache(ttl_seconds=300.0, max_entries=100)
    errors: list[Exception] = []

    def _worker(offset: int):
        try:
            for i in range(50):
                cache.set(f"k-{offset}-{i}", i)
                cache.get(f"k-{offset}-{i}")
        except RuntimeError as e:  # pragma: no cover - failure path
            errors.append(e)

    threads = [threading.Thread(target=_worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(cache) <= 100

    # Same smoke for the LRU variant.
    lru: LRUCache[int] = LRUCache(max_entries=100)
    lru_errors: list[Exception] = []

    def _lru_worker(offset: int):
        try:
            for i in range(50):
                lru.set(f"k-{offset}-{i}", i)
                lru.get(f"k-{offset}-{i}")
        except RuntimeError as e:  # pragma: no cover - failure path
            lru_errors.append(e)

    threads = [threading.Thread(target=_lru_worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not lru_errors
    assert len(lru) <= 100
