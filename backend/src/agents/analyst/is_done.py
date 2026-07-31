"""
Analyst agent stop condition.

Per ADR-6: each agent supplies its own is_done(). The analyst's stop
conditions are analysis-oriented:
    - All specs/requirements documents read → done
    - Clear specification produced → done
    - Ambiguities resolved → done
    - No more analysis steps → done

Phase 1 (this session): structural skeleton. is_done() always returns
False — the existing AgentLoop's termination logic continues to apply.
"""

from __future__ import annotations

from typing import Optional

from core.models import ToolResult


def is_analyst_done(
    iterations: int,
    wall_clock_secs: float,
    last_tool_result: Optional[ToolResult],
    trace: object,
) -> tuple[bool, str]:
    """Phase 1: always returns (False, "") — AgentLoop handles termination."""
    return False, ""
