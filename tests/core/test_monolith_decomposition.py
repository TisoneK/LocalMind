"""
Session 129 — monolith decomposition re-export contract.

The pure text helpers moved from ``core.agent.loop`` to
``core.agent.text_tools``; the routing/planning/clock helpers moved from
``core.engine._pipeline`` to ``core.engine.routing_helpers`` +
``core.engine.stage_clock``. Tests and the engine import these helpers from
the ORIGINAL modules (e.g. ``from core.agent.loop import
_parse_minimax_tool_call``), so the monoliths must keep re-exporting every
moved symbol. This test pins that contract so a future refactor cannot
silently break imports.
"""

from __future__ import annotations


def test_loop_reexports_text_tools_helpers():
    from core.agent import loop, text_tools

    moved = [
        "_parse_plan_steps",
        "_is_filler_step",
        "_normalize_dsml",
        "_parse_minimax_tool_call",
        "_strip_minimax_tool_calls",
        "_has_minimax_tool_call",
        "_truncate_observation",
        "_is_tool_talk",
        "_extract_tool_input",
        "_MINIMAX_PARTIAL_RE",
        "_STANDALONE_PARTIAL_RE",
        "_MAX_TOOL_TALK_RECOVERIES",
    ]
    for name in moved:
        # Same object, not a stale copy — the re-export must point at the
        # single source of truth in text_tools.
        assert getattr(loop, name) is getattr(text_tools, name), name


def test_pipeline_reexports_routing_and_clock_helpers():
    import core.engine._pipeline as pipeline
    import core.engine.routing_helpers as routing
    import core.engine.stage_clock as clock

    for name in ["_fallback_todo_plan", "_should_skip_planning", "_PLAN_REQUIRED_INTENTS", "get_adapter"]:
        assert getattr(pipeline, name) is getattr(routing, name), name

    assert pipeline._StageClock is clock._StageClock


def test_helpers_still_importable_from_monolith_paths():
    """The exact import paths tests and _pipeline.py use must keep working."""
    from core.agent.loop import (  # noqa: F401
        _extract_tool_input,
        _has_minimax_tool_call,
        _parse_minimax_tool_call,
        _truncate_observation,
    )
    from core.engine._pipeline import (  # noqa: F401
        _should_skip_planning,
        _StageClock,
    )
    from core.engine.routing_helpers import _fallback_todo_plan  # noqa: F401

    assert True
