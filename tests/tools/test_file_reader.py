"""Tests for the file reader tool."""
import pytest

from tools import file_reader as fr
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


# ── S422: .pub and image extensions resolve as path candidates ──────────────
# The OCR parser existed, but a .jpg path in a message never resolved —
# "No file found" — so image reading was unreachable by path reference.
# Same trap pre-S422 for .pub (now routed to honest unsupported_format).
def test_extract_image_paths():
    # Full drive-absolute path must be the FIRST candidate (S264 style) —
    # the bare-fallback pattern may add a secondary tail candidate.
    got = _extract_path_candidates(r"read C:\Users\tison\Pictures\scan.jpg")
    assert got[0] == r"C:\Users\tison\Pictures\scan.jpg"
    assert _extract_path_candidates("describe /home/user/photo.PNG")[0] == (
        "/home/user/photo.PNG"
    )


def test_extract_pub_path():
    got = _extract_path_candidates(
        r"read C:\Users\tison\OneDrive\Documents\CV-TisoneKironget.pub"
    )
    assert got[0] == r"C:\Users\tison\OneDrive\Documents\CV-TisoneKironget.pub"


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


# ── Cloud-file (OneDrive Files-On-Demand) recovery (S422) ────────────────────
# The "find my CV" transcript: a PINNED OneDrive placeholder with the cloud
# provider down fails EVERY read with OSError EINVAL (Win32 362 "The cloud
# file provider is not running"). Pre-S422 file_task surfaced a bare
# "[Errno 22] Invalid argument" and the model burned turns improvising
# zipfile / raw-byte / shell reads. The read path now classifies the
# condition, nudges the provider, and reports a precise remedy.

def _fake_attrs(monkeypatch, placeholder: bool):
    """Force _windows_file_attrs to report a (non-)placeholder regardless of OS."""
    attrs = 0x20 | (0x400000 if placeholder else 0)  # ARCHIVE (+ RECALL_ON_DATA_ACCESS)
    monkeypatch.setattr(fr, "_windows_file_attrs", lambda p: attrs)


def test_classify_cloud_error_by_winerror():
    err = OSError(22, "Invalid argument")
    err.winerror = 362  # ERROR_CLOUD_FILE_NOT_UNDER_CLOUD_ROOT family member
    assert fr._classify_cloud_file_error(err, attrs=0) is True


def test_classify_cloud_error_by_einval_plus_placeholder_attrs():
    # Python's io layer raises OSError(errno=EINVAL) WITHOUT winerror for
    # filter-driver failures (verified on the real S422 placeholder).
    err = OSError(22, "Invalid argument")
    assert fr._classify_cloud_file_error(err, attrs=0x400000 | 0x20) is True


def test_classify_plain_einval_not_cloud():
    # EINVAL on a NORMAL file (e.g. reading a directory) is NOT cloud —
    # it must propagate as a generic failure, not the cloud path.
    err = OSError(22, "Invalid argument")
    assert fr._classify_cloud_file_error(err, attrs=0x20) is False


def test_classify_other_oserror_not_cloud():
    err = OSError(13, "Permission denied")
    assert fr._classify_cloud_file_error(err, attrs=0x400000) is False


@pytest.mark.asyncio
async def test_cloud_recovery_hydrates_after_provider_start(monkeypatch, tmp_path):
    """Read fails → provider started → probe succeeds → data returned."""
    f = tmp_path / "cv.docx"
    f.write_bytes(b"PK hydrated-bytes")
    _fake_attrs(monkeypatch, placeholder=True)

    state = {"fail": True, "started": 0}

    def flaky_read(p):
        if state["fail"]:
            raise OSError(22, "Invalid argument")
        return b"PK hydrated-bytes"

    def fake_start(exe):
        state["started"] += 1
        state["fail"] = False  # the started provider hydrates the file
        return True

    monkeypatch.setattr(fr, "_cloud_provider_running", lambda: False)
    monkeypatch.setattr(fr, "_find_cloud_provider_exe", lambda: tmp_path / "fake" / "OneDrive.exe")
    monkeypatch.setattr(fr, "_start_cloud_provider", fake_start)
    monkeypatch.setattr(fr, "_probe_cloud_file", lambda p: not state["fail"])
    monkeypatch.setattr(fr, "_PROVIDER_START_WAIT_SECONDS", 0.05)
    import asyncio as _aio

    async def nosleep(_):
        return None

    monkeypatch.setattr(_aio, "sleep", nosleep)

    data, diag = await fr._read_file_with_cloud_recovery(f, _read=flaky_read)
    assert data == b"PK hydrated-bytes"
    assert diag["cloud_placeholder"] is True
    assert diag["provider_running"] is False
    assert diag["provider_started"] is True
    assert state["started"] == 1


