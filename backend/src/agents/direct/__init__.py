"""Direct agent subpackage — agent class + context_builder + tools + is_done.

Per ADR-8 Principle 5 (Session 34, Phase 1): the agent class lives INSIDE
this directory at `agent.py`. Co-located with its context_builder, tools,
is_done, and (Phase 2) playbook.md + persona.md.
"""

from agents.direct.agent import DirectAgent
from agents.direct.context_builder import build_direct_context
from agents.direct.is_done import is_direct_done
from agents.direct.tools import DIRECT_TOOLS

__all__ = ["DirectAgent", "build_direct_context", "is_direct_done", "DIRECT_TOOLS"]
