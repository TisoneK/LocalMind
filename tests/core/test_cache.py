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
from core.cache import LRUCache, TTLCache, memoize


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


# ── Memoize decorator ──────────────────────────────────────────────────────


def test_memoize_caches_by_args(_fast_clock):
    calls = []

    @memoize(ttl_seconds=60.0)
    def add(a, b):
        calls.append((a, b))
        return a + b

    assert add(1, 2) == 3
    assert add(1, 2) == 3  # cached
    assert add(2, 3) == 5  # different args → miss
    assert len(calls) == 2
    assert add.cache is not None


def test_memoize_ttl_expiry(_fast_clock):
    calls = []

    @memoize(ttl_seconds=60.0)
    def f(x):
        calls.append(x)
        return x * 2

    assert f(5) == 10
    _fast_clock["t"] += 60.001
    assert f(5) == 10  # expired → recompute
    assert len(calls) == 2


def test_memoize_kwargs_and_key_fn(_fast_clock):
    calls = []

    @memoize(ttl_seconds=60.0, key_fn=lambda args, kwargs: args[0])
    def f(x, y=10):
        calls.append((x, y))
        return x + y

    assert f(1) == 11
    assert f(1, y=20) == 11  # same key (ignores kwargs) → cached
    assert len(calls) == 1


def test_memoize_none_result_not_cached(_fast_clock):
    calls = []

    @memoize(ttl_seconds=60.0)
    def f(x):
        calls.append(x)

    assert f(1) is None
    assert f(1) is None  # None = miss → recomputes every time
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_memoize_async(_fast_clock):
    import asyncio

    calls = []

    @memoize(ttl_seconds=60.0)
    async def af(x):
        await asyncio.sleep(0)  # ensure coroutine behavior
        calls.append(x)
        return x * 3

    assert await af(4) == 12
    assert await af(4) == 12  # cached
    assert len(calls) == 1


def test_memoize_copier_isolates_caller_mutations(_fast_clock):
    @memoize(ttl_seconds=60.0, copier=lambda v: list(v))
    def f():
        return [1, 2, 3]

    first = f()
    first.append(99)  # mutate the copy
    assert f() == [1, 2, 3], "stored value must not be mutated via the copy"


def test_memoize_bare_usage_without_parens(_fast_clock):
    """@memoize (no parens) behaves like @memoize() with defaults."""
    calls = []

    @memoize
    def f(x):
        calls.append(x)
        return x * 2

    assert f(3) == 6
    assert f(3) == 6  # cached
    assert len(calls) == 1
    assert f(4) == 8  # different arg → miss
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_memoize_async_single_flight_computes_once(_fast_clock):
    """Concurrent misses for the SAME key compute once, not N times."""
    import asyncio

    compute_count = 0

    @memoize(ttl_seconds=60.0)
    async def slow(x):
        nonlocal compute_count
        compute_count += 1
        # sleep(0) yields the loop so gather's other tasks reach the lock —
        # must stay 0: the autouse _fast_clock freezes time.monotonic, so any
        # nonzero asyncio.sleep would never wake.
        await asyncio.sleep(0)
        return x * 2

    # Fire 10 concurrent calls for the same key — single-flight must collapse
    # them into ONE underlying computation.
    results = await asyncio.gather(*(slow(5) for _ in range(10)))
    assert results == [10] * 10
    assert compute_count == 1, "concurrent misses for the same key must compute once"


@pytest.mark.asyncio
async def test_memoize_async_distinct_keys_compute_independently(_fast_clock):
    """Different keys are not serialized by the single-flight lock."""
    import asyncio

    computed = set()

    @memoize(ttl_seconds=60.0)
    async def f(x):
        computed.add(x)
        await asyncio.sleep(0)
        return x

    await asyncio.gather(*(f(i) for i in range(5)))
    assert computed == {0, 1, 2, 3, 4}, "distinct keys must each compute"


def test_memoize_sync_single_flight_across_threads():
    """Concurrent cross-thread misses for the same key compute once."""
    import threading
    import time as _time

    compute_count = 0

    @memoize(ttl_seconds=60.0)
    def slow(x):
        nonlocal compute_count
        compute_count += 1
        _time.sleep(0.01)
        return x * 2

    results: list = []

    def _worker():
        results.append(slow(7))

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results == [14] * 8
    assert compute_count == 1, "cross-thread same-key misses must compute once"


def test_approx_tokens_is_memoized():
    """The engine's token estimator caches identical text (30+ calls/request)."""
    from core.engine._helpers import _approx_tokens

    _approx_tokens.cache.clear()  # start cold
    text = "the quick brown fox jumps over the lazy dog " * 10
    first = _approx_tokens(text)
    second = _approx_tokens(text)
    assert first == second
    assert len(_approx_tokens.cache) == 1

    # Different text → distinct entry, still cached.
    _approx_tokens("a completely different sentence")
    assert len(_approx_tokens.cache) == 2


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
