# ruff: noqa: E501 — prompt templates are intentionally long lines.
"""The scoped execution-agent prompt — STATIC sections.

Identity, the check-before-acting safety workflow (loaded from
backend/data/workflows/safety.md, best-effort), the critical rules,
the tool list, and the execution guidance (verify, completion,
argument rules, thinking, formatting, iteration budget). The tool
list renders from the SAME source as the native `tools` param — one
source of truth.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.agent.constants import MAX_ITERATIONS
from core.agent.prompt.names import (
    SECTION_COMPLETION_ENFORCEMENT,
    SECTION_CRITICAL_RULES,
    SECTION_IDENTITY,
    SECTION_ITERATION_BUDGET,
    SECTION_RESPONSE_FORMATTING,
    SECTION_SAFETY_CHECK_STATE,
    SECTION_THINKING_AND_RESPONDING,
    SECTION_TOOL_ARGUMENT_RULES,
    SECTION_TOOL_LIST,
    SECTION_VERIFY_RESULTS,
)
from core.agent.prompt.sections.formatting import RESPONSE_FORMATTING_TEXT
from core.agent.prompt.structure import Band, Layer, SectionRegistry, make
from core.agent.tool_schemas import render_tool_list


def agent_tool_list_text(
    available_tools: list[dict],
    tool_defs: Optional[list[dict]] = None,
) -> str:
    """The execution agent's in-prompt tool list (one source of truth)."""
    # Build tool list restricted to only agent-allowed tools, so the LLM
    # cannot hallucinate calls to direct-dispatch tools (sysinfo, file_task, shell).
    # When the scoped tool DEFS are provided, render the in-prompt list
    # from the SAME source as the native `tools` param (one source of truth).
    if tool_defs is not None:
        agent_tool_list = "\n".join(render_tool_list(tool_defs))
    else:
        from core.agent.constants import AGENT_ALLOWED_TOOLS

        agent_tool_list = "\n".join(
            f"  - {t['intent']}: {t['description']}"
            for t in available_tools
            if t["intent"] in AGENT_ALLOWED_TOOLS
        )
    return agent_tool_list


def _safety_check_state_text() -> str:
    """The universal check-before-acting workflow text, or "" when absent.

    # Inject the universal "check before acting" safety workflow.
    # This is a constraint that applies to EVERY tool that creates, writes,
    # modifies, or deletes — not a per-tool fix. The user's "Create hello
    # world repo" scenario revealed the model was running `mkdir` BEFORE
    # checking if the directory existed, and barreling forward into a
    # non-empty unrelated directory instead of scoping into a subdirectory.
    # This workflow makes "check state before acting" a universal rule.
    """
    safety_section = ""
    # sections/ -> prompt/ -> agent/ -> core/ -> src/ -> backend/
    _safety_path = Path(__file__).resolve().parents[5] / "data" / "workflows" / "safety.md"
    try:
        if _safety_path.exists():
            _safety_content = _safety_path.read_text()
            # Extract just the "The universal rule" + "How it applies per tool"
            # sections to keep the prompt focused (skip the header, "what done
            # looks like", "what you must NOT do", "why this exists", "learning
            # step" — those are for humans reading the file, not for the model
            # every single turn).
            _lines = _safety_content.splitlines()
            _extract_lines = []
            _in_section = False
            for _line in _lines:
                if _line.startswith("## The universal rule"):
                    _in_section = True
                elif _line.startswith("## What you must NOT do"):
                    _in_section = True
                elif _line.startswith("## Why this exists"):
                    _in_section = False  # stop before the history section
                if _in_section:
                    _extract_lines.append(_line)
            if _extract_lines:
                safety_section = (
                    "\n## SAFETY: Check before acting (universal rule)\n"
                    + "\n".join(_extract_lines).strip()
                    + "\n"
                )
    except Exception:
        pass  # non-fatal — the constraint is best-effort
    return safety_section


