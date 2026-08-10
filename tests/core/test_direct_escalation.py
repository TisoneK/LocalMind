"""
Regression test for Session 127 fix #4 — DIRECT-path DSML escalation.

When the ThinkingDispatcher times out (free-tier overload) it falls back to
ExecutionMode.DIRECT — a no-tools conversational fast-path that streams
adapter.chat() directly. If the model still wants a tool, it emits DeepSeek
DSML / MiniMax XML as text, which previously streamed RAW as the final answer
(no interception, tool never ran).

Fix: the DIRECT streaming loop buffers text; on tool-call XML detection it
drains the stream and escalates to the agent loop (which has the DSML/MiniMax
interception from the same session), so the tool actually executes.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.models import ExecutionMode, OrchestrationPlan, TaskProfile
from core.obs import ObsCollector

_DSML = (
    "<｜DSML｜tool_calls>\n"
    '<｜DSML｜invoke name="shell">\n'
    '<｜DSML｜parameter name="command" string="true">ls -la</｜DSML｜parameter>\n'
    "</｜DSML｜invoke>\n"
    "</｜DSML｜tool_calls>"
)


class _DirectPlanDispatcher:
    """Dispatcher stub that returns a DIRECT (no-tools) plan immediately."""

    def __init__(self, adapter):
        self._adapter = adapter

    async def dispatch(self, **kwargs):
        yield OrchestrationPlan(
            profile=TaskProfile(
                capabilities=[],
                execution_mode=ExecutionMode.DIRECT,
                confidence=0.5,
                reformulated=kwargs.get("message", ""),
            )
        )


def _make_dsml_adapter():
    """Adapter whose chat() emits DSML (then ends)."""
    mock_adapter = MagicMock()

    async def chat(messages, intent="chat", **kwargs):
        yield MagicMock(text=_DSML, done=False, error=None, usage={})
        yield MagicMock(text="", done=True, error=None, usage={})

    mock_adapter.chat = chat
    mock_adapter.effective_context_window = 8192
    return mock_adapter


@pytest.mark.asyncio
async def test_direct_dsml_escalates_to_agent_loop(monkeypatch):
    """A DIRECT stream emitting DSML must escalate to the agent loop, not
    stream the raw XML as the final answer."""
    from core.engine import Engine

    engine = Engine()
    obs = ObsCollector()
    mock_adapter = _make_dsml_adapter()

    # Record the agent-loop invocation to prove escalation happened.
    escalated_intents: list = []

    async def fake_agent_run(**kwargs):
        escalated_intents.append(kwargs.get("intent"))
        from core.models import StreamChunk

        yield StreamChunk(text="Running ls -la for you...", done=False, usage={})
        yield StreamChunk(text="", done=True, usage={})

    # Patch the three moving parts: dispatcher (DIRECT plan), adapter
    # (DSML stream), and the agent loop (records + answers).
    with patch("core.engine._pipeline.ThinkingDispatcher", _DirectPlanDispatcher), patch(
        "core.engine.get_adapter", return_value=mock_adapter
    ), patch.object(engine._agent_loop, "run", fake_agent_run):
        chunks = [
            c
            async for c in engine.process(
                "create hello world repo", "sess-direct-dsml", obs=obs
            )
        ]

    # The raw DSML must NOT be in the user-facing answer.
    full_text = "".join(getattr(c, "text", "") or "" for c in chunks)
    assert "｜DSML｜" not in full_text
    assert "invoke name" not in full_text
    assert "Running ls -la for you..." in full_text

    # Escalation happened with a tool-capable intent (shell → SHELL).
    assert escalated_intents, "agent loop was never invoked on DSML detection"
    assert escalated_intents[0] == "shell"

    # Obs records the escalation event.
    events = [e for e in obs.history() if e.type == "direct_escalate_agent"]
    assert len(events) == 1
    assert events[0].data["tool"] == "shell"


@pytest.mark.asyncio
async def test_direct_plain_text_does_not_escalate(monkeypatch):
    """A normal conversational DIRECT stream must NOT trigger escalation —
    the fast path stays fast for genuine conversation."""
    from core.engine import Engine

    engine = Engine()
    obs = ObsCollector()
    mock_adapter = MagicMock()

    async def chat(messages, intent="chat", **kwargs):
        yield MagicMock(text="Hello there!", done=False, error=None, usage={})
        yield MagicMock(text="", done=True, error=None, usage={})

    mock_adapter.chat = chat
    mock_adapter.effective_context_window = 8192

    agent_called = False

    async def fake_agent_run(**kwargs):
        nonlocal agent_called
        agent_called = True
        yield MagicMock(text="", done=True, error=None, usage={})

    with patch("core.engine._pipeline.ThinkingDispatcher", _DirectPlanDispatcher), patch(
        "core.engine.get_adapter", return_value=mock_adapter
    ), patch.object(engine._agent_loop, "run", fake_agent_run):
        chunks = [
            c
            async for c in engine.process("hello", "sess-direct-plain", obs=obs)
        ]

    full_text = "".join(getattr(c, "text", "") or "" for c in chunks)
    assert "Hello there!" in full_text
    assert agent_called is False, "plain conversational DIRECT turn must not escalate"
