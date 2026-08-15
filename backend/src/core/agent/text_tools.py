"""
Text-level helpers for the agent loop (Session 129 decomposition).

Extracted from ``core/agent/loop.py`` — pure, stateless text functions with
no dependency on the AgentLoop class:

* ``_parse_plan_steps`` / ``_is_filler_step`` — parse the planner's
  UNDERSTANDING/STEPS format into todo steps, dropping generic filler.
* MiniMax / DeepSeek DSML tool-call XML interception:
  ``_normalize_dsml``, ``_parse_minimax_tool_call``, ``_strip_minimax_tool_calls``,
  ``_has_minimax_tool_call`` — models sometimes emit tool calls as inline
  XML instead of the structured ``tool_calls`` API; these detect, parse, and
  strip that markup so the call is EXECUTED (never streamed as the answer).
* ``_truncate_observation`` — bound a single observation entry for the
  running context log.
* ``_is_tool_talk`` / ``_TOOL_TALK_PATTERNS`` / ``_MAX_TOOL_TALK_RECOVERIES`` —
  detect the "small model narrates tool intent instead of calling" failure
  mode so the leaked text can be suppressed and retried.
* ``_extract_tool_input`` — normalize a tool's argument dict into the single
  string the dispatch system expects.

``core/agent/loop.py`` re-imports every symbol here for backward
compatibility (tests and callers import these helpers from ``core.agent.loop``).
"""

from __future__ import annotations

import json
import re

from core.agent.constants import OBS_LOG_MAX_CHARS

# ── Plan parsing ────────────────────────────────────────────────────────────


def _parse_plan_steps(plan_text: str) -> list[str]:
    """Parse the UNDERSTANDING/WHAT I KNOW/WHAT I'LL VERIFY/STEPS/ARGS_PRECHECK plan format.

    The planning prompt asks the model to respond with:
        UNDERSTANDING: [what the user needs]
        WHAT I KNOW: [relevant context]
        WHAT I'LL VERIFY: [verification plan]
        STEPS:
        1. [step description]
        2. [next step]
        ARGS_PRECHECK: [verification]

    This extracts the numbered steps so they can be shown as todos.
    """
    steps: list[str] = []
    in_steps = False
    for line in plan_text.split("\n"):
        stripped = line.strip()
        if stripped.upper().startswith("STEPS"):
            in_steps = True
            continue
        if stripped.upper().startswith("ARGS_PRECHECK"):
            in_steps = False
            continue
        if in_steps and stripped:
            # Match numbered steps: "1. Do something" or "1) Do something"
            match = re.match(r"^\d+[\.\)]\s*(.+)", stripped)
            if match:
                step = match.group(1).strip()
                if not _is_filler_step(step):
                    steps.append(step)
    return steps


def _is_filler_step(step: str) -> bool:
    """Session 122: drop generic filler steps the planner sometimes emits
    ("Run the shell action", "Verify the result") that carry no concrete
    command, path, or tool — they'd pollute the Todos checklist with noise.

    Conditional steps ("If X, then Y") and the final report step are never
    dropped — they are exactly the goal-level detail a real plan needs."""
    if len(step) < 15:
        return True
    lowered = step.lower()
    # Exempt conditional / parse / report steps — they carry structure, not
    # noise, even without a literal command in them.
    if any(m in lowered for m in (" if ", "→", "otherwise", "unless", "proceed", "empty")):
        return False
    generic_prefixes = (
        "verify the", "verify and", "analyze the output", "analyze and",
        "run the command", "run the shell", "run the action", "execute the command",
        "execute the shell", "capture the", "report the result", "report the findings",
        "provide the requested", "prepare the", "present the information",
        "present a", "synthesize a", "synthesize the", "done", "check the output",
    )
    if lowered.startswith(generic_prefixes):
        return True
    # A step with no tool-name/command token is suspect: must reference one
    # of the concrete tools, a quoted command, or be a final report step.
    tool_token = re.compile(
        r"(shell|git|file|web|code|memory|sysinfo|grep|read|write|edit|"
        r"search|fetch|browse|process|diagnos|`[^`]+`)"
    )
    if tool_token.search(lowered):
        return False
    report_token = re.compile(r"(return|report|summar|give|tell).{0,40}(user|result|answer|diff|change)")
    if report_token.search(lowered):
        return False
    return True


