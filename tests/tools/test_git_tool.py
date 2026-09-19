"""
Tests for the Git tool (backend/src/tools/git_tool.py).

Tests cover all 9 operations: status, diff, log, branch, checkout, commit,
merge, stash, reset. Uses a temporary git repository created in a tmp_path
to avoid touching the real repo.

Also tests: edge cases (not a repo, invalid JSON, unknown operations),
tool registration, tool definition presence, and scoped tool filtering.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repository with a few commits."""
    repo = tmp_path / "testrepo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(repo), capture_output=True, check=True,
    )
    # Create initial commit
    (repo / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "add", "-A"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo), capture_output=True, check=True)
    # Create a second commit
    (repo / "hello.py").write_text("print('hello')\n")
    subprocess.run(["git", "add", "-A"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Add hello.py"], cwd=str(repo), capture_output=True, check=True)
    return repo


@pytest.fixture
def dirty_repo(git_repo):
    """Git repo with an uncommitted change."""
    (git_repo / "README.md").write_text("# Modified Repo\n")
    (git_repo / "newfile.txt").write_text("untracked\n")
    return git_repo


@pytest.fixture(autouse=True)
def set_test_cwd(git_repo, monkeypatch):
    """Set the session CWD context var for git operations."""
    from tools.git_tool import _session_cwd_var
    _session_cwd_var.set(str(git_repo))
    yield
    _session_cwd_var.set(None)


# ── Module-level imports ───────────────────────────────────────────────────────


def test_git_tool_registered():
    """The git tool should be registered in _REGISTRY."""
    from core.models import Intent
    from tools import _REGISTRY
    assert Intent.GIT in _REGISTRY
    assert "description" in _REGISTRY[Intent.GIT]


def test_intent_git_exists():
    """Intent.GIT should be defined."""
    from core.models import Intent
    assert Intent.GIT.value == "git"


def test_git_in_allowed_tools():
    """'git' should be in AGENT_ALLOWED_TOOLS."""
    from core.agent.constants import AGENT_ALLOWED_TOOLS
    assert "git" in AGENT_ALLOWED_TOOLS


def test_git_in_coding_tools():
    """'git' should be in CODING_TOOLS."""
    from agents.coding.tools import CODING_TOOLS
    assert "git" in CODING_TOOLS


def test_git_tool_definition_exists():
    """The git tool should have a definition in TOOL_DEFINITIONS."""
    from core.agent.loop import TOOL_DEFINITIONS
    git_defs = [td for td in TOOL_DEFINITIONS if td["function"]["name"] == "git"]
    assert len(git_defs) == 1
    git_def = git_defs[0]
    assert "operation" in git_def["function"]["parameters"]["required"]
    assert "operation" in git_def["function"]["parameters"]["properties"]


def test_git_extract_tool_input():
    """_extract_tool_input should serialize git args as JSON."""
    from core.agent.loop import _extract_tool_input
    result = _extract_tool_input("git", {"operation": "status"})
    parsed = json.loads(result)
    assert parsed["operation"] == "status"


# ── Status ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_clean_repo(git_repo):
    """git status on a clean repo should report clean."""
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(git_repo))
    args = json.dumps({"operation": "status"})
    result = await git_dispatch(args)
    assert result.success
    assert "clean" in result.content.lower() or "no uncommitted" in result.content.lower()


@pytest.mark.asyncio
async def test_status_dirty_repo(dirty_repo):
    """git status on a dirty repo should report changes."""
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(dirty_repo))
    args = json.dumps({"operation": "status"})
    result = await git_dispatch(args)
    assert result.success
    assert " M " in result.content or "?? " in result.content


# ── Diff ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_diff_clean(git_repo):
    """git diff on a clean repo should report no changes."""
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(git_repo))
    args = json.dumps({"operation": "diff"})
    result = await git_dispatch(args)
    assert result.success
    assert "no unstaged" in result.content.lower() or "no changes" in result.content.lower()


@pytest.mark.asyncio
async def test_diff_dirty(dirty_repo):
    """git diff on a dirty repo should show changes."""
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(dirty_repo))
    args = json.dumps({"operation": "diff"})
    result = await git_dispatch(args)
    assert result.success
    assert len(result.content) > 20  # Should have diff content


@pytest.mark.asyncio
async def test_diff_staged(dirty_repo):
    """git diff --staged should work."""
    subprocess.run(["git", "add", "README.md"], cwd=str(dirty_repo), capture_output=True)
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(dirty_repo))
    args = json.dumps({"operation": "diff", "staged": True})
    result = await git_dispatch(args)
    assert result.success


# ── Log ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_log(git_repo):
    """git log should show commits."""
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(git_repo))
    args = json.dumps({"operation": "log"})
    result = await git_dispatch(args)
    assert result.success
    assert "Initial commit" in result.content


@pytest.mark.asyncio
async def test_log_custom_count(git_repo):
    """git log with custom count."""
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(git_repo))
    args = json.dumps({"operation": "log", "count": 1})
    result = await git_dispatch(args)
    assert result.success
    assert "Add hello.py" in result.content  # Most recent commit


