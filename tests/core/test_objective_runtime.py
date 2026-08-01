"""Tests for the autonomous objective supervisor."""

from __future__ import annotations

import asyncio

import pytest

from core.models import StreamChunk
from core.objective_runtime import ObjectiveRuntime


class FakeEngine:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []

    async def process(self, **kwargs):
        self.calls.append(kwargs)
        for chunk in self.chunks:
            await asyncio.sleep(0)
            yield chunk


@pytest.mark.asyncio
async def test_runtime_completes_read_only_objective(tmp_db):
    engine = FakeEngine([StreamChunk(text="Research complete", done=False), StreamChunk(text="", done=True)])
    runtime = ObjectiveRuntime(engine, tmp_db)
    objective = runtime.store.create("objective-runtime-1", "session-runtime", "Research FastAPI")

    await runtime.start()
    for _ in range(50):
        current = runtime.store.get(objective.id)
        if current and current.status == "completed":
            break
        await asyncio.sleep(0.01)
    await runtime.stop()

    current = runtime.store.get(objective.id)
    assert current is not None
    assert current.status == "completed"
    assert current.result == "Research complete"
    assert engine.calls[0]["allowed_tool_names"] == ObjectiveRuntime.READ_ONLY_TOOLS


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
    for _ in range(50):
        current = runtime.store.get(objective.id)
        if current and current.status == "blocked":
            break
        await asyncio.sleep(0.01)
    await runtime.stop()

    current = runtime.store.get(objective.id)
    assert current is not None
    assert current.status == "blocked"
    assert current.approval is not None
    assert "example.txt" in current.approval