# ── Text-level tool call interception (MiniMax XML + DeepSeek DSML) ──────────
# MiniMax M2.5 and similar models sometimes generate tool calls as inline XML
# in the text content instead of using the structured tool_calls API format.
# Patterns like:
#   minimax:tool_call <invoke name="web_search"><parameter name="text">query</parameter></invoke></minimax:tool_call>
#   <invoke name="web_search"><parameter name="query">query</parameter></invoke>
# These must be intercepted, parsed, and actually EXECUTED — not just stripped.
# Without interception, the tool never runs and the model fabricates results.

_MINIMAX_TOOL_CALL_RE = re.compile(
    r"minimax:tool_call\s*"
    r"<invoke\s+name=[\"']([^\"']+)[\"']\s*>"
    r"(.*?)"
    r"</invoke>"
    r"\s*</minimax:tool_call>",
    re.DOTALL | re.IGNORECASE,
)

_STANDALONE_INVOKE_RE = re.compile(
    r"<invoke\s+name=[\"']([^\"']+)[\"']\s*>"
    r"(.*?)"
    r"</invoke>",
    re.DOTALL | re.IGNORECASE,
)

# Bare <tool_call> format (Session 195): the model emits
#   <tool_call>web_search<arg_key>query</arg_key><arg_value>Kitengela ...</arg_value></tool_call>
# instead of the structured tool_calls API or the invoke/parameter form.
# This leaked RAW into the chat bubble (transcript: "whats the weather like
# in Kitengela now?" → intent misrouted to CHAT → the DIRECT path has no
# tool interception for this format → the full XML streamed as the answer).
_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*(.*?)</tool_call>",
    re.DOTALL | re.IGNORECASE,
)

_ARG_KEY_VALUE_RE = re.compile(
    r"<arg_key>\s*([^<]+?)\s*</arg_key>\s*<arg_value>\s*(.*?)\s*</arg_value>",
    re.DOTALL | re.IGNORECASE,
)

# DSML (DeepSeek Markup Language) tool-call tags use a fullwidth-bar prefix
# (U+FF5C): <｜DSML｜invoke name="shell"> with a `string="true"` attribute on
# <｜DSML｜parameter>. Normalize the prefix away so the existing invoke/parameter
# regexes handle them, and allow extra attributes on <parameter>.
_DSML_PREFIX_RE = re.compile(r"<｜DSML｜|</｜DSML｜", re.IGNORECASE)


def _normalize_dsml(text: str) -> str:
    """Convert DeepSeek DSML tool-call markup to standard <invoke>/<parameter> form.

    DSML wraps tags in a fullwidth-bar prefix:
        <｜DSML｜tool_calls>
          <｜DSML｜invoke name="shell">
            <｜DSML｜parameter name="command" string="true">cmd</｜DSML｜parameter>
          </｜DSML｜invoke>
        </｜DSML｜tool_calls>
    becomes:
        <tool_calls>
          <invoke name="shell">
            <parameter name="command" string="true">cmd</parameter>
          </invoke>
        </tool_calls>
    which the existing MiniMax-style regexes already parse.
    """
    if not text or "｜DSML｜" not in text:
        return text
    return _DSML_PREFIX_RE.sub(lambda m: "</" if m.group(0).startswith("</") else "<", text)


_PARAM_RE = re.compile(
    r"<parameter\s+name=[\"']([^\"']+)[\"'][^>]*>"
    r"(.*?)"
    r"</parameter>",
    re.DOTALL | re.IGNORECASE,
)

# Partial/streaming tool call patterns — catches incomplete XML that arrives
# across multiple streaming chunks
_MINIMAX_PARTIAL_RE = re.compile(
    r"minimax:tool_call\s*<invoke[^>]*>.*",
    re.DOTALL | re.IGNORECASE,
)

