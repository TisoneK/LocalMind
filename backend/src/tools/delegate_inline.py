"""
Delegate Inline tool — inline delegation.

Borrowed from Codebuff's `spawn_agent_inline`. Unlike `delegate`
(handoff — the child returns a result and the parent continues with it)
and `delegate_parallel` (fan-out — children run concurrently), inline
delegation lets a special child agent REWRITE the parent's live message
history in place:

    delegate_inline(target_agent="context_pruner", task="summarize the tool results")

This is the riskiest delegation primitive because it breaks the strict
isolation invariant — the child can corrupt the parent's transcript.
Mitigations (per the B4 spec):
  (a) only agents whose AgentConfig sets `allow_inline_mutation=True`
      can be spawned inline (currently only ContextPrunerAgent);
  (b) the parent's pre-mutation history is snapshotted to disk under
      <localmind_home>/inline_mutations/ for debugging;
  (c) the mutation is logged via obs events ("inline_mutation").
  (d) the rewrite is fail-safe: the parent's mutate closure structurally
      validates the rewritten history (roles, tool_call_id pairing,
      size bounds, no trailing tool role) and refuses to apply an
      invalid rewrite.

Mechanics:
  - The parent AgentLoop.run() publishes an InlineMutationScope (its
    `loop_messages` list BY REFERENCE + a mutate callback) into a
    contextvar before its main loop. This tool reads that scope.
  - The child runs with the PARENT'S messages list (not a copy) and a
    `mutate_parent_history` callback. The child is read-only on the
    messages; the ONLY write path is the callback, which validates and
    replaces in place.
  - The parent's scope is restored around the child run (and around all
    child runs in delegate/delegate_parallel) so a nested agent loop can
    never leave its own scope in place of the parent's.
"""

from __future__ import annotations

import asyncio
import json
import logging

from core.agent.delegation import (
    AgentRunContext,
    DelegationInstructionPacket,
    DelegationResult,
    get_current_run_id,
    get_inline_mutation_scope,
    reset_current_run_id,
    reset_inline_mutation_scope,
    set_current_run_id,
    set_inline_mutation_scope,
)
from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool
from tools.delegate import (
    DELEGATION_WALL_CLOCK_SECS,
    MAX_DELEGATION_DEPTH,
    _current_adapter,
    _current_depth,
)

logger = logging.getLogger(__name__)

_DESCRIPTION = (
    "Delegate an INLINE transformation to a special agent that can REWRITE "
    "this conversation's history in place. Only agents explicitly marked "
    "inline-capable accept this — currently only 'context_pruner', which "
    "summarizes/compacts the message history when it grows too long. The "
    "pre-mutation history is snapshotted to disk for debugging. Use "
    "sparingly — it changes what you will see in subsequent steps. "
    "Payload: {\"target_agent\": \"context_pruner\", \"task\": \"summarize the "
    "tool results and older turns, keep the user's latest message verbatim\"}."
)


