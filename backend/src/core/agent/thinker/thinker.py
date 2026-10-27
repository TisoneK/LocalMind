"""The Thinker — a read-only mid-loop analyst.

Given the evidence the agent has gathered, it reasons and returns a
structured `ThinkerAnalysis` the agent acts on.

The visible reasoning IS the model's reasoning: the consult streams the
adapter's native thinking channel verbatim — the same channel the main
loop streams — and nothing else. The text channel carries only the JSON
decision block and is never surfaced. A thought the model was told to
author for an audience is a performance, and a performance is not shown:
the harness this design was checked against records the model's per-step
reasoning faithfully and has no component that writes thinking-shaped
prose on demand, and the consult now matches that honesty. An empty
ThinkingBlock during a consult (a provider that ships no reasoning
channel) is the truthful state — the decision still lands.

It calls the model's plain `chat` (no tools — it decides nothing, executes
nothing) and is bounded by a dedicated reasoning timeout so a slow/free
model can't hang the turn.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Optional

from core.models import StreamChunk

from .contract import Evidence, ThinkerAnalysis
from .parse import parse_thinker_analysis
from .prompt import build_thinker_messages

logger = logging.getLogger(__name__)


class Thinker:
    """Reason on gathered evidence and produce a structured analysis.

    Usage (streaming, for the loop):
        async for _chunk in thinker.consult(evidence, adapter):
            if _chunk.thinking:
                ...  # the model's native reasoning — forward to the ThinkingBlock
            if _chunk.done:
                analysis = thinker.last_analysis
    """

    def __init__(self, timeout_secs: float = 30.0) -> None:
        self._timeout = timeout_secs
        self.last_analysis: Optional[ThinkerAnalysis] = None

    async def consult(
        self,
        evidence: Evidence,
        adapter,
        temperature: float = 0.4,
    ) -> AsyncIterator[StreamChunk]:
        """Run a consult, streaming the model's native reasoning live.

        Whatever arrives on the thinking channel is yielded verbatim as it
        arrives — real reasoning, unfiltered (the loop's
        `_filter_system_leaks` stays the second layer against prompt
        echoes). The text channel is buffered and never yielded: it is the
        decision payload, not a thought. The parsed analysis is stashed on
        `self.last_analysis` and on the final chunk's metadata. Bounded by
        the reasoning timeout — a timeout yields whatever reasoning arrived
        plus an empty-but-safe analysis so the loop proceeds on its own
        next step."""
        self.last_analysis = None
        messages = build_thinker_messages(evidence)

        reasoning: list[str] = []  # the thinking channel — shown, verbatim
        payload: list[str] = []  # the text channel — the JSON decision, never shown
        try:
            stream = adapter.chat(messages, temperature=temperature, intent="analyze")
            async for chunk in _with_timeout(stream, self._timeout):
                if getattr(chunk, "error", None):
                    logger.warning("[thinker] provider error during consult: %s", chunk.error)
                    break
                if chunk.thinking:
                    reasoning.append(chunk.thinking)
                    yield StreamChunk(text="", thinking=chunk.thinking, done=False)
                if chunk.text:
                    payload.append(chunk.text)
        except asyncio.TimeoutError:
            logger.warning("[thinker] consult timed out after %.0fs — proceeding without analysis", self._timeout)
        except Exception as exc:  # never let a consult crash the turn
            logger.warning("[thinker] consult failed: %s — proceeding without analysis", exc)

        analysis = parse_thinker_analysis("".join(payload), reasoning="".join(reasoning))
        self.last_analysis = analysis
        yield StreamChunk(text="", done=True, metadata={"thinker_analysis": analysis.to_dict()})

    async def analyze(self, evidence: Evidence, adapter, temperature: float = 0.4) -> ThinkerAnalysis:
        """Non-streaming convenience: run the consult and return the analysis."""
        async for _ in self.consult(evidence, adapter, temperature=temperature):
            pass
        return self.last_analysis or ThinkerAnalysis()


async def _with_timeout(stream: AsyncIterator[StreamChunk], timeout: float) -> AsyncIterator[StreamChunk]:
    """Wrap an async stream with a per-consult wall-clock timeout."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + max(1.0, timeout)
    agen = stream.__aiter__()
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise asyncio.TimeoutError
        try:
            chunk = await asyncio.wait_for(agen.__anext__(), timeout=remaining)
        except StopAsyncIteration:
            return
        yield chunk