_STANDALONE_PARTIAL_RE = re.compile(
    r"<invoke\s+name=[\"'][^\"']+[\"'][^>]*>.*",
    re.DOTALL | re.IGNORECASE,
)


def _parse_minimax_tool_call(text: str) -> list[tuple[str, dict, str]]:
    """
    Parse MiniMax-style tool call XML from text content.

    Returns a list of (tool_name, tool_args, raw_xml) tuples.
    Each tuple represents one tool call found in the text.
    The raw_xml is the full XML string that should be removed from the text.

    Handles two formats:
    1. minimax:tool_call <invoke name="TOOL"><parameter name="ARG">VALUE</parameter></invoke></minimax:tool_call>
    2. <invoke name="TOOL"><parameter name="ARG">VALUE</parameter></invoke>
    """
    calls = []

    # Normalize DeepSeek DSML markup into the standard invoke/parameter form
    # first, so DSML tool calls are intercepted + executed (not streamed as
    # the final answer — Session 127 smoke caught this on zen/deepseek-v4-flash).
    text = _normalize_dsml(text)

    # Format 1: Full minimax:tool_call wrapper
    for m in _MINIMAX_TOOL_CALL_RE.finditer(text):
        tool_name = m.group(1).strip()
        params_xml = m.group(2)
        raw_xml = m.group(0)
        args = {}
        for pm in _PARAM_RE.finditer(params_xml):
            args[pm.group(1).strip()] = pm.group(2).strip()
        calls.append((tool_name, args, raw_xml))

    # Format 2: Standalone <invoke> without minimax:tool_call wrapper
    if not calls:
        for m in _STANDALONE_INVOKE_RE.finditer(text):
            tool_name = m.group(1).strip()
            params_xml = m.group(2)
            raw_xml = m.group(0)
            args = {}
            for pm in _PARAM_RE.finditer(params_xml):
                args[pm.group(1).strip()] = pm.group(2).strip()
            calls.append((tool_name, args, raw_xml))

    # Format 3: bare <tool_call>NAME<arg_key>..</arg_key><arg_value>..</arg_value></tool_call>
    # (Session 195 — see _TOOL_CALL_RE). args use arg_key/arg_value pairs.
    if not calls:
        for m in _TOOL_CALL_RE.finditer(text):
            tool_name = m.group(1).strip()
            args = {}
            for am in _ARG_KEY_VALUE_RE.finditer(m.group(2)):
                args[am.group(1).strip()] = am.group(2).strip()
            calls.append((tool_name, args, m.group(0)))

    return calls


def _strip_minimax_tool_calls_stream(text: str) -> str:
    """Streaming-safe MiniMax/DSML tool-call stripper — PRESERVES whitespace.

    Removes the same tool-call markup as ``_strip_minimax_tool_calls`` but does
    NOT ``.strip()`` the result. The stripping variant must never be applied to
    an individual streamed delta: a model that streams a JSON value token by
    token emits deltas like ``"Respond"``, ``" to"``, ``" a"`` — stripping each
    one removes the leading spaces, so the concatenation collapses to
    ``"Respondtoa"`` (Session 231 bug: spaceless thought process + answer). Use
    this per-chunk; use ``_strip_minimax_tool_calls`` only on a complete text.
    """
    text = _normalize_dsml(text)
    cleaned = _MINIMAX_TOOL_CALL_RE.sub("", text)
    cleaned = _STANDALONE_INVOKE_RE.sub("", cleaned)
    cleaned = _TOOL_CALL_RE.sub("", cleaned)
    cleaned = _MINIMAX_PARTIAL_RE.sub("", cleaned)
    cleaned = _STANDALONE_PARTIAL_RE.sub("", cleaned)
    # Also strip bare minimax:tool_call keyword
    cleaned = re.sub(r"minimax:tool_call\b", "", cleaned, flags=re.IGNORECASE)
    # Strip DSML tool_calls wrapper tags (left over after normalizing the
    # inner invoke/parameter tags away)
    cleaned = re.sub(r"<\s*/?\s*tool_calls\s*>", "", cleaned, flags=re.IGNORECASE)
    # Collapse runs of blank lines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def _strip_minimax_tool_calls(text: str) -> str:
    """Remove all MiniMax tool call XML from a COMPLETE text, trimming edges.

    Whitespace-trimming — safe only on a full text, never on a streamed delta
    (see ``_strip_minimax_tool_calls_stream``).
    """
    return _strip_minimax_tool_calls_stream(text).strip()


