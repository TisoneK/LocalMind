"""A whitespace-only content delta must not turn a reasoning+tool-call stream into a "text response".

Live capture (z.ai glm-4.5-flash, thinking on): every reasoning-mode reply carried a lone "\\n"
content delta followed by the tool call, and finished with finish_reason=tool_calls. Phase 1 treated
the "\\n" as real content, decided after 15 chunks that the reply was text, and Phase 2b (which does
not read tool-call deltas) dropped the tool call. The loop then saw "empty response after reasoning",
burned a ~25s recovery call, and only the thinking-off retry acted."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from adapters.ollama import ToolCallResult
from adapters.openai_compat import OpenAICompatAdapter

TOOLS = [{"type": "function", "function": {"name": "shell", "description": "Run",
          "parameters": {"type": "object", "properties": {"command": {"type": "string"}}}}}]
TOOL_LINE = ('data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function",'
             '"function":{"name":"shell","arguments":"{\\"command\\": \\"ls\\"}"}}]},"finish_reason":null}]}')


def _reasoning(n, start=0):
    return [f'data: {{"choices":[{{"delta":{{"reasoning_content":"think {start + i} "}},"finish_reason":null}}]}}'
            for i in range(n)]


def _content(text):
    import json
    return "data: " + json.dumps({"choices": [{"delta": {"content": text}, "finish_reason": None}]})


def _run(lines):
    adapter = OpenAICompatAdapter(provider="zen", model_override="deepseek-v4-flash-free")

    async def fake_send(url, payload, headers=None, timeout=None):
        resp = MagicMock()
        resp.status_code = 200

        async def aiter_lines():
            for ln in lines:
                yield ln
        resp.aiter_lines = aiter_lines

        async def aclose():
            pass
        resp.aclose = aclose
        return resp

    with patch.object(adapter, "_send_streaming_with_retry", new=fake_send):
        return asyncio.run(adapter.chat_with_tools(messages=[{"role": "user", "content": "ls"}], tools=TOOLS,
                                                   temperature=0.3, intent="shell"))


def _tail():
    return [TOOL_LINE, 'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}', "data: [DONE]"]


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("ZEN_API_KEY", "sk-fake-test-key")


@pytest.mark.parametrize("ws", ["\n", " ", "\n\n", "\t", " \n "])
def test_whitespace_content_then_tool_call_is_not_lost(ws):
    lines = _reasoning(3) + [_content(ws)] + _reasoning(30, 3) + _tail()
    result = _run(lines)
    assert isinstance(result, ToolCallResult), f"tool call dropped, got {type(result).__name__}"
    assert result.tool_name == "shell"


def test_whitespace_delta_late_in_reasoning_is_not_lost_either():
    lines = _reasoning(40) + [_content("\n")] + _reasoning(10, 40) + _tail()
    assert isinstance(_run(lines), ToolCallResult)


def test_real_content_after_15_chunks_is_still_a_text_response():
    lines = _reasoning(20) + [_content("Here is the answer to your question.")] + _reasoning(2, 20) + [
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}', "data: [DONE]"]
    result = _run(lines)
    assert not isinstance(result, ToolCallResult)
