"""Tests for the server-side Agent Workspace reconstruction (Session 267).

The Agents tab (run tree) and phase strip are frontend-only live state, so the
runtime rebuilds them from the request's obs events at persist time. These
tests pin the reconstruction: parent root + tool attachment, delegation
children, evidence entries, delegation completion, and the phase strip.
"""

import pytest

from core.agent_workspace import (
    RUN_LIFECYCLE_TYPES,
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
    """The chat strip keeps ONLY the Session 181 decision-history set — the
    lifecycle narration moved to the run tree (test_run_tree_lifecycle...)."""
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


def test_run_tree_lifecycle_phases_on_parent():
    """Lifecycle obs events narrate the ACTIVE AGENT — they land on the
    parent run's `phases` (Agents tab), not the chat strip."""
    c = _collector(
        ("agent_initialization_start", {}),
        ("agent_initialization_understanding", {"understanding": "the user wants the file listed"}),
        ("agent_initialization_ack", {"acknowledgement": "On it!"}),
        ("agent_initialization_done", {"mode": "execute", "objective": "list the files"}),
        ("agent_planning_done", {"iteration": 1}),
        ("agent_thinker_start", {"iteration": 2}),
        ("agent_thinker_done", {"iteration": 2}),
        ("agent_loop_start", {}),
        ("agent_loop_done", {"direct": False, "iterations": 3, "hit_limit": True}),
    )
    runs = build_run_tree(c, task="list files")
    phases = runs[0]["phases"]
    types = [p["type"] for p in phases]
    assert types == [
        "initializing",
        "understanding",
        "acknowledged",
        "initialized",
        "planned",
        "thinking",
        "thinking_done",
        "working",
        "turn_done",
    ]
    # details carry the payload text
    assert phases[1]["detail"] == "the user wants the file listed"
    assert phases[2]["detail"] == "On it!"
    assert phases[3]["label"] == "Understood — execute mode"
    assert phases[3]["detail"] == "list the files"
    # agent_loop_done detail carries iterations + hit-limit note
    assert phases[8]["detail"] == "iteration limit reached; 3 iterations"
    # the chat strip does NOT narrate lifecycle
    assert build_agent_phases(c) == []


def test_run_tree_parent_carries_classify_title():
    """The classify call names the turn ("Fetch Weather") on the
    agent_initialization_done event; the persisted parent node carries it as
    `title` so a reloaded run tree heads the turn like the live UI does."""
    c = _collector(
        ("agent_initialization_start", {}),
        ("agent_initialization_done", {"mode": "execute", "objective": "x", "title": "Fetch Weather"}),
    )
    runs = build_run_tree(c, task="what's the weather in Kitengela?")
    assert runs[0]["title"] == "Fetch Weather"

    # No title on the event → no title key (UI falls back to "Turn N").
    c2 = _collector(("agent_initialization_done", {"mode": "direct"}))
    assert "title" not in build_run_tree(c2, task="hi")[0]


def test_run_tree_child_lifecycle_phases_attach_to_child():
    """Child lifecycle events (agent-tagged by ChildObsProxy) land on the
    child run, not the parent; untagged events stay on the parent."""
    c = _collector(
        ("delegation_started", {"target_agent": "research", "task": "find weather", "run_id": "run-123", "depth": 1}),
        ("agent_initialization_start", {"agent": "research"}),
        ("agent_initialization_understanding", {"agent": "research", "understanding": "the user wants the weather"}),
        ("agent_initialization_done", {"agent": "research", "mode": "execute"}),
        # parent's own lifecycle, emitted around the delegation
        ("agent_loop_done", {"direct": False, "iterations": 4}),
    )
    runs = build_run_tree(c, task="weather report")
    parent, child = runs
    assert [p["type"] for p in child["phases"]] == [
        "initializing",
        "understanding",
        "initialized",
    ]
    assert child["phases"][1]["detail"] == "the user wants the weather"
    # the parent got only its own untagged event
    assert [p["type"] for p in parent["phases"]] == ["turn_done"]


def test_run_tree_lifecycle_phases_sorted_narratively():
    """The loop emits agent_loop_start BEFORE the init events — the phases
    must still read "getting started → understood → working → done" (sorted
    by canonical rank on attach, stable for equal ranks)."""
    c = _collector(
        ("agent_loop_start", {}),
        ("agent_initialization_start", {}),
        ("agent_initialization_done", {"mode": "direct"}),
        ("agent_loop_done", {"direct": True}),
    )
    runs = build_run_tree(c, task="hi")
    assert [p["type"] for p in runs[0]["phases"]] == [
        "initializing",
        "initialized",
        "working",
        "turn_done",
    ]


def test_run_tree_lifecycle_direct_turn_detail():
    """agent_loop_done on a direct turn carries the 'answered directly' note
    on the run's phases."""
    c = _collector(("agent_loop_done", {"direct": True, "iterations": 0}))
    runs = build_run_tree(c, task="hi")
    phases = runs[0]["phases"]
    assert len(phases) == 1
    assert phases[0]["type"] == "turn_done"
    assert phases[0]["detail"] == "answered directly"


def test_run_tree_lifecycle_skips_empty_payloads():
    """understanding/ack events without text produce no phase entry."""
    c = _collector(
        ("agent_initialization_understanding", {}),
        ("agent_initialization_ack", {"acknowledgement": ""}),
    )
    runs = build_run_tree(c, task="x")
    assert runs[0]["phases"] == []


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


def test_run_lifecycle_types_cover_workspace_narration():
    # The Agents-tab run narration handles exactly these event types
    # (frontend useLocalMind.ts RUN_LIFECYCLE_TYPES) — keep them in sync.
    assert RUN_LIFECYCLE_TYPES == {
        "agent_initialization_start",
        "agent_initialization_understanding",
        "agent_initialization_ack",
        "agent_initialization_done",
        "agent_planning_done",
        "agent_thinker_start",
        "agent_thinker_done",
        "agent_loop_start",
        "agent_loop_done",
    }


# ── build_workspace_artifacts (persist filter) ─────────────────────────────────

def test_workspace_artifacts_trivial_turn_yields_none():
    """A trivial chat turn (no tools/evidence/children/error/phases) must not
    persist a bare parent-only run tree — it would override the last
    interesting turn's tree on reload."""
    c = ObsCollector()
    c.emit("agent_runtime_start", agent="parent")
    agent_runs, agent_phases = build_workspace_artifacts(c, task="hello")
    assert agent_runs is None
    assert agent_phases is None


def test_workspace_artifacts_lifecycle_only_turn_persists_tree():
    """A direct turn still narrates the lifecycle on the run — phases make
    the tree worth persisting so the Agents tab restores it on reload."""
    c = ObsCollector()
    c.emit("agent_initialization_start", intent="analyze")
    c.emit("agent_initialization_done", mode="direct")
    c.emit("agent_loop_start")
    c.emit("agent_loop_done", direct=True)
    agent_runs, agent_phases = build_workspace_artifacts(c, task="hello")
    assert agent_runs is not None
    assert [p["type"] for p in agent_runs[0]["phases"]] == [
        "initializing",
        "initialized",
        "working",
        "turn_done",
    ]
    # the chat strip stays empty for a direct turn (lifecycle moved out)
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
