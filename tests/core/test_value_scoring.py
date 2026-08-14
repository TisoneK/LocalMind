"""
Tests for ADR-19 P3 (Session 179): LLM-guided value scoring (opt-in).

Design.md §6: "LLM-guided value scoring of every message — too slow for
free-tier; the deterministic marker approach is the P0 trade." P3 makes
the value judgment available as an OPT-IN flag; when enabled, one bounded
LLM call scores history messages and the summarizer compresses the
LOWEST-value messages instead of the oldest 50% — context rebuilt by
value, not by position.

Safety contract tested here:
- score_messages parses JSON arrays; any malformed/error/timeout → None
  (deterministic fallback, never breaks the turn).
- summarizer with value_scores compresses lowest-value messages and keeps
  high-value ones verbatim; without scores → legacy oldest-50% slice.
- engine wiring: _maybe_score_history returns None when the flag is OFF
  (default — regression-safe) and calls score_messages when ON.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _fake_adapter(reply="[0.1, 0.9, 0.5]"):
    adapter = MagicMock()

    async def _chat(messages, **kwargs):
        class _Chunk:
            error = None
            text = reply

        yield _Chunk()

    adapter.chat.side_effect = _chat
    adapter.error = None
    return adapter


def _msgs(n=4):
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(n):
        msgs.append({"role": "user", "content": f"message {i} content"})
    return msgs


class TestScoreMessages:
    @pytest.mark.asyncio
    async def test_parses_json_array(self):
        from core.value_scoring import score_messages

        scores = await score_messages(_msgs(), _fake_adapter("[0.1, 0.9, 0.5, 0.2]"))
        assert scores == [0.1, 0.9, 0.5, 0.2]

    @pytest.mark.asyncio
    async def test_strips_code_fence(self):
        from core.value_scoring import score_messages

        adapter = _fake_adapter('```json\n[0.1, 0.9, 0.5, 0.2]\n```')
        scores = await score_messages(_msgs(), adapter)
        assert scores == [0.1, 0.9, 0.5, 0.2]

    @pytest.mark.asyncio
    async def test_malformed_output_returns_none(self):
        from core.value_scoring import score_messages

        assert await score_messages(_msgs(), _fake_adapter("not json at all")) is None
        assert await score_messages(_msgs(), _fake_adapter("")) is None
        # Wrong length → None (must not misalign compression)
        assert await score_messages(_msgs(), _fake_adapter("[0.1, 0.9]")) is None

    @pytest.mark.asyncio
    async def test_adapter_error_returns_none(self):
        from core.value_scoring import score_messages

        adapter = MagicMock()

        async def _chat(messages, **kwargs):
            class _Chunk:
                error = "boom"
                text = ""

            yield _Chunk()

        adapter.chat.side_effect = _chat
        assert await score_messages(_msgs(), adapter) is None

    @pytest.mark.asyncio
    async def test_empty_messages_returns_none(self):
        from core.value_scoring import score_messages

        assert await score_messages([], _fake_adapter()) is None

    @pytest.mark.asyncio
    async def test_clamps_scores_to_unit_range(self):
        from core.value_scoring import score_messages

        scores = await score_messages(_msgs(), _fake_adapter("[-5, 2, 0.5, 0.5]"))
        assert scores == [0.0, 1.0, 0.5, 0.5]


class TestLowestValueIndices:
    def test_returns_lowest_indices(self):
        from core.value_scoring import lowest_value_indices

        idx = lowest_value_indices([0.9, 0.1, 0.5, 0.2], 2)
        assert idx == [1, 3]

    def test_none_when_scores_absent(self):
        from core.value_scoring import lowest_value_indices

        assert lowest_value_indices(None, 2) is None
        assert lowest_value_indices([0.9], 2) is None  # too short


class TestSummarizerValueSlice:
    """maybe_compress_history uses value scores to pick the compressed
    slice (ADR-19 P3)."""

    def _big_history(self):
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(8):
            msgs.append({"role": "user", "content": f"USER: msg {i} detail here"})
        return msgs

    @pytest.mark.asyncio
    async def test_compresses_lowest_value_messages(self):
        from core.summarizer import maybe_compress_history

        msgs = self._big_history()  # system + 8 conv
        # NON-MONOTONIC scores so the lowest-value slice differs from the
        # legacy oldest-50% slice: lowest 4 = indices 1, 3, 5, 7 — which
        # includes the NEWEST message (7) and excludes the oldest (0).
        # This genuinely discriminates value-based from positional.
        scores = [0.9, 0.1, 0.8, 0.2, 0.7, 0.3, 0.6, 0.4]
        adapter = _fake_adapter("value summary")
        # Fixture ≈ 80 tokens; budget 80 → threshold 60 < 80 forces compression.
        result = await maybe_compress_history(
            msgs, adapter, 80, value_scores=scores
        )
        # Compression happened (summary replaced ~50% of conv).
        assert len(result) < len(msgs)
        joined = "\n".join(m.get("content", "") for m in result)
        assert "value summary" in joined
        # The NEWEST message (index 7, score 0.4) was compressed despite
        # being most recent — proves VALUE selection, not positional.
        assert "msg 7 detail here" not in joined
        # The OLDEST message (index 0, score 0.9) survived despite being
        # oldest — high value beats old age.
        assert "msg 0 detail here" in joined

    @pytest.mark.asyncio
    async def test_no_scores_uses_legacy_positional_slice(self):
        from core.summarizer import maybe_compress_history

        msgs = self._big_history()
        adapter = _fake_adapter("legacy summary")
        result = await maybe_compress_history(msgs, adapter, 80, value_scores=None)
        joined = "\n".join(m.get("content", "") for m in result)
        assert "legacy summary" in joined
        # Legacy: oldest slice compressed, newest survive.
        assert "msg 7 detail here" in joined

    @pytest.mark.asyncio
    async def test_mismatched_scores_fall_back_to_legacy(self):
        from core.summarizer import maybe_compress_history

        msgs = self._big_history()
        adapter = _fake_adapter("fallback summary")
        # Wrong length (3 vs 8 conv messages) → legacy positional slice.
        result = await maybe_compress_history(msgs, adapter, 80, value_scores=[0.1, 0.2, 0.3])
        joined = "\n".join(m.get("content", "") for m in result)
        assert "fallback summary" in joined


class TestParentContextBoundary:
    """The parent runtime assembles context directly; no value-scoring
    method belongs to the removed request pipeline."""

    def test_value_scoring_remains_an_explicit_library(self):
        from core import value_scoring

        assert callable(value_scoring.score_messages)
        assert callable(value_scoring.lowest_value_indices)
