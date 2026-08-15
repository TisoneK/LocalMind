"""
GoalInterpreter — deterministic success-criteria fallback (ADR-18 P0+).

PURPOSE
=======
The parent agent's plan may carry explicit `success_criteria` (from the
`create_plan` tool, the loop's `success_criteria=` parameter, or a plan
block). But on free-tier small models the LLM frequently omits them —
leaving `TaskState.success_criteria == []`, which causes the ADR-18 P0/P1
acceptance gate (`core.agent.verify.criteria_gate`,
`agents/{coding,verifier}/is_done.py`) to short-circuit at
`verify.py:354-355` and the model-asserted "done" path runs unchanged.

ADR-18 P0 only wired the gate; it did not guarantee a contract the
gate can check. This module is the contract-side fix: when no explicit
criteria exist, the GoalInterpreter derives them DETERMINISTICALLY from
the routing intent + capability set + first tool args. The LLM is NOT
called again.

DESIGN
======
The interpreter runs inside the parent runtime BEFORE `AgentLoop.run()`
is invoked (so the gate sees the contract from iteration 0). The
legacy request-time dispatcher that used to emit criteria is gone — the
interpreter works from whatever the runtime actually knows: intent,
plan steps, and first tool args.

Two-tier:
  1. If explicit `llm_criteria` are non-empty → use as-is (the caller
     already has a contract; the interpreter is a no-op).
  2. Otherwise → derive 1-3 deterministic criteria per intent, sourced
     from the intent + (where applicable) the first planned tool args.

The derived criteria are always CHECKABLE by `criteria_gate` (which
parses tool evidence for exit codes, file existence, git status, HTTP
codes, error markers). They are conservative — they never make claims
the gate cannot verify.

WHAT THIS DOES NOT DO
====================
- It does NOT replace the LLM planner. When the caller passes explicit
  criteria, those win.
- It does NOT call the LLM. It is purely deterministic, runs in <1ms.
- It does NOT add criteria to pure-chat / trivial turns. If
  `effective_intent == CHAT` or the trivial fast-path applies, return
  `[]` (no contract — matching the existing
  `criteria_gate` short-circuit behavior).
- It does NOT touch the model's own plan text. The structured planner
  DAG (F3) is a separate session.

USAGE
=====
    from core.agent.goal_interpreter import GoalInterpreter

    interpreter = GoalInterpreter()
    criteria = interpreter.interpret(
        message=user_message,
        intent=effective_intent,
        capabilities=capabilities,
        execution_plan_steps=plan_steps,
        llm_criteria=explicit_criteria,
        first_tool_args=_extract_first_tool_args(...),  # optional
    )
    # `criteria` is a list[str] — pass as `success_criteria=` to AgentLoop.run

The parent runtime may use the interpreter when an explicit success
contract is absent; standalone callers can also use this deterministic helper.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from core.agent.constants import Intent

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────

# Bounded output to keep the prompt small (each criterion costs tokens).
_MAX_DERIVED_CRITERIA = 4

# Env switch — lets users disable the deterministic fallback without
# code changes (e.g. to compare LLM-only vs deterministic behavior).
_ENV_DISABLE = "LOCALMIND_GOAL_INTERPRETER_DISABLE"


# ── Intent → criteria templates ──────────────────────────────────────────────
#
# Each template is a list of 1-3 short, checkable statements. The
# statements use placeholders {path}, {command}, {code} that are filled
# from the first tool args when available; otherwise a generic
# intent-level criterion is emitted.
#
# Conservative by design: we only emit criteria the gate CAN check.
# `criteria_gate` (verify.py) recognises:
#   - "file exists at <path>"  → os.path.exists check
#   - "exit code 0"            → exit_code:0 marker in tool output
#   - "no errors in output"    → absence of 'error'/'traceback'/'failed'
#   - "git diff contains <pattern>" → git diff marker
#   - "HTTP 200"               → status marker
# See `core/agent/verify.py:criteria_gate` for the full matcher catalog.

_TEMPLATES: dict[Intent, list[str]] = {
    Intent.FILE_WRITE: [
        "file exists at {path} with content",
    ],
    Intent.FILE_EDIT: [
        "edited file {path} exists",
        "no error markers in the edit tool output",
    ],
    Intent.FILE_TASK: [
        "file content read without error",
    ],
    Intent.CODE_EXEC: [
        "no Python errors in code execution output",
        "exit code 0 from code execution",
    ],
    Intent.SHELL: [
        "no error markers in shell output",
    ],
    Intent.GIT: [
        "git command exit code 0",
    ],
    Intent.WEB_FETCH: [
        "HTTP 200 from the fetched URL",
    ],
    Intent.WEB_SEARCH: [
        "at least one search result returned",
    ],
    Intent.MEMORY_OP: [
        "memory operation completed without error",
    ],
    Intent.PROCESS: [
        "process command exit code 0",
    ],
    Intent.SQL: [
        "SQL query returned rows (or empty set) without error",
    ],
    Intent.CSV: [
        "CSV parsed without error",
    ],
    Intent.JSON: [
        "JSON parsed without error",
    ],
    Intent.CALCULATE: [
        "calculator produced a result without error",
    ],
    Intent.VERIFY: [
        "verification check(s) passed",
    ],
    Intent.DEBUG: [
        "root cause identified with evidence in tool output",
    ],
    Intent.ANALYZE: [
        "analysis produced findings with evidence",
    ],
    Intent.REVIEW: [
        "review produced findings with evidence",
    ],
    Intent.BROWSE: [
        "browser command completed without error",
    ],
    Intent.DIAGNOSTICS: [
        "diagnostics ran without error",
    ],
    Intent.SYSINFO: [
        "system info gathered without error",
    ],
    Intent.FIND_PATH: [
        "path search completed without error",
    ],
    Intent.OBSERVE: [
        "observation gathered without error",
    ],
    # Intents NOT in this map get no derived criteria — matches the
    # existing `criteria_gate` short-circuit behavior. Specifically
    # `CHAT`, `DELEGATE`, `PROPOSE_*`, `ADD_SUBGOAL`, `CREATE_PLAN`,
    # `SKILL`, `BEST_OF_N_EDIT` (none of these are end-user tasks with
    # checkable outcomes — they're orchestration primitives).
}


# ── First-tool-args extractor ────────────────────────────────────────────────
# When a plan block provided `steps[]`, the first
# step often carries the path/command/url the model intends to act on.
# We try to extract it; if we can, we substitute into the template. If
# not, the generic intent-level criterion is used (no substitution).

_PATH_KEYS = ("path", "file_path", "file", "filename")
_COMMAND_KEYS = ("command", "cmd", "shell_command")
_URL_KEYS = ("url", "uri", "link")
_QUERY_KEYS = ("query", "search_query", "q")


def _extract_first_arg(args: Optional[dict[str, Any]], keys: Iterable[str]) -> str:
    """Return the first non-empty string value under any of `keys`."""
    if not args or not isinstance(args, dict):
        return ""
    for k in keys:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:200]
    return ""


def _extract_path(args: Optional[dict[str, Any]]) -> str:
    return _extract_first_arg(args, _PATH_KEYS)


def _extract_command(args: Optional[dict[str, Any]]) -> str:
    return _extract_first_arg(args, _COMMAND_KEYS)


def _extract_url(args: Optional[dict[str, Any]]) -> str:
    return _extract_first_arg(args, _URL_KEYS)


def _extract_query(args: Optional[dict[str, Any]]) -> str:
    return _extract_first_arg(args, _QUERY_KEYS)


def _first_step_args(execution_plan_steps: list[dict]) -> Optional[dict[str, Any]]:
    """Return the args dict of the first plan step, or None."""
    if not execution_plan_steps:
        return None
    for step in execution_plan_steps:
        if isinstance(step, dict):
            args = step.get("args")
            if isinstance(args, dict):
                return args
    return None


# ── Public API ───────────────────────────────────────────────────────────────


@dataclass
class Interpretation:
    """Result of a goal interpretation.

    `criteria` is the final list to set on TaskState — either the LLM's
    own (preferred) or the deterministic fallback (when LLM omitted).
    `source` records where they came from (for tests + telemetry).
    """

    criteria: list[str]
    source: str  # "llm" | "deterministic" | "none"


class GoalInterpreter:
    """Deterministic success-criteria fallback (ADR-18 P0+).

    See module docstring for full design.
    """

    def __init__(self) -> None:
        self._disabled = os.getenv(_ENV_DISABLE, "").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

    @property
    def enabled(self) -> bool:
        return not self._disabled

    def interpret(
        self,
        message: str,
        intent: Optional[Intent],
        capabilities: Optional[list[Any]] = None,
        execution_plan_steps: Optional[list[dict]] = None,
        llm_criteria: Optional[list[str]] = None,
        first_tool_args: Optional[dict[str, Any]] = None,
    ) -> Interpretation:
        """Return the success criteria to attach to TaskState.

        Args:
            message: the raw user message (used only for debugging logs;
                never affects the derived criteria).
            intent: the routing intent (the agent's settled intent).
            capabilities: the capability list (currently unused —
                reserved for future cross-capability criteria).
            execution_plan_steps: the plan steps, used to extract the
                first tool args (path/command/url).
            llm_criteria: criteria the LLM emitted in its
                execution_plan. If non-empty, these win and the
                interpreter is a no-op.
            first_tool_args: optional override — if provided, used
                instead of extracting from execution_plan_steps.

        Returns:
            Interpretation with `criteria` (list[str], may be empty)
            and `source` (one of "llm", "deterministic", "none").
        """
        # 1. If disabled, just pass through whatever the LLM gave us.
        if not self.enabled:
            return Interpretation(
                criteria=list(llm_criteria or []),
                source="llm" if llm_criteria else "none",
            )

        # 2. LLM-emitted criteria always win.
        llm_clean = [
            str(c).strip()
            for c in (llm_criteria or [])
            if isinstance(c, str) and c.strip()
        ]
        if llm_clean:
            return Interpretation(criteria=llm_clean[:_MAX_DERIVED_CRITERIA], source="llm")

        # 3. Otherwise derive deterministically from the intent.
        if intent is None:
            return Interpretation(criteria=[], source="none")

        template = _TEMPLATES.get(intent)
        if not template:
            # Intent not in the map (CHAT, DELEGATE, etc.) → no
            # contract. Matches the existing criteria_gate behavior.
            return Interpretation(criteria=[], source="none")

        # Resolve the first tool args: prefer the explicit override,
        # fall back to extracting from the execution_plan steps.
        args = first_tool_args
        if args is None:
            args = _first_step_args(execution_plan_steps or [])

        path = _extract_path(args)
        command = _extract_command(args)
        url = _extract_url(args)
        query = _extract_query(args)

        derived: list[str] = []
        for tmpl in template:
            try:
                # Substitute the first non-empty variable we have.
                if "{path}" in tmpl:
                    sub = path or "the target file"
                    derived.append(tmpl.format(path=sub))
                elif "{command}" in tmpl:
                    sub = command or "the command"
                    derived.append(tmpl.format(command=sub))
                elif "{url}" in tmpl:
                    sub = url or "the URL"
                    derived.append(tmpl.format(url=sub))
                elif "{query}" in tmpl:
                    sub = query or "the query"
                    derived.append(tmpl.format(query=sub))
                else:
                    derived.append(tmpl)
            except (KeyError, IndexError):
                # Should not happen — template only has {path}/{command}/
                # {url}/{query}, all handled above. Defensive.
                derived.append(re.sub(r"\{[a-z_]+\}", "the target", tmpl))

        # Cap and return.
        return Interpretation(
            criteria=derived[:_MAX_DERIVED_CRITERIA],
            source="deterministic",
        )


# ── Module-level singleton ───────────────────────────────────────────────────
# The interpreter is stateless; one shared instance is fine. Imported by
# the runtime to avoid creating a new object per turn.

_default_interpreter = GoalInterpreter()


def interpret_goal(
    message: str,
    intent: Optional[Intent],
    capabilities: Optional[list[Any]] = None,
    execution_plan_steps: Optional[list[dict]] = None,
    llm_criteria: Optional[list[str]] = None,
    first_tool_args: Optional[dict[str, Any]] = None,
) -> Interpretation:
    """Convenience wrapper around the shared singleton."""
    return _default_interpreter.interpret(
        message=message,
        intent=intent,
        capabilities=capabilities,
        execution_plan_steps=execution_plan_steps,
        llm_criteria=llm_criteria,
        first_tool_args=first_tool_args,
    )
