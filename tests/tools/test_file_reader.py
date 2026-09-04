"""Tests for the file reader tool."""
import pathlib

import pytest

from tools.file_reader import _chunk_text, _extract_path_candidates, parse_file


# ── Path extraction: read-back must survive Windows backslash paths (S264) ────
# The disease: file_task's extractor used a forward-slash-only char class, so a
# Windows absolute path the writer had just produced (C:\Users\tison\Desktop\x.md)
# was truncated to the bare filename, looked up under ~/ and cwd, and reported
# not_found — even though the file existed on the Desktop.
def test_extract_windows_absolute_path_kept_whole():
    got = _extract_path_candidates(r"C:\Users\tison\Desktop\Nice_Dinner_Recipe.md")
    # The FULL path must be the first candidate (file_task returns on the first
    # one that exists), not the truncated bare filename.
    assert got[0] == r"C:\Users\tison\Desktop\Nice_Dinner_Recipe.md"


def test_extract_windows_path_with_spaces():
    got = _extract_path_candidates(r"C:\Users\tison\My Documents\notes.md")
    assert got[0] == r"C:\Users\tison\My Documents\notes.md"


def test_extract_windows_forward_slash_path():
    got = _extract_path_candidates("C:/Users/tison/Desktop/file.md")
    assert got[0] == "C:/Users/tison/Desktop/file.md"


def test_extract_unix_absolute_path_still_works():
    got = _extract_path_candidates("/Users/bao/Desktop/Chicken_Teriyaki_Recipe.md")
    assert got[0] == "/Users/bao/Desktop/Chicken_Teriyaki_Recipe.md"


def test_extract_windows_path_inside_prose():
    got = _extract_path_candidates(r"read C:\Users\tison\Desktop\file.md please")
    assert r"C:\Users\tison\Desktop\file.md" in got


def test_extract_bare_filename_and_no_path():
    assert _extract_path_candidates("notes.txt") == ["notes.txt"]
    assert _extract_path_candidates("just prose, nothing to open here") == []


# ── Windows-RELATIVE backslash paths survive whole (S325) ─────────────────────
# The S264 fix covered drive-absolute paths; a WINDOWS-RELATIVE path
# (dev\test-run\notes.txt) still hit the forward-slash-only bare class and was
# truncated to the bare filename — so a file the writer just created read back
# as not_found (live trace on bankofai/deepseek-v4-flash: file_write reported
# "Wrote 19 bytes to C:\Users\tison\Dev\test-run\notes.txt" and the immediate
# read of the same relative path failed).
def test_extract_windows_relative_path_kept_whole():
    got = _extract_path_candidates(r"read dev\test-run\notes.txt")
    assert r"dev\test-run\notes.txt" in got


def test_extract_windows_relative_path_not_truncated_to_filename():
    got = _extract_path_candidates(r"dev\test-run\notes.txt")
    assert got == [r"dev\test-run\notes.txt"], (
        "the full Windows-relative path must be the candidate, not the truncated "
        f"bare filename — got {got!r}"
    )


def test_extract_windows_relative_prose_and_mixed_separators():
    got = _extract_path_candidates(r"please read dev\test-run\notes.txt back")
    assert r"dev\test-run\notes.txt" in got
    # Forward-slash relative paths keep working.
    assert _extract_path_candidates("read subdir/notes.txt")[0] == "subdir/notes.txt"


def test_chunk_text_basic():
    text = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
    chunks = _chunk_text(text, chunk_size=50, overlap=10)
    assert len(chunks) >= 1
    assert all(isinstance(c, str) for c in chunks)


def test_chunk_text_empty():
    assert _chunk_text("", chunk_size=100, overlap=20) == []


def test_chunk_text_single_paragraph():
    text = "Just one paragraph with some content here."
    chunks = _chunk_text(text, chunk_size=200, overlap=20)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_text_overlap():
    # With very small chunk size, we should get multiple chunks
    text = "\n\n".join([f"Paragraph {i} with some content." for i in range(10)])
    chunks = _chunk_text(text, chunk_size=30, overlap=10)
    assert len(chunks) > 1


@pytest.mark.asyncio
async def test_parse_file_txt_utf8():
    """Plain UTF-8 text is decoded and chunked correctly.

    Replaces the old test_extract_plain_utf8 which tested a private
    _extract_plain helper that was removed when plain-text decoding
    was inlined into parse_file (see lines 194-209 of file_reader.py).
    """
    data = b"Hello, world!"
    attachment = await parse_file(
        data=data,
        filename="test.txt",
        content_type="text/plain",
        chunk_size=100,
    )
    assert attachment.filename == "test.txt"
    assert attachment.size_bytes == len(data)
    assert len(attachment.chunks) >= 1
    assert "Hello, world!" in " ".join(attachment.chunks)


