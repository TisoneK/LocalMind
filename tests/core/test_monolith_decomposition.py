"""Structural contracts after removing the legacy engine pipeline."""

from __future__ import annotations

from pathlib import Path


def test_legacy_pipeline_module_is_removed():
    root = Path(__file__).resolve().parents[2]
    assert not (root / "backend" / "src" / "core" / "engine" / "_pipeline.py").exists()


def test_parent_runtime_is_the_public_engine_implementation():
    from core.engine import AgentRuntime, Engine

    assert Engine is AgentRuntime


def test_loop_still_reexports_text_tools_helpers():
    from core.agent import loop, text_tools

    for name in [
        "_parse_plan_steps",
        "_is_filler_step",
        "_normalize_dsml",
        "_parse_minimax_tool_call",
        "_strip_minimax_tool_calls",
        "_has_minimax_tool_call",
        "_truncate_observation",
        "_is_tool_talk",
        "_extract_tool_input",
    ]:
        assert getattr(loop, name) is getattr(text_tools, name), name
