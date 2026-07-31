"""
Debugger agent stop condition.

Per ADR-6: each agent supplies its own is_done(). The debugger's stop
conditions are diagnosis-oriented:
    - Root cause identified → done
    - Minimal reproduction isolated → done
    - Error traced to a specific line/change → done
    - No more diagnostic steps → done

Phase 1 (this session): structural skeleton. is_done() always returns
False — the existing AgentLoop's termination logic continues to apply.

Phase 2 will add debug-specific stop conditions:
    - file_task returned the relevant source → done
    - git log/diff identified the regression commit → done
    - shell ran the failing command and captured output → done
    - process restarted service and error reproduced → done
"""

from __future__ import annotations

from typing import Optional

from core.models import ToolResult


def is_debugger_done(
    iterations: int,
    wall_clock_secs: float,
    last_tool_result: Optional[ToolResult],
    trace: object,
) -> tuple[bool, str]:
    """Phase 1: always returns (False, "") — AgentLoop handles termination."""
    return False, ""
