"""Tests for dependency-free shared utilities."""

import pytest
from core.utils import TRUNCATION_MARKER, BoundedOutputBuffer, bounded_output


def test_bounded_output_preserves_short_text():
    assert bounded_output("short", max_chars=20) == "short"


def test_bounded_output_preserves_head_and_tail():
    result = bounded_output("HEAD-" + ("x" * 90) + "-TAIL", max_chars=64)

    assert result.startswith("HEAD-")
    assert result.endswith("-TAIL")
    assert TRUNCATION_MARKER in result
    assert len(result) == 64


def test_bounded_output_tracks_incremental_chunks():
    buffer = BoundedOutputBuffer(max_chars=64)
    buffer.append("start")
    buffer.append(" middle ")
    buffer.append("end")

    assert buffer.truncated is False
    assert buffer.getvalue() == "start middle end"

    buffer.append("-" + ("y" * 100) + "-finish")
    assert buffer.truncated is True
    assert buffer.getvalue().startswith("start")
    assert buffer.getvalue().endswith("finish")
    assert len(buffer.getvalue()) == 64


def test_bounded_output_handles_marker_larger_than_limit():
    assert bounded_output("abcdef", max_chars=5) == TRUNCATION_MARKER[:5]


def test_bounded_output_rejects_negative_limit():
    with pytest.raises(ValueError):
        BoundedOutputBuffer(max_chars=-1)
