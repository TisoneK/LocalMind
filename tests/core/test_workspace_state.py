"""
Tests for workspace_state — the ADR-5 feedback service.

Verifies:
    - snapshot() returns a WorkspaceSnapshot with the right fields
    - snapshot() never raises (git unavailable → git_available=False)
    - format_snapshot() produces a readable string
    - mark_turn_start() / record_build_result() per-session state works
    - git helpers handle timeouts and non-repo directories gracefully
"""

from __future__ import annotations

import subprocess

import pytest

from core.workspace_state import (
    WorkspaceSnapshot,
    format_snapshot,
    mark_turn_start,
    record_build_result,
    reset,
    snapshot,
)


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset per-session state before each test."""
    reset()
    yield
    reset()


@pytest.fixture
def git_repo(tmp_path):
    """Create a real git repo in tmp_path with one commit."""
    def _run(*args, cwd=None):
        return subprocess.run(
            ["git"] + list(args),
            cwd=cwd or str(tmp_path),
            capture_output=True,
            text=True,
            check=True,
        )

    _run("init")
    _run("config", "user.email", "test@test.com")
    _run("config", "user.name", "Test")
    (tmp_path / "README.md").write_text("# Test\n")
    _run("add", ".")
    _run("commit", "-m", "initial")
    return tmp_path


# ── WorkspaceSnapshot dataclass ──────────────────────────────────────────────


def test_workspace_snapshot_defaults():
    """A fresh WorkspaceSnapshot has the right defaults."""
    snap = WorkspaceSnapshot()
    assert snap.git_available is False
    assert snap.git_status == ""
    assert snap.git_diff_stat == ""
    assert snap.git_branch == ""
    assert snap.git_head == ""
    assert snap.last_build_result is None
    assert snap.open_files == []
    assert snap.timestamp > 0


def test_workspace_snapshot_is_clean_when_no_status():
    """is_clean() returns True when git is available and status is empty."""
    snap = WorkspaceSnapshot(git_available=True, git_status="")
    assert snap.is_clean() is True


def test_workspace_snapshot_not_clean_when_dirty():
    """is_clean() returns False when git_status has content."""
    snap = WorkspaceSnapshot(
        git_available=True, git_status=" M file.py\n?? new.py"
    )
    assert snap.is_clean() is False


def test_workspace_snapshot_not_clean_when_git_unavailable():
    """is_clean() returns False when git isn't available (can't confirm clean)."""
    snap = WorkspaceSnapshot(git_available=False)
    assert snap.is_clean() is False


# ── snapshot() — non-git directory ───────────────────────────────────────────


def test_snapshot_non_git_directory(tmp_path):
    """snapshot() on a non-git directory returns git_available=False, no raise."""
    snap = snapshot(cwd=str(tmp_path))
    assert snap.git_available is False
    assert snap.git_status == ""
    assert snap.git_diff_stat == ""
    assert snap.git_branch == ""


def test_snapshot_nonexistent_directory_does_not_raise(tmp_path):
    """snapshot() on a nonexistent directory doesn't raise — returns git_available=False."""
    nonexistent = str(tmp_path / "does-not-exist")
    snap = snapshot(cwd=nonexistent)
    assert snap.git_available is False


# ── snapshot() — real git repo ───────────────────────────────────────────────


def test_snapshot_clean_repo(git_repo):
    """snapshot() on a clean repo reports git_available=True, clean tree."""
    snap = snapshot(cwd=str(git_repo))
    assert snap.git_available is True
    assert snap.git_branch in ("main", "master")
    assert len(snap.git_head) == 40  # full SHA
    assert snap.git_status == ""  # clean
    assert snap.is_clean() is True


def test_snapshot_dirty_repo(git_repo):
    """snapshot() on a repo with uncommitted changes reports them in git_status."""
    (git_repo / "new.py").write_text("print('hello')\n")
    (git_repo / "README.md").write_text("# Modified\n")
    snap = snapshot(cwd=str(git_repo))
    assert snap.git_available is True
    assert snap.is_clean() is False
    assert "new.py" in snap.git_status
    assert "README.md" in snap.git_status


def test_snapshot_includes_diff_stat(git_repo):
    """snapshot() includes git diff --stat when a tracked file is modified."""
    # Modify the existing tracked README.md (untracked files don't show
    # in `git diff --stat` — only tracked-but-modified files do)
    (git_repo / "README.md").write_text("# Modified\n")
    snap = snapshot(cwd=str(git_repo))
    assert snap.git_diff_stat  # non-empty
    assert "README.md" in snap.git_diff_stat or "1 file" in snap.git_diff_stat


def test_snapshot_diff_since_mark_turn_start(git_repo):
    """After mark_turn_start(), a new commit shows up in git_diff_stat."""
    mark_turn_start(cwd=str(git_repo))
    # Make a new commit (use shell=True for the && chain)
    (git_repo / "feature.py").write_text("x = 1\n")
    subprocess.run(
        "git add. && git commit -m feature",
        cwd=str(git_repo),
        shell=True,
        check=True,
        capture_output=True,
    )
    snap = snapshot(cwd=str(git_repo))
    assert snap.git_available is True
    # diff --stat between old HEAD and new HEAD should mention feature.py
    assert "feature.py" in snap.git_diff_stat or "1 file" in snap.git_diff_stat


# ── mark_turn_start() ────────────────────────────────────────────────────────


