"""
Tests for the GoalInterpreter deterministic success-criteria fallback
(Session 177 — ADR-18 P0+).

These tests pin the two-tier behavior:
1. LLM-emitted criteria always win (no-op fallback).
2. When the LLM omits criteria, the interpreter derives 1-3
   deterministic checkable criteria per intent from
   `intent + first tool args`.

The derived criteria MUST be checkable by `core.agent.verify.criteria_gate`
— these tests assert that contract by cross-checking the criteria against
the gate's evidence matchers where relevant.
"""

from __future__ import annotations

import os
from unittest import mock

from core.agent.constants import Intent
from core.agent.goal_interpreter import (
    GoalInterpreter,
    Interpretation,
    interpret_goal,
)

# ── LLM-provided criteria win ────────────────────────────────────────────────


def test_llm_criteria_pass_through_unchanged():
    """When the dispatcher LLM emitted criteria, they win verbatim."""
    interp = GoalInterpreter()
    result = interp.interpret(
        message="run pytest on the auth module",
        intent=Intent.CODE_EXEC,
        llm_criteria=["pytest exits 0", "no failed tests in output"],
    )
    assert result.source == "llm"
    assert result.criteria == ["pytest exits 0", "no failed tests in output"]


def test_llm_criteria_empty_strings_are_filtered():
    """Empty/whitespace entries are dropped (defensive against malformed LLM JSON)."""
    interp = GoalInterpreter()
    result = interp.interpret(
        message="create hello.py",
        intent=Intent.FILE_WRITE,
        llm_criteria=["", "  ", "file exists at hello.py"],
    )
    assert result.source == "llm"
    assert result.criteria == ["file exists at hello.py"]


def test_llm_criteria_capped_at_four():
    """More than 4 criteria are truncated (token budget)."""
    interp = GoalInterpreter()
    result = interp.interpret(
        message="complex task",
        intent=Intent.CODE_EXEC,
        llm_criteria=["a", "b", "c", "d", "e", "f"],
    )
    assert len(result.criteria) == 4
    assert result.source == "llm"


# ── Deterministic fallback by intent ─────────────────────────────────────────


def test_file_write_derives_file_exists_criterion():
    """FILE_WRITE without LLM criteria derives a file-exists criterion."""
    interp = GoalInterpreter()
    result = interp.interpret(
        message="create hello.py with print('hi')",
        intent=Intent.FILE_WRITE,
        first_tool_args={"path": "/tmp/hello.py"},
    )
    assert result.source == "deterministic"
    assert len(result.criteria) == 1
    assert "/tmp/hello.py" in result.criteria[0]
    assert "exists" in result.criteria[0]


def test_file_write_uses_generic_fallback_when_no_path():
    """When the first tool args don't expose a path, a generic placeholder is used."""
    interp = GoalInterpreter()
    result = interp.interpret(
        message="create a file",
        intent=Intent.FILE_WRITE,
        first_tool_args={"content": "hello"},
    )
    assert result.source == "deterministic"
    # Must still mention "exists" so criteria_gate's file-exists matcher sees it
    assert "exists" in result.criteria[0]


def test_shell_derives_exit_code_criterion():
    """SHELL intent derives a no-error-markers criterion (Session 183
    refinement — the previous 'command exit code 0' template had no
    checkable tokens per the gate's _IGNORED_FALLBACK_TOKENS filter;
    'no error markers in shell output' is checkable via _check_no_errors)."""
    interp = GoalInterpreter()
    result = interp.interpret(
        message="ls -la",
        intent=Intent.SHELL,
        first_tool_args={"command": "ls -la"},
    )
    assert result.source == "deterministic"
    assert any("no error markers" in c for c in result.criteria)


def test_code_exec_derives_no_errors_criterion():
    """CODE_EXEC intent derives a no-Python-errors criterion."""
    interp = GoalInterpreter()
    result = interp.interpret(
        message="print(2+2)",
        intent=Intent.CODE_EXEC,
        first_tool_args={"code": "print(2+2)"},
    )
    assert result.source == "deterministic"
    assert any("no Python errors" in c for c in result.criteria)
    assert any("exit code 0" in c for c in result.criteria)


def test_chat_returns_no_criteria():
    """CHAT intent never gets derived criteria — no contract for pure conversation."""
    interp = GoalInterpreter()
    result = interp.interpret(
        message="hello",
        intent=Intent.CHAT,
    )
    assert result.source == "none"
    assert result.criteria == []


def test_unknown_intent_returns_no_criteria():
    """Intents not in the template map (DELEGATE, CREATE_PLAN, etc.) get no derived criteria."""
    interp = GoalInterpreter()
    result = interp.interpret(
        message="some internal op",
        intent=Intent.CREATE_PLAN,  # an internal orchestration primitive
    )
    assert result.source == "none"
    assert result.criteria == []


def test_none_intent_returns_no_criteria():
    """When the dispatcher returned None intent, no criteria can be derived."""
    interp = GoalInterpreter()
    result = interp.interpret(
        message="anything",
        intent=None,
    )
    assert result.source == "none"
    assert result.criteria == []


# ── Execution-graph extraction ──────────────────────────────────────────────


def test_extracts_first_step_args_from_execution_plan():
    """When execution_plan_steps is given, the first step's args are used."""
    interp = GoalInterpreter()
    result = interp.interpret(
        message="edit config.yaml",
        intent=Intent.FILE_EDIT,
        execution_plan_steps=[
            {"args": {"path": "/etc/config.yaml"}},
            {"args": {"path": "/other.yaml"}},  # should be ignored
        ],
    )
    assert result.source == "deterministic"
    assert "/etc/config.yaml" in result.criteria[0]


