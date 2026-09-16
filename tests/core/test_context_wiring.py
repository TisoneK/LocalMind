"""ADR-19 wiring tests (Session 163, re-keyed Session 186).

The policy computed at the loop head must reach the compactor, and the
engine must resolve it from the settled task_type.

Session 186 (ADR-19 x ADR-22 re-key): the dispatcher task_type is now a
HINT — the agent SETTLES the task type during planning from its actual
routing (intent). An explicit canonical hint still wins; an empty or
misclassified hint is corrected by the intent fallback, so an AGENT turn
never keys memory levels / policy off a wrong hint.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.agent.loop import AgentLoop
from core.models import Intent, StreamChunk
from core.obs import ObsCollector


class _SilentAdapter:
    """Adapter that never emits text (forces the loop through iterations)."""

    def __init__(self):
        self.calls = 0

    async def chat_with_tools(self, messages, tools, temperature=0.3, intent=None, tool_choice=None):
        self.calls += 1
        async def _stream():
            yield StreamChunk(text="", done=True)
        return _stream()

    async def chat(self, messages, temperature=0.4, intent=None):
        return
        yield  # pragma: no cover


async def _run_loop_once(task_type: str = "", intent: Intent = Intent.SHELL):
    """Run AgentLoop with the given dispatcher task_type hint + intent and
    capture (a) the context policy the compactor received via the mocked
    simplify_tool_results, and (b) the obs collector (for settlement
    events)."""
    captured = {}
    obs = ObsCollector()

    def _fake_simplify(messages, policy=None):
        captured["policy"] = policy
        return messages

    with patch("core.agent.loop.simplify_tool_results", side_effect=_fake_simplify):
        loop = AgentLoop(adapter=MagicMock())
        async for chunk in loop.run(
            messages=[{"role": "user", "content": "fix the failing test"}],
            intent=intent,
            initial_tool_result=None,
            available_tools=[],
            adapter=_SilentAdapter(),
            task_type=task_type,
            obs=obs,
        ):
            pass
    captured["obs"] = obs
    return captured


@pytest.mark.asyncio
async def test_shell_settles_to_code_when_hint_empty():
    """ADR-19 x ADR-22 re-key: an EMPTY dispatcher hint on a
    SHELL agent turn settles to task_type 'code' — the agent's planning
    intent is the settled routing, not the hint. The 184 smoke showed the
    free-tier dispatcher leaves hints empty/misclassified; re-keying on the
    settled type fixes the wrong-memory-levels fallout. (The Session 163
    'empty hint must stay legacy' contract is superseded for AGENT turns: a
    SHELL task IS a code task.)"""
    captured = await _run_loop_once(task_type="")
    policy = captured.get("policy")
    assert policy is not None
    assert policy.task_type == "code"


@pytest.mark.asyncio
async def test_debug_task_type_uses_debug_policy():
    """An explicit canonical hint still wins over the intent fallback."""
    captured = await _run_loop_once(task_type="debug")
    policy = captured.get("policy")
    assert policy is not None
    assert policy.task_type == "debug"
    assert "traceback" in policy.keep_markers


@pytest.mark.asyncio
async def test_invalid_hint_settles_to_code_for_shell():
    """An unusable hint ('banana') on a SHELL turn also settles to 'code' —
    the intent fallback corrects garbage hints instead of silently keeping
    the legacy no-op policy."""
    captured = await _run_loop_once(task_type="banana")
    policy = captured.get("policy")
    assert policy.task_type == "code"


@pytest.mark.asyncio
async def test_web_search_settles_to_research():
    """WEB_SEARCH agent turns settle to 'research' (long_term/project
    memory levels) even with an empty dispatcher hint."""
    captured = await _run_loop_once(task_type="", intent=Intent.WEB_SEARCH)
    policy = captured.get("policy")
    assert policy.task_type == "research"


@pytest.mark.asyncio
async def test_explicit_canonical_hint_still_wins():
    """A canonical explicit hint (debug) still wins over the intent
    fallback — the re-key only corrects empty/misclassified hints."""
    captured = await _run_loop_once(task_type="debug", intent=Intent.WEB_SEARCH)
    policy = captured.get("policy")
    assert policy.task_type == "debug"


@pytest.mark.asyncio
async def test_settlement_emits_task_type_settled_event():
    """The loop surfaces the settled task type via the task_type_settled
    obs event so the engine/frontend can observe what the agent settled on."""
    captured = await _run_loop_once(task_type="", intent=Intent.SHELL)
    settled = [e for e in captured["obs"].history() if e.type == "task_type_settled"]
    assert len(settled) == 1
    assert settled[0].data.get("task_type") == "code"
    assert settled[0].data.get("source") in ("planning", "routing")


@pytest.mark.asyncio
async def test_resolve_from_plan_smoke():
    """A settled task_type flows into policy_for (engine side)."""
    from core.context_policy import policy_for

    policy = policy_for("debug")
    assert policy.task_type == "debug"