async def delegate_inline(message: str) -> ToolResult:
    """Delegate an inline rewrite of the parent's history to an inline-capable agent.

    Args (parsed from `message` — JSON-encoded by the agent loop):
        target_agent: the inline-capable agent name (must have
            AgentConfig.allow_inline_mutation=True — currently only
            "context_pruner").
        task: the rewrite/prune instruction given to the child.

    Returns:
        ToolResult whose content reports whether the parent's history was
        rewritten (with before/after message counts) and whose metadata
        carries the snapshot path and run ids.
    """
    # Parse the args (mirrors delegate.py).
    try:
        if message.strip().startswith("{"):
            args = json.loads(message)
            packet = DelegationInstructionPacket.from_payload(args)
            target_agent = packet.target_agent
            task = packet.objective
        else:
            return ToolResult(
                content=(
                    "ERROR: delegate_inline requires both 'target_agent' and "
                    "'task' parameters. Got a single string where JSON was "
                    "expected. Please call delegate_inline with target_agent "
                    "and task."
                ),
                risk=RiskLevel.LOW,
                source="delegate_inline",
                success=False,
                error_type="invalid_input",
            )
    except (json.JSONDecodeError, ValueError) as exc:
        return ToolResult(
            content=(
                f"ERROR: invalid inline delegation instruction: {exc}. "
                f"Expected format: {{\"target_agent\": \"context_pruner\", "
                f"\"task\": \"...\"}}. Got: {message[:200]!r}"
            ),
            risk=RiskLevel.LOW,
            source="delegate_inline",
            success=False,
            error_type="invalid_input",
        )

    if not target_agent:
        return ToolResult(
            content=(
                "ERROR: delegate_inline requires 'target_agent' parameter. "
                "Example: delegate_inline(target_agent='context_pruner', "
                "task='summarize the conversation')."
            ),
            risk=RiskLevel.LOW,
            source="delegate_inline",
            success=False,
            error_type="invalid_input",
        )

    if not task:
        return ToolResult(
            content=(
                f"ERROR: delegate_inline requires 'task' parameter for "
                f"target_agent={target_agent!r}."
            ),
            risk=RiskLevel.LOW,
            source="delegate_inline",
            success=False,
            error_type="invalid_input",
        )

    # The inline scope must be active — delegate_inline is only valid
    # INSIDE an agent loop that has published its message list.
    scope = get_inline_mutation_scope()
    if scope is None:
        return ToolResult(
            content=(
                "ERROR: delegate_inline requires an active agent-loop scope. "
                "The calling agent loop must publish its message list before "
                "dispatching inline delegation. This is a framework error — "
                "report it."
            ),
            risk=RiskLevel.HIGH,
            source="delegate_inline",
            success=False,
            error_type="not_inline_context",
        )

    parent_run_id = get_current_run_id()
    current_depth = _current_depth.get(0)
    if current_depth >= MAX_DELEGATION_DEPTH:
        return ToolResult(
            content=(
                f"ERROR: delegation depth limit reached ({current_depth}/"
                f"{MAX_DELEGATION_DEPTH}). The current agent was itself "
                "delegated to — further delegation would risk an infinite "
                "chain. Handle the task directly with your own tools instead."
            ),
            risk=RiskLevel.HIGH,
            source="delegate_inline",
            success=False,
            error_type="recursion_limit",
        )

    # Look up the target agent.
    try:
        from agents.registry import get_agent, list_agents
    except ImportError as exc:
        return ToolResult(
            content=f"ERROR: agents registry not available: {exc}",
            risk=RiskLevel.HIGH,
            source="delegate_inline",
            success=False,
            error_type="registry_unavailable",
        )

    agent_class = get_agent(target_agent)
    if agent_class is None:
        registered = sorted(name for name, _ in list_agents())
        return ToolResult(
            content=(
                f"ERROR: agent {target_agent!r} is not registered. "
                f"Registered agents: {', '.join(registered)}."
            ),
            risk=RiskLevel.LOW,
            source="delegate_inline",
            success=False,
            error_type="not_found",
        )

    # Parent adapter + per-agent model routing (C1), same as delegate.
    adapter = _current_adapter.get(None)
    if adapter is None:
        return ToolResult(
            content=(
                "ERROR: no adapter available for inline delegation. The "
                "calling agent loop must set the current adapter before "
                "delegating. This is a framework bug — report it."
            ),
            risk=RiskLevel.HIGH,
            source="delegate_inline",
            success=False,
            error_type="adapter_unavailable",
        )
    try:
        from core.model_router import get_adapter_for_agent as _router

        _routed = _router(target_agent)
        if _routed is not None:
            adapter = _routed
            logger.info(
                "[delegate_inline] %s → per-agent adapter (model=%s)",
                target_agent, getattr(_routed, "_model", "?"),
            )
    except Exception as _routing_exc:
        logger.warning(
            "[delegate_inline] per-agent routing lookup failed for %s: %s — using parent adapter",
            target_agent, _routing_exc,
        )

    child_context = AgentRunContext.create(packet, parent_run_id=parent_run_id)
    try:
        sub_agent = agent_class(adapter=adapter)
        child_config = sub_agent.config()
        if not getattr(child_config, "allow_inline_mutation", False):
            # Mitigation (a): only agents that opt in can be spawned inline.
            report = DelegationResult(
                status="failed",
                run_id=child_context.run_id,
                agent_name=target_agent,
                error_type="inline_mutation_not_allowed",
            )
            return ToolResult(
                content=(
                    f"ERROR: agent {target_agent!r} does not allow inline "
                    "mutation. Only agents with allow_inline_mutation=True "
                    "can be spawned via delegate_inline (currently only "
                    "'context_pruner'). Use 'delegate' (handoff) instead — "
                    "the child cannot rewrite the parent's history."
                ),
                risk=RiskLevel.HIGH,
                source="delegate_inline",
                success=False,
                error_type="inline_mutation_not_allowed",
                metadata={
                    "instruction": packet.to_metadata(),
                    "run": child_context.to_metadata(),
                    "delegation": report.to_metadata(),
                },
            )
    except Exception as exc:
        report = DelegationResult(
            status="failed",
            run_id=child_context.run_id,
            agent_name=target_agent,
            error_type="construction_failed",
        )
        return ToolResult(
            content=(
                f"ERROR: could not construct inline agent {target_agent!r}: "
                f"{exc}. Handle the task directly with your own tools."
            ),
            risk=RiskLevel.HIGH,
            source="delegate_inline",
            success=False,
            error_type="construction_failed",
            metadata={
                "instruction": packet.to_metadata(),
                "run": child_context.to_metadata(),
                "delegation": report.to_metadata(),
            },
        )

    logger.info(
        "[delegate_inline] inline delegation to %s (depth %d/%d, task=%r, "
        "parent_messages=%d)",
        target_agent, current_depth + 1, MAX_DELEGATION_DEPTH,
        task[:200], len(scope.messages),
    )

    # Run the child with the PARENT'S messages BY REFERENCE and the mutate
    # callback. The child must not inherit the inline scope (its own tools,
    # if any, must not be able to rewrite the parent behind its back) — the
    # parent's scope is restored in `finally`.
    _parent_scope = get_inline_mutation_scope()
    _clear_token = set_inline_mutation_scope(None)
    child_run_token = set_current_run_id(child_context.run_id)
    _current_depth.set(current_depth + 1)
    _before_count = len(scope.messages)
    try:
        async def _collect() -> str:
            chunks: list[str] = []
            async for chunk in sub_agent.run(
                messages=scope.messages,  # parent history BY REFERENCE
                intent=Intent.CHAT,
                initial_tool_result=None,
                available_tools=[],
                confidence=1.0,
                allowed_tool_names=frozenset(),
                mutate_parent_history=scope.mutate,  # the ONLY write path
                task=task,
            ):
                if chunk.text:
                    chunks.append(chunk.text)
            return "".join(chunks)

        try:
            child_response = await asyncio.wait_for(
                _collect(),
                timeout=DELEGATION_WALL_CLOCK_SECS,
            )
        except asyncio.TimeoutError:
            report = DelegationResult(
                status="timed_out",
                run_id=child_context.run_id,
                agent_name=target_agent,
                error_type="timeout",
            )
            return ToolResult(
                content=(
                    f"ERROR: inline delegation to {target_agent!r} timed out "
                    f"after {DELEGATION_WALL_CLOCK_SECS}s. The parent history "
                    "was NOT rewritten."
                ),
                risk=RiskLevel.MEDIUM,
                source="delegate_inline",
                success=False,
                error_type="timeout",
                metadata={
                    "instruction": packet.to_metadata(),
                    "run": child_context.to_metadata(),
                    "delegation": report.to_metadata(),
                },
            )
        except Exception as exc:
            logger.warning("[delegate_inline] %s child run failed: %s", target_agent, exc)
            report = DelegationResult(
                status="failed",
                run_id=child_context.run_id,
                agent_name=target_agent,
                error_type="child_exception",
            )
            return ToolResult(
                content=(
                    f"ERROR: inline agent {target_agent!r} failed: {exc}. "
                    "The parent history was NOT rewritten."
                ),
                risk=RiskLevel.MEDIUM,
                source="delegate_inline",
                success=False,
                error_type="child_exception",
                metadata={
                    "instruction": packet.to_metadata(),
                    "run": child_context.to_metadata(),
                    "delegation": report.to_metadata(),
                },
            )
    finally:
        _current_depth.set(current_depth)
        reset_current_run_id(child_run_token)
        reset_inline_mutation_scope(_clear_token)
        set_inline_mutation_scope(_parent_scope)  # restore parent's scope

    _after_count = len(scope.messages)
    # `scope.applied` is the correct success signal — a rewrite that keeps
    # the same message count (content-only pruning) is still a successful
    # mutation; the count difference is informational only.
    _applied = scope.applied
    status_line = (
        f"## Inline delegation to {target_agent}\n\n"
        f"**Task:** {task}\n\n"
        f"**Result:** {'history rewritten' if _applied else 'history unchanged'}"
    )
    if _applied:
        status_line += f" ({_before_count} → {_after_count} messages)"
    if child_response.strip():
        status_line += f"\n\n**Child report:**\n\n{child_response.strip()}\n"

    report = DelegationResult(
        status="completed" if _applied else "failed",
        run_id=child_context.run_id,
        agent_name=target_agent,
        output=child_response.strip(),
        error_type="" if _applied else "no_mutation",
    )
    return ToolResult(
        content=status_line,
        risk=RiskLevel.LOW if _applied else RiskLevel.MEDIUM,
        source="delegate_inline",
        success=_applied,
        metadata={
            "target_agent": target_agent,
            "task_length": len(task),
            "mutated": _applied,
            "before_count": _before_count,
            "after_count": _after_count,
            "depth": current_depth + 1,
            "instruction": packet.to_metadata(),
            "run": child_context.to_metadata(),
            "delegation": report.to_metadata(),
        },
    )


# Register the tool — Intent.DELEGATE_INLINE → delegate_inline function.
register_tool(
    Intent.DELEGATE_INLINE,
    delegate_inline,
    description=_DESCRIPTION,
    cost=1.2,  # inline child runs its own model call AND rewrites state
    latency_ms=5000,
    parallelizable=False,  # mutation is not concurrency-safe
)
