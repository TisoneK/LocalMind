"""
ReviewerAgent — the code review specialist BaseAgent subclass.

A thin subclass of BaseAgent that supplies
reviewer-specific context_builder, scoped tools, and is_done().

The reviewer is the agent that ASSESSES quality — it reads code, checks
it against specifications and best practices, and reports findings. It
does NOT edit code (coding agent), run tests (verifier agent), or build
features. This clean separation keeps each agent's responsibility clear.

Key difference from other agents:
  - CodingAgent: builds, writes, edits (constructive)
  - VerifierAgent: tests, reproduces, validates (analytical)
  - ReviewerAgent: assesses, critiques, reports (evaluative)

Scoped toolset: file_task + git + shell + delegate (4 tools).
Excludes: code_exec, file_write, edit_file, process, web, browser, memory.
"""

from __future__ import annotations

import logging
from typing import Optional

from agents.base_agent import AgentConfig, BaseAgent
from agents.reviewer.context_builder import build_reviewer_context
from agents.reviewer.is_done import is_reviewer_done
from agents.reviewer.tools import REVIEWER_TOOLS
from core.models import Intent, ToolResult

logger = logging.getLogger(__name__)


class ReviewerAgent(BaseAgent):
    """
    The Reviewer Agent — assesses code quality and spec conformance.

    Scoped toolset: file_task, git, shell, delegate (4 tools).
    Cannot execute code, create/edit files, manage processes, search
    the web, or drive a browser.

    Review dimensions: correctness, style, performance, security, tests.
    Reports findings with specific, actionable feedback. Does NOT fix
    issues — hands off to the coding agent when fixes are needed.
    """

    def config(self) -> AgentConfig:
        return AgentConfig(
            name="reviewer",
            # Reviews are thorough but relatively quick — read files,
            # check diff, run linters, report. 10 iterations is plenty.
            max_iterations=10,
            max_wall_clock_secs=300,  # 5 minutes
            allowed_tools=REVIEWER_TOOLS,
            tools_enabled=True,
            # SPECIFIC sub-agent with a FIXED
            # output schema. The reviewer must return JSON in exactly this
            # shape — issues with severity/file/line/description plus a
            # verdict — so the parent can parse it without re-reading prose.
            output_schema={
                "issues": [
                    {
                        "severity": "critical | major | minor | nit",
                        "file": "path/to/file.py",
                        "line": 42,
                        "description": "What's wrong and the suggested fix direction",
                    }
                ],
                "verdict": "approved | changes_requested",
                "summary": "One-paragraph assessment",
            },
        )

    def build_context(
        self,
        messages: list[dict],
        intent: Intent,
        memory_facts: Optional[list[str]] = None,
        orchestrator_context: Optional[str] = None,
    ) -> str:
        return build_reviewer_context(
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
        return is_reviewer_done(
            iterations=iterations,
            wall_clock_secs=wall_clock_secs,
            last_tool_result=last_tool_result,
            trace=trace,
        )

    def description(self) -> str:
        return (
            "Reviewer Agent — assesses whether implementations satisfy "
            "specifications and quality requirements. Use this agent for "
            "code review tasks: checking new or changed code for correctness, "
            "style conformance, performance issues, security vulnerabilities, "
            "and test coverage. Scoped toolset: file_task (read source files "
            "and specs), git (check what changed), shell (run linters and "
            "static analysis), delegate (hand off findings to coding/verifier "
            "agents). Cannot write or edit code, execute code, run tests, "
            "manage processes, search the web, or drive a browser. Think like "
            "a code reviewer: thorough, evidence-backed, constructive."
        )
