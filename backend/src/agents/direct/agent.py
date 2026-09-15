"""
DirectAgent — Direct Mode as a thin wrapper.

This class lives inside its agent directory
(`agents/direct/agent.py`) alongside its playbook, context_builder,
tools, is_done, and (Phase 2) persona.

Steps 1-2 only (assemble → model → respond). No tool execution.
tools_enabled=False. The existing engine CHAT path (Intent.CHAT) already
handles no-tool streaming; DirectAgent is the structural skeleton that
makes Direct Mode a registry lookup rather than an if/else in the chat
handler.
"""

from __future__ import annotations

import logging
from typing import Optional

from agents.base_agent import AgentConfig, BaseAgent
from agents.direct.context_builder import build_direct_context
from agents.direct.is_done import is_direct_done
from agents.direct.tools import DIRECT_TOOLS
from core.models import Intent, ToolResult

logger = logging.getLogger(__name__)


class DirectAgent(BaseAgent):
    def config(self) -> AgentConfig:
        return AgentConfig(
            name="direct",
            max_iterations=1,  # single model call — no loop
            max_wall_clock_secs=60,  # 1 min — just one model call
            allowed_tools=DIRECT_TOOLS,  # empty frozenset
            tools_enabled=False,  # the key flag — no tool execution
        )

    def build_context(
        self,
        messages: list[dict],
        intent: Intent,
        memory_facts: Optional[list[str]] = None,
        orchestrator_context: Optional[str] = None,
    ) -> str:
        return build_direct_context(
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
        return is_direct_done(
            iterations=iterations,
            wall_clock_secs=wall_clock_secs,
            last_tool_result=last_tool_result,
            trace=trace,
        )

    def description(self) -> str:
        return (
            "Direct Agent — single model call, no tools. Use this for "
            "simple chat: answering questions, explaining concepts, "
            "generating text. This is what Direct Mode becomes — a "
            "registry lookup, not a separate code path. Cannot run "
            "shell commands, edit files, execute code, search the web, "
            "or drive a browser. Just a direct conversation with the model."
        )
