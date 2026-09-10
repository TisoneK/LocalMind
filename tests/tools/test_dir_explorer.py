"""
Tests for the dir_explorer tool (bounded read-only folder inspection).

Design contract (docs/explorer_tool_design.md): ONE dispatch entry point
(Intent.DIR_EXPLORER) with three operations (list / tree / stat). Paths are
security-gated via settings.is_path_allowed, symlinks are never followed,
heavy directories are listed but never descended, walks are bounded
(time budget, entry cap, depth cap), and every operation returns NORMALIZED
metadata rows ({type, path, name, size, modified, detail}) so the Parent
agent presents without parsing prose. The tool never raises — every failure
degrades to ToolResult(success=False) — and never returns file bytes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.models import Intent
from tools import dispatch, input_is_optional


def _allow(monkeypatch, tmp_path):
    """Make tmp_path an allowed folder (tmp is normally outside ~).

    Same pattern as test_system_search: the security gate consults
    core.config._allowed_user_folders, so point it at the test tree.
    """
    monkeypatch.setattr(
        "core.config._allowed_user_folders",
        lambda: [str(tmp_path)],
    )


def _sample_tree(tmp_path):
    """A small tree: 2 files + sub/ with one file + a heavy dir with a file."""
    (tmp_path / "b_file.txt").write_text("bbbb")
    (tmp_path / "a_file.txt").write_text("aa")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "inner.md").write_text("inner")
    heavy = tmp_path / "node_modules"
    heavy.mkdir()
    (heavy / "hidden_dep.js").write_text("should never be listed")
    return tmp_path


def _payload(**kwargs) -> str:
    return json.dumps(kwargs)


_ROW_KEYS = {"type", "path", "name", "size", "modified", "detail"}


# ── Registration ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_registered_and_not_input_optional():
    """A bare call must be rejected as invalid_input, not dispatched blind."""
    assert input_is_optional(Intent.DIR_EXPLORER) is False
    result = await dispatch(Intent.DIR_EXPLORER, "")
    assert result is not None
    assert result.success is False
    assert result.error_type == "invalid_input"


# ── Operation: list ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_returns_normalized_rows(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    root = _sample_tree(tmp_path)
    result = await dispatch(
        Intent.DIR_EXPLORER, _payload(operation="list", path=str(root))
    )
    assert result.success is True
    meta = result.metadata
    assert meta["operation"] == "list"
    assert meta["walk_complete"] is True
    names = [r["name"] for r in meta["results"]]
    # dirs first, then files by name: sub/ + node_modules/ before a_file/b_file
    assert names == ["node_modules", "sub", "a_file.txt", "b_file.txt"]
    for row in meta["results"]:
        assert _ROW_KEYS <= set(row)
        assert row["type"] in ("dir", "file", "symlink")
        assert row["path"].startswith(str(root))
    by_name = {r["name"]: r for r in meta["results"]}
    assert by_name["a_file.txt"]["size"] == 2
    assert by_name["a_file.txt"]["type"] == "file"
    assert by_name["sub"]["type"] == "dir"


@pytest.mark.asyncio
async def test_list_dirs_first_false_sorts_by_name(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    root = _sample_tree(tmp_path)
    result = await dispatch(
        Intent.DIR_EXPLORER,
        _payload(operation="list", path=str(root), dirs_first=False),
    )
    names = [r["name"] for r in result.metadata["results"]]
    assert names == ["a_file.txt", "b_file.txt", "node_modules", "sub"]


@pytest.mark.asyncio
async def test_list_marks_heavy_dirs_skipped_without_descending(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    root = _sample_tree(tmp_path)
    result = await dispatch(
        Intent.DIR_EXPLORER, _payload(operation="list", path=str(root))
    )
    by_name = {r["name"]: r for r in result.metadata["results"]}
    assert "hidden_dep.js" not in by_name  # never descended
    assert "skipped" in by_name["node_modules"]["detail"]


@pytest.mark.asyncio
async def test_list_entry_cap_is_honest(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    root = _sample_tree(tmp_path)
    result = await dispatch(
        Intent.DIR_EXPLORER,
        _payload(operation="list", path=str(root), max_entries=2),
    )
    meta = result.metadata
    assert len(meta["results"]) == 2
    assert meta["truncated"] is True
    assert meta["walk_complete"] is False
    assert "PARTIAL" in result.content  # the output itself says so


@pytest.mark.asyncio
async def test_list_rejects_file_path(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    f = tmp_path / "only.txt"
    f.write_text("x")
    result = await dispatch(Intent.DIR_EXPLORER, _payload(operation="list", path=str(f)))
    assert result.success is False
    assert result.error_type == "invalid_input"


# ── Operation: tree ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tree_sketch_is_bounded_and_indented(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    root = _sample_tree(tmp_path)
    deep = root / "sub" / "deeper"
    deep.mkdir()
    (deep / "cut.txt").write_text("x")
    result = await dispatch(
        Intent.DIR_EXPLORER, _payload(operation="tree", path=str(root), depth=2)
    )
    assert result.success is True
    meta = result.metadata
    assert meta["operation"] == "tree"
    assert meta["depth"] == 2
    # plain-text indented sketch (owner decision): root line, then 2-space levels
    lines = result.content.splitlines()
    assert lines[0] == f"{root}/"
    assert any(ln.startswith("  sub/") for ln in lines)
    assert any(ln.startswith("    deeper/") for ln in lines)
    # depth cut is announced, not silent
    assert meta["depth_limited"] is True
    assert "cut.txt" not in {r["name"] for r in meta["results"]}
    assert "depth limit 2" in result.content


@pytest.mark.asyncio
async def test_tree_depth_hard_cap(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    root = _sample_tree(tmp_path)
    result = await dispatch(
        Intent.DIR_EXPLORER, _payload(operation="tree", path=str(root), depth=99)
    )
    assert result.metadata["depth"] == 4  # hard cap, clamped not trusted


@pytest.mark.asyncio
async def test_tree_never_descends_heavy_dirs(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    root = _sample_tree(tmp_path)
    result = await dispatch(
        Intent.DIR_EXPLORER, _payload(operation="tree", path=str(root), depth=4)
    )
    names = {r["name"] for r in result.metadata["results"]}
    assert "hidden_dep.js" not in names
    assert "node_modules" in names
    assert "skipped" in result.content


@pytest.mark.asyncio
async def test_tree_entry_cap_is_honest(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    root = _sample_tree(tmp_path)
    result = await dispatch(
        Intent.DIR_EXPLORER,
        _payload(operation="tree", path=str(root), max_entries=1),
    )
    meta = result.metadata
    assert len(meta["results"]) <= 1
    assert meta["walk_complete"] is False


# ── Operation: stat ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stat_returns_single_normalized_row(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    root = _sample_tree(tmp_path)
    target = root / "a_file.txt"
    result = await dispatch(Intent.DIR_EXPLORER, _payload(operation="stat", path=str(target)))
    assert result.success is True
    meta = result.metadata
    assert meta["operation"] == "stat"
    assert meta["exists"] is True
    assert len(meta["results"]) == 1
    row = meta["results"][0]
    assert _ROW_KEYS <= set(row)
    assert row["type"] == "file"
    assert row["size"] == 2
    assert "Mode:" in result.content


@pytest.mark.asyncio
async def test_stat_missing_path_is_not_found(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    result = await dispatch(
        Intent.DIR_EXPLORER, _payload(operation="stat", path=str(tmp_path / "ghost"))
    )
    assert result.success is False
    assert result.error_type == "not_found"


# ── Security contract ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_out_of_root_is_flat_deny(tmp_path, monkeypatch):
    """Outside the allowed folders: success=False, no confirmation prompt."""
    _allow(monkeypatch, tmp_path)
    result = await dispatch(
        Intent.DIR_EXPLORER, _payload(operation="list", path=str(Path.home()))
    )
    assert result.success is False
    assert result.error_type == "permission_denied"
    assert result.requires_confirmation is False


@pytest.mark.asyncio
async def test_traversal_paths_are_denied(tmp_path, monkeypatch):
    """..' inside an allowed root that escapes it must not list outside."""
    _allow(monkeypatch, tmp_path)
    inside = tmp_path / "in"
    inside.mkdir()
    escape = str(inside) + os.sep + ".." + os.sep + ".." + os.sep + ".."
    result = await dispatch(Intent.DIR_EXPLORER, _payload(operation="list", path=escape))
    assert result.success is False
    assert result.error_type == "permission_denied"


