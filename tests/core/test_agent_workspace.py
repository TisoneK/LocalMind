"""Tests for the server-side Agent Workspace reconstruction (Session 267).

The Agents tab (run tree) and phase strip are frontend-only live state, so the
runtime rebuilds them from the request's obs events at persist time. These
tests pin the reconstruction: parent root + tool attachment, delegation
children, evidence entries, delegation completion, and the phase strip.
"""

import pytest

from core.agent_workspace import (
    PHASE_EVENT_TYPES,
    build_agent_phases,
    build_run_tree,
    build_workspace_artifacts,
)
from core.obs import ObsCollector


def _collector(*events):
    c = ObsCollector()
    for event_type, data in events:
        c.emit(event_type, **data)
    return c


def test_run_tree_parent_root_with_tools():
    c = _collector(
        ("tool_call", {"tool": "shell", "label": "Running: ls", "status": "started", "tool_args": "ls -la", "iteration": 1, "reasoning": "check dir"}),
        ("tool_call", {"tool": "shell", "label": "Running: ls", "status": "done", "tool_args": "ls -la", "iteration": 1, "latency_ms": 12}),
    )
    runs = build_run_tree(c, task="list files")
    assert len(runs) == 1
    parent = runs[0]
    assert parent["role"] == "parent"
    assert parent["status"] == "completed"
    assert parent["task"] == "list files"
    assert parent["depth"] == 0
    # started + done collapse into one row (same stable id), done status wins
    assert len(parent["tools"]) == 1
    tool = parent["tools"][0]
    assert tool["name"] == "shell"
    assert tool["status"] == "done"
    assert tool["input"] == "ls -la"
    assert tool["reasoning"] == "check dir"
    assert tool["duration"] == 12


def test_run_tree_failed_root_carries_error():
    c = _collector(("tool_call", {"tool": "git", "status": "failed", "tool_args": "", "iteration": 1}))
    runs = build_run_tree(c, task="commit", root_error="zen returned 429")
    assert runs[0]["status"] == "failed"
    assert runs[0]["error"] == "zen returned 429"


def test_run_tree_delegation_child_with_own_tools():
    c = _collector(
        ("delegation_started", {"target_agent": "research", "task": "find weather", "run_id": "run-123", "depth": 1}),
        # child tool_call events carry `agent` (forwarded by ChildObsProxy)
        ("tool_call", {"tool": "web_search", "label": "Searching", "status": "started", "tool_args": "weather nairobi", "iteration": 1, "agent": "research"}),
        ("tool_call", {"tool": "web_search", "label": "Searching", "status": "done", "tool_args": "weather nairobi", "iteration": 1, "latency_ms": 400, "agent": "research"}),
        ("delegation_completed", {"target_agent": "research", "run_id": "run-123", "status": "completed"}),
    )
    runs = build_run_tree(c, task="weather report")
    assert len(runs) == 2
    parent, child = runs
    assert child["id"] == "run-123"
    assert child["name"] == "research"
    assert child["role"] == "child"
    assert child["parentId"] == "parent"
    assert child["task"] == "find weather"
    assert child["depth"] == 1
    assert child["status"] == "completed"
    assert child["completedAt"] is not None
    # the child's tool landed on the child run, not the parent
    assert len(parent["tools"]) == 0
    assert len(child["tools"]) == 1
    assert child["tools"][0]["name"] == "web_search"
    assert child["tools"][0]["status"] == "done"
    # child output must not surface (intermediate model context)
    assert child["tools"][0]["output"] == ""


def test_run_tree_parallel_delegation_single_child():
    c = _collector(
        ("delegation_started", {"target_agent": "2 parallel agents", "task": "a, b", "run_id": "parallel", "depth": 1}),
        ("delegation_completed", {"target_agent": "2 parallel agents", "run_id": "parallel", "status": "completed"}),
    )
    runs = build_run_tree(c, task="parallel task")
    assert len(runs) == 2
    assert runs[1]["id"] == "parallel"
    assert runs[1]["status"] == "completed"


def test_run_tree_evidence_lands_on_parent():
    c = _collector(
        ("tool_call", {"tool": "shell", "status": "done", "tool_args": "ls", "iteration": 1}),
        ("evidence_to_parent", {"tool": "shell", "iteration": 1, "evidence_chars": 42, "failed": False}),
    )
    runs = build_run_tree(c, task="x")
    parent = runs[0]
    assert len(parent["evidence"]) == 1
    entry = parent["evidence"][0]
    assert entry["tool"] == "shell"
    assert entry["iteration"] == 1
    assert entry["evidenceChars"] == 42
    assert entry["failed"] is False


