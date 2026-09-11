"""S427 — evidence-grounded resolution for referential memory writes.

The contract (user directive): memory should have EVIDENCE first, understand
what the user wants remembered, and distill it into a self-contained one
line or paragraph — never store the user's raw words when those words only
name a referent.

Live proof this module is needed (S427 diagnosis): "Remember the source for
EPL table" ran the deterministic zero-LLM write and stored the literal
phrase "source for EPL table", then confirmed it. The URL the user meant
(https://www.skysports.com/premier-league-table) was in the turn-1 context
and was never consulted. A referent cannot be resolved without reasoning —
so referential writes get exactly ONE bounded resolution call over the
recent conversation, and only its output is persisted. Self-contained
writes (URLs, paths, dates, quotes, complete statements) never pay this
call — `memory_intent.needs_resolution()` gates it.

Failure contract: NOT_FOUND, provider errors, and unparseable output all
return None — the caller must NOT write and MUST NOT fake-confirm; it asks
the user instead.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from core.agent.models import strip_worker_reports_from_history

logger = logging.getLogger(__name__)

# NOT_FOUND sentinel — the model's escape hatch when the conversation
# genuinely lacks what the request refers to. Matched loosely because weak
# models wrap it in punctuation.
_NOT_FOUND_MARKERS = ("not_found", "not found", "unknown", "not mentioned")

_MAX_FACT_CHARS = 400
_MAX_HISTORY_TURNS = 8
_RESOLVE_TIMEOUT_SECS = 25.0

_SYSTEM_PROMPT = (
    "You resolve what the user wants remembered into ONE self-contained fact. "
    "Use ONLY the conversation transcript below as evidence — never invent. "
    "Include concrete identifiers (URLs, names, values, numbers) exactly as "
    "they appear in the transcript. The fact must make sense on its own to "
    "someone who never saw this conversation (a future query should be "
    "answerable from it alone). One or two plain sentences maximum, no "
    "preamble, no quotes around the fact. If the transcript does not contain "
    "what the request refers to, output exactly: NOT_FOUND"
)


def build_resolution_messages(
    history: list[dict], request_content: str
) -> list[dict]:
    """Assemble the resolution prompt: system contract + evidence transcript + ask."""
    lines: list[str] = []
    for msg in strip_worker_reports_from_history(history[-_MAX_HISTORY_TURNS:]):
        role = str(msg.get("role", "?"))
        content = str(msg.get("content", "") or "").strip()
        if not content:
            continue
        lines.append(f"{role}: {content[:600]}")
    transcript = "\n".join(lines) if lines else "(no prior conversation)"
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"CONVERSATION TRANSCRIPT (the only evidence you may use):\n"
                f"{transcript}\n\n"
                f"The user asked to remember: \"{request_content}\"\n\n"
                "Output the resolved fact (or NOT_FOUND)."
            ),
        },
    ]


def parse_resolved_fact(raw_text: str) -> Optional[str]:
    """Extract the resolved fact from the model's output.

    Returns None when the model could not resolve (NOT_FOUND sentinel,
    empty output) or the output is not usable as a fact. Strips wrapping
    quotes and the transcript-echo preamble weak models sometimes add.
    """
    text = (raw_text or "").strip().strip("`").strip()
    if not text:
        return None
    lowered = text.lower()
    if any(marker in lowered for marker in _NOT_FOUND_MARKERS):
        return None
    # Drop a wrapping quote pair if the whole output is quoted.
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'“”":
        text = text[1:-1].strip()
    if not text:
        return None
    if len(text) > _MAX_FACT_CHARS:
        text = text[:_MAX_FACT_CHARS].rsplit(" ", 1)[0] + "…"
    return text


async def resolve_memory_fact(
    adapter,
    history: list[dict],
    request_content: str,
    timeout_secs: float = _RESOLVE_TIMEOUT_SECS,
) -> Optional[str]:
    """Run the ONE bounded resolution call and return the resolved fact.

    Returns None on: NOT_FOUND, empty/unparseable output, or any adapter
    error (timeout, provider failure). The caller must treat None as
    "do not write, ask the user" — never as "write the raw phrase".
    """
    messages = build_resolution_messages(history, request_content)

    async def _drain() -> str:
        chunks: list[str] = []
        async for chunk in adapter.chat(messages, intent="chat"):
            if getattr(chunk, "error", None):
                raise RuntimeError(str(chunk.error)[:200])
            text = getattr(chunk, "text", None)
            if text:
                chunks.append(text)
        return "".join(chunks)

    try:
        raw = await asyncio.wait_for(_drain(), timeout=timeout_secs)
    except asyncio.TimeoutError:
        logger.warning("[memory-resolver] resolution timed out after %.0fs", timeout_secs)
        return None
    except Exception as exc:  # provider error, empty stream, …
        logger.warning("[memory-resolver] resolution failed: %s", exc)
        return None
    return parse_resolved_fact(raw)
