"""
Delegate Parallel tool — B-2026-08-02-6 (B1): parallel delegation primitive.

Borrowed from Codebuff's `spawn_agents` + `Promise.allSettled` pattern.
The single-target `delegate` tool is HANDOFF (the calling agent blocks
until the sub-agent finishes). This tool is the PARALLEL fan-out: any
agent with `delegate_parallel` in its allowed_tools can call:

    delegate_parallel(targets=[
        {"agent": "research", "task": "summarize the FastAPI docs"},
        {"agent": "analyst", "task": "list the acceptance criteria"},
    ])

All sub-agents run CONCURRENTLY via asyncio.gather. This enables the
patterns LocalMind couldn't express before: best-of-N editing,
parallel research + coding, multi-perspective review, speculative
execution.

Safety (mirrors delegate.py):
- At most MAX_PARALLEL_TARGETS (5) targets — bounds the fan-out.
- Each target's agent must be a registered agent name.
- Recursion depth is capped via the same `_current_depth` contextvar as
  `delegate` (MAX_DELEGATION_DEPTH = 2) — parallel children count as one
  deeper level each, so a child cannot delegate further than the chain
  would allow.
- The wall-clock cap (DELEGATION_WALL_CLOCK_SECS = 120s) applies to the
  GATHER, not per child — all children share the budget.
- Partial failure is first-class: one child erroring does not cancel the
  others; the caller gets every child's result (completed or failed).
- contextvars: each child task runs with its own context — the depth
  increment and run_id are set INSIDE the child coroutine, so asyncio
  task isolation keeps them correct across the gather.

Adapter: read from the same `_current_adapter` contextvar that the agent
loop sets before tool dispatch (see tools/delegate.py).
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

# Bound the fan-out — Codebuff allows a handful of parallel agents; more
# than this thrashes the model server and the context budget.
MAX_PARALLEL_TARGETS: int = 5

_DESCRIPTION = (
    "Delegate MULTIPLE independent sub-tasks to specialized agents IN PARALLEL. "
    "Use this when a task splits into pieces that can proceed simultaneously "
    "(e.g. research several topics at once, get multiple perspectives, draft "
    "multiple variants for best-of-N). Payload: {\"targets\": [{\"agent\": "
    "\"research\", \"task\": \"...\"}, ...]} — up to 5 targets. Each target's "
    "agent must be one of: research, coding, browser, verifier, reviewer, "
    "debugger, analyst, direct. All sub-agents run concurrently and the result "
    "is a summary of EVERY output, so you can compare and combine them. For a "
    "single dependent sub-task use 'delegate' (handoff) instead."
)


async def _run_child(packet: DelegationInstructionPacket, adapter, depth: int) -> DelegationResult:
    """Run ONE sub-agent for a packet; NEVER raises.

    Every failure mode is captured as a DelegationResult (construction,
    child exception, empty response) so partial failure is first-class.
    Depth/run_id are set inside this coroutine — asyncio task isolation
    keeps them scoped to this child even under gather().
    """
    parent_run_id = get_current_run_id()
    child_context = AgentRunContext.create(packet, parent_run_id=parent_run_id)
    agent_name = packet.target_agent

    try:
        from agents.registry import get_agent

        agent_class = get_agent(agent_name)
    except Exception:
        return DelegationResult(
            status="failed",
            run_id=child_context.run_id,
            agent_name=agent_name,
            error_type="construction_failed",
        )

    if agent_class is None:
        return DelegationResult(
            status="failed",
            run_id=child_context.run_id,
            agent_name=agent_name,
            error_type="not_found",
        )

    # B-2026-08-02-10 (C1): per-agent model routing — each child uses its
    # LOCALMIND_AGENT_MODEL_<NAME> override when configured (AgentConfig-
    # declared models resolve inside BaseAgent.run()); else the parent's
    # adapter. Never raises — a bad override falls back to the parent.
    child_adapter = adapter
    try:
        from core.model_router import get_adapter_for_agent as _router

        _routed = _router(agent_name)
        if _routed is not None:
            child_adapter = _routed
    except Exception as _routing_exc:
        logger.warning(
            "[delegate_parallel] per-agent routing lookup failed for %s: %s — using parent adapter",
            agent_name, _routing_exc,
        )

    try:
        sub_agent = agent_class(adapter=child_adapter)
    except Exception as exc:
        logger.warning("[delegate_parallel] could not construct %s: %s", agent_name, exc)
        return DelegationResult(
            status="failed",
            run_id=child_context.run_id,
            agent_name=agent_name,
            error_type="construction_failed",
        )

    # B-2026-08-02-9 (B4): each child runs its OWN AgentLoop, which publishes
    # its own inline-mutation scope (overwriting the parent's in this
    # context). Restore the parent's scope when the child exits.
    _parent_inline_scope = get_inline_mutation_scope()
    child_run_token = set_current_run_id(child_context.run_id)
    _current_depth.set(depth + 1)
    try:
        sub_messages = [{"role": "user", "content": packet.to_prompt()}]

        async def _collect() -> str:
            child_allowed_tools: frozenset[str] = frozenset()
            config_method = getattr(sub_agent, "config", None)
            if callable(config_method):
                child_config = config_method()
                configured = getattr(child_config, "allowed_tools", frozenset())
                child_allowed_tools = frozenset(configured).difference(packet.forbidden_tools)
            chunks: list[str] = []
            async for chunk in sub_agent.run(
                messages=sub_messages,
                intent=Intent.CHAT,
                initial_tool_result=None,
                available_tools=[],
                confidence=1.0,
                allowed_tool_names=child_allowed_tools,
            ):
                if chunk.text:
                    chunks.append(chunk.text)
            return "".join(chunks)

        output = (await _collect()).strip()
    except asyncio.CancelledError:
        # The outer gather was cancelled (wall-clock cap or abort) — let it
        # propagate; the gather wrapper converts it to a timed-out result.
        raise
    except Exception as exc:
        logger.warning("[delegate_parallel] %s child run failed: %s", agent_name, exc)
        return DelegationResult(
            status="failed",
            run_id=child_context.run_id,
            agent_name=agent_name,
            error_type="child_exception",
        )
    finally:
        _current_depth.set(depth)
        reset_current_run_id(child_run_token)
        set_inline_mutation_scope(_parent_inline_scope)  # B4: restore parent's scope

    if not output:
        return DelegationResult(
            status="failed",
            run_id=child_context.run_id,
            agent_name=agent_name,
            error_type="empty_response",
        )

    return DelegationResult(
        status="completed",
        run_id=child_context.run_id,
        agent_name=agent_name,
        output=output,
    )


def _build_summary(results: list[DelegationResult]) -> str:
    completed = sum(1 for r in results if r.status == "completed")
    lines = [
        f"## Parallel delegation — {completed}/{len(results)} sub-agents completed",
        "",
    ]
    for r in results:
        lines.append(f"### {r.agent_name} — {r.status}")
        if r.output:
            lines.append(r.output)
        else:
            lines.append(f"_(no output — {r.error_type or 'failed'})_")
        lines.append("")
    return "\n".join(lines)


async def delegate_parallel(message: str) -> ToolResult:
    """Delegate multiple independent sub-tasks to agents IN PARALLEL.

    Args (parsed from `message` — JSON-encoded by the agent loop):
        targets: list of up to MAX_PARALLEL_TARGETS objects, each with
            `agent` (registered agent name) + `task` (self-contained
            instruction), plus optional `scope`, `constraints`,
            `forbidden_tools`, `output_requirements`.

    Returns:
        ToolResult whose content is a markdown summary of every child's
        output, and whose metadata["results"] is the list of
        DelegationResult dicts (one per target). Partial failure is
        expected — one child erroring does not fail the whole call.
    """
    try:
        args = json.loads(message)
    except (json.JSONDecodeError, ValueError) as exc:
        return ToolResult(
            content=(
                f"ERROR: invalid JSON for delegate_parallel: {exc}. Expected format: "
                f'{{"targets": [{{"agent": "research", "task": "..."}}, ...]}} '
                f"(max {MAX_PARALLEL_TARGETS})."
            ),
            risk=RiskLevel.LOW,
            source="delegate_parallel",
            success=False,
            error_type="invalid_input",
        )

    if not isinstance(args, dict):
        args = {}
    targets = args.get("targets")
    if not isinstance(targets, list) or not targets:
        return ToolResult(
            content=(
                "ERROR: delegate_parallel requires a non-empty 'targets' array. "
                'Example: delegate_parallel(targets=[{"agent": "research", "task": "..."}, ...]).'
            ),
            risk=RiskLevel.LOW,
            source="delegate_parallel",
            success=False,
            error_type="invalid_input",
        )
    if len(targets) > MAX_PARALLEL_TARGETS:
        return ToolResult(
            content=(
                f"ERROR: delegate_parallel supports at most {MAX_PARALLEL_TARGETS} "
                f"targets (got {len(targets)}). Split into smaller batches or "
                "pick the most valuable sub-tasks."
            ),
            risk=RiskLevel.MEDIUM,
            source="delegate_parallel",
            success=False,
            error_type="too_many_targets",
        )

    # Build one instruction packet per target. The tool contract uses
    # `agent` as the key (Codebuff-style); the packet itself uses
    # `target_agent` — map it.
    packets: list[DelegationInstructionPacket] = []
    for i, target in enumerate(targets):
        if not isinstance(target, dict):
            return ToolResult(
                content=f"ERROR: targets[{i}] must be an object with 'agent' and 'task'.",
                risk=RiskLevel.LOW,
                source="delegate_parallel",
                success=False,
                error_type="invalid_input",
            )
        payload = dict(target)
        if "agent" in payload and "target_agent" not in payload:
            payload["target_agent"] = payload["agent"]
        try:
            packets.append(DelegationInstructionPacket.from_payload(payload))
        except ValueError as exc:
            return ToolResult(
                content=f"ERROR: invalid target at targets[{i}]: {exc}",
                risk=RiskLevel.LOW,
                source="delegate_parallel",
                success=False,
                error_type="invalid_input",
            )

    # Hard safety limits shared with the handoff delegate: recursion depth
    # and the wall-clock budget (applies to the whole gather).
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
            source="delegate_parallel",
            success=False,
            error_type="recursion_limit",
        )

    adapter = _current_adapter.get(None)
    if adapter is None:
        return ToolResult(
            content=(
                "ERROR: no adapter available for parallel delegation. The "
                "calling agent loop must set the current adapter before "
                "delegating. This is a framework bug — report it."
            ),
            risk=RiskLevel.HIGH,
            source="delegate_parallel",
            success=False,
            error_type="adapter_unavailable",
        )

    logger.info(
        "[delegate_parallel] fanning out %d children (depth %d/%d)",
        len(packets), current_depth + 1, MAX_DELEGATION_DEPTH,
    )

    try:
        gathered = await asyncio.wait_for(
            asyncio.gather(
                *[_run_child(p, adapter, current_depth) for p in packets],
                return_exceptions=True,
            ),
            timeout=DELEGATION_WALL_CLOCK_SECS,
        )
    except asyncio.TimeoutError:
        # The whole fan-out exceeded the budget — report every child as
        # timed out (they were cancelled by wait_for).
        results = [
            DelegationResult(
                status="timed_out",
                run_id="",
                agent_name=p.target_agent,
                error_type="timeout",
            )
            for p in packets
        ]
        content = _build_summary(results) + (
            f"\n_All {len(results)} sub-agents were cancelled after the "
            f"{DELEGATION_WALL_CLOCK_SECS}s parallel-delegation budget._"
        )
        return ToolResult(
            content=content,
            risk=RiskLevel.MEDIUM,
            source="delegate_parallel",
            success=False,
            error_type="wall_clock_cap",
            metadata={"results": [r.to_metadata() for r in results]},
        )

    # Normalize: a stray exception from gather (shouldn't happen — children
    # never raise, but be defensive) becomes a failed result.
    results = []
    for packet, outcome in zip(packets, gathered):
        if isinstance(outcome, DelegationResult):
            results.append(outcome)
        else:
            results.append(
                DelegationResult(
                    status="failed",
                    run_id="",
                    agent_name=packet.target_agent,
                    error_type="child_exception",
                )
            )

    completed = [r for r in results if r.status == "completed"]
    content = _build_summary(results)
    tool_kwargs = dict(
        content=content,
        risk=RiskLevel.MEDIUM if not completed else RiskLevel.LOW,
        source="delegate_parallel",
        success=bool(completed),  # partial success counts; all-failed is an error
        metadata={
            "target_count": len(packets),
            "completed": len(completed),
            "results": [r.to_metadata() for r in results],
        },
    )
    if not completed:
        # error_type has a default of "" — only set it on failure (matches
        # the handoff delegate's success ToolResults, which omit it).
        tool_kwargs["error_type"] = "all_children_failed"
    return ToolResult(**tool_kwargs)


# Register the tool — Intent.DELEGATE_PARALLEL → delegate_parallel function.
register_tool(
    Intent.DELEGATE_PARALLEL,
    delegate_parallel,
    description=_DESCRIPTION,
    cost=1.5,  # parallel fan-out is the most expensive primitive
    latency_ms=5000,  # rough estimate — children run concurrently
    parallelizable=True,  # B-2026-08-02-6: this IS the parallel primitive
)