@pytest.mark.asyncio
async def test_symlinks_are_never_followed(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("TOPSECRET")
    link = root / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation requires privileges on this setup")
    result = await dispatch(Intent.DIR_EXPLORER, _payload(operation="list", path=str(root)))
    row = result.metadata["results"][0]
    assert row["type"] == "symlink"
    assert "not followed" in row["detail"]
    # the tool lists NAMES only — the link target's contents can never appear
    assert "TOPSECRET" not in result.content


@pytest.mark.asyncio
async def test_no_file_bytes_in_any_operation(tmp_path, monkeypatch):
    """The explorer's blanket no-secret-leak property: names + metadata only."""
    _allow(monkeypatch, tmp_path)
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".env").write_text("API_KEY=super-secret-value")
    for op in ("list", "tree", "stat"):
        path = str(root / ".env") if op == "stat" else str(root)
        result = await dispatch(Intent.DIR_EXPLORER, _payload(operation=op, path=path))
        assert "super-secret-value" not in result.content
        assert "super-secret-value" not in json.dumps(result.metadata)


# ── Robustness: never raises, always a ToolResult ────────────────────────────


@pytest.mark.asyncio
async def test_bad_json_degrades(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    result = await dispatch(Intent.DIR_EXPLORER, '{"operation": "list", "path": ')
    assert result.success is False
    assert result.error_type == "invalid_input"


@pytest.mark.asyncio
async def test_unknown_operation_degrades(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    result = await dispatch(
        Intent.DIR_EXPLORER, _payload(operation="explore", path=str(tmp_path))
    )
    assert result.success is False
    assert result.error_type == "invalid_input"
    assert "list, tree, stat" in result.content


@pytest.mark.asyncio
async def test_missing_root_lists_nothing_blindly(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    result = await dispatch(
        Intent.DIR_EXPLORER, _payload(operation="list", path=str(tmp_path / "gone"))
    )
    assert result.success is False
    assert result.error_type == "not_found"


# ── Weak-model tolerance: plain string input ─────────────────────────────────


@pytest.mark.asyncio
async def test_plain_string_inputs(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    root = _sample_tree(tmp_path)
    tree_res = await dispatch(Intent.DIR_EXPLORER, f"tree {root}")
    assert tree_res.success is True and tree_res.metadata["operation"] == "tree"
    list_res = await dispatch(Intent.DIR_EXPLORER, f"list {root}")
    assert list_res.success is True and list_res.metadata["operation"] == "list"
    bare_res = await dispatch(Intent.DIR_EXPLORER, str(root))
    assert bare_res.success is True and bare_res.metadata["operation"] == "list"


# ── Routing: folder-inspection phrasing reaches the agent loop ───────────────


def test_local_discovery_covers_inspection_phrasing():
    from core.trivial_input import _is_local_discovery

    assert _is_local_discovery("what's in my downloads folder")
    assert _is_local_discovery("show me the structure of this repo")
    assert _is_local_discovery("look at the files in backend/src")
    assert _is_local_discovery("what does this project look like")
    # knowledge questions must stay conversational
    assert not _is_local_discovery("explain the structure of a python class")
    assert not _is_local_discovery("what's in a name?")
    assert not _is_local_discovery("what does a black hole look like")
