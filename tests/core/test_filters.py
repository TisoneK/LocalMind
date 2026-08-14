"""
Session 195 — _filter_system_leaks coverage for the bare <tool_call> format.

The live transcript: "whats the weather like in Kitengela now?" was misrouted
to the no-tools DIRECT path, and the model's
`<tool_call>web_search<arg_key>query</arg_key><arg_value>...</arg_value></tool_call>`
streamed RAW into the chat bubble — neither the invoke/parameter nor the
minimax:tool_call patterns matched it. These tests pin the display filter so
the markup can never render as user-facing text on any path.
"""

from __future__ import annotations

from core.filters import _filter_system_leaks

_TOOL_CALL_WS = (
    "Let me check the weather in Kitengela for you."
    "<tool_call>web_search<arg_key>query</arg_key>"
    "<arg_value>Kitengela Kenya current weather temperature conditions</arg_value>"
    "</tool_call>"
)


def test_strips_complete_tool_call_block():
    out = _filter_system_leaks(_TOOL_CALL_WS)
    assert "tool_call" not in out
    assert "arg_key" not in out
    assert "arg_value" not in out
    assert "Kitengela Kenya current weather" not in out
    assert "Let me check the weather in Kitengela for you." in out


def test_strips_standalone_tool_call_only():
    out = _filter_system_leaks(
        "<tool_call>shell<arg_key>command</arg_key><arg_value>ls -la</arg_value></tool_call>"
    )
    assert out.strip() == ""


def test_strips_partial_tool_call_opening():
    # Streaming chunk boundary: the opening tag has arrived, the value is cut off.
    out = _filter_system_leaks("checking now<tool_call>web_search<arg_key>qu")
    assert "tool_call" not in out
    assert "arg_key" not in out
    assert out.strip() == "checking now"


def test_preserves_plain_text():
    assert _filter_system_leaks("The sky is blue today.") == "The sky is blue today."


def test_preserves_other_markup_forms():
    # Legacy agent tags and minimax forms keep being stripped too.
    out = _filter_system_leaks("<action>think</action>done")
    assert "action" not in out
    assert out.strip() == "done"
