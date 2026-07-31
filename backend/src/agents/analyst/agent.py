"""
AnalystAgent — the requirements-analysis specialist BaseAgent subclass.

Per ADR-6 (refines ADR-5): a thin subclass of BaseAgent that supplies
analyst-specific context_builder, scoped tools, and is_done().

The analyst is the agent that understands WHAT needs to be built —
it reads specifications, clarifies requirements, and produces an
actionable description of the work. It does NOT plan implementation
(planner), write code (coding agent), or verify results (verifier).

Key difference from other agents:
  - AnalystAgent: understands, clarifies, specifies (analytical)
  - Planner: designs, sequences, organizes (architectural)
  - CodingAgent: builds, writes, edits (constructive)
  - VerifierAgent: tests, reproduces, validates (analytical)
  - ReviewerAgent: assesses, critiques, reports (evaluative)
  - DebuggerAgent: isolates, traces, diagnoses (investigative)

Scoped toolset: file_task + git + delegate (3 tools — the tightest
toolset). Excludes: shell, code_exec, file_write, edit_file, process,
web, browser, memory, sysinfo.

This is the eighth and final agent from the gap analysis (B-2026-07-31-8).
"""

from __future__ import annotations

import logging
from typing import Optional

from agents.analyst.context_builder import build_analyst_context
from agents.analyst.is_done import is_analyst_done
from agents.analyst.tools import ANALYST_TOOLS
from agents.base_agent import AgentConfig, BaseAgent
from core.models import Intent, ToolResult

logger = logging.getLogger(__name__)


class AnalystAgent(BaseAgent):
    """
    The Analyst Agent — understands what needs to be built.

    Scoped toolset: file_task, git, delegate (3 tools).
    Cannot execute code, write/edit files, run shell commands, manage
    processes, search the web, or drive a browser.

    Analysis pattern: read specs → examine project → check history →
    clarify ambiguities → produce actionable specification → delegate.
    """

    def config(self) -> AgentConfig:
        return AgentConfig(
            name="analyst",
            # Analysis is focused and quick — read specs, check project
            # context, produce a specification. 8 iterations is plenty.
            max_iterations=8,
            max_wall_clock_secs=180,  # 3 minutes
            allowed_tools=ANALYST_TOOLS,
            tools_enabled=True,
        )

    def build_context(
        self,
        messages: list[dict],
        intent: Intent,
        memory_facts: Optional[list[str]] = None,
        orchestrator_context: Optional[str] = None,
    ) -> str:
        return build_analyst_context(
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
        return is_analyst_done(
            iterations=iterations,
            wall_clock_secs=wall_clock_secs,
            last_tool_result=last_tool_result,
            trace=trace,
        )

    def description(self) -> str:
        return (
            "Analyst Agent — understands requirements and clarifies what "
            "needs to be built. Use this agent for analysis tasks: reading "
            "specifications and requirements documents, examining project "
            "structure and existing code, clarifying ambiguous user requests, "
            "and producing actionable specifications that can be handed to a "
            "planner or coding agent. Scoped toolset: file_task (read specs, "
            "docs, source files), git (check project history), delegate (hand "
            "off clarified specs to planner/coding/verifier agents). Cannot "
            "execute code, write or edit files, run shell commands, manage "
            "processes, search the web, or drive a browser. Think like a "
            "requirements analyst: understand before specifying, clarify "
            "before building."
        )
