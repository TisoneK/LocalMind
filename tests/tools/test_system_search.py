"""
Tests for the system_search tool (Session 400 — unified local search).

Design contract: ONE dispatch entry point (Intent.SYSTEM_SEARCH) with six
deterministic operations (files / recent / largest / duplicates / apps /
open_with). Roots are security-gated via settings.is_path_allowed (same
gate as find_path — monkeypatched the same way here), walks are bounded,
and every operation returns NORMALIZED metadata rows ({type, path, name,
size, modified, ...}) so the Parent agent presents without parsing prose.
The tool never raises: every failure degrades to ToolResult(success=False).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from core.models import Intent
from tools import available_tools, dispatch, input_is_optional


def _allow(monkeypatch, tmp_path):
    """Make tmp_path an allowed folder (tmp is normally outside ~).

    Same pattern as test_find_path: the security gate consults
    core.config._allowed_user_folders(), so we point it at the test tree —
    plus the real home, which stays searchable so default-root calls
    (bare call / plain string) resolve their root.
    """
    monkeypatch.setattr(
        "core.config._allowed_user_folders",
        lambda: [str(tmp_path), str(Path.home())],
    )


def _alpha_tree(tmp_path):
    """Files + folders matching 'alpha' plus non-matching noise."""
    (tmp_path / "alpha_report.txt").write_text("alpha")
    (tmp_path / "alpha_notes.md").write_text("alpha")
    (tmp_path / "beta_report.txt").write_text("beta")
    (tmp_path / "zzz_unrelated.txt").write_text("zzz")
    alpha_dir = tmp_path / "alpha_dir"
    alpha_dir.mkdir()
    (alpha_dir / "alpha_inner.pdf").write_text("alpha")
    return tmp_path


def _payload(**kwargs) -> str:
    """JSON-encode dispatch args (handles tmp-path escaping safely)."""
    return json.dumps(kwargs)


# ── Operation: files ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_files_operation_finds_files_and_dirs(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    root = _alpha_tree(tmp_path)
    result = await dispatch(
        Intent.SYSTEM_SEARCH, _payload(operation="files", query="alpha", root=str(root))
    )
    assert result is not None
    assert result.success is not False
    meta = result.metadata
    assert meta["operation"] == "files"
    assert meta["total"] == 4
    results = meta["results"]
    assert len(results) == 4  # non-empty page covering every match
    names = {r["name"] for r in results}
    assert names == {"alpha_report.txt", "alpha_notes.md", "alpha_dir", "alpha_inner.pdf"}
    for row in results:
        # Normalized rows — the Parent presents without parsing prose.
        assert {"type", "path", "name", "size", "modified"} <= set(row)
        assert row["type"] in ("file", "dir")
        assert row["path"].startswith(str(root))
    assert "alpha_report.txt" in result.content
    assert "alpha_inner.pdf" in result.content
    assert "beta_report.txt" not in result.content  # non-matching name
    assert "zzz_unrelated.txt" not in result.content


@pytest.mark.asyncio
async def test_files_operation_requires_query(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    result = await dispatch(
        Intent.SYSTEM_SEARCH, _payload(operation="files", root=str(tmp_path))
    )
    assert result is not None
    assert result.success is False
    assert result.error_type == "invalid_input"
    assert "query" in result.content


@pytest.mark.asyncio
async def test_files_operation_kind_dir_filter(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    root = _alpha_tree(tmp_path)
    result = await dispatch(
        Intent.SYSTEM_SEARCH,
        _payload(operation="files", query="alpha", root=str(root), kind="dir"),
    )
    assert result.success is not False
    assert result.metadata["total"] == 1  # only alpha_dir, not the files
    row = result.metadata["results"][0]
    assert row["name"] == "alpha_dir"
    assert row["type"] == "dir"
    assert row["path"].endswith("alpha_dir")


@pytest.mark.asyncio
async def test_files_operation_ext_filter(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    root = _alpha_tree(tmp_path)
    only_txt = await dispatch(
        Intent.SYSTEM_SEARCH,
        _payload(operation="files", query="alpha", root=str(root), ext="txt"),
    )
    assert only_txt.success is not False
    assert only_txt.metadata["total"] == 1
    assert only_txt.metadata["results"][0]["name"] == "alpha_report.txt"
    assert only_txt.metadata["results"][0]["path"].endswith(".txt")

    # Comma-separated extension list narrows to md + pdf matches.
    md_or_pdf = await dispatch(
        Intent.SYSTEM_SEARCH,
        _payload(operation="files", query="alpha", root=str(root), ext="md,pdf"),
    )
    assert md_or_pdf.success is not False
    assert md_or_pdf.metadata["total"] == 2
    assert {r["name"] for r in md_or_pdf.metadata["results"]} == {
        "alpha_notes.md",
        "alpha_inner.pdf",
    }


@pytest.mark.asyncio
async def test_files_operation_offset_pagination(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    root = _alpha_tree(tmp_path)
    page1 = await dispatch(
        Intent.SYSTEM_SEARCH,
        _payload(operation="files", query="alpha", root=str(root), limit=2, offset=0),
    )
    assert page1.success is not False
    assert page1.metadata["total"] == 4
    assert page1.metadata["offset"] == 0
    assert len(page1.metadata["results"]) == 2
    assert page1.metadata["truncated"] is True

    page2 = await dispatch(
        Intent.SYSTEM_SEARCH,
        _payload(operation="files", query="alpha", root=str(root), limit=2, offset=2),
    )
    assert page2.success is not False
    assert page2.metadata["offset"] == 2
    assert page2.metadata["total"] == 4  # stable total across pages
    assert len(page2.metadata["results"]) == 2
    assert page2.metadata["truncated"] is False

    names1 = {r["name"] for r in page1.metadata["results"]}
    names2 = {r["name"] for r in page2.metadata["results"]}
    assert names1.isdisjoint(names2)  # pages never overlap
    assert names1 | names2 == {
        "alpha_report.txt",
        "alpha_notes.md",
        "alpha_dir",
        "alpha_inner.pdf",
    }


@pytest.mark.asyncio
async def test_files_operation_limit_clamped_to_hard_max(tmp_path, monkeypatch):
    """limit=100 must clamp to the hard cap (25) — the page is bounded by
    construction while `total` keeps the honest match count."""
    _allow(monkeypatch, tmp_path)
    for i in range(30):
        (tmp_path / f"clampmatch_{i:02d}.txt").write_text("x")
    result = await dispatch(
        Intent.SYSTEM_SEARCH,
        _payload(operation="files", query="clampmatch", root=str(tmp_path), limit=100),
    )
    assert result.success is not False
    assert result.metadata["total"] == 30
    assert len(result.metadata["results"]) == 25
    assert result.metadata["truncated"] is True


# ── Operation: recent ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recent_operation_window_and_mtime_order(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    now = time.time()
    (tmp_path / "old_file.txt").write_text("old")
    os.utime(tmp_path / "old_file.txt", (now - 10 * 86400, now - 10 * 86400))
    (tmp_path / "three_days_ago.txt").write_text("older")
    os.utime(tmp_path / "three_days_ago.txt", (now - 3 * 86400, now - 3 * 86400))
    (tmp_path / "two_hours_ago.txt").write_text("new")
    os.utime(tmp_path / "two_hours_ago.txt", (now - 7200, now - 7200))
    (tmp_path / "thirty_min_ago.txt").write_text("newer")
    os.utime(tmp_path / "thirty_min_ago.txt", (now - 1800, now - 1800))
    (tmp_path / "just_now.txt").write_text("newest")
    os.utime(tmp_path / "just_now.txt", (now - 5, now - 5))

    result = await dispatch(
        Intent.SYSTEM_SEARCH,
        _payload(operation="recent", root=str(tmp_path), days=1),
    )
    assert result.success is not False
    meta = result.metadata
    assert meta["operation"] == "recent"
    assert meta["days"] == 1
    assert meta["total"] == 3  # only the three in-window files
    rows = meta["results"]
    names = [r["name"] for r in rows]
    assert set(names) == {"two_hours_ago.txt", "thirty_min_ago.txt", "just_now.txt"}
    assert "old_file.txt" not in names  # 10 days old → outside the window
    assert "three_days_ago.txt" not in names  # 3 days old → outside the window
    # mtime-descending order — newest first.
    mtimes = [r["modified"] for r in rows]
    assert mtimes == sorted(mtimes, reverse=True)
    assert rows[0]["name"] == "just_now.txt"
    for row in rows:
        assert {"type", "path", "name", "size", "modified"} <= set(row)
        assert row["type"] == "file"


# ── Operation: largest ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_largest_operation_size_descending(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    (tmp_path / "tiny.txt").write_bytes(b"x" * 10)
    (tmp_path / "small.bin").write_bytes(b"x" * 1_000)
    (tmp_path / "medium.bin").write_bytes(b"x" * 10_000)
    (tmp_path / "big.bin").write_bytes(b"x" * 100_000)
    (tmp_path / "empty.bin").write_bytes(b"")  # zero-size → never ranked

    result = await dispatch(
        Intent.SYSTEM_SEARCH, _payload(operation="largest", root=str(tmp_path))
    )
    assert result.success is not False
    meta = result.metadata
    assert meta["operation"] == "largest"
    rows = meta["results"]
    assert len(rows) == 4  # empty.bin excluded (size <= 0)
    names = [r["name"] for r in rows]
    assert "empty.bin" not in names
    sizes = [r["size"] for r in rows]
    assert sizes == sorted(sizes, reverse=True)  # size-descending order
    assert rows[0]["name"] == "big.bin"  # the largest is first
    assert rows[0]["size"] == 100_000
    for row in rows:
        assert {"type", "path", "name", "size"} <= set(row)


# ── Operation: duplicates ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_duplicates_operation_groups_same_name_and_size(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    copy_a = tmp_path / "copyA"
    copy_a.mkdir()
    copy_b = tmp_path / "copyB"
    copy_b.mkdir()
    copy_c = tmp_path / "copyC"
    copy_c.mkdir()
    (copy_a / "report.pdf").write_bytes(b"a" * 100)
    (copy_b / "report.pdf").write_bytes(b"b" * 100)
    (copy_c / "report.pdf").write_bytes(b"c" * 999)  # same name, DIFFERENT size
    (tmp_path / "unique.txt").write_bytes(b"u" * 42)

    result = await dispatch(
        Intent.SYSTEM_SEARCH, _payload(operation="duplicates", root=str(tmp_path))
    )
    assert result.success is not False
    meta = result.metadata
    assert meta["operation"] == "duplicates"
    assert meta["groups"] == 1  # exactly one duplicate group
    assert meta["wasted_bytes"] == 100  # 100 bytes x (2 copies - 1)
    group = meta["results"][0]
    assert group["type"] == "duplicate_group"
    assert group["name"] == "report.pdf"
    assert group["size"] == 100
    assert group["copies"] == 2
    assert group["wasted_bytes"] == 100
    assert set(group["paths"]) == {
        str(copy_a / "report.pdf"),
        str(copy_b / "report.pdf"),
    }  # the different-size copy in copyC is NOT part of the group
    assert "report.pdf" in result.content


@pytest.mark.asyncio
async def test_duplicates_same_name_different_size_not_grouped(tmp_path, monkeypatch):
    """Same name but different size is NOT a duplicate signal."""
    _allow(monkeypatch, tmp_path)
    dir_x = tmp_path / "dirX"
    dir_x.mkdir()
    dir_y = tmp_path / "dirY"
    dir_y.mkdir()
    (dir_x / "doc.txt").write_bytes(b"x" * 10)
    (dir_y / "doc.txt").write_bytes(b"y" * 20)

    result = await dispatch(
        Intent.SYSTEM_SEARCH, _payload(operation="duplicates", root=str(tmp_path))
    )
    assert result.success is not False
    assert result.metadata["groups"] == 0
    assert result.metadata["results"] == []
    assert result.metadata["wasted_bytes"] == 0
    assert "No duplicate" in result.content


# ── Operation: apps ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apps_operation_with_query_structure(tmp_path, monkeypatch):
    """Program lists are platform-dependent — assert structure, not names."""
    _allow(monkeypatch, tmp_path)
    result = await dispatch(
        Intent.SYSTEM_SEARCH, _payload(operation="apps", query="python")
    )
    assert result is not None
    assert result.success is not False  # no matches on a platform ≠ failure
    meta = result.metadata
    assert meta["operation"] == "apps"
    assert isinstance(meta["results"], list)
    for row in meta["results"]:
        assert "name" in row
        assert row["type"] == "app"


@pytest.mark.asyncio
async def test_apps_operation_empty_query_structure(tmp_path, monkeypatch):
    """Bare apps listing: succeeds even when the platform has no programs."""
    _allow(monkeypatch, tmp_path)
    result = await dispatch(Intent.SYSTEM_SEARCH, _payload(operation="apps"))
    assert result is not None
    assert result.success is not False
    meta = result.metadata
    assert meta["operation"] == "apps"
    assert isinstance(meta.get("total_programs"), int)
    assert isinstance(meta["results"], list)
    for row in meta["results"]:
        assert "name" in row


# ── Operation: open_with ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_with_operation_ext(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    result = await dispatch(
        Intent.SYSTEM_SEARCH, _payload(operation="open_with", ext="pdf")
    )
    assert result is not None
    assert result.success is not False
    assert "pdf" in result.content.lower()
    meta = result.metadata
    assert meta["operation"] == "open_with"
    assert meta["ext"] == "pdf"
    assert isinstance(meta["results"], list)


@pytest.mark.asyncio
async def test_open_with_operation_missing_target(tmp_path, monkeypatch):
    """No path, no ext, no query → clear invalid_input error."""
    _allow(monkeypatch, tmp_path)
    result = await dispatch(Intent.SYSTEM_SEARCH, _payload(operation="open_with"))
    assert result is not None
    assert result.success is False
    assert result.error_type == "invalid_input"
    assert "requires" in result.content


# ── Dispatch-level behaviors ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bare_call_defaults_to_recent(tmp_path, monkeypatch):
    """input_optional=True: an empty payload is a meaningful call → recent."""
    _allow(monkeypatch, tmp_path)  # home stays allowed → default root resolves
    result = await dispatch(Intent.SYSTEM_SEARCH, "")
    assert result is not None
    assert result.success is not False
    assert result.metadata["operation"] == "recent"
    assert result.metadata["days"] == 7  # default recency window


@pytest.mark.asyncio
async def test_unknown_operation_lists_valid_operations(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    result = await dispatch(
        Intent.SYSTEM_SEARCH, _payload(operation="warp_drive")
    )
    assert result is not None
    assert result.success is False
    assert result.error_type == "invalid_input"
    assert "Valid operations" in result.content
    for op in ("files", "recent", "largest", "duplicates", "apps", "open_with"):
        assert op in result.content


@pytest.mark.asyncio
async def test_plain_string_treated_as_files_query(tmp_path, monkeypatch):
    """A non-JSON string is a name query for the files operation."""
    _allow(monkeypatch, tmp_path)
    result = await dispatch(Intent.SYSTEM_SEARCH, "zzz_plain_query_token")
    assert result is not None
    assert result.success is not False
    assert result.metadata["operation"] == "files"
    # The plain string became the name query (echoed in the summary line).
    assert "zzz_plain_query_token" in result.content


@pytest.mark.asyncio
async def test_malformed_json_rejected(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    result = await dispatch(
        Intent.SYSTEM_SEARCH, '{"operation": "files", "query": "unterminated'
    )
    assert result is not None
    assert result.success is False
    assert result.error_type == "invalid_input"
    assert "parse" in result.content.lower()


# ── Security: roots are gated by settings.is_path_allowed ──────────────────


@pytest.mark.asyncio
async def test_root_outside_allowed_folders_denied(tmp_path, monkeypatch):
    """Security: searching outside allowed folders is denied (find_path pattern)."""
    # Allow only a DIFFERENT directory than the search root.
    monkeypatch.setattr(
        "core.config._allowed_user_folders",
        lambda: [str(tmp_path / "only_this")],
    )
    tree = _alpha_tree(tmp_path)
    result = await dispatch(
        Intent.SYSTEM_SEARCH,
        _payload(operation="files", query="alpha", root=str(tree)),
    )
    assert result is not None
    assert result.success is False
    assert result.error_type == "permission_denied"
    assert "Access denied" in result.content

    # The stat operations (recent) gate roots through the same helper.
    recent = await dispatch(
        Intent.SYSTEM_SEARCH, _payload(operation="recent", root=str(tree), days=1)
    )
    assert recent.success is False
    assert recent.error_type == "permission_denied"


@pytest.mark.skipif(not Path("/etc").is_dir(), reason="/etc does not exist on this platform")
@pytest.mark.asyncio
async def test_system_path_root_denied(tmp_path, monkeypatch):
    """/etc exists but is never an allowed search root."""
    monkeypatch.setattr(
        "core.config._allowed_user_folders",
        lambda: [str(tmp_path)],
    )
    result = await dispatch(
        Intent.SYSTEM_SEARCH,
        _payload(operation="files", query="passwd", root="/etc"),
    )
    assert result is not None
    assert result.success is False
    assert result.error_type == "permission_denied"
    assert "Access denied" in result.content


# ── Root resolution errors ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_root_does_not_exist(tmp_path, monkeypatch):
    _allow(monkeypatch, tmp_path)
    missing = str(tmp_path / "no_such_root_xyz")
    result = await dispatch(
        Intent.SYSTEM_SEARCH,
        _payload(operation="files", query="anything", root=missing),
    )
    assert result is not None
    assert result.success is False
    assert result.error_type == "not_found"
    assert "does not exist" in result.content


# ── Registration ────────────────────────────────────────────────────────────


def test_system_search_registered_and_input_optional():
    """The tool self-registers and declares empty input as meaningful."""
    names = {t["intent"] for t in available_tools()}
    assert "system_search" in names
    assert input_is_optional(Intent.SYSTEM_SEARCH) is True


# ── Session 400 live-trace regression: weak-model noun-phrase queries ──────


@pytest.mark.asyncio
async def test_files_token_relaxation_on_noun_phrase(monkeypatch, tmp_path):
    """zai/glm-4.5-flash sent the plain string 'LocalMind project' — multi-
    token AND matched 0 (no file is named that). The tool must fall back to
    the longest token and SAY SO, not silently return nothing."""
    from core.config import settings as cfg

    tree = tmp_path / "home"
    (tree / "LocalMind").mkdir(parents=True)
    (tree / "LocalMind" / "README.md").write_text("x")
    monkeypatch.setattr(cfg, "localmind_home", str(tmp_path))
    monkeypatch.setattr(
        "core.config._allowed_user_folders", lambda: [str(tree)]
    )
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tree))

    from tools import dispatch
    from core.models import Intent

    r = await dispatch(Intent.SYSTEM_SEARCH, "LocalMind project")
    assert r.success
    assert "LocalMind" in r.content
    assert "showing matches for" in r.content  # honest about the relaxation
    assert r.metadata["total"] >= 1
    assert any("LocalMind" in p["path"] for p in r.metadata["results"])


@pytest.mark.asyncio
async def test_files_no_relaxation_when_exact_matches_exist(monkeypatch, tmp_path):
    """When the strict multi-token AND query matches, no relaxation note."""
    from core.config import settings as cfg

    tree = tmp_path / "home"
    (tree / "docs").mkdir(parents=True)
    (tree / "docs" / "project plan.md").write_text("x")
    monkeypatch.setattr(cfg, "localmind_home", str(tmp_path))
    monkeypatch.setattr(
        "core.config._allowed_user_folders", lambda: [str(tree)]
    )
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tree))

    from tools import dispatch
    from core.models import Intent

    r = await dispatch(
        Intent.SYSTEM_SEARCH, '{"operation": "files", "query": "project plan"}'
    )
    assert r.success
    assert "showing matches for" not in r.content
    assert r.metadata["total"] == 1
