"""Tests for the file reader tool."""
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
