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

from core.agent.verify import criteria_gate
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
    return criteria_gate(trace, unmet_label="criteria not yet met")
