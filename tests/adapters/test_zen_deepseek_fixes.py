"""
Session 31 regression tests for the OpenAI-compat adapter fixes.

Two bugs found via real-model testing against Zen/DeepSeek-v4-flash-free:

1. Trailing tool role 400 error: DeepSeek-v4-flash-free (and possibly
   other providers) reject requests where the last message is a `tool`
   role — they return HTTP 400 "Upstream request failed". This breaks
   the agent loop: after every tool execution, the loop appends an
   `assistant`+`tool_calls` message and a `tool` role message, then
   calls chat_with_tools again. The last message is `tool` role → 400.

   Fix: chat_with_tools appends a synthetic `user` message when the
   last message is `tool` role. Verified against Zen/DeepSeek: 200 OK.

2. Phase 1 detection gives up too early on reasoning-only streams:
   DeepSeek-v4-flash-free produces 80+ reasoning chunks BEFORE the
   tool_call delta arrives. Phase 1 was breaking at chunks_read >= 15
   (during the reasoning phase), falling through to Phase 2b (text
   streaming), which silently dropped the tool_call deltas (it only
   handles content/reasoning, not tool_calls). The model's tool call
   was lost — user saw empty output.

   Fix: only break out of Phase 1 if we've seen actual CONTENT (not
   just reasoning). Reasoning-only chunks mean the model is still
   thinking and hasn't decided between text vs tool call yet.

These tests verify both fixes at the unit level (no real API calls).
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from adapters.openai_compat import (
    PROVIDER_CONFIGS,
    OpenAICompatAdapter,
    _normalize_usage,
)


def test_normalize_usage_prefers_provider_counts():
    """Provider counts must survive normalization for UI telemetry."""
    assert _normalize_usage(
        {"prompt_tokens": 37, "completion_tokens": 11, "total_tokens": 48}
    ) == {"prompt_tokens": 37, "completion_tokens": 11, "total_tokens": 48}


def test_normalize_usage_accepts_input_output_names():
    """Providers using input/output names should map to the shared schema."""
    assert _normalize_usage({"input_tokens": 19, "output_tokens": 7}) == {
        "prompt_tokens": 19,
        "completion_tokens": 7,
        "total_tokens": 26,
    }


def test_zen_default_is_free_deepseek_model():
    """Zen's default must remain on the currently free DeepSeek model."""
    assert PROVIDER_CONFIGS["zen"].default_model == "deepseek-v4-flash-free"


def test_stream_usage_option_compatibility_retry(monkeypatch):
    """Unsupported stream usage options must not make a provider unusable."""
    monkeypatch.setenv("ZEN_API_KEY", "sk-fake-test-key")
    adapter = OpenAICompatAdapter(provider="zen", model_override="deepseek-v4-flash-free")
    requests = []

    class FakeResponse:
        def __init__(self, status_code: int, body: str = ""):
            self.status_code = status_code
            self._body = body.encode()
            self.headers = {}

        async def aread(self):
            return self._body

        async def aclose(self):
            return None

    class FakeClient:
        def build_request(self, method, url, *, json, headers, timeout):
            requests.append(json)
            return {"json": json}

        async def send(self, request, stream=True):
            if len(requests) == 1:
                return FakeResponse(400, '{"error":"unknown field stream_options"}')
            return FakeResponse(200)

    adapter._client = FakeClient()

    async def run():
        return await adapter._send_streaming_with_retry(
            "https://example.test/chat/completions",
            {"model": "deepseek-v4-flash-free", "stream_options": {"include_usage": True}},
        )

    response = asyncio.run(run())
    assert response.status_code == 200
    assert "stream_options" in requests[0]
    assert "stream_options" not in requests[1]


# ── 1. Trailing tool role → synthetic user message appended ──────────────