def test_run_tree_tool_status_update_collapses_rows():
    c = _collector(
        ("tool_call", {"tool": "file_read", "status": "started", "tool_args": "a.py", "iteration": 2}),
        ("tool_call", {"tool": "file_read", "status": "failed", "tool_args": "a.py", "iteration": 2}),
    )
    runs = build_run_tree(c, task="read file")
    assert len(runs[0]["tools"]) == 1
    assert runs[0]["tools"][0]["status"] == "failed"


def test_phases_built_for_all_phase_event_types():
    c = _collector(
        ("plan_nodes_created", {"node_count": 3, "node_ids": ["a", "b", "c"]}),
        ("plan_node_advanced", {"node_id": "a", "new_status": "completed", "subgoal": "install deps", "iteration": 1}),
        ("agent_loop_gate_passed", {"intent": "analyze", "iterations": 2}),
        ("agent_loop_gate_failed_replan", {"intent": "analyze", "unmet": ["x", "y"]}),
        ("orchestrator_replan_start", {"intent": "analyze", "iteration": 2}),
        ("orchestrator_replan_done", {"confidence": 0.85, "intent": "analyze"}),
        ("orchestrator_replan_failed", {"error": "boom", "intent": "analyze"}),
        ("agent_loop_failure", {"reason": "criteria unmet", "failure_type": "criteria_unmet"}),
    )
    phases = build_agent_phases(c)
    assert len(phases) == 8
    types = [p["type"] for p in phases]
    assert types == [
        "plan_created",
        "node_advanced",
        "gate_passed",
        "gate_failed_replan",
        "orchestrator_replan_start",
        "orchestrator_replan_done",
        "orchestrator_replan_failed",
        "agent_loop_failure",
    ]
    # plan_created label pluralizes
    assert phases[0]["label"] == "Plan built — 3 steps"
    # deterministic ids — a second build produces identical ids (no re-random)
    phases2 = build_agent_phases(c)
    assert [p["id"] for p in phases] == [p["id"] for p in phases2]


def test_phases_skip_events_missing_required_fields():
    c = _collector(
        ("plan_nodes_created", {"node_count": 0}),
        ("plan_node_advanced", {"node_id": ""}),
        ("agent_loop_gate_passed", {}),
    )
    phases = build_agent_phases(c)
    # gate_passed always builds; the empty plan/gate entries are skipped
    assert len(phases) == 1
    assert phases[0]["type"] == "gate_passed"


def test_phases_singular_plan_label():
    c = _collector(("plan_nodes_created", {"node_count": 1, "node_ids": ["a"]}))
    phases = build_agent_phases(c)
    assert phases[0]["label"] == "Plan built — 1 step"
    assert phases[0]["detail"] == "a"


def test_phase_event_types_cover_frontend_strip():
    # The frontend's phase strip handles exactly these event types
    # (useLocalMind.ts PHASE_EVENT_TYPES) — keep them in sync.
    assert PHASE_EVENT_TYPES == {
        "plan_nodes_created",
        "plan_node_advanced",
        "agent_loop_gate_passed",
        "agent_loop_gate_failed_replan",
        "orchestrator_replan_start",
        "orchestrator_replan_done",
        "orchestrator_replan_failed",
        "agent_loop_failure",
    }


# ── build_workspace_artifacts (persist filter) ─────────────────────────────────

def test_workspace_artifacts_trivial_turn_yields_none():
    """A trivial chat turn (no tools/evidence/children/error) must not
    persist a bare parent-only run tree — it would override the last
    interesting turn's tree on reload."""
    c = ObsCollector()
    c.emit("agent_runtime_start", agent="parent")
    agent_runs, agent_phases = build_workspace_artifacts(c, task="hello")
    assert agent_runs is None
    assert agent_phases is None


def test_workspace_artifacts_tool_turn_persists_tree():
    c = ObsCollector()
    c.emit("tool_call", tool="shell", status="done", tool_args="ls", iteration=1)
    agent_runs, _ = build_workspace_artifacts(c, task="list files")
    assert agent_runs is not None
    assert agent_runs[0]["name"] == "parent"
    assert len(agent_runs[0]["tools"]) == 1


def test_workspace_artifacts_error_turn_persists_failed_tree():
    c = ObsCollector()
    agent_runs, _ = build_workspace_artifacts(
        c, task="x", root_error="zen returned 429: quota exceeded"
    )
    assert agent_runs is not None
    assert agent_runs[0]["status"] == "failed"
    assert agent_runs[0]["error"] == "zen returned 429: quota exceeded"
