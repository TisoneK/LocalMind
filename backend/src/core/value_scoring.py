"""
LLM-guided value scoring (opt-in).

Design.md §6 names this slice: "LLM-guided value scoring of every
message — too slow for free-tier; the deterministic marker approach is
the P0 trade." P3 makes the value judgment available as an OPT-IN: when
`settings.localmind_llm_value_scoring` is True, one LLM call scores the
history messages 0.0-1.0 and the summarizer compresses the LOWEST-value
messages instead of blindly the oldest 50% — the context window is
rebuilt by value, not by position.

Safety contract (flaw-log friendly):
  - OFF by default — the deterministic marker path is untouched.
  - On ANY failure (adapter error, timeout, malformed output, empty
    history) `score_messages()` returns None and the caller falls back
    to the legacy positional compression. Value scoring can never break
    or slow a turn beyond its own bounded timeout.
  - One LLM call per turn, bounded message count and per-message length.

Wire-in (summarizer.py): `maybe_compress_history(..., value_scores=...)`
— when scores are present (same length as the conversation messages),
the oldest-50% slice is replaced by the lowest-value slice.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

# Bound the scoring call: a pathological long history is sampled, not
# scored wholesale.
_MAX_SCORED_MESSAGES = 40
# Per-message truncation so a single huge tool dump can't bloat the
# scoring prompt.
_MAX_MESSAGE_CHARS = 400
# The scoring call must never meaningfully delay a turn — bounded timeout.
_SCORE_TIMEOUT_SECS = 8.0

_SCORING_SYSTEM_PROMPT = (
    "You are a context-value scorer for an AI assistant's conversation. "
    "Rate how VALUABLE each message is for deciding the NEXT action. "
    "Score 0.0 for filler that can be safely discarded (greetings, "
    "confirmations, resolved digressions, verbose tool dumps) and 1.0 for "
    "content that changes future decisions (constraints, decisions, "
    "rejections, requirements, exact errors, current file state, "
    "unmet criteria). Reply with ONLY a JSON array of floats, one per "
    "message, in the same order, e.g. [0.1, 0.9, 0.5]. No prose."
)


async def score_messages(
    messages: list[dict],
    adapter: "BaseAdapter",
) -> Optional[list[float]]:
    """Score each message 0.0-1.0 via one bounded LLM call.

    Returns None on any failure — callers MUST fall back to the legacy
    deterministic behavior (never let value scoring break a turn).
    """
    if not messages:
        return None
    conv = messages[1:] if messages and messages[0].get("role") == "system" else messages
    if not conv:
        return None
    # Sample the tail (most recent) — value is densest near the action.
    conv = conv[-_MAX_SCORED_MESSAGES:]

    lines = []
    for i, m in enumerate(conv):
        role = m.get("role", "?")
        content = (m.get("content") or "")[:_MAX_MESSAGE_CHARS]
        lines.append(f"{i}. [{role}] {content}")
    excerpt = "\n".join(lines)

    try:
        chunks = []

        async def _collect() -> None:
            async for chunk in adapter.chat(
                [
                    {"role": "system", "content": _SCORING_SYSTEM_PROMPT},
                    {"role": "user", "content": excerpt},
                ],
                temperature=0.0,
            ):
                if getattr(chunk, "error", None):
                    logger.warning("[value_scoring] adapter error: %s", str(chunk.error)[:120])
                    return
                chunks.append(getattr(chunk, "text", "") or "")

        await asyncio.wait_for(_collect(), timeout=_SCORE_TIMEOUT_SECS)
        raw = "".join(chunks).strip()
        if not raw:
            return None
        return _parse_scores(raw, expected=len(conv))
    except asyncio.TimeoutError:
        logger.debug("[value_scoring] scoring timed out — falling back to deterministic")
        return None
    except Exception as e:  # pragma: no cover — defensive
        logger.debug("[value_scoring] scoring failed (non-fatal): %s", e)
        return None


def _parse_scores(raw: str, expected: int) -> Optional[list[float]]:
    """Parse the model's reply into a float list of length `expected`.

    Accepts a JSON array (preferred) or a bare list. Any malformed /
    length-mismatched output → None (deterministic fallback).
    """
    # Strip code fences if the model wrapped the JSON.
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()
    try:
        start, end = cleaned.index("["), cleaned.rindex("]") + 1
        parsed = json.loads(cleaned[start:end])
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, list) or len(parsed) != expected:
        return None
    scores = []
    for v in parsed:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        scores.append(max(0.0, min(1.0, f)))
    return scores


def lowest_value_indices(
    scores: Optional[list[float]],
    n: int,
) -> Optional[list[int]]:
    """Indices of the n lowest-value messages (for compression).

    None when scores are absent or too short — caller falls back to the
    positional slice. Deterministic tie-break (stable by index).
    """
    if scores is None or n <= 0 or len(scores) < n:
        return None
    order = sorted(range(len(scores)), key=lambda i: (scores[i], i))
    return order[:n]
