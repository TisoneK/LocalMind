"""
VerifierAgent — the verification specialist BaseAgent subclass.

A thin subclass of BaseAgent that supplies
verifier-specific context_builder, scoped tools, and is_done(). The
actual loop execution delegates to the existing AgentLoop (Phase 1).

This class lives inside its agent directory
(`agents/verifier/agent.py`) alongside its playbook, context_builder,
tools, is_done, and (Phase 2) persona.

The verifier is the agent that PROVES things work — it runs tests,
reproduces bugs, checks acceptance criteria, and validates CLI/API
behavior. It's separate from the coding agent because verification
requires a different mindset: systematic checking, failure isolation,
and clear reporting rather than building and creating.

Key difference from CodingAgent:
  - CodingAgent: builds, writes, edits (constructive)
  - VerifierAgent: tests, reproduces, validates (analytical)

Scoped toolset: shell + process + git + file_task + edit_file
+ delegate (6 tools).
Excludes: code_exec (verifier doesn't write new code), file_write (use
edit_file for targeted fixes), web/browser/memory/sysinfo.
"""

from __future__ import annotations

import logging
from typing import Optional

from agents.base_agent import AgentConfig, BaseAgent
from agents.verifier.context_builder import build_verifier_context
from agents.verifier.is_done import is_verifier_done
from agents.verifier.tools import VERIFIER_TOOLS
from core.models import Intent, ToolResult

logger = logging.getLogger(__name__)


class VerifierAgent(BaseAgent):
    """
    The Verifier Agent — runs tests, reproduces bugs, validates behavior.

    Scoped toolset: shell, process, git, file_task, edit_file, delegate
(6 tools).
    Cannot execute code (code_exec), create files (file_write), search
    the web, drive a browser, or manage memory.

    Stop condition (Phase 2): tests pass / criteria met / bug reproduced.
    Phase 1 delegates to the existing AgentLoop's termination logic.

    Benefits from the workspace_state feedback loop: git
    diff shows what changed, process status shows running services, and
    previous build/test results provide baseline for comparison.
    """

    def config(self) -> AgentConfig:
        return AgentConfig(
            name="verifier",
            # Verification tasks need moderate iterations — a typical
            # test run takes 2-3 iterations (read → run → report), but
            # bug reproduction can take more (read source → check git →
            # run multiple variations → isolate).
            max_iterations=15,
            # Verification can be slow — test suites, service startup,
            # multiple verification rounds. 8 minutes is sufficient.
            max_wall_clock_secs=480,  # 8 minutes
            allowed_tools=VERIFIER_TOOLS,
            tools_enabled=True,
        )

    def build_context(
        self,
        messages: list[dict],
        intent: Intent,
        memory_facts: Optional[list[str]] = None,
        orchestrator_context: Optional[str] = None,
    ) -> str:
        return build_verifier_context(
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
        return is_verifier_done(
            iterations=iterations,
            wall_clock_secs=wall_clock_secs,
            last_tool_result=last_tool_result,
            trace=trace,
        )

    def description(self) -> str:
        return (
            "Verifier Agent — runs tests, reproduces bugs, and validates "
            "that code works correctly. Use this agent for verification "
            "tasks: running test suites, reproducing reported bugs, "
            "checking acceptance criteria, validating CLI/API behavior, "
            "and diagnosing test failures. Scoped toolset: shell (run "
            "tests, linters, typecheckers), process (start/stop services "
            "before testing), git (check changes, diff against baseline), "
            "file_task (read test output, logs, source), edit_file "
            "(targeted bug fixes only). Cannot write new code, execute "
            "code blocks, search the web, or drive a browser. Think like "
            "a tester: systematic, skeptical, precise."
        )
