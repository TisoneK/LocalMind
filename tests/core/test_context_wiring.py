"""ADR-19 wiring tests (Session 163).

The policy computed at the loop head must reach the compactor, and the
engine must resolve it from the OrchestrationPlan.task_type. Default
(empty task_type) → legacy no-op policy, so unwired behavior is unchanged.
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

    async def chat_with_tools(self, messages, tools, temperature=0.3, intent=None):
        self.calls += 1
        async def _stream():
            yield StreamChunk(text="", done=True)
        return _stream()

    async def chat(self, messages, temperature=0.4, intent=None):
        return
        yield  # pragma: no cover


async def _run_loop_once(task_type: str = ""):
    """Run AgentLoop with the given task_type and capture the policy the
    compactor received via the mocked simplify_tool_results."""
    captured = {}

    def _fake_simplify(messages, policy=None):
        captured["policy"] = policy
        return messages

    with patch("core.agent.loop.simplify_tool_results", side_effect=_fake_simplify):
        loop = AgentLoop(adapter=MagicMock())
        async for chunk in loop.run(
            messages=[{"role": "user", "content": "fix the failing test"}],
            intent=Intent.SHELL,
            initial_tool_result=None,
            available_tools=[],
            adapter=_SilentAdapter(),
            task_type=task_type,
            obs=ObsCollector(),
        ):
            pass
    return captured


@pytest.mark.asyncio
async def test_empty_task_type_uses_legacy_policy():
    """Empty task_type + SHELL intent must stay legacy — no intent fallback
    may silently activate a policy (Session 163 no-regression contract)."""
    captured = await _run_loop_once(task_type="")
    policy = captured.get("policy")
    assert policy is not None
    assert policy.task_type == "default"
    assert policy.keep_markers == ()


@pytest.mark.asyncio
async def test_debug_task_type_uses_debug_policy():
    captured = await _run_loop_once(task_type="debug")
    policy = captured.get("policy")
    assert policy is not None
    assert policy.task_type == "debug"
    assert "traceback" in policy.keep_markers


@pytest.mark.asyncio
async def test_unknown_task_type_falls_back_to_default():
    """Even an invalid task_type must not silently change behavior."""
    captured = await _run_loop_once(task_type="banana")
    policy = captured.get("policy")
    assert policy.task_type == "default"


@pytest.mark.asyncio
async def test_resolve_from_plan_smoke():
    """OrchestrationPlan.task_type flows into policy_for (engine side)."""
    from core.context_policy import policy_for
    from core.models import OrchestrationPlan, TaskProfile

    profile = TaskProfile(
        intent=Intent.SHELL,
        primary_domain="shell",
        execution_mode="agent_loop",
        safety_level="low",
        confidence=0.9,
        reformulated="fix it",
        capabilities=[Intent.SHELL],
    )
    plan = OrchestrationPlan(profile=profile, task_type="debug")
    policy = policy_for(str(getattr(plan, "task_type", "") or ""))
    assert policy.task_type == "debug"