class TestTrailingToolRoleFix:
    """When the last message is a `tool` role, the adapter must append a
    synthetic `user` message before sending to the API. This is required
    for providers like DeepSeek-v4-flash-free that reject tool-terminated
    message lists with HTTP 400."""

    def test_synthetic_user_appended_when_last_message_is_tool_role(self, monkeypatch):
        """The adapter should append a synthetic user message when the last
        message in the input is a `tool` role."""
        # Set up a fake API key so the adapter can be constructed
        monkeypatch.setenv("ZEN_API_KEY", "sk-fake-test-key")

        adapter = OpenAICompatAdapter(provider="zen", model_override="deepseek-v4-flash-free")

        # Messages ending with a tool role (what the agent loop builds after
        # every tool execution)
        messages = [
            {"role": "user", "content": "Create a directory"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "type": "function", "function": {"name": "shell", "arguments": '{"command": "mkdir test"}'}}]},
            {"role": "tool", "tool_call_id": "1", "content": "Directory created"},
        ]
        tools = [
            {"type": "function", "function": {"name": "shell", "description": "Run shell command", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
        ]

        # Capture the payload that would be sent to the API
        captured_payload = {}

        async def fake_send_streaming(url, payload, headers=None, timeout=None):
            captured_payload.update(payload)
            # Return a mock response that yields [DONE] immediately
            mock_resp = MagicMock()
            mock_resp.status_code = 200

            async def aiter_lines():
                yield "data: [DONE]"

            mock_resp.aiter_lines = aiter_lines

            async def aclose():
                pass
            mock_resp.aclose = aclose
            return mock_resp

        with patch.object(adapter, "_send_streaming_with_retry", new=fake_send_streaming):
            import asyncio
            asyncio.run(adapter.chat_with_tools(messages=messages, tools=tools, temperature=0.3, intent="shell"))

        # Verify the synthetic user message was appended
        sent_messages = captured_payload.get("messages", [])
        assert len(sent_messages) == len(messages) + 1, (
            f"Expected {len(messages) + 1} messages (original + synthetic user), "
            f"got {len(sent_messages)}"
        )
        last_msg = sent_messages[-1]
        assert last_msg["role"] == "user", (
            f"Last message should be 'user' (synthetic), got role={last_msg['role']!r}"
        )
        assert "continue" in last_msg["content"].lower() or "tool result" in last_msg["content"].lower(), (
            f"Synthetic user message should prompt the model to continue, got: {last_msg['content']!r}"
        )

    def test_no_synthetic_user_when_last_message_is_user(self, monkeypatch):
        """When the last message is already a `user` role, the adapter should
        NOT append a synthetic user message."""
        monkeypatch.setenv("ZEN_API_KEY", "sk-fake-test-key")
        adapter = OpenAICompatAdapter(provider="zen", model_override="deepseek-v4-flash-free")

        messages = [
            {"role": "user", "content": "Hello"},
        ]
        tools = []

        captured_payload = {}

        async def fake_send_streaming(url, payload, headers=None, timeout=None):
            captured_payload.update(payload)
            mock_resp = MagicMock()
            mock_resp.status_code = 200

            async def aiter_lines():
                yield "data: [DONE]"

            mock_resp.aiter_lines = aiter_lines

            async def aclose():
                pass
            mock_resp.aclose = aclose
            return mock_resp

        with patch.object(adapter, "_send_streaming_with_retry", new=fake_send_streaming):
            import asyncio
            asyncio.run(adapter.chat_with_tools(messages=messages, tools=tools, temperature=0.3, intent="chat"))

        sent_messages = captured_payload.get("messages", [])
        assert len(sent_messages) == len(messages), (
            f"Should NOT append synthetic user when last message is already user. "
            f"Expected {len(messages)} messages, got {len(sent_messages)}"
        )

    def test_synthetic_user_appended_after_each_tool_role(self, monkeypatch):
        """When there are multiple tool calls, the adapter should still only
        append ONE synthetic user message at the end (not after each tool role)."""
        monkeypatch.setenv("ZEN_API_KEY", "sk-fake-test-key")
        adapter = OpenAICompatAdapter(provider="zen", model_override="deepseek-v4-flash-free")

        messages = [
            {"role": "user", "content": "Do 3 things"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "type": "function", "function": {"name": "shell", "arguments": '{}'}}]},
            {"role": "tool", "tool_call_id": "1", "content": "Result 1"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "2", "type": "function", "function": {"name": "shell", "arguments": '{}'}}]},
            {"role": "tool", "tool_call_id": "2", "content": "Result 2"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "3", "type": "function", "function": {"name": "shell", "arguments": '{}'}}]},
            {"role": "tool", "tool_call_id": "3", "content": "Result 3"},
        ]
        tools = [
            {"type": "function", "function": {"name": "shell", "description": "Run", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}},
        ]

        captured_payload = {}

        async def fake_send_streaming(url, payload, headers=None, timeout=None):
            captured_payload.update(payload)
            mock_resp = MagicMock()
            mock_resp.status_code = 200

            async def aiter_lines():
                yield "data: [DONE]"

            mock_resp.aiter_lines = aiter_lines

            async def aclose():
                pass
            mock_resp.aclose = aclose
            return mock_resp

        with patch.object(adapter, "_send_streaming_with_retry", new=fake_send_streaming):
            import asyncio
            asyncio.run(adapter.chat_with_tools(messages=messages, tools=tools, temperature=0.3, intent="shell"))

        sent_messages = captured_payload.get("messages", [])
        # Original 7 messages + 1 synthetic user = 8
        assert len(sent_messages) == 8, (
            f"Expected 8 messages (7 original + 1 synthetic user), got {len(sent_messages)}"
        )
        # Only the LAST message should be the synthetic user
        assert sent_messages[-1]["role"] == "user"
        # The second-to-last should still be the original tool role
        assert sent_messages[-2]["role"] == "tool"


