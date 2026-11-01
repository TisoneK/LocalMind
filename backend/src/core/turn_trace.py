"""
Durable per-turn execution trace — the request/turn/call identity layer.

The observability investigation (office/reviews/2026-11-01-full-execution-
observability-investigation.md) established that LocalMind records rich
events while a turn runs but persists only projections of them, and that
the least-observed stages are the routing decision (which path a turn took
and why) and the inside of every model call (submit → first byte → last
byte). This module supplies the two primitives the durable trace needs:

1. **TurnContext** — a per-request identity (``turn_id`` + session) bound at
   the transport boundary (chat.py), carried by ContextVar so every layer
   (runtime, loop, adapters) can stamp its events with the turn they serve.
2. **ModelCallWatch** — the adapter-level per-call boundary stamps: the
   request submitted, the provider's response received, the first content
   byte, and the completed/failed outcome with usage and a payload
   fingerprint. The watch is started by the ADAPTER (so every path — parent
   loop, fast path, auxiliary calls, failover candidates — is covered by
   construction, not by per-site wiring), looks up the active TurnContext,
   and is a no-op when no request context exists (CLI, background jobs).

Clock discipline (one rule): every timestamp is epoch-ms. A monotonic value
may appear only as an explicitly-labelled field beside an epoch anchor —
``started_at`` (monotonic, the heartbeat's contract) always travels with
``started_at_epoch_ms``.

Redaction rule: model-call events carry sizes and hashes, never payload
contents or key material.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - import cycle guard for typing only
    from core.obs import ObsCollector

__all__ = [
    "TurnContext",
    "new_turn_id",
    "epoch_ms",
    "bind_turn",
    "reset_turn",
    "current_turn",
    "current_turn_id",
    "payload_fingerprint",
    "start_model_call",
    "current_model_call",
    "ModelCallWatch",
]


def epoch_ms() -> int:
    """Wall-clock milliseconds — the only timestamp domain of the trace."""
    return int(time.time() * 1000)


def new_turn_id() -> str:
    """Mint a per-request turn id at the transport boundary."""
    return f"turn-{int(time.time() * 1000):x}-{uuid.uuid4().hex[:6]}"


@dataclass
class TurnContext:
    """One transport request's identity: the turn id, its session, and the
    event collector every layer of this request emits into."""

    turn_id: str
    session_id: str
    collector: "ObsCollector"
    started_epoch_ms: int = 0

    def __post_init__(self) -> None:
        if not self.started_epoch_ms:
            self.started_epoch_ms = epoch_ms()

    def emit(self, event_type: str, **data) -> None:
        self.collector.emit(event_type, **data)


_current_turn: ContextVar[Optional[TurnContext]] = ContextVar(
    "current_turn_context", default=None
)


def bind_turn(ctx: TurnContext):
    """Bind the request's TurnContext (transport boundary only)."""
    return _current_turn.set(ctx)


def reset_turn(token) -> None:
    _current_turn.reset(token)


def current_turn() -> Optional[TurnContext]:
    return _current_turn.get()


def current_turn_id() -> Optional[str]:
    ctx = _current_turn.get()
    return ctx.turn_id if ctx else None


def payload_fingerprint(messages: list, tools: Optional[list] = None) -> dict:
    """Size + hash of the outgoing payload — never the contents.

    The full payload stays available only behind the env-gated prompt audit
    (LOCALMIND_PROMPT_AUDIT); the durable trace carries just enough to know
    HOW BIG each call was and whether two calls carried the same bytes.
    """
    try:
        body = json.dumps(messages, default=str, ensure_ascii=False)
    except Exception:
        body = repr(messages)
    if tools:
        try:
            body = body + "\n" + json.dumps(tools, default=str, ensure_ascii=False)
        except Exception:
            body = body + "\n" + repr(tools)
    return {
        "payload_chars": len(body),
        "payload_sha": hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()[:16],
    }


class _NoopWatch:
    """The watch when no request context exists (CLI, background jobs).

    Every method is a cheap no-op; adapters never branch on it."""

    call_id = ""
    closed = True  # permanently settled — the finally-close-out skips it

    def response_received(self, status: int = 0) -> None:  # pragma: no cover
        pass

    def retry(self, status: int = 0, attempt: int = 0) -> None:  # pragma: no cover
        pass

    def first_byte(self) -> None:  # pragma: no cover
        pass

    def completed(self, usage: Optional[dict] = None) -> None:  # pragma: no cover
        pass

    def failed(self, error: str = "") -> None:  # pragma: no cover
        pass


_NOOP = _NoopWatch()


