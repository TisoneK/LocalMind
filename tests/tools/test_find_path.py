"""
Tests for the find_path tool (Session 125).

Design contract: name-match search for files AND folders, path-only output,
bounded by depth + result caps, never a full listing. This is the tool that
prevents the "dir C:\\Users\\tison dumped the entire home directory into
context" failure mode — the output size is bounded by construction.
"""

from __future__ import annotations

import pytest
from tools import dispatch
from tools.find_path import _matches, _search


def _allow(monkeypatch, tmp_path):
    """Make tmp_path an allowed folder (tmp is normally outside ~)."""
    from pathlib import Path

    monkeypatch.setattr(
        "core.config._allowed_user_folders",
        lambda: [str(tmp_path), str(Path.home())],
    )


def _tree(tmp_path):
    """Build a small fixture tree and return the root."""
    (tmp_path / "LocalMind").mkdir()
    (tmp_path / "LocalMind" / "README.md").write_text("hi")
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "localmind_notes.txt").write_text("x")
    (tmp_path / "node_modules").mkdir()  # must be skipped
    (tmp_path / "node_modules" / "localmind_pkg").mkdir()  # inside heavy dir
    (tmp_path / "deep").mkdir()
    (tmp_path / "deep" / "mid").mkdir()
    (tmp_path / "deep" / "mid" / "localmind_target").mkdir()
    return tmp_path


# ── _matches (pure helper) ──────────────────────────────────────────────


def test_matches_substring_case_insensitive():
    assert _matches("LocalMind", "localmind")
    assert _matches("my_localmind_notes.txt", "localmind")
    assert not _matches("other", "localmind")


def test_matches_glob():
    assert _matches("LocalMind", "local*")
    assert _matches("README.md", "*.md")
    assert not _matches("README.txt", "*.md")


def test_matches_empty_pattern():
    assert not _matches("anything", "")


# ── _search (bounded walk) ──────────────────────────────────────────────


def test_search_finds_files_and_dirs_by_name(tmp_path):
    tree = _tree(tmp_path)
    matches = _search(tree, "localmind", max_depth=4, max_results=10)
    names = {m.name for m in matches}
    assert "LocalMind" in names  # folder
    assert "localmind_notes.txt" in names  # file
    # node_modules/localmind_pkg must NOT appear (heavy dir skipped)
    assert "localmind_pkg" not in names


def test_search_respects_max_depth(tmp_path):
    tree = _tree(tmp_path)
    # depth 1 from root: LocalMind, other, node_modules, deep
    shallow = _search(tree, "target", max_depth=1, max_results=10)
    assert shallow == []  # target is at depth 3
    deep = _search(tree, "target", max_depth=4, max_results=10)
    assert any(m.name == "localmind_target" for m in deep)


def test_search_respects_max_results(tmp_path):
    tree = _tree(tmp_path)
    (tmp_path / "a_localmind").mkdir()
    (tmp_path / "b_localmind").mkdir()
    (tmp_path / "c_localmind").mkdir()
    matches = _search(tree, "localmind", max_depth=1, max_results=2)
    assert len(matches) == 2


def test_search_skips_heavy_dirs_even_when_matching(tmp_path):
    """A name inside node_modules must not match — heavy dirs are skipped entirely."""
    tree = _tree(tmp_path)
    matches = _search(tree, "localmind", max_depth=4, max_results=10)
    names = {m.name for m in matches}
    assert "localmind_pkg" not in names


# ── dispatch (full tool behavior) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_find_path_returns_paths_only(tmp_path, monkeypatch):
    """End-to-end: JSON args in → ToolResult with matching paths only."""
    _allow(monkeypatch, tmp_path)
    tree = _tree(tmp_path)
    result = await dispatch(
        __import__("core.models", fromlist=["Intent"]).Intent.FIND_PATH,
        f'{{"name": "localmind", "root": "{tree}"}}',
    )
    assert result is not None
    assert result.success is not False
    assert "LocalMind" in result.content
    assert "localmind_notes.txt" in result.content
    assert "node_modules" not in result.content  # heavy dir + contents skipped


@pytest.mark.asyncio
async def test_find_path_blocks_outside_allowed_folders(tmp_path, monkeypatch):
    """Security: searching outside allowed folders is denied."""

    # Allow only a DIFFERENT directory than the search root.
    monkeypatch.setattr(
        "core.config._allowed_user_folders",
        lambda: [str(tmp_path / "only_this")],
    )
    tree = _tree(tmp_path)
    result = await dispatch(
        __import__("core.models", fromlist=["Intent"]).Intent.FIND_PATH,
        f'{{"name": "localmind", "root": "{tree}"}}',
    )
    assert result is not None
    assert result.success is False
    assert "Access denied" in result.content


@pytest.mark.asyncio
async def test_find_path_missing_name_returns_clear_error(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    result = await dispatch(
        __import__("core.models", fromlist=["Intent"]).Intent.FIND_PATH,
        "{}",
    )
    assert result is not None
    assert result.success is False
    assert "name" in result.content


@pytest.mark.asyncio
async def test_find_path_no_match(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    tree = _tree(tmp_path)
    result = await dispatch(
        __import__("core.models", fromlist=["Intent"]).Intent.FIND_PATH,
        f'{{"name": "nonexistent_xyz", "root": "{tree}"}}',
    )
    assert result is not None
    assert "No files or folders matching" in result.content
