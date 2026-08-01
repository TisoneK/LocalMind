"""Tests for the opt-in Engine observation snapshot boundary."""

from __future__ import annotations

import subprocess

from core.engine._pipeline import Engine
from core.obs import ObsCollector


def test_engine_snapshot_captures_events_without_draining(tmp_path):
    """The helper must leave request events available to the SSE bridge."""
    engine = object.__new__(Engine)
    engine._last_observation_snapshots = {}
    collector = ObsCollector()
    collector.emit("tool_started", tool="file_task", status="running")
    collector.drain()
    collector.emit("tool_status", tool="file_task", status="done")

    observation = engine.build_observation_snapshot(
        collector,
        cwd=str(tmp_path),
        session_id="session-1",
    )

    assert observation.workspace.git_available is False
    assert [event.type for event in observation.recent_events] == [
        "tool_started",
        "tool_status",
    ]
    assert observation.recent_events[1].data == {
        "tool": "file_task",
        "status": "done",
    }
    assert engine._last_observation_snapshots["session-1"] is observation
    assert collector.all()[0].type == "tool_status"
    assert collector.drain()[0].to_sse_dict() == {
        "obs_event": {
            "type": "tool_status",
            "data": {"tool": "file_task", "status": "done"},
        }
    }


def test_explicit_workspace_capture_does_not_use_global_turn_baseline(tmp_path):
    """Explicit workspace captures cannot inherit another workspace's HEAD."""
    from core.workspace_state import mark_turn_start

    other_repo = tmp_path / "other-repo"
    other_repo.mkdir()
    subprocess.run(["git", "init"], cwd=other_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=other_repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=other_repo,
        check=True,
        capture_output=True,
    )
    (other_repo / "README.md").write_text("initial\n")
    subprocess.run(["git", "add", "."], cwd=other_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=other_repo,
        check=True,
        capture_output=True,
    )

    engine = object.__new__(Engine)
    engine._last_observation_snapshots = {}
    mark_turn_start(cwd=str(other_repo))

    observation = engine.build_observation_snapshot(cwd=str(tmp_path))

    assert observation.workspace.git_available is False
    assert observation.workspace.git_diff_stat == ""


def test_engine_snapshot_without_collector_is_empty_but_structured(tmp_path):
    """The opt-in helper also provides a safe empty collector by default."""
    engine = object.__new__(Engine)
    engine._last_observation_snapshots = {}

    observation = engine.build_observation_snapshot(cwd=str(tmp_path))

    assert observation.workspace.git_available is False
    assert observation.recent_events == ()
    assert observation.format_context() == ""
    assert engine._last_observation_snapshots == {}
