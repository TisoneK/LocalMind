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


# ── Creation-commitment narration  ────────────────────────────
# Live trace on deepseek-v4-flash (the user's "create a project" session):
# after the directory was made, the model ended the turn with "Now I'll
# create the project files — a modular Python project…" — a commitment to
# file creation with no file_write/file_task call, so the turn ended with
# zero files. The detector must flag creation commitments (the recovery
# nudge then anchors the model back to the task) without false-triggering
# on legitimate prose that describes a non-file deliverable.


def test_is_tool_talk_detects_creation_commitment():
    # The exact live-trace ending: "Now I'll create the project files …"
    assert _is_tool_talk("Now I'll create the project files with a modular structure") is True
    assert _is_tool_talk("I will create the project files next") is True
    assert _is_tool_talk("Let me create the project files now") is True
    assert _is_tool_talk("I'm going to write the module files now") is True
    # Live-trace variant with an adjective between article and noun:
    # "Now I'll write the source modules and tests" (iter-7 of the second trace)
    assert _is_tool_talk("Now I'll write the source modules and tests") is True
    assert _is_tool_talk("I will build the new project package") is True
    # Hyphenated/dotted adjectives. The user's live
    # Windows trace ended with "Let me create the path-test folder and the two
    # files" (recon only, no file_write) and the panel showed 2/2 as if the
    # task were done — the single-adjective group was \w-only, so "path-test"
    # and "a.txt" defeated the detector and the commitment streamed as the
    # final answer. Widened to [\w.-].
    assert _is_tool_talk("Let me create the path-test folder and the two files") is True
    assert _is_tool_talk("Let me write the a.txt file") is True


def test_is_tool_talk_ignores_creation_of_non_files():
    # Legitimate final answers describing a non-file deliverable must NOT be
    # intercepted as tool-talk.
    assert _is_tool_talk("I'll create a summary of the search results") is False
    assert _is_tool_talk("I'll create a table for you") is False
    # Past tense = the work is done, not a commitment.
    assert _is_tool_talk("I created the project files") is False


# ── Bare <tool_call> format  ──────────────────────────────────
# The live leak: the model emitted
#   <tool_call>web_search<arg_key>query</arg_key><arg_value>Kitengela ...</arg_value></tool_call>
# which neither the minimax:tool_call nor the standalone <invoke> patterns
# matched — so on the no-tools DIRECT path it streamed RAW as the answer.

_TOOL_CALL_WS = (
    "<tool_call>web_search<arg_key>query</arg_key>"
    "<arg_value>Kitengela Kenya current weather temperature conditions</arg_value>"
    "</tool_call>"
)


def test_has_detects_bare_tool_call():
    assert _has_minimax_tool_call(_TOOL_CALL_WS) is True
    assert _has_minimax_tool_call(
        "<tool_call>shell<arg_key>command</arg_key><arg_value>ls -la</arg_value></tool_call>"
    ) is True


def test_has_ignores_plain_text_for_tool_call():
    assert _has_minimax_tool_call("just some words about weather") is False


def test_parse_bare_tool_call_web_search():
    calls = _parse_minimax_tool_call(_TOOL_CALL_WS)
    assert len(calls) == 1
    tool, args, raw = calls[0]
    assert tool == "web_search"
    assert args["query"] == "Kitengela Kenya current weather temperature conditions"
    assert "tool_call" in raw


def test_parse_bare_tool_call_shell():
    calls = _parse_minimax_tool_call(
        "<tool_call>shell<arg_key>command</arg_key><arg_value>ls -la</arg_value></tool_call>"
    )
    assert len(calls) == 1
    tool, args, _raw = calls[0]
    assert tool == "shell"
    assert args["command"] == "ls -la"


def test_parse_bare_tool_call_multiple_args():
    calls = _parse_minimax_tool_call(
        "<tool_call>web_search<arg_key>query</arg_key><arg_value>a b</arg_value>"
        "<arg_key>max_results</arg_key><arg_value>5</arg_value></tool_call>"
    )
    assert len(calls) == 1
    _tool, args, _raw = calls[0]
    assert args == {"query": "a b", "max_results": "5"}


def test_strip_removes_bare_tool_call():
    cleaned = _strip_minimax_tool_calls(_TOOL_CALL_WS)
    assert "tool_call" not in cleaned
    assert "arg_key" not in cleaned
    assert "arg_value" not in cleaned
    assert "Kitengela Kenya" not in cleaned


def test_strip_keeps_surrounding_text_for_tool_call():
    text = "Let me check that. " + _TOOL_CALL_WS + " Done."
    cleaned = _strip_minimax_tool_calls(text)
    assert "Let me check that." in cleaned
    assert "Done." in cleaned
    assert "tool_call" not in cleaned
