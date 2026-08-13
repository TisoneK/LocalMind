"""
Tests for Session 178 — wire AgentOrchestrator.replan() (F1).

Before Session 178, `AgentOrchestrator.replan()` (defined at
`core/agent/orchestrator.py:361`) had ZERO callers in the entire
backend. The verify-fail path used `AgentLoop._replan_for_gate`
(loop.py:3931) which is a self-contained LLM call that never
notified the orchestrator — so:
- The orchestrator's confidence never dropped.
- The orchestrator could never re-route to a different agent
  (e.g. coding → debugger).
- The `orchestrator_replan_start/done/timeout/failed` obs events
  emitted by `replan()` were dead code (never reachable).

These tests pin the new wiring: when `AgentLoop.run()` is given
an `orchestrator=` kwarg, that orchestrator's `replan()` IS
called from the verify-fail branch of `_acceptance_gate_at_final_answer`,
its result is injected into the loop context, and the
`orchestrator_replan_*` obs events fire for real.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.agent.constants import Intent
from core.agent.loop import AgentLoop
from core.agent.models import AgentStep, AgentTrace
from core.agent.orchestrator import OrchestrationResult, OrchestrationStep

# ── Test doubles ─────────────────────────────────────────────────────────────


class _FakeAdapter:
    """Minimal adapter that streams one chunk and exits."""

    def __init__(self, chunks: list[str]):
        self._chunks = chunks

    async def chat(self, messages, temperature=0.1, intent="chat"):
        for chunk_text in self._chunks:
            yield MagicMock(text=chunk_text, error=None, thinking=None)
        return


class _FakeObs:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def emit(self, event_type: str, **kwargs):
        self.events.append((event_type, kwargs))


# ── Direct test of the new wiring in _acceptance_gate_at_final_answer ────────


@pytest.mark.asyncio
async def test_orchestrator_replan_is_called_on_gate_failure():
    """When the acceptance gate fails with iterations remaining AND an
    orchestrator is provided, orchestrator.replan() IS called.

    We use a "pytest passes" criterion — the tests checker requires
    actual pytest output in the evidence, so a tool step whose output
    is just "wrote 14 bytes" will FAIL this criterion.
    """
    loop = AgentLoop(adapter=_FakeAdapter(["1. retry with a different path"]))

    # Build a trace with a real tool step so the run-scoped evidence guard
    # passes, and a criterion that FAILS against this evidence (no pytest
    # output means "pytest passes" cannot be verified).
    trace = AgentTrace(
        success_criteria=["pytest passes with zero failures"],
        steps=[
            AgentStep(
                iteration=0,
                thought="running tests",
                tool_name="shell",
                tool_input='{"command": "pytest tests/"}',
                observation="wrote 14 bytes",  # NOT pytest output
            ),
        ],
    )

    # Mock orchestrator — verify its replan() is awaited.
    mock_orchestrator = MagicMock()
    mock_orchestrator.replan = AsyncMock(
        return_value=OrchestrationResult(
            steps=[],
            confidence=0.3,
            needs_clarification=False,
            clarification_question="",
            orchestrator_context="[Orchestrator: confidence dropped to 0.3]",
            raw_plan="",
        )
    )

    obs = _FakeObs()
    loop_messages: list[dict] = [{"role": "user", "content": "run the tests"}]

    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace,
        iteration=0,
        effective_max_iter=8,
        loop_messages=loop_messages,
        observation_log="shell returned: wrote 14 bytes",
        active_adapter=_FakeAdapter(["1. retry with another approach"]),
        intent=Intent.SHELL,
        obs=obs,
        orchestrator=mock_orchestrator,
        reformulated_message="run pytest",
        memory_facts=[],
        intent_history=["shell"],
    )

    # First verify the gate actually FAILED — without that, the test is moot.
    assert is_final is False, "gate should have failed (no pytest output in evidence)"

    # 1. The orchestrator's replan() WAS called.
    assert mock_orchestrator.replan.called, "orchestrator.replan() was not called"
    call_kwargs = mock_orchestrator.replan.call_args.kwargs
    assert call_kwargs["intent"] == Intent.SHELL
    assert call_kwargs["failure_reason"]
    assert isinstance(call_kwargs["failed_step"], OrchestrationStep)

    # 2. The orchestrator's obs events fired.
    event_types = [e[0] for e in obs.events]
    assert "orchestrator_replan_start" in event_types
    assert "orchestrator_replan_done" in event_types

    # 3. The orchestrator's hint is in the user block injected into loop_messages.
    injected_block = loop_messages[-1]["content"]
    assert "ORCHESTRATOR" in injected_block
    assert "confidence dropped to 0.3" in injected_block

    # 4. The loop continues (is_final is False) — the gate did not accept "done".
    assert is_final is False
    assert suffix == ""


@pytest.mark.asyncio
async def test_no_orchestrator_keeps_legacy_behavior():
    """When orchestrator=None (legacy path), the existing _replan_for_gate
    LLM call still runs and no orchestrator obs events fire."""
    loop = AgentLoop(adapter=_FakeAdapter(["1. retry the failed step"]))

    # Use a failing criterion (no pytest output) so the gate fires.
    trace = AgentTrace(
        success_criteria=["pytest passes with zero failures"],
        steps=[
            AgentStep(
                iteration=0,
                thought="running tests",
                tool_name="shell",
                tool_input='{"command": "pytest tests/"}',
                observation="wrote 14 bytes",  # NOT pytest output
            ),
        ],
    )

    obs = _FakeObs()
    loop_messages: list[dict] = [{"role": "user", "content": "run the tests"}]

    # No orchestrator — legacy path.
    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace,
        iteration=0,
        effective_max_iter=8,
        loop_messages=loop_messages,
        observation_log="shell returned: wrote 14 bytes",
        active_adapter=_FakeAdapter(["1. retry the failed step"]),
        intent=Intent.SHELL,
        obs=obs,
        orchestrator=None,
    )

    # Sanity: gate failed.
    assert is_final is False, "gate should have failed"

    # Legacy behavior: no orchestrator_replan_* events; gate fails → not final.
    event_types = [e[0] for e in obs.events]
    assert not any("orchestrator_replan" in t for t in event_types)
    assert "agent_loop_gate_failed_replan" in event_types


@pytest.mark.asyncio
async def test_orchestrator_replan_failure_is_swallowed():
    """If orchestrator.replan() raises, the loop falls back to _replan_for_gate
    without crashing. (Defensive — orchestrator is best-effort.)"""
    loop = AgentLoop(adapter=_FakeAdapter(["1. retry the failed step"]))

    trace = AgentTrace(
        success_criteria=["pytest passes with zero failures"],
        steps=[
            AgentStep(
                iteration=0,
                thought="running tests",
                tool_name="shell",
                tool_input='{"command": "pytest tests/"}',
                observation="wrote 14 bytes",  # NOT pytest output
            ),
        ],
    )

    mock_orchestrator = MagicMock()
    mock_orchestrator.replan = AsyncMock(side_effect=RuntimeError("simulated orchestrator crash"))

    obs = _FakeObs()
    loop_messages: list[dict] = [{"role": "user", "content": "run the tests"}]

    # Should not raise.
    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace,
        iteration=0,
        effective_max_iter=8,
        loop_messages=loop_messages,
        observation_log="shell returned: wrote 14 bytes",
        active_adapter=_FakeAdapter(["1. retry the failed step"]),
        intent=Intent.SHELL,
        obs=obs,
        orchestrator=mock_orchestrator,
    )

    # Sanity: gate failed.
    assert is_final is False, "gate should have failed"

    # The orchestrator was called (and raised) but the loop continued.
    assert mock_orchestrator.replan.called
    # The legacy _replan_for_gate still ran and injected its own block.
    assert is_final is False
    injected_block = loop_messages[-1]["content"]
    # The legacy "Revised plan from the gate" block is present.
    assert "Revised plan from the gate" in injected_block
    # The orchestrator hint is NOT present (replan crashed).
    assert "ORCHESTRATOR" not in injected_block


@pytest.mark.asyncio
async def test_orchestrator_not_called_when_gate_passes():
    """When all criteria are met, the orchestrator's replan() is NOT called —
    there's no failure to report. We use a "no errors" criterion with a
    clean tool output (the _check_no_errors checker passes it)."""
    loop = AgentLoop(adapter=_FakeAdapter([]))

    trace = AgentTrace(
        success_criteria=["no errors in the output"],
        steps=[
            AgentStep(
                iteration=0,
                thought="running command",
                tool_name="shell",
                tool_input='{"command": "echo hi"}',
                observation="hi",  # clean output, no error markers
            ),
        ],
    )

    mock_orchestrator = MagicMock()
    mock_orchestrator.replan = AsyncMock()

    obs = _FakeObs()
    loop_messages: list[dict] = [{"role": "user", "content": "run the command"}]

    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace,
        iteration=0,
        effective_max_iter=8,
        loop_messages=loop_messages,
        observation_log="shell returned: hi",
        active_adapter=_FakeAdapter([]),
        intent=Intent.SHELL,
        obs=obs,
        orchestrator=mock_orchestrator,
    )

    # Gate passed → final, replan NOT called.
    assert is_final is True
    assert not mock_orchestrator.replan.called
    # No orchestrator_replan_* events.
    event_types = [e[0] for e in obs.events]
    assert not any("orchestrator_replan" in t for t in event_types)


@pytest.mark.asyncio
async def test_orchestrator_not_called_when_no_criteria():
    """When trace.success_criteria is empty, the gate short-circuits and
    the orchestrator is NOT called. (Conservative — no contract.)"""
    loop = AgentLoop(adapter=_FakeAdapter([]))

    trace = AgentTrace(
        success_criteria=[],  # empty — the F2 fallback is what populates this
        steps=[
            AgentStep(
                iteration=0,
                thought="writing file",
                tool_name="file_write",
                tool_input='{"path": "/tmp/whatever.txt"}',
                observation="wrote 14 bytes",
            ),
        ],
    )

    mock_orchestrator = MagicMock()
    mock_orchestrator.replan = AsyncMock()

    obs = _FakeObs()
    loop_messages: list[dict] = [{"role": "user", "content": "write the file"}]

    suffix, is_final = await loop._acceptance_gate_at_final_answer(
        trace=trace,
        iteration=0,
        effective_max_iter=8,
        loop_messages=loop_messages,
        observation_log="",
        active_adapter=_FakeAdapter([]),
        intent=Intent.FILE_WRITE,
        obs=obs,
        orchestrator=mock_orchestrator,
    )

    # No criteria → legacy path, no orchestrator call.
    assert is_final is True
    assert not mock_orchestrator.replan.called
