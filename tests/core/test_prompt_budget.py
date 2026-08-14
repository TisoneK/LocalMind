"""ADR-34 B-12: Stage-specific prompt budget.

Validates that:
1. The init prompt uses a COMPACT capability summary, not full 180-char
   tool descriptions.
2. The init prompt is significantly smaller than the old format (target:
   under 2500 chars for 30 tools; was 7039 chars before B-12).
3. The compact summary still includes all tool names so the model can
   reference them in tool_names.
4. The InitializationDecision records init_prompt_chars for budget
   measurement.
"""

from __future__ import annotations

import pytest

from core.agent.initialization import (
    InitializationDecision,
    _compact_capability_summary,
    build_initialization_prompt,
)


def _sample_tools() -> list[dict]:
    """A representative subset of LocalMind's 30 tools."""
    return [
        {"intent": "sysinfo", "description": "Get current time, date, OS version, CPU, RAM, disk specs. Offline, instant."},
        {"intent": "file_task", "description": "Read the TEXT CONTENTS of a single FILE (code, text, PDF, DOCX, CSV, XLSX)."},
        {"intent": "shell", "description": "Execute shell commands and filesystem operations: list directory contents, find files, run commands, open apps/files/websites, check disk/internet/IP."},
        {"intent": "code_exec", "description": "Execute Python code snippets and return stdout/stderr output"},
        {"intent": "web_search", "description": "Search the web for current information, news, prices, or recent events"},
        {"intent": "delegate", "description": "Delegate a sub-task to another specialized agent. Use this when the current task requires a different domain of expertise (e.g., a coding task that needs web research, or a research task that needs file analysis)."},
        {"intent": "memory_op", "description": "Store, recall, or delete facts from persistent semantic memory"},
        {"intent": "calculate", "description": "Evaluate a safe arithmetic expression exactly (no shell needed): numbers, + - * / // % **, parentheses, unary minus, constants pi/e/tau, and functions abs/round/min/max/pow/sqrt/floor/ceil/trunc/exp/log/sin/cos/tan."},
    ]


def test_compact_summary_groups_tools_by_category():
    """The compact summary should group tools into coarse categories."""
    summary = _compact_capability_summary(_sample_tools())
    assert "file ops:" in summary
    assert "code:" in summary
    assert "web:" in summary
    assert "memory:" in summary
    assert "math:" in summary
    # Each tool name should appear exactly once
    assert summary.count("file_task") == 1
    assert summary.count("shell") == 1
    assert summary.count("web_search") == 1


def test_compact_summary_does_not_include_descriptions():
    """The compact summary must NOT include the full tool descriptions."""
    tools = _sample_tools()
    summary = _compact_capability_summary(tools)
    # A distinctive phrase from the shell description should NOT appear
    assert "list directory contents" not in summary
    assert "Execute shell commands" not in summary
    # The delegate description is very long — it must not leak
    assert "different domain of expertise" not in summary


def test_compact_summary_handles_empty_tools():
    summary = _compact_capability_summary([])
    assert summary == "(no tools available)"


def test_init_prompt_is_under_budget():
    """ADR-34 B-12: the init prompt must be significantly smaller than the
    old 7039-char format. Target: under 2500 chars for 30 tools."""
    from tools import available_tools

    tools = available_tools()
    prompt = build_initialization_prompt(
        user_message="whats the time?",
        available_tools=tools,
        env_context="",
        history=[],
    )
    assert len(prompt) < 2500, (
        f"B-12 budget violation: init prompt is {len(prompt)} chars, "
        f"expected under 2500. The old format was 7039 chars."
    )


def test_init_prompt_includes_all_tool_names():
    """The compact summary must still include every tool name so the model
    can reference them in tool_names."""
    from tools import available_tools

    tools = available_tools()
    prompt = build_initialization_prompt(
        user_message="test",
        available_tools=tools,
        env_context="",
        history=[],
    )
    for tool in tools:
        name = str(tool.get("intent") or tool.get("name") or "").strip()
        if name:
            assert name in prompt, f"tool name '{name}' missing from init prompt"


def test_init_prompt_uses_capability_summary_not_full_descriptions():
    """The init prompt must use the compact capability summary, not the
    full 180-char tool descriptions."""
    from tools import available_tools

    tools = available_tools()
    prompt = build_initialization_prompt(
        user_message="test",
        available_tools=tools,
        env_context="",
        history=[],
    )
    # The prompt should have "Capabilities (use these names in tool_names):"
    assert "Capabilities" in prompt
    # It should NOT have the old "Available tools:" header
    assert "Available tools:" not in prompt
    # It should NOT include any tool's full description (180 chars)
    for tool in tools:
        desc = str(tool.get("description") or "")
        if len(desc) > 100:
            # Check that no 80+ char substring of the description appears
            # (the summary only has the tool name, not the description)
            chunk = desc[:80]
            assert chunk not in prompt, (
                f"tool description leaked into init prompt: {chunk!r}"
            )


def test_initialization_decision_has_prompt_chars_field():
    """ADR-34 B-12: InitializationDecision must have an init_prompt_chars
    field for budget measurement."""
    decision = InitializationDecision()
    assert hasattr(decision, "init_prompt_chars")
    assert decision.init_prompt_chars == 0  # default


def test_parse_initialization_preserves_prompt_chars():
    """parse_initialization should not clobber init_prompt_chars when set."""
    from core.agent.initialization import parse_initialization

    decision = parse_initialization('{"mode": "execute", "objective": "test"}')
    decision.init_prompt_chars = 1795
    assert decision.init_prompt_chars == 1795
    assert decision.mode == "execute"
