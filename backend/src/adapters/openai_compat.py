"""
Composable adapter for OpenAI-compatible APIs.

Supports multiple providers (OpenAI, Anthropic, OpenRouter, LiteLLM) with
shared logic and provider-specific config. Each provider is configured
via environment variables and registered in PROVIDER_CONFIGS.

v8 changes:
- Bug C fix: _stream_from_http() now gracefully handles empty content deltas
  (keepalives from providers that send delta.content="" between text chunks).
  Previously these empty deltas were silently skipped (correct), but they
  also shouldn't cause the generator to stall. The fix ensures we continue
  reading from the stream without yielding for empty content.
- v8.1 fix: Tool args truncation — Phase 1 detection now reads up to 10
  chunks (was 5) before deciding text vs tool_call, giving slow-streaming
  providers more time to produce the tool_call delta. Phase 2a now drains
  until [DONE] or finish_reason=="tool_calls" to ensure complete args.
  If args JSON is still invalid after draining, logs a clear warning with
  the raw args preview instead of silently passing malformed data.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncIterator

import httpx

from adapters.base import BaseAdapter
from core.models import StreamChunk

if TYPE_CHECKING:
    # ToolCallResult is defined in adapters.ollama. Imported only under
    # TYPE_CHECKING to avoid a circular import at runtime (ollama.py is
    # the heavier module). Runtime references use local imports.
    from adapters.ollama import ToolCallResult

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Model context window registry
# ─────────────────────────────────────────────────────────────────────────────

MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # OpenAI
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "gpt-4": 8192,
    "gpt-3.5-turbo": 16385,
    # Anthropic
    "claude-sonnet-4-20250514": 200000,
    "claude-3-5-sonnet-20241022": 200000,
    "claude-3-5-sonnet-20240620": 200000,
    "claude-3-opus-20240229": 200000,
    "claude-3-sonnet-20240229": 200000,
    "claude-3-haiku-20240307": 200000,
    "claude-3-5-haiku-20241022": 200000,
    # OpenRouter (varies by underlying model, use conservative default)
    "openrouter/auto": 128000,
    "openrouter/free": 128000,
    # DeepSeek
    "deepseek-chat": 64000,
    "deepseek-coder": 64000,
    # Zen (curated models)
    "zen/default": 128000,
    "minimax-m2.5-free": 128000,
    "MiniMax M2.5 Free": 128000,
    # Groq (fast inference)
    "llama-3.1-70b-versatile": 128000,
    "llama-3.1-8b-instant": 128000,
    "mixtral-8x7b-32768": 32768,
    # Together AI
    "meta-llama/Llama-3.1-70B-Instruct-Turbo": 128000,
    # Mistral
    "mistral-large-latest": 131072,
    "mistral-small-latest": 131072,
    # Cohere
    "command-r-plus": 128000,
    "command-r": 128000,
    # Cerebras (Llama 3.3 70B, gpt-oss-120B, Qwen3 32B)
    "llama-3.3-70b": 128000,
    "llama4-scout-17b-16e-instruct": 128000,
    "qwen-3-32b": 128000,
    "gpt-oss-120b": 128000,
    # SambaNova
    "Meta-Llama-3.3-70B-Instruct": 128000,
    "DeepSeek-R1": 128000,
    # Google Gemini (via OpenAI-compatible endpoint)
    "gemini-2.5-flash": 1048576,
    "gemini-2.5-pro": 1048576,
    "gemini-2.5-flash-lite": 1048576,
    # Chutes (varies by underlying model; conservative default)
    "unsloth/Llama-3.3-70B-Instruct": 128000,
    # Default fallback
    "default": 32768,
}

# ─────────────────────────────────────────────────────────────────────────────
# Provider configuration
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ProviderConfig:
    name: str  # "openai", "anthropic", "openrouter", etc.
    base_url: str  # e.g. "https://api.openai.com/v1"
    api_key: str  # from env var
    default_model: str  # fallback if none specified
    headers: dict = None  # optional extra headers
    supports_streaming: bool = True


PROVIDER_CONFIGS: dict[str, ProviderConfig] = {
    "openai": ProviderConfig(
        name="openai",
        base_url="https://api.openai.com/v1",
        api_key=os.getenv("OPENAI_API_KEY", ""),
        default_model="gpt-4o-mini",
    ),
    "anthropic": ProviderConfig(
        name="anthropic",
        base_url="https://api.anthropic.com/v1",
        api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        default_model="claude-3-5-sonnet-20241022",
        headers={
            "anthropic-version": "2023-06-01",
            "x-api-key": os.getenv("ANTHROPIC_API_KEY", ""),
        },
    ),
    "openrouter": ProviderConfig(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
        default_model="openrouter/auto",
    ),
    "deepseek": ProviderConfig(
        name="deepseek",
        base_url="https://api.deepseek.com/v1",
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        default_model="deepseek-chat",
    ),
    "lite-llm": ProviderConfig(
        name="lite-llm",
        base_url=os.getenv("LITELLM_BASE_URL", "http://localhost:4000"),
        api_key=os.getenv("LITELLM_API_KEY", "dummy"),
        default_model=os.getenv("LITELLM_MODEL", "gpt-4"),
    ),
    "zen": ProviderConfig(
        name="Zen AI",
        base_url="https://opencode.ai/zen/v1",
        api_key=os.getenv("ZEN_API_KEY", ""),
        default_model="minimax-m2.5-free",
    ),
    # High-performance / infra
    "groq": ProviderConfig(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key=os.getenv("GROQ_API_KEY", ""),
        default_model="llama-3.1-70b-versatile",
    ),
    "together": ProviderConfig(
        name="together",
        base_url="https://api.together.ai/v1",
        api_key=os.getenv("TOGETHER_API_KEY", ""),
        default_model="meta-llama/Llama-3.1-70B-Instruct-Turbo",
    ),
    "fireworks": ProviderConfig(
        name="fireworks",
        base_url="https://api.fireworks.ai/v1",
        api_key=os.getenv("FIREWORKS_API_KEY", ""),
        default_model="accounts/fireworks/models/llama-v3-70b-instruct",
    ),
    "deepinfra": ProviderConfig(
        name="deepinfra",
        base_url="https://api.deepinfra.com/v1",
        api_key=os.getenv("DEEPINFRA_API_KEY", ""),
        default_model="meta-llama/Llama-3.1-70B-Instruct",
    ),
    # Model-specific providers
    "mistral": ProviderConfig(
        name="mistral",
        base_url="https://api.mistral.ai/v1",
        api_key=os.getenv("MISTRAL_API_KEY", ""),
        default_model="mistral-large-latest",
    ),
    "cohere": ProviderConfig(
        name="cohere",
        base_url="https://api.cohere.ai/v1",
        api_key=os.getenv("COHERE_API_KEY", ""),
        default_model="command-r-plus",
    ),
    # Gateways (use custom base URL)
    "vercel": ProviderConfig(
        name="vercel",
        base_url=os.getenv("VERCEL_AI_GATEWAY_URL", "https://gateway.ai.vercel.sh"),
        api_key=os.getenv("VERCEL_API_KEY", ""),
        default_model="gpt-4o-mini",
    ),
    "cloudflare": ProviderConfig(
        name="cloudflare",
        base_url=os.getenv("CLOUDFLARE_GATEWAY_URL", "https://gateway.ai.cloudflare.com"),
        api_key=os.getenv("CLOUDFLARE_API_KEY", ""),
        default_model="@cf/meta/llama-3.1-70b-instruct",
    ),
    # Free-tier-friendly providers with strong OpenAI compatibility
    "cerebras": ProviderConfig(
        name="Cerebras",
        base_url="https://api.cerebras.ai/v1",
        api_key=os.getenv("CEREBRAS_API_KEY", ""),
        # llama-3.3-70b is broadly available; gpt-oss-120b also available
        default_model="llama-3.3-70b",
    ),
    "sambanova": ProviderConfig(
        name="SambaNova",
        base_url="https://api.sambanova.ai/v1",
        api_key=os.getenv("SAMBANOVA_API_KEY", ""),
        default_model="Meta-Llama-3.3-70B-Instruct",
    ),
    "gemini": ProviderConfig(
        name="Google Gemini",
        # Google's official OpenAI-compatible endpoint
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key=os.getenv("GEMINI_API_KEY", ""),
        default_model="gemini-2.5-flash",
    ),
    "chutes": ProviderConfig(
        name="Chutes AI",
        base_url="https://api.chutes.ai/v1",
        api_key=os.getenv("CHUTES_API_KEY", ""),
        default_model="unsloth/Llama-3.3-70B-Instruct",
    ),
}


class OpenAICompatAdapter(BaseAdapter):
    """Composable adapter for OpenAI-compatible APIs."""

    def __init__(
        self,
        provider: str = "openai",
        model_override: str = "",
    ):
        from core.config import settings

        cfg = PROVIDER_CONFIGS.get(provider)
        if not cfg:
            raise ValueError(f"Unknown provider: {provider}. Available: {list(PROVIDER_CONFIGS.keys())}")

        # Try runtime API key first, then fall back to env var
        api_key = settings.get_api_key(provider) or cfg.api_key
        if not api_key:
            raise ValueError(f"API key not set for provider '{provider}'. Set it in settings or .env.")

        self._provider_name = cfg.name
        self._base_url = cfg.base_url.rstrip("/")
        # Read the model from settings (set by select_model or settings.json),
        # falling back to the provider default. Previously this only used
        # cfg.default_model (a static value evaluated at import time), so
        # model selection via the UI had NO EFFECT on which model the
        # adapter actually used for chat requests.
        settings_model_attr = f"{provider.replace('-', '')}_model"
        settings_model = getattr(settings, settings_model_attr, "") or ""
        self._model = model_override or settings_model or cfg.default_model
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            **(cfg.headers or {}),
        }
        # Update headers with runtime key if needed
        if "x-api-key" in self._headers:
            self._headers["x-api-key"] = api_key

        # Per-intent timeouts (seconds)
        self._timeouts = {
            "chat": 120,
            "web_search": 180,
            "file_task": 180,
            "file_write": 180,
            "file_edit": 180,
            "shell": 120,
            "code_exec": 180,
            "sysinfo": 60,
            "memory_op": 120,
        }

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=30.0),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
            ),
        )

    # ─────────────────────────────────────────────────────────────────────
    # Properties
    # ─────────────────────────────────────────────────────────────────────

    @property
    def context_window(self) -> int:
        return MODEL_CONTEXT_WINDOWS.get(self._model, MODEL_CONTEXT_WINDOWS["default"])

    @property
    def effective_context_window(self) -> int:
        # Cloud APIs don't need smart capping like Ollama
        return self.context_window

    # ─────────────────────────────────────────────────────────────────────
    # Core chat (streaming)
    # ─────────────────────────────────────────────────────────────────────

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        intent: str = "chat",
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        timeout = self._timeouts.get(intent, 120)

        # Build payload based on provider
        if self._provider_name == "anthropic":
            async for chunk in self._chat_anthropic(messages, temperature, timeout):
                yield chunk
        else:
            async for chunk in self._chat_openai_style(messages, temperature, timeout):
                yield chunk

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.7,
        intent: str = "chat",
        tool_choice: str | dict | None = None,
    ) -> "AsyncIterator[StreamChunk] | ToolCallResult":
        """Send messages with tool definitions.

        For providers that support OpenAI-style function calling (most do via
        the /chat/completions endpoint), we pass the tools parameter and handle
        tool_call responses. For providers that don't (e.g. Anthropic), we fall
        back to regular chat.

        Returns either:
          - ToolCallResult: when the model requests a tool call
          - AsyncIterator[StreamChunk]: when the model streams text

        IMPORTANT: This method must RETURN (not yield) so that the caller
        (AgentLoop) can distinguish ToolCallResult from streaming text via
        isinstance(). Using yield would make this an async generator, which
        cannot be awaited — causing "async_generator can't be used in 'await'
        expression" errors.
        """
        # Anthropic has a different tool calling format — fall back to plain chat
        # TODO: implement Anthropic native tool calling
        if self._provider_name == "anthropic":

            async def _anthropic_fallback() -> AsyncIterator[StreamChunk]:
                async for chunk in self.chat(messages, temperature, intent):
                    yield chunk

            return _anthropic_fallback()

        # OpenAI-style providers: send tools and parse tool_call responses
        timeout = self._timeouts.get(intent, 120)
        url = f"{self._base_url}/chat/completions"

        # Inject tool descriptions into the system prompt as a fallback
        # for providers that don't support the tools parameter natively.
        # This gives the model context about available tools even if the
        # API doesn't support structured tool calling.
        tool_descriptions = []
        tool_names = set()
        for tool in tools:
            func = tool.get("function", {})
            name = func.get("name", "")
            tool_names.add(name)
            desc = func.get("description", "")
            params = func.get("parameters", {})
            required = params.get("required", [])
            param_desc = ", ".join(
                f"{p}: {params.get('properties', {}).get(p, {}).get('description', p)}" for p in required
            )
            tool_descriptions.append(f"- {name}({param_desc}): {desc}")

        tool_context = ""
        if tool_descriptions:
            tool_context = (
                "\n\nYou have access to these tools. To use a tool, call it directly using "
                "the native tool-calling API. Do NOT output tool calls as text.\n\n"
                "Available tools:\n" + "\n".join(tool_descriptions) + "\n\n"
                "IMPORTANT: Call the tool immediately when needed. Do NOT narrate your intent. "
                "Do NOT output minimax:tool_call or any other text format for tool calls. "
                "Use the native function-calling API only."
            )

        # Add tool context to the system message
        enhanced_messages = list(messages)
        if enhanced_messages and enhanced_messages[0].get("role") == "system":
            enhanced_messages[0] = {
                "role": "system",
                "content": enhanced_messages[0]["content"] + tool_context,
            }

        payload = {
            "model": self._model,
            "messages": enhanced_messages,
            "temperature": temperature,
            "stream": True,
        }

        # Try sending with the tools parameter for providers that support it
        if tools:
            payload["tools"] = tools

        # ── Streaming implementation ─────────────────────────────────────────
        # Previous version buffered ALL text before returning, which broke
        # real-time SSE streaming — the user saw "Generating response..."
        # until the entire LLM response was complete, then it appeared at once.
        #
        # New approach: detect tool calls from streaming deltas (they appear
        # early). If no tool call is detected, stream text directly from the
        # HTTP response without buffering. This gives true token-by-token
        # streaming through to the frontend.
        #
        # We use a two-phase approach:
        #   Phase 1: Read deltas until we can determine tool_call vs text
        #            (usually just 1-3 deltas, <100ms)
        #   Phase 2a: If tool_call detected → buffer remaining, return ToolCallResult
        #   Phase 2b: If text → return async gen that yields directly from stream

        try:
            tool_call_buffers: dict[int, dict] = {}
            raw_content_parts: list[str] = []
            tool_call_detected = False
            # Initial text accumulated during Phase 1 — yielded once Phase 2
            # decides this is a text response (not tool call).
            initial_text_chunks: list[StreamChunk] = []
            phase1_done = False

            # Open the streaming response WITHOUT async-with so we can hand
            # the open stream to the returned generator. The generator is
            # responsible for closing it.
            request = self._client.build_request(
                "POST",
                url,
                json=payload,
                headers=self._headers,
            )
            response = await self._client.send(request, stream=True)

            if response.status_code != 200:
                body = await response.aread()
                await response.aclose()
                error_msg = (
                    f"{self._provider_name} returned {response.status_code}: {body.decode(errors='replace')[:200]}"
                )
                logger.error(error_msg)

                async def _error_iter():
                    # text="" on error so consumers that only read .text don't
                    # leak the error message as chat content. The .error field
                    # is the authoritative signal.
                    yield StreamChunk(text="", done=True, error=error_msg)

                return _error_iter()

            # ── Phase 1: Detect tool_call vs text ──────────────────────────
            # Read deltas until we see either tool_calls in the delta or
            # enough text to be confident this is a plain text response.
            # Tool calls typically appear in the very first delta.
            # v8.1: raised from 5 to 10 — some providers (MiniMax, etc.)
            # take longer to emit the tool_call delta, and 5 was too
            # aggressive, causing false text classification.
            _DETECTION_CHUNK_LIMIT = 10
            chunks_read = 0

            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    phase1_done = True
                    break

                try:
                    obj = json.loads(data)
                    choice = obj.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    chunks_read += 1

                    # Check for tool calls in the delta
                    if "tool_calls" in delta:
                        tool_call_detected = True
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", 0)
                            if idx not in tool_call_buffers:
                                tool_call_buffers[idx] = {"name": "", "arguments": ""}
                            if tc.get("function", {}).get("name"):
                                tool_call_buffers[idx]["name"] = tc["function"]["name"]
                            if tc.get("function", {}).get("arguments"):
                                tool_call_buffers[idx]["arguments"] += tc["function"]["arguments"]

                    # Capture text content
                    text = delta.get("content", "")
                    if text:
                        raw_content_parts.append(text)
                        initial_text_chunks.append(StreamChunk(text=text, done=False))

                    # Check finish_reason for tool calls — THIS signals completion
                    finish_reason = choice.get("finish_reason", "")
                    if finish_reason == "tool_calls":
                        tool_call_detected = True
                        phase1_done = True  # Tool call is complete, stop reading
                        break

                except (json.JSONDecodeError, IndexError, KeyError):
                    continue

                # Decision point: if we've seen text and no tool_call so far,
                # check if the text contains MiniMax's proprietary tool_call format
                # before deciding this is a plain text response. MiniMax outputs
                # tool calls as text content in the format:
                #   minimax:tool_call <invoke name="TOOL">...</invoke> </minimax:tool_call>
                # If we find this pattern, we should NOT break out of Phase 1
                # — instead, continue reading to get the complete tool call text.
                #
                # v8.2 fix: MiniMax sometimes outputs a text prefix (e.g., "Searching the web")
                # BEFORE the minimax:tool_call XML. The previous check at chunks_read >= 4
                # would break too early if the text prefix consumed the first 4 chunks.
                # Now we:
                # 1. Use a larger detection window (15 chunks instead of 4)
                # 2. Check for both the full pattern AND the "minimax:tool_call" prefix
                #    (partial match) — if we see even the start of a tool call, keep reading
                # 3. After 15 chunks with no sign of tool calling, break confidently
                if not tool_call_detected and initial_text_chunks and chunks_read >= 4:
                    _full_text_so_far = "".join(raw_content_parts)
                    _mm_full_check = re.search(
                        r'minimax:tool_call\s*<invoke\s+name=["\']\w+["\']',
                        _full_text_so_far,
                        re.IGNORECASE,
                    )
                    _mm_prefix_check = "minimax:tool_call" in _full_text_so_far.lower()
                    if _mm_full_check:
                        # Full MiniMax tool call pattern detected — don't break,
                        # continue reading to get the complete call
                        logger.info("[adapter] MiniMax tool_call pattern detected in Phase 1 text — continuing to read")
                    elif _mm_prefix_check:
                        # Partial "minimax:tool_call" prefix detected — the full
                        # <invoke> tag hasn't arrived yet. Keep reading.
                        logger.info(
                            "[adapter] MiniMax tool_call prefix detected in Phase 1 — continuing to read for full pattern"
                        )
                    elif chunks_read >= 15:
                        # Read enough chunks with no tool call sign — this is text
                        phase1_done = True
                        break
                    # else: chunks_read < 15, keep reading to be sure

            # ── Phase 2a: Tool call detected ──────────────────────────────
            # Continue reading to collect full tool call arguments, then
            # return ToolCallResult.
            if tool_call_detected:
                # Drain remaining lines to get full tool call args
                if not phase1_done:
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                            choice = obj.get("choices", [{}])[0]
                            delta = choice.get("delta", {})
                            if "tool_calls" in delta:
                                for tc in delta["tool_calls"]:
                                    idx = tc.get("index", 0)
                                    if idx not in tool_call_buffers:
                                        tool_call_buffers[idx] = {"name": "", "arguments": ""}
                                    if tc.get("function", {}).get("name"):
                                        tool_call_buffers[idx]["name"] = tc["function"]["name"]
                                    if tc.get("function", {}).get("arguments"):
                                        tool_call_buffers[idx]["arguments"] += tc["function"]["arguments"]
                            text = delta.get("content", "")
                            if text:
                                raw_content_parts.append(text)
                            finish_reason = choice.get("finish_reason", "")
                            if finish_reason == "tool_calls":
                                # Tool call complete — stop reading
                                break
                        except (json.JSONDecodeError, IndexError, KeyError):
                            continue

                await response.aclose()

                if tool_call_buffers:
                    first_idx = sorted(tool_call_buffers.keys())[0]
                    buf = tool_call_buffers[first_idx]
                    raw_args = buf.get("arguments", "{}")
                    try:
                        tool_args = json.loads(raw_args) if raw_args else {}
                    except json.JSONDecodeError:
                        # v8.1: Enhanced logging for truncated tool args.
                        # The stream may have ended before the args were
                        # fully transmitted. Log the raw args for debugging
                        # and pass them through so the agent loop can
                        # detect the malformed args and retry.
                        logger.warning(
                            "[adapter] tool args not valid JSON (possibly truncated). Raw args (%d chars): %s",
                            len(raw_args),
                            raw_args[:300],
                        )
                        # Try to extract partial args using a lenient parser
                        # Some providers emit valid key-value pairs but with
                        # truncated string values — we can still extract the
                        # tool name and partial params.
                        tool_args = {"_raw_arguments": raw_args}
                        # Attempt a simple key-value extraction for common params
                        import re as _re

                        for _key in ("path", "command", "query", "code", "content", "description"):
                            _m = _re.search(rf'"{_key}"\s*:\s*"([^"]*)', raw_args)
                            if _m:
                                tool_args[_key] = _m.group(1)

                    if len(tool_call_buffers) > 1:
                        extra = [tool_call_buffers[i]["name"] for i in sorted(tool_call_buffers.keys())[1:]]
                        logger.warning(
                            "[adapter] %d tool calls; using first (%s), extra: %s",
                            len(tool_call_buffers),
                            buf["name"],
                            extra,
                        )

                    from adapters.ollama import ToolCallResult

                    return ToolCallResult(
                        tool_name=buf["name"],
                        tool_args=tool_args,
                        raw_content="".join(raw_content_parts),
                    )

                # Tool call detected but no buffers parsed — treat as text
                # (fall through to Phase 2b)

            # ── MiniMax proprietary format detection ─────────────────────
            # MiniMax M2.5 Free sometimes outputs tool calls as text in the
            # format: minimax:tool_call <invoke name="TOOL"> <parameter
            # name="param">value</parameter> </invoke> </minimax:tool_call>
            # This is NOT the standard OpenAI tool_calls delta format. We need
            # to detect this pattern in the accumulated text and convert it to
            # a proper ToolCallResult so the agent loop can execute the tool.
            full_initial_text = "".join(raw_content_parts)
            _MINIMAX_TC_RE = re.compile(
                r'minimax:tool_call\s*<invoke\s+name=["\'](\w+)["\']>(.*?)</invoke>\s*</minimax:tool_call>',
                re.DOTALL | re.IGNORECASE,
            )
            _minimax_match = _MINIMAX_TC_RE.search(full_initial_text)
            if _minimax_match:
                _mm_tool_name = _minimax_match.group(1)
                _mm_params_xml = _minimax_match.group(2)
                # Normalize tool name to lowercase — MiniMax outputs "SHELL"
                # but the tool registry expects "shell"
                _mm_tool_name = _mm_tool_name.lower()
                # Parse <parameter name="key">value</parameter> from the XML
                _mm_args = {}
                _PARAM_RE = re.compile(
                    r'<parameter\s+name=["\']([^"\']+)["\']>([^<]*)</parameter>',
                    re.DOTALL,
                )
                for _pm in _PARAM_RE.finditer(_mm_params_xml):
                    _mm_args[_pm.group(1)] = _pm.group(2).strip()
                logger.info(
                    "[adapter] MiniMax proprietary tool_call detected: %s args=%s",
                    _mm_tool_name,
                    list(_mm_args.keys()),
                )
                await response.aclose()
                from adapters.ollama import ToolCallResult

                return ToolCallResult(
                    tool_name=_mm_tool_name,
                    tool_args=_mm_args,
                    raw_content=full_initial_text,
                )

            # ── Phase 2b: Text response — stream directly from HTTP ──────
            # Return an async generator that yields the initial buffered text
            # and then continues reading from the still-open HTTP stream.
            # The generator closes the response when exhausted.
            _initial = initial_text_chunks
            _resp = response
            _raw_parts = list(raw_content_parts)  # snapshot for JSON fallback
            _tool_names = tool_names  # captured for mid-stream detection

            async def _stream_from_http() -> AsyncIterator[StreamChunk]:
                """Yield text chunks directly from the live HTTP stream.

                Bug C fix: Some providers send empty content deltas as
                keepalives (delta.content = ""). These should not block the
                stream — we simply skip them without yielding, and continue
                reading. Previously this was handled implicitly (the `if text:`
                check skipped empty strings), but the fix makes this explicit
                and also ensures we don't accidentally treat a keepalive as
                an error or end-of-stream signal.

                v8.2 fix: MiniMax tool_call XML leak prevention. MiniMax sometimes
                outputs tool calls as text content (minimax:tool_call <invoke...>)
                which should NEVER be shown to the user. We filter these patterns
                from the text stream before yielding chunks to the caller.
                """
                full_text_parts = list(_raw_parts)
                json_tool_checked = False
                minimax_checked = False

                # v8.2: Pre-compiled patterns for filtering MiniMax tool call XML
                # from the text stream. These patterns match the proprietary format
                # that MiniMax uses when it doesn't use native tool calling.
                _mm_full_pattern = re.compile(
                    r'minimax:tool_call\s*<invoke\s+name=["\'][^"\']+["\']\s*>.*?</invoke>\s*</minimax:tool_call>',
                    re.DOTALL | re.IGNORECASE,
                )
                _mm_prefix_pattern = re.compile(
                    r"minimax:tool_call\s*<invoke[^>]*>.*?</invoke>",
                    re.DOTALL | re.IGNORECASE,
                )
                # Also match just the opening "minimax:tool_call" tag as a prefix
                _mm_tag_prefix = re.compile(
                    r"minimax:tool_call\b",
                    re.IGNORECASE,
                )

                try:
                    # Yield the initial text accumulated during Phase 1
                    # v8.2: Filter MiniMax tool_call XML from initial text
                    for chunk in _initial:
                        filtered_text = _mm_full_pattern.sub("", chunk.text)
                        filtered_text = _mm_prefix_pattern.sub("", filtered_text)
                        filtered_text = _mm_tag_prefix.sub("", filtered_text)
                        if filtered_text:
                            yield StreamChunk(text=filtered_text, done=False)

                    # Continue reading from the still-open stream
                    if not phase1_done:
                        async for line in _resp.aiter_lines():
                            if not line or not line.startswith("data: "):
                                # Empty lines or non-data lines are SSE
                                # keepalives — skip them but keep reading.
                                continue
                            data = line[6:]
                            if data == "[DONE]":
                                break

                            try:
                                obj = json.loads(data)
                                delta = obj.get("choices", [{}])[0].get("delta", {})
                                text = delta.get("content", "")
                                # Bug C fix: explicitly handle empty content deltas.
                                # Some providers send delta.content="" as keepalives.
                                # These are not errors — just skip and continue.
                                if text:
                                    # v8.2: Filter MiniMax tool_call XML from streaming text.
                                    # This prevents the proprietary format from being shown to
                                    # the user. The model should use native tool calling, but
                                    # when it falls back to text-format tool calls, we strip them.
                                    filtered_text = _mm_full_pattern.sub("", text)
                                    filtered_text = _mm_prefix_pattern.sub("", filtered_text)
                                    filtered_text = _mm_tag_prefix.sub("", filtered_text)
                                    if not filtered_text:
                                        # The entire chunk was a tool call tag — skip it
                                        full_text_parts.append(text)
                                        continue
                                    full_text_parts.append(text)
                                    yield StreamChunk(text=filtered_text, done=False)

                                    # One-time MiniMax proprietary format check.
                                    # MiniMax may send its tool_call as text
                                    # content mid-stream after initial text.
                                    if not minimax_checked and len("".join(full_text_parts)) > 60:
                                        minimax_checked = True
                                        _full_so_far = "".join(full_text_parts)
                                        _mm_re = re.compile(
                                            r'minimax:tool_call\s*<invoke\s+name=["\'](\w+)["\']>(.*?)</invoke>\s*</minimax:tool_call>',
                                            re.DOTALL | re.IGNORECASE,
                                        )
                                        _mm_m = _mm_re.search(_full_so_far)
                                        if _mm_m:
                                            # MiniMax tool call found mid-stream.
                                            # We can't un-send the text already
                                            # yielded, but we log it for debugging.
                                            logger.info(
                                                "[adapter] MiniMax tool_call detected mid-stream (after text already sent): %s",
                                                _mm_m.group(1),
                                            )

                                    # One-time JSON tool fallback check after
                                    # accumulating enough text. This handles
                                    # providers that don't support structured
                                    # tool calling.
                                    if not json_tool_checked and len("".join(full_text_parts)) > 80:
                                        json_tool_checked = True
                                        full_so_far = "".join(full_text_parts)
                                        _JSON_TOOL_RE = re.compile(
                                            r'```json\s*\n?\s*(\{[^`]*?"tool"\s*:\s*"[^"]+?"[^}]*\})\s*\n?\s*```',
                                            re.DOTALL,
                                        )
                                        json_match = _JSON_TOOL_RE.search(full_so_far)
                                        if json_match:
                                            try:
                                                tool_json = json.loads(json_match.group(1))
                                                tn = tool_json.get("tool", "")
                                                if tn and tn in {t["function"]["name"] for t in tools}:
                                                    # Found a JSON tool call —
                                                    # can't un-send text, but log it
                                                    logger.info(
                                                        "[adapter] JSON tool call found mid-stream: %s",
                                                        tn,
                                                    )
                                            except (json.JSONDecodeError, KeyError):
                                                pass
                                # else: empty content delta (keepalive) — skip, continue reading

                            except (json.JSONDecodeError, IndexError, KeyError):
                                continue

                    yield StreamChunk(text="", done=True)
                finally:
                    await _resp.aclose()

            return _stream_from_http()

        except httpx.ConnectError:
            msg = f"Cannot connect to {self._provider_name} at {self._base_url}. Check your network and API endpoint."
            logger.error(msg)

            async def _error_iter():
                yield StreamChunk(text="", done=True, error=msg)

            return _error_iter()

        except httpx.TimeoutException:
            msg = f"{self._provider_name} timed out after {timeout}s. The request may be too large for the context window."
            logger.error(msg)

            async def _error_iter():
                yield StreamChunk(text="", done=True, error=msg)

            return _error_iter()

        except Exception as e:
            msg = f"Unexpected error calling {self._provider_name}: {e}"
            logger.error(msg)

            async def _error_iter():
                yield StreamChunk(text="", done=True, error=msg)

            return _error_iter()

    async def _chat_openai_style(
        self,
        messages: list[dict],
        temperature: float,
        timeout: int,
    ) -> AsyncIterator[StreamChunk]:
        """Handle OpenAI-style APIs (OpenAI, OpenRouter, DeepSeek, LiteLLM)."""
        url = f"{self._base_url}/chat/completions"
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }

        try:
            async with self._client.stream(
                "POST", url, json=payload, headers=self._headers, timeout=timeout
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    error_msg = (
                        f"{self._provider_name} returned {response.status_code}: {body.decode(errors='replace')[:200]}"
                    )
                    logger.error(error_msg)
                    yield StreamChunk(text="", done=True, error=error_msg)
                    return

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        yield StreamChunk(text="", done=True)
                        return

                    try:
                        obj = json.loads(data)
                        delta = obj.get("choices", [{}])[0].get("delta", {})
                        text = delta.get("content", "")
                        if text:
                            yield StreamChunk(text=text, done=False)
                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue

        except httpx.ConnectError:
            msg = f"Cannot connect to {self._provider_name} at {self._base_url}. Check your network and API endpoint."
            logger.error(msg)
            yield StreamChunk(text="", done=True, error=msg)
        except httpx.TimeoutException:
            msg = f"{self._provider_name} timed out after {timeout}s. The request may be too large for the context window."
            logger.error(msg)
            yield StreamChunk(text="", done=True, error=msg)
        except Exception as e:
            msg = f"Unexpected error calling {self._provider_name}: {e}"
            logger.error(msg)
            yield StreamChunk(text="", done=True, error=msg)

    async def _chat_anthropic(
        self,
        messages: list[dict],
        temperature: float,
        timeout: int,
    ) -> AsyncIterator[StreamChunk]:
        """Handle Anthropic's API (different format from OpenAI)."""
        url = f"{self._base_url}/messages"

        # Convert messages to Anthropic format
        # Anthropic uses "system" as a separate field, not in messages
        system_messages = [m for m in messages if m.get("role") == "system"]
        non_system_messages = [m for m in messages if m.get("role") != "system"]

        system_content = ""
        if system_messages:
            system_content = system_messages[0].get("content", "")

        # Build Anthropic message format
        anthropic_messages = []
        for m in non_system_messages:
            role = "assistant" if m.get("role") == "assistant" else "user"
            anthropic_messages.append(
                {
                    "role": role,
                    "content": m.get("content", ""),
                }
            )

        payload = {
            "model": self._model,
            "messages": anthropic_messages,
            "max_tokens": 4096,
            "temperature": temperature,
            "stream": True,
        }
        if system_content:
            payload["system"] = system_content

        try:
            async with self._client.stream(
                "POST", url, json=payload, headers=self._headers, timeout=timeout
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    error_msg = f"Anthropic returned {response.status_code}: {body.decode(errors='replace')[:200]}"
                    logger.error(error_msg)
                    yield StreamChunk(text="", done=True, error=error_msg)
                    return

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        yield StreamChunk(text="", done=True)
                        return

                    try:
                        obj = json.loads(data)
                        # Anthropic uses "content" array instead of delta
                        content = obj.get("content", [])
                        for block in content:
                            if block.get("type") == "text":
                                text = block.get("text", "")
                                if text:
                                    yield StreamChunk(text=text, done=False)
                    except (json.JSONDecodeError, KeyError):
                        continue

        except httpx.ConnectError:
            msg = f"Cannot connect to Anthropic at {self._base_url}. Check your network."
            logger.error(msg)
            yield StreamChunk(text="", done=True, error=msg)
        except httpx.TimeoutException:
            msg = f"Anthropic timed out after {timeout}s."
            logger.error(msg)
            yield StreamChunk(text="", done=True, error=msg)
        except Exception as e:
            msg = f"Unexpected error calling Anthropic: {e}"
            logger.error(msg)
            yield StreamChunk(text="", done=True, error=msg)

    # ─────────────────────────────────────────────────────────────────────
    # Model management
    # ─────────────────────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """Return True if the provider endpoint is reachable."""
        try:
            if self._provider_name == "anthropic":
                # Anthropic doesn't have a simple /models endpoint,
                # use a minimal message to check connectivity
                response = await self._client.post(
                    f"{self._base_url}/messages",
                    json={
                        "model": self._model,
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 1,
                    },
                    headers=self._headers,
                    timeout=10,
                )
                return response.status_code in (
                    200,
                    400,
                )  # 400 means auth worked but invalid request
            else:
                response = await self._client.get(
                    f"{self._base_url}/models",
                    headers=self._headers,
                    timeout=10,
                )
                return response.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """Return list of available models for this provider."""
        try:
            if self._provider_name == "anthropic":
                # Anthropic returns models in a different format
                # Use a simple approach: return the configured model + known variants
                return [
                    "claude-sonnet-4-20250514",
                    "claude-3-5-sonnet-20241022",
                    "claude-3-5-sonnet-20240620",
                    "claude-3-opus-20240229",
                    "claude-3-sonnet-20240229",
                    "claude-3-haiku-20240307",
                    "claude-3-5-haiku-20241022",
                ]
            else:
                response = await self._client.get(
                    f"{self._base_url}/models",
                    headers=self._headers,
                    timeout=15,
                )
                data = response.json()
                return [m.get("id") for m in data.get("data", [])]
        except Exception as e:
            logger.warning(f"Failed to list models for {self._provider_name}: {e}")
            return [self._model]  # Fallback to current model

    # ─────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Gracefully close the HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "OpenAICompatAdapter":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
