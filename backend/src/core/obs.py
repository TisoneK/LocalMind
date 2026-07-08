"""
Observability event bus — lightweight structured event emission.

The engine calls obs_emit() for every pipeline step. The chat route
subscribes via ObsSubscription to forward events as SSE JSON chunks.

Design: a simple per-request list. No background threads, no global state.
The Engine receives an optional ObsSubscription at process() call time.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ObsEvent:
    type: str
    data: dict

    def to_sse_dict(self) -> dict:
        return {"obs_event": {"type": self.type, "data": self.data}}


class ObsCollector:
    """
    Collects observability events during a single request.
    The engine holds a reference and emits into it.
    The chat route drains it between SSE chunks.
    """
    def __init__(self):
        self._events: list[ObsEvent] = []

    def emit(self, event_type: str, **data):
        # FIX: Use JSON-safe serialization instead of str() to avoid
        # str(None) -> "None" which breaks Number("None") -> NaN in the frontend.
        # Skip None values entirely, and convert everything else to a string
        # only if it isn't already a number or bool (which JSON handles natively).
        safe_data = {}
        for k, v in data.items():
            if v is None:
                continue  # Skip None values entirely
            if isinstance(v, (int, float, bool)):
                safe_data[k] = v  # Keep numbers/bools as-is for JSON
            else:
                safe_data[k] = str(v)
        self._events.append(ObsEvent(type=event_type, data=safe_data))

    def drain(self) -> list[ObsEvent]:
        events, self._events = self._events, []
        return events

    def all(self) -> list[ObsEvent]:
        return list(self._events)
