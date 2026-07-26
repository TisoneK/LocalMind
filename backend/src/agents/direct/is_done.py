"""Direct agent stop condition — always done after one model call."""

from __future__ import annotations

from typing import Optional

from core.models import ToolResult


def is_direct_done(
    iterations: int,
    wall_clock_secs: float,
    last_tool_result: Optional[ToolResult],
    trace: object,
) -> tuple[bool, str]:
    """Direct agent is always done — it's steps 1-2 only, no loop.

    The direct agent makes a single model call and returns. There's no
    iteration loop to terminate — is_done() is conceptually always True
    after the first (and only) model call. In Phase 1 this isn't called
    because the direct agent doesn't run the agent loop at all.
    """
    return True, "direct agent — single model call, no loop"