@pytest.mark.asyncio
async def test_cloud_recovery_reports_unhydrated_when_provider_down(monkeypatch, tmp_path):
    """Provider missing entirely → honest None + full diagnostics."""
    f = tmp_path / "cv.docx"
    f.write_bytes(b"PK never-readable")
    _fake_attrs(monkeypatch, placeholder=True)

    def always_fail(p):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(fr, "_cloud_provider_running", lambda: False)
    monkeypatch.setattr(fr, "_find_cloud_provider_exe", lambda: None)  # not installed
    monkeypatch.setattr(fr, "_probe_cloud_file", lambda p: False)  # never hydrates
    import asyncio as _aio

    async def nosleep(_):
        return None

    monkeypatch.setattr(_aio, "sleep", nosleep)
    monkeypatch.setattr(fr, "_PROVIDER_START_WAIT_SECONDS", 0.05)

    data, diag = await fr._read_file_with_cloud_recovery(f, _read=always_fail)
    assert data is None
    assert diag["cloud_placeholder"] is True
    assert diag["provider_running"] is False
    assert diag["provider_started"] is False
    assert diag["cloud_error"] == 22  # the original OS error is preserved


@pytest.mark.asyncio
async def test_cloud_recovery_provider_running_no_start(monkeypatch, tmp_path):
    """Provider already running → never spawns a process; keeps waiting."""
    f = tmp_path / "cv.docx"
    f.write_bytes(b"PK slow-provider")
    _fake_attrs(monkeypatch, placeholder=True)

    def slow_read(p):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(fr, "_cloud_provider_running", lambda: True)
    started = {"n": 0}

    def no_start(exe):
        started["n"] += 1
        return True

    monkeypatch.setattr(fr, "_start_cloud_provider", no_start)
    monkeypatch.setattr(fr, "_probe_cloud_file", lambda p: False)
    import asyncio as _aio

    async def nosleep(_):
        return None

    monkeypatch.setattr(_aio, "sleep", nosleep)
    monkeypatch.setattr(fr, "_PROVIDER_START_WAIT_SECONDS", 0.05)

    data, diag = await fr._read_file_with_cloud_recovery(f, _read=slow_read)
    assert data is None
    assert diag["provider_running"] is True
    assert diag["provider_started"] is False
    assert started["n"] == 0


def test_cloud_unavailable_message_names_remedy(tmp_path):
    diag = {"cloud_placeholder": True, "provider_running": False,
            "provider_started": False, "cloud_error": 362}
    msg = fr._cloud_file_unavailable_message(tmp_path / "cv.docx", diag)
    assert "OneDrive" in msg
    assert "Remedy" in msg
    assert "Do NOT try zipfile/code_exec/shell" in msg
    assert "Never fabricate" in msg


@pytest.mark.asyncio
async def test_file_task_cloud_placeholder_reports_cloud_file_unavailable(monkeypatch, tmp_path):
    """End-to-end: file_task returns error_type=cloud_file_unavailable, with the
    recovery-relevant metadata — the exact shape the transcript needed."""
    from tools.file_reader import file_task

    f = tmp_path / "CV-Test.docx"
    f.write_bytes(b"PK placeholder")
    from pathlib import Path as _P

    monkeypatch.setattr(
        "core.config._allowed_user_folders", lambda: [str(tmp_path), str(_P.home())]
    )
    _fake_attrs(monkeypatch, placeholder=True)

    def always_fail(p):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(fr, "_default_read", always_fail)
    monkeypatch.setattr(fr, "_cloud_provider_running", lambda: False)
    monkeypatch.setattr(fr, "_find_cloud_provider_exe", lambda: None)
    monkeypatch.setattr(fr, "_probe_cloud_file", lambda p: False)  # never hydrates
    import asyncio as _aio

    async def nosleep(_):
        return None

    monkeypatch.setattr(_aio, "sleep", nosleep)
    monkeypatch.setattr(fr, "_PROVIDER_START_WAIT_SECONDS", 0.05)

    res = await file_task(str(f))
    assert res.success is False
    assert res.error_type == "cloud_file_unavailable"
    assert res.metadata["cloud_placeholder"] is True
    assert "Remedy" in res.content


