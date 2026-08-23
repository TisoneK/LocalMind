"""B-2026-08-23-17 follow-up: the agent's default write scratch lands in the
session workspace when a session is bound (contextvar), while explicit user
paths stay exactly where the user asked.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.config import settings
from core.session_workspace import (
    current_session_id,
    reset_current_session,
    set_current_session,
    workspace_path,
    workspace_tmp_dir,
)
from tools.file_writer import resolve_write_path, write_file


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Point the LocalMind home AND Path.home at tmp so no real dirs are touched."""
    monkeypatch.setattr(settings, "localmind_home", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


@pytest.fixture
def bound_session():
    token = set_current_session("sess-write-1")
    yield "sess-write-1"
    reset_current_session(token)


def test_contextvar_default_is_none():
    assert current_session_id() is None


class TestResolveDefaultScratch:
    def test_with_session_lands_in_workspace(self, home, bound_session):
        p = resolve_write_path("", "notes.txt")
        # B-2026-08-23-25: default scratch now lands in .tmp/
        assert p == workspace_tmp_dir("sess-write-1") / "notes.txt"
        assert p.is_absolute()

    def test_without_session_keeps_legacy_home_scratch(self, home):
        p = resolve_write_path("", "notes.txt")
        assert p == home / "notes.txt"


class TestExplicitBareFilenames:
    """B-2026-08-23-17 follow-up: the agent's EXPLICIT bare-filename writes
    (not just the internal scratch copy) default into the session workspace —
    including the model's legacy habits (dot-prefixed ./name and the old
    ~/LocalMind scratch name). User-named directories still escape.
    """

    WS = staticmethod(lambda: workspace_path("sess-write-1"))

    @pytest.mark.parametrize(
        "path",
        ["notes.txt", "./notes.txt", "LocalMind/notes.txt", "~/LocalMind/notes.txt"],
    )
    def test_bare_filename_redirects_to_workspace(self, home, bound_session, path):
        p = resolve_write_path(path, fallback_filename="notes.txt")
        # B-2026-08-23-25: default scratch now lands in .tmp/
        assert p == workspace_tmp_dir("sess-write-1") / "notes.txt", path

    @pytest.mark.parametrize(
        "path",
        ["sub/notes.txt", "Documents/notes.txt", "~/Desktop/notes.txt"],
    )
    def test_user_named_directory_keeps_destination(self, home, bound_session, path):
        p = resolve_write_path(path, fallback_filename="notes.txt")
        # Never lands in the session workspace — the user named a directory.
        assert workspace_path("sess-write-1") not in p.parents, path
        assert p.name == "notes.txt"

    @pytest.mark.parametrize(
        "path",
        ["notes.txt", "./notes.txt", "LocalMind/notes.txt", "~/LocalMind/notes.txt"],
    )
    def test_without_session_keeps_legacy_behavior(self, home, path):
        p = resolve_write_path(path, fallback_filename="notes.txt")
        assert workspace_path("sess-write-1") not in p.parents, path


class TestWriteFileScratch:
    @pytest.mark.asyncio
    async def test_default_write_lands_in_workspace(self, home, bound_session):
        result = await write_file("notes.txt:\n\nhello artifact")
        dest = Path(result.metadata["path"])
        # The visible write is the workspace .tmp copy.
        assert dest == workspace_tmp_dir("sess-write-1") / "notes.txt"
        assert dest.exists()
        assert dest.read_text() == "hello artifact"

    @pytest.mark.asyncio
    async def test_explicit_user_path_unchanged_scratch_in_workspace(self, home, bound_session):
        # A relative dir path is an explicit user destination (step 5 of
        # resolve_write_path) — it must land at Path.home()/project, NOT the
        # workspace, while the scratch copy still lives in the workspace.
        result = await write_file("project/notes.txt:\n\nhello")
        dest = Path(result.metadata["path"])
        assert dest == home / "project" / "notes.txt"
        assert dest.exists()
        # The session workspace .tmp still holds the artifact copy.
        assert (workspace_tmp_dir("sess-write-1") / "notes.txt").exists()

    @pytest.mark.asyncio
    async def test_no_session_uses_legacy_scratch(self, home):
        result = await write_file("notes.txt:\n\nhello")
        dest = Path(result.metadata["path"])
        assert dest == home / "notes.txt"
        assert dest.exists()


class TestFileWriteContractScratch:
    """The FileWriteContract (loop's typed write path) must use the same
    session-workspace default scratch — the live run exposed it computing
    `home / filename` directly, leaving a stray file in the LocalMind root
    even though the final dest correctly landed in the workspace.
    """

    @pytest.mark.asyncio
    async def test_scratch_only_write_lands_in_workspace(self, home, bound_session):
        from tools.contracts.schemas import FileWriteContract

        result = await FileWriteContract().execute(
            {"path": "notes.txt", "content": "contract artifact"}
        )
        dest = Path(result.metadata["path"])
        # B-2026-08-23-25: default scratch now lands in .tmp/
        assert dest == workspace_tmp_dir("sess-write-1") / "notes.txt"
        assert dest.exists()
        assert dest.read_text() == "contract artifact"
        # No stray copy at the legacy LocalMind root.
        assert not (home / "notes.txt").exists()

    @pytest.mark.asyncio
    async def test_scratch_only_no_session_keeps_legacy(self, home):
        from tools.contracts.schemas import FileWriteContract

        result = await FileWriteContract().execute(
            {"path": "notes.txt", "content": "contract artifact"}
        )
        dest = Path(result.metadata["path"])
        assert dest == home / "notes.txt"
        assert dest.exists()
