"""
agents — LocalMind's multi-agent architecture package.

Implements ADR-6 (refines ADR-5): multiple distinct agents (browser,
coding, research, direct) sharing a common 5-step loop shape, each
with its own scoped toolset, context builder, and stop condition.

Public API:
    from agents import BaseAgent, BrowserAgent, get_agent, list_agents

    # Look up an agent by name (the UI picker / intent router does this)
    agent_class = get_agent("browser")
    agent = agent_class(adapter=some_adapter)

    # List all registered agents (the UI picker shows these)
    for name, cls in list_agents():
        print(f"{name}: {cls(adapter=None).description()}")

Phase 1 (Session 15): only BrowserAgent is registered. The existing
AgentLoop continues to handle all other traffic. Adding CodingAgent,
ResearchAgent, DirectAgent in future sessions is a matter of:
    1. Subclassing BaseAgent
    2. Calling register("name", AgentClass) below
    3. Wiring the intent router / UI picker to call get_agent(name)
"""

from __future__ import annotations

from agents.base_agent import DEFAULT_MAX_ITERATIONS, DEFAULT_MAX_WALL_CLOCK_SECS, AgentConfig, BaseAgent
from agents.browser_agent import BrowserAgent
from agents.coding_agent import CodingAgent
from agents.registry import get_agent, is_registered, list_agents, register

# Auto-register all built-in agents at import time.
# Each agent registers itself under its short name. The UI picker and
# intent router look up agents by name via get_agent().
#
# To add a new agent:
#   1. Create agents/<name>_agent.py with a BaseAgent subclass
#   2. Create agents/<name>/ subpackage with context_builder, tools, is_done
#   3. Import the class here and call register("<name>", AgentClass)
register("browser", BrowserAgent)
register("coding", CodingAgent)

__all__ = [
    "BaseAgent",
    "AgentConfig",
    "BrowserAgent",
    "CodingAgent",
    "DEFAULT_MAX_ITERATIONS",
    "DEFAULT_MAX_WALL_CLOCK_SECS",
    "get_agent",
    "is_registered",
    "list_agents",
    "register",
]
