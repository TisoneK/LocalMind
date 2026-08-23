"""B-2026-08-23-17: per-session workspace folders.

Each session owns <localmind_home>/sessions/<sanitized_id>/ — created on first
session touch, deleted with the session, and never able to escape the workspace
root even with a hostile session id.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core.session_workspace import (
    delete_workspace,
    ensure_workspace,
    sanitize_session_id,
    workspace_path,
    workspace_root,
    workspace_uploads_dir,
)


class TestSanitizeSessionId:
    def test_plain_ids_pass_through(self):
        assert sanitize_session_id("abc-123_def.ghi") == "abc-123_def.ghi"

    def test_path_traversal_neutralized(self):
        assert "/" not in sanitize_session_id("../../etc/passwd")
        assert ".." not in sanitize_session_id("../..")
        assert "\\" not in sanitize_session_id("..\\..\\evil")

    def test_drive_prefix_neutralized(self):
        out = sanitize_session_id("C:\\Windows\\evil")
        assert out != "C:\\Windows\\evil"
        assert Path(out).is_absolute() is False

    def test_null_bytes_and_empty(self):
        assert sanitize_session_id("a\x00b") == sanitize_session_id("a_b")
        assert sanitize_session_id("")  # falls back to a hash, never empty

    def test_deterministic_for_same_input(self):
        assert sanitize_session_id("live-test-1") == sanitize_session_id("live-test-1")


class TestWorkspaceLifecycle:
    def test_paths_live_under_home_sessions(self, tmp_path):
        with patch("core.session_workspace.settings") as _s:
            _s.localmind_home = str(tmp_path)
            p = workspace_path("sess-1")
            assert p == tmp_path / "sessions" / "sess-1"
            assert workspace_uploads_dir("sess-1") == p / "uploads"
            assert workspace_root() == tmp_path / "sessions"

    def test_ensure_creates_dir(self, tmp_path):
        with patch("core.session_workspace.settings") as _s:
            _s.localmind_home = str(tmp_path)
            path = ensure_workspace("sess-1")
            assert path.is_dir()

    def test_delete_removes_folder_recursively(self, tmp_path):
        with patch("core.session_workspace.settings") as _s:
            _s.localmind_home = str(tmp_path)
            ensure_workspace("sess-1")
            up = workspace_path("sess-1") / "uploads"
            up.mkdir(parents=True, exist_ok=True)
            (up / "file.txt").write_text("hi")
            assert delete_workspace("sess-1") is True
            assert not workspace_path("sess-1").exists()

    def test_delete_missing_returns_false(self, tmp_path):
        with patch("core.session_workspace.settings") as _s:
            _s.localmind_home = str(tmp_path)
            assert delete_workspace("never-created") is False

    def test_delete_never_escapes_root(self, tmp_path):
        with patch("core.session_workspace.settings") as _s:
            _s.localmind_home = str(tmp_path)
            # A file OUTSIDE the workspace root must survive a hostile id.
            victim = tmp_path / "important.txt"
            victim.write_text("keep me")
            assert delete_workspace("../important.txt") is False
            assert victim.exists()

    def test_uploads_dir_inside_workspace(self, tmp_path):
        with patch("core.session_workspace.settings") as _s:
            _s.localmind_home = str(tmp_path)
            up = workspace_uploads_dir("sess-2")
            assert str(up).startswith(str(tmp_path / "sessions"))
