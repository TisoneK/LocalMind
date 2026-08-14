"""
Observability event bus — lightweight structured event emission.

The engine calls obs_emit() for every pipeline step. The chat route
subscribes via ObsSubscription to forward events as SSE JSON chunks.

Design: a simple per-request list. No background threads, no global state.
The Engine receives an optional ObsSubscription at process() call time.
"""

from __future__ import annotations

from dataclasses import dataclass


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
        # Keep a request-local history separate from the pending queue.
        # ``drain()`` must remain destructive for SSE flushing, while
        # structured observation snapshots need events already forwarded.
        self._history: list[ObsEvent] = []

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
        event = ObsEvent(type=event_type, data=safe_data)
        self._events.append(event)
        self._history.append(event)

    def drain(self) -> list[ObsEvent]:
        events, self._events = self._events, []
        return events

    def all(self) -> list[ObsEvent]:
        """Return pending events without clearing them."""
        return list(self._events)

    def drain_matching(self, event_types: set[str] | frozenset[str]) -> list[ObsEvent]:
        """Remove and return only events whose type is in ``event_types``.

        The SSE transport uses this while the engine is awaiting a slow model
        or tool: progress events can be delivered immediately without stealing
        unrelated observations from the normal bridge.
        """
        matched: list[ObsEvent] = []
        remaining: list[ObsEvent] = []
        for event in self._events:
            (matched if event.type in event_types else remaining).append(event)
        self._events = remaining
        return matched

    def history(self) -> list[ObsEvent]:
        """Return every event emitted during this request, without clearing."""
        return list(self._history)


# ADR-18 P3 (Session 176): delegation streaming/UX — the sub-agent's
# progress is visible to the user, but its raw tool results stay internal
# to the child/parent agent contract. A delegated child gets a
# ChildObsProxy instead of a bare collector: the child behaves exactly
# as before (its own event list drives its internal behavior — failure
# memory, SSE, etc.), while only progress metadata is forwarded to the
# parent's collector.
#
# Deliberately NOT forwarded: agent_loop_start/agent_loop_done,
# turn_complete, intent_classified, stage_timing — those are the
# PARENT's UI state (intent display, metrics, timeline). Forwarding the
# child's CHAT intent would clobber the parent's intent in the Observe
# panel.
class ChildObsProxy(ObsCollector):
    """Delegated child's observability collector.

    Keeps its own event list (the child's internal behavior is
    unchanged) AND forwards user-visible progress to the parent
    collector. Raw child tool output remains internal so the parent agent,
    not the presentation layer, consumes it.
    """

    # Event types the frontend renders as tool progress (the chat.py
    # bridge converts these to top-level `tool_call` SSE events).
    _FORWARD_TYPES = frozenset({"tool_call", "tool_status"})

    def __init__(self, parent, agent_name: str):
        super().__init__()
        self._parent = parent
        self._agent = agent_name

    def emit(self, event_type: str, **data):
        super().emit(event_type, **data)
        if event_type in self._FORWARD_TYPES and self._parent is not None:
            tagged = dict(data)
            if event_type == "tool_call":
                # The child loop already consumes this output and returns its
                # final result to the parent. Forward labels/status only — raw
                # observations must never become user-facing child output.
                tagged.pop("output", None)
            tagged["agent"] = self._agent  # which sub-agent did this
            self._parent.emit(event_type, **tagged)