def _has_minimax_tool_call(text: str) -> bool:
    """Quick check if text contains a MiniMax-style tool call pattern."""
    text = _normalize_dsml(text)
    return bool(
        _MINIMAX_TOOL_CALL_RE.search(text)
        or _STANDALONE_INVOKE_RE.search(text)
        or _TOOL_CALL_RE.search(text)
    )


# ── Deterministic system-query guard ─────────────────────────────────────────

_CURRENT_SYSTEM_QUERY_RE = re.compile(
    r"(?:\bwhat(?:'s|s)?\s+(?:the\s+)?(?:current\s+)?(?:time|date|day)\b"
    r"|\bwhat\s+is\s+(?:the\s+)?(?:current\s+)?(?:time|date|day)\b"
    r"|\bwhat\s+time\s+is\s+it\b"
    r"|\bwhat\s+day\s+is\s+it\b"
    r"|\bcurrent\s+(?:time|date|day)\b"
    r"|\btoday'?s\s+date\b)",
    re.IGNORECASE,
)


def _is_current_system_query(text: str) -> bool:
    """Return whether a request needs the authoritative local clock.

    This is intentionally narrow: it catches current time/date/day questions
    but does not classify arbitrary system or shell requests.
    """
    return bool(_CURRENT_SYSTEM_QUERY_RE.search(text or ""))


def _normalize_system_tool_call(
    user_question: str,
    tool_name: str,
    tool_args: dict,
) -> tuple[str, dict, bool]:
    """Correct a shell call when the parent is answering a clock question.

    Small models sometimes emit ``shell(command='Get-Date')`` even though the
    request is a local time query. The shell contract correctly rejects that
    natural-language/legacy shape, but making the model spend an iteration on
    the rejected call is avoidable. Keep the correction inside the parent loop
    so the request remains agentic and the action is observable as ``sysinfo``.
    """
    if tool_name == "shell" and _is_current_system_query(user_question):
        return "sysinfo", {"query": user_question}, True
    return tool_name, tool_args, False


def _authoritative_sysinfo_answer(content: str, user_question: str) -> str:
    """Return the exact clock line for a current time/date answer.

    The local sysinfo tool is the source of truth. A smaller model may turn
    ``August 14`` into ``August 1`` during a final paraphrase, so current clock
    queries terminate with the verified line instead of asking the model to
    recalculate it.
    """
    if not _is_current_system_query(user_question):
        return content.strip()
    for line in (content or "").splitlines():
        if line.strip().lower().startswith("current date/time:"):
            return line.strip()
    return (content or "").strip()


# ── Observation truncation ────────────────────────────────────────────────────


def _truncate_observation(obs: str, max_chars: int = OBS_LOG_MAX_CHARS) -> str:
    """Trim a single observation entry for the running context log."""
    if len(obs) <= max_chars:
        return obs
    half = max_chars // 2
    return obs[:half] + f"\n… [{len(obs) - max_chars} chars truncated] …\n" + obs[-half:]


# ── Tool-talk detection ────────────────────────────────────────────────────────
# Small models (≤3B) sometimes narrate their intent to use a tool instead of
# actually invoking it.  These patterns detect that failure mode so we can
# suppress the leaked text and retry with a corrective hint.

