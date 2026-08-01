"""
WorkspaceState — the ADR-5 feedback service.

Implements the "Workspace" bar from the CODING HARNESS diagram (ADR-5):
pipes git status/diff, build/test/typecheck output, and open-file state
back into the agent's context every turn. This is the literal difference
between a harness and a bare API — "observations flow back into context
every turn."

Why this module exists (ADR-5 thesis):
    A coding agent isn't just "LLM + tool-calling." It's a closed loop
    where the workspace's real state (git diffs, test results, file
    system) continuously feeds back into the context for the next turn.
    That feedback loop — not the model itself — is what separates a
    harness like Cursor or Claude Code from a bare API call.

What snapshot() returns:
    - git status --short (uncommitted changes)
    - git diff --stat since the last turn (what changed)
    - last test/build/typecheck result (if recorded)
    - currently-open files (if tracked)

Design notes:
    - Standalone module — does NOT require the BaseAgent loop extraction
      (Phase 2). Can be wired into the existing AgentLoop.run() with a
      small surgical change. This delivers the ADR-5 differentiator
      without the risky 2926-line refactor.
    - All git operations are subprocess calls with a hard timeout. If
      git isn't available or the cwd isn't a git repo, snapshot()
      returns a minimal dict with `git_available: False` — never raises.
    - The "since last turn" diff tracking is opt-in: call
      `mark_turn_start()` at the beginning of each turn to record the
      current HEAD; the next snapshot() will diff against it. Without
      `mark_turn_start()`, snapshot() reports the full `git diff` (no
      baseline).
    - Open-file tracking is deferred to a future session (the frontend
      would need to report open files to the backend). snapshot()
      returns `open_files: []` for now.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Hard timeout for git subprocess calls. Git operations should complete
# in <1s on any reasonably-sized repo; 5s is a generous safety net.
_GIT_TIMEOUT_SECS = 5.0

# Max lines of git status / diff output to include in the snapshot.
# Prevents context bloat on repos with many uncommitted changes.
_MAX_STATUS_LINES = 50
_MAX_DIFF_STAT_LINES = 30


@dataclass
class WorkspaceSnapshot:
    """
    A point-in-time snapshot of the workspace state.

    Returned by snapshot(). Use format_snapshot() to turn it into a
    string for context injection.
    """

    # Whether git is available and the cwd is a git repo. If False, all
    # other git_* fields are empty.
    git_available: bool = False
    # `git status --short` output (uncommitted changes). Empty string if
    # the working tree is clean.
    git_status: str = ""
    # `git diff --stat` output since the last mark_turn_start() call (or
    # the full diff if no baseline was marked). Empty if no changes.
    git_diff_stat: str = ""
    # Current branch name (e.g., "main", "feature/foo"). Empty if git
    # isn't available.
    git_branch: str = ""
    # Current HEAD commit short SHA. Empty if git isn't available.
    git_head: str = ""
    # The last recorded test/build/typecheck result. None if no result
    # has been recorded this session.
    last_build_result: Optional[dict] = None
    # Currently-open files (frontend-reported). Empty list for now —
    # open-file tracking is deferred to a future session.
    open_files: list[str] = field(default_factory=list)
    # When this snapshot was taken (epoch seconds). Useful for logging.
    timestamp: float = field(default_factory=time.time)

    def is_clean(self) -> bool:
        """True if the working tree is clean (no uncommitted changes)."""
        return self.git_available and not self.git_status.strip()


# ── Per-session state ────────────────────────────────────────────────────────

# The HEAD SHA recorded at the start of the current turn. snapshot()
# diffs against this. Reset by mark_turn_start().
_last_turn_head: Optional[str] = None

# The last recorded build/test/typecheck result. Set by
# record_build_result(). Persists across turns within a session.
_last_build_result: Optional[dict] = None


def mark_turn_start(cwd: Optional[str] = None) -> None:
    """
    Record the current HEAD as the baseline for the next snapshot()'s diff.

    Call this at the beginning of each agent turn (step 1: assemble
    prompt). The next snapshot() will diff against this HEAD, showing
    only what changed during this turn.

    If this is never called, snapshot() reports the full `git diff` (no
    baseline) — still useful, just less precise.

    Args:
        cwd: the working directory to check. Defaults to the current
            working directory.
    """
    global _last_turn_head
    _last_turn_head = _git_rev_parse("HEAD", cwd)
    logger.debug("[workspace_state] mark_turn_start: HEAD=%s", _last_turn_head)


def record_build_result(
    result: str,
    command: str = "",
    output_tail: str = "",
    exit_code: Optional[int] = None,
) -> None:
    """
    Record the last test/build/typecheck result.

    Call this after running any build/test/typecheck command (whether
    from the shell tool or from the agent loop's own health checks).
    The next snapshot() will include it, so the agent sees the result
    in context on the next turn.

    Args:
        result: short label — "pass", "fail", "error", "timeout".
        command: the command that was run (e.g., "pytest", "ruff check .").
        output_tail: the last N lines of output (capped to avoid bloat).
        exit_code: the process exit code, if known.
    """
    global _last_build_result
    _last_build_result = {
        "result": result,
        "command": command,
        "output_tail": output_tail[:500],  # cap at 500 chars
        "exit_code": exit_code,
        "timestamp": time.time(),
    }
    logger.debug(
        "[workspace_state] record_build_result: %s (%s)", result, command
    )


def reset() -> None:
    """Reset per-session state. Useful for tests."""
    global _last_turn_head, _last_build_result
    _last_turn_head = None
    _last_build_result = None


# ── Snapshot collection ──────────────────────────────────────────────────────


def snapshot(
    cwd: Optional[str] = None,
    *,
    include_turn_diff: bool = True,
) -> WorkspaceSnapshot:
    """
    Take a point-in-time snapshot of the workspace state.

    This is the main entry point. The agent loop calls this at step 1
    (assemble prompt) of each turn and injects the result into the
    context for the next model call.

    Never raises — if git isn't available or the cwd isn't a repo,
    returns a snapshot with `git_available: False`. If a git command
    times out, the corresponding field is empty.

    Args:
        cwd: the working directory to snapshot. Defaults to the current
            working directory.
        include_turn_diff: whether to use the process-level turn baseline
            when calculating git_diff_stat. Set this to False for an
            explicitly selected workspace whose baseline may belong to a
            different request or session.

    Returns:
        A WorkspaceSnapshot. Use format_snapshot() to turn it into a
        string for context injection.
    """
    work_dir = Path(cwd or os.getcwd())

    snap = WorkspaceSnapshot(
        last_build_result=_last_build_result,
    )

    # ── Git state ──
    head = _git_rev_parse("HEAD", str(work_dir))
    if head is None:
        # Not a git repo or git unavailable
        snap.git_available = False
        return snap

    snap.git_available = True
    snap.git_head = head
    snap.git_branch = _git_branch(str(work_dir)) or ""
    snap.git_status = _git_status_short(str(work_dir))

    # Diff: against _last_turn_head if set, else full unstaged diff
    if include_turn_diff and _last_turn_head and _last_turn_head != head:
        snap.git_diff_stat = _git_diff_stat(
            _last_turn_head, str(work_dir)
        )
    elif include_turn_diff and _last_turn_head == head:
        # No new commits since mark_turn_start — show unstaged changes only
        snap.git_diff_stat = _git_diff_stat(None, str(work_dir))
    else:
        # No baseline, or explicitly requested a baseline-free snapshot.
        snap.git_diff_stat = _git_diff_stat(None, str(work_dir))

    return snap


def format_snapshot(snap: WorkspaceSnapshot) -> str:
    """
    Format a snapshot as a string for context injection.

    This is what gets appended to the agent's system prompt or
    environment context. Kept concise — on gemma3:1b-class hardware,
    every token of context is expensive.

    Returns an empty string if the snapshot has no useful information
    (e.g., git unavailable AND no build result AND no open files).
    """
    if not snap.git_available and not snap.last_build_result and not snap.open_files:
        return ""

    lines = ["# Workspace State"]

    if not snap.git_available:
        lines.append("")
        lines.append("(git not available or not a git repo)")
    else:
        lines.append("")
        lines.append(f"Branch: {snap.git_branch or '(detached)'}")
        lines.append(f"HEAD: {snap.git_head[:12] if snap.git_head else 'unknown'}")

        if snap.is_clean():
            lines.append("Working tree: clean")
        else:
            lines.append("Working tree: dirty (uncommitted changes)")
            if snap.git_status.strip():
                status_lines = snap.git_status.strip().split("\n")
                if len(status_lines) > _MAX_STATUS_LINES:
                    lines.append(
                        f"  ({len(status_lines)} files changed; showing first {_MAX_STATUS_LINES})"
                    )
                    status_lines = status_lines[:_MAX_STATUS_LINES]
                for sl in status_lines:
                    lines.append(f"  {sl}")

        if snap.git_diff_stat.strip():
            lines.append("")
            lines.append("Changes since last turn:")
            diff_lines = snap.git_diff_stat.strip().split("\n")
            if len(diff_lines) > _MAX_DIFF_STAT_LINES:
                lines.append(
                    f"  ({len(diff_lines)} files; showing first {_MAX_DIFF_STAT_LINES})"
                )
                diff_lines = diff_lines[:_MAX_DIFF_STAT_LINES]
            for dl in diff_lines:
                lines.append(f"  {dl}")

    if snap.last_build_result:
        lines.append("")
        lines.append("Last build/test result:")
        br = snap.last_build_result
        lines.append(f"  Command: {br.get('command', '(unknown)')}")
        lines.append(f"  Result: {br.get('result', '(unknown)')}")
        if br.get("exit_code") is not None:
            lines.append(f"  Exit code: {br['exit_code']}")
        if br.get("output_tail"):
            lines.append("  Output (tail):")
            for ol in br["output_tail"].strip().split("\n"):
                lines.append(f"    {ol}")

    if snap.open_files:
        lines.append("")
        lines.append("Open files:")
        for f in snap.open_files[:10]:  # cap at 10
            lines.append(f"  {f}")

    return "\n".join(lines)


# ── Git subprocess helpers (all synchronous, all timeout-guarded) ────────────


def _git_rev_parse(rev: str, cwd: str) -> Optional[str]:
    """Return the SHA for a rev, or None if git fails / not a repo."""
    return _git_output(["rev-parse", rev], cwd)


def _git_branch(cwd: str) -> Optional[str]:
    """Return the current branch name, or None."""
    return _git_output(["rev-parse", "--abbrev-ref", "HEAD"], cwd)


def _git_status_short(cwd: str) -> str:
    """Return `git status --short` output, or empty string."""
    return _git_output(["status", "--short"], cwd) or ""


def _git_diff_stat(since_rev: Optional[str], cwd: str) -> str:
    """
    Return `git diff --stat` output.

    Args:
        since_rev: if provided, diff between this rev and HEAD (shows
            commits landed since the baseline). If None, shows unstaged
            changes only.
    """
    if since_rev:
        return _git_output(["diff", "--stat", since_rev, "HEAD"], cwd) or ""
    return _git_output(["diff", "--stat"], cwd) or ""


def _git_output(args: list[str], cwd: str) -> Optional[str]:
    """
    Run a git command and return its stdout (stripped), or None on failure.

    All failures are logged at debug level and return None — snapshot()
    must never raise. A timeout returns None. A non-zero exit returns None.
    """
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECS,
        )
        if result.returncode != 0:
            logger.debug(
                "[workspace_state] git %s failed (exit %d): %s",
                " ".join(args),
                result.returncode,
                result.stderr.strip()[:200],
            )
            return None
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug("[workspace_state] git %s error: %s", " ".join(args), e)
        return None
