"""Acceptance behavior for LocalMind's parent agent."""

from __future__ import annotations

from typing import Optional

from core.agent.verify import criteria_gate
from core.models import ToolResult


def is_parent_done(
    iterations: int,
    wall_clock_secs: float,
    last_tool_result: Optional[ToolResult],
    trace: object,
) -> tuple[bool, str]:
    """Stop early only when explicit criteria have deterministic evidence."""
    return criteria_gate(trace, unmet_label="parent-agent criteria not yet met")
