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

import threading
import time
from collections import OrderedDict
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
