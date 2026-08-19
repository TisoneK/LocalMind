"""
Tests for the parent's completion-verification FLOOR (B-2026-08-18-2, review-66).

The missing VERIFY→DONE segment of the spec's wheel: on the user-facing parent
path there is no explicit success-criteria contract, so the acceptance gate used
to accept the model's "done" even when the parent's last real action FAILED
(spec §29/§30). `parent_completion_floor_note` plugs the hole, scoped to
high-stakes tools, judging failure by EITHER the dispatcher's `tool_failed`
verdict (tool-level failure) OR error markers in the observation (command-level
failure — e.g. a nonzero-exit shell command that `shell.py` returns with
success=True).
"""

from __future__ import annotations

from core.agent.loop import parent_completion_floor_note
from core.agent.models import AgentStep, AgentTrace


def _step(tool_name, *, failed=False, observation=""):
    return AgentStep(
        iteration=0,
        thought="",
        tool_name=tool_name,
        tool_input="",
        observation=observation,
        tool_failed=failed,
    )


def test_no_steps_returns_none():
    """No tools ran → nothing to verify → None (legacy model-assertion path)."""
    assert parent_completion_floor_note(AgentTrace(steps=[])) is None


def test_tool_level_failure_returns_note():
    """Dispatcher set tool_failed (permission/internal) → reject 'done'."""
    note = parent_completion_floor_note(AgentTrace(steps=[_step("shell", failed=True)]))
    assert note is not None and "shell" in note


def test_command_level_failure_in_observation_returns_note():
    """The live gap: a nonzero-exit shell command returns success=True but its
    output carries the error — the floor must still catch it."""
    # shell.py wraps a nonzero exit as "Command failed:\n<output>" (success=True),
    # which is exactly what the observation check keys on.
    trace = AgentTrace(
        steps=[_step("shell", observation="Command failed:\ncat: /nope.txt: No such file or directory")]
    )
    note = parent_completion_floor_note(trace)
    assert note is not None and "shell" in note


def test_code_exec_exception_returns_note():
    trace = AgentTrace(
        steps=[_step("code_exec", observation="Traceback (most recent call last): ValueError: boom")]
    )
    assert parent_completion_floor_note(trace) is not None


def test_clean_success_returns_none():
    """A successful high-stakes action is not rejected."""
    trace = AgentTrace(steps=[_step("shell", observation="floor-smoke-ok")])
    assert parent_completion_floor_note(trace) is None


def test_success_markers_override_error_word():
    """`0 errors` is a passing result, not a failure (success-marker override)."""
    trace = AgentTrace(steps=[_step("code_exec", observation="pytest: 0 errors, all passed")])
    assert parent_completion_floor_note(trace) is None


def test_low_stakes_last_tool_returns_none():
    """Read/analysis/search turns get no floor even with an error observation."""
    trace = AgentTrace(
        steps=[_step("file_task", observation="error: file not found")]
    )
    assert parent_completion_floor_note(trace) is None


def test_only_the_last_tool_is_judged():
    """An earlier failure the model already recovered from doesn't block a later
    successful 'done'."""
    trace = AgentTrace(
        steps=[
            _step("shell", observation="No such file or directory"),
            _step("file_write", observation="Wrote 12 bytes to /tmp/ok.txt."),
        ]
    )
    assert parent_completion_floor_note(trace) is None


def test_trailing_failed_high_stakes_rejects_after_earlier_success():
    trace = AgentTrace(
        steps=[
            _step("file_write", observation="Wrote 5 bytes to /tmp/ok.txt."),
            _step("code_exec", failed=True),
        ]
    )
    note = parent_completion_floor_note(trace)
    assert note is not None and "code_exec" in note


def test_all_high_stakes_tools_covered_via_tool_failed():
    for tool in ("file_write", "file_edit", "shell", "code_exec"):
        trace = AgentTrace(steps=[_step(tool, failed=True)])
        assert parent_completion_floor_note(trace) is not None, tool
