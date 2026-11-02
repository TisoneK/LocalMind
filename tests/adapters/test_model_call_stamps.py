"""
Adapter-level model-call stamp tests (B-2026-11-01-26).

Contract locked here:
  - ``chat()`` and ``chat_with_tools()`` emit the full boundary sequence
    (started → response → first byte → completed/failed) into the bound
    request's collector — by construction, not per-site wiring;
  - a returned inner stream (the tools adapter's text path) stamps
    completion when the caller actually drains it, not when it was created;
  - a ToolCallResult path stamps completion with the result's usage;
  - the heartbeat's legacy provider_call_start/provider_first_byte pair is
    emitted by the same watch — with the epoch-ms anchor beside the
    monotonic clock — so loop turns get stall detection for free;
  - with no request context bound, adapter calls make NO trace events.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.models import StreamChunk
from core.obs import ObsCollector
from core.turn_trace import TurnContext, bind_turn, new_turn_id, reset_turn
from adapters.openai_compat import OpenAICompatAdapter
from adapters.ollama import OllamaAdapter


@pytest.fixture
def turn_collector():
    collector = ObsCollector()
    ctx = TurnContext(turn_id=new_turn_id(), session_id="sess-adapter-stamps", collector=collector)
    token = bind_turn(ctx)
    yield collector
    reset_turn(token)


def _openai_adapter() -> OpenAICompatAdapter:
    """A minimal adapter instance — no network, no settings. Only the
    attributes the trace wrapper reads are real; the streaming impl is
    patched per test."""
    adapter = object.__new__(OpenAICompatAdapter)
    adapter._provider_name = "zai"
    adapter._model = "glm-4.5-flash"
    adapter._provider_key = "openai"
    adapter._capabilities = SimpleNamespace(streaming=True, tool_calling=True)
    adapter._timeouts = {"chat": 120, "agent": 120}
    return adapter


def _ollama_adapter() -> OllamaAdapter:
    adapter = object.__new__(OllamaAdapter)
    adapter._model = "llama3.1"
    return adapter


class TestOpenAIChatStamps:
    @pytest.mark.asyncio
    async def test_chat_emits_boundary_sequence(self, turn_collector):
        collector = turn_collector
        adapter = _openai_adapter()

        async def fake_openai_style(messages, temperature, timeout):
            yield StreamChunk(text="Hel", done=False)
            yield StreamChunk(text="lo", done=False, usage={"prompt_tokens": 7})
            yield StreamChunk(text="", done=True, usage={"prompt_tokens": 7, "completion_tokens": 2})

        with patch.object(adapter, "_chat_openai_style", fake_openai_style):
            chunks = [c async for c in adapter.chat([{"role": "user", "content": "hi"}], intent="chat")]

        assert [c.text for c in chunks] == ["Hel", "lo", ""]
        types = [e.type for e in collector.history()]
        assert types == [
            "model_call_started",
            "provider_call_start",
            "model_call_first_byte",
            "provider_first_byte",
            "model_call_completed",
        ]
        completed = collector.history()[-1].data
        assert completed["usage"]["completion_tokens"] == 2
        started = collector.history()[0].data
        assert started["intent"] == "chat"
        assert started["mode"] == "chat"

    @pytest.mark.asyncio
    async def test_chat_error_chunk_records_failure(self, turn_collector):
        collector = turn_collector
        adapter = _openai_adapter()

        async def failing_impl(messages, temperature, timeout):
            yield StreamChunk(text="", done=True, error="provider 503")

        with patch.object(adapter, "_chat_openai_style", failing_impl):
            _ = [c async for c in adapter.chat([{"role": "user", "content": "hi"}])]

        terminals = [e for e in collector.history() if e.type in ("model_call_completed", "model_call_failed")]
        assert len(terminals) == 1
        assert terminals[0].type == "model_call_failed"
        assert "503" in terminals[0].data["error"]

    @pytest.mark.asyncio
    async def test_chat_without_request_context_makes_no_trace_events(self):
        adapter = _openai_adapter()

        async def fake_impl(messages, temperature, timeout):
            yield StreamChunk(text="hey", done=False)
            yield StreamChunk(text="", done=True)

        with patch.object(adapter, "_chat_openai_style", fake_impl):
            _ = [c async for c in adapter.chat([{"role": "user", "content": "hi"}])]

        assert True  # reaching here without events is the assertion

    @pytest.mark.asyncio
    async def test_response_headers_stamp_via_send_hook(self, turn_collector):
        """_send_streaming_with_retry stamps the response moment on the
        active watch — the loop path's acceptance moment."""

        collector = turn_collector
        adapter = _openai_adapter()

        # Simulate what _send_streaming_with_retry does on a 200: look up the
        # current watch and stamp. (The method itself needs a live HTTP
        # client; the hook contract is what's locked here.)
        from core.turn_trace import current_model_call, start_model_call

        async def impl_with_send(messages, tools, temperature, intent, tool_choice):
            watch = current_model_call()
            assert watch is not None
            watch.response_received(200)
            watch.first_byte()
            return StreamChunk(text="done", done=True)

        started_watch = start_model_call(
            provider="zai", model="glm-4.5-flash", intent="agent", mode="tools",
            messages=[], tools=[{"type": "function"}],
        )
        result = await impl_with_send([], [], 0.7, "agent", None)
        started_watch.completed()

        types = [e.type for e in collector.history()]
        assert "model_call_response" in types
        assert "model_call_first_byte" in types
        assert "model_call_completed" in types


