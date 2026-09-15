"""The Thinker — the agent's reasoning backbone.

A read-only mid-loop analyst. Given the evidence the agent has gathered, it
reasons and returns a structured `ThinkerAnalysis` the agent acts on.

The "no call runs silent" rule: the consult's prose reasoning is
yielded as `thinking` chunks so the loop can stream it to the ThinkingBlock —
the user watches the actual decision reasoning, not an empty spinner. The
surfacing is bounded by the visible-prose contract, which is enforced
structurally here rather than by muting everything: reasoning streams ONLY
until the JSON block begins, and the JSON itself is never yielded (structure
≠ thought). The prompt echoes that motivated this contract are prevented at the
source — the prompt forbids restating the role/instructions — while
`_filter_system_leaks` in the loop stays the second layer.

It calls the model's plain `chat` (no tools — it decides nothing, executes
nothing) and is bounded by a dedicated reasoning timeout so a slow/free model
can't hang the turn.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Optional

from core.models import StreamChunk

from .contract import Evidence, ThinkerAnalysis
from .parse import _first_json_object, parse_thinker_analysis
from .prompt import build_thinker_messages

logger = logging.getLogger(__name__)

# While streaming, the first byte of a possible JSON block (a ``{`` or a
# ``` ``` ``` fence) is held back immediately — a brace mid-chunk must never
# surface, so the hold-back has to trigger on the marker, not on a fixed tail.
# At flush time the held-back region is either cut (real JSON) or released
# (it was prose all along).
def _earliest_json_marker(text: str) -> int:
    fence = text.find("```")
    brace = text.find("{")
    if fence < 0:
        return brace
    if brace < 0:
        return fence
    return min(fence, brace)


def _unterminated_json_start(text: str) -> int:
    """Index of the first '{' opening an unterminated brace region (the stream
    died mid-JSON), or -1. Naive balance walk, mirroring parse.py's rules."""
    start = text.find("{")
    while start >= 0:
        depth, in_str, esc, closed = 0, False, False, False
        for ch in text[start:]:
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    closed = True
                    break
        if not closed and depth > 0:
            return start
        start = text.find("{", start + 1)
    return -1


class Thinker:
    """Reason on gathered evidence and produce a structured analysis.

    Usage (streaming, for the loop):
        async for _chunk in thinker.consult(evidence, adapter):
            if _chunk.thinking:
                ...  # prose reasoning — forward to the ThinkingBlock
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
        """Run a consult, streaming the model's prose reasoning live.

        Prose (everything before the JSON block) is yielded as `thinking`
        chunks as it arrives; the JSON structure is buffered and never
        yielded. The parsed analysis is stashed on `self.last_analysis` and
        on the final chunk's metadata. Bounded by the reasoning timeout — a
        timeout yields whatever prose arrived plus an empty-but-safe analysis
        so the loop proceeds on its own next step."""
        self.last_analysis = None
        messages = build_thinker_messages(evidence)

        joined = ""
        surfaced = 0
        try:
            stream = adapter.chat(messages, temperature=temperature, intent="analyze")
            async for chunk in _with_timeout(stream, self._timeout):
                if getattr(chunk, "error", None):
                    logger.warning("[thinker] provider error during consult: %s", chunk.error)
                    break
                piece = (chunk.text or "") + (chunk.thinking or "")
                if not piece:
                    continue
                joined += piece
                marker = _earliest_json_marker(joined)
                limit = marker if marker >= 0 else len(joined)
                if limit > surfaced:
                    yield StreamChunk(text="", thinking=joined[surfaced:limit], done=False)
                    surfaced = limit
        except asyncio.TimeoutError:
            logger.warning("[thinker] consult timed out after %.0fs — proceeding without analysis", self._timeout)
        except Exception as exc:  # never let a consult crash the turn
            logger.warning("[thinker] consult failed: %s — proceeding without analysis", exc)

        # Final flush with the complete text: a completed object (or fence)
        # proves the held-back region is structure — cut it. An unterminated
        # brace region (timeout mid-JSON) is dropped rather than leaked. Only
        # prose survives to the user.
        _, json_start = _first_json_object(joined)
        limit = json_start if json_start >= 0 else _unterminated_json_start(joined)
        if limit < 0:
            limit = len(joined)
        if limit > surfaced:
            yield StreamChunk(text="", thinking=joined[surfaced:limit], done=False)
            surfaced = limit

        analysis = parse_thinker_analysis(joined)
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
