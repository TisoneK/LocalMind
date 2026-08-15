"""
Session 79: B-2026-08-02-5 (A5) — steering without aborting.

Today, redirecting a running agent requires abort + re-run. Steering lets
the user inject a message at the next step boundary: AgentLoop.run()
drains a per-session asyncio.Queue at each iteration top and the agent
sees the message as a new user prompt, continuing its turn.

Contract under test:
  1. A steering message queued mid-run is injected at the NEXT iteration
     boundary — never into the iteration whose model call is in flight
     (deferral), and never mid-tool.
  2. Steering messages are tagged {"steering": True} so compaction passes
     can identify them. They are user-role, so the A4 compactor
     (simplify_tool_results — tool-role only) never stubs them.
  3. Engine.steer() queues stripped messages, rejects blank ones, and
     returns False when the session queue is full (route maps to 409).
  4. POST /api/chat/{session_id}/steer accepts {"message": "..."} and
     returns 200 / 400 / 409 appropriately.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from adapters.ollama import ToolCallResult
from core.agent.loop import AgentLoop
from core.engine import Engine
from core.models import Intent, RiskLevel, StreamChunk, ToolResult


def _successful_dispatch() -> tuple:
    """A dispatched tool call that succeeds (mirrors other loop tests)."""
    return (ToolResult(content="OK", risk=RiskLevel.LOW, source="shell", success=True), False, 0)


async def _run_loop_with_steering(steering_queue: asyncio.Queue, seen: dict, steer_texts: list | None = None) -> list:
    """Run AgentLoop with a fake adapter through one tool call + final answer.

    steer_texts: messages queued during iteration 1's model call (i.e. after
    iteration 1's drain ran) — they must only be visible from iteration 2 on.
    """
    loop = AgentLoop(adapter=MagicMock())
    steer_texts = steer_texts or ["Actually, use grep instead of ls"]

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen.setdefault("calls", []).append([dict(m) for m in messages])
        call = len(seen["calls"])
        if call == 1:
            # Steering arrives MID-RUN: iteration 1's drain already ran, so
            # these messages are only visible to iteration 2.
            for _text in steer_texts:
                steering_queue.put_nowait({"role": "user", "content": _text})
            return ToolCallResult(
                tool_name="shell",
                tool_args={"command": "ls"},
                raw_content="Let me list the directory",
            )
        # Second call: the model streams a final answer.
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

    with patch("core.agent.loop.dispatch_with_retry", return_value=_successful_dispatch()), \
         patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
        chunks = []
        async for chunk in loop.run(
            messages=[{"role": "user", "content": "List files in the project"}],
            intent=Intent.SHELL,
            initial_tool_result=None,
            available_tools=[],
            adapter=mock_adapter,
            steering_queue=steering_queue,
        ):
            chunks.append(chunk)
    return chunks


class TestLoopSteering:
    """AgentLoop.run() drains the steering queue at iteration boundaries."""

    @pytest.mark.asyncio
    async def test_steering_message_injected_at_next_iteration(self):
        q: asyncio.Queue = asyncio.Queue()
        seen: dict = {}
        await _run_loop_with_steering(q, seen)

        # The loop must have made exactly 2 model calls (tool call, then answer).
        assert len(seen["calls"]) == 2, f"expected 2 model calls, got {len(seen['calls'])}"

        # Iteration 1 (the call whose model was in flight when steering
        # arrived) must NOT contain the steering text — deferred.
        iter1_texts = [m["content"] for m in seen["calls"][0] if m.get("role") == "user"]
        assert not any("use grep instead" in t for t in iter1_texts), (
            "steering message must NOT be injected into the in-flight iteration"
        )

        # Iteration 2 must contain it as a user message.
        iter2 = seen["calls"][1]
        steer_msgs = [
            m for m in iter2 if m.get("role") == "user" and "use grep instead" in m.get("content", "")
        ]
        assert steer_msgs, f"steering message missing from iteration 2 messages: {iter2!r}"

    @pytest.mark.asyncio
    async def test_multiple_steering_messages_all_drained_in_order(self):
        q: asyncio.Queue = asyncio.Queue()
        seen: dict = {}
        texts = ["first steer", "second steer"]
        await _run_loop_with_steering(q, seen, steer_texts=texts)

        iter2_user = [
            m["content"] for m in seen["calls"][1] if m.get("role") == "user"
        ]
        assert "first steer" in iter2_user
        assert "second steer" in iter2_user

    @pytest.mark.asyncio
    async def test_steering_message_is_tagged(self):
        q: asyncio.Queue = asyncio.Queue()
        seen: dict = {}
        await _run_loop_with_steering(q, seen)

        steer_msgs = [
            m
            for m in seen["calls"][1]
            if m.get("role") == "user" and "use grep instead" in m.get("content", "")
        ]
        assert steer_msgs[0].get("steering") is True, (
            "steering messages must be tagged {'steering': True} so compaction "
            "passes can identify them"
        )

    @pytest.mark.asyncio
    async def test_steering_message_survives_a4_compaction(self):
        """A4 (simplify_tool_results) only touches tool-role messages; a
        steering-tagged user message must pass through untouched."""
        from core.context_compactor import simplify_tool_results

        big = "x" * 2000
        messages = [
            {"role": "tool", "tool_call_id": "call_1", "content": big},
            {"role": "user", "content": "steer now", "steering": True},
        ]
        out = simplify_tool_results(messages)
        assert out[1] == messages[1], "steering user message must never be stubbed"


@pytest.fixture
def engine():
    e = Engine()
    e._steering_queues = {}
    return e


class TestEngineSteer:
    """Engine.steer() queue semantics."""

    def test_steer_queues_stripped_tagged_message(self, engine):
        assert engine.steer("sess-1", "  change direction  ") is True
        msg = engine._steering_queues["sess-1"].get_nowait()
        assert msg == {"role": "user", "content": "change direction", "steering": True}

    def test_steer_rejects_blank_message(self, engine):
        assert engine.steer("sess-2", "   ") is False
        assert "sess-2" not in engine._steering_queues

    def test_steer_queue_full_returns_false(self, engine):
        from core.agent_runtime import STEERING_QUEUE_MAX

        q = asyncio.Queue(maxsize=STEERING_QUEUE_MAX)
        engine._steering_queues["sess-3"] = q
        for i in range(STEERING_QUEUE_MAX):
            q.put_nowait({"role": "user", "content": f"m{i}"})
        assert engine.steer("sess-3", "one more") is False

    def test_steer_reuses_existing_queue(self, engine):
        engine.steer("sess-4", "first")
        engine.steer("sess-4", "second")
        q = engine._steering_queues["sess-4"]
        assert q.qsize() == 2


class TestSteerTurnSemantics:
    """Fresh queue per process() turn — stale steers never leak forward."""

    @pytest.mark.asyncio
    async def test_process_replaces_queue_dropping_stale_steers(self, engine):
        """A steer left over from a previous turn (e.g. queued during an
        earlier turn that didn't thread the queue) must be DROPPED when
        the next turn starts — not injected into it as the most-recent
        user message."""
        assert engine.steer("sess-turn", "stale instruction") is True
        stale_queue = engine._steering_queues["sess-turn"]
        assert stale_queue.qsize() == 1

        async def _stub_unlocked(**kwargs):
            current = engine._steering_queues.get(kwargs["session_id"])
            assert current is not stale_queue, "queue must be fresh per turn"
            assert current is not None and current.qsize() == 0, (
                "stale steer must be dropped, not carried into the new turn"
            )
            yield StreamChunk(text="ok", done=False)
            yield StreamChunk(text="", done=True)

        with patch.object(engine, "_process_unlocked", _stub_unlocked):
            async for _ in engine.process("hi", "sess-turn"):
                pass

    @pytest.mark.asyncio
    async def test_process_threads_same_queue_into_agent_loop(self, engine, monkeypatch, tmp_path):
        """The wiring link: the queue the steer route puts onto (via
        Engine.steer) must be the SAME queue threaded into AgentLoop.run —
        otherwise mid-turn steers never reach the model."""
        from core.config import settings

        monkeypatch.setattr(settings, "localmind_db_path", str(tmp_path / "test.db"))
        captured: dict = {}

        class _FakeLoop:
            async def run(self, **kwargs):
                captured["queue"] = kwargs.get("steering_queue")
                yield StreamChunk(text="done", done=True)

        engine._agent_loop = _FakeLoop()
        # Force the classic `self._agent_loop.run` branch (the ADR-8 agent
        # path constructs its own internal loop): disable agent selection
        # and the orchestrator routing.
        with patch.object(engine, "_agent_loop", engine._agent_loop):
            async for _ in engine.process(
                "list files",
                "sess-wire",
                client_intent="shell",
                client_confidence=1.0,
            ):
                pass

        session_queue = engine._steering_queues["sess-wire"]
        assert captured.get("queue") is session_queue, (
            "AgentLoop.run must receive the session's steering queue object"
        )
        # And a mid-run steer lands on that same queue.
        assert engine.steer("sess-wire", "now use grep") is True
        assert session_queue.qsize() == 1


@pytest.fixture
def client():
    from api.app import create_app

    return TestClient(create_app(), raise_server_exceptions=False)


class TestBaseAgentSteeringThreading:
    """The default ADR-8 execution path (BaseAgent.run → internal
    AgentLoop) must also receive the steering queue."""

    @pytest.mark.asyncio
    async def test_base_agent_threads_steering_queue_to_internal_loop(self):
        from agents import CodingAgent
        from core.models import Intent as I

        captured: dict = {}

        class _FakeLoop:
            def __init__(self, adapter=None):
                pass

            async def run(self, **kwargs):
                captured["queue"] = kwargs.get("steering_queue")
                yield StreamChunk(text="done", done=True)
                yield StreamChunk(text="", done=True)

        q: asyncio.Queue = asyncio.Queue()
        with patch("core.agent.loop.AgentLoop", _FakeLoop):
            async for _ in CodingAgent(adapter=None).run(
                messages=[{"role": "user", "content": "test"}],
                intent=I.SHELL,
                initial_tool_result=None,
                available_tools=[],
                steering_queue=q,
            ):
                pass

        assert captured.get("queue") is q, (
            "BaseAgent.run() must pass steering_queue through to AgentLoop.run()"
        )


class TestSteerRoute:
    """POST /api/chat/{session_id}/steer"""

    def test_steer_accepted(self, client):
        with patch("api.routes.chat._engine.steer", return_value=True) as m:
            r = client.post("/api/chat/sess-route-1/steer", json={"message": "go left"})
        assert r.status_code == 200
        assert r.json() == {"accepted": True}
        m.assert_called_once_with("sess-route-1", "go left")

    def test_steer_blank_rejected(self, client):
        with patch("api.routes.chat._engine.steer") as m:
            r = client.post("/api/chat/sess-route-2/steer", json={"message": "  "})
        assert r.status_code == 400
        m.assert_not_called()

    def test_steer_queue_full_returns_409(self, client):
        with patch("api.routes.chat._engine.steer", return_value=False):
            r = client.post("/api/chat/sess-route-3/steer", json={"message": "more!"})
        assert r.status_code == 409
