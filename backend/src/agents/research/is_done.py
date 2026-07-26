"""Research agent stop condition — Phase 1 stub."""

from __future__ import annotations

from typing import Optional

from core.models import ToolResult


def is_research_done(
    iterations: int,
    wall_clock_secs: float,
    last_tool_result: Optional[ToolResult],
    trace: object,
) -> tuple[bool, str]:
    """Phase 1: always (False, ''). Phase 2: enough-sources / query-exhausted."""
    return False, ""
