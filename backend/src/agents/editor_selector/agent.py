"""
EditorSelectorAgent — B-2026-08-02-11 (C2, best-of-N editor).

The selector in the best-of-N editing pattern. The coding agent's
`best_of_n_edit` tool generates N candidate edits (each under a different
strategy), then spawns THIS agent with all N proposals as input. The
selector is a single model call (no tools) that returns the best pick:

    {"choice": <0-based index>, "reason": "...", "suggested_improvements": "..."}

Per ADR-8 Principle 5 (Session 34): lives in its own agent directory
(`agents/editor_selector/`) so it is registry-discovered, listable, and —
thanks to B-2026-08-02-10 (C1) — can be routed to a STRONG model via
`LOCALMIND_AGENT_MODEL_EDITOR_SELECTOR=...` even when the orchestrator is
local (the spec's core motivation: the selector's pick is the highest-risk
LLM call in the pattern, so it deserves the strongest available model).
"""

from __future__ import annotations

import logging
from typing import Optional

from agents.base_agent import AgentConfig, BaseAgent
from agents.editor_selector.context_builder import build_editor_selector_context
from agents.editor_selector.is_done import is_editor_selector_done
from agents.editor_selector.tools import EDITOR_SELECTOR_TOOLS
from core.models import Intent, ToolResult

logger = logging.getLogger(__name__)


class EditorSelectorAgent(BaseAgent):
    def config(self) -> AgentConfig:
        return AgentConfig(
            name="editor_selector",
            max_iterations=1,  # single model call — no loop
            max_wall_clock_secs=60,  # 1 min — just one model call
            allowed_tools=EDITOR_SELECTOR_TOOLS,  # empty frozenset
            tools_enabled=False,  # no tool execution — pure judgment call
        )

    def build_context(
        self,
        messages: list[dict],
        intent: Intent,
        memory_facts: Optional[list[str]] = None,
        orchestrator_context: Optional[str] = None,
    ) -> str:
        return build_editor_selector_context(
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
        return is_editor_selector_done(
            iterations=iterations,
            wall_clock_secs=wall_clock_secs,
            last_tool_result=last_tool_result,
            trace=trace,
        )

    def description(self) -> str:
        return (
            "Editor Selector — single model call, no tools. Used by the "
            "best_of_n_edit workflow: receives N candidate edit proposals "
            "for one file and returns the best pick as JSON "
            '{"choice": index, "reason": "...", "suggested_improvements": "..."}. '
            "Never invoked directly by the user; spawned by best_of_n_edit."
        )
