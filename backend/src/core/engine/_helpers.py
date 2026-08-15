"""
Module-level helper utilities for the Engine package.

Extracted from the original engine.py to reduce file size. These are
pure functions and standalone classes that don't depend on the Engine
instance.
"""

from __future__ import annotations

from core.cache import memoize

# ── Constants ────────────────────────────────────────────────────────────

# Similarity threshold for memory deduplication (0–1, higher = stricter)
MEMORY_DEDUP_THRESHOLD = 0.85


# ── Token estimation ─────────────────────────────────────────────────────


@memoize(ttl_seconds=300.0, max_entries=256)
def _approx_tokens(text: str) -> int:
    """
    Rough token count. ~4 chars/token for Latin scripts; ~1.5 for CJK/Arabic.
    Not used for billing — observability only.

    Memoized (shared TTLCache): the engine calls this 30+ times per request,
    often on the SAME text twice (prompt + completion of one turn) — the
    pure Python per-char scan is the expensive part, so caching identical
    inputs is a real win. Bounded to 256 entries, 5-minute TTL; the default
    keyer stores repr(text) so a busy session with large outputs holds up to
    256 full-text keys briefly — bounded, TTL'd, not a leak.
    """
    cjk_and_arabic = sum(
        1
        for c in text
        if "\u4e00" <= c <= "\u9fff"  # CJK Unified
        or "\u0600" <= c <= "\u06ff"  # Arabic
        or "\uac00" <= c <= "\ud7a3"  # Hangul
    )
    ratio = 1.5 if cjk_and_arabic > len(text) * 0.2 else 4.0
    return max(1, round(len(text) / ratio))
