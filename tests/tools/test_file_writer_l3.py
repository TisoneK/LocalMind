"""file_write returns a FACTUAL result (byte/line count + path) and NOTHING that
tells the agent whether to verify its own work.

B-2026-08-18-7: the old "saved and verified. Do not read it back to check; the
write is confirmed." wording was a phantom self-verification instruction the
tool has no business issuing. The result must state only the facts of the write;
the agent decides for itself whether to read the file back.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.file_writer import _do_write


@pytest.mark.asyncio
async def test_write_result_is_factual_without_a_verify_instruction(tmp_path: Path):
    dest = tmp_path / "note.txt"
    result = await _do_write(dest, "hello from adr43")

    assert result.success is not False
    # Factual: byte count + full path.
    assert "16 bytes" in result.content
    assert str(dest) in result.content
    # NO phantom self-verification instruction of any kind.
    low = result.content.lower()
    for phantom in ("read it back", "write is confirmed", "saved and verified", "do not read"):
        assert phantom not in low, f"phantom instruction leaked: {result.content!r}"
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
