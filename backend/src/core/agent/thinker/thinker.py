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


class _FenceSuppressor:
    """Drop fenced code blocks from a streamed reasoning channel, across
    chunk boundaries.

    The consult asks for EXACTLY ONE JSON object on the TEXT channel. A
    model that rehearses that JSON on the THINKING channel ("Let me
    structure this as a JSON response: ```json {…}```") turns the visible
    reasoning into a wall of half-written decision JSON (live export
    2026-11-02: the pre-tool consult's rehearsal filled the ThinkingBlock
    and persisted into the message's thinking). The deliberation AROUND a
    fence is real reasoning and stays verbatim; the fenced block is
    decision construction, not thought, and goes. An unclosed fence
    suppresses to the end of the stream — the honest reading of what the
    model was doing, and the decision itself was never on this channel.
    """

    _FENCE = "```"

    def __init__(self) -> None:
        self._in_fence = False
        # A trailing 1–2 char fragment that could be the head of a fence
        # marker split across chunks ("`", "``") — held until the next
        # chunk decides.
        self._pending = ""

    def feed(self, text: str) -> str:
        out: list[str] = []
        buf = self._pending + text
        self._pending = ""
        i = 0
        n = len(buf)
        while i < n:
            if buf.startswith(self._FENCE, i):
                i += 3
                if self._in_fence:
                    self._in_fence = False
                else:
                    self._in_fence = True
                    # Skip a short language tag on the same line ("json").
                    nl = buf.find("\n", i)
                    if 0 <= nl <= i + 12:
                        i = nl + 1
                continue
            if not self._in_fence and i >= n - 2 and buf[i:] in ("`", "``"):
                self._pending = buf[i:]
                break
            if not self._in_fence:
                out.append(buf[i])
            i += 1
        return "".join(out)

    def flush(self) -> str:
        """Emit a held fragment at stream end (it was never a fence)."""
        held, self._pending = self._pending, ""
        return held if not self._in_fence else ""


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

        Whatever arrives on the thinking channel is yielded as it arrives —
        real reasoning, verbatim, with one subtraction: fenced code blocks
        (a model rehearsing the JSON decision on the thinking channel) are
        stripped across chunk boundaries. The loop's
        `_filter_system_leaks` stays the second layer against prompt
        echoes. The text channel is buffered and never yielded: it is the
        decision payload, not a thought. The parsed analysis is stashed on
        `self.last_analysis` and on the final chunk's metadata. Bounded by
        the reasoning timeout — a timeout yields whatever reasoning arrived
        plus an empty-but-safe analysis so the loop proceeds on its own
        next step."""
        self.last_analysis = None
        messages = build_thinker_messages(evidence)

        reasoning: list[str] = []  # the thinking channel — shown, fence-stripped
        payload: list[str] = []  # the text channel — the JSON decision, never shown
        _fences = _FenceSuppressor()
        try:
            stream = adapter.chat(messages, temperature=temperature, intent="analyze")
            async for chunk in _with_timeout(stream, self._timeout):
                if getattr(chunk, "error", None):
                    logger.warning("[thinker] provider error during consult: %s", chunk.error)
                    break
                if chunk.thinking:
                    # The deliberation streams verbatim; a fenced JSON
                    # rehearsal of the decision does not (the decision lives
                    # on the text channel — this copy is construction noise
                    # in the visible reasoning, the 2026-11-02 mess).
                    shown = _fences.feed(chunk.thinking)
                    if shown:
                        reasoning.append(shown)
                        yield StreamChunk(text="", thinking=shown, done=False)
                if chunk.text:
                    payload.append(chunk.text)
        except asyncio.TimeoutError:
            logger.warning("[thinker] consult timed out after %.0fs — proceeding without analysis", self._timeout)
        except Exception as exc:  # never let a consult crash the turn
            logger.warning("[thinker] consult failed: %s — proceeding without analysis", exc)
        _tail = _fences.flush()
        if _tail:
            reasoning.append(_tail)
            yield StreamChunk(text="", thinking=_tail, done=False)

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
