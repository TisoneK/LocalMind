"""
Tests for the post-execution verifier (Session 179 — F4).

Closes the gap that the model can claim "done" after a tool failure
(e.g. file_write returned an error string, code_exec raised an
exception) and the existing `criteria_gate` doesn't catch it because
the GoalInterpreter's derived criteria check the FIRST tool's outcome.

The post-execution verifier runs AFTER criteria pass, for high-stakes
intents, and checks the LAST tool's observation for error markers.
"""

from __future__ import annotations

import pytest

from core.agent.constants import Intent
from core.agent.models import AgentStep, AgentTrace
from core.agent.post_execution_verifier import (
    is_high_stakes_intent,
    post_execution_verify,
    verify_last_tool_succeeded,
)

# ── verify_last_tool_succeeded ───────────────────────────────────────────────


def test_no_steps_passes():
    """No tool steps in the trace → pass (no work to verify)."""
    trace = AgentTrace(success_criteria=[], steps=[])
    passed, note = verify_last_tool_succeeded(trace)
    assert passed is True
    assert "no tool steps" in note


def test_empty_observation_passes():
    """Last step with no observation → pass (no error markers to check)."""
    trace = AgentTrace(
        success_criteria=[],
        steps=[
            AgentStep(
                iteration=0,
                thought="writing file",
                tool_name="file_write",
                tool_input='{"path": "/tmp/foo"}',
                observation="",
            ),
        ],
    )
    passed, _ = verify_last_tool_succeeded(trace)
    assert passed is True


def test_clean_observation_passes():
    """Last tool output with no error markers → pass."""
    trace = AgentTrace(
        success_criteria=[],
        steps=[
            AgentStep(
                iteration=0,
                thought="writing file",
                tool_name="file_write",
                tool_input='{"path": "/tmp/foo"}',
                observation="wrote 14 bytes to /tmp/foo",
            ),
        ],
    )
    passed, _ = verify_last_tool_succeeded(trace)
    assert passed is True


def test_traceback_in_observation_fails():
    """Last tool output containing 'traceback' → fail."""
    trace = AgentTrace(
        success_criteria=[],
        steps=[
            AgentStep(
                iteration=0,
                thought="running code",
                tool_name="code_exec",
                tool_input='{"code": "1/0"}',
                observation="Traceback (most recent call last):\n  File ...\nZeroDivisionError: division by zero",
            ),
        ],
    )
    passed, note = verify_last_tool_succeeded(trace)
    assert passed is False
    assert "traceback" in note.lower()


def test_exception_in_observation_fails():
    """Last tool output containing 'exception' → fail."""
    trace = AgentTrace(
        success_criteria=[],
        steps=[
            AgentStep(
                iteration=0,
                thought="running command",
                tool_name="shell",
                tool_input='{"command": "python -c badsyntax"}',
                observation="Exception raised: SyntaxError",
            ),
        ],
    )
    passed, _ = verify_last_tool_succeeded(trace)
    assert passed is False


def test_failed_marker_in_observation_fails():
    """Last tool output containing 'failed' → fail."""
    trace = AgentTrace(
        success_criteria=[],
        steps=[
            AgentStep(
                iteration=0,
                thought="writing file",
                tool_name="file_write",
                tool_input='{"path": "/etc/passwd"}',
                observation="Error: permission denied — write failed",
            ),
        ],
    )
    passed, _ = verify_last_tool_succeeded(trace)
    assert passed is False


def test_error_colon_in_observation_fails():
    """Last tool output containing 'Error:' (but not 'errors' plural) → fail."""
    trace = AgentTrace(
        success_criteria=[],
        steps=[
            AgentStep(
                iteration=0,
                thought="writing file",
                tool_name="file_write",
                tool_input='{"path": "/nonexistent/foo.txt"}',
                observation="error: no such file or directory",
            ),
        ],
    )
    passed, _ = verify_last_tool_succeeded(trace)
    assert passed is False


def test_nonzero_exit_code_fails():
    """Last tool output containing 'exit code 1' (or any non-zero) → fail."""
    trace = AgentTrace(
        success_criteria=[],
        steps=[
            AgentStep(
                iteration=0,
                thought="running command",
                tool_name="shell",
                tool_input='{"command": "false"}',
                observation="exit code 1",
            ),
        ],
    )
    passed, _ = verify_last_tool_succeeded(trace)
    assert passed is False


def test_zero_exit_code_passes():
    """Last tool output 'exit code 0' → pass (success marker overrides)."""
    trace = AgentTrace(
        success_criteria=[],
        steps=[
            AgentStep(
                iteration=0,
                thought="running command",
                tool_name="shell",
                tool_input='{"command": "true"}',
                observation="exit code 0",
            ),
        ],
    )
    passed, _ = verify_last_tool_succeeded(trace)
    assert passed is True


def test_no_errors_passes_via_success_marker():
    """Output containing 'no errors' → pass (success marker)."""
    trace = AgentTrace(
        success_criteria=[],
        steps=[
            AgentStep(
                iteration=0,
                thought="running tests",
                tool_name="shell",
                tool_input='{"command": "pytest"}',
                observation="==== no errors, all tests passed ====",
            ),
        ],
    )
    passed, _ = verify_last_tool_succeeded(trace)
    assert passed is True


