"""The Thinker — the agent's reasoning backbone (ADR-42).

A silent, read-only mid-loop analyst. Given the evidence the agent has
gathered, it reasons (streamed live to the ThinkingBlock) and returns a
structured `ThinkerAnalysis` the agent acts on. It calls the model's plain
`chat` (no tools — it decides nothing, executes nothing) and is bounded by a
dedicated reasoning timeout so a slow/free model can't hang the turn.
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

# The reasoning stream, once it reaches the JSON tail, is machine data — stop
# surfacing it as human "thought" at the first structure marker.
_JSON_MARKERS = ("```json", "```", "{")


class Thinker:
    """Reason on gathered evidence and produce a structured analysis.

    Usage (streaming, for the loop):
        analysis = None
        async for chunk in thinker.consult(evidence, adapter):
            if chunk.thinking:            # live reasoning → ThinkingBlock
                emit_thinking(chunk.thinking)
            if chunk.done:
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
        """Stream the Thinker's reasoning; stash the parsed analysis on
        `self.last_analysis` and on the final chunk's metadata. Bounded by the
        reasoning timeout — a timeout yields whatever reasoning arrived plus an
        empty-but-safe analysis so the loop proceeds on its own next step."""
        self.last_analysis = None
        messages = build_thinker_messages(evidence)

        buf: list[str] = []
        stopped_surfacing = False  # once the JSON tail starts, stop streaming as thought
        try:
            stream = adapter.chat(messages, temperature=temperature, intent="analyze")
            async for chunk in _with_timeout(stream, self._timeout):
                if getattr(chunk, "error", None):
                    logger.warning("[thinker] provider error during consult: %s", chunk.error)
                    break
                piece = (chunk.text or "") + (chunk.thinking or "")
                if not piece:
                    continue
                buf.append(piece)
                if not stopped_surfacing:
                    joined = "".join(buf)
                    marker = _first_marker(joined)
                    if marker >= 0:
                        # Surface only the prose up to the JSON tail, once.
                        head = joined[:marker]
                        already = _visible_len(buf, len(piece))
                        tail = head[already:] if already < len(head) else ""
                        if tail:
                            yield StreamChunk(text="", thinking=tail, done=False)
                        stopped_surfacing = True
                    else:
                        yield StreamChunk(text="", thinking=piece, done=False)
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


def _first_marker(text: str) -> int:
    """Index of the earliest JSON-tail marker, or -1."""
    idxs = [text.find(m) for m in _JSON_MARKERS]
    idxs = [i for i in idxs if i >= 0]
    return min(idxs) if idxs else -1


def _visible_len(buf: list[str], last_piece_len: int) -> int:
    """Chars already surfaced as thought before the current piece was added."""
    return sum(len(p) for p in buf) - last_piece_len


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
