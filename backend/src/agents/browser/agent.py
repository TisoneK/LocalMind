"""
BrowserAgent — drives a real headless browser via agent-browser.

Per ADR-6: a thin subclass of BaseAgent that supplies browser-specific
context_builder, scoped tools, and is_done().

Per ADR-8 Principle 5: this class lives inside its agent directory
(`agents/browser/agent.py`) alongside its workflow, context_builder,
tools, is_done, and (Phase 2) persona.

Why BrowserAgent first (per Session 15 implementation plan):
    - The existing backend/src/tools/browser_agent.py is already
      domain-scoped in name (it's called "browser_agent") but
      structured as a tool, not a full agent.
    - Promoting it to a full agent is the smallest-risk first concrete
      step: no existing coding/research agent to break.
    - The browser agent's scoped toolset is exactly one tool
      (Intent.BROWSE) — the smallest possible surface, ideal for
      testing the scoped-tools concept on a small model.
"""

from __future__ import annotations

import logging
from typing import Optional

from agents.base_agent import AgentConfig, BaseAgent
from agents.browser.context_builder import build_browser_context
from agents.browser.is_done import is_browser_done
from agents.browser.tools import BROWSER_TOOLS
from core.models import Intent, ToolResult

logger = logging.getLogger(__name__)


class BrowserAgent(BaseAgent):
    """
    The Browser Agent — drives a real headless browser via agent-browser.

    Scoped toolset: Intent.BROWSE only (navigate, click, fill, scroll,
    screenshot, eval JS, etc.). Cannot run shell commands, edit files,
    or execute code.

    Stop condition (Phase 2): close action / form submitted / target
    page reached / user says stop. Phase 1 delegates to the existing
    AgentLoop's termination logic.
    """

    def config(self) -> AgentConfig:
        return AgentConfig(
            name="browser",
            max_iterations=15,  # browser tasks rarely need >15 steps
            max_wall_clock_secs=240,  # 4 minutes — browser actions are slow
            allowed_tools=BROWSER_TOOLS,
            tools_enabled=True,
        )

    def build_context(
        self,
        messages: list[dict],
        intent: Intent,
        memory_facts: Optional[list[str]] = None,
        orchestrator_context: Optional[str] = None,
    ) -> str:
        return build_browser_context(
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
        return is_browser_done(
            iterations=iterations,
            wall_clock_secs=wall_clock_secs,
            last_tool_result=last_tool_result,
            trace=trace,
        )

    def description(self) -> str:
        return (
            "Browser Agent — drives a real headless browser to navigate, "
            "click, fill forms, scroll, take screenshots, and execute "
            "JavaScript. Use this agent when the task requires interacting "
            "with live web pages (logging in, filling forms, clicking "
            "buttons, reading dynamic content that needs JavaScript). "
            "Cannot run shell commands, edit local files, or execute code. "
            "Scoped toolset: browse only."
        )
