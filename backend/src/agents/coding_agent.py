"""Backward-compat shim — re-exports CodingAgent from agents.coding.agent.

The CodingAgent class moved INTO its
agent directory at `agents/coding/agent.py`. This thin shim preserves
backward compatibility for any code that imports
`from agents.coding_agent import CodingAgent` (e.g., the test at
`tests/agents/test_coding_agent.py:211`). New code should import from
`agents.coding.agent` (or via the package: `from agents import
CodingAgent`).

This file is scheduled for removal in a future Phase (after all import
sites are migrated). Do not add new code here.
"""

from __future__ import annotations

from agents.coding.agent import CodingAgent

__all__ = ["CodingAgent"]