# ── 2. Phase 1 detection: keep reading during reasoning-only streams ─────


class TestPhase1ReasoningOnlyFix:
    """DeepSeek-v4-flash-free produces 80+ reasoning chunks BEFORE the
    tool_call delta arrives. Phase 1 was breaking at chunks_read >= 15,
    falling through to Phase 2b which silently dropped the tool_call.

    Fix: only break out of Phase 1 if we've seen actual CONTENT (not just
    reasoning). Keep reading during reasoning-only streams."""

    def test_phase1_does_not_break_on_reasoning_only(self, monkeypatch):
        """Phase 1 should keep reading when it sees only reasoning chunks
        (no content, no tool_calls). It should NOT break at chunks_read >= 15."""
        monkeypatch.setenv("ZEN_API_KEY", "sk-fake-test-key")
        adapter = OpenAICompatAdapter(provider="zen", model_override="deepseek-v4-flash-free")

        # Simulate a stream that produces 20 reasoning chunks, then a tool_call
        def make_sse_lines():
            lines = []
            # 20 reasoning chunks
            for i in range(20):
                lines.append(f'data: {{"choices":[{{"delta":{{"reasoning_content":"thinking {i} "}},"finish_reason":null}}]}}')
            # Tool call chunk
            lines.append('data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"shell","arguments":"{\\"command\\": \\"ls\\"}"}}]},"finish_reason":null}]}')
            # Finish reason
            lines.append('data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}')
            lines.append("data: [DONE]")
            return lines

        messages = [{"role": "user", "content": "List files"}]
        tools = [
            {"type": "function", "function": {"name": "shell", "description": "Run", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}},
        ]

        async def fake_send_streaming(url, payload, headers=None, timeout=None):
            mock_resp = MagicMock()
            mock_resp.status_code = 200

            async def aiter_lines():
                for line in make_sse_lines():
                    yield line

            mock_resp.aiter_lines = aiter_lines

            async def aclose():
                pass
            mock_resp.aclose = aclose
            return mock_resp

        with patch.object(adapter, "_send_streaming_with_retry", new=fake_send_streaming):
            import asyncio

            from adapters.ollama import ToolCallResult
            result = asyncio.run(adapter.chat_with_tools(messages=messages, tools=tools, temperature=0.3, intent="shell"))

        # The result should be a ToolCallResult — the tool_call was detected
        # AFTER the 20 reasoning chunks, not lost.
        assert isinstance(result, ToolCallResult), (
            f"Expected ToolCallResult (tool call should be detected after reasoning), "
            f"got {type(result).__name__}"
        )
        assert result.tool_name == "shell"
        assert "ls" in result.tool_args.get("command", "")

    def test_phase1_breaks_on_content_after_15_chunks(self, monkeypatch):
        """Phase 1 should still break at chunks_read >= 15 if it sees actual
        CONTENT (not just reasoning) — that's a text response."""
        monkeypatch.setenv("ZEN_API_KEY", "sk-fake-test-key")
        adapter = OpenAICompatAdapter(provider="zen", model_override="deepseek-v4-flash-free")

        # Simulate a stream that produces 5 reasoning chunks, then 15+ content chunks
        def make_sse_lines():
            lines = []
            for i in range(5):
                lines.append(f'data: {{"choices":[{{"delta":{{"reasoning_content":"thinking {i} "}}}}]}}')
            for i in range(20):
                lines.append(f'data: {{"choices":[{{"delta":{{"content":"text chunk {i} "}}}}]}}')
            lines.append('data: {"choices":[{"delta":{},"finish_reason":"stop"}]}')
            lines.append("data: [DONE]")
            return lines

        messages = [{"role": "user", "content": "Tell me a story"}]
        tools = [
            {"type": "function", "function": {"name": "shell", "description": "Run", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}},
        ]

        async def fake_send_streaming(url, payload, headers=None, timeout=None):
            mock_resp = MagicMock()
            mock_resp.status_code = 200

            async def aiter_lines():
                for line in make_sse_lines():
                    yield line

            mock_resp.aiter_lines = aiter_lines

            async def aclose():
                pass
            mock_resp.aclose = aclose
            return mock_resp

        with patch.object(adapter, "_send_streaming_with_retry", new=fake_send_streaming):
            import asyncio
            result = asyncio.run(adapter.chat_with_tools(messages=messages, tools=tools, temperature=0.3, intent="chat"))

        # Should be a streaming response (not a ToolCallResult) — Phase 1
        # correctly identified this as text after seeing content
        assert not (result is None), "Result should not be None"
        # result is an async iterator (generator) for text streaming
        # Consume it to verify we get text
        async def consume():
            chunks = []
            async for chunk in result:
                chunks.append(chunk)
            return chunks

        chunks = asyncio.run(consume())
        text = "".join(c.text for c in chunks if c.text)
        assert "text chunk" in text, (
            f"Should have streamed the text content. Got: {text!r}"
        )