def test_skips_steps_with_missing_or_non_dict_args():
    """Steps with missing/non-dict args are skipped, the next valid one is used."""
    interp = GoalInterpreter()
    result = interp.interpret(
        message="edit config",
        intent=Intent.FILE_EDIT,
        execution_plan_steps=[
            {"args": "not a dict"},  # skip
            {},  # skip
            {"args": {"path": "/etc/config.yaml"}},  # use this
        ],
    )
    assert result.source == "deterministic"
    assert "/etc/config.yaml" in result.criteria[0]


def test_first_tool_args_override_execution_plan_steps():
    """Explicit first_tool_args wins over execution_plan_steps."""
    interp = GoalInterpreter()
    result = interp.interpret(
        message="write file",
        intent=Intent.FILE_WRITE,
        first_tool_args={"path": "/explicit/path.txt"},
        execution_plan_steps=[{"args": {"path": "/from-plan.txt"}}],
    )
    assert result.source == "deterministic"
    assert "/explicit/path.txt" in result.criteria[0]
    assert "/from-plan.txt" not in result.criteria[0]


# ── Env-var disable ──────────────────────────────────────────────────────────


def test_env_disable_falls_through_to_none():
    """When LOCALMIND_GOAL_INTERPRETER_DISABLE is set, the deterministic fallback is bypassed."""
    with mock.patch.dict(os.environ, {"LOCALMIND_GOAL_INTERPRETER_DISABLE": "1"}):
        interp = GoalInterpreter()
        result = interp.interpret(
            message="write file",
            intent=Intent.FILE_WRITE,
            first_tool_args={"path": "/tmp/x"},
        )
    # With the fallback disabled and no LLM criteria, result is none.
    assert result.source == "none"
    assert result.criteria == []


def test_env_disable_does_not_override_llm_criteria():
    """LLM criteria always pass through even when the interpreter is disabled."""
    with mock.patch.dict(os.environ, {"LOCALMIND_GOAL_INTERPRETER_DISABLE": "true"}):
        interp = GoalInterpreter()
        result = interp.interpret(
            message="write file",
            intent=Intent.FILE_WRITE,
            llm_criteria=["file exists at /tmp/x"],
        )
    assert result.source == "llm"
    assert result.criteria == ["file exists at /tmp/x"]


# ── Singleton wrapper ───────────────────────────────────────────────────────


def test_module_level_interpret_goal_returns_interpretation():
    """The convenience wrapper returns an Interpretation."""
    result = interpret_goal(
        message="create hello.py",
        intent=Intent.FILE_WRITE,
        first_tool_args={"path": "/tmp/hello.py"},
    )
    assert isinstance(result, Interpretation)
    assert result.source == "deterministic"


# ── Coverage: every agent intent has a template (or is deliberately excluded) ─


_EXCLUDED_INTENTS = {
    # Pure-conversation / orchestration primitives — no checkable contract.
    Intent.CHAT,
    Intent.DELEGATE,
    Intent.DELEGATE_PARALLEL,
    Intent.DELEGATE_INLINE,
    Intent.PROPOSE_EDIT,  # value is 'propose_str_replace'
    Intent.PROPOSE_WRITE,
    Intent.APPLY_PROPOSED,
    Intent.ADD_SUBGOAL,
    Intent.UPDATE_SUBGOAL,
    Intent.CREATE_PLAN,
    Intent.SKILL,
    Intent.BEST_OF_N_EDIT,
    Intent.DESCRIBE_TOOL,  # ADR-40 option C: meta-tool (loads a schema; no checkable contract)
    Intent.TODO_WRITE,  # ADR-43: UI-checklist tool (updates the panel; no checkable goal contract)
    # MEMORY_OP gets a generic "completed without error" — it's in the map.
}


def test_every_non_excluded_intent_has_a_template():
    """Pins the template coverage — if a new Intent is added, the dev must
    either add it to _TEMPLATES or to _EXCLUDED_INTENTS in this test."""
    from core.agent.goal_interpreter import _TEMPLATES
    from core.models import Intent as AllIntent

    for intent in AllIntent:
        if intent in _EXCLUDED_INTENTS:
            continue
        assert intent in _TEMPLATES, (
            f"Intent {intent} has no GoalInterpreter template — either add one"
            f" or add it to _EXCLUDED_INTENTS in this test."
        )


# ── Derived criteria are checkable by criteria_gate (contract test) ─────────


def test_derived_file_write_criterion_is_checkable_by_gate():
    """The criterion text MUST be a form criteria_gate recognizes. Cross-check
    that the gate's evidence matchers would accept the derived text."""
    from core.agent.models import AgentStep, AgentTrace
    from core.agent.verify import criteria_gate

    interp = GoalInterpreter()
    result = interp.interpret(
        message="create hello.py",
        intent=Intent.FILE_WRITE,
        first_tool_args={"path": "/tmp/lm_goal_interp_test_hello.py"},
    )
    assert result.source == "deterministic"
    assert result.criteria

    # Create the file so the gate's file-exists check passes.
    with open("/tmp/lm_goal_interp_test_hello.py", "w") as f:
        f.write("print('hi')\n")

    trace = AgentTrace(
        success_criteria=result.criteria,
        steps=[
            AgentStep(
                iteration=0,
                thought="writing hello.py",
                tool_name="file_write",
                tool_input='{"path": "/tmp/lm_goal_interp_test_hello.py"}',
                observation="wrote 14 bytes",
            ),
        ],
    )
    done, _unmet = criteria_gate(trace, unmet_label="test")
    assert done is True

    # Cleanup
    os.remove("/tmp/lm_goal_interp_test_hello.py")
