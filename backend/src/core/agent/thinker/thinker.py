"""The Thinker — the agent's reasoning backbone (ADR-42).

A SILENT, read-only mid-loop analyst. Given the evidence the agent has
gathered, it reasons and returns a structured `ThinkerAnalysis` the agent
acts on. Nothing it produces is surfaced to the user: the loop injects the
structured analysis into the agent's context and reports the lifecycle via
`agent_thinker_start`/`agent_thinker_done` obs events, but the raw monologue
stays internal. (Session 324 — the user's spec: the Thinker's private
reasoning used to render into the ThinkingBlock on every model because no
filter-before-render step existed; the model's prompt echoes — "You are the
Thinker… SILENT and READ-ONLY" — and its JSON-format musing leaked into the
visible transcript.) It calls the model's plain `chat` (no tools — it
decides nothing, executes nothing) and is bounded by a dedicated reasoning
timeout so a slow/free model can't hang the turn.
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
        """Run a SILENT consult. The model's reasoning is buffered internally
        for parsing only — no `thinking` chunk is ever yielded, so the loop
        cannot forward it to the user. The parsed analysis is stashed on
        `self.last_analysis` and on the final chunk's metadata. Bounded by the
        reasoning timeout — a timeout yields whatever arrived plus an
        empty-but-safe analysis so the loop proceeds on its own next step."""
        self.last_analysis = None
        messages = build_thinker_messages(evidence)

        buf: list[str] = []
        try:
            stream = adapter.chat(messages, temperature=temperature, intent="analyze")
            async for chunk in _with_timeout(stream, self._timeout):
                if getattr(chunk, "error", None):
                    logger.warning("[thinker] provider error during consult: %s", chunk.error)
                    break
                piece = (chunk.text or "") + (chunk.thinking or "")
                if piece:
                    buf.append(piece)
        except asyncio.TimeoutError:
            logger.warning("[thinker] consult timed out after %.0fs — proceeding without analysis", self._timeout)
        except Exception as exc:  # never let a consult crash the turn
            logger.warning("[thinker] consult failed: %s — proceeding without analysis", exc)

        analysis = parse_thinker_analysis("".join(buf))
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