# ── API-key live resolution (Session 112) ─────────────────────────────────
# ProviderConfig.api_key is a BAKED DEFAULT only — the env value is resolved
# at CONSTRUCTION time via key_env. The old import-time freeze made the
# adapter keep using a stale key after the env var was deleted (the root
# cause of the flaky test_missing_api_key_falls_back_to_none: importing
# openai_compat while ZEN_API_KEY was set froze the real key into the
# config, so monkeypatch.delenv later had no effect).


def test_adapter_resolves_api_key_live_not_frozen_at_import(monkeypatch):
    """The API key must be read at CONSTRUCTION time, not frozen at import.

    Regression: the old code froze the env value into PROVIDER_CONFIGS at
    import time, so if openai_compat was imported while ZEN_API_KEY was set
    (e.g. tests/api collection), deleting the env var later had no effect —
    construction still succeeded with the stale key.
    """
    from core.config import settings

    # Defensive: a runtime-stored key (from another test's save_api_key)
    # would win before the env path — clear it so the env is authoritative.
    settings._runtime_api_keys.pop("zen", None)

    monkeypatch.setenv("ZEN_API_KEY", "sk-live")
    adapter = OpenAICompatAdapter(provider="zen")
    assert adapter._headers["Authorization"] == "Bearer sk-live"

    # Delete the key AFTER the module is already imported — construction
    # must now FAIL (live resolution), not reuse a frozen import-time key.
    monkeypatch.delenv("ZEN_API_KEY", raising=False)
    with pytest.raises(ValueError, match="API key not set"):
        OpenAICompatAdapter(provider="zen")


def test_litellm_baked_dummy_default_survives_live_resolution(monkeypatch):
    """LiteLLM's baked 'dummy' placeholder default must still construct.

    Guard: the baked cfg.api_key fallback is load-bearing for LiteLLM (its
    local proxy needs no key) — do not remove it while switching to live
    env resolution.
    """
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    adapter = OpenAICompatAdapter(provider="lite-llm")
    assert adapter._headers["Authorization"] == "Bearer dummy"


# ── 3. null tool_calls delta (Session 116, real-model smoke test) ────────
# A live Zen/DeepSeek-v4-flash-free run crashed with "Unexpected error
# calling zen: 'NoneType' object is not iterable" on the agent loop's
# first LLM call. Root cause: providers commonly emit a first assistant
# delta with `tool_calls: null`; the Phase 1 / Phase 2a loops iterated
# delta["tool_calls"] unconditionally, and the inner except only caught
# JSONDecodeError/IndexError/KeyError, so the TypeError escaped to the
# outer handler and killed the whole turn (no tool ever ran).