@pytest.mark.asyncio
async def test_file_task_happy_path_unchanged(monkeypatch, tmp_path):
    """Normal local file still reads through the same pipeline unchanged."""
    from tools.file_reader import file_task

    f = tmp_path / "notes.md"
    f.write_bytes(b"# hello\nworld\n")
    from pathlib import Path as _P

    monkeypatch.setattr(
        "core.config._allowed_user_folders", lambda: [str(tmp_path), str(_P.home())]
    )

    res = await file_task(str(f))
    assert res.success is True
    assert not res.error_type
    assert "hello" in res.content


@pytest.mark.asyncio
async def test_file_task_plain_einval_stays_internal_error(monkeypatch, tmp_path):
    """EINVAL on a normal file must NOT be classified as cloud — it keeps the
    honest generic failure (e.g. read-a-directory edge)."""
    from tools.file_reader import file_task

    d = tmp_path / "not-a-file.docx"  # exists() is True, is_file() is False →
    # file_task skips it; use a real file whose read raises plain EINVAL.
    real = tmp_path / "weird.md"
    real.write_bytes(b"x")
    from pathlib import Path as _P

    monkeypatch.setattr(
        "core.config._allowed_user_folders", lambda: [str(tmp_path), str(_P.home())]
    )
    _fake_attrs(monkeypatch, placeholder=False)

    def plain_einval(p):
        raise OSError(22, "Invalid argument")  # no winerror, no placeholder attrs

    monkeypatch.setattr(fr, "_default_read", plain_einval)

    res = await file_task(str(real))
    assert res.success is False
    # NOT the cloud class — EINVAL on a normal file is a generic read failure.
    assert res.error_type == "internal_error"
    assert res.error_type != "cloud_file_unavailable"


# ── Content-sniffed parser dispatch (S422) ───────────────────────────────────

