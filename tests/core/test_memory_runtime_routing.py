"""The runtime route IS the decision: reads and deletes never reach the model.

Live failures drove this file:
- a memory question ("What do you know about me?") was answered from
  conversation context — listing a public IP the write path had refused to
  store — because the read reached the tool only when the model chose it;
- "forget X" waited on the model's tool choice, so removal was best-effort.

So the gates under test are: read turns are answered from the store's listing,
delete turns are applied then confirmed from a read-back, both leave the turn
trail (user row, reply row, turn-complete), and general-knowledge questions
still reach the model.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _runtime():
    # Import via core.engine: importing core.agent_runtime directly triggers a
    # circular import (agent_runtime → engine._helpers → engine/__init__ →
    # agent_runtime).
    from core.engine import AgentRuntime

    rt = AgentRuntime()
    rt._last_observation = {}
    store = MagicMock()
    store.get_history.return_value = []
    rt._store = store
    return rt


def _tool_result(content: str) -> MagicMock:
    result = MagicMock()
    result.success = True
    result.content = content
    return result


async def _collect(rt, message, session_id="sess-route"):
    from core.obs import ObsCollector

    obs = ObsCollector()
    chunks = [c async for c in rt.process(message, session_id, obs=obs)]
    return chunks, obs


class TestDeterministicReadRoute:
    @pytest.mark.asyncio
    async def test_read_is_answered_from_the_store_not_the_model(self):
        rt = _runtime()
        listing = _tool_result("**Stored facts:**\n- I prefer dark mode")
        with patch("tools.memory_tool.memory_op", return_value=listing) as mem:
            chunks, _obs = await _collect(rt, "What do you know about me?")

        mem.assert_awaited_once()
        assert mem.await_args.kwargs.get("operation") == "list"
        text = "".join(c.text for c in chunks)
        assert "I prefer dark mode" in text

    @pytest.mark.asyncio
    async def test_read_failure_changes_nothing_and_says_so(self):
        rt = _runtime()

        async def boom(*a, **k):
            raise RuntimeError("store offline")

        with patch("tools.memory_tool.memory_op", side_effect=boom):
            chunks, _obs = await _collect(rt, "What do you remember?")
        text = "".join(c.text for c in chunks)
        assert "couldn't read memory" in text
        assert "dark mode" not in text

    @pytest.mark.asyncio
    async def test_read_turn_leaves_the_full_trail(self):
        rt = _runtime()
        listing = _tool_result("**Stored facts:**\n- (nothing stored yet)")
        with patch("tools.memory_tool.memory_op", return_value=listing):
            _chunks, obs = await _collect(rt, "list all facts", "sess-trail")

        types = [e.type for e in obs.history()]
        assert "agent_loop_start" in types
        assert "agent_runtime_done" in types
        assert "turn_complete" in types
        # The user row is written BEFORE the reply (order matters for history
        # reads, which sort by timestamp ASC).
        from core.models import Role

        appends = [c for c in rt._store.method_calls if c[0] == "append"]
        assert appends, "deterministic turn must leave persisted rows"
        rows = [c.args[1] for c in appends if c.args]
        assert [row.role for row in rows] == [Role.USER, Role.ASSISTANT]
        assert rows[0].content == "list all facts"


class TestDeterministicDeleteRoute:
    @pytest.mark.asyncio
    async def test_delete_is_applied_then_confirmed(self):
        rt = _runtime()
        result = _tool_result(
            "Removed. I now have 0 facts in memory:\n- (nothing stored yet)"
        )
        with patch("tools.memory_tool.memory_op", return_value=result) as mem:
            chunks, _obs = await _collect(rt, "forget that I prefer dark mode")

        mem.assert_awaited_once()
        kwargs = mem.await_args.kwargs
        assert kwargs.get("operation") == "forget"
        assert "I prefer dark mode" in (kwargs.get("content") or "")
        text = "".join(c.text for c in chunks)
        assert "Removed" in text

    @pytest.mark.asyncio
    async def test_delete_failure_removes_nothing(self):
        rt = _runtime()

        async def boom(*a, **k):
            raise RuntimeError("store offline")

        with patch("tools.memory_tool.memory_op", side_effect=boom):
            chunks, _obs = await _collect(rt, "forget my timezone is UTC+3")
        text = "".join(c.text for c in chunks)
        assert "nothing was removed" in text


class TestFallThrough:
    @pytest.mark.asyncio
    async def test_general_knowledge_still_reaches_the_model(self):
        rt = _runtime()
        adapter = MagicMock()

        async def chat(messages, intent="chat", **kwargs):
            yield MagicMock(
                text="The EPL table is on Sky Sports.", done=False, error=None
            )
            yield MagicMock(text="", done=True, error=None)

        adapter.chat = chat
        called = {"n": 0}

        def fake_memory_op(*a, **k):
            called["n"] += 1
            return _tool_result("nope")

        with patch("core.engine.get_adapter", return_value=adapter), patch(
            "tools.memory_tool.memory_op", side_effect=fake_memory_op
        ):
            chunks, _obs = await _collect(rt, "What do you know about Python?")

        assert called["n"] == 0
        text = "".join(c.text for c in chunks)
        assert "EPL table is on Sky Sports" in text
