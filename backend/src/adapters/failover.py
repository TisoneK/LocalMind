"""Provider failover: a model provider's limits are the agent's problem, not the user's.

A rate limit, an exhausted quota, an overloaded or unreachable provider used to end the turn
with an error card. Every one of those is recoverable when another configured provider can
answer, so `FailoverAdapter` wraps the turn's adapter and, when a call fails BEFORE producing
anything, moves on to the next candidate (the connection's `fallback_to`, then every other
provider that has a key) and carries on. The user only sees an error when every candidate has
failed.

`ProviderHealth` remembers what is down and for how long, so the next turn (and the next call
in the same turn) skips a provider that just rate-limited us instead of paying for it again.

Failover is only safe before the first token: once text has streamed, a swap would splice two
models' replies together, so a mid-stream error passes through untouched.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, AsyncIterator, Callable

from core.error_normalizer import (
    AUTH_ERROR,
    CONTEXT_OVERFLOW,
    MODEL_NOT_FOUND,
    NETWORK_ERROR,
    PAYMENT_REQUIRED,
    RATE_LIMIT,
    SERVER_ERROR,
    TIMEOUT,
    normalize_error,
)
from core.models import StreamChunk

logger = logging.getLogger(__name__)

# How long a provider is skipped after each kind of failure. Quota and credentials do not fix
# themselves in a minute; a burst limit or a blip does.
_COOLDOWN_SECONDS: dict[str, float] = {
    RATE_LIMIT: 60.0,
    PAYMENT_REQUIRED: 900.0,
    AUTH_ERROR: 900.0,
    MODEL_NOT_FOUND: 900.0,
    SERVER_ERROR: 30.0,
    NETWORK_ERROR: 20.0,
    TIMEOUT: 20.0,
}
# A failure the next provider cannot fix: the conversation itself is the problem.
_NOT_A_PROVIDER_PROBLEM = {CONTEXT_OVERFLOW}
_MAX_FALLBACKS = 3
# Longest a lone provider is waited on: past this, saying so beats a hang the user cannot cancel.
_MAX_WAIT_SECONDS = 15.0
_MAX_COOLDOWN_SECONDS = 900.0

# What each failure means, in the words the user sees while the agent works around it.
_PROBLEM_PHRASE: dict[str, str] = {
    RATE_LIMIT: "is busy",
    PAYMENT_REQUIRED: "is out of quota",
    AUTH_ERROR: "rejected the key",
    MODEL_NOT_FOUND: "doesn't have that model",
    SERVER_ERROR: "is having trouble",
    NETWORK_ERROR: "isn't reachable",
    TIMEOUT: "is too slow to answer",
}


def retry_window_seconds(error: Any) -> float | None:
    """Seconds the provider said to wait ("Retry-After", "retry in 12s"), when the error says."""
    from adapters.openai_compat import OpenAICompatAdapter

    return OpenAICompatAdapter._parse_retry_delay_seconds(str(error or ""), None)


class ProviderHealth:
    """Which providers are cooling down, process-wide."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._down_until: dict[str, float] = {}
        # The provider a call is being sent to right now (cosmetic: names the wait for the user).
        self.trying: str = ""
        self._reason: dict[str, str] = {}

    def mark_down(self, provider: str, code: str, window: float | None = None) -> None:
        """Skip `provider` for the window it named, else the default for this kind of failure."""
        cooldown = _COOLDOWN_SECONDS.get(code, 30.0)
        if window is not None and window > 0:
            cooldown = min(window + 1.0, _MAX_COOLDOWN_SECONDS)
        self._down_until[provider] = self._clock() + cooldown
        self._reason[provider] = code

    def mark_up(self, provider: str) -> None:
        self._down_until.pop(provider, None)
        self._reason.pop(provider, None)

    def is_down(self, provider: str) -> bool:
        until = self._down_until.get(provider)
        if until is None:
            return False
        if self._clock() >= until:
            self.mark_up(provider)
            return False
        return True

    def snapshot(self) -> dict[str, dict[str, Any]]:
        now = self._clock()
        return {
            p: {"reason": self._reason.get(p, ""), "retry_in": round(u - now, 1)}
            for p, u in self._down_until.items()
            if u > now
        }

    def clear(self) -> None:
        self._down_until.clear()
        self._reason.clear()


_health = ProviderHealth()


def get_provider_health() -> ProviderHealth:
    return _health


