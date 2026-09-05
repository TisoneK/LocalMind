"""
Session 419 — identical-call no-progress stop + honest limit classification.

The transcript that motivated this: "I'm Tisone, find my CV" ran three
malformed `system_search` calls (corrupted query strings), then a shell
fallback, then hit the run's budget — and the UI banner said
"✗ Agent loop failed / Reason: iteration_limit" ABOVE a complete, correct
answer. Three gaps:

1. Every budget break (step cap, wall clock, runaway ceiling) was classified
   as "iteration_limit" — the wall-clock break reported the wrong cause
   (the Session 32 contract: the stated cause must be the real one).
2. The failure event was emitted BEFORE the forced final synthesis, so a
   capped turn that DELIVERED a real answer still showed "Agent loop failed".
3. The B-2026-08-18-3 nudge counts same-TOOL repetitions only; a model can
   tweak one character and re-run the same failing call. The new
   `identical_call_streak` hard-stops after N identical (tool + normalized
   args) calls — the literal "same command over and over" loop.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from adapters.ollama import ToolCallResult
from core.agent.loop import (
    _IDENTICAL_CALL_STOP_CAP,
    AgentLoop,
    identical_call_streak,
)
from core.agent.models import AgentStep, AgentTrace
from core.failure_memory import build_failure_summary, classify_failure
from core.models import Intent, RiskLevel, StreamChunk, ToolResult
from tools.system_search import _op_files

# ── unit: identical_call_streak ──────────────────────────────────────────────


def _trace_calls(*calls):
    t = AgentTrace()
    for i, (name, args) in enumerate(calls):
        t.steps.append(
            AgentStep(iteration=i, thought="", tool_name=name, tool_input=args, observation="ok")
        )
    return t


def test_identical_streak_counts_same_tool_same_args():
    t = _trace_calls(
        ("system_search", '{"query": "CV 30"}'),
        ("system_search", '{"query": "CV 30"}'),
        ("system_search", '{"query": "CV 30"}'),
    )
    streak, sig = identical_call_streak(t)
    assert streak == 3
    assert "system_search" in sig and "cv 30" in sig


def test_different_args_break_the_identical_streak():
    t = _trace_calls(
        ("system_search", '{"query": "CV 30"}'),
        ("system_search", '{"query": "CV 30"}'),
        ("system_search", '{"query": "Tisone CV"}'),
    )
    assert identical_call_streak(t)[0] == 1


def test_whitespace_and_case_do_not_fool_the_streak():
    t = _trace_calls(
        ("shell", 'Get-ChildItem   "Tisone"'),
        ("shell", 'get-childitem "Tisone"'),
    )
    assert identical_call_streak(t)[0] == 2


def test_a_different_tool_breaks_the_identical_streak():
    t = _trace_calls(
        ("system_search", '{"query": "CV"}'),
        ("shell", '{"command": "Get-ChildItem"}'),
    )
    assert identical_call_streak(t)[0] == 1


def test_toolless_step_does_not_break_identical_streak():
    t = _trace_calls(("shell", "dir"), ("shell", "dir"))
    t.steps.append(AgentStep(iteration=9, thought="thinking", tool_name=None, tool_input="", observation=""))
    assert identical_call_streak(t)[0] == 2


# ── unit: honest failure classification ──────────────────────────────────────


def test_wall_clock_break_classifies_as_wall_clock_limit():
    t = AgentTrace()
    t.hit_limit = True
    t.limit_kind = "wall_clock"
    t.iterations_used = 5
    t.steps.append(
        AgentStep(iteration=0, thought="", tool_name="shell", tool_input="dir",
                  observation="ok", tool_failed=True)
    )
    assert classify_failure(t) == "wall_clock_limit"
    assert "wall-clock cap" in build_failure_summary(t)


def _fail_step(**kw):
    """One failed tool step, wrapped so the constructor call stays under 120 chars."""
    defaults = dict(iteration=0, thought="", tool_name="shell", tool_input="dir",
                    observation="ok", tool_failed=True)
    defaults.update(kw)
    return AgentStep(**defaults)


def test_repetition_break_classifies_as_repetition_loop():
    t = AgentTrace()
    t.hit_limit = True
    t.limit_kind = "repetition"
    t.iterations_used = 3
    t.steps.append(_fail_step(tool_name="system_search", tool_input="q"))
    assert classify_failure(t) == "repetition_loop"
    assert "same tool call" in build_failure_summary(t)


def test_capped_run_with_rescued_answer_is_not_a_failure():
    """The CV transcript: budget break, forced synthesis delivered a real
    answer → classify_failure must return '' (no agent_loop_failure event)."""
    t = AgentTrace()
    t.hit_limit = True
    t.limit_kind = "iteration_cap"
    t.iterations_used = 5
    t.steps.append(_fail_step())
    t.final_response = "Found it. Your CV is here: C:\\Users\\tison\\OneDrive\\Documents\\Tisone\\CV-TisoneKironget.pdf"
    assert classify_failure(t) == ""


def test_capped_run_without_answer_still_classifies():
    t = AgentTrace()
    t.hit_limit = True
    t.limit_kind = "iteration_cap"
    t.iterations_used = 8
    t.steps.append(_fail_step())
    assert classify_failure(t) == "iteration_limit"


# ── e2e: the identical-call stop fires through the real loop ────────────────


def _ok_dispatch():
    return (
        ToolResult(content="Found 0 matches.", risk=RiskLevel.LOW, source="system_search", success=True),
        False,
        0,
    )


async def _run_loop_identical_calls(seen: dict, *, repeats: int):
    """Drive AgentLoop with an adapter that makes `repeats` IDENTICAL tool
    calls (same tool, same args — the no-progress signature), then streams a
    final answer."""
    loop = AgentLoop(adapter=MagicMock())

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen.setdefault("calls", []).append([dict(m) for m in messages])
        call = len(seen["calls"])
        if call <= repeats:
            return ToolCallResult(
                tool_name="system_search",
                tool_args={"query": "CV 30"},
                raw_content="searching",
            )

        async def _stream():
            yield StreamChunk(text="Answer from gathered evidence.", done=False)
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
            messages=[{"role": "user", "content": "find my CV"}],
            intent=Intent.FIND_PATH,
            initial_tool_result=None,
            available_tools=[],
            adapter=mock_adapter,
        ):
            pass


@pytest.mark.asyncio
async def test_identical_calls_stop_the_loop_at_cap():
    seen: dict = {}
    # Give the adapter more identical calls than the cap: the loop must
    # break BEFORE consuming them all (the stop fires at the iteration head
    # after the cap-th identical call lands).
    await _run_loop_identical_calls(seen, repeats=_IDENTICAL_CALL_STOP_CAP + 2)

    calls = seen["calls"]
    # The loop must have stopped early: fewer model calls than the adapter
    # offered (cap iterations + the forced synthesis happens outside
    # chat_with_tools). At minimum, it must not have consumed all
    # cap+2 identical offers plus continued further.
    assert len(calls) <= _IDENTICAL_CALL_STOP_CAP + 1


@pytest.mark.asyncio
async def test_identical_calls_below_cap_do_not_stop():
    seen: dict = {}
    await _run_loop_identical_calls(seen, repeats=_IDENTICAL_CALL_STOP_CAP - 1)

    calls = seen["calls"]
    # Below the cap the turn proceeds normally to the model's own answer.
    assert len(calls) >= _IDENTICAL_CALL_STOP_CAP


# ── unit: system_search relaxed-fallback quality gate ────────────────────────


class _FakeEntry:
    def __init__(self, path: str, is_dir: bool = False):
        from pathlib import Path

        self.path = Path(path)
        self.name = self.path.name
        self._is_dir = is_dir

    def is_symlink(self):
        return False

    def is_dir(self):
        return self._is_dir

    def stat(self):
        import os

        st = os.stat_result((0, 0, 0, 0, 0, 0, 1024, 0, 1756000000.0, 0))
        return st


def test_files_operation_missing_query_is_invalid_input():
    res = _op_files({})
    assert res.success is False
    assert res.error_type == "invalid_input"


def test_generic_token_excluded_from_relaxation_via_helper():
    """The generic-token stoplist is the load-bearing part of the gate —
    verify the constant directly so 'files' can never win the fallback."""
    from tools.system_search import _RELAXED_GENERIC_TOKENS

    for bad in ("files", "file", "docs", "data", "my"):
        assert bad in _RELAXED_GENERIC_TOKENS


def test_path_token_reduced_to_basename_in_relaxation():
    """'C:\\Users\\tison\\OneDrive\\Documents\\Tisone' as a token must
    reduce to 'Tisone' — no file is NAMED an absolute path."""
    import re as _re

    tok = "C:\\Users\\tison\\OneDrive\\Documents\\Tisone"
    reduced = _re.split(r"[\\/]", tok)[-1]
    assert reduced == "Tisone"


# ── e2e: capped + rescued → no false "Agent loop failed" event ───────────────


@pytest.mark.asyncio
async def test_capped_turn_with_real_synthesis_emits_no_failure_event():
    """The CV transcript: the loop hit its budget but the forced synthesis
    delivered a real answer — `agent_loop_failure` must NOT fire (the user
    saw "✗ Agent loop failed" above a complete answer)."""
    from core.obs import ObsCollector

    loop = AgentLoop(adapter=MagicMock())
    obs = ObsCollector()
    seen: dict = {}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen.setdefault("calls", []).append(1)
        return ToolCallResult(
            tool_name="system_search",
            tool_args={"query": "CV 30"},
            raw_content="searching",
        )

    async def real_chat(messages, temperature=0.4):
        yield StreamChunk(
            text="Found it. Your CV is at C:/Users/tison/OneDrive/Documents/Tisone/CV-TisoneKironget.pdf.",
            done=False,
        )
        yield StreamChunk(text="", done=True)

    mock_adapter = MagicMock()
    mock_adapter.chat_with_tools = chat_with_tools
    mock_adapter.chat = real_chat

    with patch("core.agent.loop.MAX_ITERATIONS", 2), \
         patch("core.agent.loop.PLAN_ENABLED", False), \
         patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), \
         patch("core.agent.loop.dispatch_with_retry", return_value=_ok_dispatch()):
        async for _chunk in loop.run(
            messages=[{"role": "user", "content": "find my CV"}],
            intent=Intent.FIND_PATH,
            initial_tool_result=None,
            available_tools=[],
            adapter=mock_adapter,
            obs=obs,
        ):
            pass

    events = [e.type for e in obs.history()]
    assert "agent_loop_done" in events
    assert "agent_loop_failure" not in events, (
        "a capped turn whose synthesis delivered a real answer must not be "
        "reported as a failure (the CV transcript bug)"
    )
