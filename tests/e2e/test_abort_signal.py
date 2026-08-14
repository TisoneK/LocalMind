"""
Session 80: B-2026-08-02-2 (A2) — abort signal threading.

Previously the UI could close the SSE stream but the backend AgentLoop kept
running until the wall-clock/iteration cap. This feature threads an
asyncio.Event through AgentLoop.run() / BaseAgent.run(); when set (via
POST /api/chat/{session_id}/abort, or client disconnect), the loop raises
AgentAbortedError at the next iteration boundary and the engine yields a
clean "⏹ Stopped by user." response.

Contract under test:
  1. AgentLoop.run() raises AgentAbortedError at the next iteration
     boundary when the event is set mid-run (never mid-tool).
  2. No abort → the loop completes normally (regression).
  3. Engine.abort() sets the session event; each process() turn starts
     with a FRESH (unset) event — a stale abort from an idle moment does
     not kill the next turn.
  4. The event threaded into AgentLoop.run is the same object the abort
     route sets; when the loop raises, process() yields "Stopped by user."
  5. POST /api/chat/{session_id}/abort returns 200 {"aborted": true}.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from adapters.ollama import ToolCallResult
from core.agent.loop import AgentLoop
from core.engine import Engine
from core.models import AgentAbortedError, Intent, RiskLevel, StreamChunk, ToolResult
from fastapi.testclient import TestClient


def _successful_dispatch() -> tuple:
    return (ToolResult(content="OK", risk=RiskLevel.LOW, source="shell", success=True), False, 0)


class TestLoopAbort:
    """AgentLoop.run() raises AgentAbortedError at iteration boundaries."""

    @pytest.mark.asyncio
    async def test_abort_raises_at_next_iteration_boundary(self):
        """Abort set mid-run (during iteration 1's model call) raises at
        iteration 2's top — never interrupting the in-flight tool work."""
        loop = AgentLoop(adapter=MagicMock())
        abort_signal = asyncio.Event()
        seen = {"call": 0}

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None):
            seen["call"] += 1
            if seen["call"] == 1:
                # Abort arrives after iteration 1's top-of-loop check.
                abort_signal.set()
                return ToolCallResult(
                    tool_name="shell",
                    tool_args={"command": "ls"},
                    raw_content="Let me list",
                )
            async def _stream():
                yield StreamChunk(text="Done.", done=False)
                yield StreamChunk(text="", done=True)
            return _stream()

        async def empty_chat(messages, temperature=0.4):
            return
            yield

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = empty_chat

        with patch("core.agent.loop.dispatch_with_retry", return_value=_successful_dispatch()), \
             patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
             patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
            with pytest.raises(AgentAbortedError):
                async for _ in loop.run(
                    messages=[{"role": "user", "content": "list files"}],
                    intent=Intent.SHELL,
                    initial_tool_result=None,
                    available_tools=[],
                    adapter=mock_adapter,
                    abort_signal=abort_signal,
                ):
                    pass

    @pytest.mark.asyncio
    async def test_abort_before_run_raises_at_planning_or_first_boundary(self):
        """An abort requested before the turn starts is honored immediately
        — at the planning-phase check when planning is enabled, else at
        iteration 1's boundary check."""
        loop = AgentLoop(adapter=MagicMock())
        abort_signal = asyncio.Event()
        abort_signal.set()  # set before run() starts

        async def empty_chat(messages, temperature=0.4):
            return
            yield

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = empty_chat
        mock_adapter.chat = empty_chat

        with pytest.raises(AgentAbortedError):
            async for _ in loop.run(
                messages=[{"role": "user", "content": "list files"}],
                intent=Intent.SHELL,
                initial_tool_result=None,
                available_tools=[],
                adapter=mock_adapter,
                abort_signal=abort_signal,
            ):
                pass

    @pytest.mark.asyncio
    async def test_no_abort_completes_normally(self):
        """Regression: without an abort the loop runs to a final answer."""
        loop = AgentLoop(adapter=MagicMock())
        seen = {"call": 0}

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None):
            seen["call"] += 1
            if seen["call"] == 1:
                return ToolCallResult(
                    tool_name="shell",
                    tool_args={"command": "ls"},
                    raw_content="Let me list",
                )
            async def _stream():
                yield StreamChunk(text="Done with the task.", done=False)
                yield StreamChunk(text="", done=True)
            return _stream()

        async def empty_chat(messages, temperature=0.4):
            return
            yield

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = empty_chat

        chunks = []
        with patch("core.agent.loop.dispatch_with_retry", return_value=_successful_dispatch()), \
             patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
             patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
            async for chunk in loop.run(
                messages=[{"role": "user", "content": "list files"}],
                intent=Intent.SHELL,
                initial_tool_result=None,
                available_tools=[],
                adapter=mock_adapter,
            ):
                chunks.append(chunk)

        full = "".join(c.text for c in chunks)
        assert "Done with the task." in full


