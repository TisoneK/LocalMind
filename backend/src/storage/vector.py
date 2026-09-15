"""
Vector Store — sqlite-vec backed semantic memory.  (OPTIMIZED v3 — final)

Iteration history
─────────────────
v1  LRU cache · per-thread SQLite · normalise-once · zero-cost dedup
v2  Normalised cache key · bounded ThreadPoolExecutor · semaphore-gated batch
v3  Two-tier cache · startup warm-up · transactional write batching ·
    persistent embed dedup · full observability (p50/p95 latency, semaphore
    wait, queue depth, SQLite write time, cache stats)

Architecture
────────────
                 ┌──────────────────────────────────┐
  text ──────▶  │  _normalise_text()                │
                 │  Tier-1: LRU (hot queries, 4096)  │
                 │  Tier-2: SQLite embed_cache table  │  ◀── persistent across restarts
                 └──────────────┬───────────────────┘
                                │ miss
                 ┌──────────────▼───────────────────┐
                 │  Ollama /api/embeddings            │
                 │  bounded ThreadPoolExecutor        │
                 │  Semaphore(_BATCH_CONCURRENCY)     │
                 └──────────────┬───────────────────┘
                                │
                 ┌──────────────▼───────────────────┐
                 │  _normalise() → _pack()           │
                 │  sqlite-vec  (dot-product / cos)  │
                 └──────────────────────────────────┘

Public API is **unchanged** — all existing callers (MemoryComposer, engine.py,
memory_tool.py) work without modification.

New additions (fully backwards-compatible):
  store_batch(facts, ...)         — bulk embed + persist in one transaction
  warmup()                        — pre-load Ollama model, call from startup()
  metrics() -> VectorMetrics      — structured snapshot of all counters
  clear_embed_cache()             — evict LRU tier (e.g. after model switch)
  embed_cache_info() -> str       — human-readable cache stats
"""

from __future__ import annotations

import asyncio
import collections
import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

_EMBED_TIMEOUT = 30


def _get_embed_model() -> str:
    """Read embed model from settings at call time (supports hot-swap in tests)."""
    return settings.ollama_embed_model


# ── Embed backend selection ──────────────────────────────────────────────────
# A single vec0 index stores vectors from ONE embedding space.  Mixing vectors
# produced by different models/providers in the same index silently corrupts
# recall (same-dim-but-different-model vectors are not comparable, and dims can
# differ outright).  So the backend is chosen ONCE at bind time and stays fixed
# for the store's lifetime; it is never decided per call.
#
# _USE_CLOUD is a module-level flag because the whole app shares one embedding
# space: the semantic-memory store and the tool-result index must embed with the
# same backend, so their vectors live in one comparable space.  When False
# (the default) everything uses Ollama — the historical behavior.  When a
# VectorStore binds to the configured cloud embedder (because Ollama was
# unreachable at startup) it flips this flag for the process.
_USE_CLOUD: bool = False


def _cloud_embed_config() -> tuple[str, str, str]:
    """Resolve (base_url, model, api_key) for the OpenAI-compatible embedder.

    base_url falls back to the provider registry entry for
    ``settings.localmind_embed_key_provider`` (then the public OpenAI URL);
    the API key reuses an already-stored provider key so enabling a cloud
    embedder adds no new secret surface.
    """
    base = (settings.localmind_embed_base_url or "").strip()
    if not base:
        base = "https://api.openai.com/v1"
        try:
            from adapters.openai_compat import PROVIDER_CONFIGS

            cfg = PROVIDER_CONFIGS.get(settings.localmind_embed_key_provider)
            if cfg and cfg.base_url:
                base = cfg.base_url
        except Exception:
            pass
    model = (settings.localmind_embed_model or "").strip()
    key = settings.get_api_key(settings.localmind_embed_key_provider) or ""
    return base.rstrip("/"), model, key


def _backend_id(mode: str, url: str, model: str) -> str:
    """Stable identity for an embed backend — used as the cache key namespace.

    Including the backend in every cache key guarantees a cloud vector can
    never be served for an Ollama query (or vice-versa), which is the
    cross-backend poisoning the plain text-hash key allowed.
    """
    return f"{mode}|{url.rstrip('/')}|{model}"


def _current_backend(base_url: str) -> tuple[str, str, str, str]:
    """(mode, url, model, api_key) for the currently-bound embed backend.

    When cloud is bound, the passed base_url is ignored — every caller embeds
    through the one active backend so all vectors share a space.  When cloud is
    not bound, Ollama is used with the caller's base_url (unchanged behavior).
    """
    if _USE_CLOUD:
        cloud_base, cloud_model, cloud_key = _cloud_embed_config()
        return "cloud", cloud_base, cloud_model, cloud_key
    return "ollama", base_url.rstrip("/"), _get_embed_model(), ""


