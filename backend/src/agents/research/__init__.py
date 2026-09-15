"""Research agent subpackage — agent class + context_builder + tools + is_done.

The agent class lives INSIDE
this directory at `agent.py`. Co-located with its context_builder, tools,
is_done, and (Phase 2) playbook.md + persona.md.
"""

from agents.research.agent import ResearchAgent
from agents.research.context_builder import build_research_context
from agents.research.is_done import is_research_done
from agents.research.tools import RESEARCH_TOOLS

__all__ = ["ResearchAgent", "build_research_context", "is_research_done", "RESEARCH_TOOLS"]
