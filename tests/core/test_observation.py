"""Tests for the additive structured observation contract."""

from __future__ import annotations

from core.obs import ObsCollector, ObsEvent
from core.observation import ObservationSnapshot
from core.workspace_state import WorkspaceSnapshot


def test_emit_keeps_json_containers_native_not_stringified():
    """ObsCollector.emit must NOT str() lists/dicts.

    The old `str(v)` turned the edit_file diff_hunks list into a Python-repr
    STRING, so the diff SSE event's `hunks` field was a string and the
    frontend's Array.isArray check silently dropped every diff (the preview
    Diff mode and inline chat DiffBlock never filled). JSON containers pass
    through to json.dumps natively; scalars are unchanged.
    """
    collector = ObsCollector()
    hunks = [{"type": "added", "content": "x", "newLine": 1}]
    collector.emit("file_diff", diff_hunks=hunks, path="/tmp/a.txt")
    collector.emit("stage_timing", latency_ms=0, status="skipped")

    drained = collector.drain()
    diff = next(e for e in drained if e.type == "file_diff")
    timing = next(e for e in drained if e.type == "stage_timing")
    assert diff.data["diff_hunks"] == hunks, "list must stay a list"
    assert diff.data["diff_hunks"][0]["type"] == "added"
    assert diff.data["path"] == "/tmp/a.txt"
    # Scalars still pass through natively (JSON handles them).
    assert timing.data["latency_ms"] == 0
    assert timing.data["status"] == "skipped"


def test_emit_skips_none_values():
    collector = ObsCollector()
    collector.emit("tool_call", tool="shell", output=None, label="Run")
    data = collector.drain()[0].data
    assert "output" not in data
    assert data["label"] == "Run"


def test_observation_snapshot_defaults_to_empty_workspace_and_events():
    """The contract can be created without runtime state."""
    observation = ObservationSnapshot()

    assert observation.workspace.git_available is False
    assert observation.recent_events == ()
    assert observation.timestamp > 0
    assert observation.format_context() == ""


def test_from_events_composes_workspace_and_structured_events():
    """Workspace formatting and event formatting coexist in one context."""
    workspace = WorkspaceSnapshot(
        git_available=True,
        git_branch="main",
        git_head="a" * 40,
        git_status=" M report.md",
    )
    events = [ObsEvent(type="tool_started", data={"tool": "file_read"})]

    observation = ObservationSnapshot.from_events(workspace, events)
    formatted = observation.format_context()

    assert observation.recent_events == tuple(events)
    assert "# Workspace State" in formatted
    assert "report.md" in formatted
    assert "# Recent Observation Events" in formatted
    assert '"tool": "file_read"' in formatted


def test_from_collector_captures_without_draining():
    """Creating a snapshot must not consume events needed by the SSE route."""
    collector = ObsCollector()
    collector.emit("step", number=2, optional=None)
    workspace = WorkspaceSnapshot(git_available=False)

    observation = ObservationSnapshot.from_collector(workspace, collector)

    assert len(observation.recent_events) == 1
    assert observation.recent_events[0].data == {"number": 2}
    assert len(collector.all()) == 1


def test_drain_matching_preserves_unrelated_pending_events():
    """Live tool flushing must not remove metrics or planning observations."""
    collector = ObsCollector()
    collector.emit("tool_call", tool="shell", status="done")
    collector.emit("turn_complete", total_latency_ms=42)

    flushed = collector.drain_matching({"tool_call", "tool_status"})

    assert [event.type for event in flushed] == ["tool_call"]
    assert [event.type for event in collector.all()] == ["turn_complete"]


def test_format_context_keeps_only_newest_events():
    """Formatting bounds event growth while retaining the newest observations."""
    events = [ObsEvent(type=f"event_{i}", data={"i": i}) for i in range(4)]
    observation = ObservationSnapshot.from_events(WorkspaceSnapshot(), events)

    formatted = observation.format_context(max_events=2)

    assert "event_0" not in formatted
    assert "event_1" not in formatted
    assert "event_2" in formatted
    assert "event_3" in formatted


def test_format_context_with_zero_event_limit_omits_events():
    """A zero event limit produces workspace-only context."""
    event = ObsEvent(type="hidden", data={"value": "not shown"})
    observation = ObservationSnapshot.from_events(WorkspaceSnapshot(), [event])

    assert observation.format_context(max_events=0) == ""


def test_event_payload_formatting_is_deterministic():
    """Event keys are sorted to make context and tests stable."""
    event = ObsEvent(type="state", data={"z": 1, "a": 2})
    observation = ObservationSnapshot.from_events(WorkspaceSnapshot(), [event])

    formatted = observation.format_context()

    assert '{"a": 2, "z": 1}' in formatted


def test_snapshot_capture_bounds_retained_event_history():
    """Long request histories retain only the newest bounded events."""
    events = [ObsEvent(type=f"event_{i}", data={"i": i}) for i in range(60)]

    observation = ObservationSnapshot.from_events(WorkspaceSnapshot(), events)

    assert len(observation.recent_events) == 50
    assert observation.recent_events[0].type == "event_10"
    assert observation.recent_events[-1].type == "event_59"


def test_public_summary_is_bounded_and_structured():
    """Public summaries cap workspace and event payload sizes."""
    observation = ObservationSnapshot.from_events(
        WorkspaceSnapshot(
            git_status="s" * 5000,
            git_diff_stat="d" * 5000,
            open_files=["f" * 1000 for _ in range(20)],
        ),
        [ObsEvent(type="large", data={"value": "x" * 5000}) for _ in range(25)],
    )

    summary = observation.to_public_summary()

    assert len(summary["workspace"]["git_status"]) == 4000
    assert len(summary["workspace"]["git_diff_stat"]) == 3000
    assert len(summary["workspace"]["open_files"]) == 10
    assert len(summary["recent_events"]) == 20
    assert summary["recent_events"][0]["data"]["truncated"] is True


def test_snapshot_copies_event_sequence_and_nested_payload():
    """Later mutations of source events do not alter the snapshot."""
    event = ObsEvent(type="first", data={"nested": {"value": 1}})
    events = [event]
    observation = ObservationSnapshot.from_events(WorkspaceSnapshot(), events)

    events.append(ObsEvent(type="second", data={}))
    event.data["nested"]["value"] = 99

    assert [item.type for item in observation.recent_events] == ["first"]
    assert observation.recent_events[0].data["nested"]["value"] == 1


def test_snapshot_copies_workspace_nested_state():
    """Later mutations of workspace state do not alter the snapshot."""
    workspace = WorkspaceSnapshot(
        last_build_result={"result": "pass", "details": {"count": 1}},
        open_files=["report.md"],
    )
    observation = ObservationSnapshot.from_events(workspace, [])

    workspace.last_build_result["details"]["count"] = 99
    workspace.open_files.append("notes.md")

    assert observation.workspace.last_build_result["details"]["count"] == 1
    assert observation.workspace.open_files == ["report.md"]


def test_public_state_accessors_return_defensive_copies():
    """Mutating returned state does not alter the captured observation."""
    observation = ObservationSnapshot.from_events(
        WorkspaceSnapshot(open_files=["report.md"]),
        [ObsEvent(type="state", data={"count": 1})],
    )

    returned_workspace = observation.workspace
    returned_workspace.open_files.append("notes.md")
    returned_events = observation.recent_events
    returned_events[0].data["count"] = 99

    assert observation.workspace.open_files == ["report.md"]
    assert observation.recent_events[0].data["count"] == 1