class TestNullToolCallsDelta:
    def test_null_tool_calls_delta_is_skipped_and_tool_still_detected(self, monkeypatch):
        """A delta with `tool_calls: null` (common first assistant chunk)
        must be skipped - not iterated - and a later real tool_call delta
        must still be detected."""
        monkeypatch.setenv("ZEN_API_KEY", "sk-fake-test-key")
        adapter = OpenAICompatAdapter(provider="zen", model_override="deepseek-v4-flash-free")
        import json as _json

        def make_sse_lines():
            # The null tool_calls delta the live provider actually sent.
            yield "data: " + _json.dumps({"choices": [{"delta": {"role": "assistant", "tool_calls": None}, "finish_reason": None}]})
            # The real tool call that followed.
            yield "data: " + _json.dumps({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "shell", "arguments": '{"command": "ls"}'}}]}, "finish_reason": None}]})
            yield "data: " + _json.dumps({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]})
            yield "data: [DONE]"

        messages = [{"role": "user", "content": "List files"}]
        tools = [
            {"type": "function", "function": {"name": "shell", "description": "Run", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}},
        ]

        async def fake_send_streaming(url, payload, headers=None, timeout=None):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            # Session 116: enforce httpx ONE-SHOT stream semantics so the
            # test catches the double-read bug (Phase 2 re-iterating an
            # already-consumed response). Permissive mocks let the old
            # broken code pass.
            mock_resp.is_stream_consumed = False
            iterated = {"n": 0}

            async def aiter_lines():
                iterated["n"] += 1
                if iterated["n"] > 1:
                    raise RuntimeError(
                        "Attempted to read or stream some content, but the content "
                        "has already been streamed."
                    )
                for line in make_sse_lines():
                    yield line
                mock_resp.is_stream_consumed = True

            mock_resp.aiter_lines = aiter_lines

            async def aclose():
                pass
            mock_resp.aclose = aclose
            return mock_resp

        with patch.object(adapter, "_send_streaming_with_retry", new=fake_send_streaming):
            from adapters.ollama import ToolCallResult
            result = asyncio.run(adapter.chat_with_tools(messages=messages, tools=tools, temperature=0.3, intent="shell"))

        assert isinstance(result, ToolCallResult), (
            f"null tool_calls delta must not kill the call; expected ToolCallResult, got {type(result).__name__}"
        )
        assert result.tool_name == "shell"
        assert "ls" in result.tool_args.get("command", "")


class TestTextStreamWithoutDone:
    """A text response whose stream ends WITHOUT a [DONE] line (provider
    closes the connection) previously crashed: Phase 1 exhausted the
    one-shot httpx stream, then Phase 2b re-iterated it and raised
    RuntimeError('content has already been streamed') - the exact error
    seen in the Session 116 real-model smoke test. The Phase 2b guard
    (not phase1_done and not is_stream_consumed) must skip the
    re-iteration and yield the already-buffered text."""

    def test_text_stream_ending_without_done_still_streams(self, monkeypatch):
        monkeypatch.setenv("ZEN_API_KEY", "sk-fake-test-key")
        adapter = OpenAICompatAdapter(provider="zen", model_override="deepseek-v4-flash-free")
        import json as _json

        def make_sse_lines():
            # 8 text chunks (below the 15-chunk break) then the stream ends
            # abruptly - no [DONE] line.
            for i in range(8):
                yield "data: " + _json.dumps(
                    {"choices": [{"delta": {"content": f"text chunk {i} "}, "finish_reason": None}]}
                )

        messages = [{"role": "user", "content": "Tell me a story"}]
        tools = [
            {"type": "function", "function": {"name": "shell", "description": "Run", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}},
        ]

        async def fake_send_streaming(url, payload, headers=None, timeout=None):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.is_stream_consumed = False
            iterated = {"n": 0}

            async def aiter_lines():
                iterated["n"] += 1
                if iterated["n"] > 1:
                    raise RuntimeError(
                        "Attempted to read or stream some content, but the content "
                        "has already been streamed."
                    )
                for line in make_sse_lines():
                    yield line
                mock_resp.is_stream_consumed = True

            mock_resp.aiter_lines = aiter_lines

            async def aclose():
                pass
            mock_resp.aclose = aclose
            return mock_resp

        with patch.object(adapter, "_send_streaming_with_retry", new=fake_send_streaming):
            result = asyncio.run(adapter.chat_with_tools(messages=messages, tools=tools, temperature=0.3, intent="chat"))

        assert not hasattr(result, "tool_name"), "text path must return an async generator"

        async def consume():
            chunks = []
            async for chunk in result:
                chunks.append(chunk)
            return chunks

        chunks = asyncio.run(consume())
        text = "".join(c.text for c in chunks)
        assert "text chunk 0" in text and "text chunk 7" in text, (
            f"all buffered text must be yielded despite the missing [DONE], got {text!r}"
        )
        assert any(c.done for c in chunks), "a done chunk must be yielded"


