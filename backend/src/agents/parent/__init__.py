"""LocalMind parent-agent package.

The parent is the only user-facing reasoning agent. It owns the complete
objective and delegates bounded cross-domain work to specialized agents.
"""

from agents.parent.agent import ParentAgent

__all__ = ["ParentAgent"]
