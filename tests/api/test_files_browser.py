"""The Files-tab browser endpoints.

GET    /api/files/search  — recursive name search under a root, capped at 200
DELETE /api/files         — delete a file or EMPTY folder the user chose
GET    /api/files/download — stream raw bytes as an attachment

All three are gated by the same allowed-folder check as listing, and must
never resolve outside the allowed root (path traversal rejected).
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

import core.config as config_module
from api.routes.filesystem import delete_file, download_file, search_files


def _run(coro):
    return asyncio.run(coro)


def _allow(tmp_path):
    """Scoped helper: allow the tmp dir so the endpoints pass their gate."""
    patcher = patch.object(config_module, "_allowed_user_folders", return_value=[str(tmp_path)])
    patcher.start()
    return patcher


class TestSearchFiles:
    def test_recursive_name_search_case_insensitive(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "Report Q3.md").write_text("x", encoding="utf-8")
        (tmp_path / "notes.txt").write_text("y", encoding="utf-8")
        (tmp_path / "unrelated.log").write_text("z", encoding="utf-8")

        patcher = _allow(tmp_path)
        try:
            result = _run(search_files(str(tmp_path), "report"))
        finally:
            patcher.stop()

        names = [r["name"] for r in result["results"]]
        assert "Report Q3.md" in names
        assert "notes.txt" not in names

    def test_empty_query_returns_no_results(self, tmp_path):
        (tmp_path / "anything.py").write_text("x", encoding="utf-8")
        patcher = _allow(tmp_path)
        try:
            result = _run(search_files(str(tmp_path), ""))
        finally:
            patcher.stop()
        assert result["results"] == []

    def test_matches_are_capped_at_200(self, tmp_path):
        for i in range(250):
            (tmp_path / f"hit_{i}.txt").write_text("x", encoding="utf-8")
        patcher = _allow(tmp_path)
        try:
            result = _run(search_files(str(tmp_path), "hit_"))
        finally:
            patcher.stop()
        assert len(result["results"]) == 200


class TestDeleteFile:
    def test_delete_regular_file(self, tmp_path):
        f = tmp_path / "trash.txt"
        f.write_text("bye", encoding="utf-8")
        patcher = _allow(tmp_path)
        try:
            result = _run(delete_file(str(f)))
        finally:
            patcher.stop()
        assert not f.exists()
        assert result["deleted"] == str(f)

    def test_delete_empty_folder(self, tmp_path):
        d = tmp_path / "empty_dir"
        d.mkdir()
        patcher = _allow(tmp_path)
        try:
            _run(delete_file(str(d)))
        finally:
            patcher.stop()
        assert not d.exists()

    def test_non_empty_folder_rejected(self, tmp_path):
        d = tmp_path / "full_dir"
        d.mkdir()
        (d / "inside.txt").write_text("x", encoding="utf-8")
        patcher = _allow(tmp_path)
        try:
            with pytest.raises(Exception) as exc:
                _run(delete_file(str(d)))
            assert "not empty" in str(exc.value).lower()
        finally:
            patcher.stop()
        assert d.exists()

    def test_missing_path_rejected(self, tmp_path):
        patcher = _allow(tmp_path)
        try:
            with pytest.raises(Exception) as exc:
                _run(delete_file(str(tmp_path / "nope.txt")))
            assert "not found" in str(exc.value).lower()
        finally:
            patcher.stop()

    def test_traversal_outside_allowed_root_rejected(self, tmp_path):
        # The gate is absolute-path based: a resolved path escaping the
        # allowed folder must be refused regardless of how it was spelled.
        outside = tmp_path.parent / "outside.txt"
        outside.write_text("x", encoding="utf-8")
        patcher = _allow(tmp_path)
        try:
            with pytest.raises(Exception) as exc:
                _run(delete_file(str(outside)))
            assert "outside allowed folders" in str(exc.value).lower()
        finally:
            patcher.stop()
        assert outside.exists()


class TestDownloadFile:
    def test_streams_raw_bytes(self, tmp_path):
        from fastapi.responses import FileResponse

        f = tmp_path / "data.bin"
        f.write_bytes(b"\x00\x01\x02hello")
        patcher = _allow(tmp_path)
        try:
            response = _run(download_file(str(f)))
        finally:
            patcher.stop()
        assert isinstance(response, FileResponse)
        assert response.filename == "data.bin"
        # The actual bytes are streamed by Starlette; verify the headers only
        # here (endpoint returns the FileResponse pointing at the right file).
        assert response.media_type == "application/octet-stream"

    def test_directory_rejected(self, tmp_path):
        patcher = _allow(tmp_path)
        try:
            with pytest.raises(Exception) as exc:
                _run(download_file(str(tmp_path)))
            assert "not found" in str(exc.value).lower()
        finally:
            patcher.stop()


class TestRecentFiles:
    def test_returns_newest_files_with_metadata(self, tmp_path):
        from api.routes.filesystem import recent_files

        (tmp_path / "docs").mkdir()
        older = tmp_path / "docs" / "old.md"
        older.write_text("x", encoding="utf-8")
        newer = tmp_path / "fresh.txt"
        newer.write_text("y", encoding="utf-8")
        # Make the mtimes deterministic: fresh.txt strictly newer.
        newer_stat = newer.stat()
        import os

        os.utime(older, (newer_stat.st_atime, newer_stat.st_mtime - 1000))

        patcher = _allow(tmp_path)
        try:
            result = _run(recent_files(str(tmp_path), 10))
        finally:
            patcher.stop()

        assert len(result["files"]) == 2
        first = result["files"][0]
        assert first["name"] == "fresh.txt"
        assert first["type"] == "file"
        assert first["path"] == str(newer)
        assert first["relPath"] == "fresh.txt"
        assert first["size"] == 1
        assert "modified" in first
        # Newest first.
        assert result["files"][1]["name"] == "old.md"

    def test_limit_respected(self, tmp_path):
        from api.routes.filesystem import recent_files

        for i in range(5):
            (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")
        patcher = _allow(tmp_path)
        try:
            result = _run(recent_files(str(tmp_path), 2))
        finally:
            patcher.stop()
        assert len(result["files"]) == 2

    def test_skips_hidden_directories(self, tmp_path):
        from api.routes.filesystem import recent_files

        (tmp_path / ".git").mkdir()
        (tmp_path / "visible.txt").write_text("x", encoding="utf-8")
        hidden = tmp_path / ".git" / "config"
        hidden.write_text("hidden", encoding="utf-8")
        # Make the hidden file look newest.
        import os

        visible_stat = (tmp_path / "visible.txt").stat()
        os.utime(hidden, (visible_stat.st_atime, visible_stat.st_mtime + 1000))

        patcher = _allow(tmp_path)
        try:
            result = _run(recent_files(str(tmp_path), 10))
        finally:
            patcher.stop()
        names = [f["name"] for f in result["files"]]
        assert "visible.txt" in names
        assert "config" not in names

    def test_outside_allowed_root_rejected(self, tmp_path):
        from api.routes.filesystem import recent_files

        outside = tmp_path.parent / "recent_outside"
        outside.mkdir()
        patcher = _allow(tmp_path)
        try:
            with pytest.raises(Exception) as exc:
                _run(recent_files(str(outside), 10))
            assert "outside allowed folders" in str(exc.value).lower()
        finally:
            patcher.stop()
