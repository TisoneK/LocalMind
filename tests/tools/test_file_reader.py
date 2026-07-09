"""Tests for the file reader tool."""
import pytest
from tools.file_reader import _chunk_text, parse_file


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