def _extract_cloud_embedding(payload: dict) -> list[float] | None:
    """Pull data[0].embedding out of an OpenAI /embeddings response body."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if data and isinstance(data, list):
        emb = data[0].get("embedding") if isinstance(data[0], dict) else None
        if emb:
            return list(emb)
    return None


# ── Bounded thread pool ────────────────────────────────────────────────────────
# Shared across all VectorStore instances.  Sized to CPU count — beyond that,
# context-switching overhead dominates on CPU-first deployments.
_EXECUTOR = ThreadPoolExecutor(max_workers=os.cpu_count() or 4)

# Maximum concurrent Ollama requests during batch ingestion.
_BATCH_CONCURRENCY = 4

# CPU count — used for both executor sizing and the per-store embed semaphore.
_CPU_COUNT: int = os.cpu_count() or 4

# ── Write buffer ───────────────────────────────────────────────────────────────
# Accumulates (key, blob) pairs from fire-and-forget _write_persistent calls.
# Flushed in a single transaction every _WRITE_BUFFER_FLUSH_EVERY items OR
# _WRITE_BUFFER_FLUSH_SECS seconds, whichever comes first.
# This turns N individual INSERTs (each with its own fsync) into one batch
# commit — 5–20× fewer disk syncs under ingestion load.
_WRITE_BUFFER_FLUSH_EVERY: int = 20  # items
_WRITE_BUFFER_FLUSH_SECS: float = 2.0  # seconds


# ── Observability ──────────────────────────────────────────────────────────────


@dataclass
class VectorMetrics:
    """Snapshot of all observable counters.  Returned by VectorStore.metrics()."""

    lru_hits: int = 0
    lru_misses: int = 0
    lru_size: int = 0
    persistent_hits: int = 0
    persistent_misses: int = 0
    embed_count: int = 0
    embed_p50_ms: float = 0.0
    embed_p95_ms: float = 0.0
    sem_wait_p50_ms: float = 0.0
    sem_wait_p95_ms: float = 0.0
    db_write_count: int = 0
    db_write_p50_ms: float = 0.0
    db_write_p95_ms: float = 0.0
    active_workers: int = 0


class _Stats:
    """Rolling window of latency samples (last 1 000 per dimension)."""

    _WINDOW = 1000

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._embed: collections.deque = collections.deque(maxlen=self._WINDOW)
        self._sem_wait: collections.deque = collections.deque(maxlen=self._WINDOW)
        self._db_write: collections.deque = collections.deque(maxlen=self._WINDOW)
        self.persistent_hits = 0
        self.persistent_misses = 0
        self.active_workers = 0
        self.db_write_count = 0

    def record_embed(self, ms: float) -> None:
        with self._lock:
            self._embed.append(ms)

    def record_sem_wait(self, ms: float) -> None:
        with self._lock:
            self._sem_wait.append(ms)

    def record_db_write(self, ms: float) -> None:
        with self._lock:
            self._db_write.append(ms)
            self.db_write_count += 1

    def _pct(self, samples: collections.deque, p: float) -> float:
        if not samples:
            return 0.0
        s = sorted(samples)
        return round(s[max(0, int(len(s) * p / 100) - 1)], 2)

    def snapshot(self) -> dict:
        with self._lock:
            info = _embed_cached.cache_info()
            return dict(
                lru_hits=info.hits,
                lru_misses=info.misses,
                lru_size=info.currsize,
                persistent_hits=self.persistent_hits,
                persistent_misses=self.persistent_misses,
                embed_count=len(self._embed),
                embed_p50_ms=self._pct(self._embed, 50),
                embed_p95_ms=self._pct(self._embed, 95),
                sem_wait_p50_ms=self._pct(self._sem_wait, 50),
                sem_wait_p95_ms=self._pct(self._sem_wait, 95),
                db_write_count=self.db_write_count,
                db_write_p50_ms=self._pct(self._db_write, 50),
                db_write_p95_ms=self._pct(self._db_write, 95),
                active_workers=self.active_workers,
            )


_stats = _Stats()  # module-level singleton shared by all VectorStore instances


# ── Embedding cache — Tier 1: LRU ─────────────────────────────────────────────


def _normalise_text(text: str) -> str:
    """Stable cache key: strip, collapse whitespace, lowercase."""
    return re.sub(r"\s+", " ", text.strip()).lower()


@lru_cache(maxsize=4096)
def _embed_cached(norm_text: str, mode: str, url: str, model: str) -> tuple:
    """
    Synchronous embed with LRU cache, keyed on (normalised text, backend).

    The backend identity (mode|url|model) is part of the cache key so a cloud
    vector can never be served for an Ollama query — the plain text key allowed
    exactly that cross-backend poisoning.  Records embed latency into _stats.
    Do NOT call directly — use _embed_async() which resolves the backend.
    """
    t0 = time.monotonic()
    result = None
    try:
        if mode == "cloud":
            key = _cloud_embed_config()[2]
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            resp = httpx.post(
                f"{url}/embeddings",
                json={"model": model, "input": norm_text},
                headers=headers,
                timeout=_EMBED_TIMEOUT,
            )
            if resp.status_code == 200:
                emb = _extract_cloud_embedding(resp.json())
                result = tuple(emb) if emb else None
            else:
                logger.warning(
                    "[embed] cloud returned %s: %s", resp.status_code, resp.text[:100]
                )
        else:
            post_url = f"{url}/api/embeddings"
            resp = httpx.post(
                post_url, json={"model": model, "prompt": norm_text}, timeout=_EMBED_TIMEOUT
            )
            if resp.status_code != 200:
                resp = httpx.post(
                    post_url,
                    json={"model": settings.ollama_model, "prompt": norm_text},
                    timeout=_EMBED_TIMEOUT,
                )
            data = resp.json().get("embedding")
            result = tuple(data) if data else None
    except Exception as exc:
        logger.warning("Embedding request failed: %s", exc)
    finally:
        _stats.record_embed((time.monotonic() - t0) * 1000)
    return result  # type: ignore[return-value]


# ── Async HTTP client for embedding ────────────────────────────────────────────
# v0.11 PERFORMANCE: Use httpx.AsyncClient directly instead of run_in_executor.
# This eliminates thread pool context-switching overhead and allows true async
# concurrent embeddings without being limited by CPU count.

_async_client: httpx.AsyncClient | None = None


async def _get_async_client() -> httpx.AsyncClient:
    """Get or create a shared async HTTP client."""
    global _async_client
    if _async_client is None or _async_client.is_closed:
        _async_client = httpx.AsyncClient(timeout=_EMBED_TIMEOUT)
    return _async_client


async def _embed_async(text: str, base_url: str) -> list[float] | None:
    """
    True async embedding via httpx.AsyncClient — no thread pool needed.

    v0.11 PERFORMANCE IMPROVEMENT:
    - Eliminates ThreadPoolExecutor context-switching overhead
    - Allows unlimited concurrent embeddings (no CPU-count limit)
    - Uses asyncio.Semaphore for bounded concurrency control instead

    Falls back to LRU cache first, then persistent cache, then async HTTP.

    The `base_url` argument names the Ollama endpoint and keeps its historical
    signature (an external caller passes it); when the process has bound a
    cloud embed backend, that backend wins for every caller so all vectors
    share one embedding space.
    """
    norm_text = _normalise_text(text)
    mode, url, model, api_key = _current_backend(base_url)
    backend = _backend_id(mode, url, model)

    # Check LRU cache first (sync, fast)
    cached = _embed_cached(norm_text, mode, url, model)
    if cached:
        return list(cached)

    # Check persistent cache (sync)
    persistent = _get_persistent_cache(norm_text, backend)
    if persistent:
        return persistent

    # True async HTTP — no thread pool
    _stats.active_workers += 1
    try:
        client = await _get_async_client()
        embedding = None
        if mode == "cloud":
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            response = await client.post(
                f"{url}/embeddings",
                json={"model": model, "input": norm_text},
                headers=headers,
            )
            if response.status_code == 200:
                embedding = _extract_cloud_embedding(response.json())
            else:
                logger.warning(
                    f"[embed] cloud returned {response.status_code}: {response.text[:100]}"
                )
        else:
            response = await client.post(
                f"{url}/api/embeddings",
                json={"model": model, "prompt": norm_text},
            )
            if response.status_code == 200:
                embedding = response.json().get("embedding")
            else:
                logger.warning(
                    f"[embed] Ollama returned {response.status_code}: {response.text[:100]}"
                )
        if embedding:
            # Store in LRU cache (sync)
            _embed_cached(norm_text, mode, url, model)  # Populate cache
            # Store in persistent cache asynchronously
            _safe_persist_async(norm_text, backend, tuple(embedding))
            return list(embedding)
    except httpx.TimeoutException:
        logger.warning(f"[embed] Timeout calling embedder for: {norm_text[:50]}")
    except Exception as e:
        logger.warning(f"[embed] Failed: {e}")
    finally:
        _stats.active_workers -= 1

    return None


# ── Persistent cache helpers for async embedding ───────────────────────────────


def _get_persistent_cache(norm_text: str, backend: str) -> list[float] | None:
    """
    Check the Tier-2 SQLite embed_cache for a pre-computed embedding.
    The key is namespaced by backend identity so a cloud vector can never be
    served for an Ollama query (or vice-versa).
    Returns None if not found or on error (non-critical).
    """
    try:
        key = hashlib.sha256(f"{backend}|{norm_text}".encode()).hexdigest()[:32]
        db_path = settings.localmind_db_path or "./localmind.db"
        conn = sqlite3.connect(db_path, timeout=1.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        row = conn.execute("SELECT vec FROM embed_cache WHERE key = ?", (key,)).fetchone()
        conn.close()
        if row:
            _stats.persistent_hits += 1
            vec_bytes = row["vec"]
            dim = len(vec_bytes) // 4
            return list(struct.unpack(f"{dim}f", vec_bytes))
        _stats.persistent_misses += 1
    except Exception as e:
        logger.debug(f"[embed] persistent cache miss: {e}")
    return None


async def _safe_persist_async(norm_text: str, backend: str, vec: tuple[float, ...]) -> None:
    """
    Asynchronously persist an embedding to the SQLite embed_cache table.
    This is fire-and-forget — errors are logged but never raised.
    """
    try:
        key = hashlib.sha256(f"{backend}|{norm_text}".encode()).hexdigest()[:32]
        db_path = settings.localmind_db_path or "./localmind.db"
        packed = struct.pack(f"{len(vec)}f", *vec)

        def _write():
            try:
                conn = sqlite3.connect(db_path, timeout=1.0)
                conn.execute("PRAGMA journal_mode = WAL")
                conn.execute(
                    "INSERT OR IGNORE INTO embed_cache(key, vec) VALUES (?, ?)", (key, packed)
                )
                conn.commit()
                conn.close()
            except Exception as e:
                logger.debug(f"[embed] persistent cache write failed: {e}")

        # Run in executor to not block the event loop
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _write)
    except Exception as e:
        logger.debug(f"[embed] _safe_persist_async failed: {e}")


# ── Backward compatibility shim ────────────────────────────────────────────────
# Keep the old run_in_executor path for any legacy code that needs it.


async def _embed_async_legacy(text: str, base_url: str) -> list[float] | None:
    """
    Legacy async embed via ThreadPoolExecutor.
    DEPRECATED: Use _embed_async() instead.
    """
    loop = asyncio.get_running_loop()
    _stats.active_workers += 1
    mode, url, model, _ = _current_backend(base_url)
    try:
        result = await loop.run_in_executor(
            _EXECUTOR, _embed_cached, _normalise_text(text), mode, url, model
        )
    finally:
        _stats.active_workers -= 1
    return list(result) if result else None


# ── Vector math ────────────────────────────────────────────────────────────────


def _l2_norm(vec: list[float]) -> float:
    return math.sqrt(sum(x * x for x in vec))


def _normalise(vec: list[float]) -> list[float]:
    n = _l2_norm(vec)
    return [x / n for x in vec] if n > 1e-10 else vec


def _is_normalised(vec: list[float]) -> bool:
    return abs(_l2_norm(vec) - 1.0) < 1e-5


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _cosine_to_score(dot: float) -> float:
    """dot-product of unit vectors → [0,1] distance (0=identical)."""
    return (1.0 - max(-1.0, min(1.0, dot))) / 2.0


def _l2_to_score(distance: float) -> float:
    """vec0 L2 (Euclidean) distance → [0,1] similarity distance.

    vec0's default metric returns the plain Euclidean distance (0 = identical,
    sqrt(2) = orthogonal for unit vectors), NOT a dot product. For unit
    vectors: l2^2 = 2 - 2*cos, so score = (1 - cos)/2 = l2^2 / 4.

    This was the root cause of the memory-collapse bug (S370 follow-up): the
    dedup and recall paths fed the raw L2 distance into _cosine_to_score,
    which clamps to [-1,1] — so almost ANY pair of facts scored ~0, dedup
    merged distinct facts into one row, and recall returned garbage scores.
    """
    return min(1.0, (distance * distance) / 4.0)


# ── SQLite connection pool ─────────────────────────────────────────────────────
_pool: dict[str, sqlite3.Connection] = {}
_pool_lock = threading.Lock()


def _get_connection(db_path: str) -> sqlite3.Connection:
    """One WAL-mode connection per thread — avoids open/close overhead."""
    key = f"{db_path}:{threading.get_ident()}"
    with _pool_lock:
        if key not in _pool:
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA cache_size = -8000")
            import sqlite_vec

            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            _pool[key] = conn
        return _pool[key]


# ── VectorStore ────────────────────────────────────────────────────────────────


class VectorStore:
    def __init__(self, db_path: str = None):
        self._db_path = db_path or settings.localmind_db_path or "./localmind.db"
        self._base_url = settings.ollama_base_url
        self._dim: int | None = None
        self._ready = False

        # Soft concurrency guard for single-embed calls (_embed).
        # Prevents executor queue runaway when many coroutines all call _embed
        # concurrently — caps in-flight Ollama requests to CPU count without
        # ever blocking the event loop (asyncio.Semaphore is purely cooperative).
        # store_batch() manages its own tighter semaphore (_BATCH_CONCURRENCY)
        # and bypasses this one via _embed_async directly.
        self._embed_sem: asyncio.Semaphore = asyncio.Semaphore(_CPU_COUNT)

        # Batched SQLite write buffer for embed_cache persistence.
        # Pairs are queued here and flushed as a single transaction, turning
        # N individual fsyncs into one — critical for ingestion throughput.
        self._write_buf: list[tuple[str, bytes]] = []
        self._write_buf_lock = threading.Lock()
        self._write_buf_last_flush: float = time.monotonic()

        self._dim_mismatch: tuple[int, int] | None = None  # (stored_dim, actual_dim)
        self._init_db()

    # ── Setup ──────────────────────────────────────────────────────────────

    def _probe_embed_dim(self) -> int | None:
        """
        Ask Ollama for the actual embedding dimension with a minimal probe string.
        Runs synchronously (blocking) — only called once at startup inside _init_db.
        Returns None if Ollama is unreachable (treated as "no mismatch, carry on").
        """
        try:
            url = f"{self._base_url.rstrip('/')}/api/embeddings"
            resp = httpx.post(
                url,
                json={"model": settings.ollama_embed_model, "prompt": "dim_probe"},
                timeout=10,
            )
            if resp.status_code == 200:
                vec = resp.json().get("embedding")
                if vec:
                    return len(vec)
        except Exception:
            pass
        return None

    def _probe_cloud_dim(self) -> int | None:
        """Same one-shot dimension probe against the configured cloud embedder.
        Returns None when the endpoint is unreachable or misconfigured."""
        if not self._cloud_usable():
            return None
        base, model, key = _cloud_embed_config()
        try:
            resp = httpx.post(
                f"{base}/embeddings",
                json={"model": model, "input": "dim_probe"},
                headers={"Authorization": f"Bearer {key}"} if key else {},
                timeout=10,
            )
            if resp.status_code == 200:
                emb = _extract_cloud_embedding(resp.json())
                if emb:
                    return len(emb)
            else:
                logger.warning(
                    "[embed] cloud probe returned %s: %s", resp.status_code, resp.text[:100]
                )
        except Exception as exc:
            logger.warning("[embed] cloud probe failed: %s", exc)
        return None

    @staticmethod
    def _cloud_usable() -> bool:
        """True when a cloud embed backend is configured well enough to try:
        adapter selected, model named, and a key resolvable for the provider.
        A missing key would make every call 401, so binding would be pointless."""
        if settings.localmind_embed_adapter != "openai":
            return False
        base, model, key = _cloud_embed_config()
        if not model:
            logger.warning(
                "[embed] embed adapter 'openai' but no embed model configured — cloud skipped"
            )
            return False
        if not key:
            logger.warning(
                "[embed] no API key for embed provider %r — cloud skipped",
                settings.localmind_embed_key_provider,
            )
            return False
        return bool(base)

    def _fact_count(self, conn: sqlite3.Connection) -> int:
        try:
            return conn.execute("SELECT COUNT(*) FROM vector_facts").fetchone()[0]
        except Exception:
            return 0

    def _meta_get(self, conn: sqlite3.Connection, key: str) -> str | None:
        row = conn.execute("SELECT value FROM vector_meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def _bind_to_cloud(self, conn: sqlite3.Connection, stored_dim: int | None) -> bool:
        """
        Bind this store (and the process's shared embedding space) to the
        configured OpenAI-compatible cloud embedder.

        One vec0 index answers queries by comparing vectors, and vectors from
        different models are not comparable even at equal dimensions — so
        binding cloud is only safe when the index is empty, or when the index
        was already written by this same cloud backend (restart continuity:
        Ollama stays down across restarts, memory must not die with it).
        A populated Ollama-space index is never handed to a cloud backend;
        the store says so plainly and stays offline until the local embedder
        returns, instead of silently corrupting recall.

        Returns True when the bind succeeded (cloud backend live for this
        store's lifetime).
        """
        cloud_dim = self._probe_cloud_dim()
        if cloud_dim is None:
            logger.warning(
                "[embed] cloud embedder unreachable — memory stays offline as before"
            )
            return False

        base, model, _ = _cloud_embed_config()
        cloud_id = _backend_id("cloud", base, model)
        bound_id = self._meta_get(conn, "embed_backend_id")
        fact_count = self._fact_count(conn)

        if fact_count > 0 and bound_id != cloud_id:
            # The index holds vectors from another embedding space — an
            # Ollama-era DB (no recorded backend) or a different cloud model.
            # Comparing across spaces is silently meaningless, so refuse.
            logger.error(
                "[vector] index holds %d vectors written by backend %r — refusing "
                "to write it with %r (different embedding space). Memory stays "
                "offline until that backend is reachable again.",
                fact_count,
                bound_id or "ollama (pre-backend-tracking)",
                cloud_id,
            )
            return False
        if fact_count == 0 and stored_dim is not None and cloud_dim != stored_dim:
            # Empty index at a stale dimension — safe to re-key at the new
            # backend's dimension and rebuild the (empty) vec0 table.
            conn.execute("DROP TABLE IF EXISTS vector_embeddings")
            conn.execute(
                "INSERT OR REPLACE INTO vector_meta(key, value) VALUES ('dim', ?)",
                (str(cloud_dim),),
            )
            stored_dim = cloud_dim
        if stored_dim is not None and cloud_dim != stored_dim:
            logger.error(
                "[vector] DIM MISMATCH — DB has dim=%d but cloud embedder %s returns "
                "dim=%d. Refusing to bind: the existing index would be corrupted.",
                stored_dim,
                model,
                cloud_dim,
            )
            self._dim_mismatch = (stored_dim, cloud_dim)
            return False

        global _USE_CLOUD
        _USE_CLOUD = True
        conn.execute(
            "INSERT OR REPLACE INTO vector_meta(key, value) VALUES ('embed_backend_id', ?)",
            (cloud_id,),
        )
        effective_dim = stored_dim if stored_dim is not None else self._dim
        if effective_dim is None:
            # Fresh index — dim is recorded by _set_dim on first store; mark
            # ready exactly like the historical fresh-DB path does.
            self._ready = True
        else:
            self._dim = effective_dim
            self._ensure_vec_table(conn)
            self._ready = True
        conn.commit()
        logger.warning(
            "[vector] Ollama unavailable at startup — bound cloud embed backend "
            "(%s / %s) for this session. One embedding space, fixed at bind time.",
            base,
            model,
        )
        return True

    def _connect(self) -> sqlite3.Connection:
        return _get_connection(self._db_path)

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = self._connect()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vector_meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vector_facts (
                    id          TEXT PRIMARY KEY,
                    content     TEXT NOT NULL,
                    metadata    TEXT NOT NULL DEFAULT '{}',
                    created_at  REAL NOT NULL DEFAULT (unixepoch('now'))
                )
            """)
            # Tier-2 persistent embed cache — survives process restarts.
            # Maps sha256(norm_text) → packed float blob so re-ingesting the
            # same document never hits Ollama twice, even across restarts.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS embed_cache (
                    key  TEXT PRIMARY KEY,
                    vec  BLOB NOT NULL
                )
            """)
            conn.commit()
            row = conn.execute("SELECT value FROM vector_meta WHERE key = 'dim'").fetchone()
            stored_dim = int(row["value"]) if row else None

            # Restart continuity: an index already written by the currently
            # configured cloud backend stays on that backend — Ollama coming
            # and going must not flip the embedding space under a live index.
            cloud_bound = False
            if stored_dim is not None and self._cloud_usable():
                _base, _model, _key = _cloud_embed_config()
                if self._meta_get(conn, "embed_backend_id") == _backend_id("cloud", _base, _model):
                    cloud_bound = self._bind_to_cloud(conn, stored_dim)

            if not cloud_bound:
                # Probe actual embed dim synchronously (one cheap blocking call at startup)
                actual_dim = self._probe_embed_dim()
                if stored_dim is not None:
                    if actual_dim is not None and actual_dim != stored_dim:
                        logger.error(
                            "[vector] DIM MISMATCH — DB has dim=%d but %s now returns dim=%d. "
                            "Run: python scripts/reset_vector_db.py --yes",
                            stored_dim,
                            settings.ollama_embed_model,
                            actual_dim,
                        )
                        self._dim_mismatch = (stored_dim, actual_dim)
                        # Leave self._ready = False so callers get empty results,
                        # not a cryptic sqlite-vec error.  A configured cloud
                        # embedder may still keep memory alive — _bind_to_cloud
                        # applies the space guard itself (an index with facts
                        # from another backend is refused).
                        if not self._ready and self._cloud_usable():
                            cloud_bound = self._bind_to_cloud(conn, stored_dim)
                    else:
                        # A dim match is not a SPACE match: an index recorded
                        # as written by any cloud backend cannot be extended
                        # by Ollama's vectors even at equal dimensions.  (Only
                        # indexes created after backend-tracking exist, so
                        # legacy DBs — recorded None — keep working unchanged.)
                        recorded = self._meta_get(conn, "embed_backend_id")
                        ollama_id = _backend_id(
                            "ollama", self._base_url.rstrip("/"), settings.ollama_embed_model
                        )
                        if recorded is not None and recorded != ollama_id:
                            logger.error(
                                "[vector] index was written by backend %r — refusing "
                                "to extend it with a different embedding space. "
                                "Restore that backend or run scripts/reset_vector_db.py --yes",
                                recorded,
                            )
                            self._dim_mismatch = (stored_dim, stored_dim)
                        else:
                            self._dim = stored_dim
                            self._ensure_vec_table(conn)
                            self._ready = True
                            if actual_dim is None and self._cloud_usable():
                                # Ollama unreachable with an existing index — fail
                                # over to the configured cloud embedder for this
                                # session (one space, fixed at bind time).
                                cloud_bound = self._bind_to_cloud(conn, stored_dim)
                else:
                    # Fresh DB — no dim row yet.  Mark ready so the first store() call
                    # can flow through _persist → _set_dim which records the dim and
                    # creates vector_embeddings at the correct dimension.
                    self._ready = True
                    if actual_dim is None and self._cloud_usable():
                        # Ollama is not running and a cloud embedder is
                        # configured: bind it now so the very first fact a
                        # user stores succeeds instead of being silently
                        # dropped.
                        cloud_bound = self._bind_to_cloud(conn, None)
            logger.debug("VectorStore ready at %s (dim=%s)", self._db_path, self._dim)
        except Exception as exc:
            logger.error("VectorStore init failed: %s", exc)

    def _ensure_vec_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vector_embeddings
            USING vec0(embedding float[{self._dim}])
        """)
        conn.commit()

    def _set_dim(self, conn: sqlite3.Connection, dim: int) -> None:
        self._dim = dim
        conn.execute(
            "INSERT OR REPLACE INTO vector_meta(key, value) VALUES ('dim', ?)",
            (str(dim),),
        )
        # Record which backend wrote the first vector: the index holds exactly
        # one embedding space, and later restarts must not blend another
        # backend's vectors into it.
        mode, url, model, _ = _current_backend(self._base_url)
        conn.execute(
            "INSERT OR REPLACE INTO vector_meta(key, value) VALUES ('embed_backend_id', ?)",
            (_backend_id(mode, url, model),),
        )
        self._ensure_vec_table(conn)
        self._ready = True

    def _fact_id(self, fact: str) -> str:
        return hashlib.sha256(fact.encode()).hexdigest()[:16]

    # ── Tier-2 persistent embed cache ─────────────────────────────────────

    def _pkey(self, norm_text: str) -> str:
        # Namespaced by backend identity so a cloud vector can never be served
        # for an Ollama query (or vice-versa) out of the persistent tier.
        mode, url, model, _ = _current_backend(self._base_url)
        backend = _backend_id(mode, url, model)
        return hashlib.sha256(f"{backend}|{norm_text}".encode()).hexdigest()

    def _read_persistent(self, norm_text: str) -> list[float] | None:
        try:
            row = (
                self._connect()
                .execute("SELECT vec FROM embed_cache WHERE key = ?", (self._pkey(norm_text),))
                .fetchone()
            )
            if row:
                blob: bytes = row["vec"]
                _stats.persistent_hits += 1
                return list(struct.unpack(f"{len(blob) // 4}f", blob))
            _stats.persistent_misses += 1
            return None
        except Exception:
            return None

    def _write_persistent(self, norm_text: str, vec: list[float]) -> None:
        """
        Queue a (key, blob) pair for batched SQLite write.

        Called from run_in_executor (thread context) — must be thread-safe.
        Flushes the buffer synchronously when either threshold is hit so the
        caller's thread does the work rather than scheduling yet another task.
        """
        key = self._pkey(norm_text)
        blob = _pack(vec)

        with self._write_buf_lock:
            self._write_buf.append((key, blob))
            should_flush = (
                len(self._write_buf) >= _WRITE_BUFFER_FLUSH_EVERY
                or (time.monotonic() - self._write_buf_last_flush) >= _WRITE_BUFFER_FLUSH_SECS
            )
            if should_flush:
                self._flush_write_buf_locked()

    def _flush_write_buf_locked(self) -> None:
        """
        Flush _write_buf in a single transaction.  Caller MUST hold _write_buf_lock.
        Errors are swallowed — cache writes are never critical.
        """
        if not self._write_buf:
            return
        batch, self._write_buf = self._write_buf, []
        self._write_buf_last_flush = time.monotonic()
        try:
            conn = self._connect()
            # BEGIN IMMEDIATE for the same reason as _persist: a deferred BEGIN
            # that upgraded to a write after a stale read snapshot would fail
            # with SQLITE_BUSY under concurrent writers.
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany("INSERT OR IGNORE INTO embed_cache(key, vec) VALUES (?, ?)", batch)
            conn.execute("COMMIT")
            _stats.record_db_write((time.monotonic() - self._write_buf_last_flush) * 1000)
        except Exception as exc:
            logger.debug("embed_cache batch flush failed (non-critical): %s", exc)
            try:
                self._connect().execute("ROLLBACK")
            except Exception:
                pass

    def flush_write_buf(self) -> None:
        """
        Public flush — call from shutdown hooks to drain any pending writes.

            @app.on_event("shutdown")
            async def on_shutdown():
                vector_store.flush_write_buf()
        """
        with self._write_buf_lock:
            self._flush_write_buf_locked()

    async def _embed(self, text: str) -> list[float] | None:
        """
        Two-tier embed lookup — fully non-blocking:
          1. LRU (_embed_cached via executor) — fastest, in-process
          2. SQLite embed_cache              — persistent across restarts
          3. Ollama                          — real inference, written to both tiers

        IMPORTANT: _embed_cached must NEVER be called synchronously here.
        On an LRU miss it performs a blocking Ollama HTTP request, which
        would stall the event loop for the full round-trip (~200–500 ms).
        Always go through _embed_async which runs _embed_cached in the
        bounded ThreadPoolExecutor.  LRU hits inside the executor cost
        ~10 µs of thread-dispatch overhead — negligible.

        Tier ordering:
          SQLite is checked before dispatching to the executor because a
          SQLite hit (~1–5 ms) avoids the full Ollama call (~200–500 ms).
          The LRU is still checked first *inside* _embed_cached (which runs
          in the executor), so a warm LRU hit still wins — it just pays the
          ~10 µs executor-dispatch cost instead of zero.  That tradeoff is
          correct: blocking the event loop on a rare cold miss is far worse
          than 10 µs of overhead on every warm hit.
        """
        norm = _normalise_text(text)

        # Tier 2: SQLite persistent cache — avoids Ollama on restarts.
        # Checked before executor dispatch so a disk hit short-circuits the
        # thread-pool round-trip entirely.
        vec = self._read_persistent(norm)
        if vec is not None:
            return vec

        # Tier 1 + 3: LRU (instant if warm) → Ollama — both run in executor,
        # event loop never blocked regardless of cache state.
        # Semaphore caps concurrent executor dispatches to CPU count, preventing
        # queue runaway under bursts without ever blocking the event loop.
        async with self._embed_sem:
            vec_raw = await _embed_async(text, self._base_url)
        if vec_raw is None:
            return None
        vec = _normalise(vec_raw)

        # Write-back to persistent tier (fire-and-forget, never blocks caller)
        asyncio.get_running_loop().run_in_executor(None, self._write_persistent, norm, vec)
        return vec

    # ── Public API ─────────────────────────────────────────────────────────

    async def warmup(self) -> None:
        """
        Pre-warm the Ollama embedding model.

        Ollama lazy-loads models on first request — that initial call can block
        for 2–10 s while the model is paged into memory.  Call once from your
        FastAPI startup hook so the first real user query is never affected:

            @app.on_event("startup")
            async def on_startup():
                await engine.startup()
                await vector_store.warmup()
        """
        logger.info("[vector] warming up embedding model…")
        t0 = time.monotonic()
        vec = await _embed_async("warmup", self._base_url)
        ms = round((time.monotonic() - t0) * 1000)
        if vec:
            logger.info("[vector] embed model warm (%d ms, dim=%d)", ms, len(vec))
        else:
            logger.warning("[vector] warmup failed — is Ollama running?")

    async def store(
        self,
        fact: str,
        session_id: str,
        source: str = "user",
        extra_metadata: Optional[dict] = None,
    ) -> bool:
        """Embed + persist one fact.  Use store_batch() for bulk ingestion."""
        vec = await self._embed(fact)
        if vec is None:
            logger.warning("Embedding failed — fact not stored")
            return False
        if not _is_normalised(vec):
            vec = _normalise(vec)
        return (await self._persist([(fact, vec)], session_id, source, extra_metadata)) == 1

    async def store_batch(
        self,
        facts: list[str],
        session_id: str,
        source: str = "user",
        extra_metadata: Optional[dict] = None,
    ) -> int:
        """
        Embed + persist multiple facts in a single SQLite transaction.

        Concurrent embedding is semaphore-gated to prevent Ollama queue
        saturation.  All writes are batched under one BEGIN/COMMIT, which is
        significantly faster than per-fact commits (especially on WAL mode).

        Returns the number of facts successfully stored.
        """
        if not facts:
            return 0

        sem = asyncio.Semaphore(_BATCH_CONCURRENCY)

        async def _bounded(text: str) -> list[float] | None:
            t_wait = time.monotonic()
            async with sem:
                _stats.record_sem_wait((time.monotonic() - t_wait) * 1000)
                return await self._embed(text)

        vecs_raw = await asyncio.gather(*[_bounded(f) for f in facts])

        pairs: list[tuple[str, list[float]]] = []
        for fact, vec in zip(facts, vecs_raw):
            if vec is None:
                logger.warning("Embedding failed: %s…", fact[:40])
                continue
            pairs.append((fact, vec if _is_normalised(vec) else _normalise(vec)))

        return await self._persist(pairs, session_id, source, extra_metadata)

    async def _persist(
        self,
        pairs: list[tuple[str, list[float]]],
        session_id: str,
        source: str,
        extra_metadata: Optional[dict],
    ) -> int:
        """
        Write N (fact, normalised_vec) pairs in a single transaction.

        Single-transaction batching is the primary write-performance lever:
        one fsync per batch instead of one per fact.  At 50 facts/batch this
        is typically 10–30× faster than the original one-commit-per-store design.
        """
        if not pairs:
            return 0
        # Embedding-space guard: while a mismatch is recorded, writes would go
        # into an index that cannot serve them (or blend two incomparable
        # vector spaces) — refuse loudly instead of corrupting silently.
        if self._dim_mismatch is not None:
            logger.warning(
                "[vector] embedding-space guard active (stored dim=%d, active dim=%d) "
                "— write refused. Run: python scripts/reset_vector_db.py --yes",
                self._dim_mismatch[0],
                self._dim_mismatch[1],
            )
            return 0

        meta_base = {
            "session_id": session_id,
            "timestamp": str(time.time()),
            "source": source,
            "memory_type": "semantic",
        }
        if extra_metadata:
            meta_base.update(extra_metadata)

        t0 = time.monotonic()
        stored = 0
        conn = self._connect()
        try:
            if self._dim is None:
                self._set_dim(conn, len(pairs[0][1]))

            # BEGIN IMMEDIATE, not plain BEGIN: the dedup SELECT below takes a
            # WAL read snapshot, and a deferred BEGIN's upgrade to a write lock
            # FAILS INSTANTLY with "database is locked" (SQLITE_BUSY) if any
            # other connection commits in between — busy_timeout does not apply
            # to snapshot-upgrade. Taking the write lock up front makes the
            # transaction immune to the race (WAL still allows concurrent reads).
            conn.execute("BEGIN IMMEDIATE")
            for fact, vec in pairs:
                blob = _pack(vec)
                target_id = self._fact_id(fact)

                # Deduplication — reuses already-computed vec (no extra embed call)
                try:
                    for row in conn.execute(
                        """
                        SELECT vf.id, ve.distance
                        FROM vector_embeddings ve
                        JOIN vector_facts vf ON vf.rowid = ve.rowid
                        WHERE ve.embedding MATCH ? AND k = 3
                        ORDER BY ve.distance
                        """,
                        [blob],
                    ).fetchall():
                        # distance is vec0 L2, not a dot product — see _l2_to_score.
                        if _l2_to_score(row["distance"]) < 0.15:
                            target_id = row["id"]
                            logger.debug("[memory] dedup id=%s", target_id[:8])
                            break
                except Exception:
                    pass

                conn.execute(
                    """
                    INSERT INTO vector_facts(id, content, metadata)
                    VALUES (?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        content  = excluded.content,
                        metadata = excluded.metadata
                    """,
                    (target_id, fact, json.dumps(meta_base)),
                )
                rowid = conn.execute(
                    "SELECT rowid FROM vector_facts WHERE id = ?", (target_id,)
                ).fetchone()["rowid"]
                conn.execute("DELETE FROM vector_embeddings WHERE rowid = ?", (rowid,))
                conn.execute(
                    "INSERT INTO vector_embeddings(rowid, embedding) VALUES (?, ?)",
                    (rowid, blob),
                )
                stored += 1

            conn.execute("COMMIT")
            _stats.record_db_write((time.monotonic() - t0) * 1000)
        except Exception as exc:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            logger.error("Vector batch write failed: %s", exc)
            stored = 0

        return stored

    async def recall(self, query: str, top_k: int = 5) -> list[str]:
        results = await self.recall_with_scores(query=query, top_k=top_k)
        return [fact for fact, _, _ in results]

    async def recall_with_scores(
        self,
        query: str,
        top_k: int = 10,
        session_id: Optional[str] = None,
    ) -> list[tuple[str, float, dict]]:
        if not self._ready:
            return []
        vec_raw = await self._embed(query)
        if vec_raw is None:
            return []
        vec = vec_raw if _is_normalised(vec_raw) else _normalise(vec_raw)
        try:
            conn = self._connect()
            total = conn.execute("SELECT COUNT(*) FROM vector_facts").fetchone()[0]
            if total == 0:
                return []
            rows = conn.execute(
                """
                SELECT vf.id, vf.content, vf.metadata, ve.distance
                FROM vector_embeddings ve
                JOIN vector_facts vf ON vf.rowid = ve.rowid
                WHERE ve.embedding MATCH ? AND k = ?
                ORDER BY ve.distance
                """,
                [_pack(vec), min(top_k, total)],
            ).fetchall()
            results = []
            for row in rows:
                meta = json.loads(row["metadata"])
                if session_id and meta.get("session_id") != session_id:
                    continue
                meta["id"] = row["id"]
                # distance is vec0 L2, not a dot product — see _l2_to_score.
                results.append((row["content"], _l2_to_score(row["distance"]), meta))
            return results
        except Exception as exc:
            logger.error("recall_with_scores failed: %s", exc)
            return []

    async def forget(self, fact: str) -> bool:
        return await self.forget_by_id(self._fact_id(fact))

    async def forget_by_id(self, fact_id: str) -> bool:
        """Delete a fact by id. Returns True only if a row was actually
        removed — a missing id returns False so callers (the DELETE route's
        404, the agent's "couldn't find that fact") report truthfully instead
        of a silent success on nothing."""
        try:
            conn = self._connect()
            row = conn.execute("SELECT rowid FROM vector_facts WHERE id = ?", (fact_id,)).fetchone()
            if not row:
                return False
            conn.execute("DELETE FROM vector_embeddings WHERE rowid = ?", (row["rowid"],))
            conn.execute("DELETE FROM vector_facts WHERE id = ?", (fact_id,))
            conn.commit()
            return True
        except Exception as exc:
            logger.error("forget_by_id failed: %s", exc)
            return False

    async def update_content(self, fact_id: str, new_content: str) -> str | None:
        """Correct an existing fact's content (B-2026-08-23-14 follow-up).

        The fact id is derived from the content hash, so an edit re-embeds the
        corrected text and migrates the row to a NEW id while preserving the
        original metadata (source, timestamp, memory_type, importance). Returns
        the new fact id on success, None when the fact id doesn't exist, the
        content is empty, or the re-embed fails.
        """
        new_content = (new_content or "").strip()
        if not new_content:
            return None
        try:
            conn = self._connect()
            row = conn.execute(
                "SELECT metadata FROM vector_facts WHERE id = ?", (fact_id,)
            ).fetchone()
            if not row:
                return None
            try:
                meta = json.loads(row["metadata"]) or {}
            except (ValueError, TypeError):
                meta = {}

            vec = await self._embed(new_content)
            if vec is None:
                logger.warning("[memory] edit re-embed failed — fact not updated")
                return None
            if not _is_normalised(vec):
                vec = _normalise(vec)
            blob = _pack(vec)
            new_id = self._fact_id(new_content)

            conn.execute("BEGIN IMMEDIATE")
            try:
                old_row = conn.execute(
                    "SELECT rowid FROM vector_facts WHERE id = ?", (fact_id,)
                ).fetchone()
                if old_row:
                    conn.execute("DELETE FROM vector_embeddings WHERE rowid = ?", (old_row["rowid"],))
                    conn.execute("DELETE FROM vector_facts WHERE id = ?", (fact_id,))

                conn.execute(
                    "INSERT OR REPLACE INTO vector_facts(id, content, metadata) VALUES (?, ?, ?)",
                    (new_id, new_content, json.dumps(meta)),
                )
                rowid = conn.execute(
                    "SELECT rowid FROM vector_facts WHERE id = ?", (new_id,)
                ).fetchone()["rowid"]
                conn.execute("DELETE FROM vector_embeddings WHERE rowid = ?", (rowid,))
                conn.execute(
                    "INSERT INTO vector_embeddings(rowid, embedding) VALUES (?, ?)",
                    (rowid, blob),
                )
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            return new_id
        except Exception as exc:
            logger.error("update_content failed: %s", exc)
            return None

    async def list_all(self) -> list[str]:
        try:
            rows = (
                self._connect()
                .execute("SELECT content FROM vector_facts ORDER BY created_at")
                .fetchall()
            )
            return [r["content"] for r in rows]
        except Exception:
            return []

    async def list_all_with_metadata(self) -> list[dict]:
        try:
            rows = (
                self._connect()
                .execute("SELECT id, content, metadata FROM vector_facts ORDER BY created_at")
                .fetchall()
            )
            return [
                {"id": r["id"], "fact": r["content"], **json.loads(r["metadata"])} for r in rows
            ]
        except Exception:
            return []

    async def count(self) -> int:
        try:
            return self._connect().execute("SELECT COUNT(*) FROM vector_facts").fetchone()[0]
        except Exception:
            return 0

    async def update_metadata(self, fact_id: str, updates: dict) -> bool:
        try:
            conn = self._connect()
            row = conn.execute(
                "SELECT metadata FROM vector_facts WHERE id = ?", (fact_id,)
            ).fetchone()
            if not row:
                return False
            meta = json.loads(row["metadata"])
            meta.update(updates)
            conn.execute(
                "UPDATE vector_facts SET metadata = ? WHERE id = ?",
                (json.dumps(meta), fact_id),
            )
            conn.commit()
            return True
        except Exception as exc:
            logger.debug("update_metadata non-critical: %s", exc)
            return False

    # ── Observability ──────────────────────────────────────────────────────

    def metrics(self) -> VectorMetrics:
        """
        Structured snapshot of all performance counters.

        Integrate with core/metrics.py or log on a schedule:

            m = vector_store.metrics()
            total = max(1, m.lru_hits + m.lru_misses)
            logger.info(
                "[vector] cache=%.0f%% embed_p95=%.0fms db_write_p95=%.0fms workers=%d",
                100 * m.lru_hits / total,
                m.embed_p95_ms,
                m.db_write_p95_ms,
                m.active_workers,
            )
        """
        return VectorMetrics(**_stats.snapshot())

    @staticmethod
    def clear_embed_cache() -> None:
        """Evict LRU tier (call after switching embedding model)."""
        _embed_cached.cache_clear()

    @staticmethod
    def embed_cache_info() -> str:
        info = _embed_cached.cache_info()
        return (
            f"lru hits={info.hits} misses={info.misses} "
            f"size={info.currsize}/{info.maxsize} | "
            f"persistent hits={_stats.persistent_hits} misses={_stats.persistent_misses}"
        )
