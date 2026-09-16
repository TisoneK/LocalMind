"""
DebuggerAgent — the failure-diagnosis specialist BaseAgent subclass.

A thin subclass of BaseAgent that supplies
debugger-specific context_builder, scoped tools, and is_done().

The debugger is the agent that finds ROOT CAUSES — it isolates failures,
traces through code, checks git history for regressions, and reproduces
errors. It does NOT fix bugs (coding agent), run test suites (verifier),
or assess code quality (reviewer). This clean separation keeps each
agent's responsibility clear.

Key difference from other agents:
  - CodingAgent: builds, writes, edits (constructive)
  - VerifierAgent: tests, reproduces, validates (analytical)
  - ReviewerAgent: assesses, critiques, reports (evaluative)
  - DebuggerAgent: isolates, traces, diagnoses (investigative)

Scoped toolset: file_task + git + shell + process + delegate (5 tools).
Excludes: code_exec, file_write, edit_file, web, browser, memory, sysinfo.
"""

from __future__ import annotations

import logging
from typing import Optional

from agents.base_agent import AgentConfig, BaseAgent
from agents.debugger.context_builder import build_debugger_context
from agents.debugger.is_done import is_debugger_done
from agents.debugger.tools import DEBUGGER_TOOLS
from core.models import Intent, ToolResult

logger = logging.getLogger(__name__)


class DebuggerAgent(BaseAgent):
    """
    The Debugger Agent — isolates failures and finds root causes.

    Scoped toolset: file_task, git, shell, process, delegate (5 tools).
    Cannot execute code, create/edit files, search the web, or drive a
    browser.

    Debugging pattern: capture error → read source/logs → check git →
    reproduce → isolate root cause → report + delegate fix.
    """

    def config(self) -> AgentConfig:
        return AgentConfig(
            name="debugger",
            # Debugging is iterative — hypothesis → test → refine.
            # 12 iterations balances thoroughness with efficiency.
            max_iterations=12,
            # Debugging benefits from headroom — git operations, log
            # analysis, and service restarts take time.
            max_wall_clock_secs=360,  # 6 minutes
            allowed_tools=DEBUGGER_TOOLS,
            tools_enabled=True,
        )

    def build_context(
        self,
        messages: list[dict],
        intent: Intent,
        memory_facts: Optional[list[str]] = None,
        orchestrator_context: Optional[str] = None,
    ) -> str:
        return build_debugger_context(
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
        return is_debugger_done(
            iterations=iterations,
            wall_clock_secs=wall_clock_secs,
            last_tool_result=last_tool_result,
            trace=trace,
        )

    def description(self) -> str:
        return (
            "Debugger Agent — isolates failures and finds root causes of "
            "bugs, errors, crashes, and unexpected behavior. Use this agent "
            "for debugging tasks: diagnosing test failures, tracing runtime "
            "errors, finding regression commits, isolating minimal "
            "reproductions. Scoped toolset: file_task (read source files, "
            "error logs, tracebacks), git (check what changed — diff, log), "
            "shell (run diagnostic commands, inspect state), process "
            "(start/stop services for debugging), delegate (hand off fixes "
            "to the coding agent once root cause is found). Cannot write or "
            "edit code, execute code, run test suites, search the web, or "
            "drive a browser. Think like a debugger: systematic, skeptical, "
            "precise — isolate before fixing."
        )
