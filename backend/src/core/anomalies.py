"""Anomaly detection for the Observe panel.

The Observe panel used to be a passive readout — it displayed the numbers
but never flagged when they were wrong. This module turns the two failure
shapes the user actually hit into first-class alerts:

1. STALL — a turn that burned 60s+ producing almost no output (the
   The "died silently" failure (108.6s with 23 tokens). Detected
   by throughput: latency > 60s AND completion tokens < 1/sec. A normal
   slow turn (65s / 300 tokens) is NOT flagged — only the near-empty
   burn.

2. TOKEN_LEAK — a brand-new chat whose prompt/context token count is
   suspiciously close to the previous turn's (the "new chat did not
   reset" failure: 5653 -> 5705). Detected on a session's FIRST turn
   when context tokens clear a floor AND match the previous turn's
   count within 25% — a fresh session should start near zero, so a
   near-identical large count means history or memory leaked across
   sessions.

Pure functions — unit-testable without running the engine.
"""

from __future__ import annotations

from typing import Optional

# A turn at/above this latency is eligible for the stall alert.
STALL_LATENCY_MS = 60_000
# Minimum output throughput below which the turn is considered stalled.
STALL_MIN_TOKENS_PER_SEC = 1.0
# A fresh session's context count must clear this floor before a leak is
# plausible (a small prompt is just the system prompt + user message).
LEAK_MIN_PROMPT_TOKENS = 4000
# The fresh session's count must match the previous turn's within this
# fraction to count as "carried over". Kept tight (15%) because the
# reported leak was within ~1% (5653 -> 5705) and legitimate first turns
# of new chats can carry 4-5k prompt tokens (agent prompt + tools + env +
# memory) — a loose window would false-alarm on ordinary heavy turns.
LEAK_SIMILARITY = 0.15


def detect_stall(
    latency_ms: float,
    completion_tokens: float,
) -> Optional[dict]:
    """Flag a turn that spent >60s producing almost no output."""
    if not latency_ms or latency_ms < STALL_LATENCY_MS:
        return None
    elapsed_s = latency_ms / 1000.0
    if completion_tokens < elapsed_s * STALL_MIN_TOKENS_PER_SEC:
        return {
            "kind": "stall",
            "severity": "high",
            "title": "Turn stalled",
            "detail": (
                f"{elapsed_s:.0f}s of work produced only {int(completion_tokens)} "
                "output tokens — the model likely hung or returned an empty "
                "stream. Check the Actions tab for what actually ran."
            ),
            "metrics": {
                "latency_ms": int(latency_ms),
                "completion_tokens": int(completion_tokens),
            },
        }
    return None


def detect_token_leak(
    session_id: str,
    context_tokens: float,
    is_first_turn: bool,
    prev_prompt_tokens: Optional[float],
    prev_session_id: Optional[str],
) -> Optional[dict]:
    """Flag a fresh session whose context count matches the previous turn's.

    A new chat (fresh session id, first turn) with a large prompt that is
    nearly identical to the previous turn's large prompt means context
    carried over instead of resetting.
    """
    if not is_first_turn or not context_tokens:
        return None
    if context_tokens < LEAK_MIN_PROMPT_TOKENS:
        return None
    if not prev_prompt_tokens or prev_prompt_tokens < LEAK_MIN_PROMPT_TOKENS:
        return None
    if prev_session_id == session_id:
        return None  # same session continuing — not a cross-session leak
    if abs(context_tokens - prev_prompt_tokens) <= prev_prompt_tokens * LEAK_SIMILARITY:
        return {
            "kind": "token_leak",
            "severity": "high",
            "title": "Context may have leaked from a previous session",
            "detail": (
                f"A new chat reported {int(context_tokens)} context tokens — "
                f"within {int(LEAK_SIMILARITY * 100)}% of the previous turn's "
                f"{int(prev_prompt_tokens)}. A fresh chat should start near "
                "zero; history or memory may not have reset."
            ),
            "metrics": {
                "context_tokens": int(context_tokens),
                "prev_context_tokens": int(prev_prompt_tokens),
            },
        }
    return None


def detect_turn_anomalies(
    session_id: str,
    latency_ms: float,
    completion_tokens: float,
    context_tokens: float,
    is_first_turn: bool,
    prev_prompt_tokens: Optional[float] = None,
    prev_session_id: Optional[str] = None,
) -> list[dict]:
    """Run all detectors for one completed turn. Returns anomaly dicts."""
    out: list[dict] = []
    stall = detect_stall(latency_ms, completion_tokens)
    if stall:
        out.append(stall)
    leak = detect_token_leak(
        session_id,
        context_tokens,
        is_first_turn,
        prev_prompt_tokens,
        prev_session_id,
    )
    if leak:
        out.append(leak)
    return out
