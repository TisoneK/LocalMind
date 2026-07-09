"""
Ollama adapter -- wraps the Ollama OpenAI-compatible API.

Ollama exposes a REST API at http://localhost:11434 that is compatible with
the OpenAI chat completions format. This adapter handles:
- Streaming responses token by token
- Native tool/function calling via Ollama v0.3+ OpenAI-compatible endpoint
- Connection errors with clear user-facing messages
- Model context window detection (with smart per-tier defaults)
- Health checking (is Ollama running?)
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

from adapters.base import BaseAdapter
from core.config import settings
from core.models import StreamChunk


# Per-intent timeout overrides (seconds).
# CHAT is fast; tool-heavy intents need more time.
def _build_intent_timeouts() -> dict[str, int]:
    """Read per-intent timeouts from settings so .env changes take effect on restart."""
    return {
        "chat": settings.ollama_timeout_chat,
        "web_search": settings.ollama_timeout_web_search,
        "file_task": settings.ollama_timeout_file_task,
        "file_write": settings.ollama_timeout_file_write,
        "shell": settings.ollama_timeout_shell,
        "code_exec": settings.ollama_timeout_code_exec,
        "sysinfo": settings.ollama_timeout_sysinfo,
        "memory_op": settings.ollama_timeout_memory_op,
    }


_INTENT_TIMEOUTS: dict[str, int] = _build_intent_timeouts()
_DEFAULT_TIMEOUT: int = settings.ollama_timeout_default

logger = logging.getLogger(__name__)

# Known context windows for common models
_MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "llama3.1:8b": 128000,
    "llama3.2:3b": 128000,
    "llama3.1:70b": 128000,
    "qwen2.5-coder:7b": 32768,
    "qwen2.5-coder:14b": 32768,
    "deepseek-coder-v2:16b": 65536,
    "mistral:7b": 32768,
    "mixtral:8x7b": 32768,
    "phi3:mini": 4096,
    "gemma2:9b": 8192,
    "gemma3:1b": 131072,
    "gemma3:4b": 131072,
    "gemma3:12b": 131072,
    "gemma3:27b": 131072,
    "qwen3.5:9b": 131072,
    "qwen3:9b": 131072,
}

# Context window tiers for models not in the lookup table.
_SMALL_MODEL_TAGS = (":1b", ":3b", "phi3:mini", "phi3.5")
_MEDIUM_MODEL_TAGS = (":7b", ":8b", ":9b", ":14b", ":12b")


@dataclass
class ToolCallResult:
    """Returned by ``chat_with_tools`` when the model invokes a tool."""

    tool_name: str
    tool_args: dict
    raw_content: str = ""  # any text content emitted before the tool call


@dataclass
class MultiToolCallResult:
    """Returned by ``chat_with_tools`` when the model invokes multiple tools.

    When the LLM returns multiple tool calls in a single response (parallel
    tool calling), we batch them here so the agent loop can dispatch them
    concurrently via asyncio.gather().  Falls back gracefully: consumers
    that don't handle MultiToolCallResult can treat it as a single
    ToolCallResult by accessing .first.
    """

    calls: list[ToolCallResult]  # ordered as the model returned them
    raw_content: str = ""

    @property
    def first(self) -> ToolCallResult:
        """Convenience: get the first tool call (backward compat)."""
        return (
            self.calls[0]
            if self.calls
            else ToolCallResult(tool_name="", tool_args={}, raw_content=self.raw_content)
        )

    @property
    def is_parallel(self) -> bool:
        """True when the model returned more than one tool call."""
        return len(self.calls) > 1


def _is_small_model(model: str) -> bool:
    """Return True for 1B/3B/mini models that should use reduced context."""
    return any(tag in model for tag in _SMALL_MODEL_TAGS)


def _is_medium_model(model: str) -> bool:
    """Return True for 7B-14B models."""
    return any(tag in model for tag in _MEDIUM_MODEL_TAGS)


def _smart_num_ctx(model: str, context_window: int, intent: str = "chat") -> int:
    """Choose a practical ``num_ctx`` that balances capability vs. resource use.

    Previous logic capped small models to 2048 which left almost zero room for
    conversation after the response-reserve was subtracted.  The new tiers:

    * **Small** (1b/3b/phi3:mini) — 8 192 tokens.  Enough for multi-turn chat
      without blowing up VRAM on consumer hardware.
    * **Medium** (7b-14b) — 16 384 tokens.
    * **Large** — use the model's full context window.
    """
    if _is_small_model(model):
        return min(context_window, 8192)
    if _is_medium_model(model):
        return min(context_window, 16384)
    # Large models: use the full window
    return context_window


class OllamaAdapter(BaseAdapter):
    """Wraps the Ollama OpenAI-compatible API with streaming + tool calling."""

    # Cache for available models — avoids hitting /api/tags on every request.
    _cached_models: list[str] = []
    _models_cache_ts: float = 0.0
    _MODELS_CACHE_TTL: float = 30.0  # seconds

    def __init__(self, model_override: str = ""):
        self._base_url = settings.ollama_base_url.rstrip("/")
        # Strip inline .env comments — pydantic-settings doesn't do this by default
        raw = model_override if model_override else settings.ollama_model
        self._model = raw.split("#")[0].strip()
        self._timeout = settings.ollama_timeout
        self._keep_alive = settings.ollama_keep_alive
        # Single persistent client with connection pooling.
        # Limits and timeouts are overridden per-request so the shared client
        # never becomes a bottleneck.
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout, connect=10.0),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=120,
            ),
        )

    async def _check_model_exists(self) -> tuple[bool, list[str]]:
        """Check if the configured model exists locally via GET /api/tags.

        Returns (exists, available_models). The result is cached for
        ``_MODELS_CACHE_TTL`` seconds to avoid hammering Ollama on every
        request.
        """
        import time as _time

        now = _time.monotonic()
        if now - OllamaAdapter._models_cache_ts < OllamaAdapter._MODELS_CACHE_TTL:
            available = OllamaAdapter._cached_models
        else:
            try:
                resp = await self._client.get(
                    f"{self._base_url}/api/tags",
                    timeout=httpx.Timeout(5.0, connect=3.0),
                )
                if resp.status_code == 200:
                    data = resp.json()
                    available = [m.get("name", "") for m in data.get("models", [])]
                    OllamaAdapter._cached_models = available
                    OllamaAdapter._models_cache_ts = now
                else:
                    available = []
            except Exception:
                available = []

        model_exists = any(
            m == self._model or m.split(":")[0] == self._model.split(":")[0] for m in available
        )
        return model_exists, available

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def context_window(self) -> int:
        model = self._model.split("#")[0].strip()
        base_model = model.split(":")[0]
        return _MODEL_CONTEXT_WINDOWS.get(
            model,
            _MODEL_CONTEXT_WINDOWS.get(base_model, 8192),
        )

    @property
    def effective_context_window(self) -> int:
        """The actual num_ctx sent to Ollama — capped for small/medium models.

        Use this for context budget calculations instead of context_window,
        which returns the model's declared maximum.  The declared maximum for
        gemma3:1b is 131072, but _smart_num_ctx caps it to 8192 — a 16x
        difference that causes context_builder to budget 131K tokens when only
        8K will actually be processed by Ollama.
        """
        return _smart_num_ctx(self._model, self.context_window)

    # ------------------------------------------------------------------
    # Core chat (streaming, no tools)
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        intent: str = "chat",
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a plain-text response from the model."""
        url = f"{self._base_url}/v1/chat/completions"
        timeout = _INTENT_TIMEOUTS.get(intent, _DEFAULT_TIMEOUT)
        num_ctx = _smart_num_ctx(self._model, self.context_window, intent)

        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            "keep_alive": self._keep_alive,
            "options": {"num_ctx": num_ctx},
        }

        try:
            async with self._client.stream("POST", url, json=payload, timeout=timeout) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    raw_error = body.decode(errors="replace")[:200]

                    # Build a user-friendly error message with actionable advice
                    if response.status_code == 404:
                        # Model not found — check what's available and suggest
                        model_exists, available = await self._check_model_exists()
                        if not self._model:
                            error_msg = (
                                "Model not specified. No default model is configured. "
                                "Please set OLLAMA_MODEL in your .env or select a model in Settings."
                            )
                        elif not model_exists and available:
                            # Suggest the first available model as an alternative
                            suggestion = available[0]
                            error_msg = (
                                f"Model '{self._model}' not found locally. "
                                f"Available models: {', '.join(available[:5])}. "
                                f"Run `ollama pull {self._model}` to download it, "
                                f"or switch to '{suggestion}' in Settings."
                            )
                        elif not model_exists:
                            error_msg = (
                                f"Model '{self._model}' not found locally and no other "
                                f"models are installed. Run `ollama pull {self._model}` "
                                f"to download it, or `ollama pull llama3.1:8b` for a "
                                f"recommended starter model."
                            )
                        else:
                            error_msg = (
                                f"Ollama returned 404 for model '{self._model}'. "
                                f"The model appears to exist but Ollama could not load it. "
                                f"Try restarting Ollama or pulling the model again."
                            )
                    else:
                        error_msg = f"Ollama returned {response.status_code}: {raw_error}"

                    logger.error(error_msg)
                    yield StreamChunk(text=error_msg, done=True, error=error_msg)
                    return

                # Buffer for parsing Thinking... markers
                _think_buf = ""
                _in_think = False

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]  # strip "data: "
                    if data == "[DONE]":
                        # Flush any remaining buffer
                        if _think_buf:
                            if _in_think:
                                yield StreamChunk(text="", thinking=_think_buf)
                            else:
                                yield StreamChunk(text=_think_buf)
                        yield StreamChunk(text="", done=True)
                        return
                    try:
                        obj = json.loads(data)
                        delta = obj["choices"][0]["delta"]
                        text = delta.get("content", "")
                        if not text:
                            continue

                        # Route Thinking... markers to thinking field
                        _think_buf += text
                        while True:
                            if not _in_think:
                                start = _think_buf.find("Thinking...")
                                if start == -1:
                                    yield StreamChunk(text=_think_buf)
                                    _think_buf = ""
                                    break
                                # emit text before Thinking...
                                if start > 0:
                                    yield StreamChunk(text=_think_buf[:start])
                                _think_buf = _think_buf[start + 10 :]  # "Thinking..." is 10 chars
                                _in_think = True
                            else:
                                end = _think_buf.find("...done thinking.")
                                if end == -1:
                                    yield StreamChunk(text="", thinking=_think_buf)
                                    _think_buf = ""
                                    break
                                yield StreamChunk(text="", thinking=_think_buf[:end])
                                _think_buf = _think_buf[
                                    end + 16 :
                                ]  # "...done thinking." is 16 chars
                                _in_think = False
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

        except httpx.ConnectError:
            msg = (
                f"Cannot connect to Ollama at {self._base_url}. "
                "Is Ollama running? Try: ollama serve"
            )
            logger.error(msg)
            yield StreamChunk(text=msg, done=True, error=msg)
        except httpx.TimeoutException:
            msg = (
                f"Ollama timed out after {timeout}s "
                f"(intent: {intent}, model: {self._model}). "
                "The model may still be loading, or the request is too large "
                "for the context window. Try a shorter message or restart Ollama."
            )
            logger.error(msg)
            yield StreamChunk(text=msg, done=True, error=msg)

    # ------------------------------------------------------------------
    # Chat with native tool calling
    # ------------------------------------------------------------------

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.7,
        intent: str = "chat",
        tool_choice: str | dict | None = None,
    ) -> "AsyncIterator[StreamChunk] | ToolCallResult":
        """Send messages with tool definitions and stream tokens live.

        Uses Ollama's OpenAI-compatible endpoint (v0.3+).  Returns either:
        * An ``AsyncIterator[StreamChunk]`` — text streamed token-by-token.
        * A ``ToolCallResult`` — when the model invokes a function/tool.

        Uses a background asyncio task + Queue so text tokens are delivered
        live to the UI instead of being held back until the full response
        arrives (which caused the "Generating response..." spinner to freeze).

        When tool_calls arrive in the stream the background task signals the
        consumer, waits to accumulate all argument fragments, then returns
        a ToolCallResult.  The whole exchange is transparent to loop.py.
        """
        url = f"{self._base_url}/v1/chat/completions"
        timeout = _INTENT_TIMEOUTS.get(intent, _DEFAULT_TIMEOUT)
        num_ctx = _smart_num_ctx(self._model, self.context_window, intent)

        payload: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            "tools": tools,
            "keep_alive": self._keep_alive,
            "options": {"num_ctx": num_ctx},
        }
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

        # Sentinel objects placed in the queue by the background reader task.
        _TOOL_CALL_DETECTED = object()  # model started a tool call
        _STREAM_DONE = object()  # stream ended with no tool call
        _STREAM_ERROR = object()  # connection/timeout error

        queue: asyncio.Queue = asyncio.Queue()

        # Shared mutable state written by the background reader.
        state: dict = {
            "tool_call_buffers": {},  # index -> {id, name, arguments}
            "raw_content_parts": [],  # text emitted before/during tool call
            "text_chunks": [],  # StreamChunks already put on the queue
            "error_msg": "",
        }

        async def _reader() -> None:
            try:
                async with self._client.stream(
                    "POST", url, json=payload, timeout=timeout
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        raw_error = body.decode(errors="replace")[:200]

                        # Build a user-friendly error message with actionable advice
                        if response.status_code == 404:
                            model_exists, available = await self._check_model_exists()
                            if not self._model:
                                state["error_msg"] = (
                                    "Model not specified. No default model is configured. "
                                    "Please set OLLAMA_MODEL in your .env or select a model in Settings."
                                )
                            elif not model_exists and available:
                                suggestion = available[0]
                                state["error_msg"] = (
                                    f"Model '{self._model}' not found locally. "
                                    f"Available models: {', '.join(available[:5])}. "
                                    f"Run `ollama pull {self._model}` to download it, "
                                    f"or switch to '{suggestion}' in Settings."
                                )
                            elif not model_exists:
                                state["error_msg"] = (
                                    f"Model '{self._model}' not found locally and no other "
                                    f"models are installed. Run `ollama pull {self._model}` "
                                    f"to download it, or `ollama pull llama3.1:8b` for a "
                                    f"recommended starter model."
                                )
                            else:
                                state["error_msg"] = (
                                    f"Ollama returned 404 for model '{self._model}'. "
                                    f"The model appears to exist but Ollama could not load it. "
                                    f"Try restarting Ollama or pulling the model again."
                                )
                        else:
                            state["error_msg"] = (
                                f"Ollama returned {response.status_code}: {raw_error}"
                            )
                        logger.error(state["error_msg"])
                        await queue.put(_STREAM_ERROR)
                        return

                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data == "[DONE]":
                            break

                        try:
                            obj = json.loads(data)
                            delta = obj["choices"][0]["delta"]
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue

                        text = delta.get("content", "")
                        tc_deltas = delta.get("tool_calls")

                        if text:
                            state["raw_content_parts"].append(text)
                            # Only stream text live when no tool call has been detected yet
                            if not state["tool_call_buffers"] and not tc_deltas:
                                chunk = StreamChunk(text=text, done=False)
                                state["text_chunks"].append(chunk)
                                await queue.put(chunk)

                        if tc_deltas:
                            if not state["tool_call_buffers"]:
                                # First tool-call delta — signal consumer to stop reading
                                await queue.put(_TOOL_CALL_DETECTED)
                            for tc_delta in tc_deltas:
                                idx = tc_delta.get("index", 0)
                                if idx not in state["tool_call_buffers"]:
                                    state["tool_call_buffers"][idx] = {
                                        "id": tc_delta.get("id", ""),
                                        "name": "",
                                        "arguments": "",
                                    }
                                buf = state["tool_call_buffers"][idx]
                                if tc_delta.get("id"):
                                    buf["id"] = tc_delta["id"]
                                fn = tc_delta.get("function", {})
                                if fn.get("name"):
                                    buf["name"] = fn["name"]
                                if fn.get("arguments"):
                                    buf["arguments"] += fn["arguments"]

                    await queue.put(_STREAM_DONE)

            except httpx.ConnectError:
                state["error_msg"] = (
                    f"Cannot connect to Ollama at {self._base_url}. "
                    "Is Ollama running? Try: ollama serve"
                )
                logger.error(state["error_msg"])
                await queue.put(_STREAM_ERROR)
            except httpx.TimeoutException:
                state["error_msg"] = (
                    f"Ollama timed out after {timeout}s "
                    f"(intent: {intent}, model: {self._model}). "
                    "The model may still be loading, or the request is too large "
                    "for the context window. Try a shorter message or restart Ollama."
                )
                logger.error(state["error_msg"])
                await queue.put(_STREAM_ERROR)
            except Exception as exc:
                state["error_msg"] = f"Unexpected adapter error: {exc}"
                logger.error(state["error_msg"])
                await queue.put(_STREAM_ERROR)

        reader_task = asyncio.create_task(_reader())

        # Drain the queue until we hit a sentinel
        tool_call_detected = False
        stream_error = False

        while True:
            item = await queue.get()
            if item is _STREAM_DONE:
                break
            if item is _STREAM_ERROR:
                stream_error = True
                break
            if item is _TOOL_CALL_DETECTED:
                tool_call_detected = True
                # Wait for the reader to finish accumulating all argument fragments
                await reader_task
                break
            # StreamChunk — already on state["text_chunks"], loop.py will replay it

        if not tool_call_detected:
            try:
                await asyncio.wait_for(reader_task, timeout=1.0)
            except (asyncio.TimeoutError, Exception):
                pass

        # ── ToolCallResult path ───────────────────────────────────────────
        if tool_call_detected and state["tool_call_buffers"]:
            raw_content_text = "".join(state["raw_content_parts"])

            # Parse all tool calls from the response
            all_calls: list[ToolCallResult] = []
            for idx in sorted(state["tool_call_buffers"].keys()):
                buf = state["tool_call_buffers"][idx]
                raw_args = buf["arguments"]
                try:
                    tool_args = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    logger.warning("[adapter] tool args not valid JSON: %s", raw_args[:200])
                    tool_args = {"_raw_arguments": raw_args}
                all_calls.append(
                    ToolCallResult(
                        tool_name=buf["name"],
                        tool_args=tool_args,
                        raw_content=raw_content_text
                        if idx == sorted(state["tool_call_buffers"].keys())[0]
                        else "",
                    )
                )

            # Single tool call — return simple ToolCallResult (backward compat)
            if len(all_calls) == 1:
                return all_calls[0]

            # Multiple tool calls — return MultiToolCallResult for parallel dispatch
            logger.info(
                "[adapter] %d tool calls detected — returning MultiToolCallResult", len(all_calls)
            )
            return MultiToolCallResult(
                calls=all_calls,
                raw_content=raw_content_text,
            )

        # ── Streaming text path ───────────────────────────────────────────
        if stream_error:

            async def _error_iter():
                yield StreamChunk(text=state["error_msg"], done=True, error=state["error_msg"])

            return _error_iter()

        # Replay buffered chunks (loop.py buffers them for tool-talk detection
        # before deciding to stream them to the UI — no double-delivery issue).
        async def _text_replay() -> AsyncIterator[StreamChunk]:
            for chunk in state["text_chunks"]:
                yield chunk
            yield StreamChunk(text="", done=True)

        return _text_replay()

    # ------------------------------------------------------------------
    # Model management
    # ------------------------------------------------------------------

    async def warmup(self) -> bool:
        """Pre-load the model into VRAM so the first user request is fast.

        Strategy (in order of preference):
        1. /api/generate with no prompt key — Ollama's documented way to
           load-and-hold a model without generating tokens.  Works on most
           models but returns 400 on some (e.g. qwen3.5:9b).
        2. /api/chat with a minimal message — generates 1 token then stops.
           Works on all models that support the chat endpoint.
        """
        # Attempt 1: /api/generate with no prompt (zero-cost warmup)
        url_gen = f"{self._base_url}/api/generate"
        payload_gen = {
            "model": self._model,
            "keep_alive": self._keep_alive,
        }
        try:
            response = await self._client.post(url_gen, json=payload_gen, timeout=60)
            if response.status_code == 200:
                logger.info(
                    "[adapter] model '%s' pre-loaded via /api/generate (keep_alive=%s)",
                    self._model,
                    self._keep_alive,
                )
                return True
            # 400 from some models (e.g. qwen3.5) — fall through to chat warmup
            logger.info(
                "[adapter] /api/generate warmup returned %s for model '%s' — trying /api/chat",
                response.status_code,
                self._model,
            )
        except Exception as exc:
            logger.info(
                "[adapter] /api/generate warmup failed for model '%s': %s — trying /api/chat",
                self._model,
                exc,
            )

        # Attempt 2: /api/chat with minimal prompt (generates 1 token)
        url_chat = f"{self._base_url}/v1/chat/completions"
        payload_chat = {
            "model": self._model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
            "stream": False,
            "keep_alive": self._keep_alive,
        }
        try:
            response = await self._client.post(url_chat, json=payload_chat, timeout=60)
            ok = response.status_code == 200
            if ok:
                logger.info(
                    "[adapter] model '%s' pre-loaded via /api/chat warmup (keep_alive=%s)",
                    self._model,
                    self._keep_alive,
                )
            else:
                logger.warning(
                    "[adapter] warmup returned %s for model '%s' via both /api/generate and /api/chat",
                    response.status_code,
                    self._model,
                )
            return ok
        except Exception as exc:
            logger.warning(
                "[adapter] warmup failed for model '%s' via both endpoints: %s",
                self._model,
                exc,
            )
            return False

    async def health_check(self) -> bool:
        """Return True if Ollama is reachable and responding."""
        try:
            response = await self._client.get(f"{self._base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """Return names of locally available Ollama chat/generation models."""
        try:
            response = await self._client.get(f"{self._base_url}/api/tags", timeout=5)
            data = response.json()
            # Filter out embedding models (they have separate /api/embeddings endpoint)
            all_models = [m["name"] for m in data.get("models", [])]
            return [m for m in all_models if not m.endswith("-embed")]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Gracefully close the persistent HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "OllamaAdapter":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