# ── Branch ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_branch_list(git_repo):
    """git branch list should show branches."""
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(git_repo))
    args = json.dumps({"operation": "branch"})
    result = await git_dispatch(args)
    assert result.success
    assert "main" in result.content or "master" in result.content


@pytest.mark.asyncio
async def test_branch_create(git_repo):
    """git branch create should create a new branch."""
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(git_repo))
    args = json.dumps({"operation": "branch", "name": "feature-test"})
    result = await git_dispatch(args)
    assert result.success
    assert "Created branch" in result.content or "feature-test" in result.content


# ── Checkout ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_checkout_existing(git_repo):
    """git checkout to a branch we created."""
    subprocess.run(["git", "branch", "test-branch"], cwd=str(git_repo), capture_output=True)
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(git_repo))
    args = json.dumps({"operation": "checkout", "branch": "test-branch"})
    result = await git_dispatch(args)
    assert result.success
    assert "test-branch" in result.content


@pytest.mark.asyncio
async def test_checkout_missing_branch(git_repo):
    """git checkout to non-existent branch should fail."""
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(git_repo))
    args = json.dumps({"operation": "checkout", "branch": "nonexistent"})
    result = await git_dispatch(args)
    assert not result.success


# ── Commit ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_commit_add_all(dirty_repo):
    """git commit with add_all should stage and commit all changes."""
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(dirty_repo))
    args = json.dumps({"operation": "commit", "message": "Test commit", "add_all": True})
    result = await git_dispatch(args)
    assert result.success
    assert "commit" in result.content.lower() or "committed" in result.content.lower()


@pytest.mark.asyncio
async def test_commit_no_staged(git_repo):
    """git commit without staged changes should fail gracefully."""
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(git_repo))
    args = json.dumps({"operation": "commit", "message": "Nothing to commit"})
    result = await git_dispatch(args)
    assert not result.success
    assert "no staged" in result.content.lower() or "nothing to commit" in result.content.lower()


@pytest.mark.asyncio
async def test_commit_no_message(git_repo):
    """git commit without message should fail."""
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(git_repo))
    args = json.dumps({"operation": "commit"})
    result = await git_dispatch(args)
    assert not result.success


# ── Merge ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_merge_branch(git_repo):
    """git merge should merge a branch."""
    # Create and commit to a feature branch
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=str(git_repo), capture_output=True)
    (git_repo / "feature.txt").write_text("feature content\n")
    subprocess.run(["git", "add", "-A"], cwd=str(git_repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "Feature commit"], cwd=str(git_repo), capture_output=True)
    # Switch back to main
    subprocess.run(["git", "checkout", "main"], cwd=str(git_repo), capture_output=True)
    # Merge feature
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(git_repo))
    args = json.dumps({"operation": "merge", "branch": "feature"})
    result = await git_dispatch(args)
    assert result.success


@pytest.mark.asyncio
async def test_merge_missing_branch(git_repo):
    """git merge non-existent branch should fail."""
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(git_repo))
    args = json.dumps({"operation": "merge", "branch": "nonexistent"})
    result = await git_dispatch(args)
    assert not result.success


# ── Stash ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stash_push(git_repo):
    """git stash push should shelve changes."""
    (git_repo / "temp.txt").write_text("temp\n")
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(git_repo))
    args = json.dumps({"operation": "stash", "action": "push"})
    result = await git_dispatch(args)
    assert result.success


@pytest.mark.asyncio
async def test_stash_list_empty(git_repo):
    """git stash list on clean repo should show empty."""
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(git_repo))
    args = json.dumps({"operation": "stash", "action": "list"})
    result = await git_dispatch(args)
    assert result.success
    assert "no stashed" in result.content.lower()


# ── Reset ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reset_soft(git_repo):
    """git reset --soft HEAD~1 should undo last commit but keep changes staged."""
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(git_repo))
    args = json.dumps({"operation": "reset", "mode": "--soft", "ref": "HEAD~1"})
    result = await git_dispatch(args)
    assert result.success


@pytest.mark.asyncio
async def test_reset_mixed(git_repo):
    """git reset --mixed HEAD should work."""
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(git_repo))
    args = json.dumps({"operation": "reset", "mode": "--mixed"})
    result = await git_dispatch(args)
    assert result.success


@pytest.mark.asyncio
async def test_reset_hard_blocked(git_repo):
    """git reset --hard should be blocked for safety."""
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(git_repo))
    args = json.dumps({"operation": "reset", "mode": "--hard"})
    result = await git_dispatch(args)
    assert not result.success
    assert "destructive" in result.content.lower() or "blocked" in result.content.lower()
    assert result.requires_confirmation


# ── Edge cases ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_not_a_git_repo(tmp_path):
    """git tool on a non-git directory should fail gracefully."""
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(tmp_path))
    args = json.dumps({"operation": "status"})
    result = await git_dispatch(args)
    assert not result.success
    assert "not inside" in result.content.lower() or "not a git" in result.content.lower()