class ModelCallWatch:
    """Boundary stamps for ONE adapter-level model call.

    Emits (all epoch-ms):
      model_call_started    {call_id, provider, model, intent, mode,
                             submitted_at, payload_chars, payload_sha,
                             tool_count}
      provider_call_start   {provider, model, started_at (monotonic — the
                             heartbeat's contract), started_at_epoch_ms}
      model_call_response   {call_id, response_at, status}
      model_call_retry      {call_id, status, attempt}
      model_call_first_byte {call_id, first_byte_at}  (+ provider_first_byte)
      model_call_completed  {call_id, last_byte_at, duration_ms, usage}
      model_call_failed     {call_id, failed_at, error}
    """

    def __init__(
        self,
        ctx: TurnContext,
        provider: str,
        model: str,
        intent: str,
        mode: str,
        fingerprint: dict,
        tool_count: int = 0,
    ):
        self.call_id = f"call-{uuid.uuid4().hex[:10]}"
        self._ctx = ctx
        self._provider = provider
        self._model = model
        self._intent = intent
        self._mode = mode
        self._fingerprint = fingerprint
        self._tool_count = tool_count
        self._submitted_epoch = epoch_ms()
        self._submitted_mono = time.monotonic()
        self._first_byte_done = False
        self._response_done = False
        self._closed = False
        ctx.emit(
            "model_call_started",
            call_id=self.call_id,
            provider=provider,
            model=model,
            intent=intent,
            mode=mode,
            submitted_at=self._submitted_epoch,
            **fingerprint,
            tool_count=tool_count,
        )
        # The heartbeat's stall detection reads provider_call_start /
        # provider_first_byte pairs; emit them here so EVERY path that goes
        # through an adapter gets them (loop turns previously had neither —
        # the heartbeat could not fire there). started_at stays monotonic
        # (the heartbeat computes time.monotonic() - started_at); the epoch
        # anchor rides beside it so the record obeys the one-clock rule.
        ctx.emit(
            "provider_call_start",
            provider=provider,
            model=model,
            started_at=self._submitted_mono,
            started_at_epoch_ms=self._submitted_epoch,
        )

    def _mark_closed(self) -> None:
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    # ── boundary milestones ────────────────────────────────────────────
    def response_received(self, status: int = 0) -> None:
        if self._closed or self._response_done or status == 429:
            return
        self._response_done = True
        self._ctx.emit(
            "model_call_response", call_id=self.call_id, response_at=epoch_ms(), status=status
        )

    def retry(self, status: int = 0, attempt: int = 0) -> None:
        if self._closed:
            return
        self._ctx.emit(
            "model_call_retry", call_id=self.call_id, status=status, attempt=attempt
        )

    def first_byte(self) -> None:
        if self._closed or self._first_byte_done:
            return
        self._first_byte_done = True
        self._ctx.emit(
            "model_call_first_byte", call_id=self.call_id, first_byte_at=epoch_ms()
        )
        self._ctx.emit("provider_first_byte", call_id=self.call_id)

    def completed(self, usage: Optional[dict] = None) -> None:
        if self._closed:
            return
        self._closed = True
        last = epoch_ms()
        clean_usage: dict = {}
        if usage:
            for key in (
                "prompt_tokens",
                "completion_tokens",
                "cached_tokens",
                "total_tokens",
                "reasoning_tokens",
            ):
                val = usage.get(key)
                if val is not None:
                    try:
                        clean_usage[key] = int(val)
                    except (TypeError, ValueError):
                        pass
        self._ctx.emit(
            "model_call_completed",
            call_id=self.call_id,
            last_byte_at=last,
            duration_ms=last - self._submitted_epoch,
            usage=clean_usage,
        )

    def failed(self, error: str = "") -> None:
        if self._closed:
            return
        self._closed = True
        self._ctx.emit(
            "model_call_failed",
            call_id=self.call_id,
            failed_at=epoch_ms(),
            error=str(error)[:300],
        )


_current_call: ContextVar[Optional[ModelCallWatch]] = ContextVar(
    "current_model_call", default=None
)


def start_model_call(
    provider: str,
    model: str,
    intent: str = "",
    mode: str = "chat",
    messages: Optional[list] = None,
    tools: Optional[list] = None,
) -> ModelCallWatch:
    """Start a per-call watch at the adapter boundary.

    Returns a no-op watch when no request context is bound — the adapter
    code never branches on tracing being active."""
    ctx = _current_turn.get()
    if ctx is None:
        return _NOOP  # type: ignore[return-value]
    fingerprint = payload_fingerprint(messages or [], tools)
    watch = ModelCallWatch(
        ctx,
        provider=provider,
        model=model,
        intent=intent,
        mode=mode,
        fingerprint=fingerprint,
        tool_count=len(tools or []),
    )
    _current_call.set(watch)
    return watch


def current_model_call() -> Optional[ModelCallWatch]:
    """The active watch for this task — deep adapter internals (the HTTP
    send, the SSE line loop) stamp response/first-byte milestones on it
    without the public method needing to pass it down."""
    return _current_call.get()
