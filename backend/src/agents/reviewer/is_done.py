"""
Reviewer agent stop condition.

Per ADR-6: each agent supplies its own is_done(). The reviewer's stop
conditions are review-oriented:
    - All files checked → done
    - Spec conformance assessed → done
    - Quality report complete → done
    - No more review steps → done

Phase 1 (this session): structural skeleton. is_done() always returns
False — the existing AgentLoop's termination logic continues to apply.

Phase 2 will add review-specific stop conditions:
    - file_task returned content for all target files → done
    - shell ran linter and output reviewed → done
    - git diff analyzed and findings reported → done
    - no more tool calls requested → done
"""

from __future__ import annotations

from typing import Optional

from core.models import ToolResult


def is_reviewer_done(
    iterations: int,
    wall_clock_secs: float,
    last_tool_result: Optional[ToolResult],
    trace: object,
) -> tuple[bool, str]:
    """Phase 1: always returns (False, "") — AgentLoop handles termination."""
    return False, ""
