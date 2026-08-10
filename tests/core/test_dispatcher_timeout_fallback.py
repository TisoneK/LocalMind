"""
Regression test for the Session 127 smoke-caught crash.

Scenario: the free-tier model is overloaded and the capability-inference
adapter stream produces NO output. `asyncio.wait_for(_thinking_queue.get(),
timeout=DISPATCHER_TIMEOUT_SECS)` fires, the collect task is cancelled, and
the post-loop `await asyncio.wait_for(_collect_task, timeout=5)` re-raises
CancelledError — a BaseException in py3.8+, which the `except
(TimeoutError, Exception)` handler does NOT catch. The CancelledError
escaped the generator and killed the ENTIRE request (traceback all the way
up through Engine.process) instead of falling back to the minimal plan.

Fix: await the collect task via `asyncio.gather(_collect_task,
return_exceptions=True)` so the child's CancelledError is absorbed as a
result, and add an explicit `except asyncio.CancelledError` for genuine
external cancellation (which must propagate).

These tests assert the CONTRACT: dispatch() never raises CancelledError on
a slow/hanging adapter; it yields a fallback plan instead.
"""

from __future__ import annotations

import asyncio

import pytest
from core import thinking_dispatcher as td
from core.models import StreamChunk
from core.obs import ObsCollector


class HangingAdapter:
    """Adapter whose chat() never yields anything (free-tier overload shape)."""

    async def chat(self, messages, temperature=0.7, **kwargs):
        # Never produce output; the dispatcher must time out, not hang forever.
        await asyncio.sleep(3600)
        yield StreamChunk(text="")  # pragma: no cover — unreachable


class EmptyAdapter:
    """Adapter that immediately yields an empty chunk, then finishes."""

    async def chat(self, messages, temperature=0.7, **kwargs):
        yield StreamChunk(text="")


async def _collect(dispatcher, message: str) -> list:
    """Drain dispatch() to exhaustion, returning every yielded item."""
    items: list = []
    async for item in dispatcher.dispatch(
        message=message,
        history=[],
        memory_facts=[],
        has_attachment=False,
        obs=ObsCollector(),
        session_id="test-session",
    ):
        items.append(item)
    return items


@pytest.mark.asyncio
async def test_hanging_adapter_falls_back_not_crashes(monkeypatch):
    """A silent adapter must trigger the timeout fallback, NOT CancelledError."""
    # Make the timeout small so the test is fast; the production default is 30s.
    monkeypatch.setattr(td, "DISPATCHER_TIMEOUT_SECS", 0.1)
    dispatcher = td.ThinkingDispatcher(HangingAdapter())

    # The bug: this raised CancelledError out of the generator.
    items = await asyncio.wait_for(_collect(dispatcher, "create hello world repo"), timeout=15)

    # We must get a usable plan (fallback) rather than an exception.
    plans = [i for i in items if not isinstance(i, StreamChunk)]
    assert plans, "expected a fallback plan after dispatcher timeout"


@pytest.mark.asyncio
async def test_hanging_adapter_does_not_raise_cancelled_error(monkeypatch):
    """dispatch() must never propagate CancelledError for a slow adapter."""
    monkeypatch.setattr(td, "DISPATCHER_TIMEOUT_SECS", 0.1)
    dispatcher = td.ThinkingDispatcher(HangingAdapter())

    try:
        await asyncio.wait_for(_collect(dispatcher, "hi"), timeout=15)
    except asyncio.CancelledError:  # pragma: no cover — the regression
        pytest.fail("dispatch() propagated CancelledError on adapter timeout")


@pytest.mark.asyncio
async def test_normal_adapter_still_works(monkeypatch):
    """Non-timeout path is unaffected: an empty-but-responsive adapter completes."""
    monkeypatch.setattr(td, "DISPATCHER_TIMEOUT_SECS", 5)
    dispatcher = td.ThinkingDispatcher(EmptyAdapter())

    # Should not raise; empty output falls through to the JSON-parse fallback.
    items = await asyncio.wait_for(_collect(dispatcher, "hello"), timeout=15)
    assert items is not None