_TOOL_TALK_PATTERNS = [
    re.compile(r"please provide (me with |the )?tool results?", re.IGNORECASE),
    re.compile(r"i need (you to |the )?tool results?", re.IGNORECASE),
    re.compile(r"provide (me with |the )?results? of (the )?tool", re.IGNORECASE),
    re.compile(r"i (will|would|need to|am going to) (use|call|invoke|run) (the )?(\w+) tool", re.IGNORECASE),
    re.compile(r"let me (use|call|invoke|run) (the )?(\w+) tool", re.IGNORECASE),
    re.compile(r"i('ll| will) (need to |try to )?(search|look up|execute|run|query)", re.IGNORECASE),
    re.compile(r"to answer (this|your) (question|request),? i (will|would|need to)", re.IGNORECASE),
    re.compile(r"<tool>|<action>|<function>", re.IGNORECASE),
    re.compile(r"tool_call|function_call|invoke_tool", re.IGNORECASE),
    # DeepSeek DSML tool-call markup — must be intercepted, not streamed
    re.compile(r"<｜DSML｜\s*(tool_calls|invoke)\b", re.IGNORECASE),
    # MiniMax-style: "I will call the web_search tool" followed by XML
    re.compile(r"i('ll| will) (now |then )?(call|use|invoke) (the )?\w+ (tool|function)", re.IGNORECASE),
    # v0.7: Additional plain-text tool narration patterns — models like MiniMax M2.5
    # sometimes describe what they would do instead of actually doing it.
    # These catch "I'm searching for...", "Let me look that up...", "Searching..."
    # followed by fabricated results from training data.
    re.compile(r"(i'm|i am) (now )?(searching|looking up|fetching|checking|finding)", re.IGNORECASE),
    re.compile(r"(searching|fetching|looking up|checking).{0,30}(for|on|in|about)\b", re.IGNORECASE),
    re.compile(r"let me (search|look|check|find|fetch|browse)", re.IGNORECASE),
    re.compile(r"i('ll| will) (search|look|check|find|fetch) (the |online |the web |on )?", re.IGNORECASE),
    re.compile(r"\[tool_call\]|\[search\]|\[tool\]|\[shell\]|\[bash\]|\[cmd\]|\[powershell\]", re.IGNORECASE),
    re.compile(r"\bsearching\.{3,}\b", re.IGNORECASE),  # "Searching..." theatrical animation
    re.compile(r"\bfetching\.{3,}\b", re.IGNORECASE),
    re.compile(r"\blooking up\.{3,}\b", re.IGNORECASE),
]

_MAX_TOOL_TALK_RECOVERIES = 2


def _is_tool_talk(text: str) -> bool:
    """Return True if the model is narrating tool intent instead of calling tools."""
    if not text or len(text.strip()) < 10:
        return False
    return any(p.search(text) for p in _TOOL_TALK_PATTERNS)


# ── Tool argument → single-input extraction ───────────────────────────────────


