"""Regression: streamed model deltas must keep the spaces between them.

Session 231 bug: the init producer (direct-mode reply) and the plan stream
(execute-mode thinking) ran ``_strip_minimax_tool_calls`` — which ends with
``.strip()`` — on every streamed delta. A model streaming a JSON value token
by token emits deltas like ``"Respond"``, ``" to"``, ``" a"``; trimming each
one dropped the leading spaces, so the joined buffer collapsed to
``"Respondtoacasualgreeting"`` — a spaceless thought process AND answer. The
whitespace-safe stream variant fixes it.
"""

from __future__ import annotations

from core.agent.text_tools import (
    _strip_minimax_tool_calls,
    _strip_minimax_tool_calls_stream,
)


def test_stream_variant_preserves_leading_and_trailing_space():
    assert _strip_minimax_tool_calls_stream(" to") == " to"
    assert _strip_minimax_tool_calls_stream("Respond ") == "Respond "


def test_concatenated_stream_deltas_keep_their_spaces():
    # The exact failure shape from the bug report.
    deltas = ["Respond", " to", " a", " casual", " greeting"]
    joined = "".join(_strip_minimax_tool_calls_stream(d) for d in deltas)
    assert joined == "Respond to a casual greeting"


def test_stream_variant_still_removes_tool_call_markup():
    dirty = 'hello <minimax:tool_call>{"x":1}</minimax:tool_call> world'
    cleaned = _strip_minimax_tool_calls_stream(dirty)
    assert "minimax:tool_call" not in cleaned
    assert "hello" in cleaned and "world" in cleaned


def test_trimming_variant_still_trims_complete_text():
    # The non-streaming variant is unchanged: it trims edges of a full text.
    assert _strip_minimax_tool_calls("  hello world  ") == "hello world"
