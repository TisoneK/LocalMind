"""
Delegate tool — ADR-8 Phase 3 (Session 34): agent-initiated delegation.

Per ADR-8 Principle 3: "Agents collaborate — a coding task needing
research delegates to the ResearchAgent — either parallel (both work
simultaneously) or handoff (ResearchAgent returns results, CodingAgent
continues). This replaces the current should_use_sub_agents() keyword
heuristic with agent-initiated delegation."

This tool is the agent-initiated delegation primitive. Any agent with
`delegate` in its allowed_tools can call:

    delegate(target_agent="research", task="find current weather in Nairobi")

The framework looks up the target agent in the registry (via
`agents.registry.get_agent()`), constructs it with the current adapter,
runs it via `agent.run()`, and returns the sub-agent's response as the
ToolResult content. The calling agent continues with the sub-agent's
output in its context.

Why this replaces should_use_sub_agents():
- The OLD approach: a keyword heuristic in the engine decided whether
  to decompose a task into sub-tasks BEFORE the agent loop ran. The
  model had no say in whether delegation was appropriate.
- The NEW approach: the model decides to delegate mid-loop, based on
  what it actually sees in the user's request and the tool results so
  far. The `delegate` tool is just another tool in the agent's
  toolset — the model calls it when it judges delegation is needed.

Safety:
- The target_agent must be a registered agent name (no arbitrary
  module path injection).
- The sub-agent runs with its OWN scoped toolset (CodingAgent can't
  delegate to a phantom agent that has more tools).
- Recursion depth is capped (a sub-agent can delegate further, but
  only up to MAX_DELEGATION_DEPTH = 2 — prevents infinite chains).
- The sub-agent's tools_enabled flag is honored (DirectAgent as a
  sub-agent is just a single model call, no tools).

Parallel vs handoff: this implementation is HANDOFF (the calling agent
blocks until the sub-agent finishes, then continues with the result).
Parallel delegation (both work simultaneously) is a future enhancement
that would require streaming two agent loops concurrently and
merging their outputs — significantly more complex. Handoff is the
MVP.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool

logger = logging.getLogger(__name__)

# Cap recursion depth to prevent infinite delegation chains. A
# CodingAgent delegates to ResearchAgent delegates to CodingAgent
# delegates to ResearchAgent... — without a cap, this loops forever.
# Depth 2 means: agent A delegates to B (depth 1); B can delegate to C
# (depth 2); C cannot delegate further. Sufficient for the common
# cases (coding → research → back to coding).
MAX_DELEGATION_DEPTH: int = 2

# Per-delegation wall-clock cap. The sub-agent's own max_wall_clock_secs
# still applies, but this is the OUTER cap — if the sub-agent + its own
# delegations exceed this, we abort. Prevents a single delegation from
# consuming the entire turn budget.
DELEGATION_WALL_CLOCK_SECS: int = 120  # 2 minutes


async def delegate(message: str) -> ToolResult:
    """
    Delegate a sub-task to another agent.

    Args (parsed from `message` — JSON-encoded by the agent loop):
        target_agent: the name of the agent to delegate to (e.g.,
            "research", "coding", "browser", "direct"). Must be a
            registered agent name.
        task: the sub-task description. A clear, self-contained
            instruction that the sub-agent can execute without further
            context from the calling agent.

    Returns:
        ToolResult whose content is the sub-agent's response. If the
        sub-agent failed or returned no text, the content explains
        what went wrong (the calling agent can retry or fall back).

    The calling agent continues with the sub-agent's output in its
    context (handoff semantics, not parallel).
    """
    # Parse the args from the JSON-encoded message
    try:
        # The agent loop serializes multi-param tool calls as JSON
        # (per _extract_tool_input in loop.py — same pattern as
        # edit_file). Parse it back here.
        if message.strip().startswith("{"):
            args = json.loads(message)
            target_agent = args.get("target_agent", "").strip()
            task = args.get("task", "").strip()
        else:
            # Fallback: the message is the task only; target_agent
            # was not provided. This is an error — we can't delegate
            # without knowing WHO to delegate to.
            return ToolResult(
                content=(
                    "ERROR: delegate tool requires both 'target_agent' and "
                    "'task' parameters. Got a single string where JSON was "
                    "expected. Please call delegate with target_agent and task."
                ),
                risk=RiskLevel.LOW,
                source="delegate",
                success=False,
                error_type="invalid_input",
            )
    except json.JSONDecodeError as exc:
        return ToolResult(
            content=(
                f"ERROR: could not parse delegate arguments as JSON: {exc}. "
                f"Expected format: {{\"target_agent\": \"research\", \"task\": \"...\"}}. "
                f"Got: {message[:200]!r}"
            ),
            risk=RiskLevel.LOW,
            source="delegate",
            success=False,
            error_type="invalid_input",
        )

    if not target_agent:
        return ToolResult(
            content=(
                "ERROR: delegate tool requires 'target_agent' parameter. "
                "Example: delegate(target_agent='research', task='find weather in Nairobi')"
            ),
            risk=RiskLevel.LOW,
            source="delegate",
            success=False,
            error_type="invalid_input",
        )

    if not task:
        return ToolResult(
            content=(
                f"ERROR: delegate tool requires 'task' parameter for target_agent={target_agent!r}. "
                f"Example: delegate(target_agent='research', task='find weather in Nairobi')"
            ),
            risk=RiskLevel.LOW,
            source="delegate",
            success=False,
            error_type="invalid_input",
        )

    # Look up the target agent in the registry
    try:
        from agents.registry import get_agent, list_agents
    except ImportError as exc:
        return ToolResult(
            content=f"ERROR: agents registry not available: {exc}",
            risk=RiskLevel.HIGH,
            source="delegate",
            success=False,
            error_type="registry_unavailable",
        )

    agent_class = get_agent(target_agent)
    if agent_class is None:
        registered = sorted(name for name, _ in list_agents())
        return ToolResult(
            content=(
                f"ERROR: agent {target_agent!r} is not registered. "
                f"Registered agents: {', '.join(registered)}. "
                f"Use one of those names as the target_agent."
            ),
            risk=RiskLevel.LOW,
            source="delegate",
            success=False,
            error_type="not_found",
        )

    # Check recursion depth — prevent infinite delegation chains.
    # Checked BEFORE the adapter lookup so the test for recursion_limit
    # doesn't depend on whether an adapter is set (the recursion check
    # is a hard safety limit; the adapter check is a runtime precondition).
    current_depth = _current_depth.get(0)
    if current_depth >= MAX_DELEGATION_DEPTH:
        return ToolResult(
            content=(
                f"ERROR: delegation depth limit reached ({current_depth}/{MAX_DELEGATION_DEPTH}). "
                f"The current agent was itself delegated to — further delegation would risk "
                f"an infinite chain. Handle the task directly with your own tools instead."
            ),
            risk=RiskLevel.HIGH,
            source="delegate",
            success=False,
            error_type="recursion_limit",
        )

    # Construct the sub-agent with the current adapter. The adapter is
    # passed via a thread-local / context var set by the calling agent
    # loop. If no adapter is available, we can't run the sub-agent.
    try:
        # Lazy import to avoid circular dependency
        from adapters.base import BaseAdapter  # noqa: F401  (type-only)
        # The adapter is stashed in a module-level variable by the
        # calling agent loop (see _set_current_adapter below).
        adapter = _current_adapter.get(None)
    except Exception as exc:
        return ToolResult(
            content=f"ERROR: could not access current adapter: {exc}",
            risk=RiskLevel.HIGH,
            source="delegate",
            success=False,
            error_type="adapter_unavailable",
        )

    if adapter is None:
        return ToolResult(
            content=(
                "ERROR: no adapter available for delegation. The calling "
                "agent loop must set the current adapter before delegating. "
                "This is a framework bug — report it."
            ),
            risk=RiskLevel.HIGH,
            source="delegate",
            success=False,
            error_type="adapter_unavailable",
        )

    # Construct the sub-agent and run it
    try:
        sub_agent = agent_class(adapter=adapter)
    except Exception as exc:
        return ToolResult(
            content=f"ERROR: could not construct sub-agent {target_agent!r}: {exc}",
            risk=RiskLevel.HIGH,
            source="delegate",
            success=False,
            error_type="construction_failed",
        )

    logger.info(
        "[delegate] delegating to %s (depth %d/%d, task=%r)",
        target_agent, current_depth + 1, MAX_DELEGATION_DEPTH, task[:200],
    )

    # Run the sub-agent. Use a wall-clock cap to prevent a single
    # delegation from consuming the entire turn budget. The sub-agent's
    # own max_iterations / max_wall_clock_secs also apply (via its
    # AgentConfig, honored per ADR-8 Phase 2).
    _current_depth.set(current_depth + 1)
    try:
        sub_messages = [
            {"role": "user", "content": task},
        ]

        # Determine the intent for the sub-agent. The sub-agent picks
        # its own intent internally — but we need to pass SOMETHING to
        # agent.run(). Use CHAT for now (the sub-agent's workflow +
        # scoped tools govern its behavior, not the intent). A future
        # refinement could let the calling agent pass an intent hint.
        from core.models import Intent as _Intent

        # Run the sub-agent's async generator inside a task so we can
        # apply a wall-clock timeout. asyncio.wait_for doesn't directly
        # support async generators (it expects a single awaitable), so
        # we collect all chunks inside an async helper function and
        # await THAT with a timeout.
        async def _collect_sub_agent_response() -> str:
            chunks: list[str] = []
            async for chunk in sub_agent.run(
                messages=sub_messages,
                intent=_Intent.CHAT,
                initial_tool_result=None,
                available_tools=[],  # the sub-agent's config().allowed_tools is used
                confidence=1.0,
            ):
                if chunk.text:
                    chunks.append(chunk.text)
            return "".join(chunks)

        try:
            sub_response = await asyncio.wait_for(
                _collect_sub_agent_response(),
                timeout=DELEGATION_WALL_CLOCK_SECS,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                content=(
                    f"ERROR: delegation to {target_agent!r} timed out after "
                    f"{DELEGATION_WALL_CLOCK_SECS}s. The sub-agent may still "
                    f"be running, but its output is not available. Try a "
                    f"more focused sub-task or use your own tools directly."
                ),
                risk=RiskLevel.MEDIUM,
                source="delegate",
                success=False,
                error_type="timeout",
            )

        sub_response = sub_response.strip()
        if not sub_response:
            return ToolResult(
                content=(
                    f"Sub-agent {target_agent!r} returned an empty response "
                    f"for task: {task[:200]!r}. It may have hit its own "
                    f"iteration limit or had a tool failure. Try a more "
                    f"focused sub-task or handle the task directly."
                ),
                risk=RiskLevel.MEDIUM,
                source="delegate",
                success=False,
                error_type="empty_response",
            )

        logger.info(
            "[delegate] %s returned %d chars for task %r",
            target_agent, len(sub_response), task[:100],
        )

        return ToolResult(
            content=(
                f"## Delegated to {target_agent} agent\n\n"
                f"**Sub-task:** {task}\n\n"
                f"**Sub-agent response:**\n\n{sub_response}\n"
            ),
            risk=RiskLevel.LOW,
            source="delegate",
            success=True,
            metadata={
                "target_agent": target_agent,
                "task_length": len(task),
                "response_length": len(sub_response),
                "depth": current_depth + 1,
            },
        )
    finally:
        _current_depth.set(current_depth)


# ── Adapter + recursion-depth context vars ─────────────────────────────────
#
# The calling agent loop sets the current adapter before invoking any
# tool. The delegate tool reads it to construct the sub-agent with the
# same adapter (so the sub-agent uses the same model + provider).
#
# The recursion depth is tracked per-thread (actually per-context-var)
# so a sub-agent's own delegation calls increment the depth correctly.

import contextvars  # noqa: E402  (intentional late import for clarity)

_current_adapter: contextvars.ContextVar[Optional[object]] = contextvars.ContextVar(
    "_delegate_current_adapter", default=None
)
_current_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
    "_delegate_current_depth", default=0
)


def set_current_adapter(adapter) -> None:
    """Set the current adapter for delegation. Called by the agent loop.

    The agent loop calls this at the start of each tool dispatch so the
    delegate tool can access the adapter when the model invokes it.
    """
    _current_adapter.set(adapter)


def get_current_depth() -> int:
    """Return the current delegation depth (for testing)."""
    return _current_depth.get()


# Register the tool — Intent.DELEGATE → delegate function
register_tool(
    Intent.DELEGATE,
    delegate,
    description=(
        "Delegate a sub-task to another specialized agent. Use this when "
        "the current task requires a different domain of expertise (e.g., "
        "a coding task that needs web research, or a research task that "
        "needs file analysis). The sub-agent runs with its own scoped "
        "tools and returns its result; you continue with that result in "
        "your context. Target agents: 'research' (web search + fetch), "
        "'coding' (shell + file tools + code exec), 'browser' (headless "
        "browser), 'direct' (single model call, no tools)."
    ),
    cost=1.0,  # delegation is expensive — sub-agent runs its own loop
    latency_ms=5000,  # rough estimate — sub-agent takes time
    parallelizable=False,  # handoff semantics, not parallel
)
