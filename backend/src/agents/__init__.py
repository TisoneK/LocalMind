"""
agents — LocalMind's multi-agent architecture package.

Multiple distinct agents (browser,
coding, research, direct) sharing a common 5-step loop shape, each
with its own scoped toolset, context builder, and stop condition.

Agents are
directories, not modules. Each agent lives in its own subpackage at
`agents/<name>/` containing `agent.py` (the class), `context_builder.py`,
`is_done.py`, `tools.py`, `__init__.py` (re-exports the class), and
(Phase 2) `playbook.md` + `persona.md`. The registry auto-discovers
directories with `agent.py` — adding a new agent = adding a new
directory, no manual `register()` call needed.

Public API:
    from agents import BaseAgent, BrowserAgent, get_agent, list_agents

    # Look up an agent by name (the UI picker / intent router does this)
    agent_class = get_agent("browser")
    agent = agent_class(adapter=some_adapter)

    # List all registered agents (the UI picker shows these)
    for name, cls in list_agents():
        print(f"{name}: {cls(adapter=None).description()}")

Adding a new agent:
    1. Create agents/<name>/agent.py with a BaseAgent subclass
    2. Create agents/<name>/{context_builder,is_done,tools}.py
    3. Update agents/<name>/__init__.py to re-export the class
    4. The registry auto-discovers it on next import — no edit needed here

Legacy path (still supported via backward-compat shims):
    from agents.coding_agent import CodingAgent  # ← shim → agents.coding.agent
"""

from __future__ import annotations

from agents.analyst.agent import AnalystAgent
from agents.base_agent import DEFAULT_MAX_ITERATIONS, DEFAULT_MAX_WALL_CLOCK_SECS, AgentConfig, BaseAgent
from agents.browser.agent import BrowserAgent
from agents.coding.agent import CodingAgent
from agents.debugger.agent import DebuggerAgent
from agents.direct.agent import DirectAgent
from agents.parent.agent import ParentAgent
from agents.registry import auto_discover_agents, get_agent, is_registered, list_agents, register
from agents.research.agent import ResearchAgent
from agents.reviewer.agent import ReviewerAgent
from agents.selection import (
    intent_to_agent_name,
    list_intent_mappings,
    primary_domain_to_agent_name,
    select_agent,
    select_agent_by_task_profile,
)
from agents.verifier.agent import VerifierAgent

# Auto-register all built-in agents via directory discovery.
# Scans agents/* for subdirectories
# with agent.py and registers their classes under the directory name.
# The explicit imports above (BrowserAgent, CodingAgent, etc.) ensure
# the agent subpackages are loaded BEFORE auto_discover scans them —
# otherwise pkgutil might not see them yet on a cold-start.
auto_discover_agents()

__all__ = [
    "BaseAgent",
    "AgentConfig",
    "BrowserAgent",
    "ParentAgent",
    "CodingAgent",
    "DirectAgent",
    "ResearchAgent",
    "VerifierAgent",
    "ReviewerAgent",
    "DebuggerAgent",
    "AnalystAgent",
    "DEFAULT_MAX_ITERATIONS",
    "DEFAULT_MAX_WALL_CLOCK_SECS",
    "auto_discover_agents",
    "get_agent",
    "intent_to_agent_name",
    "is_registered",
    "list_agents",
    "list_intent_mappings",
    "primary_domain_to_agent_name",
    "register",
    "select_agent",
    "select_agent_by_task_profile",
]
