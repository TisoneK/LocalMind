"""Workspace telemetry carries event-time, not rebuild-time stamps.

Regression (live export 2026-10-31, "Quick check-in"): every phase, run
boundary and evidence entry in the persisted agentRuns/agentPhases was
stamped with ``_now_ms()`` at persist-time REBUILD, so a stored turn showed
``startedAt == completedAt`` (and every phase sharing one timestamp) no
matter how long the turn actually ran — the export showed identical stamps
on a ~100 s turn. The record must reconstruct the turn: ``ObsEvent`` now
carries its emit-time ``ts`` and the workspace builders read it.
"""

from __future__ import annotations

import time

import pytest

from core.obs import ObsCollector

from core.agent_workspace import (
    build_agent_phases,
    build_run_tree,
    build_workspace_artifacts,
)


def test_obs_event_stamps_emit_time():
    collector = ObsCollector()
    collector.emit("agent_thinker_start")
    first = collector.history()[0]
    time.sleep(0.012)
    collector.emit("agent_thinker_done")
    second = collector.history()[1]

    assert second.ts > first.ts
    # Both are wall-clock ms near "now" — within a minute of it.
    now = int(time.time() * 1000)
    assert abs(now - first.ts) < 60_000
    assert abs(now - second.ts) < 60_000


def test_sse_payload_shape_unchanged():
    """The wire must not grow the ts field: the live frontend keeps its own
    arrival clock; ts is for durable reconstruction only."""
    collector = ObsCollector()
    collector.emit("agent_loop_start", iteration=1)
    sse = collector.history()[0].to_sse_dict()
    assert set(sse.keys()) == {"obs_event"}
    assert set(sse["obs_event"].keys()) == {"type", "data"}
    assert "ts" not in sse["obs_event"]["data"]


def test_run_tree_boundaries_come_from_events():
    """startedAt/completedAt derive from the event stream when the caller
    supplies none — the first event is the turn starting, the last is the
    end of what it did. They must differ on a turn that took time."""
    collector = ObsCollector()
    collector.emit("agent_initialization_start")
    first_ts = collector.history()[0].ts
    time.sleep(0.012)
    collector.emit("agent_loop_done", direct=True, iterations=1)
    last_ts = collector.history()[-1].ts

    runs = build_run_tree(collector, task="Hey sup LM?")
    root = runs[0]
    assert root["startedAt"] == first_ts
    assert root["completedAt"] == last_ts
    assert root["startedAt"] < root["completedAt"]


def test_explicit_boundaries_still_win():
    """Callers that know the real turn window (runtime stamps) keep priority
    over the event-derived fallback."""
    collector = ObsCollector()
    collector.emit("agent_initialization_start")
    runs = build_run_tree(collector, task="t", started_at=1000, completed_at=9000)
    assert runs[0]["startedAt"] == 1000
    assert runs[0]["completedAt"] == 9000


def test_lifecycle_phase_carries_event_time():
    collector = ObsCollector()
    collector.emit("agent_initialization_start")
    evt_ts = collector.history()[0].ts
    time.sleep(0.012)
    collector.emit("agent_loop_done", direct=True, iterations=2)
    done_ts = collector.history()[-1].ts

    runs = build_run_tree(collector, task="t")
    phases = runs[0]["phases"]
    assert [p["type"] for p in phases] == ["initializing", "turn_done"]
    assert phases[0]["timestamp"] == evt_ts
    assert phases[1]["timestamp"] == done_ts
    assert phases[0]["timestamp"] < phases[1]["timestamp"]


def test_phase_strip_carries_event_time():
    collector = ObsCollector()
    collector.emit("plan_nodes_created", node_count=2, node_ids=["a", "b"])
    plan_ts = collector.history()[0].ts
    time.sleep(0.012)
    collector.emit(
        "agent_loop_gate_failed_replan",
        intent="analyze",
        iteration=1,
        unmet=["completion judge judged the reply still pending"],
    )
    gate_ts = collector.history()[-1].ts

    phases = build_agent_phases(collector)
    by_type = {p["type"]: p for p in phases}
    assert by_type["plan_created"]["timestamp"] == plan_ts
    assert by_type["gate_failed_replan"]["timestamp"] == gate_ts
    assert plan_ts < gate_ts


def test_persisted_artifacts_reconstruct_a_spread():
    """End to end: the workspace artifacts persisted with the message must
    show a run window that spans the turn, not one instant."""
    collector = ObsCollector()
    collector.emit("agent_initialization_start")
    time.sleep(0.012)
    collector.emit(
        "tool_call", tool="shell", label="Run ls", status="completed",
        tool_args="ls /tmp", output="f", latency_ms=5, iteration=1,
    )
    time.sleep(0.012)
    collector.emit("agent_loop_done", iterations=1)

    agent_runs, agent_phases = build_workspace_artifacts(collector, task="list tmp")
    root = agent_runs[0]
    assert root["startedAt"] < root["completedAt"]
    phase_stamps = [p["timestamp"] for p in root["phases"]]
    assert phase_stamps == sorted(phase_stamps)
