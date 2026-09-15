"""
Reviewer agent stop condition.

Each agent supplies its own is_done(). The reviewer's stop
conditions are review-oriented:
    - All files checked → done
    - Spec conformance assessed → done
    - Quality report complete → done
    - No more review steps → done

Promote from the always-False
stub to a real `criteria_gate` check — same one-line pattern as
`is_coding_done` and `is_verifier_done`.

The base loop still enforces hard caps (max_iterations,
max_wall_clock_secs) regardless of this function's answer — that's
the loop's "OR limit".
"""

from __future__ import annotations

from typing import Optional

from core.agent.verify import criteria_gate
from core.models import ToolResult


def is_reviewer_done(
    iterations: int,
    wall_clock_secs: float,
    last_tool_result: Optional[ToolResult],
    trace: object,
) -> tuple[bool, str]:
    """
    Decide whether the reviewer agent's loop should terminate.

    With success criteria: evaluate them against the trace evidence; the
    loop stops (True) only when all criteria pass.

    Without criteria: returns (False, "") — the existing AgentLoop
    termination logic continues to apply unchanged.
    """
    return criteria_gate(trace, unmet_label="criteria not yet met")
