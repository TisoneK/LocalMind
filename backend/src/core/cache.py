"""
Shared cache primitives (Session 135 addendum).

Consolidates the ad-hoc TTL caches that previously lived inline in several
modules (thinking_dispatcher._PLAN_CACHE, api/routes/health.py reachability,
tools/installed_programs.py windows list, ...) into ONE tested primitive so
future caches get TTL + bounded eviction + optional deep-copy-on-read for
free instead of re-implementing the same monotonic-clock dance per file.

All caches here are IN-PROCESS and keyed in memory. They are appropriate
for memoizing expensive but cheap-to-key work (model routes, health probes,
repeated routing decisions). They are NOT a substitute for the persistent
stores in storage/ (db.py, vector.py embed cache).
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import OrderedDict
from functools import wraps
from typing import Any, Callable, Generic, Optional, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    """Thread-safe, bounded, TTL cache.

    Semantics:
      - Entries expire ``ttl_seconds`` after insertion. Expiry is checked
        lazily on ``get`` (a stale entry is dropped and reported as a miss)
        and swept opportunistically on ``set`` so the dict never accumulates
        dead keys.
      - When at ``max_entries`` capacity, the oldest-inserted entry is
        evicted (FIFO by insertion order — dicts preserve insertion order).
      - Optional ``copier``: when set, ``get()`` returns ``copier(value)``
        instead of the stored object, so callers can never mutate cached
        state through the returned reference (e.g. ``model_copy(deep=True)``
        for pydantic models). If the copier raises, the entry is dropped and
        treated as a miss — a shared mutable reference must never leak.

    Note: ``get()`` returns ``None`` for both a miss and an expired entry,
    so store values that are never legitimately ``None``.
    """

    def __init__(
        self,
        ttl_seconds: float = 300.0,
        max_entries: int = 64,
        copier: Optional[Callable[[T], T]] = None,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._copier = copier
        self._store: "OrderedDict[Any, tuple[float, T]]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Any) -> Optional[T]:
        """Return the cached value if fresh (copied if a copier is set), else None."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if time.monotonic() - stored_at > self.ttl_seconds:
                del self._store[key]
                return None
            if self._copier is None:
                return value
            try:
                return self._copier(value)
            except Exception:
                # Copy failure — drop the entry and report a miss. Returning
                # the stored instance would hand out a shared mutable
                # reference; a re-run is cheaper than a corrupted cache.
                del self._store[key]
                return None

    def set(self, key: Any, value: T) -> None:
        """Store a value, refreshing its timestamp and insertion position."""
        with self._lock:
            self._sweep_expired()
            if key in self._store:
                del self._store[key]
            if len(self._store) >= self.max_entries:
                # Evict oldest by insertion order (FIFO).
                self._store.popitem(last=False)
            self._store[key] = (time.monotonic(), value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def pop(self, key: Any) -> None:
        """Drop a single key (no-op if absent).

        Used for targeted invalidation, e.g. per-provider model-list caches
        when one provider's config changes.
        """
        with self._lock:
            self._store.pop(key, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    def _sweep_expired(self) -> None:
        now = time.monotonic()
        expired = [
            k for k, (ts, _v) in self._store.items() if now - ts > self.ttl_seconds
        ]
        for k in expired:
            del self._store[k]


class LRUCache(Generic[T]):
    """Thread-safe, bounded LRU cache (no TTL).

    Evicts the LEAST-RECENTLY-USED entry when at ``max_entries`` — ``get``
    refreshes recency (move-to-end). Use this for memoization where recency
    matters more than age (e.g. the chat-agent response cache). For TTL
    expiry use :class:`TTLCache`.
    """

    def __init__(self, max_entries: int = 256) -> None:
        self.max_entries = max_entries
        self._store: "OrderedDict[Any, T]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Any) -> Optional[T]:
        """Return the cached value, refreshing its recency; None on miss."""
        with self._lock:
            if key not in self._store:
                return None
            self._store.move_to_end(key)
            return self._store[key]

    def set(self, key: Any, value: T) -> None:
        """Store a value, marking it most-recently-used; evict LRU if over cap."""
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            else:
                if len(self._store) >= self.max_entries:
                    self._store.popitem(last=False)  # evict least-recently-used
            self._store[key] = value

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


# ── Memoize decorator ──────────────────────────────────────────────────────


def memoize(
    ttl_seconds: float = 300.0,
    max_entries: int = 64,
    key_fn: Optional[Callable[..., Any]] = None,
    copier: Optional[Callable[[Any], Any]] = None,
):
    # Support bare @memoize (no parens) like functools.lru_cache — the first
    # positional arg is then the decorated function with default options.
    if callable(ttl_seconds):
        return memoize()(ttl_seconds)

    """Memoize a function's result in a per-function TTLCache.

    Supports both sync and async callables. Each decorated function gets its
    OWN TTLCache instance (mirroring functools.lru_cache's per-function
    cache), so keys can never collide across functions.

    Args:
        ttl_seconds: How long a result is reused before the function re-runs.
        max_entries: Bound on cached keys (FIFO eviction by insertion order).
        key_fn: Optional ``key_fn(args_tuple, kwargs_dict) -> hashable key``.
            Default: ``(repr(pos_arg)..., kwarg=repr(v)...)`` — repr keeps
            unhashable args from crashing the keyer; the cache key itself is
            a tuple of strings, always hashable.
        copier: Optional deep-copy applied on read so callers can't mutate
            cached state through the returned reference.

    Returns the wrapped function with a ``.cache`` attribute exposing the
    underlying TTLCache (for tests and targeted ``cache.clear()``).

    Single-flight: concurrent misses for the SAME key are serialized by a
    per-key lock (asyncio.Lock for async callables, threading.Lock for sync)
    so the underlying function computes ONCE and the other callers reuse the
    result — mirroring the adapter /models per-provider lock. Lock dicts are
    bounded (oldest evicted past a cap); eviction only costs a duplicate
    compute, never correctness.

    Note: like TTLCache, ``None`` means "miss" — a function returning None
    is never cached and re-runs every call.
    """

    cache: TTLCache = TTLCache(
        ttl_seconds=ttl_seconds,
        max_entries=max_entries,
        copier=copier,
    )

    # ── Per-key single-flight locks (Session 140) ────────────────────────
    # Concurrent misses for the SAME key must compute ONCE, not N times: the
    # first caller to acquire the key's lock computes + stores, waiters re-
    # check the cache after acquiring and return the stored result. Mirrors
    # the adapter /models per-provider lock, but generic per-key.
    #
    # The lock dicts are bounded (evict oldest beyond a cap) so a long-lived
    # process with many distinct keys can't grow unboundedly. The cap scales
    # with max_entries so lock-dict key memory stays proportional to the
    # cache itself (e.g. a 256-entry cache holds at most ~1K lock keys, not
    # a fixed 1024 regardless of size). Eviction is safe for correctness:
    # losing a lock merely means a duplicate compute (same as no
    # single-flight), never a wrong result.
    _SINGLE_FLIGHT_LOCKS_MAX = max(64, min(1024, max_entries * 4))
    _async_key_locks: dict[Any, "asyncio.Lock"] = {}
    _thread_key_locks: dict[Any, "threading.Lock"] = {}
    _locks_guard = threading.Lock()

    def _get_key_lock(key: Any, lock_map: dict, factory) -> Any:
        """Return (creating if needed) the per-key single-flight lock."""
        with _locks_guard:
            lock = lock_map.get(key)
            if lock is None:
                if len(lock_map) >= _SINGLE_FLIGHT_LOCKS_MAX:
                    lock_map.pop(next(iter(lock_map)), None)
                lock = factory()
                lock_map[key] = lock
            return lock

    def _default_key(args: tuple, kwargs: dict) -> tuple:
        parts = [repr(a) for a in args]
        parts.extend(f"{k}={v!r}" for k, v in sorted(kwargs.items()))
        return tuple(parts)

    keyer = key_fn or _default_key

    def _store_and_return(result, key):
        # Shared by the sync and async wrappers.
        if result is None:
            return None
        cache.set(key, result)
        if copier is not None:
            # Hand out a fresh copy even on the FIRST call — otherwise the
            # caller would receive the stored object itself and a mutation
            # would corrupt the cache before any later read could be
            # protected.
            copied = cache.get(key)
            if copied is not None:
                return copied
        return result

    def decorator(fn):
        if asyncio.iscoroutinefunction(fn):

            @wraps(fn)
            async def _async_wrapper(*args, **kwargs):
                key = keyer(args, kwargs)
                cached = cache.get(key)
                if cached is not None:
                    return cached
                # Single-flight: serialize concurrent misses for this key.
                async with _get_key_lock(key, _async_key_locks, asyncio.Lock):
                    # Re-check after acquiring — the lock winner may have
                    # computed + stored while we waited.
                    cached = cache.get(key)
                    if cached is not None:
                        return cached
                    return _store_and_return(await fn(*args, **kwargs), key)

            _async_wrapper.cache = cache
            return _async_wrapper

        @wraps(fn)
        def _sync_wrapper(*args, **kwargs):
            key = keyer(args, kwargs)
            cached = cache.get(key)
            if cached is not None:
                return cached
            with _get_key_lock(key, _thread_key_locks, threading.Lock):
                cached = cache.get(key)
                if cached is not None:
                    return cached
                return _store_and_return(fn(*args, **kwargs), key)

        _sync_wrapper.cache = cache
        return _sync_wrapper

    return decorator
