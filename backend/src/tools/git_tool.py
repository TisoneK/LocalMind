"""
Git tool — structured Git operations for LocalMind agents.

Exposes 9 semantic Git operations as structured
tool calls instead of opaque shell commands. The agent can reason about
git state using typed operations instead of parsing raw text output.

Operations:
  status    — `git status --short` (uncommitted changes, staged/unstaged)
  diff      — `git diff` or `git diff --staged` (what changed)
  log       — `git log --oneline -N` (commit history)
  branch    — `git branch -a` or `git branch <name>` (list/create branches)
  checkout  — `git checkout <branch>` (switch branches)
  commit    — `git commit -m <message>` or `git add -A && git commit -m <msg>`
  merge     — `git merge <branch>` (merge a branch into current)
  stash     — `git stash [push|pop|list]` (shelve working changes)
  reset     — `git reset [--soft|--mixed|--hard] [<ref>]` (undo commits)

Why a structured tool instead of shell:
  - Semantic operations let the model reason about git state without
    parsing raw terminal output
  - Safety: destructive operations (reset --hard, force push) are gated
  - Consistent output format across platforms (Windows/macOS/Linux)
  - Structured error messages instead of raw git error text
  - Complements workspace_state.py (which passively observes git state
    and injects it into context)

Integration:
  - Registered as Intent.GIT via register_tool()
  - Added to AGENT_ALLOWED_TOOLS and CODING_TOOLS
  - Added to TOOL_DEFINITIONS for model visibility
  - Wired through _extract_tool_input() in loop.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from contextvars import ContextVar
from pathlib import Path

from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool

logger = logging.getLogger(__name__)

# Hard timeout for git subprocess calls
_GIT_TIMEOUT_SECS = 15.0

# Max output lines to return (prevents context bloat)
_MAX_OUTPUT_LINES = 100

# CWD context var (shared with shell tool for session directory tracking)
_session_cwd_var: ContextVar[str | None] = ContextVar("_session_cwd", default=None)


def set_session_cwd(cwd: str | None) -> None:
    """Set session CWD for git operations. Called by the Engine."""
    _session_cwd_var.set(cwd)


def _get_cwd() -> str:
    """Resolve the working directory for git operations."""
    cwd = _session_cwd_var.get(None)
    if cwd and Path(cwd).is_dir():
        return cwd
    return os.getcwd()


def _run_git(args: list[str], cwd: str) -> tuple[bool, str]:
    """Run a git command. Returns (success, output). Never raises."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECS,
        )
        output = (result.stdout + result.stderr).strip()
        if not output:
            output = "(no output)"
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"Git command timed out after {_GIT_TIMEOUT_SECS}s"
    except FileNotFoundError:
        return False, "Git is not installed or not on PATH"
    except OSError as exc:
        return False, f"Git command failed: {exc}"


