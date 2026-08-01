"""
Tests for the Ollama adapter.
All HTTP calls are mocked — these tests do not require Ollama to be running.
"""
from __future__ import annotations
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from adapters.ollama import OllamaAdapter, _normalize_ollama_usage
from core.models import StreamChunk


def test_normalize_ollama_native_usage():
    """Native Ollama terminal counters map to the shared usage schema."""
    assert _normalize_ollama_usage(
        {"prompt_eval_count": 23, "eval_count": 9}
    ) == {
        "prompt_tokens": 23,
        "completion_tokens": 9,
        "total_tokens": 32,
    }


def test_normalize_ollama_nested_usage():
    """OpenAI-shaped usage nested in an Ollama response is also supported."""
    assert _normalize_ollama_usage(
        {"usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16}}
    ) == {
        "prompt_tokens": 12,
        "completion_tokens": 4,
        "total_tokens": 16,
    }


def _make_sse_line(text: str, done: bool = False) -> str:
    if done:
        return "data: [DONE]"
    payload = json.dumps({"choices": [{"delta": {"content": text}}]})
    return f"data: {payload}"


@pytest.fixture
def adapter():
    return OllamaAdapter()


@pytest.mark.asyncio
async def test_chat_streams_tokens(adapter):
    """Adapter should yield one StreamChunk per token."""
    lines = [
        _make_sse_line("Hello"),
        _make_sse_line(", "),
        _make_sse_line("world"),
        _make_sse_line("", done=True),
    ]

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.aiter_lines = AsyncMock(return_value=iter(lines))

    async def fake_aiter_lines():
        for line in lines:
            yield line

    mock_response.aiter_lines = fake_aiter_lines

    with patch.object(adapter._client, "stream") as mock_stream:
        mock_stream.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream.return_value.__aexit__ = AsyncMock(return_value=False)

        chunks = []
        async for chunk in adapter.chat([{"role": "user", "content": "Hi"}]):
            chunks.append(chunk)

    texts = [c.text for c in chunks if c.text]
    assert texts == ["Hello", ", ", "world"]
    assert chunks[-1].done is True


@pytest.mark.asyncio
async def test_chat_preserves_terminal_usage(adapter):
    """Usage on the terminal Ollama frame reaches the done chunk."""
    lines = [
        _make_sse_line("Hello"),
        'data: {"prompt_eval_count": 23, "eval_count": 9}',
        _make_sse_line("", done=True),
    ]

    mock_response = AsyncMock()
    mock_response.status_code = 200

    async def fake_aiter_lines():
        for line in lines:
            yield line

    mock_response.aiter_lines = fake_aiter_lines

    with patch.object(adapter._client, "stream") as mock_stream:
        mock_stream.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream.return_value.__aexit__ = AsyncMock(return_value=False)

        chunks = [chunk async for chunk in adapter.chat([{"role": "user", "content": "Hi"}])]

    assert chunks[-1].done is True
    assert chunks[-1].usage == {
        "prompt_tokens": 23,
        "completion_tokens": 9,
        "total_tokens": 32,
    }


@pytest.mark.asyncio
async def test_chat_connect_error_yields_error_chunk(adapter):
    """ConnectError should produce a single error StreamChunk, not raise."""
    import httpx

    with patch.object(adapter._client, "stream", side_effect=httpx.ConnectError("refused")):
        chunks = []
        async for chunk in adapter.chat([{"role": "user", "content": "Hi"}]):
            chunks.append(chunk)

    assert len(chunks) == 1
    assert chunks[0].error is not None
    assert "Ollama" in chunks[0].error
    assert chunks[0].done is True


@pytest.mark.asyncio
async def test_health_check_returns_false_when_unreachable(adapter):
    import httpx
    with patch.object(adapter._client, "get", side_effect=httpx.ConnectError("refused")):
        result = await adapter.health_check()
    assert result is False


def test_context_window_known_model(adapter):
    adapter._model = "llama3.1:8b"
    assert adapter.context_window == 128000


def test_context_window_unknown_model_defaults(adapter):
    adapter._model = "some-unknown-model:7b"
    assert adapter.context_window == 8192