def _extract_tool_input(tool_name: str, tool_args: dict) -> str:
    """
    Extract a single string 'input' from the tool's arguments.

    Different tools structure their arguments differently.  The dispatch
    system expects a single string input.  This function normalises the
    dict returned by Ollama's tool calling into that string.

    For tools with a single required parameter, we use that value.
    For tools with multiple parameters, we join them into a
    semi-structured string that the tool dispatcher can parse.
    """
    if tool_name == "web_search":
        return tool_args.get("query", "")
    elif tool_name == "web_fetch":
        return tool_args.get("url", "")
    elif tool_name == "code_exec":
        return tool_args.get("code", "")
    elif tool_name == "file_write":
        # file_write dispatcher expects "path:\n\ncontent" format
        path = tool_args.get("path", "")
        content = tool_args.get("content", "")
        return f"{path}:\n\n{content}"
    elif tool_name == "edit_file":
        # edit_file: serialise args as JSON for the dispatch layer
        return json.dumps(tool_args, ensure_ascii=False)
    elif tool_name == "file_task":
        return tool_args.get("path", "")
    elif tool_name == "find_path":
        # find_path dispatcher expects JSON-encoded args (name/root/max_depth/
        # max_results) — same pattern as git/delegate. The tool parses it back.
        return json.dumps(tool_args, ensure_ascii=False)
    elif tool_name == "shell":
        return tool_args.get("command", "")
    elif tool_name == "memory_op":
        operation = tool_args.get("operation", "recall")
        content = tool_args.get("content", "")
        return f"{operation} {content}".strip()
    elif tool_name == "sysinfo":
        return tool_args.get("query", "")
    elif tool_name == "observe":
        # observe takes a single query string, same as sysinfo.
        return tool_args.get("query", "")
    elif tool_name == "calculator":
        # calculator takes a single expression string, same as observe.
        return tool_args.get("expression", "")
    elif tool_name == "csv":
        # csv dispatcher expects JSON-encoded args (path/max_rows/max_cols)
        # — same pattern as find_path/git. The tool parses it back.
        return json.dumps(tool_args, ensure_ascii=False)
    elif tool_name == "json":
        # json dispatcher expects JSON-encoded args (source/query/max_items)
        # — same pattern as find_path/git. The tool parses it back.
        return json.dumps(tool_args, ensure_ascii=False)
    elif tool_name == "sql":
        # sql dispatcher expects JSON-encoded args (path/query/max_rows)
        # — same pattern as find_path/git. The tool parses it back.
        return json.dumps(tool_args, ensure_ascii=False)
    elif tool_name == "delegate":
        # delegate dispatcher expects JSON-encoded args (target_agent + task)
        # — same pattern as edit_file. The delegate tool parses it back.
        return json.dumps(tool_args, ensure_ascii=False)
    elif tool_name == "delegate_parallel":
        # delegate_parallel dispatcher expects JSON-encoded args (targets
        # array) — same pattern as delegate. The tool parses it back.
        return json.dumps(tool_args, ensure_ascii=False)
    elif tool_name == "delegate_inline":
        # delegate_inline dispatcher expects JSON-encoded args
        # (target_agent + task) — same pattern as delegate. The tool
        # parses it back.
        return json.dumps(tool_args, ensure_ascii=False)
    elif tool_name == "propose_str_replace":
        # propose_str_replace dispatcher expects JSON-encoded args
        # (path/action/search/replace) — same pattern as edit_file.
        return json.dumps(tool_args, ensure_ascii=False)
    elif tool_name == "propose_write_file":
        # propose_write_file expects "path:\n\ncontent" — same as file_write.
        path = tool_args.get("path", "")
        content = tool_args.get("content", "")
        return f"{path}:\n\n{content}"
    elif tool_name == "apply_proposed_edit":
        # apply_proposed_edit takes a single path argument.
        return tool_args.get("path", "")
    elif tool_name == "add_subgoal":
        # add_subgoal takes a single description argument.
        return tool_args.get("description", "")
    elif tool_name == "update_subgoal":
        # update_subgoal dispatcher expects JSON-encoded args (id/status/notes).
        return json.dumps(tool_args, ensure_ascii=False)
    elif tool_name == "create_plan":
        # create_plan dispatcher expects JSON-encoded args (steps array or plan).
        return json.dumps(tool_args, ensure_ascii=False)
    elif tool_name == "skill":
        # skill takes a single skill_name argument.
        return tool_args.get("skill_name", "")
    elif tool_name == "best_of_n_edit":
        # best_of_n_edit dispatcher expects JSON-encoded args
        # (file_path/instruction/n/strategies).
        return json.dumps(tool_args, ensure_ascii=False)
    elif tool_name == "git":
        # git dispatcher expects JSON-encoded args (operation + params)
        # — same pattern as delegate/edit_file. The git tool parses it back.
        return json.dumps(tool_args, ensure_ascii=False)
    elif tool_name == "process":
        # process dispatcher expects JSON-encoded args (operation + params)
        # — same pattern as git/delegate. The process tool parses it back.
        return json.dumps(tool_args, ensure_ascii=False)
    elif tool_name == "diagnostics":
        # diagnostics dispatcher expects JSON-encoded args (operation + text/path)
        return json.dumps(tool_args, ensure_ascii=False)
    elif tool_name == "browse":
        # browse dispatcher expects JSON-encoded args so action-specific
        # options (selector, filters, clear/json flags) survive dispatch.
        return json.dumps(tool_args, ensure_ascii=False)
    else:
        # Fallback: join all values
        return " ".join(str(v) for v in tool_args.values() if v)