def _is_git_repo(cwd: str) -> bool:
    """Check if cwd is inside a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _cap_lines(output: str, max_lines: int = _MAX_OUTPUT_LINES) -> str:
    """Cap output to max_lines, with a truncation note."""
    lines = output.split("\n")
    if len(lines) > max_lines:
        return "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines truncated)"
    return output


# ── Operation handlers ─────────────────────────────────────────────────────────


def _git_status(cwd: str) -> ToolResult:
    """Run git status --short."""
    ok, output = _run_git(["status", "--short"], cwd)
    if not ok:
        return ToolResult(
            content=f"git status failed: {output}",
            risk=RiskLevel.LOW,
            source="git",
            success=False,
            error_type="git_error",
            error_message=output,
        )
    if not output.strip() or output.strip() == "(no output)":
        return ToolResult(
            content="Working tree clean — no uncommitted changes.",
            risk=RiskLevel.LOW,
            source="git",
            metadata={"clean": True},
        )
    return ToolResult(
        content=f"Git status (working tree changes):\n{_cap_lines(output)}",
        risk=RiskLevel.LOW,
        source="git",
        metadata={"clean": False},
    )


def _git_diff(cwd: str, staged: bool = False) -> ToolResult:
    """Run git diff or git diff --staged."""
    args = ["diff"]
    if staged:
        args.append("--staged")
    ok, output = _run_git(args, cwd)
    if not ok:
        return ToolResult(
            content=f"git diff failed: {output}",
            risk=RiskLevel.LOW,
            source="git",
            success=False,
            error_type="git_error",
            error_message=output,
        )
    if not output.strip() or output.strip() == "(no output)":
        label = "staged changes" if staged else "unstaged changes"
        return ToolResult(
            content=f"No {label} to show.",
            risk=RiskLevel.LOW,
            source="git",
            metadata={"changes": False},
        )
    label = "Staged changes" if staged else "Unstaged changes"
    return ToolResult(
        content=f"{label}:\n{_cap_lines(output)}",
        risk=RiskLevel.LOW,
        source="git",
        metadata={"changes": True},
    )


def _git_log(cwd: str, count: int = 10) -> ToolResult:
    """Run git log --oneline -N."""
    count = max(1, min(count, 50))  # clamp 1-50
    ok, output = _run_git(["log", "--oneline", f"-{count}"], cwd)
    if not ok:
        return ToolResult(
            content=f"git log failed: {output}",
            risk=RiskLevel.LOW,
            source="git",
            success=False,
            error_type="git_error",
            error_message=output,
        )
    if not output.strip():
        return ToolResult(
            content="No commits yet in this repository.",
            risk=RiskLevel.LOW,
            source="git",
        )
    return ToolResult(
        content=f"Recent commits (last {count}):\n{output}",
        risk=RiskLevel.LOW,
        source="git",
    )


def _git_branch(cwd: str, name: str = "") -> ToolResult:
    """List branches (git branch -a) or create a new branch."""
    if name:
        # Create a new branch: git branch <name>
        ok, output = _run_git(["branch", name], cwd)
        if not ok:
            return ToolResult(
                content=f"Failed to create branch '{name}': {output}",
                risk=RiskLevel.LOW,
                source="git",
                success=False,
                error_type="git_error",
                error_message=output,
            )
        return ToolResult(
            content=f"Created branch '{name}' (did not switch to it). Use checkout to switch.",
            risk=RiskLevel.LOW,
            source="git",
        )
    # List branches
    ok, output = _run_git(["branch", "-a"], cwd)
    if not ok:
        return ToolResult(
            content=f"git branch failed: {output}",
            risk=RiskLevel.LOW,
            source="git",
            success=False,
            error_type="git_error",
            error_message=output,
        )
    return ToolResult(
        content=f"Branches:\n{_cap_lines(output)}",
        risk=RiskLevel.LOW,
        source="git",
    )


def _git_checkout(cwd: str, branch: str) -> ToolResult:
    """Switch to a branch: git checkout <branch>."""
    if not branch:
        return ToolResult(
            content="checkout requires a branch name.",
            risk=RiskLevel.LOW,
            source="git",
            success=False,
            error_type="missing_arg",
        )
    ok, output = _run_git(["checkout", branch], cwd)
    if not ok:
        return ToolResult(
            content=f"Checkout failed: {output}",
            risk=RiskLevel.MEDIUM,
            source="git",
            success=False,
            error_type="git_error",
            error_message=output,
        )
    return ToolResult(
        content=f"Switched to branch '{branch}'.\n{output}",
        risk=RiskLevel.LOW,
        source="git",
    )


def _git_commit(cwd: str, message: str, add_all: bool = False) -> ToolResult:
    """Commit changes: git commit -m <message>. Optionally git add -A first."""
    if not message:
        return ToolResult(
            content="commit requires a message.",
            risk=RiskLevel.LOW,
            source="git",
            success=False,
            error_type="missing_arg",
        )
    # Check for staged changes
    if add_all:
        _run_git(["add", "-A"], cwd)
        # Check if there's anything to commit after staging
        ok, staged = _run_git(["diff", "--cached", "--name-only"], cwd)
        if ok and not staged.strip():
            return ToolResult(
                content="Nothing to commit — working tree is clean.",
                risk=RiskLevel.LOW,
                source="git",
                success=True,
            )
    else:
        # Only commit if there are staged changes
        ok, staged = _run_git(["diff", "--cached", "--name-only"], cwd)
        if ok and not staged.strip():
            return ToolResult(
                content=(
                    "No staged changes to commit. Use 'add_all: true' to stage and "
                    "commit all changes, or stage specific files with shell first."
                ),
                risk=RiskLevel.LOW,
                source="git",
                success=False,
                error_type="no_staged_changes",
            )

    ok, output = _run_git(["commit", "-m", message], cwd)
    if not ok:
        return ToolResult(
            content=f"Commit failed: {output}",
            risk=RiskLevel.LOW,
            source="git",
            success=False,
            error_type="git_error",
            error_message=output,
        )
    return ToolResult(
        content=f"Committed successfully:\n{output}",
        risk=RiskLevel.MEDIUM,  # commits are a real change
        source="git",
        metadata={"action": "commit"},
    )


def _git_merge(cwd: str, branch: str) -> ToolResult:
    """Merge a branch into current: git merge <branch>."""
    if not branch:
        return ToolResult(
            content="merge requires a branch name.",
            risk=RiskLevel.LOW,
            source="git",
            success=False,
            error_type="missing_arg",
        )
    ok, output = _run_git(["merge", branch], cwd)
    if not ok:
        return ToolResult(
            content=f"Merge failed: {output}",
            risk=RiskLevel.HIGH,  # merge conflicts can be messy
            source="git",
            success=False,
            error_type="git_error",
            error_message=output,
        )
    return ToolResult(
        content=f"Merged '{branch}' into current branch:\n{output}",
        risk=RiskLevel.MEDIUM,
        source="git",
    )


def _git_stash(cwd: str, action: str = "push", message: str = "") -> ToolResult:
    """Stash operations: push, pop, list."""
    if action == "list":
        ok, output = _run_git(["stash", "list"], cwd)
        if not ok:
            return ToolResult(
                content=f"stash list failed: {output}",
                risk=RiskLevel.LOW,
                source="git",
                success=False,
                error_type="git_error",
                error_message=output,
            )
        if not output.strip() or output.strip() == "(no output)":
            return ToolResult(
                content="No stashed changes.",
                risk=RiskLevel.LOW,
                source="git",
            )
        return ToolResult(
            content=f"Stashed changes:\n{output}",
            risk=RiskLevel.LOW,
            source="git",
        )
    elif action == "pop":
        ok, output = _run_git(["stash", "pop"], cwd)
        if not ok:
            return ToolResult(
                content=f"stash pop failed: {output}",
                risk=RiskLevel.MEDIUM,
                source="git",
                success=False,
                error_type="git_error",
                error_message=output,
            )
        return ToolResult(
            content=f"Popped stash:\n{output}",
            risk=RiskLevel.MEDIUM,
            source="git",
        )
    else:
        # push (default)
        args = ["stash", "push"]
        if message:
            args.extend(["-m", message])
        ok, output = _run_git(args, cwd)
        if not ok:
            return ToolResult(
                content=f"stash push failed: {output}",
                risk=RiskLevel.LOW,
                source="git",
                success=False,
                error_type="git_error",
                error_message=output,
            )
        return ToolResult(
            content=f"Changes stashed:\n{output}",
            risk=RiskLevel.LOW,
            source="git",
        )


def _git_reset(cwd: str, mode: str = "--mixed", ref: str = "HEAD") -> ToolResult:
    """Reset: git reset [--soft|--mixed|--hard] [<ref>]."""
    if mode not in ("--soft", "--mixed", "--hard"):
        return ToolResult(
            content=f"Invalid reset mode '{mode}'. Use --soft, --mixed, or --hard.",
            risk=RiskLevel.LOW,
            source="git",
            success=False,
            error_type="invalid_args",
        )
    if mode == "--hard":
        return ToolResult(
            content=(
                f"Reset --hard to {ref} is destructive — it will discard all "
                f"uncommitted changes permanently. This operation cannot be undone. "
                f"If you're sure, use the shell tool to run 'git reset --hard {ref}' directly."
            ),
            risk=RiskLevel.HIGH,
            source="git",
            success=False,
            error_type="destructive_blocked",
            requires_confirmation=True,
        )
    ok, output = _run_git(["reset", mode, ref], cwd)
    if not ok:
        return ToolResult(
            content=f"Reset failed: {output}",
            risk=RiskLevel.HIGH,
            source="git",
            success=False,
            error_type="git_error",
            error_message=output,
        )
    return ToolResult(
        content=f"Reset ({mode} to {ref}):\n{output}",
        risk=RiskLevel.HIGH,
        source="git",
        metadata={"mode": mode, "ref": ref},
    )


# ── Main dispatch ──────────────────────────────────────────────────────────────


def _resolve_repo_dir(path) -> tuple[str, str]:
    """Return ``(directory, error)`` for the repo a git call should run in.

    No/blank ``path`` -> the session's working folder. A file path resolves to
    its parent folder; a missing path is an error, never a silent fallback."""
    raw = str(path or "").strip()
    if not raw:
        return _get_cwd(), ""
    target = Path(raw).expanduser()
    if target.is_file():
        target = target.parent
    if not target.is_dir():
        return "", f"Git path not found or not a folder: {raw}"
    return str(target), ""


async def git_dispatch(message: str) -> ToolResult:
    """Route to the correct git operation based on parsed args.

    Args:
        message: JSON-encoded arguments from the agent loop
            (same pattern as delegate and edit_file — the loop
            serializes multi-param tool calls as JSON).

    Returns:
        ToolResult with structured output.
    """
    # Parse args from JSON
    try:
        if message.strip().startswith("{"):
            args = json.loads(message)
        else:
            # Legacy single-string: treat as status if empty, otherwise error
            return ToolResult(
                content=(
                    "Git tool requires structured arguments. "
                    "Use 'operation' plus operation-specific parameters. "
                    "Example: {\"operation\": \"status\"}"
                ),
                risk=RiskLevel.LOW,
                source="git",
                success=False,
                error_type="invalid_input",
            )
    except json.JSONDecodeError as exc:
        return ToolResult(
            content=f"Could not parse git arguments: {exc}",
            risk=RiskLevel.LOW,
            source="git",
            success=False,
            error_type="invalid_input",
        )

    operation = args.get("operation", "").strip().lower()
    # `path` names the repository to operate on. It used to be ignored, so a
    # request about a specific repo silently ran in the session's working
    # folder and returned another repo's commits as if they were the answer.
    cwd, path_error = _resolve_repo_dir(args.get("path"))
    if path_error:
        return ToolResult(
            content=path_error,
            risk=RiskLevel.LOW,
            source="git",
            success=False,
            error_type="invalid_input",
        )

    # Check if we're in a git repo
    if not _is_git_repo(cwd):
        return ToolResult(
            content=(
                f"Not inside a git repository (checked: {cwd}). "
                f"Initialize a repo first with the shell tool: 'git init'"
            ),
            risk=RiskLevel.LOW,
            source="git",
            success=False,
            error_type="not_a_repo",
        )

    # Run the operation in a thread pool (all git ops are synchronous subprocess calls)
    def _sync_dispatch() -> ToolResult:
        if operation == "status":
            return _git_status(cwd)
        elif operation == "diff":
            staged = args.get("staged", False)
            return _git_diff(cwd, staged=staged)
        elif operation == "log":
            count = args.get("count", args.get("limit", 10))
            try:
                count = int(count)
            except (ValueError, TypeError):
                count = 10
            return _git_log(cwd, count=count)
        elif operation == "branch":
            name = args.get("name", "").strip()
            return _git_branch(cwd, name=name)
        elif operation == "checkout":
            branch = args.get("branch", "").strip()
            return _git_checkout(cwd, branch=branch)
        elif operation == "commit":
            message = args.get("message", "").strip()
            add_all = args.get("add_all", False)
            return _git_commit(cwd, message=message, add_all=add_all)
        elif operation == "merge":
            branch = args.get("branch", "").strip()
            return _git_merge(cwd, branch=branch)
        elif operation == "stash":
            action = args.get("action", "push").strip().lower()
            msg = args.get("message", "").strip()
            return _git_stash(cwd, action=action, message=msg)
        elif operation == "reset":
            mode = args.get("mode", "--mixed").strip()
            ref = args.get("ref", "HEAD").strip()
            return _git_reset(cwd, mode=mode, ref=ref)
        else:
            return ToolResult(
                content=(
                    f"Unknown git operation '{operation}'. "
                    f"Valid operations: status, diff, log, branch, checkout, "
                    f"commit, merge, stash, reset."
                ),
                risk=RiskLevel.LOW,
                source="git",
                success=False,
                error_type="unknown_operation",
            )

    try:
        return await asyncio.get_event_loop().run_in_executor(None, _sync_dispatch)
    except Exception as exc:
        logger.error("[git_tool] unexpected error: %s", exc, exc_info=True)
        return ToolResult(
            content=f"Git tool internal error: {exc}",
            risk=RiskLevel.HIGH,
            source="git",
            success=False,
            error_type="internal_error",
            error_message=str(exc),
        )


# ── Registration ───────────────────────────────────────────────────────────────

register_tool(
    Intent.GIT,
    git_dispatch,
    description=(
        "Structured Git operations — use this instead of shell for git commands. "
        "Operations: status (working tree state), diff (unstaged or staged changes), "
        "log (commit history), branch (list or create branches), checkout (switch branches), "
        "commit (commit staged or all changes with a message), merge (merge a branch), "
        "stash (push/pop/list stashed changes), reset (--soft/--mixed to undo commits; "
        "--hard is blocked for safety — use shell directly if absolutely needed)."
    ),
    cost=0.1,
    latency_ms=500,
    parallelizable=False,  # state-altering — keep sequential
)
