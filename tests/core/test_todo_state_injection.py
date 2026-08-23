"""Session 359 — todo-state injection: the agent must know its own environment.

The user's complaint (B-2026-08-23-2): the agent "didn't mark task/todo as
complete, when I asked it to mark it complete didn't have no idea what I was
talking about because it looked for todos in chat." Todos were persisted in
the DB and shown in the UI, but NEVER injected into the model context — the
model only saw chat history.

Fix: the session's persisted todos (id/content/status) are now rendered into
(a) the parent-agent loop's turn context ("# Current todos") and (b) the
conversational fast-path prompt, so "mark the task as complete" and "what
todos are left?" are answerable from real state.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.agent.loop import AgentLoop, _render_todo_state
from core.models import Intent, StreamChunk
from core.obs import ObsCollector
from core.trivial_input import _render_conversational_todos


class TestRenderTodoState:
    def test_renders_status_markers(self):
        state = [
            {"id": "plan-0", "content": "create the folder", "completed": True, "status": "done"},
            {"id": "plan-1", "content": "write a.txt", "completed": False, "status": "pending"},
            {"id": "plan-2", "content": "write b.txt", "completed": False, "status": "in_progress"},
        ]
        out = _render_todo_state(state)
        assert "# Current todos" in out
        assert "[x] create the folder" in out
        assert "[ ] write a.txt" in out
        assert "[~] write b.txt" in out
        assert "1/3 completed" in out

    def test_accepts_text_field_and_blocked(self):
        state = [
            {"id": "t1", "text": "install deps", "completed": False, "status": "blocked"},
            {"id": "t2", "text": "run tests", "completed": False, "status": "pending"},
        ]
        out = _render_todo_state(state)
        assert "[!] install deps" in out
        assert "[ ] run tests" in out

    def test_empty_state_returns_empty(self):
        assert _render_todo_state([]) == ""
        assert _render_todo_state(None) == ""

    def test_missing_status_falls_back_to_completed_flag(self):
        state = [{"id": "t1", "content": "done thing", "completed": True}]
        out = _render_todo_state(state)
        assert "[x] done thing" in out


class TestRenderConversationalTodos:
    def test_renders_checklist_for_fast_path(self):
        state = [
            {"id": "plan-0", "content": "create the folder", "completed": True, "status": "done"},
            {"id": "plan-1", "content": "write a.txt", "completed": False, "status": "pending"},
        ]
        out = _render_conversational_todos(state)
        assert "current task checklist" in out
        assert "[x] create the folder" in out
        assert "[ ] write a.txt" in out

    def test_empty_state_returns_empty(self):
        assert _render_conversational_todos([]) == ""
        assert _render_conversational_todos(None) == ""


class TestLoopInjectsTodoState:
    @pytest.mark.asyncio
    async def test_todo_state_reaches_model_messages(self):
        """The loop must pass the '# Current todos' block in the system context."""
        loop = AgentLoop(adapter=MagicMock())
        sent_messages = {}

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            sent_messages["messages"] = messages

            async def _stream():
                yield StreamChunk(text="Understood — I'll mark it complete.", done=False)
                yield StreamChunk(text="", done=True)

            return _stream()

        async def empty_chat(messages, temperature=0.4):
            return
            yield

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = empty_chat

        todo_state = [
            {"id": "plan-0", "content": "create the folder", "completed": True, "status": "done"},
            {"id": "plan-1", "content": "write a.txt", "completed": False, "status": "pending"},
        ]
        chunks = []
        with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
             patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
            async for chunk in loop.run(
                messages=[{"role": "user", "content": "mark the task as complete"}],
                intent=Intent.SHELL,
                initial_tool_result=None,
                available_tools=[],
                adapter=mock_adapter,
                obs=ObsCollector(),
                todo_state=todo_state,
            ):
                chunks.append(chunk)

        full = "".join(c.text for c in chunks)
        assert "Understood" in full

        all_content = "\n".join(
            str(m.get("content", "")) for m in sent_messages.get("messages", [])
        )
        assert "# Current todos" in all_content, "todo state must be injected into model context"
        assert "[ ] write a.txt" in all_content
        assert "[x] create the folder" in all_content

    @pytest.mark.asyncio
    async def test_todo_write_not_synthesized_as_synthetic_todo(self):
        """A todo_write call must not create a leftover empty syn-* row."""
        from adapters.ollama import ToolCallResult
        from tools.todo_write import todo_write

        loop = AgentLoop(adapter=MagicMock())
        obs = ObsCollector()
        seen = {"dispatch": 0}

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            seen["dispatch"] += 1
            if seen["dispatch"] == 1:
                # First call: the model decides to update todos.
                return ToolCallResult(
                    tool_name="todo_write",
                    tool_args={
                        "todos": [
                            {"content": "file exists at a.txt", "completed": True},
                            {"content": "folder created at demo-todo", "completed": True},
                        ]
                    },
                    raw_content="marking complete",
                )

            async def _stream():
                yield StreamChunk(text="All done.", done=False)
                yield StreamChunk(text="", done=True)

            return _stream()

        async def empty_chat(messages, temperature=0.4):
            return
            yield

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = empty_chat

        async def _fake_dispatch(intent, inp, adapter=None, obs=None, allowed_tool_names=None):
            res = await todo_write(inp)
            return res, False, None

        with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
             patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), \
             patch("core.agent.loop.dispatch_with_retry", side_effect=_fake_dispatch):
            async for chunk in loop.run(
                messages=[{"role": "user", "content": "mark the task as complete"}],
                intent=Intent.SHELL,
                initial_tool_result=None,
                available_tools=[],
                adapter=mock_adapter,
                obs=obs,
                todo_state=[
                    {"id": "plan-0", "content": "file exists at a.txt", "completed": True, "status": "done"},
                ],
            ):
                pass

        created = [e.data for e in obs.history() if e.type == "todo_created"]
        syn_ids = [t.get("id") for t in created if str(t.get("id", "")).startswith("syn-")]
        assert syn_ids == [], f"todo_write must not create synthetic todos: {syn_ids}"
        # The todo_write metadata todos still flow through.
        assert any("file exists at a.txt" in str(t.get("text", "")) for t in created)

    @pytest.mark.asyncio
    async def test_no_todo_state_injects_nothing(self):
        """Without persisted todos, no '# Current todos' block appears."""
        loop = AgentLoop(adapter=MagicMock())
        sent_messages = {}

        async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
            sent_messages["messages"] = messages

            async def _stream():
                yield StreamChunk(text="Nothing to mark yet.", done=False)
                yield StreamChunk(text="", done=True)

            return _stream()

        async def empty_chat(messages, temperature=0.4):
            return
            yield

        mock_adapter = MagicMock()
        mock_adapter.chat_with_tools = chat_with_tools
        mock_adapter.chat = empty_chat

        chunks = []
        with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
             patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x):
            async for chunk in loop.run(
                messages=[{"role": "user", "content": "hello"}],
                intent=Intent.CHAT,
                initial_tool_result=None,
                available_tools=[],
                adapter=mock_adapter,
                obs=ObsCollector(),
                todo_state=None,
            ):
                chunks.append(chunk)

        all_content = "\n".join(
            str(m.get("content", "")) for m in sent_messages.get("messages", [])
        )
        assert "# Current todos" not in all_content
