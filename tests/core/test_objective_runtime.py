"""Tests for the autonomous objective supervisor (ADR-16 specific-task loop)."""

from __future__ import annotations

import asyncio

import pytest
from core.models import StreamChunk
from core.objective_runtime import ObjectiveRuntime


class FakeEngine:
    """Mimics the real engine: yields chunks AND emits obs events.

    The real engine emits `agent_loop_done` (with hit_limit=True when the
    model ran out of iterations, without it on a natural end). The runtime
    uses that event to decide whether to continue to the next round.
    """

    def __init__(self, chunks, hit_limit: bool = False, chunk_delay: float = 0.0):
        self.chunks = chunks
        self.hit_limit = hit_limit
        self.chunk_delay = chunk_delay
        self.calls = []

    async def process(self, **kwargs):
        self.calls.append(kwargs)
        for chunk in self.chunks:
            if self.chunk_delay:
                await asyncio.sleep(self.chunk_delay)
            else:
                await asyncio.sleep(0)
            yield chunk
        # Mirror the real engine: agent_loop_done is a TERMINAL event,
        # emitted after the stream (several real paths emit it with no
        # following chunk). This ordering is what the runtime's post-stream
        # drain must catch.
        obs = kwargs.get("obs")
        if obs is not None:
            if self.hit_limit:
                obs.emit("agent_loop_done", intent="research", iterations=8, hit_limit=True)
            else:
                obs.emit("agent_loop_done", intent="research", iterations=3)


def _wait_for_status(runtime, objective_id, wanted, rounds=100):
    """Poll the store until the objective reaches a terminal-ish status."""

    async def _wait():
        for _ in range(rounds):
            current = runtime.store.get(objective_id)
            if current and current.status == wanted:
                return current
            await asyncio.sleep(0.01)
        return runtime.store.get(objective_id)

    return _wait()


@pytest.mark.asyncio
async def test_runtime_completes_read_only_objective(tmp_db):
    engine = FakeEngine([StreamChunk(text="Research complete", done=False), StreamChunk(text="", done=True)])
    runtime = ObjectiveRuntime(engine, tmp_db)
    objective = runtime.store.create("objective-runtime-1", "session-runtime", "Research FastAPI")

    await runtime.start()
    current = await _wait_for_status(runtime, objective.id, "completed")
    await runtime.stop()

    assert current is not None
    assert current.status == "completed"
    assert current.result == "Research complete"
    assert engine.calls[0]["allowed_tool_names"] == ObjectiveRuntime.READ_ONLY_TOOLS
    # Natural end → exactly one engine pass.
    assert len(engine.calls) == 1


@pytest.mark.asyncio
async def test_runtime_blocks_when_engine_requests_approval(tmp_db):
    engine = FakeEngine([
        StreamChunk(
            text="I prepared the change.",
            done=True,
            metadata={"pending_write": {"path": "example.txt", "content": "safe"}},
        )
    ])
    runtime = ObjectiveRuntime(engine, tmp_db)
    objective = runtime.store.create("objective-runtime-2", "session-runtime", "Prepare a file change")

    await runtime.start()
    current = await _wait_for_status(runtime, objective.id, "blocked")
    await runtime.stop()

    assert current is not None
    assert current.status == "blocked"
    assert current.approval is not None
    assert "example.txt" in current.approval
    # Approval request stops the loop immediately — one round.
    assert len(engine.calls) == 1


