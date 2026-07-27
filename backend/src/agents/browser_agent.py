"""Backward-compat shim — re-exports BrowserAgent from agents.browser.agent.

Per ADR-8 Phase 1 (Session 34): the BrowserAgent class moved INTO its
agent directory at `agents/browser/agent.py`. This thin shim preserves
backward compatibility. New code should import from
`agents.browser.agent` (or via the package: `from agents import
BrowserAgent`).

Scheduled for removal in a future Phase. Do not add new code here.
"""

from __future__ import annotations

from agents.browser.agent import BrowserAgent

__all__ = ["BrowserAgent"]