def test_sniff_format_known_signatures():
    assert fr._sniff_format(b"%PDF-1.7\n...") == "pdf"
    assert fr._sniff_format(b"PK\x03\x04rest") == "zip"
    assert fr._sniff_format(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1...") == "ole"
    assert fr._sniff_format(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8) == "png"
    assert fr._sniff_format(b"\xFF\xD8\xFF\xE0") == "jpeg"
    assert fr._sniff_format(b"GIF89a" + b"\x00" * 4) == "gif"
    assert fr._sniff_format(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "webp"


def test_sniff_format_weak_signatures_not_sniffed():
    # BMP ('BM') and TIFF ('II*'/'MM*') also prefix ordinary text — they must
    # NOT be sniffed, or text files starting "BMW..." would route to the
    # image parser.
    assert fr._sniff_format(b"BMW is a car brand\n") == "unknown"
    assert fr._sniff_format(b"II* and the order\n") == "unknown"


def test_sniff_format_unknown():
    assert fr._sniff_format(b"plain text file") == "unknown"
    assert fr._sniff_format(b"") == "unknown"


def test_looks_like_text():
    assert fr._looks_like_text(b"# markdown\n- list\n")
    assert not fr._looks_like_text(b"\x00\x01binary\x00")      # NUL bytes
    assert not fr._looks_like_text(b"\xff\xfe\x00\x00")        # invalid UTF-8
    assert fr._looks_like_text(b"")


def test_resolve_kind_content_overrides_extension():
    # Real PDF bytes under a .txt name → content wins.
    kind, note = fr._resolve_read_kind(".txt", "pdf", b"%PDF-1.4")
    assert kind == "pdf" and "dispatched by content" in note
    # Text content under .docx → honest text fallback.
    kind, note = fr._resolve_read_kind(".docx", "unknown", b"# actually markdown")
    assert kind == "text" and "read as text" in note
    # Binary content under a .bmp name → extension trusted (no weak sniff).
    kind, _ = fr._resolve_read_kind(".bmp", "unknown", b"BM\x00\x00binary")
    assert kind == "image"


def test_resolve_kind_unsupported_families():
    kind, _ = fr._resolve_read_kind(".pub", "ole", b"\xD0\xCF\x11\xE0" + b"\x00" * 4)
    assert kind == "unsupported_ole"
    # A zip that claims nothing recognized is ambiguous, not silently text.
    kind, _ = fr._resolve_read_kind(".dat", "zip", b"PK\x03\x04")
    assert kind == "zip_ambiguous"
    # Right extensions keep their parsers.
    assert fr._resolve_read_kind(".docx", "zip", b"PK\x03\x04")[0] == "docx"
    assert fr._resolve_read_kind(".xlsx", "zip", b"PK\x03\x04")[0] == "xlsx"
    assert fr._resolve_read_kind(".pdf", "pdf", b"%PDF-1.4")[0] == "pdf"
    assert fr._resolve_read_kind(".csv", "unknown", b"a,b\n1,2")[0] == "csv"


@pytest.mark.asyncio
async def test_file_task_ole_pub_honest_unsupported(monkeypatch, tmp_path):
    """A .pub (Publisher) file now gets an honest unsupported result instead of
    line-numbered binary garbage (pre-S422 it fell through the text path)."""
    from tools.file_reader import file_task

    f = tmp_path / "old-cv.pub"
    f.write_bytes(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1" + b"\x00" * 64)
    from pathlib import Path as _P

    monkeypatch.setattr(
        "core.config._allowed_user_folders", lambda: [str(tmp_path), str(_P.home())]
    )

    res = await file_task(str(f))
    assert res.success is False
    assert res.error_type == "unsupported_format"
    assert "re-save it as .docx or .pdf" in res.content
    assert res.metadata["sniff"] == "ole"


@pytest.mark.asyncio
async def test_file_task_text_maslabeled_docx_reads_as_text(monkeypatch, tmp_path):
    from tools.file_reader import file_task

    f = tmp_path / "actually-text.docx"
    f.write_bytes(b"# this is plain markdown\nnot a real docx\n")
    from pathlib import Path as _P

    monkeypatch.setattr(
        "core.config._allowed_user_folders", lambda: [str(tmp_path), str(_P.home())]
    )

    res = await file_task(str(f))
    assert res.success is True
    assert "actually-text.docx" in res.content
    assert "read as text" in res.content  # the mismatch note is surfaced


@pytest.mark.asyncio
async def test_file_task_pdf_bytes_txt_name_dispatches_by_content(monkeypatch, tmp_path):
    from tools.file_reader import file_task

    f = tmp_path / "mislabeled.txt"
    f.write_bytes(b"%PDF-1.4\n(broken pdf body)")
    from pathlib import Path as _P

    monkeypatch.setattr(
        "core.config._allowed_user_folders", lambda: [str(tmp_path), str(_P.home())]
    )

    res = await file_task(str(f))
    assert res.success is True
    # Routed into the PDF parser (which honestly reports the broken body) —
    # NOT line-numbered text output.
    assert "dispatched by content" in res.content
    assert res.metadata["sniff"] == "pdf"


@pytest.mark.asyncio
async def test_parse_file_sniffed_dispatch_xyz_image(monkeypatch):
    """Upload pipeline: PNG bytes under an unknown extension route to the
    image parser instead of plain-text garbage."""
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    attachment = await parse_file(data=png, filename="mystery.xyz", content_type="application/xyz")
    # PIL is not installed in every env; both outcomes prove the ROUTE:
    # image parser metadata line, or its honest missing-dependency error —
    # never the "[File parse error]" of a misrouted text decode.
    first = attachment.chunks[0] if attachment.chunks else ""
    assert "Image" in first or "image" in first
