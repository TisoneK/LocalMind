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

_MAX_FORMATTED_EVENTS = 20


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
        object.__setattr__(
            self,
            "_recent_events",
            tuple(deepcopy(event) for event in recent_events),
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
        """Capture the collector's currently buffered events without draining it."""

        return cls(workspace=workspace, recent_events=collector.all())

    @classmethod
    def from_events(
        cls,
        workspace: WorkspaceSnapshot,
        events: Iterable[ObsEvent],
    ) -> "ObservationSnapshot":
        """Create a snapshot from any iterable of structured observation events."""

        return cls(workspace=workspace, recent_events=events)

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


def _format_event_data(data: dict) -> str:
    """Return deterministic, robust JSON for one event payload."""

    try:
        return json.dumps(data, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(data)
