"""Tool ownership for LocalMind's parent agent."""

from core.agent.constants import AGENT_ALLOWED_TOOLS

# ADR-53 (parent-only scope): the multi-agent delegation surface is parked
# compatibility residue — the Parent is the sole active agent and must not
# advertise or reach it. Excluding these from PARENT_TOOLS removes them from
# BOTH the parent's prose tool catalog (system prompt) and its native tool
# schemas on every iteration, without touching the parked child agents
# (analyst/coding/browser/...) whose own toolsets still subset the full
# AGENT_ALLOWED_TOOLS.
_PARKED_MULTI_AGENT_TOOLS = frozenset(
    {
        "delegate",  # ADR-8 Phase 3 — parked per ADR-53
        "delegate_parallel",  # B-2026-08-02-6 — parked per ADR-53
        "delegate_inline",  # B-2026-08-02-9 — parked per ADR-53
        "best_of_n_edit",  # B-2026-08-02-11 (spawns N+1 sub-agents) — parked per ADR-53
    }
)

PARENT_TOOLS: frozenset[str] = AGENT_ALLOWED_TOOLS - _PARKED_MULTI_AGENT_TOOLS
