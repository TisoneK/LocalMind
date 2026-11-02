"""
Unit tests for the durable per-turn execution trace primitives
(``core/turn_trace.py``, B-2026-11-01-26).

Contract locked here:
  - turn ids are unique and transport-shaped;
  - the payload fingerprint carries sizes and a hash — NEVER payload content;
  - a bound TurnContext turns a ModelCallWatch into a real event stream
    (started → response → first byte → completed/failed), every timestamp
    epoch-ms, the heartbeat's monotonic clock always labelled beside an
    epoch anchor;
  - without a request context the watch is a no-op (CLI / background jobs);
  - completed/failed are idempotent — double-close cannot double-count.
"""

from __future__ import annotations

import time

import pytest

from core.obs import ObsCollector
from core.turn_trace import (
    ModelCallWatch,
    TurnContext,
    bind_turn,
    current_turn,
    current_turn_id,
    epoch_ms,
    new_turn_id,
    payload_fingerprint,
    reset_turn,
    start_model_call,
)


@pytest.fixture
def turn_env():
    """A bound TurnContext over a fresh collector, reset on exit."""
    collector = ObsCollector()
    ctx = TurnContext(turn_id=new_turn_id(), session_id="sess-trace-test", collector=collector)
    token = bind_turn(ctx)
    yield ctx, collector
    reset_turn(token)


# ── identity ─────────────────────────────────────────────────────────────────


def test_new_turn_id_unique_and_prefixed():
    ids = {new_turn_id() for _ in range(200)}
    assert len(ids) == 200
    for tid in ids:
        assert tid.startswith("turn-")


def test_turn_context_defaults_started_to_now():
    before = epoch_ms()
    ctx = TurnContext(turn_id=new_turn_id(), session_id="s", collector=ObsCollector())
    assert before <= ctx.started_epoch_ms <= epoch_ms()


# ── payload fingerprint ──────────────────────────────────────────────────────


def test_payload_fingerprint_covers_messages_and_tools():
    msgs = [{"role": "system", "content": "You are LocalMind."}]
    tools = [{"type": "function", "function": {"name": "shell"}}]
    fp = payload_fingerprint(msgs, tools)
    assert fp["payload_chars"] > 0
    assert len(fp["payload_sha"]) == 16


def test_payload_fingerprint_is_content_free():
    """The fingerprint must never carry the payload text — a secret pasted
    into a message must not leak into the durable trace."""
    secret = "sk-super-secret-key-12345"
    msgs = [{"role": "user", "content": f"my key is {secret}"}]
    fp = payload_fingerprint(msgs)
    assert secret not in str(fp)


def test_payload_fingerprint_stable_for_same_bytes():
    msgs = [{"role": "user", "content": "same"}]
    assert payload_fingerprint(msgs) == payload_fingerprint(list(msgs))


# ── watch lifecycle (bound context) ─────────────────────────────────────────


def test_watch_without_context_is_noop():
    watch = start_model_call(provider="p", model="m", messages=[{"role": "user", "content": "x"}])
    assert isinstance(watch, ModelCallWatch) or watch is not None
    # No-ops must never raise, even completed/failed out of order.
    watch.completed({"prompt_tokens": 1})
    watch.failed("late")
    watch.first_byte()
    watch.response_received(200)


def test_watch_emits_full_boundary_sequence(turn_env):
    ctx, collector = turn_env
    watch = start_model_call(
        provider="zai",
        model="glm-4.5-flash",
        intent="chat",
        mode="tools",
        messages=[{"role": "user", "content": "hello"}],
        tools=[{"type": "function", "function": {"name": "shell"}}],
    )
    watch.response_received(200)
    watch.first_byte()
    watch.completed({"prompt_tokens": 10, "completion_tokens": 4, "cached_tokens": 8})

    types = [e.type for e in collector.history()]
    assert types == [
        "model_call_started",
        "provider_call_start",
        "model_call_response",
        "model_call_first_byte",
        "provider_first_byte",
        "model_call_completed",
    ]

    started = collector.history()[0].data
    assert started["provider"] == "zai"
    assert started["mode"] == "tools"
    assert started["tool_count"] == 1
    assert started["payload_chars"] > 0
    # Contents never ride the event — size + hash only.
    assert "hello" not in str(started)

    call_start = collector.history()[1].data
    # One clock rule: the monotonic heartbeat value always has an epoch-ms
    # anchor beside it.
    assert isinstance(call_start["started_at"], float)
    assert call_start["started_at_epoch_ms"] == started["submitted_at"]

    completed = collector.history()[-1].data
    assert completed["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 4,
        "cached_tokens": 8,
    }
    assert completed["duration_ms"] >= 0
    for evt in collector.history():
        assert isinstance(evt.ts, int) and evt.ts > 0


def test_watch_first_byte_idempotent(turn_env):
    ctx, collector = turn_env
    watch = start_model_call(provider="p", model="m", messages=[])
    watch.first_byte()
    watch.first_byte()
    watch.first_byte()
    firsts = [e for e in collector.history() if e.type == "model_call_first_byte"]
    assert len(firsts) == 1


def test_watch_completed_then_failed_cannot_double_close(turn_env):
    ctx, collector = turn_env
    watch = start_model_call(provider="p", model="m", messages=[])
    watch.completed({"prompt_tokens": 5})
    watch.failed("late failure")
    terminals = [e for e in collector.history() if e.type in ("model_call_completed", "model_call_failed")]
    assert len(terminals) == 1
    assert terminals[0].type == "model_call_completed"


def test_watch_failed_records_error_bounded(turn_env):
    ctx, collector = turn_env
    watch = start_model_call(provider="p", model="m", messages=[])
    watch.failed("x" * 5000)
    failed = [e for e in collector.history() if e.type == "model_call_failed"][0]
    assert len(failed.data["error"]) <= 300


def test_watch_429_response_does_not_close_response_milestone(turn_env):
    """A 429 is a retry, not a response — response_received stays open so the
    eventual 200 still stamps the real acceptance moment."""
    ctx, collector = turn_env
    watch = start_model_call(provider="p", model="m", messages=[])
    watch.retry(429, 0)
    watch.response_received(429)  # ignored — retries are recorded, not responses
    watch.response_received(200)
    responses = [e for e in collector.history() if e.type == "model_call_response"]
    retries = [e for e in collector.history() if e.type == "model_call_retry"]
    assert len(responses) == 1 and responses[0].data["status"] == 200
    assert len(retries) == 1


def test_current_turn_id_reads_binding(turn_env):
    ctx, _ = turn_env
    assert current_turn_id() == ctx.turn_id
    assert current_turn() is ctx
