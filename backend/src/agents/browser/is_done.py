"""
Browser agent stop condition.

Per ADR-6: each agent supplies its own is_done(). The browser agent's
stop condition is task-page-reached / form-submitted / user-says-stop.

Phase 1 (this session, Session 15): structural skeleton. The actual
stop-condition logic will be wired in when BaseAgent.run() hosts the
actual loop (Phase 2). For now, is_done() always returns False — the
existing AgentLoop's own termination logic (max iterations, no more
tool calls) continues to apply.
"""

from __future__ import annotations

from typing import Optional

from core.models import ToolResult


def is_browser_done(
    iterations: int,
    wall_clock_secs: float,
    last_tool_result: Optional[ToolResult],
    trace: object,
) -> tuple[bool, str]:
    """
    Decide whether the browser agent's loop should terminate.

    Phase 1: always returns (False, "") — let the existing AgentLoop
    handle termination via its own max-iterations + no-more-tool-calls
    logic. This keeps the new abstraction non-breaking.

    Phase 2 will add browser-specific stop conditions:
        - "close" action received → done (user closed the browser)
        - form submitted successfully → done (task complete)
        - target page reached (URL match) → done
        - user sent a new message → done (yield back to user)

    The base loop also enforces hard caps (max_iterations,
    max_wall_clock_secs) regardless of this function's answer — that's
    the "OR limit" from ADR-5.
    """
    return False, ""