@pytest.mark.asyncio
async def test_parse_file_txt_latin1_fallback():
    """Non-UTF-8 bytes are handled gracefully via errors='replace'.

    Replaces the old test_extract_plain_latin1_fallback. The new decoder
    uses errors='replace' so invalid bytes become U+FFFD rather than
    raising. We verify the file still produces readable output.
    """
    data = b"Caf\xe9"  # latin-1 encoded
    attachment = await parse_file(
        data=data,
        filename="test.txt",
        content_type="text/plain",
        chunk_size=100,
    )
    assert len(attachment.chunks) >= 1
    # The replacement char (U+FFFD) should appear where \xe9 was
    assert "Caf" in " ".join(attachment.chunks)


@pytest.mark.asyncio
async def test_parse_file_txt(sample_txt_bytes):
    attachment = await parse_file(
        data=sample_txt_bytes,
        filename="test.txt",
        content_type="text/plain",
        chunk_size=100,
    )
    assert attachment.filename == "test.txt"
    assert attachment.size_bytes == len(sample_txt_bytes)
    assert len(attachment.chunks) >= 1
    assert "test document" in " ".join(attachment.chunks)


@pytest.mark.asyncio
async def test_parse_file_unknown_extension():
    # Should fall back to plain text extraction
    data = b"Some content in an unknown file type"
    attachment = await parse_file(data=data, filename="file.xyz", content_type="application/xyz")
    assert len(attachment.chunks) >= 1


# ── Cloud placeholders (OneDrive Files-On-Demand) — B-2026-09-05-1 ───────────
# Live transcript (qwen3.8-flash, CV-read session): the user's CV was a cloud
# placeholder with OneDrive NOT running. open() → errno 22, copies → WinError
# 362; file_task classified it internal_error, whose recovery directive says
# "try a different approach" — so the model burned 4+ iterations on doomed
# retries (code_exec, shell Copy-Item) before the turn died. The fix classifies
# these reads as cloud_placeholder with an explicit do-not-retry directive.



class _FakeStat:
    """Minimal stat_result stand-in carrying only st_file_attributes."""

    def __init__(self, attrs):
        self.st_file_attributes = attrs


def test_is_cloud_placeholder_detects_recall_attr():
    from tools.file_reader import _is_cloud_placeholder_file

    # 0x00400020 = ARCHIVE | RECALL_ON_DATA_ACCESS — the live CV file's attrs.
    assert _is_cloud_placeholder_file(_FakeStat(0x00400020)) is True
    assert _is_cloud_placeholder_file(_FakeStat(0x20)) is False


def test_is_cloud_placeholder_non_windows_stat():
    """Non-Windows stat results have no st_file_attributes — not a placeholder."""
    from tools.file_reader import _is_cloud_placeholder_file

    class _UnixStat:
        pass

    assert _is_cloud_placeholder_file(_UnixStat()) is False


def test_classify_read_error_winerror_362():
    """WinError 362 (cloud provider not running) is cloud_placeholder even
    without the attribute (shutil surfaces exactly this)."""
    from tools.file_reader import _classify_read_error

    exc = OSError(22, "Invalid argument")
    exc.winerror = 362
    assert _classify_read_error(exc, has_recall_attr=False) == "cloud_placeholder"


def test_classify_read_error_errno22_needs_recall_corroboration():
    from tools.file_reader import _classify_read_error

    assert _classify_read_error(OSError(22, "Invalid argument"), has_recall_attr=True) == "cloud_placeholder"
    # errno 22 without the placeholder attribute is NOT confidently a cloud
    # failure — keep the generic class instead of a misleading diagnosis.
    assert _classify_read_error(OSError(22, "bogus"), has_recall_attr=False) == "internal_error"


def test_classify_read_error_permission_and_generic():
    from tools.file_reader import _classify_read_error

    assert _classify_read_error(OSError(13, "Permission denied"), has_recall_attr=False) == "permission_denied"
    assert _classify_read_error(OSError(5, "Access is denied"), has_recall_attr=False) == "internal_error"


