"""
describe_tool tool — ADR-40 option C: on-demand full-tool-context.

The `skill`-loader pattern applied to the tool catalog: the 16 LONG-TAIL
tools (browse/delegate/sql/csv/json/best_of_n/propose_*/subgoal/skill/
diagnostics) are NOT sent in the native `tools` param on every call — that
was ~9.8k chars of rarely-used schema paid on EVERY iteration. Instead the
model calls `describe_tool(name)` to pull ONE tool's full schema into its
context; the agent loop then includes that tool's schema in the `tools`
param for the REST of the run (bookkeeping lives in the loop — see
AgentLoop.loaded_tools, updated from this tool's ToolResult metadata, so it
survives the asyncio task boundary of dispatch_with_retry).

This tool is read-only: it returns schema text, never executes anything.
"""

from __future__ import annotations

import json

from core.agent.tool_schemas import (
    CORE_TOOL_NAMES,
    LONG_TAIL_TOOL_NAMES,
    TOOL_DEFINITIONS,
    get_full_tool_def,
    long_tail_tool_summary,
)
from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool


async def describe_tool(message: str) -> ToolResult:
    """Return the full usage schema for an on-demand tool.

    Args (single string from the agent loop): the tool name, e.g.
    "browse". The model sees the schema and can then call the tool with
    valid arguments on its next step (the loop has loaded it by then).
    """
    name = (message or "").strip()

    if not name:
        return ToolResult(
            content=(
                "'tool_name' is required for the describe_tool tool. "
                f"Core tools: {', '.join(sorted(CORE_TOOL_NAMES))}. "
                f"On-demand tools: {long_tail_tool_summary()}."
            ),
            risk=RiskLevel.LOW,
            source="describe_tool",
            success=False,
            error_type="validation_error",
            error_message="Missing required field 'tool_name'",
        )

    if name in CORE_TOOL_NAMES:
        # B-2026-08-30-13: do NOT re-dump the schema for a core tool — it is
        # already in the model's tools list. Dumping ~2-3k chars here (browse
        # was the worst offender) bloated context and could overflow the window.
        # Return a short nudge to call it directly instead.
        return ToolResult(
            content=(
                f"Tool {name!r} is a CORE tool — it is already loaded and in your tools "
                f"list. Call it DIRECTLY now; describe_tool is only for on-demand tools "
                f"and wastes a step on core tools."
            ),
            risk=RiskLevel.LOW,
            source="describe_tool",
            success=True,
            metadata={"tool_name": name, "already_loaded": True},
        )

    if name in LONG_TAIL_TOOL_NAMES:
        td = get_full_tool_def(name)
        if td is None:  # defensive — the sets are derived from the catalog
            return ToolResult(
                content=f"No schema found for tool {name!r}.",
                risk=RiskLevel.LOW,
                source="describe_tool",
                success=False,
                error_type="not_found",
            )
        schema = json.dumps(td, indent=2)
        return ToolResult(
            content=(
                f"Tool {name!r} is now LOADED — its full schema is below. "
                f"Call it with the native tool API on your NEXT step using "
                f"exactly these parameters:\n\n{schema}"
            ),
            risk=RiskLevel.LOW,
            source="describe_tool",
            success=True,
            metadata={
                "loaded_tool": name,
                "chars": len(schema),
                "catalog_len": len(TOOL_DEFINITIONS),
            },
        )

    return ToolResult(
        content=(
            f"Tool {name!r} not found. Core tools: {', '.join(sorted(CORE_TOOL_NAMES))}. "
            f"On-demand tools: {long_tail_tool_summary()}."
        ),
        risk=RiskLevel.LOW,
        source="describe_tool",
        success=False,
        error_type="not_found",
    )


# Register the tool — Intent.DESCRIBE_TOOL → describe_tool
register_tool(
    Intent.DESCRIBE_TOOL,
    describe_tool,
    description=(
        "Load the FULL usage schema for a capability before using it, then "
        "call it in your NEXT step. Core and on-demand tools are supported. "
        f"Core tools: {', '.join(sorted(CORE_TOOL_NAMES))}. "
        f"On-demand tools: {long_tail_tool_summary()}."
    ),
    cost=0.0,
    latency_ms=5,
    parallelizable=True,  # read-only lookup
)
