"""Structured runtime observations for LocalMind.

This module composes the existing workspace feedback snapshot with request-local
observability events.  It is deliberately opt-in: the agent loop, routing,
tool registry, and existing ``WorkspaceSnapshot`` contract remain unchanged.

Static capability metadata belongs in ``core.capabilities``; this module is
for dynamic state observed while a request is running.
"""

from __future__ import annotations

import json
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Iterable

from core.obs import ObsCollector, ObsEvent
from core.workspace_state import WorkspaceSnapshot, format_snapshot

_MAX_CAPTURE_EVENTS = 50
_MAX_FORMATTED_EVENTS = 20
_MAX_SUMMARY_EVENTS = 20
_MAX_SUMMARY_STRING_CHARS = 500
_MAX_SUMMARY_STATUS_CHARS = 4000
_MAX_SUMMARY_DIFF_CHARS = 3000


@dataclass(frozen=True, init=False)
class ObservationSnapshot:
    """A point-in-time composition of workspace state and runtime events.

    The snapshot owns private copies of its nested compatibility objects.
    Public properties return fresh copies, preserving the existing
    ``WorkspaceSnapshot`` and ``ObsEvent`` shapes without exposing mutable
    state that could change the captured observation.
    """

    _workspace: WorkspaceSnapshot
    _recent_events: tuple[ObsEvent, ...]
    timestamp: float

    def __init__(
        self,
        workspace: WorkspaceSnapshot | None = None,
        recent_events: Iterable[ObsEvent] = (),
        timestamp: float | None = None,
    ) -> None:
        """Capture owned copies of workspace and event state."""

        object.__setattr__(
            self,
            "_workspace",
            deepcopy(workspace) if workspace is not None else WorkspaceSnapshot(),
        )
        # Bound retained state at capture time, not only at API serialization.
        # Long-running requests can emit many progress events; keeping the
        # newest events is sufficient for diagnostics and avoids unbounded
        # per-session snapshot memory.
        captured_events = tuple(recent_events)[-_MAX_CAPTURE_EVENTS:]
        object.__setattr__(
            self,
            "_recent_events",
            tuple(deepcopy(event) for event in captured_events),
        )
        object.__setattr__(
            self,
            "timestamp",
            time.time() if timestamp is None else timestamp,
        )

    @property
    def workspace(self) -> WorkspaceSnapshot:
        """Return an isolated copy of the captured workspace state."""

        return deepcopy(self._workspace)

    @property
    def recent_events(self) -> tuple[ObsEvent, ...]:
        """Return isolated copies of the captured observation events."""

        return tuple(deepcopy(event) for event in self._recent_events)

    @classmethod
    def from_collector(
        cls,
        workspace: WorkspaceSnapshot,
        collector: ObsCollector,
    ) -> "ObservationSnapshot":
        """Capture every request event without draining the collector."""

        return cls(workspace=workspace, recent_events=collector.history())

    @classmethod
    def from_events(
        cls,
        workspace: WorkspaceSnapshot,
        events: Iterable[ObsEvent],
    ) -> "ObservationSnapshot":
        """Create a snapshot from any iterable of structured observation events."""

        return cls(workspace=workspace, recent_events=events)

    def to_public_summary(
        self,
        *,
        max_events: int = _MAX_SUMMARY_EVENTS,
    ) -> dict:
        """Return a bounded, JSON-safe summary for API consumers.

        This intentionally exposes a projection rather than the owned
        compatibility objects. It keeps response size bounded and prevents
        callers from observing or mutating internal snapshot state.
        """

        workspace = self._workspace
        build_result = workspace.last_build_result
        bounded_build = None
        if build_result:
            bounded_build = {
                "result": str(build_result.get("result", ""))[:100],
                "command": str(build_result.get("command", ""))[:_MAX_SUMMARY_STRING_CHARS],
                "output_tail": str(build_result.get("output_tail", ""))[:_MAX_SUMMARY_STRING_CHARS],
                "exit_code": build_result.get("exit_code"),
                "timestamp": build_result.get("timestamp"),
            }

        event_summaries = []
        if max_events > 0:
            for event in self._recent_events[-min(max_events, _MAX_SUMMARY_EVENTS) :]:
                event_summaries.append(
                    {
                        "type": event.type[:100],
                        "data": _bounded_event_data(event.data),
                    }
                )

        return {
            "timestamp": self.timestamp,
            "workspace": {
                "git_available": workspace.git_available,
                "git_branch": workspace.git_branch[:200],
                "git_head": workspace.git_head[:40],
                "git_status": workspace.git_status[:_MAX_SUMMARY_STATUS_CHARS],
                "git_diff_stat": workspace.git_diff_stat[:_MAX_SUMMARY_DIFF_CHARS],
                "last_build_result": bounded_build,
                "open_files": [str(path)[:_MAX_SUMMARY_STRING_CHARS] for path in workspace.open_files[:10]],
            },
            "recent_events": event_summaries,
        }

    def format_context(
        self,
        *,
        max_events: int = _MAX_FORMATTED_EVENTS,
    ) -> str:
        """Format useful workspace and event state for model context.

        The existing workspace formatter remains the source of truth for
        workspace state. Event payloads are JSON encoded with a string fallback
        so malformed third-party values cannot make context assembly fail.
        ``max_events`` bounds context growth while preserving the newest events.
        """

        sections: list[str] = []
        workspace_text = format_snapshot(self._workspace)
        if workspace_text:
            sections.append(workspace_text)

        if self._recent_events and max_events > 0:
            events = self._recent_events[-max_events:]
            event_lines = ["# Recent Observation Events"]
            for event in events:
                event_lines.append(
                    f"- {event.type}: {_format_event_data(event.data)}"
                )
            sections.append("\n".join(event_lines))

        return "\n\n".join(sections)


def _bounded_event_data(data: dict) -> dict:
    """Bound event payloads while retaining their structured shape when safe."""

    try:
        serialized = json.dumps(data, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return {"truncated": True, "preview": str(data)[:_MAX_SUMMARY_STRING_CHARS]}
    if len(serialized) <= _MAX_SUMMARY_STRING_CHARS:
        return json.loads(serialized)
    return {
        "truncated": True,
        "preview": serialized[:_MAX_SUMMARY_STRING_CHARS],
    }


def _format_event_data(data: dict) -> str:
    """Return deterministic, robust JSON for one event payload."""

    try:
        return json.dumps(data, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(data)
