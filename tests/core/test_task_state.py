"""Tests for TaskState — the first-class task-state object (ADR-18 P0)."""

from __future__ import annotations

from core.agent.task_state import PHASE_EXECUTE, PHASE_VERIFY, TaskState


def test_record_tool_appends_evidence():
    state = TaskState(objective="fix the bug")
    state.record_tool("shell", "pytest tests -q", "3 passed in 0.5s", succeeded=True)
    state.record_tool("shell", "git status", "error: failed", succeeded=False, iteration=2)
    assert len(state.evidence) == 2
    assert state.evidence[0]["tool"] == "shell"
    assert state.evidence[0]["input"] == "pytest tests -q"
    assert state.evidence[0]["succeeded"] is True
    assert state.evidence[1]["iteration"] == 2


def test_record_step_moves_pending_to_completed():
    state = TaskState(pending=["create dir", "write hello.py"])
    state.record_step("write hello.py", succeeded=True)
    assert "write hello.py" in state.completed
    assert "write hello.py" not in state.pending
    assert "create dir" in state.pending


def test_record_step_failed_records_error():
    state = TaskState(pending=["run tests"])
    state.record_step("run tests", succeeded=False, error="AssertionError")
    assert state.failed == [("run tests", "AssertionError")]
    assert state.pending == []


def test_to_prompt_includes_criteria_and_phase():
    state = TaskState(
        objective="create hello.py",
        constraints=["low risk"],
        success_criteria=["pytest passes", "hello.py exists with content"],
        phase=PHASE_VERIFY,
    )
    state.set_budget(iter_used=3, iter_max=8, wall_used=12.5, wall_max=180)
    prompt = state.to_prompt()
    assert "# Task State" in prompt
    assert "Objective: create hello.py" in prompt
    assert "Constraints: low risk" in prompt
    assert "do NOT report done until ALL are met" in prompt
    assert "- [ ] pytest passes" in prompt
    assert "- [ ] hello.py exists with content" in prompt
    assert "Phase: verify" in prompt
    assert "Iteration 3/8" in prompt


def test_to_prompt_progress_section():
    state = TaskState(
        pending=["create dir"],
        completed=["read README"],
        failed=[("run tests", "TimeoutError")],
    )
    prompt = state.to_prompt()
    assert "- [x] read README" in prompt
    assert "- [ ] create dir" in prompt
    assert "- [!] run tests — failed: TimeoutError" in prompt


def test_to_prompt_empty_when_no_contract():
    assert TaskState().to_prompt() == ""


def test_to_prompt_objective_only():
    assert TaskState(objective="hi").to_prompt() != ""


def test_to_dict_roundtrip():
    state = TaskState(
        objective="write code",
        success_criteria=["pytest passes"],
        pending=["step-a"],
    )
    state.record_step("step-a", succeeded=False, error="boom")
    state.record_tool("shell", "pytest", "2 passed", succeeded=True)
    data = state.to_dict()
    assert data["objective"] == "write code"
    assert data["failed"] == [{"step": "step-a", "error": "boom"}]
    assert data["evidence"][0]["tool"] == "shell"
    assert data["phase"] == PHASE_EXECUTE
    # Mutating the serialized copy must not affect the original.
    data["completed"].append("nope")
    assert state.completed == []


def test_advance_phase():
    state = TaskState()
    state.advance_phase(PHASE_VERIFY)
    assert state.phase == PHASE_VERIFY


def test_set_budget_shape():
    state = TaskState()
    state.set_budget(iter_used=1, iter_max=8, wall_used=9.99, wall_max=180)
    assert state.budget["iter_used"] == 1
    assert state.budget["iter_max"] == 8
    assert state.budget["wall_used"] == 10.0  # rounded
    assert state.budget["wall_max"] == 180


def test_evidence_truncation():
    state = TaskState()
    state.record_tool("shell", "x" * 900, "y" * 900)
    assert len(state.evidence[0]["input"]) == 500
    assert len(state.evidence[0]["observation"]) == 500
