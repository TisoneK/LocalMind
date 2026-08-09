"""Editor selector agent subpackage — the best-of-N picker.

Per ADR-8 Principle 5 (Session 34, Phase 1): the agent class lives INSIDE
this directory at `agent.py`. The registry auto-discovers directories with
an `agent.py` whose class name matches <Name>Agent.
"""

from agents.editor_selector.agent import EditorSelectorAgent
from agents.editor_selector.context_builder import build_editor_selector_context
from agents.editor_selector.is_done import is_editor_selector_done
from agents.editor_selector.tools import EDITOR_SELECTOR_TOOLS

__all__ = [
    "EditorSelectorAgent",
    "build_editor_selector_context",
    "is_editor_selector_done",
    "EDITOR_SELECTOR_TOOLS",
]
