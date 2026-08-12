"""
Deterministic acceptance-gate checkers (ADR-18 P0 / B-2026-08-12-1).

The gate's job: turn "the model says done" into "the model says done
AND the success criteria have receipts." Every checker here is
deterministic — no LLM calls — so the gate costs one cheap pass per
evaluation and is fully unit-testable.

Matching is deliberately heuristic and conservative:
  - Specific patterns first (tests/build, file existence, git, HTTP,
    error-freedom); each checker returns None when the criterion is not
    in its domain, otherwise the verdict.
  - Fallback: evidence-requirement — a criterion is met when the trace
    contains a tool observation / tool input that quotes its key tokens
    (the same trick WorkReport.needs_report uses). This keeps
    subjective criteria honest: there must be at least one receipt.

Each verdict is (passed: bool, note: str). A criterion with NO evidence
anywhere is NOT met — absence of evidence is not evidence. Empty
criteria lists gate as passed (the legacy model-assertion path is
unchanged when there is no contract).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from core.agent.models import AgentTrace

# ── Command / marker tables ──────────────────────────────────────────────────

# Commands whose output we can parse for pass/fail signals.
_TEST_CMDS = (
    "pytest",
    "tsc",
    "typecheck",
    "ruff",
    "eslint",
    "vitest",
    "npm test",
    "go test",
    "cargo test",
    "mvn test",
    "gradle test",
    "make test",
)

_TEST_PASS_MARKERS = (
    "passed",
    "passing",
    "ok",
    "no errors",
    "0 failed",
    "successful",
    "all tests",
    "tests passed",
    "no output",
)
_TEST_FAIL_MARKERS = (
    "failed",
    "traceback",
    "error:",
    "exit code",
    "not ok",
    "1 failed",
    "tests failed",
    "failures",
)

# Verbs that make a criterion a file-existence claim.
_FILE_VERBS = ("exists", "created", "written", "wrote", "saved to", "written to")

# HTTP 200-equivalent strings found in web_fetch/browse observations.
_HTTP_OK_MARKERS = ("200", "200 ok", "http 200", "status 200")

# Error markers used by the error-freedom check.
_ERR_MARKERS = ("error", "traceback", "exception", "failed", "fatal", "exit code")

# Criterion tokens that carry no evidence value for the fallback check.
_IGNORED_FALLBACK_TOKENS = {
    "true", "false", "none", "null", "the", "and", "with", "that", "this",
    "should", "must", "have", "has", "not", "all", "are", "was", "from",
    "check", "verify", "ensure", "criterion", "criteria", "success",
    "file", "files", "output", "result", "status", "command", "test",
    "tests", "build", "returns", "exists", "passes", "pass", "show", "make",
    "written", "write", "created", "contains", "content",
    "code", "exit", "run", "exec",
}

_PATH_RE = re.compile(
    r"[\w./\\-]+\.(?:py|js|ts|tsx|jsx|md|json|txt|toml|yaml|yml|html|css|sh|sql|"
    r"c|h|cpp|go|rs|java|rb|php|ipynb|cfg|ini|env)\b",
    re.IGNORECASE,
)


# ── Evidence extraction ──────────────────────────────────────────────────────


def _evidence(trace: AgentTrace) -> list[dict]:
    """Flatten trace steps into tool-evidence records."""
    return [
        {
            "tool": step.tool_name,
            "input": step.tool_input or "",
            "observation": step.observation or "",
            "succeeded": not step.tool_failed,
        }
        for step in trace.steps
        if step.tool_name
    ]


def _cmd_for(criterion: str) -> Optional[str]:
    lowered = criterion.lower()
    for cmd in _TEST_CMDS:
        if cmd in lowered:
            return cmd
    return None


# ── Domain checkers (None = criterion not in this domain) ───────────────────


def _check_tests(
    criterion: str,
    trace: AgentTrace,
    cwd: Optional[str] = None,
) -> Optional[tuple[bool, str]]:
    """'pytest passes' / 'tsc has no errors' / 'build succeeds' → parse the
    matching tool observation for pass/fail markers."""
    cmd = _cmd_for(criterion)
    if cmd is None:
        return None
    for ev in _evidence(trace):
        hay = f"{ev['input']} {ev['observation']}".lower()
        if cmd not in hay:
            continue
        obs = ev["observation"].lower()
        has_pass = any(marker in obs for marker in _TEST_PASS_MARKERS)
        has_fail = any(marker in obs for marker in _TEST_FAIL_MARKERS)
        if has_fail and not has_pass:
            return False, f"{cmd} output shows failure markers"
        if has_pass and not has_fail:
            return True, f"{cmd} output shows pass markers"
        if has_pass and has_fail:
            return False, f"{cmd} output is ambiguous (pass and fail markers)"
    return False, f"no {cmd} run found in tool evidence"


def _check_file(
    criterion: str,
    trace: AgentTrace,
    cwd: Optional[str],
) -> Optional[tuple[bool, str]]:
    """'hello.py exists with content' / 'created <path>' → check the workspace
    plus write/edit evidence."""
    lowered = criterion.lower()
    # A git-flavored criterion belongs to the git domain even when it names
    # a file ("git diff contains hello.py") — never intercept it here.
    if "git" in lowered:
        return None
    if not any(verb in lowered for verb in _FILE_VERBS) and not _PATH_RE.search(criterion):
        return None
    paths = _PATH_RE.findall(criterion)
    if not paths:
        return None
    work_dir = Path(cwd or os.getcwd())
    wants_content = "with content" in lowered
    for raw in paths:
        candidate = work_dir / raw
        if candidate.is_file():
            if not wants_content or candidate.stat().st_size > 0:
                return True, f"{raw} exists on disk"
    # Evidence fallback: a write/edit tool input or observation names the file.
    for ev in _evidence(trace):
        hay = f"{ev['input']} {ev['observation']}".lower()
        if any(raw.lower() in hay for raw in paths):
            return True, f"{paths[0]} referenced in tool evidence"
    return False, f"{paths[0]} not found on disk or in tool evidence"


def _check_git(
    criterion: str,
    trace: AgentTrace,
    cwd: Optional[str],
) -> Optional[tuple[bool, str]]:
    """'git status is clean' / 'git diff contains <file>' → reuse the
    per-turn workspace snapshot (already computed each iteration)."""
    if "git" not in criterion.lower():
        return None
    try:
        from core import workspace_state

        snap = workspace_state.snapshot(cwd)
    except Exception:
        return False, "workspace snapshot unavailable"
    if not snap.git_available:
        return False, "not a git repo (or git unavailable)"
    if "clean" in criterion.lower():
        if snap.is_clean():
            return True, "git working tree is clean"
        return False, "git working tree has uncommitted changes"
    files = _PATH_RE.findall(criterion)
    hay = f"{snap.git_status} {snap.git_diff_stat}"
    if files:
        if all(f in hay for f in files):
            return True, f"git shows changes to {', '.join(files)}"
        return False, f"git does not show {', '.join(files)}"
    if snap.git_diff_stat.strip():
        return True, "git diff shows changes"
    return False, "git diff is empty"


def _check_http(
    criterion: str,
    trace: AgentTrace,
    cwd: Optional[str] = None,
) -> Optional[tuple[bool, str]]:
    """'<endpoint> returns 200' → scan web_fetch/browse observations."""
    lowered = criterion.lower()
    # Tight domain: "returns"/"status" alone are too generic ("report the
    # current status of the deployment" is not an HTTP claim). Require an
    # http-specific token, or a status verb followed by a status code.
    http_hint = any(
        token in lowered
        for token in ("http", "url", "endpoint", "server", "api", "website", "web page", "reachable")
    )
    status_verb_code = bool(re.search(r"\b(?:returns?|status)\s+\d{3}\b", lowered))
    if not (http_hint or status_verb_code):
        return None
    for ev in _evidence(trace):
        obs = ev["observation"].lower()
        if ev["tool"] in ("web_fetch", "browse") or "http" in obs:
            if any(ok in obs for ok in _HTTP_OK_MARKERS):
                return True, "tool evidence shows HTTP 200"
            status = re.search(r"\b([45]\d\d)\b", ev["observation"])
            if status:
                return False, f"tool evidence shows HTTP {status.group(1)}"
    return False, "no HTTP status found in tool evidence"


def _check_no_errors(
    criterion: str,
    trace: AgentTrace,
    cwd: Optional[str] = None,
) -> Optional[tuple[bool, str]]:
    """'no errors in the output' → the latest tool output must be error-free."""
    lowered = criterion.lower()
    if not any(phrase in lowered for phrase in ("no error", "without error", "does not fail")):
        return None
    evidence = _evidence(trace)
    if not evidence:
        return False, "no tool evidence to check for errors"
    last = evidence[-1]
    obs = last["observation"].lower()
    # Classic SUCCESS outputs ("Found 0 errors.", "no errors, build ok") must
    # pass — otherwise the substring "error" inside "errors" false-negatives
    # the most common passing build/test output.
    if re.search(r"\b0 errors?\b", obs) or "no errors" in obs:
        return True, "latest tool output reports zero errors"
    if re.search(r"\berror", obs) or any(
        marker in obs for marker in ("traceback", "exception", "failed", "fatal", "exit code")
    ):
        return False, f"latest tool output contains error markers ({_ERR_MARKERS[0]})"
    return True, "latest tool output is free of error markers"


# ── Fallback: evidence-requirement ───────────────────────────────────────────


def _fallback_evidence(criterion: str, trace: AgentTrace) -> tuple[bool, str]:
    """Criterion is met when a tool observation / tool input quotes its
    key tokens (WorkReport-style). Subjective criteria still need a
    receipt."""
    keys = {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_.:/\\-]{3,}", criterion.lower())
        if token not in _IGNORED_FALLBACK_TOKENS
    }
    if not keys:
        return False, "criterion has no checkable tokens"
    for ev in _evidence(trace):
        hay = f"{ev['input']} {ev['observation']}".lower()
        if any(key in hay for key in keys):
            return True, "tool evidence quotes the criterion's key tokens"
    return False, "no tool evidence quotes the criterion's key tokens"


# ── Public API ───────────────────────────────────────────────────────────────


def check_criterion(
    criterion: str,
    trace: AgentTrace,
    cwd: Optional[str] = None,
) -> tuple[bool, str]:
    """Evaluate one success criterion against the trace + workspace.

    Deterministic and conservative. Returns (passed, note). A criterion
    with no evidence anywhere is NOT met.
    """
    for checker in (_check_tests, _check_git, _check_file, _check_http, _check_no_errors):
        verdict = checker(criterion, trace, cwd)
        if verdict is not None:
            return verdict
    return _fallback_evidence(criterion, trace)


def evaluate_criteria(
    criteria: list[str],
    trace: AgentTrace,
    cwd: Optional[str] = None,
) -> list[tuple[str, bool, str]]:
    """Evaluate every criterion. Returns [(criterion, passed, note)]."""
    if not criteria:
        return []
    return [(criterion, *check_criterion(criterion, trace, cwd)) for criterion in criteria]


def gate_passed(results: list[tuple[str, bool, str]]) -> bool:
    """All criteria met. Empty criteria → True (no contract = the legacy
    model-assertion path is unchanged)."""
    if not results:
        return True
    return all(passed for _, passed, _ in results)


def format_gate_results(results: list[tuple[str, bool, str]]) -> str:
    """One-line gate outcome for the user-facing final answer, e.g.
    '✓ 2/2 criteria met (pytest passes, hello.py exists with content)' or
    '✗ 1/2 criteria met — unmet: <criterion> (<note>)'."""
    if not results:
        return ""
    passed_count = sum(1 for _, passed, _ in results if passed)
    total = len(results)
    if passed_count == total:
        met = ", ".join(criterion for criterion, _, _ in results)
        return f"✓ {total}/{total} criteria met ({met})"
    unmet = [
        f"{criterion} ({note})"
        for criterion, passed, note in results
        if not passed
    ]
    return f"✗ {passed_count}/{total} criteria met — unmet: {'; '.join(unmet)}"