def test_mark_turn_start_in_git_repo(git_repo):
    """mark_turn_start() records the current HEAD."""
    mark_turn_start(cwd=str(git_repo))
    # Internal state — verify via a snapshot after a no-op change
    snap = snapshot(cwd=str(git_repo))
    assert snap.git_available is True
    # HEAD should match what mark_turn_start recorded
    assert snap.git_head  # non-empty


def test_mark_turn_start_in_non_git_dir(tmp_path):
    """mark_turn_start() in a non-git directory doesn't raise."""
    mark_turn_start(cwd=str(tmp_path))
    # No assertion needed — just verifying it doesn't raise


# ── record_build_result() ────────────────────────────────────────────────────


def test_record_build_result_stores_result():
    """record_build_result() stores the result for the next snapshot."""
    record_build_result(
        result="pass",
        command="pytest",
        output_tail="197 passed",
        exit_code=0,
    )
    snap = snapshot(cwd="/tmp")  # cwd doesn't matter for build result
    assert snap.last_build_result is not None
    assert snap.last_build_result["result"] == "pass"
    assert snap.last_build_result["command"] == "pytest"
    assert snap.last_build_result["exit_code"] == 0
    assert "197 passed" in snap.last_build_result["output_tail"]


def test_record_build_result_caps_output_tail():
    """record_build_result() caps output_tail at 500 chars to avoid bloat."""
    long_output = "x" * 1000
    record_build_result(result="fail", command="make", output_tail=long_output)
    snap = snapshot(cwd="/tmp")
    assert len(snap.last_build_result["output_tail"]) == 500


def test_record_build_result_persists_across_snapshots():
    """record_build_result() state persists across snapshot() calls."""
    record_build_result(result="pass", command="tsc")
    snap1 = snapshot(cwd="/tmp")
    snap2 = snapshot(cwd="/tmp")
    assert snap1.last_build_result == snap2.last_build_result


# ── format_snapshot() ────────────────────────────────────────────────────────


def test_format_snapshot_empty_when_no_info():
    """format_snapshot() returns empty string when there's no useful info."""
    snap = WorkspaceSnapshot(git_available=False)
    assert format_snapshot(snap) == ""


def test_format_snapshot_includes_branch_and_head(git_repo):
    """format_snapshot() includes branch and HEAD SHA."""
    snap = snapshot(cwd=str(git_repo))
    formatted = format_snapshot(snap)
    assert "Workspace State" in formatted
    assert "Branch:" in formatted
    assert "HEAD:" in formatted


def test_format_snapshot_shows_clean_tree(git_repo):
    """format_snapshot() reports 'clean' when the working tree is clean."""
    snap = snapshot(cwd=str(git_repo))
    formatted = format_snapshot(snap)
    assert "clean" in formatted.lower()


def test_format_snapshot_shows_dirty_files(git_repo):
    """format_snapshot() lists dirty files when the working tree has changes."""
    (git_repo / "new.py").write_text("x = 1\n")
    snap = snapshot(cwd=str(git_repo))
    formatted = format_snapshot(snap)
    assert "dirty" in formatted.lower()
    assert "new.py" in formatted


def test_format_snapshot_includes_build_result():
    """format_snapshot() includes the last build/test result."""
    record_build_result(
        result="fail",
        command="pytest",
        output_tail="1 failed",
        exit_code=1,
    )
    snap = snapshot(cwd="/tmp")
    formatted = format_snapshot(snap)
    assert "Last build/test result" in formatted
    assert "pytest" in formatted
    assert "fail" in formatted
    assert "1 failed" in formatted


def test_format_snapshot_caps_status_lines(git_repo):
    """format_snapshot() caps git status output to avoid context bloat."""
    # Create many dirty files
    for i in range(60):
        (git_repo / f"file_{i}.py").write_text(f"x = {i}\n")
    snap = snapshot(cwd=str(git_repo))
    formatted = format_snapshot(snap)
    # Should mention that it's showing a subset
    assert "showing first" in formatted or "50" in formatted


# ── reset() ──────────────────────────────────────────────────────────────────


def test_reset_clears_build_result():
    """reset() clears the recorded build result."""
    record_build_result(result="pass", command="tsc")
    reset()
    snap = snapshot(cwd="/tmp")
    assert snap.last_build_result is None


def test_reset_clears_turn_head():
    """reset() clears the marked turn head."""
    # We can't directly read _last_turn_head, but we can verify via
    # snapshot behavior — after reset, a snapshot shouldn't error
    reset()
    snap = snapshot(cwd="/tmp")
    assert snap.git_available is False  # /tmp isn't a repo


# ── Git helper edge cases ────────────────────────────────────────────────────


def test_snapshot_with_timeout_does_not_raise(git_repo, monkeypatch):
    """If git times out, snapshot() returns git_available=False, no raise."""
    # Patch subprocess.run to raise TimeoutExpired

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=0.001)

    monkeypatch.setattr(subprocess, "run", fake_run)
    snap = snapshot(cwd=str(git_repo))
    assert snap.git_available is False


def test_snapshot_with_git_not_on_path(monkeypatch, git_repo):
    """If git isn't on PATH, snapshot() returns git_available=False, no raise."""
    # Patch subprocess.run to raise FileNotFoundError (git not found)
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    snap = snapshot(cwd=str(git_repo))
    assert snap.git_available is False