@pytest.fixture
def engine():
    e = Engine()
    e._abort_events = {}
    return e


class TestEngineAbort:
    """Engine.abort() + fresh-event-per-turn semantics."""

    def test_abort_sets_session_event(self, engine):
        assert engine.abort("sess-1") is True
        assert engine._abort_events["sess-1"].is_set()

    @pytest.mark.asyncio
    async def test_fresh_unset_event_per_turn(self, engine):
        """A stale abort from an idle moment must NOT kill the next turn —
        process() replaces the event with a fresh (unset) one."""
        assert engine.abort("sess-2") is True
        stale = engine._abort_events["sess-2"]
        assert stale.is_set()

        async def _stub_unlocked(**kwargs):
            current = engine._abort_events.get(kwargs["session_id"])
            assert current is not None, "process() must create a fresh event"
            assert current is not stale, "event must be fresh per turn"
            assert not current.is_set(), "stale abort must not carry into the new turn"
            yield StreamChunk(text="ok", done=True)

        with patch.object(engine, "_process_unlocked", _stub_unlocked):
            async for _ in engine.process("hi", "sess-2"):
                pass

    @pytest.mark.asyncio
    async def test_process_threads_same_event_and_yields_stopped(self, engine, monkeypatch, tmp_path):
        """The event threaded into AgentLoop.run is the one the abort route
        sets; when the loop raises AgentAbortedError, process() yields a
        clean 'Stopped by user.' chunk."""
        from core.config import settings

        monkeypatch.setattr(settings, "localmind_db_path", str(tmp_path / "test.db"))
        captured: dict = {}

        class _FakeLoop:
            async def run(self, **kwargs):
                captured["event"] = kwargs.get("abort_signal")
                raise AgentAbortedError("aborted")
                yield  # pragma: no cover — makes this an async generator

        engine._agent_loop = _FakeLoop()
        with patch.object(engine, "_agent_loop", engine._agent_loop):
            chunks = [
                c
                async for c in engine.process(
                    "list files",
                    "sess-abort-wire",
                    client_intent="shell",
                    client_confidence=1.0,
                )
            ]

        session_event = engine._abort_events["sess-abort-wire"]
        assert captured.get("event") is session_event, (
            "AgentLoop.run must receive the session's abort event object"
        )
        assert engine.abort("sess-abort-wire") is True
        assert session_event.is_set()
        texts = "".join(c.text for c in chunks)
        assert "Stopped by user" in texts, (
            f"process() must yield the stopped marker on AgentAbortedError, got {texts!r}"
        )


@pytest.fixture
def client():
    from api.app import create_app

    return TestClient(create_app(), raise_server_exceptions=False)


class TestAbortRoute:
    """POST /api/chat/{session_id}/abort"""

    def test_abort_returns_200(self, client):
        with patch("api.routes.chat._engine.abort", return_value=True) as m:
            r = client.post("/api/chat/sess-abort-route/abort")
        assert r.status_code == 200
        assert r.json() == {"aborted": True}
        m.assert_called_once_with("sess-abort-route")