@pytest.mark.asyncio
async def test_runtime_continues_rounds_on_iteration_limit(tmp_db):
    """When the engine's loop hits its iteration cap (hit_limit),
    the objective must run ANOTHER round on the same session — the model
    keeps going with accumulated history instead of giving up."""
    engine = FakeEngine(
        [StreamChunk(text="Found sources, continuing", done=False), StreamChunk(text="", done=True)],
        hit_limit=True,
    )
    runtime = ObjectiveRuntime(engine, tmp_db)
    objective = runtime.store.create("objective-runtime-3", "session-runtime", "Research and summarize")

    await runtime.start()
    current = await _wait_for_status(runtime, objective.id, "completed")
    await runtime.stop()

    assert current is not None
    assert current.status == "completed"
    # With hit_limit every round and no natural end, the runtime runs all
    # MAX_OBJECTIVE_ROUNDS rounds before giving up gracefully.
    assert len(engine.calls) == ObjectiveRuntime.MAX_OBJECTIVE_ROUNDS
    # Every round reused the same execution session (history accumulates).
    sessions = {call["session_id"] for call in engine.calls}
    assert len(sessions) == 1
    # All rounds used a continuation prompt after the first.
    assert engine.calls[0]["message"] == "Research and summarize"
    assert engine.calls[1]["message"] == ObjectiveRuntime.ROUND_CONTINUATION
    # Text ACCUMULATES across rounds into the final result — each round
    # yielded the same chunk, so it appears once per round.
    assert current.result.count("Found sources, continuing") == ObjectiveRuntime.MAX_OBJECTIVE_ROUNDS


@pytest.mark.asyncio
async def test_runtime_natural_end_after_hit_limit_stops_loop(tmp_db):
    """A round that starts under hit_limit but ends naturally (e.g. a
    per-round success) must NOT keep looping."""
    engine = FakeEngine(
        [StreamChunk(text="Done already", done=False), StreamChunk(text="", done=True)],
        hit_limit=False,
    )
    runtime = ObjectiveRuntime(engine, tmp_db)
    objective = runtime.store.create("objective-runtime-4", "session-runtime", "Quick task")

    await runtime.start()
    current = await _wait_for_status(runtime, objective.id, "completed")
    await runtime.stop()

    assert current is not None
    assert current.status == "completed"
    assert len(engine.calls) == 1


@pytest.mark.asyncio
async def test_runtime_cancel_stops_loop_between_rounds(tmp_db):
    """If the user cancels while the objective is mid-loop, the next round
    must not start — the objective ends canceled."""
    engine = FakeEngine(
        [StreamChunk(text="", done=True)],
        hit_limit=True,
        # Slow the engine so the cancel lands mid-loop instead of after
        # all rounds have already run in <10ms.
        chunk_delay=0.05,
    )
    runtime = ObjectiveRuntime(engine, tmp_db)
    objective = runtime.store.create("objective-runtime-5", "session-runtime", "Long objective")

    await runtime.start()
    # Let the first round start, then cancel.
    for _ in range(50):
        current = runtime.store.get(objective.id)
        if current and current.status == "running":
            break
        await asyncio.sleep(0.01)
    runtime.store.request_cancel(objective.id)
    runtime.interrupt(objective.id)

    current = await _wait_for_status(runtime, objective.id, "canceled")
    await runtime.stop()

    assert current is not None
    assert current.status == "canceled"
    # The cancel landed mid-round-1 (the chunk_delay keeps round 1 in
    # flight while the test cancels), so the in-flight round is the ONLY
    # one that ran — the loop must not start round 2.
    assert len(engine.calls) == 1


@pytest.mark.asyncio
async def test_runtime_empty_every_round_marks_failed(tmp_db):
    """If every round yields no usable text (e.g. an overloaded free-tier
    model returning empty streams), the objective must NOT end 'completed'
    with an empty result — it ends failed with a diagnostic."""
    engine = FakeEngine(
        [StreamChunk(text="", done=True)],
        hit_limit=True,
    )
    runtime = ObjectiveRuntime(engine, tmp_db)
    objective = runtime.store.create("objective-runtime-6", "session-runtime", "Produce output")

    await runtime.start()
    current = await _wait_for_status(runtime, objective.id, "failed")
    await runtime.stop()

    assert current is not None
    assert current.status == "failed"
    assert "no usable response" in (current.error or "")
