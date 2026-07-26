"""
CodingAgent — the second concrete BaseAgent subclass.

Per ADR-6: a thin subclass of BaseAgent that supplies coding-specific
context_builder, scoped tools, and is_done(). The actual loop execution
delegates to the existing AgentLoop (Phase 1) — this keeps the new
abstraction non-breaking while establishing the structural skeleton
that ResearchAgent and DirectAgent will populate in future sessions.

The coding agent is the centerpiece of the CODING HARNESS diagram
(ADR-5). It's the agent that:
    - Edits files (file_write, file_edit)
    - Runs shell commands (shell)
    - Executes code (code_exec)
    - Reads files (file_task)
    - Benefits most from the workspace_state feedback loop (Session 16)
      — git diff shows what it changed, build/test results show whether
      the change worked

Scoped toolset: 5 tools (shell, file_task, file_write, file_edit,
code_exec). Excludes web_search, web_fetch, browse, memory_op, sysinfo.
Smaller surface = more reliable selection on gemma3:1b-class hardware
(ADR-6 point 6).
"""

from __future__ import annotations

import logging
from typing import Optional

from agents.base_agent import AgentConfig, BaseAgent
from agents.coding import CODING_TOOLS, build_coding_context, is_coding_done
from core.models import Intent, ToolResult

logger = logging.getLogger(__name__)


class CodingAgent(BaseAgent):
    """
    The Coding Agent — edits files, runs shell commands, executes code.

    Scoped toolset: shell, file_task, file_write, file_edit, code_exec
    (5 tools). Cannot search the web, drive a browser, or manage memory.

    Stop condition (Phase 2): tests pass / build succeeds / no more
    tool calls / user says stop. Phase 1 delegates to the existing
    AgentLoop's termination logic (max iterations + wall-clock cap from
    Session 16).

    Benefits from the workspace_state feedback loop (Session 16): git
    diff shows what it changed, build/test results show whether the
    change worked. This is the ADR-5 differentiator — "observations
    flow back into context every turn."
    """

    def config(self) -> AgentConfig:
        return AgentConfig(
            name="coding",
            # Coding tasks need more iterations than browser tasks —
            # a typical "create X" task takes 2-3 iterations, but
            # debugging can take more. 20 is generous; the wall-clock
            # cap is the real safety net.
            max_iterations=20,
            # Coding tasks are slow — file I/O, shell commands, code
            # execution. 10 minutes is generous; the iteration cap is
            # the other safety net.
            max_wall_clock_secs=600,  # 10 minutes
            allowed_tools=CODING_TOOLS,
            tools_enabled=True,
        )

    def build_context(
        self,
        messages: list[dict],
        intent: Intent,
        memory_facts: Optional[list[str]] = None,
        orchestrator_context: Optional[str] = None,
    ) -> str:
        return build_coding_context(
            messages=messages,
            intent=intent,
            memory_facts=memory_facts,
            orchestrator_context=orchestrator_context,
        )

    def is_done(
        self,
        iterations: int,
        wall_clock_secs: float,
        last_tool_result: Optional[ToolResult],
        trace: object,
    ) -> tuple[bool, str]:
        return is_coding_done(
            iterations=iterations,
            wall_clock_secs=wall_clock_secs,
            last_tool_result=last_tool_result,
            trace=trace,
        )

    def description(self) -> str:
        return (
            "Coding Agent — edits files, runs shell commands, and executes "
            "code. Use this agent for programming tasks: writing code, "
            "fixing bugs, running tests, building projects, refactoring. "
            "Scoped toolset: shell (terminal commands), file_task (read "
            "files), file_write (create files), file_edit (modify files), "
            "code_exec (run code). Cannot search the web, drive a browser, "
            "or manage memory. The workspace state (git status, diff, "
            "build/test results) is injected every turn — use it to verify "
            "your changes."
        )
