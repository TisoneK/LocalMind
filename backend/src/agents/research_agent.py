"""
ResearchAgent — web research specialist.

Scoped toolset: web_search + web_fetch (2 tools). Cannot run shell,
edit files, execute code, or drive a browser. Stop condition (Phase 2):
enough sources gathered / query exhausted.
"""

from __future__ import annotations

import logging
from typing import Optional

from agents.base_agent import AgentConfig, BaseAgent
from agents.research import RESEARCH_TOOLS, build_research_context, is_research_done
from core.models import Intent, ToolResult

logger = logging.getLogger(__name__)


class ResearchAgent(BaseAgent):
    def config(self) -> AgentConfig:
        return AgentConfig(
            name="research",
            max_iterations=10,  # research rarely needs >10 search/fetch cycles
            max_wall_clock_secs=300,  # 5 min — web calls are slow but bounded
            allowed_tools=RESEARCH_TOOLS,
            tools_enabled=True,
        )

    def build_context(
        self,
        messages: list[dict],
        intent: Intent,
        memory_facts: Optional[list[str]] = None,
        orchestrator_context: Optional[str] = None,
    ) -> str:
        return build_research_context(
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
        return is_research_done(
            iterations=iterations,
            wall_clock_secs=wall_clock_secs,
            last_tool_result=last_tool_result,
            trace=trace,
        )

    def description(self) -> str:
        return (
            "Research Agent — searches the web and reads documents to answer "
            "questions. Use this agent for research tasks: finding current "
            "information, reading articles, comparing sources, summarizing "
            "web content. Scoped toolset: web_search (find sources) and "
            "web_fetch (read a specific URL). Cannot run shell commands, "
            "edit files, execute code, or drive a browser. Track your "
            "sources and synthesize findings into a coherent answer."
        )
