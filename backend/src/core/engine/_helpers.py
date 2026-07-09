"""
Module-level helper utilities for the Engine package.

Extracted from the original engine.py to reduce file size. These are
pure functions and standalone classes that don't depend on the Engine
instance.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections import OrderedDict
from typing import Optional

from core.models import Intent

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────

# Max entries kept in per-session intent history window fed to AgentLoop
INTENT_HISTORY_WINDOW = 5

# Max sessions tracked in _intent_history before pruning old entries
INTENT_HISTORY_MAX_SESSIONS = 100

# Similarity threshold for memory deduplication (0–1, higher = stricter)
MEMORY_DEDUP_THRESHOLD = 0.85


# ── Background task helper ───────────────────────────────────────────────

def _safe_task(coro) -> asyncio.Task:
    """
    Schedule a fire-and-forget coroutine as an asyncio Task.

    Replaces bare ensure_future/create_task calls throughout the engine.
    Differences from raw create_task:
      - Uses create_task (explicit, Python 3.7+ standard — no loop ambiguity).
      - Wraps the coroutine so any unhandled exception is logged rather than
        silently discarded.  Without this wrapper, exceptions in background
        tasks produce an "unhandled exception in task" warning at GC time —
        after the traceback context is gone — making them nearly impossible
        to diagnose in production.
    """
    async def _wrapper():
        try:
            await coro
        except Exception:
            logger.exception("Background task failed")

    return asyncio.create_task(_wrapper())


# ── Chat Agent response cache ────────────────────────────────────────────
# v0.11 PERFORMANCE: Cache Chat Agent responses for repeated/simple queries.
# This saves 2-5s for repeated queries (15-25% of requests).

class _LRUCache:
    """Simple LRU cache with max size."""
    def __init__(self, maxsize: int = 256):
        self._cache: OrderedDict = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: str) -> Optional[tuple[str, str]]:
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def set(self, key: str, value: tuple[str, str]) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self._maxsize:
                self._cache.popitem(last=False)
        self._cache[key] = value

    def clear(self) -> None:
        self._cache.clear()


_chat_agent_cache = _LRUCache(maxsize=256)


def _get_chat_agent_cache_key(message: str, intent: Intent) -> str:
    """Create cache key from message and intent."""
    # Use first 200 chars and intent for cache key
    return hashlib.sha256(
        f"{intent.value}:{message[:200]}".encode()
    ).hexdigest()[:32]


# ── Chat Agent output parsing ────────────────────────────────────────────

def _parse_chat_agent_output(text: str) -> tuple[str, str]:
    """
    Parse the Chat Agent's structured output into acknowledgement and reformulated instruction.

    The Chat Agent prompt asks for two parts:
      PART 1 — ACKNOWLEDGE: brief friendly confirmation
      PART 2 — REFORMULATED INSTRUCTION: structured steps for the Execution Agent

    Returns (acknowledgement, reformulated_instruction).
    If parsing fails, returns (text, text) — the full text serves as both.
    """
    # Try to split on "PART 2" marker
    part2_match = re.search(
        r'(?:^|\n)\s*PART\s*2\s*[—\-:]\s*(?:REFORMULATED\s+INSTRUCTION\s*[—\-:]?\s*)?',
        text, re.IGNORECASE
    )
    if part2_match:
        part1_text = text[:part2_match.start()].strip()
        part2_text = text[part2_match.end():].strip()

        # Extract just the acknowledgement from Part 1
        part1_match = re.search(
            r'(?:^|\n)\s*PART\s*1\s*[—\-:]\s*(?:ACKNOWLEDGE\s*[—\-:]?\s*)?',
            part1_text, re.IGNORECASE
        )
        if part1_match:
            acknowledgement = part1_text[part1_match.end():].strip()
        else:
            acknowledgement = part1_text

        # Clean up acknowledgement: remove bullet points, numbered steps
        # If the acknowledgement looks like it contains steps, just take first sentence
        ack_lines = acknowledgement.split('\n')
        ack_clean = []
        for line in ack_lines:
            line = line.strip()
            if not line:
                continue
            # Stop at numbered/bulleted lists — those belong in Part 2
            if re.match(r'^\d+[\.\)]\s', line):
                break
            if line.startswith('- ') or line.startswith('* '):
                break
            ack_clean.append(line)
        acknowledgement = ' '.join(ack_clean).strip()

        # If acknowledgement is too long (>200 chars), truncate to first 2 sentences
        if len(acknowledgement) > 200:
            sentences = re.split(r'(?<=[.!?])\s+', acknowledgement)
            acknowledgement = ' '.join(sentences[:2])

        return acknowledgement, part2_text

    # Fallback: no PART 2 marker found. Try splitting on a double newline
    # or "Steps:" / "Instruction:" pattern
    steps_match = re.search(
        r'(?:^|\n)\s*(?:STEPS?|INSTRUCTION|EXECUTION PLAN)[\s:—\-]',
        text, re.IGNORECASE
    )
    if steps_match:
        acknowledgement = text[:steps_match.start()].strip()
        reformulated = text[steps_match.start():].strip()
        return acknowledgement, reformulated

    # Final fallback: use first 1-2 sentences as acknowledgement,
    # full text as reformulated instruction
    sentences = re.split(r'(?<=[.!?])\s+', text)
    if len(sentences) >= 2 and len(sentences[0]) < 200:
        return sentences[0], text
    return text, text


# ── Intent resolution ────────────────────────────────────────────────────

def _resolve_intent(
    primary_intent: Intent,
    top_tool: Optional[Intent],
    confidence: float,
) -> Intent:
    """
    Legacy intent resolution — kept for edge cases where tool scoring
    disagrees with the dispatcher. In v4.0, this is rarely triggered
    because the ThinkingDispatcher's LLM-based inference is more accurate
    than keyword-based tool scoring.
    """
    if top_tool and confidence < 0.6:
        logger.debug(f"[engine] low confidence ({confidence:.2f}), deferring to top_tool={top_tool.value}")
        return top_tool
    return primary_intent


# ── Token estimation ─────────────────────────────────────────────────────

def _approx_tokens(text: str) -> int:
    """
    Rough token count. ~4 chars/token for Latin scripts; ~1.5 for CJK/Arabic.
    Not used for billing — observability only.
    """
    cjk_and_arabic = sum(
        1 for c in text
        if '\u4e00' <= c <= '\u9fff'      # CJK Unified
        or '\u0600' <= c <= '\u06ff'      # Arabic
        or '\uac00' <= c <= '\ud7a3'      # Hangul
    )
    ratio = 1.5 if cjk_and_arabic > len(text) * 0.2 else 4.0
    return max(1, round(len(text) / ratio))


# ── Duplicate text detection ────────────────────────────────────────────

class DuplicateFilter:
    """Detects and suppresses duplicate paragraphs in streaming output.

    Small models (especially free-tier) sometimes loop, repeating the same
    paragraph or sentence multiple times. This filter tracks the accumulated
    text and suppresses tokens that would create a duplicate paragraph.

    Strategy: after each new chunk, check if the text since the last paragraph
    boundary (\n\n) matches any earlier complete paragraph. If it does, suppress
    the matching portion.
    """

    def __init__(self):
        self._accumulated: str = ""
        self._seen_paragraphs: list[str] = []
        self._min_dup_len: int = 30  # Only check for dups >= 30 chars
        self._suppressing: bool = False

    def feed(self, new_text: str) -> str:
        """Feed new text and return the non-duplicate portion."""
        if not new_text:
            return new_text

        self._accumulated += new_text

        # Split into paragraphs — everything before the last \n\n is "complete"
        parts = self._accumulated.rsplit('\n\n', 1)
        if len(parts) == 2:
            # We have a complete paragraph boundary
            complete_para = parts[0].rsplit('\n\n', 1)[-1].strip()
            if len(complete_para) >= self._min_dup_len:
                # Check if this paragraph was already seen
                if complete_para in self._seen_paragraphs:
                    # Duplicate! Suppress by removing the duplicate from accumulated
                    self._accumulated = parts[0]  # Keep everything before the dup
                    return ""
                else:
                    self._seen_paragraphs.append(complete_para)

        # Also check the current (incomplete) paragraph for duplicates
        current_para = parts[-1].strip()
        if len(current_para) >= self._min_dup_len:
            # Check if current paragraph exactly matches a seen one
            if current_para in self._seen_paragraphs:
                # The full current paragraph is a duplicate — suppress
                self._accumulated = parts[0] if len(parts) == 2 else ""
                return ""

        return new_text

    @property
    def text(self) -> str:
        """Return the filtered accumulated text."""
        return self._accumulated