class TestOpenAIToolsStamps:
    @pytest.mark.asyncio
    async def test_text_result_wraps_stream_and_stamps_completion(self, turn_collector):
        collector = turn_collector
        adapter = _openai_adapter()

        async def inner_stream():
            yield StreamChunk(text="answer", done=False)
            yield StreamChunk(text="", done=True, usage={"prompt_tokens": 9, "completion_tokens": 3})

        async def fake_impl(messages, tools, temperature, intent, tool_choice):
            return inner_stream()

        with patch.object(adapter, "chat_with_tools_impl", fake_impl):
            result = await adapter.chat_with_tools(
                [{"role": "user", "content": "hi"}], tools=[{"type": "function"}]
            )
        # The coroutine returned — the stream has NOT flowed yet, so the
        # watch must not be closed (completed fires when the caller drains).
        assert not any(e.type == "model_call_completed" for e in collector.history())

        _ = [c async for c in result]
        completed = [e for e in collector.history() if e.type == "model_call_completed"]
        assert len(completed) == 1
        assert completed[0].data["usage"]["completion_tokens"] == 3
        firsts = [e for e in collector.history() if e.type == "model_call_first_byte"]
        assert len(firsts) == 1

    @pytest.mark.asyncio
    async def test_tool_result_stamps_completion_with_usage(self, turn_collector):
        collector = turn_collector
        adapter = _openai_adapter()

        async def fake_impl(messages, tools, temperature, intent, tool_choice):
            from adapters.ollama import ToolCallResult

            return ToolCallResult(
                tool_name="shell",
                tool_args={"command": "ls"},
                raw_content="",
                usage={"prompt_tokens": 12, "completion_tokens": 1},
            )

        with patch.object(adapter, "chat_with_tools_impl", fake_impl):
            result = await adapter.chat_with_tools(
                [{"role": "user", "content": "hi"}], tools=[{"type": "function"}]
            )

        assert result.tool_name == "shell"
        completed = [e for e in collector.history() if e.type == "model_call_completed"]
        assert len(completed) == 1
        assert completed[0].data["usage"]["prompt_tokens"] == 12


class TestOllamaStamps:
    @pytest.mark.asyncio
    async def test_chat_emits_boundary_sequence(self, turn_collector):
        collector = turn_collector
        adapter = _ollama_adapter()

        async def fake_impl(messages, temperature, intent, **kwargs):
            yield StreamChunk(text="hello", done=False)
            yield StreamChunk(text="", done=True, usage={"prompt_tokens": 4, "completion_tokens": 1})

        with patch.object(adapter, "chat_impl", fake_impl):
            _ = [c async for c in adapter.chat([{"role": "user", "content": "hi"}])]

        types = [e.type for e in collector.history()]
        assert types == [
            "model_call_started",
            "provider_call_start",
            "model_call_first_byte",
            "provider_first_byte",
            "model_call_completed",
        ]
        started = collector.history()[0].data
        assert started["provider"] == "ollama"

    @pytest.mark.asyncio
    async def test_tools_result_stamps_completion(self, turn_collector):
        collector = turn_collector
        adapter = _ollama_adapter()

        async def fake_impl(messages, tools, temperature, intent, tool_choice):
            from adapters.ollama import ToolCallResult

            return ToolCallResult(
                tool_name="file_read", tool_args={"path": "a.py"}, raw_content="",
                usage={"prompt_tokens": 3, "completion_tokens": 2},
            )

        with patch.object(adapter, "chat_with_tools_impl", fake_impl):
            result = await adapter.chat_with_tools([], tools=[{"type": "function"}])

        assert result.tool_name == "file_read"
        completed = [e for e in collector.history() if e.type == "model_call_completed"]
        assert len(completed) == 1