# ── 3. tool_choice passthrough + graceful degrade (Session 238) ──────────


class TestToolChoicePassthrough:
    """Session 238 (Thinker/Agent rebuild Step 0): the OpenAI-compat adapter
    must HONOR the tool_choice parameter (previously accepted but silently
    ignored), and degrade gracefully when a provider rejects the field."""

    def test_tool_choice_required_lands_in_payload(self, monkeypatch):
        monkeypatch.setenv("ZEN_API_KEY", "sk-fake-test-key")
        adapter = OpenAICompatAdapter(provider="zen", model_override="deepseek-v4-flash-free")
        captured = {}

        async def fake_send_streaming(url, payload, headers=None, timeout=None):
            captured.update(payload)
            mock_resp = MagicMock()
            mock_resp.status_code = 200

            async def aiter_lines():
                yield "data: [DONE]"

            mock_resp.aiter_lines = aiter_lines

            async def aclose():
                pass
            mock_resp.aclose = aclose
            return mock_resp

        with patch.object(adapter, "_send_streaming_with_retry", new=fake_send_streaming):
            asyncio.run(
                adapter.chat_with_tools(
                    messages=[{"role": "user", "content": "list files"}],
                    tools=[{"type": "function", "function": {"name": "shell", "description": "Run", "parameters": {}}}],
                    temperature=0.3,
                    intent="shell",
                    tool_choice="required",
                )
            )

        assert captured.get("tool_choice") == "required", (
            f"tool_choice='required' must reach the provider payload, got {captured.get('tool_choice')!r}"
        )

    def test_no_tool_choice_key_when_none(self, monkeypatch):
        """The default (tool_choice=None) must not add the key at all — the
        pre-Session-238 payload shape is preserved for every other call."""
        monkeypatch.setenv("ZEN_API_KEY", "sk-fake-test-key")
        adapter = OpenAICompatAdapter(provider="zen", model_override="deepseek-v4-flash-free")
        captured = {}

        async def fake_send_streaming(url, payload, headers=None, timeout=None):
            captured.update(payload)
            mock_resp = MagicMock()
            mock_resp.status_code = 200

            async def aiter_lines():
                yield "data: [DONE]"

            mock_resp.aiter_lines = aiter_lines

            async def aclose():
                pass
            mock_resp.aclose = aclose
            return mock_resp

        with patch.object(adapter, "_send_streaming_with_retry", new=fake_send_streaming):
            asyncio.run(
                adapter.chat_with_tools(
                    messages=[{"role": "user", "content": "hi"}],
                    tools=[],
                    temperature=0.3,
                    intent="chat",
                )
            )

        assert "tool_choice" not in captured, "tool_choice=None must not add the key"

    def test_provider_rejecting_tool_choice_retries_without_it(self, monkeypatch):
        """A 400 that names tool_choice degrades to the unforced request
        instead of failing the turn (mirrors the stream_options degrade)."""
        monkeypatch.setenv("ZEN_API_KEY", "sk-fake-test-key")
        adapter = OpenAICompatAdapter(provider="zen", model_override="deepseek-v4-flash-free")
        requests = []

        class FakeResponse:
            def __init__(self, status_code: int, body: str = ""):
                self.status_code = status_code
                self._body = body.encode()
                self.headers = {}

            async def aread(self):
                return self._body

            async def aclose(self):
                return None

        class FakeClient:
            def build_request(self, method, url, *, json, headers, timeout):
                requests.append(json)
                return {"json": json}

            async def send(self, request, stream=True):
                if len(requests) == 1:
                    return FakeResponse(400, '{"error":"unsupported field: tool_choice"}')
                return FakeResponse(200)

        adapter._client = FakeClient()

        async def run():
            return await adapter._send_streaming_with_retry(
                "https://example.test/chat/completions",
                {"model": "deepseek-v4-flash-free", "tools": [], "tool_choice": "required"},
            )

        response = asyncio.run(run())
        assert response.status_code == 200
        assert "tool_choice" in requests[0]
        assert "tool_choice" not in requests[1]
