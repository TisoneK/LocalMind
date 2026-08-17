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


# ── Bug 3 (Session 289): real context window via /api/show ────────────────
# phi4-mini:latest (128K real window, 3.8B params) was absent from the static
# table AND matched no size tag, so it fell to the 8192 default — the sidebar
# meter read 5248/8192 = 64% for a nearly-empty chat.

from adapters.ollama import (  # noqa: E402
    _extract_context_length,
    _DETECTED_CONTEXT_WINDOWS,
    _is_small_model,
    _smart_num_ctx,
)


@pytest.fixture(autouse=True)
def _clear_detected_cache():
    """Isolate the module-level detection cache between tests."""
    _DETECTED_CONTEXT_WINDOWS.clear()
    yield
    _DETECTED_CONTEXT_WINDOWS.clear()


def test_extract_context_length_arch_prefixed_key():
    # Ollama reports "<arch>.context_length" — arch varies per model.
    payload = {"model_info": {"phi3.context_length": 131072, "phi3.embedding_length": 3072}}
    assert _extract_context_length(payload) == 131072


def test_extract_context_length_missing_returns_none():
    assert _extract_context_length({"model_info": {"general.parameter_count": 3821079552}}) is None
    assert _extract_context_length({}) is None
    assert _extract_context_length({"model_info": None}) is None


def test_phi4_mini_treated_as_small():
    # The size-tier heuristic must catch tag-free "mini" models so num_ctx
    # defaults to a resource-sane 8192 rather than ballooning to the full 128K.
    assert _is_small_model("phi4-mini:latest") is True


@pytest.mark.asyncio
async def test_detect_context_length_populates_window(adapter, monkeypatch):
    adapter._model = "phi4-mini:latest"
    # Pre-condition: unknown model → 8192 fallback (the bug).
    assert adapter.context_window == 8192

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value={"model_info": {"phi3.context_length": 131072}})
    monkeypatch.setattr(adapter._client, "post", AsyncMock(return_value=mock_resp))

    await adapter.prime_context_window()
    # After detection the declared window is the model's real capacity.
    assert adapter.context_window == 131072
    # phi4-mini is "small" → num_ctx still capped at 8192 (memory safety).
    assert adapter.effective_context_window == 8192


@pytest.mark.asyncio
async def test_detect_context_length_is_cached(adapter, monkeypatch):
    adapter._model = "phi4-mini:latest"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value={"model_info": {"phi3.context_length": 131072}})
    post = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(adapter._client, "post", post)

    await adapter.prime_context_window()
    await adapter.prime_context_window()
    # A successful detection is cached for the process — only one /api/show hit.
    assert post.await_count == 1


@pytest.mark.asyncio
async def test_detect_context_length_failure_falls_back(adapter, monkeypatch):
    import httpx

    adapter._model = "llama3.1:8b"  # known model in the static table
    monkeypatch.setattr(adapter._client, "post", AsyncMock(side_effect=httpx.ConnectError("refused")))
    await adapter.prime_context_window()
    # /api/show unreachable → static table still answers.
    assert adapter.context_window == 128000


def test_num_ctx_override_wins_and_clamps(adapter, monkeypatch):
    from core.config import settings

    adapter._model = "llama3.1:8b"  # 128000 declared
    monkeypatch.setattr(settings, "ollama_num_ctx", 32768, raising=False)
    # Override beats the size-tier default.
    assert adapter.effective_context_window == 32768
    # An override larger than the declared window is clamped to capacity.
    monkeypatch.setattr(settings, "ollama_num_ctx", 999999, raising=False)
    assert adapter.effective_context_window == 128000


def test_num_ctx_override_zero_is_auto(adapter, monkeypatch):
    from core.config import settings

    adapter._model = "llama3.1:70b"
    monkeypatch.setattr(settings, "ollama_num_ctx", 0, raising=False)
    # 0 = auto → large model (no small/medium tag) uses its full window.
    assert _smart_num_ctx("llama3.1:70b", 128000) == 128000
