"""
E2E coverage for the parent's completion-verification FLOOR (B-2026-08-18-2,
review-66) — the missing VERIFY→DONE segment of the spec's wheel.

These drive the REAL acceptance-gate method (`_acceptance_gate_at_final_answer`)
with a stub replan adapter, so they exercise the floor branch AND its recovery
wiring (`_replan_for_gate` + the injected [COMPLETION FLOOR] block) end-to-end —
not just the `parent_completion_floor_note` helper (unit-tested separately).

The scenario the floor closes: on the user-facing parent path there is no
explicit success-criteria contract, so the gate used to accept the model's
"done" even when the parent's last high-stakes action FAILED (spec §29/§30).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from core.agent.loop import AgentLoop
from core.agent.models import AgentStep, AgentTrace
from core.models import Intent, StreamChunk

# shell.py wraps a nonzero-exit command as this. The dispatch layer now also
# propagates ToolResult.success=False as `tool_failed`; the observation check
# remains the defensive floor for command-level failures from other tools.
_SHELL_FAIL_OBS = "Command failed:\ncat: /nonexistent_xyz.txt: No such file or directory"
_SHELL_OK_OBS = "floor-smoke-ok"


class _ReplanAdapter:
    """Captures the gate's replan LLM call and returns a revised plan."""

    def __init__(self, plan_text="1. inspect the failure\n2. fix and re-run"):
        self.plan_text = plan_text
        self.replan_calls = []

    async def chat(self, messages, temperature=0.1, intent=None):
        self.replan_calls.append(messages)
        yield StreamChunk(text=self.plan_text, done=False)
        yield StreamChunk(text="", done=True)


def _trace(*steps):
    """steps: (tool_name, observation, tool_failed) tuples → an AgentTrace with
    NO success_criteria (the parent path)."""
    trace = AgentTrace(success_criteria=[])
    for i, (name, obs, failed) in enumerate(steps):
        trace.steps.append(
            AgentStep(
                iteration=i + 1,
                thought=f"step {i}",
                tool_name=name,
                tool_input="",
                observation=obs,
                tool_failed=failed,
            )
        )
    return trace


async def _run_gate(loop, trace, *, is_parent, iteration=0, max_iter=8, adapter=None):
    loop_messages = [{"role": "user", "content": "run the command and report"}]
    adapter = adapter or _ReplanAdapter()
    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace,
        iteration=iteration,
        effective_max_iter=max_iter,
        loop_messages=loop_messages,
        observation_log="(observation log)",
        active_adapter=adapter,
        intent=Intent.ANALYZE,  # the parent's fixed turn intent
        obs=None,
        is_parent=is_parent,
    )
    return suffix, is_final, loop_messages, adapter


@pytest.mark.asyncio
async def test_parent_failed_last_action_rejects_done_and_recovers():
    """Parent claims done after a failed shell → gate rejects, injects a
    recovery block, and continues (is_final False)."""
    loop = AgentLoop(adapter=MagicMock())
    trace = _trace(("shell", _SHELL_FAIL_OBS, False))
    suffix, is_final, loop_messages, adapter = await _run_gate(loop, trace, is_parent=True)

    assert is_final is False
    assert suffix == ""
    assert len(adapter.replan_calls) == 1  # the gate actually replanned
    injected = loop_messages[-1]
    assert injected["role"] == "user"
    assert "COMPLETION FLOOR" in injected["content"]
    assert "Do NOT report done" in injected["content"]


@pytest.mark.asyncio
async def test_parent_successful_last_action_accepts_done():
    """A successful high-stakes action must complete normally — no false-fail,
    no replan."""
    loop = AgentLoop(adapter=MagicMock())
    trace = _trace(("shell", _SHELL_OK_OBS, False))
    _suffix, is_final, loop_messages, adapter = await _run_gate(loop, trace, is_parent=True)

    assert is_final is True
    assert adapter.replan_calls == []
    assert "COMPLETION FLOOR" not in loop_messages[-1]["content"]


@pytest.mark.asyncio
async def test_non_parent_is_unaffected_legacy_path():
    """The floor is parent-scoped: a non-parent agent with the same failed
    trace and no criteria keeps the legacy model-assertion path (is_final True)."""
    loop = AgentLoop(adapter=MagicMock())
    trace = _trace(("shell", _SHELL_FAIL_OBS, False))
    _suffix, is_final, _lm, adapter = await _run_gate(loop, trace, is_parent=False)

    assert is_final is True
    assert adapter.replan_calls == []


@pytest.mark.asyncio
async def test_parent_failed_action_at_cap_stops_honestly():
    """Out of iterations → stop honestly rather than loop the same failure."""
    loop = AgentLoop(adapter=MagicMock())
    trace = _trace(("shell", _SHELL_FAIL_OBS, False))
    # iteration+1 >= max_iter → cap reached.
    suffix, is_final, _lm, adapter = await _run_gate(
        loop, trace, is_parent=True, iteration=7, max_iter=8
    )

    assert is_final is True
    assert "completion floor" in suffix.lower()
    assert adapter.replan_calls == []  # no replan at the cap


@pytest.mark.asyncio
async def test_parent_low_stakes_failure_is_not_gated():
    """A failed READ/analysis tool is not high-stakes → no floor, done accepted."""
    loop = AgentLoop(adapter=MagicMock())
    trace = _trace(("file_task", "error: file not found", False))
    _suffix, is_final, _lm, adapter = await _run_gate(loop, trace, is_parent=True)

    assert is_final is True
    assert adapter.replan_calls == []


@pytest.mark.asyncio
async def test_parent_tool_level_failure_also_rejects():
    """A tool-level failure (tool_failed=True, e.g. permission/internal) is
    caught even without error markers in the observation."""
    loop = AgentLoop(adapter=MagicMock())
    trace = _trace(("code_exec", "", True))
    _suffix, is_final, loop_messages, adapter = await _run_gate(loop, trace, is_parent=True)

    assert is_final is False
    assert len(adapter.replan_calls) == 1
    assert "COMPLETION FLOOR" in loop_messages[-1]["content"]
