"""Browser agent subpackage — agent class + context_builder + tools + is_done.

Per ADR-8 Principle 5 (Session 34, Phase 1): the agent class lives INSIDE
this directory at `agent.py`. Co-located with its context_builder, tools,
is_done, and (Phase 2) playbook.md + persona.md.
"""

from agents.browser.agent import BrowserAgent
from agents.browser.context_builder import build_browser_context
from agents.browser.is_done import is_browser_done
from agents.browser.tools import BROWSER_TOOLS

__all__ = ["BrowserAgent", "build_browser_context", "is_browser_done", "BROWSER_TOOLS"]
