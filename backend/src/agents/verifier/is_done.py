"""
Verifier agent stop condition.

Per ADR-6: each agent supplies its own is_done(). The verifier's stop
conditions are verification-oriented:
    - All tests pass → done (verified)
    - Bug successfully reproduced → done (reproduced)
    - Acceptance criteria met → done (accepted)
    - Build/typecheck succeeds → done (verified)
    - No more verification steps → done

Phase 1 (this session): structural skeleton. is_done() always returns
False — the existing AgentLoop's termination logic continues to apply.

Phase 2 will add verification-specific stop conditions:
    - shell tool ran `pytest` and all tests passed → done
    - shell tool ran `ruff check` / `tsc` and no errors → done
    - process tool started a service and it responded → done
    - file_task read test output and it shows "OK" → done
    - no more tool calls requested → done (model is satisfied)
"""

from __future__ import annotations

from typing import Optional

from core.models import ToolResult


def is_verifier_done(
    iterations: int,
    wall_clock_secs: float,
    last_tool_result: Optional[ToolResult],
    trace: object,
) -> tuple[bool, str]:
    """
    Decide whether the verifier agent's loop should terminate.

    Phase 1: always returns (False, "") — let the existing AgentLoop
    handle termination via its own max-iterations + wall-clock-cap +
    no-more-tool-calls logic.

    Phase 2 will add verification-specific stop conditions:
        - pytest output contains "passed" with no failures → done
        - lint/typecheck output shows no errors → done
        - process status shows service is running → done
        - bug reproduction confirmed → done
        - all acceptance criteria checked → done

    The base loop also enforces hard caps (max_iterations,
    max_wall_clock_secs) regardless of this function's answer.
    """
    return False, ""
