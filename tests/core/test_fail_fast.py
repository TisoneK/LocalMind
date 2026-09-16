"""ADR-32 regressions for terminal provider errors in the parent runtime."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_parent_runtime_forwards_terminal_error_to_sse_boundary():
    """A parent error chunk must not become the generic empty-answer fallback."""
    from core.engine import Engine
    from core.models import StreamChunk

    raw_error = (
        'zen returned 401: {"error":{"type":"invalid_api_key",'
        '"message":"bad key"}}'
    )
    engine = Engine()
    adapter = MagicMock()
    adapter.effective_context_window = 8192

    async def parent_run(self, *args, **kwargs):
        yield StreamChunk(text="", done=True, error=raw_error)

    with (
        patch("core.agent_runtime.get_adapter", return_value=adapter),
        patch("core.agent_runtime.build_context", return_value=[{"role": "user", "content": "inspect"}]),
        patch.object(engine, "_memory_facts", new=AsyncMock(return_value=[])),
        patch("core.agent_runtime.ParentAgent.run", parent_run),
    ):
        chunks = [
            chunk
            async for chunk in engine.process("inspect the project", "adr32-runtime")
        ]

    errors = [chunk.error for chunk in chunks if chunk.error]
    assert errors == [raw_error]
    assert not any("no usable final answer" in chunk.text for chunk in chunks)
    assert any(chunk.done for chunk in chunks)
