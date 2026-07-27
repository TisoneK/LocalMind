"""Backward-compat shim — re-exports ResearchAgent from agents.research.agent.

Per ADR-8 Phase 1 (Session 34): the ResearchAgent class moved INTO its
agent directory at `agents/research/agent.py`. This thin shim preserves
backward compatibility. New code should import from
`agents.research.agent` (or via the package: `from agents import
ResearchAgent`).

Scheduled for removal in a future Phase. Do not add new code here.
"""

from __future__ import annotations

from agents.research.agent import ResearchAgent

__all__ = ["ResearchAgent"]
