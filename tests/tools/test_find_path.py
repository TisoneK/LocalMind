"""
Tests for the find_path tool (Session 125).

Design contract: name-match search for files AND folders, path-only output,
bounded by depth + result caps, never a full listing. This is the tool that
prevents the "dir C:\\Users\\tison dumped the entire home directory into
context" failure mode — the output size is bounded by construction.
"""

from __future__ import annotations

import pytest
from core.models import Intent
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


# ── Catalog contract (Session 194) ─────────────────────────────────────
# glob/grep-style enumeration: walk once (time-budgeted, not result-capped),
# cache the walk, serve filters/pagination from memory. The result is a
# CATALOG (total + folder/type breakdown + a small page) and the structured
# metadata the deterministic file-ops layer picks from.


@pytest.fixture(autouse=True)
def _clear_find_cache():
    """Each test starts with a clean catalog cache (module-global)."""
    from tools.find_path import _FIND_CACHE

    _FIND_CACHE.clear()
    yield
    _FIND_CACHE.clear()


def _cv_tree(tmp_path):
    docs = tmp_path / "Documents"
    docs.mkdir()
    (docs / "CV-TisoneKironget.docx").write_text("x")
    (docs / "CV-JOHN.docx").write_text("x")
    (docs / "CV-MORGAN.pdf").write_text("x")
    desk = tmp_path / "Desktop"
    desk.mkdir()
    (desk / "cv-eng-Arpra.doc").write_text("x")
    return tmp_path


@pytest.mark.asyncio
async def test_catalog_reports_total_groups_and_types(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    tree = _cv_tree(tmp_path)
    result = await dispatch(Intent.FIND_PATH, f'{{"name": "cv", "root": "{tree}"}}')
    assert result.success is not False
    meta = result.metadata
    assert meta["total"] == 4
    assert meta["groups"] == {"Documents": 3, "Desktop": 1}
    assert meta["extensions"] == {"docx": 2, "pdf": 1, "doc": 1}
    assert meta["walk_complete"] is True
    assert "Catalog:" in result.content
    assert "Documents 3" in result.content


@pytest.mark.asyncio
async def test_catalog_paginates_with_offset(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    tree = _cv_tree(tmp_path)
    page1 = await dispatch(
        Intent.FIND_PATH, f'{{"name": "cv", "root": "{tree}", "max_results": 1}}'
    )
    assert page1.metadata["page_size"] == 1
    assert page1.metadata["truncated"] is True
    first = page1.metadata["paths"][0]
    page2 = await dispatch(
        Intent.FIND_PATH,
        f'{{"name": "cv", "root": "{tree}", "max_results": 1, "offset": 1}}',
    )
    assert page2.metadata["offset"] == 1
    assert page2.metadata["paths"][0] != first
    assert page2.metadata["total"] == 4  # same cached walk, stable total


@pytest.mark.asyncio
async def test_ext_filter_narrows_catalog(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    tree = _cv_tree(tmp_path)
    result = await dispatch(
        Intent.FIND_PATH, f'{{"name": "cv", "root": "{tree}", "ext": "pdf"}}'
    )
    assert result.metadata["total"] == 1
    assert result.metadata["paths"][0].endswith(".pdf")
    assert result.metadata["extensions"] == {"pdf": 1}


@pytest.mark.asyncio
async def test_ext_filter_accepts_dot_and_list(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    tree = _cv_tree(tmp_path)
    result = await dispatch(
        Intent.FIND_PATH, f'{{"name": "cv", "root": "{tree}", "ext": ".pdf,doc"}}'
    )
    assert result.metadata["total"] == 2


@pytest.mark.asyncio
async def test_subpath_filter_narrows_catalog(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    tree = _cv_tree(tmp_path)
    result = await dispatch(
        Intent.FIND_PATH,
        f'{{"name": "cv", "root": "{tree}", "subpath": "Documents"}}',
    )
    assert result.metadata["total"] == 3
    assert all("Documents" in p for p in result.metadata["paths"])
    assert result.metadata["groups"] == {"Documents": 3}


@pytest.mark.asyncio
async def test_kind_filter_files_vs_dirs(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    d = tmp_path / "cv_folder"
    d.mkdir()
    (tmp_path / "cv.txt").write_text("x")
    result = await dispatch(
        Intent.FIND_PATH, f'{{"name": "cv", "root": "{tmp_path}", "kind": "dir"}}'
    )
    assert result.metadata["total"] == 1
    assert result.metadata["paths"][0].endswith("cv_folder")


@pytest.mark.asyncio
async def test_exact_match_filters(tmp_path, monkeypatch):
    """exact compares the full basename, not a substring."""
    _allow(monkeypatch, tmp_path)
    (tmp_path / "cv.txt").write_text("x")
    (tmp_path / "my-cv.txt").write_text("x")
    (tmp_path / "cv.pdf").write_text("x")
    result = await dispatch(
        Intent.FIND_PATH, f'{{"name": "cv.txt", "root": "{tmp_path}", "exact": true}}'
    )
    assert result.metadata["total"] == 1
    assert result.metadata["paths"][0].endswith("cv.txt")
    # Without exact, the substring "cv.txt" also matches my-cv.txt
    loose = await dispatch(
        Intent.FIND_PATH, f'{{"name": "cv.txt", "root": "{tmp_path}"}}'
    )
    assert loose.metadata["total"] == 2


@pytest.mark.asyncio
async def test_all_paths_returns_full_catalog_in_metadata(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    tree = _cv_tree(tmp_path)
    result = await dispatch(
        Intent.FIND_PATH,
        f'{{"name": "cv", "root": "{tree}", "max_results": 1, "all_paths": true}}',
    )
    assert result.metadata["page_size"] == 1  # display page stays small
    assert len(result.metadata["paths"]) == 4  # full catalog for the picker


@pytest.mark.asyncio
async def test_cached_walk_not_rewalked(tmp_path, monkeypatch):
    """Enumerate once, filter many — identical + filtered calls reuse the walk."""
    import tools.find_path as fp_mod

    _allow(monkeypatch, tmp_path)
    tree = _cv_tree(tmp_path)
    calls = []
    real = fp_mod._walk_catalog

    def _spy(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(fp_mod, "_walk_catalog", _spy)
    base = f'{{"name": "cv", "root": "{tree}"}}'
    await dispatch(Intent.FIND_PATH, base)
    await dispatch(Intent.FIND_PATH, base)  # identical follow-up → cache hit
    await dispatch(Intent.FIND_PATH, f'{{"name": "cv", "root": "{tree}", "ext": "pdf"}}')
    assert len(calls) == 1