@pytest.mark.asyncio
async def test_file_task_cloud_placeholder_returns_honest_no_retry(monkeypatch, tmp_path):
    """A placeholder whose read fails (provider down) yields cloud_placeholder
    with the no-retry hint — NOT the old internal_error retry loop."""
    from tools.file_reader import file_task

    f = tmp_path / "CV.docx"
    f.write_bytes(b"PK\x03\x04not-really-a-zip")  # exists() must pass
    monkeypatch.setattr(
        pathlib.Path, "read_bytes", lambda self: (_ for _ in ()).throw(OSError(22, "Invalid argument"))
    )
    # The temp file is a real local file; force the placeholder stat signal.
    monkeypatch.setattr("tools.file_reader._is_cloud_placeholder_file", lambda st: True)

    result = await file_task(f"Read {f}")

    assert result.success is False
    assert result.error_type == "cloud_placeholder"
    assert "do NOT retry" in result.content
    assert "Always keep on this device" in result.content


@pytest.mark.asyncio
async def test_file_task_provider_down_winerror_362(monkeypatch, tmp_path):
    """shutil-style WinError 362 surfaces the same honest cloud_placeholder."""
    from tools.file_reader import file_task

    class _CloudOSError(OSError):
        def __init__(self, *args):
            super().__init__(*args)
            self.winerror = 362

    f = tmp_path / "notes.txt"
    f.write_bytes(b"hello")
    monkeypatch.setattr(
        pathlib.Path,
        "read_bytes",
        lambda self: (_ for _ in ()).throw(
            _CloudOSError(22, "The cloud file provider is not running")
        ),
    )

    result = await file_task(f"Read {f}")

    assert result.error_type == "cloud_placeholder"
    assert "do NOT retry" in result.content


# ── Unsupported binary containers — B-2026-09-05-2 ───────────────────────────
# .pub/.doc/.ppt-era files used to reach the plain-text decode path and come
# back as mojibake line-numbered garbage the model could mistake for contents.

@pytest.mark.asyncio
async def test_file_task_ole2_container_is_unsupported_not_mojibake(tmp_path):
    """A legacy .pub (OLE2 compound doc) gets an honest unsupported_format
    result with a convert-first instruction — never decoded garbage."""
    from tools.file_reader import file_task

    f = tmp_path / "CV-TisoneKironget.pub"
    f.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)

    result = await file_task(f"Read {f}")

    assert result.success is False
    assert result.error_type == "unsupported_format"
    assert "Save As" in result.content
    # The OLE2 magic must NOT leak into the content as decoded text.
    assert "\xd0\xcf" not in result.content


@pytest.mark.asyncio
async def test_file_task_zip_container_doc_is_unsupported(tmp_path):
    """A legacy .doc that is really a zip-container binary gets the same guard."""
    from tools.file_reader import file_task

    f = tmp_path / "old.doc"
    f.write_bytes(b"PK\x03\x04" + b"\x00" * 64)

    result = await file_task(f"Read {f}")

    assert result.error_type == "unsupported_format"
    assert "PDF, DOCX" in result.content


@pytest.mark.asyncio
async def test_file_task_plain_text_still_reads_normally(tmp_path):
    """Guard is magic-based only — a normal text file is untouched."""
    from tools.file_reader import file_task

    f = tmp_path / "notes.md"
    f.write_bytes("Line one.\nLine two.\n".encode("utf-8"))

    result = await file_task(f"Read {f}")

    assert result.success is not False
    assert "Line one." in result.content


def test_extract_legacy_office_paths():
    """.pub/.doc paths are now extracted instead of not_found."""
    got = _extract_path_candidates(r"read C:\Users\tison\OneDrive\Documents\CV-TisoneKironget.pub")
    assert got[0] == r"C:\Users\tison\OneDrive\Documents\CV-TisoneKironget.pub"
    # docx must still win over doc in the alternation (order-sensitive regex).
    assert _extract_path_candidates(r"C:\Users\tison\Documents\CV.docx")[0] == r"C:\Users\tison\Documents\CV.docx"
    assert _extract_path_candidates(r"C:\Users\tison\Documents\CV.xlsx")[0] == r"C:\Users\tison\Documents\CV.xlsx"


@pytest.mark.asyncio
async def test_parse_file_upload_path_rejects_ole2():
    """parse_file (upload path) returns the honest unsupported text instead of
    mojibake chunks for a legacy .pub attachment."""
    data = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64
    attachment = await parse_file(data=data, filename="brochure.pub", content_type="application/octet-stream")
    joined = " ".join(attachment.chunks)
    assert "Unsupported binary format" in joined
    assert "Save As" in joined
