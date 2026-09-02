"""B-2026-09-02 — gated live-streaming slice 1 (ADR-57): the flush helper.

Live traces (scripts/live_test_stream_gating.py, bankofai + zai) proved the
streamed happy path end-to-end. These unit tests pin the dedupe arithmetic
that the post-gate flush depends on: the flush must never re-yield text the
user already saw live (the Session 332 duplicate-answer class), and must
recover a held-but-unseen tail when a guard stripped text after streaming
started.
"""

from __future__ import annotations

from core.agent.loop import _flush_after_live_stream


def test_no_stream_shown_yields_everything():
    """Nothing streamed live → the full clean text flushes (legacy path)."""
    assert _flush_after_live_stream("", "the whole answer") == "the whole answer"
    assert _flush_after_live_stream("", "") == ""


def test_clean_empty_yields_nothing():
    """Streamed but nothing clean to flush → no yield, no crash."""
    assert _flush_after_live_stream("shown text", "") == ""


def test_identical_text_yields_nothing():
    """Buffered text equals the streamed text → nothing re-yielded."""
    assert _flush_after_live_stream("same text", "same text") == ""


def test_prefix_match_yields_only_tail():
    """Cleaned text extends the shown prefix → only the tail flushes."""
    assert _flush_after_live_stream("head", "head and tail") == " and tail"


def test_whitespace_only_difference_is_deduped():
    """_strip_minimax_tool_calls strips whitespace — a stripped-prefix match
    must still dedupe (no re-yield of the whole answer). The tail keeps its
    boundary whitespace (no welded words when concatenated)."""
    assert _flush_after_live_stream("head", "head ") == ""
    assert _flush_after_live_stream("head ", "head tail") == " tail"


def test_divergent_text_yields_nothing_safe():
    """Guards rewrote the text so the shown prefix doesn't match → return ""
    (lose a few unseen chars) rather than duplicating the answer."""
    assert _flush_after_live_stream("shown preamble", "completely different") == ""


def test_leading_whitespace_in_clean_text_still_dedupes():
    """Clean text starting with whitespace then the shown prefix dedupes."""
    assert _flush_after_live_stream("head", "  head tail") == " tail"
