"""Push-based delivery of obs events on the chat SSE bridge.

Root cause (live-found on a real turn): the bridge only drained buffered obs
events when the engine yielded a text chunk or its heartbeat timer fired. While
a model call was in flight there were no chunks, so a tool that finished in
milliseconds was reported to the client a full heartbeat (5 s) later, and the
thinking/lifecycle events arrived in bursts. An obs emit now wakes the bridge.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest


def _decode(sse_frame: str) -> dict:
    for line in sse_frame.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    return {}


class TestObsWake:
    @pytest.mark.asyncio
    async def test_emit_sets_the_wake_event(self):
        from core.obs import ObsCollector

        obs = ObsCollector()
        wake = asyncio.Event()
        obs.attach_wake(asyncio.get_running_loop(), wake)
        obs.emit("tool_call", tool="shell", status="done")
        await asyncio.wait_for(wake.wait(), timeout=1)
        assert wake.is_set()

    @pytest.mark.asyncio
    async def test_emit_from_a_worker_thread_wakes_the_loop(self):
        from core.obs import ObsCollector

        obs = ObsCollector()
        wake = asyncio.Event()
        obs.attach_wake(asyncio.get_running_loop(), wake)
        threading.Thread(target=lambda: obs.emit("terminal_output", tool="shell")).start()
        await asyncio.wait_for(wake.wait(), timeout=1)
        assert len(obs.all()) == 1  # the event itself is still queued for draining

    def test_emit_after_the_loop_closed_does_not_raise(self):
        from core.obs import ObsCollector

        loop = asyncio.new_event_loop()
        obs = ObsCollector()
        obs.attach_wake(loop, asyncio.Event())
        loop.close()
        obs.emit("tool_call", tool="shell")  # must not raise into the engine
        obs.emit("tool_call", tool="shell")
        assert len(obs.all()) == 2

    def test_emit_without_a_transport_is_unchanged(self):
        from core.obs import ObsCollector

        obs = ObsCollector()
        obs.emit("x", a=1)
        assert [e.type for e in obs.drain()] == ["x"]


class TestKeepaliveFlush:
    @pytest.mark.asyncio
    async def test_wake_flushes_long_before_the_heartbeat(self):
        from api.routes.chat import _LIVE_FLUSH, _with_keepalives
        from core.models import StreamChunk

        release = asyncio.Event()

        async def slow_engine():
            await release.wait()
            yield StreamChunk(text="answer", done=True)

        wake = asyncio.Event()
        stream = _with_keepalives(slow_engine(), interval_s=30.0, wake=wake)
        nxt = asyncio.create_task(anext(stream))
        await asyncio.sleep(0.05)
        assert not nxt.done()  # nothing to deliver yet
        started = time.monotonic()
        wake.set()
        assert await asyncio.wait_for(nxt, timeout=2) is _LIVE_FLUSH
        assert time.monotonic() - started < 1.0
        assert not wake.is_set()  # cleared so the next emit wakes it again

        # the pending engine call was not cancelled by the flush
        release.set()
        chunk = await asyncio.wait_for(anext(stream), timeout=2)
        assert chunk.text == "answer"
        await stream.aclose()

    @pytest.mark.asyncio
    async def test_heartbeat_still_fires_on_its_own_cadence(self):
        from api.routes.chat import _with_keepalives

        async def silent_engine():
            await asyncio.sleep(10)
            yield None  # pragma: no cover

        stream = _with_keepalives(silent_engine(), interval_s=0.02, wake=asyncio.Event())
        assert await asyncio.wait_for(anext(stream), timeout=1) is None
        assert await asyncio.wait_for(anext(stream), timeout=1) is None
        await stream.aclose()

    @pytest.mark.asyncio
    async def test_engine_error_and_completion_propagate(self):
        from api.routes.chat import _with_keepalives

        async def boom():
            raise ValueError("engine failed")
            yield  # pragma: no cover

        with pytest.raises(ValueError, match="engine failed"):
            async for _ in _with_keepalives(boom(), interval_s=1.0, wake=asyncio.Event()):
                pass

        async def empty():
            return
            yield  # pragma: no cover

        assert [c async for c in _with_keepalives(empty(), 1.0, wake=asyncio.Event())] == []


class TestBridgeDeliversToolEventsWhileEngineIsPending:
    @pytest.mark.asyncio
    async def test_tool_done_reaches_the_client_before_the_next_model_chunk(self):
        """A tool emits `done`, then the (simulated) model call takes 2.5 s. The
        client must see the tool event promptly, not at the 5 s heartbeat or at
        the model's next chunk. Fails on the polling bridge."""
        from unittest.mock import patch

        from api.routes import chat
        from core.models import StreamChunk

        async def _process(self, message, session_id, file=None, filename=None,
                           content_type=None, obs=None, **kwargs):
            obs.emit("tool_call", tool="shell", label="Running: ls", status="done",
                     output="ok", latency_ms=3, iteration=1)
            await asyncio.sleep(2.5)  # the model call the tool result feeds
            yield StreamChunk(text="answer", done=True)

        seen: list[tuple[float, dict]] = []
        with patch("core.engine.Engine.process", _process):
            start = time.monotonic()
            async for frame in chat._event_stream("run ls", "push-delivery-1", False):
                seen.append((time.monotonic() - start, _decode(frame)))

        tool_at = [t for t, e in seen if e.get("type") == "tool_call"]
        assert tool_at, "the bridged tool_call SSE event never arrived"
        assert tool_at[0] < 1.0, f"tool event delayed {tool_at[0]:.2f}s behind the engine"
        # and it still ends normally with the answer
        assert any(e.get("type") == "token" and "answer" in e.get("content", "") for _, e in seen)
        assert seen[-1][1].get("type") == "done"
