"""Context pruner agent subpackage — the inline history-rewriter.

Per ADR-8 Principle 5 (Session 34, Phase 1): the agent class lives INSIDE
this directory at `agent.py`. The registry auto-discovers directories with
an `agent.py` whose class name matches <Name>Agent (or any BaseAgent
subclass for multi-word names like ContextPrunerAgent).
"""

from agents.context_pruner.agent import ContextPrunerAgent
from agents.context_pruner.context_builder import build_context_pruner_context
from agents.context_pruner.is_done import is_context_pruner_done
from agents.context_pruner.tools import CONTEXT_PRUNER_TOOLS

__all__ = [
    "ContextPrunerAgent",
    "build_context_pruner_context",
    "is_context_pruner_done",
    "CONTEXT_PRUNER_TOOLS",
]
