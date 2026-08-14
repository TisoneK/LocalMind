"""Parent-agent planning contract.

There is no dispatcher planning-skip helper anymore. Planning belongs to the
single parent AgentLoop and is not bypassed by a confidence label.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.engine import Engine
from core.models import StreamChunk


@pytest.mark.asyncio
async def test_parent_runtime_does_not_select_or_skip_planning():
    engine = Engine()
    captured: dict = {}

    async def fake_run(**kwargs):
        captured.update(kwargs)
        yield StreamChunk(text="planned", done=True)

    adapter = MagicMock()
    adapter.effective_context_window = 8192
    with patch("core.engine.get_adapter", return_value=adapter), patch.object(
        engine._agent_loop, "run", fake_run
    ):
        chunks = [
            chunk
            async for chunk in engine.process("run the tests", "planning-parent-1")
        ]

    assert chunks
    assert captured["agent_config"].name == "parent"
    assert captured["skip_planning"] is False
    assert captured["agent_config"].tools_enabled is True
