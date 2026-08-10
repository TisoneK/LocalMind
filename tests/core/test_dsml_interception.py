"""
Regression tests for the Session 127 DSML interception fix.

The real-model smoke (zen / deepseek-v4-flash-free, "create hello world repo")
caught DeepSeek's native DSML tool-call format being streamed as the FINAL
ANSWER instead of being intercepted + executed:

    <｜DSML｜tool_calls>
    <｜DSML｜invoke name="shell">
    <｜DSML｜parameter name="command" string="true">ls -la /tmp</｜DSML｜parameter>
    </｜DSML｜invoke>
    </｜DSML｜tool_calls>

The MiniMax-style interception path existed but only recognized
`minimax:tool_call <invoke ...>` / `<invoke ...>` markup. DSML uses a
fullwidth-bar prefix (U+FF5C) on every tag plus a `string="true"` attribute
on <parameter> — both broke the existing regexes. This session:

1. `_normalize_dsml()` converts DSML tags to standard <invoke>/<parameter> form.
2. `_parse_minimax_tool_call` / `_has_minimax_tool_call` /
   `_strip_minimax_tool_calls` normalize before parsing.
3. `_PARAM_RE` tolerates extra attributes (the `string="true"` attribute).
4. `_is_tool_talk` recognizes `<｜DSML｜` as tool-talk (recovery path).
"""

from __future__ import annotations

from core.agent.loop import (
    _has_minimax_tool_call,
    _is_tool_talk,
    _normalize_dsml,
    _parse_minimax_tool_call,
    _strip_minimax_tool_calls,
)

_DSML_SHELL = """<｜DSML｜tool_calls>
<｜DSML｜invoke name="shell">
<｜DSML｜parameter name="command" string="true">ls -la /tmp</｜DSML｜parameter>
</｜DSML｜invoke>
</｜DSML｜tool_calls>"""

_DSML_INLINE = (
    '<｜DSML｜invoke name="shell">'
    '<｜DSML｜parameter name="command" string="true">git status</｜DSML｜parameter>'
    "</｜DSML｜invoke>"
)


# ── _normalize_dsml ─────────────────────────────────────────────────────────


def test_normalize_dsml_converts_prefix():
    out = _normalize_dsml(_DSML_SHELL)
    assert "<invoke name=\"shell\">" in out
    assert "</invoke>" in out
    assert "<parameter name=\"command\" string=\"true\">" in out
    assert "</parameter>" in out
    # No DSML markers remain
    assert "｜DSML｜" not in out


def test_normalize_dsml_passthrough_without_markers():
    assert _normalize_dsml("plain text") == "plain text"
    assert _normalize_dsml("") == ""


# ── _has_minimax_tool_call ─────────────────────────────────────────────────


def test_has_detects_dsml_shell():
    assert _has_minimax_tool_call(_DSML_SHELL) is True
    assert _has_minimax_tool_call(_DSML_INLINE) is True


def test_has_ignores_plain_text():
    assert _has_minimax_tool_call("just some words") is False


# ── _parse_minimax_tool_call ───────────────────────────────────────────────


def test_parse_dsml_shell_extracts_command():
    calls = _parse_minimax_tool_call(_DSML_SHELL)
    assert len(calls) == 1
    tool, args, raw = calls[0]
    assert tool == "shell"
    assert args["command"] == "ls -la /tmp"
    assert "invoke" in raw


def test_parse_dsml_inline_extracts_command():
    calls = _parse_minimax_tool_call(_DSML_INLINE)
    assert len(calls) == 1
    tool, args, _raw = calls[0]
    assert tool == "shell"
    assert args["command"] == "git status"


# ── _strip_minimax_tool_calls ──────────────────────────────────────────────


def test_strip_removes_dsml_markup():
    cleaned = _strip_minimax_tool_calls(_DSML_SHELL)
    assert "DSML" not in cleaned
    assert "invoke" not in cleaned
    assert "parameter" not in cleaned
    assert "ls -la" not in cleaned  # the command is consumed, not echoed


def test_strip_keeps_surrounding_text():
    text = "Here is the result. " + _DSML_INLINE + " Done."
    cleaned = _strip_minimax_tool_calls(text)
    assert "Here is the result." in cleaned
    assert "Done." in cleaned
    assert "invoke" not in cleaned


# ── _is_tool_talk ──────────────────────────────────────────────────────────


def test_is_tool_talk_recognizes_dsml():
    # The recovery path must flag DSML markup so it isn't streamed raw
    # if interception somehow fails.
    assert _is_tool_talk(_DSML_SHELL) is True
    assert _is_tool_talk(_DSML_INLINE) is True


def test_is_tool_talk_still_ignores_plain_text():
    assert _is_tool_talk("the sky is blue today") is False