def _failure_code(error: Any) -> str:
    return normalize_error(error)["code"]


def fallback_candidates(primary: str) -> list[tuple[str, str]]:
    """Ordered `(provider, model)` pairs to try after `primary`, best first.

    The connection's own `fallback_to` comes first (the user's explicit choice); then any other
    provider that has an API key. Models are the providers' defaults (empty override).
    """
    from core.config import settings
    from core.connections import get_connection_registry

    registry = get_connection_registry()
    out: list[str] = []
    connection = registry.get(primary)
    chosen = getattr(connection, "fallback_to", "") if connection else ""
    if chosen and chosen != primary and registry.get(chosen) is not None:
        out.append(chosen)
    # A local model's failure must never ship the conversation to a cloud provider the user did
    # not choose: only an explicit fallback applies.
    if primary == "ollama" or (connection is not None and connection.kind == "ollama"):
        return [(cid, "") for cid in out]
    for cid in registry.ids():
        if cid == primary or cid in out or cid == "ollama":
            continue
        conn = registry.get(cid)
        if conn is None or not conn.enabled or conn.kind != "openai-compat":
            continue
        if settings.get_api_key(cid):
            out.append(cid)
    return [(cid, "") for cid in out]


class FailoverAdapter:
    """Wraps a turn's adapter; on a pre-output provider failure, tries the next candidate."""

    def __init__(
        self,
        primary: Any,
        primary_name: str,
        *,
        candidates: Callable[[str], list[tuple[str, str]]] = fallback_candidates,
        make_adapter: Callable[[str, str], Any] | None = None,
        health: ProviderHealth | None = None,
        retry_delays: tuple[float, ...] = (1.5, 4.0),
    ):
        self._primary = primary
        self._primary_name = primary_name
        self._candidates = candidates
        self._make_adapter = make_adapter or _default_make_adapter
        self._health = health or _health
        self._retry_delays = retry_delays
        # Set to the provider name that ended up serving the last call, for diagnostics.
        self.last_served_by = primary_name
        # Plain-language progress for the user ("X is busy — switching to Y"). The agent loop
        # drains this while the model call is in flight, so it is seen DURING the wait.
        self.status_queue: asyncio.Queue[str] = asyncio.Queue()

    def _say(self, text: str) -> None:
        self.status_queue.put_nowait(text)

    @staticmethod
    def _label(name: str) -> str:
        try:
            from core.connections import get_connection_registry

            conn = get_connection_registry().get(name)
            full = (conn.name if conn else "") or name
            # "BankOfAI (promo free models — time-limited)" is a description, not a name.
            return re.split(r"\s+[(—–-]", full, maxsplit=1)[0].strip() or name
        except Exception:
            return name

    def __getattr__(self, name: str):
        return getattr(self._primary, name)

    # ── plumbing ────────────────────────────────────────────────────────────────────

    def _chain(self) -> list[tuple[str, Any]]:
        """Primary first (unless cooling down), then fallbacks; adapters built lazily."""
        chain: list[tuple[str, Any]] = []
        if not self._health.is_down(self._primary_name):
            chain.append((self._primary_name, self._primary))
        try:
            extras = self._candidates(self._primary_name)
        except Exception:
            logger.debug("[failover] candidate lookup failed", exc_info=True)
            extras = []
        for name, model in extras[:_MAX_FALLBACKS]:
            if self._health.is_down(name):
                continue
            try:
                chain.append((name, self._make_adapter(name, model)))
            except Exception:
                logger.debug("[failover] cannot build adapter for %s", name, exc_info=True)
        if not chain:
            # Everything is cooling down: better to try the primary than to fail without trying.
            chain.append((self._primary_name, self._primary))
        return chain

    async def _try_stream(self, stream: AsyncIterator[StreamChunk]):
        """Peek the first chunk. Returns (ok, replay_iterator | error_text, raised)."""
        try:
            first = await stream.__anext__()
        except StopAsyncIteration:
            return True, _empty(), False
        except Exception as exc:  # the adapter raised instead of yielding an error chunk
            return False, str(exc) or exc.__class__.__name__, True
        if getattr(first, "error", None) and not getattr(first, "text", ""):
            return False, first.error, False
        return True, _prepend(first, stream), False

    async def _countdown(self, name: str, code: str, seconds: float) -> None:
        """Wait `seconds`, telling the user what is being waited for, once a second."""
        label, phrase = self._label(name), _PROBLEM_PHRASE.get(code, "is unavailable")
        remaining = seconds
        while remaining > 0:
            self._say(f"{label} {phrase} — retrying in {max(1, round(remaining))}s")
            step = min(1.0, remaining)
            await asyncio.sleep(step)
            remaining -= step

    async def _run(self, call: Callable[[Any], Any]):
        """Run `call(adapter)` down the chain until one candidate produces output."""
        chain = self._chain()
        last_error = ""
        switched = False  # a candidate failed during THIS call, so the user was told about a switch
        single = len(chain) == 1
        for idx, (name, adapter) in enumerate(chain):
            attempt = 0
            while True:
                self._health.trying = name
                try:
                    result = call(adapter)
                    if asyncio.iscoroutine(result):
                        result = await result
                except Exception as exc:
                    ok, payload, raised = False, str(exc) or exc.__class__.__name__, True
                else:
                    if hasattr(result, "__anext__"):
                        ok, payload, raised = await self._try_stream(result)
                    else:
                        ok, payload, raised = True, result, False  # ToolCallResult / MultiToolCallResult
                if ok:
                    self._health.mark_up(name)
                    if name != self._primary_name:
                        logger.warning("[failover] %s unavailable — served by %s", self._primary_name, name)
                        if switched:
                            self._say(f"Continuing with {self._label(name)}")
                    self.last_served_by = name
                    return payload
                code = _failure_code(payload)
                if raised and code not in _COOLDOWN_SECONDS and code not in _NOT_A_PROVIDER_PROBLEM:
                    code = NETWORK_ERROR  # an exception, not a provider reply: the transport failed
                last_error = payload
                if code in _NOT_A_PROVIDER_PROBLEM or code not in _COOLDOWN_SECONDS:
                    # Not something another provider can fix: surface it as it is.
                    return _error_stream(payload)
                window = retry_window_seconds(payload) if code == RATE_LIMIT else None
                waitable = code not in (AUTH_ERROR, PAYMENT_REQUIRED, MODEL_NOT_FOUND)
                if single and waitable:
                    # Nothing to switch to: wait the time the provider asked for (or back off).
                    if window is not None:
                        wait = window if window <= _MAX_WAIT_SECONDS and attempt < 2 else None
                    else:
                        wait = self._retry_delays[attempt] if attempt < len(self._retry_delays) else None
                    if wait is not None:
                        await self._countdown(name, code, wait)
                        attempt += 1
                        continue
                self._health.mark_down(name, code, window)
                more = idx + 1 < len(chain)
                logger.warning("[failover] %s failed (%s)%s", name, code, "; trying next" if more else "")
                if more:
                    switched = True
                    self._say(
                        f"{self._label(name)} {_PROBLEM_PHRASE.get(code, 'is unavailable')} "
                        f"— switching to {self._label(chain[idx + 1][0])}"
                    )
                break
        return _error_stream(last_error)

    # ── the adapter surface the loop uses ───────────────────────────────────────────

    async def chat(self, messages, temperature: float = 0.7, **kwargs):
        # Run the recovery as a task so its progress ("X is busy — switching to Y") streams out
        # as status chunks while it is still happening, not after.
        task = asyncio.ensure_future(self._run(lambda a: a.chat(messages, temperature=temperature, **kwargs)))
        try:
            while not task.done():
                try:
                    line = await asyncio.wait_for(self.status_queue.get(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                yield StreamChunk(text="", status=line)
            while not self.status_queue.empty():
                yield StreamChunk(text="", status=self.status_queue.get_nowait())
        except BaseException:
            task.cancel()
            raise
        async for chunk in task.result():
            yield chunk

    async def chat_with_tools(self, messages, tools, temperature=0.7, intent="chat", tool_choice=None):
        def call(adapter):
            fn = getattr(adapter, "chat_with_tools", None)
            if fn is None:
                return adapter.chat(messages, temperature=temperature, intent=intent)
            return fn(messages, tools, temperature=temperature, intent=intent, tool_choice=tool_choice)

        return await self._run(call)


def _default_make_adapter(name: str, model: str):
    from adapters import get_adapter

    return get_adapter(name, model_override=model)


async def _empty():
    return
    yield  # pragma: no cover  (makes this an async generator)


async def _prepend(first: StreamChunk, rest: AsyncIterator[StreamChunk]):
    yield first
    async for chunk in rest:
        yield chunk


async def _error_stream(error: str):
    yield StreamChunk(text="", error=error, done=True)
