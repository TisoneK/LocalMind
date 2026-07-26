"""
Coding agent stop condition.

Per ADR-6: each agent supplies its own is_done(). The coding agent's
stop condition is tests-pass / build-succeeds / user-says-stop.

Phase 1 (this session, Session 17): structural skeleton. The actual
stop-condition logic will be wired in when BaseAgent.run() hosts the
actual loop (Phase 2). For now, is_done() always returns False — the
existing AgentLoop's own termination logic (max iterations, no more
tool calls, wall-clock cap from Session 16) continues to apply.

Phase 2 will add coding-specific stop conditions:
    - tests pass after a file edit → done (task complete)
    - build/typecheck succeeds after a change → done
    - no more tool calls requested → done (model is satisfied)
    - user sends a new message → done (yield back to user)
    - wall-clock cap hit → done (hard limit, already enforced)
"""

from __future__ import annotations

from typing import Optional

from core.models import ToolResult


def is_coding_done(
    iterations: int,
    wall_clock_secs: float,
    last_tool_result: Optional[ToolResult],
    trace: object,
) -> tuple[bool, str]:
    """
    Decide whether the coding agent's loop should terminate.

    Phase 1: always returns (False, "") — let the existing AgentLoop
    handle termination via its own max-iterations + wall-clock-cap +
    no-more-tool-calls logic. This keeps the new abstraction
    non-breaking.

    Phase 2 will add coding-specific stop conditions:
        - shell tool ran `pytest` / `ruff` / `tsc` and it passed → done
        - file_write/file_edit succeeded and no follow-up tool call → done
        - code_exec output indicates success → done

    The base loop also enforces hard caps (max_iterations,
    max_wall_clock_secs from Session 16) regardless of this function's
    answer — that's the "OR limit" from ADR-5.
    """
    return False, ""
