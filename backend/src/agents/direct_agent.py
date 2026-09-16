"""Backward-compat shim — re-exports DirectAgent from agents.direct.agent.

The DirectAgent class moved INTO its
agent directory at `agents/direct/agent.py`. This thin shim preserves
backward compatibility. New code should import from
`agents.direct.agent` (or via the package: `from agents import
DirectAgent`).

Scheduled for removal in a future Phase. Do not add new code here.
"""

from __future__ import annotations

from agents.direct.agent import DirectAgent

__all__ = ["DirectAgent"]
