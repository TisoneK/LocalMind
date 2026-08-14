"""Tool ownership for LocalMind's parent agent."""

from core.agent.constants import AGENT_ALLOWED_TOOLS

# The parent owns the complete registered surface. Specialized child agents
# narrow this set in their own `tools.py` files.
PARENT_TOOLS: frozenset[str] = AGENT_ALLOWED_TOOLS
