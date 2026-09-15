"""
History Summarizer — task-aware, decision-line-preserving.

When conversation history exceeds 75% of the token budget, summarize the
oldest 50% of messages into a single compact system message, then replace
those messages with the summary.  This preserves important early context
(user preferences, task setup) that would otherwise be silently dropped.

A `policy` parameter enables task-aware behavior:
- `policy=None` (or a default/legacy policy) → behavior is EXACTLY the
  original generic summary (byte-identical prompt) — a wiring no-op.
- A real policy uses its TASK-SPECIFIC summary prompt AND extracts
  decision-relevant lines (matching the policy's keep_markers) VERBATIM
  into a `[Preserved decisions]` block prepended to the summary — so the
  lossy-compression case the user named ("user wants PostgreSQL, rejected
  MongoDB, wants SQLite locally") survives compression instead of
  collapsing to "Database: PostgreSQL".

Usage:
    from core.summarizer import maybe_compress_history

    messages = maybe_compress_history(messages, adapter, token_budget, policy=policy)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, Optional

from core.context_policy import ContextPolicy
from core.value_scoring import lowest_value_indices

if TYPE_CHECKING:
    from adapters.base import BaseAdapter

# The engine passes a decision_sink so preserved
# decision lines are persisted to the cross-session decision ledger
# (durable — survives compression and session deletion).
DecisionSink = Callable[[list[str]], None]

logger = logging.getLogger(__name__)

# Summarise when history fills this fraction of the budget
_COMPRESS_THRESHOLD = 0.75
# Summarise the oldest this fraction of history messages
_COMPRESS_FRACTION = 0.50
# Cap on preserved decision lines (protects the summary from bloat).
_MAX_PRESERVED_LINES = 8
# Total-char cap on the preserved block (review: 12 x 500-char
# lines could add ~1500 tokens — net-negative on an already-over-budget
# turn). Kept well under what compression saves.
_MAX_PRESERVED_CHARS = 1200
# Per-line trim so one long line can't hog the whole block.
_MAX_PRESERVED_LINE_CHARS = 200

_SUMMARY_PROMPT = (
    "You are a conversation summarizer. "
    "Summarize the following conversation excerpt into a compact paragraph "
    "that preserves key facts, user preferences, decisions, and context that "
    "would be important for continuing the conversation. "
    "Be concise — aim for 3-6 sentences. Do not add commentary or preamble."
)


def _rough_token_count(messages: list[dict]) -> int:
    """UTF-8 byte based token estimate (mirrors context_builder fallback)."""
    total = 0
    for m in messages:
        total += len(m.get("content", "").encode("utf-8")) // 4 + 4
    return total


def _preserved_decision_lines(excerpt: str, policy: ContextPolicy) -> list[str]:
    """Extract lines matching the policy's keep_markers VERBATIM.

    The user's lossy-compression example: "user wants PostgreSQL, rejected
    MongoDB, wants SQLite locally, production uses PostgreSQL" — a naive
    summary collapses to "Database: PostgreSQL", silently dropping the
    rejected option and the local-mode choice. Lines that contain a
    decision/constraint marker are kept word-for-word so the summarizer
    cannot paraphrase them away.

    Bounds (per review): line count, per-line length, and total
    chars — a preserved block must never cost more than compression saves.
    """
    if not policy.keep_markers:
        return []
    markers = tuple(m.lower() for m in policy.keep_markers)
    kept: list[str] = []
    total = 0
    for line in excerpt.splitlines():
        line = line.strip()
        if not line:
            continue
        lowered = line.lower()
        if any(m in lowered for m in markers):
            trimmed = line[:_MAX_PRESERVED_LINE_CHARS]
            kept.append(trimmed)
            total += len(trimmed)
        if len(kept) >= _MAX_PRESERVED_LINES or total >= _MAX_PRESERVED_CHARS:
            break
    return kept


async def maybe_compress_history(
    messages: list[dict],
    adapter: "BaseAdapter",
    token_budget: int,
    policy: Optional[ContextPolicy] = None,
    decision_sink: Optional[DecisionSink] = None,
    value_scores: Optional[list[float]] = None,
) -> list[dict]:
    """
    A2: If history exceeds 75% of token_budget, summarize oldest 50% into a
    single system message and return the compressed list.

    Args:
        messages: Full prompt message list (may include a system message at [0]).
        adapter:  LLM adapter used to generate the summary.
        token_budget: Model context window in tokens.
        policy: Optional ContextPolicy. None/default → the original
            generic summary (no-op). A real policy switches to its per-task
            summary prompt and prepends preserved decision lines.
        decision_sink: Optional callback invoked with the preserved
            decision lines when compression actually ran (so the caller can
            persist them to the cross-session decision ledger). Default None
            → no-op; the summarizer stays pure.
        value_scores: Optional list of per-message value scores
            (0-1, aligned with the conversation messages after any leading
            system message). When present and correctly sized, the OLDEST-50%
            slice is replaced by the LOWEST-VALUE slice — compression by
            value, not by position. None/mismatched → legacy positional slice.

    Returns:
        Original list unchanged, or compressed list with a summary injected.
    """
    used = _rough_token_count(messages)
    threshold = int(token_budget * _COMPRESS_THRESHOLD)

    if used < threshold:
        return messages  # nothing to do

    # Separate system message (keep it intact) from conversation messages
    has_system = messages and messages[0]["role"] == "system"
    system_msgs = messages[:1] if has_system else []
    conv_msgs = messages[1:] if has_system else messages[:]

    if len(conv_msgs) < 4:
        return messages  # too short to compress meaningfully

    # Identify the slice to summarise. Default: the oldest 50%. Value-scored:
    # (opt-in LLM value scoring): when per-message value scores are present
    # and correctly sized, compress the LOWEST-VALUE messages instead — the
    # context window is rebuilt by value, not by position (design.md §6).
    # The kept messages retain their original relative order.
    n_to_compress = max(2, int(len(conv_msgs) * _COMPRESS_FRACTION))
    if value_scores is not None and len(value_scores) == len(conv_msgs):
        low_idx = lowest_value_indices(value_scores, n_to_compress)
        if low_idx is not None:
            low_set = set(low_idx)
            to_compress = [m for i, m in enumerate(conv_msgs) if i in low_set]
            to_keep = [m for i, m in enumerate(conv_msgs) if i not in low_set]
            logger.info(
                "[summarizer] compressing %d LOWEST-VALUE messages "
                "(value-based slice)",
                len(to_compress),
            )
        else:
            to_compress = conv_msgs[:n_to_compress]
            to_keep = conv_msgs[n_to_compress:]
    else:
        to_compress = conv_msgs[:n_to_compress]
        to_keep = conv_msgs[n_to_compress:]

    # Build a text excerpt for the summariser (truncated per message — the
    # LLM only needs a digest).
    excerpt = "\n".join(f"{m['role'].upper()}: {m.get('content', '')[:500]}" for m in to_compress)

    # Task-aware prompt + decision-line preservation. Preserved
    # lines are extracted from the RAW message contents (NOT the truncated
    # excerpt — per review: a decision line past the 500-char cut
    # must still survive, that is the entire point of the feature).
    active_policy = None if policy is None or policy.task_type == "default" else policy
    summary_prompt = active_policy.summary_prompt if active_policy else _SUMMARY_PROMPT
    raw_excerpt = "\n".join(f"{m['role'].upper()}: {m.get('content', '')}" for m in to_compress)
    preserved = _preserved_decision_lines(raw_excerpt, active_policy) if active_policy else []

    try:
        summary_chunks = []
        async for chunk in adapter.chat(
            [
                {"role": "system", "content": summary_prompt},
                {"role": "user", "content": excerpt},
            ],
            temperature=0.2,
        ):
            if chunk.error:
                logger.warning("[summarizer] adapter error: %s", chunk.error[:120])
                break
            summary_chunks.append(chunk.text)
        summary_text = "".join(summary_chunks).strip()
    except Exception as e:
        logger.warning(f"[summarizer] summary generation failed: {e}; skipping compression")
        return messages

    if not summary_text:
        return messages

    parts = [f"[Conversation summary — earlier context]\n{summary_text}"]
    if preserved:
        parts.append(
            "\n\n[Preserved decisions — verbatim, do not lose these]\n"
            + "\n".join(f"- {line}" for line in preserved)
        )
        # Forward the preserved lines to the decision ledger
        # (durable, cross-session) — best-effort, never breaks compression.
        if decision_sink is not None:
            try:
                decision_sink(preserved)
            except Exception as _ledger_exc:  # pragma: no cover — defensive
                logger.debug("[summarizer] decision_sink failed (non-fatal): %s", _ledger_exc)
    summary_msg = {"role": "system", "content": "\n".join(parts)}

    compressed = system_msgs + [summary_msg] + to_keep
    new_count = _rough_token_count(compressed)
    logger.info(f"[summarizer] compressed {n_to_compress} messages → summary ({used} → {new_count} tokens approx)")
    return compressed
