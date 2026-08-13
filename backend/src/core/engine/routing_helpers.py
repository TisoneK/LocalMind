"""
Routing + planning helpers for the engine (Session 129 decomposition).

Extracted from ``core/engine/_pipeline.py`` — the pure planning-skip and
fallback-plan decisions, kept module-level so tests can import the exact
source of truth (``tests/core/test_planning_skip.py`` imports
``_should_skip_planning``; ``tests/e2e/test_todo_system.py`` derives its
expectations from ``_fallback_todo_plan``).

``core/engine/_pipeline.py`` re-imports every symbol here for backward
compatibility.
"""

from __future__ import annotations

from core.models import Intent


def _dispatcher_plan_context(graph) -> str:
    """Format an ExecutionGraph into an orchestrator-style plan text.

    The ThinkingDispatcher's single LLM call already emits
    ``execution_plan.steps`` (graph nodes with capability/tool/label).
    When that plan is usable, the engine feeds it to the agent loop as
    ``orchestrator_context`` and skips the separate planning LLM call —
    the plan already exists, a second call would only re-derive it
    (Session 134: the 4-7 model calls per tool request include a plan
    call that duplicates what call #1 already produced).

    Returns "" when the graph is empty/degenerate (fallback plans build
    an empty ``ExecutionGraph()``), which leaves the existing planner in
    place — never skip planning with no plan at all (Session 113: raw NL
    reached the shell tool because planning was skipped with nothing to
    translate-before-dispatch).
    """
    if graph is None or not getattr(graph, "nodes", None):
        return ""
    lines = []
    for i, node in enumerate(graph.nodes, 1):
        label = (getattr(node, "label", "") or "").strip()
        tool = (getattr(node, "tool_name", "") or "").strip()
        # Only nodes with a human-readable label count as plan steps — a
        # bare tool name ("1. shell") is not a plan. This keeps degenerate
        # graphs (fallback plans, LLM output with steps but no labels) on
        # the existing planner instead of silently skipping it.
        if not label:
            continue
        lines.append(f"{i}. {label}" + (f" (via {tool})" if tool else ""))
    return "\n".join(lines)


def _dispatcher_plan_steps(graph) -> list[str]:
    """Human-readable step labels from the dispatcher's ExecutionGraph.

    Used to seed the Todos panel when the dispatcher's plan is reused in
    place of the separate planning call, so the UI still shows a real
    plan (the loop's own plan parsing is bypassed in that path).
    """
    if graph is None or not getattr(graph, "nodes", None):
        return []
    steps = []
    for i, node in enumerate(graph.nodes, 1):
        label = (getattr(node, "label", "") or "").strip()
        # Mirrors _dispatcher_plan_context: only labeled nodes are plan
        # steps, so the Todos panel shows exactly what the injected
        # orchestrator plan says.
        if label:
            steps.append(label)
    return steps


def get_adapter(*args, **kwargs):
    """Deferred-lookup wrapper for adapters.get_adapter.

    Looks up get_adapter from the core.engine package at call time so that
    test patches (patch("core.engine.get_adapter", ...)) take effect on
    code in this submodule. Without this, a module-level
    `from adapters import get_adapter` would create a separate binding
    that the patch cannot reach.
    """
    from core.engine import get_adapter as _real

    return _real(*args, **kwargs)


def _fallback_todo_plan(intent: Intent, message: str) -> list[str]:
    """Fallback todo plan for multi-step intents (Understand → Run → Verify).

    Kept as a module-level factory (not inline in Engine._emit_todo_plan) so
    tests/e2e/test_todo_system.py derives its expectations from the SAME
    source — pinning the strings in the test caused a long-lived baseline
    failure whenever the template changed (fixed Session 90).
    """
    intent_label = intent.value.replace('_', ' ')
    return [
        f"Understand: {message.strip()[:72]}",
        f"Run the {intent_label} action",
        "Verify the result and explain what changed",
    ]


# Intents whose requests are usually compound tasks and therefore keep the
# agent planning phase even when the dispatcher is highly confident. The
# v0.11 latency fix skipped planning for ALL intents at confidence >= 0.7,
# which left tool-heavy intents without any translate-before-dispatch step
# — Session 113's failure: the model passed the raw user sentence as a shell
# command. Planning is kept for these so requests like "check git status,
# and if there are changes show the diff" get decomposed up front (the
# plan phase also eliminates the documented file_write missing-args
# fumbling). Single-shot/simple intents keep the v0.11 fast path.
_PLAN_REQUIRED_INTENTS: frozenset[Intent] = frozenset(
    {
        Intent.SHELL,
        Intent.CODE_EXEC,
        Intent.FILE_WRITE,
        Intent.FILE_EDIT,
        # Session 122: git requests chain tools (locate → status → maybe
        # diff → report); at dispatcher confidence >= 0.7 the planner used to
        # be skipped, so the Todos panel showed no real plan for them.
        Intent.GIT,
    }
)


# Session 114: the planning-skip decision is a pure function so the routing
# contract is unit-testable without running the engine.
#
# === ADR-22 (Session 184) — Agent-First Routing ===
# Previously: planning was skipped when dispatcher confidence ≥0.7 AND the
# intent was not in _PLAN_REQUIRED_INTENTS. The agent's first LLM call was a
# tool-execution call, not a reasoning call — the dispatcher pre-decided.
#
# Now: ALWAYS return False — the agent ALWAYS plans for AGENT_INTENTS,
# regardless of dispatcher confidence. The dispatcher's output becomes a
# routing hint the agent evaluates during its own planning call, not a
# directive that bypasses planning. See ADR-22 for the full rationale + the
# user's "Show me projects in dev folder" example.
def _should_skip_planning(intent: Intent, dispatcher_confidence: float) -> bool:
    """Whether the agent planning phase should be skipped for this turn.

    ADR-22 (Session 184): ALWAYS False — the agent always plans. The
    `intent` and `dispatcher_confidence` parameters are kept for backward
    compatibility with existing callers + tests; they no longer affect
    the decision.
    """
    return False
