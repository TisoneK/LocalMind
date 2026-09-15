"""Tool ownership for LocalMind's parent agent."""

from core.agent.constants import AGENT_ALLOWED_TOOLS

# Parent-only scope: the multi-agent delegation surface is parked
# compatibility residue — the Parent is the sole active agent and must not
# advertise or reach it. Excluding these from PARENT_TOOLS removes them from
# BOTH the parent's prose tool catalog (system prompt) and its native tool
# schemas on every iteration, without touching the parked child agents
# (analyst/coding/browser/...) whose own toolsets still subset the full
# AGENT_ALLOWED_TOOLS.
_PARKED_MULTI_AGENT_TOOLS = frozenset(
    {
        "delegate",  # parked (parent-only scope)
        "delegate_parallel",  # parked (parent-only scope)
        "delegate_inline",  # parked (parent-only scope)
        "best_of_n_edit",  # spawns N+1 sub-agents — parked (parent-only scope)
    }
)

PARENT_TOOLS: frozenset[str] = AGENT_ALLOWED_TOOLS - _PARKED_MULTI_AGENT_TOOLS
