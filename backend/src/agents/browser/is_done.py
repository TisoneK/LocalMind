"""
Browser agent stop condition.

Per ADR-6: each agent supplies its own is_done(). The browser agent's
stop condition is task-page-reached / form-submitted / user-says-stop.

ADR-18 P0 (Session 183, F6 cleanup): promote from the always-False
stub to a real `criteria_gate` check — same one-line pattern as
`is_coding_done` (Session 173) and `is_verifier_done` (Session 174).
When the turn carries `success_criteria`, the gate evaluates them
deterministically against the trace's tool evidence + the workspace;
the loop stops ONLY when every criterion is VERIFIED. When criteria
are empty, returns (False, "") — the legacy model-assertion +
hard-caps path is unchanged.

The base loop still enforces hard caps (max_iterations,
max_wall_clock_secs) regardless of this function's answer — that's
the "OR limit" from ADR-5.
"""

from __future__ import annotations

from typing import Optional

from core.agent.verify import criteria_gate
from core.models import ToolResult


def is_browser_done(
    iterations: int,
    wall_clock_secs: float,
    last_tool_result: Optional[ToolResult],
    trace: object,
) -> tuple[bool, str]:
    """
    Decide whether the browser agent's loop should terminate.

    With success criteria: evaluate them against the trace evidence; the
    loop stops (True) only when all criteria pass. The evaluation is
    stored back on the trace (criteria_results / gate_passed /
    gate_summary) so the final-answer path can report it honestly.

    Without criteria: returns (False, "") — the existing AgentLoop
    termination logic (model assertion, max iterations, wall-clock cap)
    continues to apply unchanged.
    """
    return criteria_gate(trace, unmet_label="criteria not yet met")
