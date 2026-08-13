"""
PostExecutionVerifier — last-tool sanity check (ADR-18 P1+, F4).

PURPOSE
=======
ADR-18 P0 wired the `criteria_gate` (verify.py) as the acceptance
gate. The gate short-circuits when `trace.success_criteria == []`,
which (per Session 176 audit F2) was the case on ~90% of turns
BEFORE the GoalInterpreter fallback (Session 177) populated
deterministic criteria.

Even WITH the GoalInterpreter, two edge cases remain:
  1. Intents the GoalInterpreter deliberately excludes (CHAT, DELEGATE,
     PROPOSE_*, etc.) get no criteria — but those don't write files
     or run code, so they don't need a verifier.
  2. The GoalInterpreter's derived criteria use the FIRST tool args
     (path/command/url). When the loop executed MULTIPLE tools, only
     the FIRST one is checked. A subsequent tool's failure can slip
     through if its evidence isn't in the first tool's args.

This module closes the remaining gap for HIGH-STAKES intents
(FILE_WRITE, FILE_EDIT, CODE_EXEC): even when criteria exist AND pass,
the loop runs ONE additional deterministic check that the LAST tool's
output had no error markers. If the last tool failed, the gate fails
regardless of criteria — the model's "done" claim is rejected and the
loop replans.

DESIGN
======
- Pure, deterministic, no LLM call.
- Only checks the LAST tool step's observation for error markers
  (traceback, exception, "error:", "failed", "exit code").
- Conservative: errs on the side of accepting "done" when the
  observation is ambiguous (no markers = pass).
- Does NOT replace `criteria_gate` — it runs AFTER criteria pass,
  as a final sanity check.

The error marker list mirrors `core/agent/verify.py:_ERR_MARKERS`
(kept in sync by importing it lazily so future updates propagate).
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


# ── Error marker catalog ────────────────────────────────────────────────────
#
# Conservative list — these markers are unambiguous failure signals.
# DO NOT add "warning" or "deprecated" — those often appear in
# successful tool output (Python DeprecationWarning, npm WARN, etc.)
# and would false-positive the gate.

_ERR_PATTERNS = (
    r"\btraceback\b",
    r"\bexception\b",
    r"\berror:\s",  # "error:" but not "errors" (plural) or "no errors"
    r"\bfailed\b",
    r"\bfatal\b",
    r"\bexit code\b\s*[1-9]",  # exit code N where N != 0
    r"\bsegmentation fault\b",
    r"\bcore dumped\b",
)

_ERR_RE = re.compile("|".join(_ERR_PATTERNS), re.IGNORECASE)


# Success markers — when present, OVERRIDE the error markers
# (e.g. "0 errors", "no errors", "all tests passed")
_SUCCESS_PATTERNS = (
    r"\b0 errors?\b",
    r"\bno errors\b",
    r"\ball tests? (?:passed|passed)\b",
    r"\btests? passed\b",
    r"\bexit code 0\b",
    r"\bok\b\s*$",  # "OK" alone at end of output
)

_SUCCESS_RE = re.compile("|".join(_SUCCESS_PATTERNS), re.IGNORECASE)


def verify_last_tool_succeeded(trace: object) -> tuple[bool, str]:
    """Deterministic sanity check on the LAST tool's observation.

    Returns (passed, note). `passed=True` means "the last tool's
    observation has no error markers (or has success markers that
    override them)." `passed=False` means the last tool failed.

    Conservative: returns True (pass) when:
      - No tool step exists in the trace (no work was done).
      - The last step has no observation.
      - The observation is empty/whitespace.
      - The observation contains success markers (overrides errors).
      - The observation has no recognizable error markers.
    """
    steps = getattr(trace, "steps", None) or []
    if not steps:
        return True, "no tool steps in trace (no work to verify)"

    last = steps[-1]
    obs = getattr(last, "observation", None) or ""
    if not obs.strip():
        return True, "last tool observation is empty (no error markers)"

    obs_lower = obs.lower()

    # Success markers override error markers — e.g. "pytest: 0 errors"
    # has the word "errors" but is a passing result.
    if _SUCCESS_RE.search(obs_lower):
        return True, "last tool observation contains success markers"

    if _ERR_RE.search(obs_lower):
        # Find which pattern matched for a useful note.
        for pattern in _ERR_PATTERNS:
            m = re.search(pattern, obs, re.IGNORECASE)
            if m:
                return False, f"last tool observation contains error marker: {m.group(0)!r}"
        # Should not reach here, but defensive.
        return False, "last tool observation contains error markers"

    return True, "last tool observation is free of error markers"


# ── High-stakes intent check ───────────────────────────────────────────────
#
# Only run the post-execution verifier for intents where a tool failure
# is materially consequential — file write/edit, code exec, shell. For
# read-only intents (file_read, web_search, sysinfo), the gate is
# redundant: a "failed" web_search returns no results, which the
# model can synthesize around; a "failed" file_read returns empty,
# same. The high-stakes set is the one where the model's "done" claim
# is most dangerous to take at face value.

_HIGH_STAKES_INTENT_VALUES = frozenset(
    {
        "file_write",
        "file_edit",
        "code_exec",
        "shell",
    }
)


def is_high_stakes_intent(intent) -> bool:
    """Return True if the intent warrants a post-execution verifier pass.

    Accepts either a string (intent.value) or an Intent enum.
    """
    if intent is None:
        return False
    value = getattr(intent, "value", intent)
    return value in _HIGH_STAKES_INTENT_VALUES


def post_execution_verify(trace: object, intent) -> tuple[bool, str]:
    """Run the post-execution sanity check if the intent is high-stakes.

    Returns (passed, note). For non-high-stakes intents, returns
    (True, "skipped — non-high-stakes intent") — the gate does not
    apply.

    This is the F4 mandatory verifier — runs at the model's "done"
    claim, AFTER criteria_gate, for high-stakes intents. When the
    GoalInterpreter's criteria passed but the last tool's output
    contains error markers, this catches the failure.
    """
    if not is_high_stakes_intent(intent):
        return True, "skipped — non-high-stakes intent"
    return verify_last_tool_succeeded(trace)
