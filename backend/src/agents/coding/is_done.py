"""
Coding agent stop condition.

Per ADR-6: each agent supplies its own is_done(). The coding agent's
stop condition is criteria-verified / tests-pass / build-succeeds /
user-says-stop.

ADR-18 P0 (B-2026-08-12-1, Session 156): the acceptance gate. When the
turn carries success criteria (from the dispatcher's execution_plan or
the model's create_plan), is_done() evaluates them deterministically
against the trace's tool evidence + the workspace. The loop stops ONLY
when every criterion is VERIFIED — not merely because the model asserts
it is done. That is the "an agent saying 'done' should not mean the
task is done" contract.

No criteria → (False, "") — the legacy model-assertion + hard-caps
termination path is unchanged (chat/trivial/research turns never get a
contract, so this agent's stop behavior is identical there).

The base loop still enforces the hard caps (max_iterations,
max_wall_clock_secs) regardless of this function's answer — the "OR
limit" from ADR-5.
"""

from __future__ import annotations

from typing import Optional

from core.agent.verify import evaluate_criteria, format_gate_results, gate_passed
from core.models import ToolResult


def is_coding_done(
    iterations: int,
    wall_clock_secs: float,
    last_tool_result: Optional[ToolResult],
    trace: object,
) -> tuple[bool, str]:
    """
    Decide whether the coding agent's loop should terminate.

    With success criteria: evaluate them against the trace evidence; the
    loop stops (True) only when all criteria pass. The evaluation is
    stored back on the trace (criteria_results / gate_passed /
    gate_summary) so the final-answer path can report it honestly.

    Without criteria: returns (False, "") — the existing AgentLoop
    termination logic (model assertion, max iterations, wall-clock cap)
    continues to apply unchanged.
    """
    criteria = getattr(trace, "success_criteria", None) or []
    if not criteria:
        return False, ""

    # Run-scoped evidence guard: the gate must NOT pass before this run has
    # executed ANY tool. Workspace-scoped criteria ("hello.py exists", "git
    # status is clean") can be satisfied by PRE-EXISTING state — without this
    # guard the loop would terminate on iteration 0 claiming the criteria are
    # met while the agent never did any work. "Done" requires receipts FROM
    # THIS RUN.
    if not any(step.tool_name for step in getattr(trace, "steps", [])):
        return False, ""

    results = evaluate_criteria(criteria, trace)
    trace.criteria_results = results
    trace.gate_passed = gate_passed(results)

    if trace.gate_passed:
        trace.gate_summary = format_gate_results(results)
        return True, trace.gate_summary

    unmet = [criterion for criterion, passed, _ in results if not passed]
    return False, f"criteria not yet met: {', '.join(unmet[:3])}"