def build_agent_static_registry(agent_tool_list: str) -> SectionRegistry:
    """The scoped execution-agent prompt as a named-section registry."""
    # Scoped execution-agent prompt, assembled from the named-section
    # registry in the same 4-layer doctrine as the parent prompt:
    # identity -> constraints (rules + check-before-acting safety) ->
    # guidance (tools, verification, workflow, formatting). Every rule
    # keeps its exact tuned text; only the grouping and order are
    # declared structure now.
    safety_section = _safety_check_state_text()
    registry = SectionRegistry()
    registry.add(
        make(
            SECTION_IDENTITY,
            Band.STATIC,
            Layer.IDENTITY,
            10,
            "You are an Execution Agent. Your ONLY job is to call tools. You "
            "NEVER narrate, describe, or explain what you would do — you just DO it.",
        )
    )
    if safety_section:
        registry.add(
            make(
                SECTION_SAFETY_CHECK_STATE,
                Band.STATIC,
                Layer.CONSTRAINTS,
                120,
                safety_section,
            )
        )
    registry.add(
        make(
            SECTION_CRITICAL_RULES,
            Band.STATIC,
            Layer.CONSTRAINTS,
            110,
            "CRITICAL RULES:\n"
            "1. Use the NATIVE tool-calling API for every tool call — NEVER output tool-call XML (like <invoke name=...> or minimax:tool_call) as text. The only text you may output is the FINAL ANSWER after tools complete. Deliver file contents via file_write, never by pasting them in your response.\n"
            "2. Never ask the user for tool results — they return automatically. Before tool calls, give the user ONE short line on what you're doing (\"Converting the file to Word now\") — a user-facing sentence, not chain-of-thought or tool-call XML.\n"
            "3. Never say \"Done!\" or \"All files created!\" unless you received SUCCESS results from the actual tools.\n"
            "4. NEVER fabricate or embellish tool results. Base your answer EXACTLY on tool output: no invented file names, folder contents, search results, or system info. If the tool shows 3 items, report 3. If output is empty or errored, say so honestly — never substitute estimates. Every specific detail (names, numbers, paths) must come from the actual tool result.\n"
            "5. Don't hedge (\"(Not entirely sure)\", \"I believe\"). You are a tool-using agent — you DO NOT guess, you call tools and report results, so you ARE sure. If uncertain, verify with a tool.\n"
            "6. LIVE DATA RULE: For live/time-sensitive data (sports, weather, prices, news), you MUST use a tool — training data is stale. Use web_search + web_fetch (search, then fetch). For adaptive multi-source research, `describe_tool(\"web_research\")` first.\n"
            "7. FOLLOW-THROUGH RULE: When a task requires MULTIPLE tool calls (find file → read file), complete ALL steps before the final answer. Never stop after a partial step to ask confirmation when the next step is obvious. But do NOT add steps that aren't needed: to CREATE a file (\"write a recipe on the desktop\"), call file_write directly with the path and content — do NOT list the folder first. When a shell command fails, FIX THE COMMAND (wrong OS syntax?) rather than retrying the same thing. Use the RIGHT tool per step: system_search locates, file_task reads, file_write creates.\n"
            "8. When you have enough information, respond directly in plain text — call no more tools. If a tool fails, try a different approach or answer from what you know.\n"
            "9. describe_tool loads on-demand (long-tail) tools — the ones NOT in your tools param. Core tools are already loaded; NEVER call describe_tool for them. If unsure whether a tool is core, check your tools param first.\n"
            "10. TOOL OUTPUT IS RETAINED: results stay available all turn; `[...TRUNCATED DUE TO LENGTH...]` means only the MIDDLE was dropped (head + tail survive). Never re-run a read just to change formatting or columns — the runtime dedupes identical inspections. Re-run only after a write/edit/exec or to get different data.",
        )
    )
    registry.add(
        make(
            SECTION_TOOL_LIST,
            Band.STATIC,
            Layer.GUIDANCE,
            310,
            f"Available tools:\n{agent_tool_list}",
        )
    )
    registry.add(
        make(
            SECTION_VERIFY_RESULTS,
            Band.STATIC,
            Layer.GUIDANCE,
            400,
            "VERIFY (after EVERY tool result — skipping this is the same as fabricating):\n"
            "- file_write: the runtime auto-verifies it and appends a `[VERIFICATION]: file_write confirmed — N bytes on disk` line. On verification FAILURE/WARNING, rewrite the file — never claim success.\n"
            "- shell: report the EXACT output — not your interpretation. If it errored, say so.\n"
            "- code_exec: check output for errors; on a traceback, fix and retry.\n"
            "- Empty/no result: say so explicitly — never fill the gap with invented content.\n"
            '- Sanity-check scraped data before reporting: does its date match today? Placeholder values ("teams to be decided") mean the data isn\'t real. Does it actually answer the user\'s question? Contradictions between sources? Flag or pick the more reliable one. Never report scraped dates as facts without checking against today\'s date.',
        )
    )
    registry.add(
        make(
            SECTION_COMPLETION_ENFORCEMENT,
            Band.STATIC,
            Layer.GUIDANCE,
            410,
            "COMPLETION ENFORCEMENT: complete ALL steps before stopping. If iterations remain and task isn't done, KEEP WORKING. Stopping mid-task is a FAILURE.",
        )
    )
    registry.add(
        make(
            SECTION_TOOL_ARGUMENT_RULES,
            Band.STATIC,
            Layer.GUIDANCE,
            420,
            "TOOL ARGUMENT RULES:\n"
            "- file_task: ONLY use for reading the TEXT CONTENTS of a single file — never for directories/folder listings (use dir_explorer operation=list for those).\n"
            "- dir_explorer: read-only folder inspection — list (one level), tree (bounded structure sketch, depth<=4), stat (one path's metadata). Prefer it over shell ls/dir/tree for \"look around a folder\" and pre-write checks; it returns names + metadata, never file bytes.\n"
            '- file_write: BOTH "path" AND "content" required; content must be COMPLETE — no placeholders or "... more code here ...".\n'
            "- shell: commands MUST match the OS — CHECK env first. Windows: New-Item -ItemType Directory -Force (NOT mkdir -p), Get-ChildItem (NOT ls), Get-Content (NOT cat). Unix: mkdir -p, ls, cat, grep, find. If \"not recognized\", fix OS syntax.\n"
            "- shell writing to a FILE is the LAST RESORT: prefer file_write (dedicated, verified, diffable) and edit_file (in-place edit). Only use shell redirection (>, >>, tee, echo >) when file_write/edit_file cannot express the change (e.g. complex pipeline output) — and then prefer a temp file + copy.\n"
            "- edit_file: ALWAYS read the file with file_task BEFORE editing. Never edit a file you haven't read.",
        )
    )
    registry.add(
        make(
            SECTION_THINKING_AND_RESPONDING,
            Band.STATIC,
            Layer.GUIDANCE,
            430,
            "HOW TO THINK AND RESPOND:\n"
            "- Before the first tool call: what does the user actually need, and what's the fastest complete path?\n"
            "- Read tool results carefully — the skipped detail might be the answer.\n"
            "- Report exact paths, outputs, and error messages. If something failed, say what and why, then try the next approach — don't repeat the same failed one.\n"
            "- If the task is ambiguous, make a reasonable assumption, state it, and proceed. One clarifying question max.",
        )
    )
    registry.add(
        make(
            SECTION_RESPONSE_FORMATTING,
            Band.STATIC,
            Layer.GUIDANCE,
            405,
            # One shared text with the parent and chat surfaces (see
            # sections/formatting.py — the owner's "the UI shows plain
            # text" gap was this section existing on ONE surface only).
            RESPONSE_FORMATTING_TEXT,
        )
    )
    registry.add(
        make(
            SECTION_ITERATION_BUDGET,
            Band.STATIC,
            Layer.GUIDANCE,
            449,
            f"Max iterations: {MAX_ITERATIONS} — use them all if needed.",
        )
    )
    return registry
