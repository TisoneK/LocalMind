"""LocalMind's user-facing parent agent."""

from __future__ import annotations

from typing import Optional

from agents.base_agent import AgentConfig, BaseAgent
from agents.parent.context_builder import build_parent_context
from agents.parent.is_done import is_parent_done
from agents.parent.tools import PARENT_TOOLS
from core.models import Intent, ToolResult


class ParentAgent(BaseAgent):
    """Own the user objective and coordinate specialized child agents."""

    def config(self) -> AgentConfig:
        return AgentConfig(
            name="parent",
            max_iterations=20,
            max_wall_clock_secs=600,
            allowed_tools=PARENT_TOOLS,
            tools_enabled=True,
        )

    def build_context(
        self,
        messages: list[dict],
        intent: Intent,
        memory_facts: Optional[list[str]] = None,
        orchestrator_context: Optional[str] = None,
    ) -> str:
        return build_parent_context(
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
        return is_parent_done(iterations, wall_clock_secs, last_tool_result, trace)

    def description(self) -> str:
        return (
            "LocalMind parent agent — the only user-facing agent. It owns the "
            "complete objective, uses the full tool surface, delegates bounded "
            "cross-domain work to specialized agents, evaluates evidence, "
            "replans when needed, and returns the final grounded answer."
        )
