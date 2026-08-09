"""Context pruner agent stop condition — single model call, no loop."""

from __future__ import annotations

from typing import Optional

from core.models import ToolResult


def is_context_pruner_done(
    iterations: int,
    wall_clock_secs: float,
    last_tool_result: Optional[ToolResult],
    trace: object,
) -> tuple[bool, str]:
    """The pruner is a single model call — stop after one iteration."""
    if iterations >= 1:
        return True, "context pruner is a single-call agent (no tools, no loop)"
    return False, ""
