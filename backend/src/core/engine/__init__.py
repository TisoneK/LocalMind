"""Compatibility exports for LocalMind's parent-agent runtime.

The request execution model no longer lives in a domain-routing pipeline.
`AgentRuntime` owns lifecycle concerns and sends each non-blocked turn to the
LocalMind parent agent; the parent owns tool selection, delegation, evaluation,
and final synthesis. `Engine` remains an import-compatible alias for API and
external callers while the old pipeline module is removed.
"""

from __future__ import annotations

# Re-export the public API so `from core.engine import Engine` still works.
# Also re-export get_adapter because tests patch `core.engine.get_adapter`.
from adapters import get_adapter
from core.agent_runtime import AgentRuntime

Engine = AgentRuntime

__all__ = ["AgentRuntime", "Engine", "get_adapter"]
