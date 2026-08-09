"""
Tests for B-2026-08-09-9 — per-session `_process_lock` (was global).

Before this change, `Engine.process()` wrapped the ENTIRE stream in a single
global `asyncio.Lock`: while one request streamed (up to ~40s), any other
request on a DIFFERENT session (CLI ask/chat, ObjectiveRuntime turn) blocked
until the first finished. The engine's mutable state is keyed by session_id
(intent history, observations, pending writes, CWD), so only streams on the
SAME session actually need serialization.

These tests prove the new contract:
  - different sessions  → streams run CONCURRENTLY (no cross-session blocking)
  - same session        → streams still SERIALIZE (interleaved turns cannot
                          corrupt that session's history/observations)
  - the lock registry is bounded (session churn cannot grow it unbounded)
"""

from __future__ import annotations

import asyncio
import time
import unittest.mock as mock

import pytest
from core.models import StreamChunk


async def _slow_unlocked(**kwargs):
    """A stand-in for `Engine._process_unlocked` that takes ~0.3s per stream.

    Patching this method (rather than driving the real LLM pipeline) makes
    the timing deterministic: concurrency is measured purely on how long
    `process()` holds its stream lock.
    """
    yield StreamChunk(text="start", done=False)
    await asyncio.sleep(0.3)
    yield StreamChunk(text="", done=True)


async def _consume(agen) -> int:
    """Drain an engine stream, returning the number of done chunks seen."""
    return sum(1 for c in [x async for x in agen] if getattr(c, "done", False))


@pytest.fixture
def engine():
    from core.engine import Engine

    e = Engine()
    e._session_locks = {}
    return e


class TestPerSessionLock:
    @pytest.mark.asyncio
    async def test_different_sessions_stream_concurrently(self, engine):
        """Two streams on DIFFERENT sessions must not block each other."""
        with mock.patch.object(engine, "_process_unlocked", _slow_unlocked):
            t0 = time.monotonic()
            await asyncio.gather(
                _consume(engine.process("hello", "sess-conc-a")),
                _consume(engine.process("hello", "sess-conc-b")),
            )
            elapsed = time.monotonic() - t0

        # Concurrent: ~0.3s + startup overhead — NOT the ~0.6s serial time.
        assert elapsed < 0.55, (
            f"different-session streams blocked each other: {elapsed:.2f}s "
            f"(expected < 0.55s, saw serialized behavior)"
        )

    @pytest.mark.asyncio
    async def test_same_session_streams_serialize(self, engine):
        """Two streams on the SAME session must still run one after another."""
        with mock.patch.object(engine, "_process_unlocked", _slow_unlocked):
            t0 = time.monotonic()
            await asyncio.gather(
                _consume(engine.process("hello", "sess-serial")),
                _consume(engine.process("hello", "sess-serial")),
            )
            elapsed = time.monotonic() - t0

        # Serialized: two × ~0.3s = ~0.6s minimum.
        assert elapsed >= 0.55, (
            f"same-session streams ran concurrently: {elapsed:.2f}s "
            f"(expected >= 0.55s, saw interleaved behavior)"
        )

    @pytest.mark.asyncio
    async def test_each_session_gets_its_own_lock(self, engine):
        """Distinct session ids map to distinct lock objects; same id reuses one."""
        lock_a = engine._lock_for("sess-lock-a")
        lock_a_again = engine._lock_for("sess-lock-a")
        lock_b = engine._lock_for("sess-lock-b")

        assert lock_a is lock_a_again
        assert lock_a is not lock_b

    def test_lock_registry_is_bounded(self, engine):
        """Session churn must not grow the lock registry without bound."""
        for i in range(250):
            engine._lock_for(f"bound-{i}")
        assert len(engine._session_locks) <= 200

    def test_cleanup_session_removes_lock(self, engine):
        """Deleting a session also drops its stream lock from the registry."""
        engine._lock_for("sess-cleanup")
        assert "sess-cleanup" in engine._session_locks

        engine.cleanup_session("sess-cleanup")
        assert "sess-cleanup" not in engine._session_locks