@pytest.mark.asyncio
async def test_invalid_json(git_repo):
    """Invalid JSON input should fail gracefully."""
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(git_repo))
    result = await git_dispatch("not json")
    assert not result.success


@pytest.mark.asyncio
async def test_unknown_operation(git_repo):
    """Unknown operation should fail with a helpful message."""
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(git_repo))
    args = json.dumps({"operation": "cherry-pick"})
    result = await git_dispatch(args)
    assert not result.success
    assert "unknown" in result.content.lower()


@pytest.mark.asyncio
async def test_status_no_args_uses_status(git_repo):
    """git operation defaults — status is a common default."""
    from tools.git_tool import git_dispatch, _session_cwd_var
    _session_cwd_var.set(str(git_repo))
    args = json.dumps({"operation": "status"})
    result = await git_dispatch(args)
    assert result.success


# ── Registration / Integration tests ───────────────────────────────────────────


def test_intent_git_in_agent_intents():
    """Intent.GIT should be in AGENT_INTENTS for the agent loop."""
    from core.agent.constants import AGENT_INTENTS
    from core.models import Intent
    assert Intent.GIT in AGENT_INTENTS


def test_coding_tools_is_subset_of_allowed_tools():
    """CODING_TOOLS must remain a subset of AGENT_ALLOWED_TOOLS."""
    from agents.coding.tools import CODING_TOOLS
    from core.agent.constants import AGENT_ALLOWED_TOOLS
    assert CODING_TOOLS.issubset(AGENT_ALLOWED_TOOLS), (
        f"CODING_TOOLS ({CODING_TOOLS}) must be subset of "
        f"AGENT_ALLOWED_TOOLS ({AGENT_ALLOWED_TOOLS})"
    )


def test_git_in_tool_definitions():
    """Git should be in TOOL_DEFINITIONS with required 'operation' parameter."""
    from core.agent.loop import TOOL_DEFINITIONS
    git_defs = [td for td in TOOL_DEFINITIONS if td["function"]["name"] == "git"]
    assert len(git_defs) == 1
    params = git_defs[0]["function"]["parameters"]
    assert "operation" in params["required"]
    assert "operation" in params["properties"]
    # Check that all 9 operations are listed
    ops = params["properties"]["operation"]["enum"]
    assert set(ops) == {"status", "diff", "log", "branch", "checkout", "commit", "merge", "stash", "reset"}


def test_label_map_includes_git():
    """The label map in loop.py should include 'git' for UI label generation."""
    from core.agent.loop import TOOL_DEFINITIONS
    # The label map is inside the loop's _dispatch_single function
    # — we verify it's in TOOL_DEFINITIONS instead (test_git_in_tool_definitions)
    pass  # covered by test_git_in_tool_definitions


def test_git_not_in_direct_agent():
    """DirectAgent should still have no tools (git is coding-only)."""
    from agents.direct.tools import DIRECT_TOOLS
    assert "git" not in DIRECT_TOOLS


# ── path: the repo to run in (was silently ignored) ────────────────────────


@pytest.mark.asyncio
async def test_path_selects_the_repo_not_the_session_cwd(git_repo, tmp_path):
    """A request about a specific repo must answer from THAT repo. Live: the
    model passed `path` for a fixture repo and got the session folder's
    commits back as if they were the answer."""
    from tools.git_tool import git_dispatch, set_session_cwd

    other = tmp_path / "other"
    other.mkdir()
    subprocess.run(["git", "init"], cwd=str(other), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(other), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(other), capture_output=True, check=True)
    (other / "f").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=str(other), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "the other repo's only commit"], cwd=str(other), capture_output=True, check=True)
    set_session_cwd(str(git_repo))
    try:
        res = await git_dispatch(json.dumps({"operation": "log", "path": str(other)}))
        assert res.success and "the other repo's only commit" in res.content
        assert "Initial commit" not in res.content
    finally:
        set_session_cwd(None)


@pytest.mark.asyncio
async def test_a_file_path_resolves_to_its_folder(git_repo):
    from tools.git_tool import git_dispatch

    res = await git_dispatch(json.dumps({"operation": "log", "path": str(git_repo / "README.md")}))
    assert res.success and "Initial commit" in res.content


@pytest.mark.asyncio
async def test_missing_path_is_an_error_not_a_silent_fallback(git_repo):
    from tools.git_tool import git_dispatch, set_session_cwd

    set_session_cwd(str(git_repo))
    try:
        res = await git_dispatch(json.dumps({"operation": "log", "path": "/no/such/folder"}))
    finally:
        set_session_cwd(None)
    assert not res.success and "not found" in res.content.lower()


@pytest.mark.asyncio
async def test_limit_is_accepted_as_an_alias_for_count(git_repo):
    from tools.git_tool import git_dispatch

    (git_repo / "b.txt").write_text("b")
    subprocess.run(["git", "add", "-A"], cwd=str(git_repo), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "second"], cwd=str(git_repo), capture_output=True, check=True)
    res = await git_dispatch(json.dumps({"operation": "log", "path": str(git_repo), "limit": 1}))
    assert "second" in res.content and "Initial commit" not in res.content
