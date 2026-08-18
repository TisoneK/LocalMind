"""
E2E + unit coverage for the progress nudge (B-2026-08-18-3).

The transcript that motivated it: "current weather Kitengela" made the model run
3 `web_search` calls that all SUCCEEDED (returned results) but were useless, then
return an empty synthesis. `same_tool_failure_streak` never caught it (nothing
failed). The loop now nudges ONCE after N consecutive same-tool calls to change
approach or answer with what it has.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from adapters.ollama import ToolCallResult
from core.agent.loop import (
    _SAME_TOOL_REPETITION_NUDGE_CAP,
    AgentLoop,
    same_tool_repetition_streak,
)
from core.agent.models import AgentStep, AgentTrace
from core.models import Intent, RiskLevel, StreamChunk, ToolResult


# ── unit: same_tool_repetition_streak ────────────────────────────────────────


def _trace(*tools):
    t = AgentTrace()
    for i, name in enumerate(tools):
        t.steps.append(AgentStep(iteration=i, thought="", tool_name=name, tool_input="", observation="ok"))
    return t


def test_streak_counts_consecutive_same_tool_regardless_of_success():
    assert same_tool_repetition_streak(_trace("web_search", "web_search", "web_search")) == (3, "web_search")


def test_a_different_tool_breaks_the_streak():
    # last run is a single file_write after web_searches → streak 1
    assert same_tool_repetition_streak(_trace("web_search", "web_search", "file_write")) == (1, "file_write")


def test_toolless_step_does_not_break_streak():
    t = _trace("shell", "shell")
    t.steps.append(AgentStep(iteration=9, thought="thinking", tool_name=None, tool_input="", observation=""))
    assert same_tool_repetition_streak(t) == (2, "shell")


def test_empty_trace_is_zero():
    assert same_tool_repetition_streak(AgentTrace()) == (0, "")


# ── e2e: the nudge fires through the real loop ───────────────────────────────


def _ok_dispatch():
    return (ToolResult(content="Search results (8)", risk=RiskLevel.LOW, source="web_search", success=True), False, 0)


async def _run_loop_repeating_tool(seen: dict, *, tool="web_search", repeats=3):
    """Drive AgentLoop with an adapter that calls the same tool `repeats` times
    (different args each time, so the exact-match dedup doesn't short-circuit),
    then streams a final answer."""
    loop = AgentLoop(adapter=MagicMock())

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen.setdefault("calls", []).append([dict(m) for m in messages])
        call = len(seen["calls"])
        if call <= repeats:
            return ToolCallResult(
                tool_name=tool,
                tool_args={"query": f"weather query variant {call}"},
                raw_content=f"searching (attempt {call})",
            )

        async def _stream():
            yield StreamChunk(text="Best answer from what I found.", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()

    async def empty_chat(messages, temperature=0.4):
        return
        yield

    mock_adapter = MagicMock()
    mock_adapter.chat_with_tools = chat_with_tools
    mock_adapter.chat = empty_chat

    with patch("core.agent.loop.dispatch_with_retry", return_value=_ok_dispatch()), \
         patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
        async for _chunk in loop.run(
            messages=[{"role": "user", "content": "What's the weather in Kitengela?"}],
            intent=Intent.WEB_SEARCH,
            initial_tool_result=None,
            available_tools=[],
            adapter=mock_adapter,
        ):
            pass


@pytest.mark.asyncio
async def test_progress_nudge_injected_after_repeated_same_tool():
    seen: dict = {}
    await _run_loop_repeating_tool(seen, repeats=_SAME_TOOL_REPETITION_NUDGE_CAP)

    calls = seen["calls"]
    # The model was called (cap) times for the tool + at least one more for the
    # final answer.
    assert len(calls) >= _SAME_TOOL_REPETITION_NUDGE_CAP + 1

    def _has_nudge(msgs):
        return any(
            m.get("role") == "user" and "[PROGRESS CHECK]" in m.get("content", "")
            for m in msgs
        )

    # The nudge must NOT appear before the streak is reached...
    assert not _has_nudge(calls[0]), "nudge fired too early (before any repetition)"
    # ...but MUST appear on the model call after the cap-th consecutive same-tool call.
    assert _has_nudge(calls[_SAME_TOOL_REPETITION_NUDGE_CAP]), "progress nudge was not injected after the streak"
    # And it fires only ONCE per turn (not on every later call).
    nudge_calls = sum(1 for c in calls if _has_nudge(c))
    assert nudge_calls == 1, f"nudge should fire exactly once, fired on {nudge_calls} calls"


@pytest.mark.asyncio
async def test_no_nudge_when_tool_not_repeated_enough():
    """Below the cap → no nudge (legitimate short tool use is not disturbed)."""
    seen: dict = {}
    await _run_loop_repeating_tool(seen, repeats=_SAME_TOOL_REPETITION_NUDGE_CAP - 1)

    for msgs in seen["calls"]:
        assert not any(
            "[PROGRESS CHECK]" in m.get("content", "") for m in msgs
        ), "nudge should not fire below the repetition cap"
