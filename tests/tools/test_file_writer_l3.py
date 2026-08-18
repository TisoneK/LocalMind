"""ADR-43 L3 — file_write returns an affirmative, self-contained confirmation.

The terse "name - parent/" echo read like an unconfirmed path and invited a
redundant post-write read-back (file_task) to verify — a wasted call that also
hit the S264 path bug and cascaded to empty_response. The write is already done
and verified in the tool; its result must SAY so, so the model doesn't re-check.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.file_writer import _do_write


@pytest.mark.asyncio
async def test_write_result_is_an_affirmative_confirmation(tmp_path: Path):
    dest = tmp_path / "note.txt"
    result = await _do_write(dest, "hello from adr43")

    assert result.success is not False
    # Affirmative, self-contained: byte count, full path, and an explicit
    # "don't read it back" so the model spends no verify call.
    assert "16 bytes" in result.content
    assert str(dest) in result.content
    assert "read it back" in result.content.lower()
    # Structured metadata is unchanged (consumers rely on it, not the prose).
    assert result.metadata["bytes"] == 16
    assert result.metadata["path"] == str(dest)


@pytest.mark.asyncio
async def test_write_result_pluralizes_lines(tmp_path: Path):
    one = await _do_write(tmp_path / "a.txt", "single")
    assert "(1 line)" in one.content
    many = await _do_write(tmp_path / "b.txt", "l1\nl2\nl3")
    assert "(3 lines)" in many.content


# ── S293 / B-2026-08-17-6: native absolute paths honored verbatim ────────────

from tools.file_writer import resolve_write_path


def test_absolute_path_is_honored_verbatim():
    # A genuine absolute path must NOT be re-anchored to HOME (the bug prepended
    # /Users/<me> to /private/tmp/... so the write landed in the wrong place and
    # the loop's read-back verification then failed against the original path).
    assert resolve_write_path("/private/tmp/x/foo.txt") == Path("/private/tmp/x/foo.txt")
    assert resolve_write_path("/var/data/bar.py") == Path("/var/data/bar.py")


def test_relative_and_named_folder_paths_unchanged():
    # Regression guard: non-absolute paths keep their home-anchored behavior.
    home = Path.home()
    assert resolve_write_path("Code/hello.py") == home / "Code" / "hello.py"
    assert resolve_write_path("Documents/note.txt") == home / "Documents" / "note.txt"
