"""Task-aware context policy — ADR-19 (design.md, Session 159-160).

LocalMind compresses context POSITIONALLY today (`context_compactor` keeps
the newest N tool results; `summarizer` LLM-summarizes the oldest 50% with
one generic prompt). ADR-19 makes allocation TASK-AWARE: a pure, deterministic
policy maps the current task type to what MUST stay verbatim, what CAN be
stubbed, and (eventually, OFF by default in P0) what CAN be dropped.

This module is deliberately PURE — no I/O, no awaits, no imports from the
loop. Every function is unit-testable in isolation. The default policy
(`policy_for("default")`) reproduces today's positional behavior exactly,
so wiring the policy into the compactor/summarizer is a NO-OP until a task
type is explicitly resolved (locked decision: per-task tables, seeded from
a global default with per-task overrides).

Locked decisions (Session 159):
  - Full P0 scope (build order steps 1-6).
  - The dispatcher emits an explicit `task_type` in execution_plan.
  - Per-task KEEP tables (each task type overrides its own markers).
  - CAN DISCARD implemented but OFF by default in P0 (stub-only ships).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ── Task types ───────────────────────────────────────────────────────────────

# Canonical task types the policy layer understands. The dispatcher's
# `task_type` field should use these; anything unknown falls back to
# "default" (legacy positional behavior).
TASK_TYPES = frozenset(
    {"debug", "plan", "code", "research", "chat", "verify", "default"}
)

# Dispatcher primary_domain → task_type hints. Kept conservative: only map
# domains where the mapping is unambiguous; everything else stays "default"
# (legacy behavior) unless the dispatcher emits an explicit task_type.
_DOMAIN_HINTS = {
    "shell": "code",
    "code": "code",
    "file_edit": "code",
    "file_write": "code",
    "code_exec": "code",
    "web_search": "research",
    "web_fetch": "research",
    "browser": "research",
    "debugging": "debug",
    "debug": "debug",
    "diagnostics": "debug",
    "test": "verify",
    "verification": "verify",
}


@dataclass(frozen=True)
class ContextPolicy:
    """Per-task context rules.

    keep_markers:   content substrings that MUST stay verbatim — a tool
                    result or history line containing one of these is
                    protected from stubbing/trimming (bounded by
                    `max_keep`).
    drop_markers:   content signals that CAN be removed with a one-line
                    notice. P0: the capability exists but no task type
                    enables it (`allow_drop` is always False except tests).
    summary_prompt: task-specific instruction for the LLM summarizer.
    max_keep:       upper bound on how many verbatim-protected items the
                    compactor keeps, so a pathological stream can't fill
                    the window with protected results.
    allow_drop:     P0 locked OFF. Future task types may opt in after a
                    real-model smoke shows it safe.
    """

    task_type: str
    keep_markers: tuple[str, ...] = ()
    drop_markers: tuple[str, ...] = ()
    summary_prompt: str = (
        "Summarize the following conversation excerpt into a compact "
        "paragraph that preserves key facts, user preferences, decisions, "
        "and context that would be important for continuing the "
        "conversation. Be concise — aim for 3-6 sentences."
    )
    max_keep: int = 6
    allow_drop: bool = False

    # Matching semantics (Session 160 review): keep/drop markers are matched
    # CASE-INSENSITIVE substring against the tool-result content. Tables
    # therefore avoid redundant mixed-case pairs — one lowercase form is
    # enough. Greedy bare tokens ('.py', 'must', 'assert') are avoided on
    # purpose: they match nearly every tool output and would degenerate the
    # per-task table into legacy keep-newest-N behavior.



# ── Per-task tables (locked decision: per-task KEEP tables) ──────────────────

# Global default seeds every task type; per-task overrides win.
_DEFAULT_POLICY = ContextPolicy(task_type="default")

_POLICIES: dict[str, ContextPolicy] = {
    "debug": ContextPolicy(
        task_type="debug",
        keep_markers=(
            "traceback",
            "error:",
            "assertionerror",
            "exit code",
            "stderr",
            "exception",
            "test failed",
            "tests failed",
            "command failed",
            "traceback (most recent call last)",
        ),
        summary_prompt=(
            "Summarize the following conversation excerpt, PRESERVING verbatim: "
            "exact error messages, stack traces, failing assertions, exit codes, "
            "and the tool calls that produced them. Condense narrative prose but "
            "never paraphrase an error string. Aim for 3-6 sentences."
        ),
    ),
    "plan": ContextPolicy(
        task_type="plan",
        keep_markers=(
            "constraint",
            "must not",
            "cannot",
            "can't",
            "rejected",
            "decided",
            "requirement",
            "preference",
            "production uses",
            "instead of",
        ),
        summary_prompt=(
            "Summarize the following conversation excerpt, PRESERVING verbatim "
            "every constraint, decision, rejection, and requirement (e.g. "
            "'user rejected MongoDB', 'production uses PostgreSQL'). These lines "
            "change future decisions and must not be paraphrased away. Condense "
            "the rest. Aim for 3-6 sentences."
        ),
    ),
    "code": ContextPolicy(
        task_type="code",
        keep_markers=(
            "git status",
            "git diff",
            "success_criteria",
            "convention",
            "pytest",
            "tsc",
            "build passed",
            "build failed",
        ),
        summary_prompt=(
            "Summarize the following conversation excerpt, PRESERVING: current "
            "file paths and their state, code conventions the user stated, "
            "verify-after-write expectations, and any diff/git outcomes. Condense "
            "narrative prose. Aim for 3-6 sentences."
        ),
    ),
    "research": ContextPolicy(
        task_type="research",
        keep_markers=(
            "source:",
            "claim:",
            "evidence:",
            "https://",
            "http://",
            "retrieved from",
            "published",
        ),
        summary_prompt=(
            "Summarize the following conversation excerpt, PRESERVING: sources "
            "and URLs, claims and their evidence, publication dates, and "
            "fact-vs-opinion distinctions. Condense narrative prose. Aim for "
            "3-6 sentences."
        ),
    ),
    "chat": ContextPolicy(task_type="chat"),
    "verify": ContextPolicy(
        task_type="verify",
        keep_markers=(
            "pytest",
            "test",
            "passed",
            "failed",
            "criteria",
            "1 passed",
            "tests passed",
            "all tests",
        ),
        summary_prompt=(
            "Summarize the following conversation excerpt, PRESERVING: exactly "
            "what test/build command was run, the pass/fail counts, and any "
            "success criteria that remain unmet. Condense narrative prose. Aim "
            "for 3-6 sentences."
        ),
    ),
}


def policy_for(task_type: Optional[str]) -> ContextPolicy:
    """Return the policy for a task type, falling back to the legacy default.

    The default policy reproduces today's positional behavior (no keep
    markers, no drop), so a None/unknown/'' task type is a no-op.
    """
    key = (task_type or "").strip().lower()
    if key in _POLICIES:
        return _POLICIES[key]
    # Map known primary_domain hints when the task_type wasn't explicit.
    if key in _DOMAIN_HINTS:
        hinted = _DOMAIN_HINTS[key]
        return _POLICIES[hinted]
    return _DEFAULT_POLICY


def resolve_task_type(
    task_type: Optional[str],
    primary_domain: str = "",
    phase: str = "",
    intent: str = "",
) -> str:
    """Resolve the effective task type from all available signals.

    Priority (locked decision: dispatcher emits explicit task_type):
      1. Explicit dispatcher `task_type` (if it's a canonical type).
      2. primary_domain hint (shell→code, web_search→research, ...).
      3. Intent fallback (WEB_* → research; SHELL/CODE_EXEC → code).
      4. TaskState.phase ('verify' → verify).
      5. '' → default (legacy no-op).

    Returns a canonical TASK_TYPES member or '' for the legacy default.
    """
    if task_type and task_type.strip().lower() in TASK_TYPES:
        resolved = task_type.strip().lower()
        # ADR-19 x ADR-22 re-key (Session 186): a canonical 'chat' hint on a
        # NON-CHAT routing is definitionally a misclassification — 'chat' is
        # the no-tool fallback, so a tool-bearing intent (SHELL/CODE_EXEC/
        # WEB_*) can never settle to it. Only applied when the caller KNOWS
        # the routing (explicit intent); the dispatcher (intent='') keeps
        # its emitted hint verbatim for the DIRECT path.
        if resolved == "chat" and intent and intent.upper() != "CHAT":
            resolved = ""
        if resolved:
            return resolved

    if primary_domain and primary_domain.strip().lower() in _DOMAIN_HINTS:
        return _DOMAIN_HINTS[primary_domain.strip().lower()]

    intent_l = intent.upper()
    if intent_l.startswith("WEB_") or intent_l == "BROWSE":
        return "research"
    if intent_l in ("SHELL", "CODE_EXEC", "FILE_WRITE", "FILE_EDIT"):
        return "code"

    if phase.strip().lower() == "verify":
        return "verify"
    if phase.strip().lower() == "plan":
        return "plan"

    return ""


def parse_task_type_from_plan(
    task_type_raw: object,
    primary_domain: str = "",
) -> str:
    """Sanitize a dispatcher-provided task_type (str or None) to canonical.

    Mirrors the ADR-18 success_criteria parse pattern (lenient, capped,
    defaulting to '' when unusable).
    """
    if isinstance(task_type_raw, str):
        return resolve_task_type(task_type_raw, primary_domain=primary_domain)
    return resolve_task_type("", primary_domain=primary_domain)
