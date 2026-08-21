"""
Tests for B-2026-08-09-5 / ADR-12 — trivial + conversational short-circuits
emit turn_complete and store a per-session observation.

Before this fix, a "Hi" turn streamed its reply but emitted only
`trivial_short_circuit`/`_done` — no `turn_complete`, no `_store_observation`.
The Observe panel showed nothing for conversational turns, and
/api/observability/{session} fell back to a session-AGNOSTIC MetricsStore
aggregate that could show ANOTHER session's intent/latency.

These tests lock in: every short-circuit turn emits a real `turn_complete`
(so the SSE `metrics` event + per-message metrics work) and writes
`_last_observation[session_id]` so the polling endpoint returns truthful
per-session data.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.obs import ObsCollector


async def _mock_chat(text: str):
    """Adapter.chat fake yielding one content chunk + a done marker."""

    async def chat(messages, intent="chat", **kwargs):
        yield MagicMock(text=text, done=False, error=None)
        yield MagicMock(text="", done=True, error=None)

    return chat


@pytest.fixture
def isolated_engine():
    """A real Engine with an empty observation cache (isolated from other tests)."""
    from core.engine import Engine

    engine = Engine()
    engine._last_observation = {}
    return engine


class TestTrivialTurnComplete:
    @pytest.mark.asyncio
    async def test_trivial_turn_emits_turn_complete_and_stores_observation(self, isolated_engine):
        engine = isolated_engine
        obs = ObsCollector()
        mock_adapter = MagicMock()
        mock_adapter.chat = await _mock_chat("Hi! How can I help?")

        with patch("core.engine.get_adapter", return_value=mock_adapter):
            chunks = [c async for c in engine.process("hi", "sess-tc-trivial", obs=obs)]

        assert any(getattr(c, "done", False) for c in chunks)

        completes = [e for e in obs.history() if e.type == "turn_complete"]
        assert len(completes) == 1
        data = completes[0].data
        # Session 332-C: trivial turns now use the fast-path (canned reply,
        # zero LLM calls). intent="chat" reflects that the parent agent did
        # NOT run. agent_mode=False because no parent-agent loop executed.
        assert data["intent"] == "chat"
        assert data["tokens_approx"] > 0
        assert data["total_latency_ms"] >= 0
        assert data["agent_mode"] is False

        stored = engine._last_observation.get("sess-tc-trivial")
        assert stored is not None
        assert stored["intent"] == "chat"
        assert stored["tools_used"] == ""
        assert stored["latency_ms"] >= 0
        # The stage clock marked tool_select/execute skipped — the stored
        # snapshot must carry them so the polling panel is truthful too.
        assert stored["stage_timings"]["tool_select"]["status"] == "skipped"
        assert stored["stage_timings"]["execute"]["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_conversational_question_emits_turn_complete_and_stores_observation(self, isolated_engine):
        engine = isolated_engine
        obs = ObsCollector()
        mock_adapter = MagicMock()
        mock_adapter.chat = await _mock_chat("I can help with code, files, and more!")

        with patch("core.engine.get_adapter", return_value=mock_adapter):
            chunks = [c async for c in engine.process("What can you do?", "sess-tc-conv", obs=obs)]

        assert any(getattr(c, "done", False) for c in chunks)

        completes = [e for e in obs.history() if e.type == "turn_complete"]
        assert len(completes) == 1
        data = completes[0].data
        # Session 332-C: conversational questions use the fast-path (one direct
        # chat call, no parent-agent loop). intent="chat" reflects that.
        assert data["intent"] == "chat"
        assert data["tokens_approx"] > 0
        assert data["total_latency_ms"] >= 0

        stored = engine._last_observation.get("sess-tc-conv")
        assert stored is not None
        assert stored["intent"] == "chat"
        assert stored["tools_used"] == ""


class TestShortCircuitCleanupSafety:
    """The turn_complete + store work is best-effort — it must never prevent
    the short-circuit return (which would duplicate the response)."""

    @pytest.mark.asyncio
    async def test_trivial_cleanup_failure_still_returns(self, isolated_engine):
        engine = isolated_engine
        obs = ObsCollector()
        mock_adapter = MagicMock()
        mock_adapter.chat = await _mock_chat("Hi there!")

        with (
            patch("core.engine.get_adapter", return_value=mock_adapter),
            patch.object(engine, "_persist_user_message", side_effect=RuntimeError("disk full")),
        ):
            chunks = [c async for c in engine.process("hello", "sess-tc-safe", obs=obs)]

        # The stream still completed exactly once — no duplicate, no crash.
        assert any(getattr(c, "done", False) for c in chunks)
        assert sum(1 for c in chunks if getattr(c, "done", False)) == 1