def test_zero_errors_passes_via_success_marker():
    """Output containing '0 errors' → pass (success marker overrides 'errors' word)."""
    trace = AgentTrace(
        success_criteria=[],
        steps=[
            AgentStep(
                iteration=0,
                thought="running linter",
                tool_name="shell",
                tool_input='{"command": "ruff check ."}',
                observation="Found 0 errors in 12 files.",
            ),
        ],
    )
    passed, _ = verify_last_tool_succeeded(trace)
    assert passed is True


# ── is_high_stakes_intent ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "intent, expected",
    [
        (Intent.FILE_WRITE, True),
        (Intent.FILE_EDIT, True),
        (Intent.CODE_EXEC, True),
        (Intent.SHELL, True),
        (Intent.CHAT, False),
        (Intent.WEB_SEARCH, False),
        (Intent.FILE_TASK, False),  # read-only
        (Intent.SYSINFO, False),
        (Intent.MEMORY_OP, False),
    ],
)
def test_high_stakes_intent_classification(intent, expected):
    assert is_high_stakes_intent(intent) is expected


def test_high_stakes_accepts_string_value():
    """Pass the intent value as a string instead of the enum."""
    assert is_high_stakes_intent("file_write") is True
    assert is_high_stakes_intent("chat") is False


def test_high_stakes_none_returns_false():
    assert is_high_stakes_intent(None) is False


# ── post_execution_verify (combined) ────────────────────────────────────────


def test_post_execution_skips_non_high_stakes():
    """Non-high-stakes intents (CHAT, FILE_TASK, etc.) skip the verifier."""
    trace = AgentTrace(
        success_criteria=[],
        steps=[
            AgentStep(
                iteration=0,
                thought="reading file",
                tool_name="file_task",
                tool_input='{"path": "/etc/passwd"}',
                observation="error: file not found",  # would fail the verifier
            ),
        ],
    )
    passed, note = post_execution_verify(trace, Intent.FILE_TASK)
    assert passed is True
    assert "skipped" in note.lower()


def test_post_execution_runs_for_file_write():
    """FILE_WRITE with a clean observation → pass."""
    trace = AgentTrace(
        success_criteria=[],
        steps=[
            AgentStep(
                iteration=0,
                thought="writing file",
                tool_name="file_write",
                tool_input='{"path": "/tmp/foo"}',
                observation="wrote 14 bytes",
            ),
        ],
    )
    passed, _ = post_execution_verify(trace, Intent.FILE_WRITE)
    assert passed is True


def test_post_execution_catches_failure_for_file_write():
    """FILE_WRITE with a 'failed' observation → FAIL the gate."""
    trace = AgentTrace(
        success_criteria=[],
        steps=[
            AgentStep(
                iteration=0,
                thought="writing file",
                tool_name="file_write",
                tool_input='{"path": "/nonexistent/foo"}',
                observation="error: permission denied — write failed",
            ),
        ],
    )
    passed, note = post_execution_verify(trace, Intent.FILE_WRITE)
    assert passed is False
    assert "error marker" in note.lower() or "permission" in note.lower()


def test_post_execution_catches_python_traceback():
    """CODE_EXEC that raised a Python traceback → FAIL."""
    trace = AgentTrace(
        success_criteria=[],
        steps=[
            AgentStep(
                iteration=0,
                thought="running code",
                tool_name="code_exec",
                tool_input='{"code": "1/0"}',
                observation="Traceback (most recent call last):\n  File ...\nZeroDivisionError: division by zero",
            ),
        ],
    )
    passed, _ = post_execution_verify(trace, Intent.CODE_EXEC)
    assert passed is False


# ── Integration: criteria pass but post-exec fails ──────────────────────────


def test_scenario_criteria_pass_post_exec_fails():
    """Realistic scenario:
    - GoalInterpreter derived criteria: "file exists at /tmp/foo with content"
    - The criteria_gate uses evidence fallback: file path appears in
      file_write tool input → criterion passes.
    - BUT the file_write output actually contains an error string
      (e.g. "permission denied").
    - The post-execution verifier catches the error marker that the
      criteria gate missed.

    This is the F4 use case in one test.
    """
    from core.agent.goal_interpreter import interpret_goal
    from core.agent.verify import evaluate_criteria, gate_passed

    # 1. GoalInterpreter derives criteria from FILE_WRITE intent + tool args
    interp = interpret_goal(
        message="write file /tmp/foo",
        intent=Intent.FILE_WRITE,
        first_tool_args={"path": "/tmp/foo"},
    )
    assert interp.source == "deterministic"
    assert interp.criteria

    # 2. criteria_gate accepts (path appears in tool input → evidence fallback)
    trace = AgentTrace(
        success_criteria=interp.criteria,
        steps=[
            AgentStep(
                iteration=0,
                thought="writing file",
                tool_name="file_write",
                tool_input='{"path": "/tmp/foo", "content": "hi"}',
                observation="error: permission denied — write failed",  # ⚠️
            ),
        ],
    )
    results = evaluate_criteria(trace.success_criteria, trace)
    assert gate_passed(results), "criteria gate passes (path in tool input)"

    # 3. Post-execution verifier catches what criteria_gate missed
    pe_passed, pe_note = post_execution_verify(trace, Intent.FILE_WRITE)
    assert pe_passed is False, (
        f"post-exec verifier should fail when last tool output has error "
        f"markers — got: passed={pe_passed}, note={pe_note}"
    )
