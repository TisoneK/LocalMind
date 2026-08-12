"""
Verifier agent stop condition.

Per ADR-6: each agent supplies its own is_done(). The verifier's stop
conditions are verification-oriented: all tests pass, acceptance
criteria met, build/typecheck succeeds, bug reproduced.

ADR-18 P1 (Session 174): real implementation replacing the Phase 1 stub.
The verifier is the acceptance stage — "an agent saying 'done' should not
mean the task is done." When the turn carries success criteria (from the
dispatcher's execution_plan or the model's create_plan), is_done()
evaluates them deterministically against the trace's tool evidence; the
loop stops ONLY when every criterion is VERIFIED. That is the same
evidence-contract as is_coding_done (shared verify.py criteria_gate) —
the verifier is the stage that enforces it for high-stakes intents.

No criteria → (False, "") — legacy model-assertion termination unchanged.

The base loop still enforces hard caps (max_iterations, max_wall_clock_secs)
regardless of this function's answer.
"""

from __future__ import annotations

from typing import Optional

from core.agent.verify import criteria_gate
from core.models import ToolResult


def is_verifier_done(
    iterations: int,
    wall_clock_secs: float,
    last_tool_result: Optional[ToolResult],
    trace: object,
) -> tuple[bool, str]:
    """
    Decide whether the verifier agent's loop should terminate.

    With success criteria: evaluate them against the trace evidence; the
    loop stops (True) only when all criteria pass. The evaluation is
    stored back on the trace (criteria_results / gate_passed /
    gate_summary) so the final-answer path can report it honestly.

    Without criteria: returns (False, "") — the existing AgentLoop
    termination logic (model assertion, max iterations, wall-clock cap)
    continues to apply unchanged.
    """
    return criteria_gate(trace, unmet_label="verification criteria not yet met")
