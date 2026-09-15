"""Coding agent subpackage — agent class + context_builder + tools + is_done.

The agent class lives INSIDE
this directory at `agent.py`. Co-located with its context_builder, tools,
is_done, and (Phase 2) playbook.md + persona.md.
"""

from agents.coding.agent import CodingAgent
from agents.coding.context_builder import build_coding_context
from agents.coding.is_done import is_coding_done
from agents.coding.tools import CODING_TOOLS

__all__ = ["CodingAgent", "build_coding_context", "is_coding_done", "CODING_TOOLS"]
