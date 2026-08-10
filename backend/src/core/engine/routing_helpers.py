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
def _should_skip_planning(intent: Intent, dispatcher_confidence: float) -> bool:
    """Whether the agent planning phase should be skipped for this turn.

    The v0.11 fast path skips planning when the dispatcher was highly
    confident (>= 0.7) AND the intent is not compound-capable. Below the
    threshold planning is never skipped (the slow path runs the planner).
    """
    if dispatcher_confidence < 0.7:
        return False
    return intent not in _PLAN_REQUIRED_INTENTS
