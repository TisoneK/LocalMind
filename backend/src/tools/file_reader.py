"""
File Reader tool — parses uploaded files into text chunks for the model.

Supported formats:
    PDF   → PyMuPDF (fitz)
    DOCX  → python-docx
    CSV   → pandas
    XLSX  → pandas + openpyxl
    Images → OCR via pytesseract (if installed), else metadata only
    TXT / MD / code files → plain UTF-8 read

Also exports parse_file() used directly by the engine for file attachments.
Registered as Intent.FILE_TASK in the tool registry.

Performance notes:
- Plain text files are read with a hard cap (FILE_READ_MAX_BYTES) to prevent
  context overflow on large logs/source files.
- All heavy parsing (PDF, DOCX, CSV) runs inside asyncio.to_thread so it never
  blocks the event loop.
- A FILE_OP_TIMEOUT_SECONDS deadline wraps each parse call; stalls on network
  mounts or corrupt files are killed cleanly.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import time
from pathlib import Path

from core.agent.constants import FILE_OP_TIMEOUT_SECONDS, FILE_READ_MAX_BYTES
from core.config import settings
from core.models import FileAttachment, Intent, RiskLevel, ToolResult
from tools import register_tool

logger = logging.getLogger(__name__)

# ── Line-numbered output constants ──────────────────────────────────────────
# For the file_task tool, plain-text files whose formatted (line-numbered)
# output fits under this byte budget are returned in full.  Larger files are
# truncated at a clean line boundary with a precise line-count notice so the
# model knows exactly how much is missing.
_FULL_CONTENT_MAX_BYTES: int = 100 * 1024  # 100 KB

# ── Cloud-file (OneDrive Files-On-Demand) handling (S422) ───────────────────
# OneDrive "Files On-Demand" leaves placeholder entries on disk whose bytes
# live in the cloud. Reading one is supposed to hydrate it transparently —
# but when the cloud provider process (OneDrive.exe) is not running, EVERY
# read fails with OSError EINVAL (Win32 ERROR_CLOUD_FILE_* family; observed
# 362 "The cloud file provider is not running" on a real PINNED placeholder).
# Before S422 this surfaced as a bare "[Errno 22] Invalid argument" that the
# model misdiagnosed and worked around with zipfile / raw-byte / shell
# attempts (the "find my CV" transcript). We now classify the condition and
# give one bounded provider nudge; everything else is an honest, precise
# error. NOTE: a pinned placeholder cannot be hydrated from the file side
# while the provider is down — starting the provider is the only remedy.

_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
_FILE_ATTRIBUTE_OFFLINE = 0x1000

# winnt.h ERROR_CLOUD_FILE_* family (362..410). 362 is the observed
# "The cloud file provider is not running" code.
_CLOUD_FILE_WINERROR_LO = 362
_CLOUD_FILE_WINERROR_HI = 410

_CLOUD_PROVIDER_NAME = "onedrive.exe"

# Bounded hydration wait after the provider is (re)started — a small file
# over a working sync connection downloads well inside this; a big one will
# honestly report "not yet downloaded, retry shortly" instead of hanging.
_PROVIDER_START_WAIT_SECONDS = 12.0
_PROVIDER_POLL_INTERVAL_SECONDS = 1.0


def _windows_file_attrs(p: Path) -> int:
    """``st_file_attributes`` on Windows; 0 elsewhere (attribute is nt-only)."""
    try:
        return os.stat(p).st_file_attributes
    except (AttributeError, OSError):
        return 0


def _attrs_say_cloud_placeholder(attrs: int) -> bool:
    """RECALL_ON_DATA_ACCESS / OFFLINE mark a Files-On-Demand placeholder.

    REPARSE_POINT alone is NOT cloud (plain symlinks/junctions carry it).
    """
    return bool(attrs & (_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS | _FILE_ATTRIBUTE_OFFLINE))


def _safe_file_size(p: Path) -> int:
    """st_size via stat, 0 when stat fails (metadata only — never fatal)."""
    try:
        return os.stat(p).st_size
    except OSError:
        return 0


def _classify_cloud_file_error(e: OSError, attrs: int) -> bool:
    """Is this OSError a cloud-file provider failure (not a plain EINVAL)?

    Two accepted signals, either suffices:
    - ``e.winerror`` inside the ERROR_CLOUD_FILE_* family (strong, OS-given);
    - EINVAL + placeholder attributes (Python's io layer raises
      OSError(errno=EINVAL) WITHOUT winerror for filter-driver failures —
      verified on the real S422 placeholder, where GetLastError() held 362
      but ``e.winerror`` was None).
    """
    winerr = getattr(e, "winerror", None)
    if isinstance(winerr, int) and _CLOUD_FILE_WINERROR_LO <= winerr <= _CLOUD_FILE_WINERROR_HI:
        return True
    return e.errno == 22 and _attrs_say_cloud_placeholder(attrs)


def _cloud_provider_running() -> bool | None:
    """True/False by process scan; None when psutil is unavailable."""
    try:
        import psutil
    except ImportError:
        return None
    try:
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if name == _CLOUD_PROVIDER_NAME:
                return True
    except Exception as e:  # psutil can raise on access-restricted processes
        logger.debug("[file_task] provider process scan failed: %s", e)
        return None
    return False


def _find_cloud_provider_exe() -> Path | None:
    """Locate the installed cloud-provider executable, or None."""
    if os.name != "nt":
        return None
    candidates: list[Path] = []
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        candidates.append(Path(local_app) / "Microsoft" / "OneDrive" / "OneDrive.exe")
    candidates.extend([
        Path("C:/Program Files/Microsoft OneDrive/OneDrive.exe"),
        Path("C:/Program Files (x86)/Microsoft OneDrive/OneDrive.exe"),
    ])
    for c in candidates:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    return None


def _start_cloud_provider(exe: Path) -> bool:
    """Start the provider detached (no console, no output capture)."""
    try:
        flags = 0
        if hasattr(subprocess, "DETACHED_PROCESS"):
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(  # noqa: S603 — fixed executable path, no shell
            [str(exe), "/background"],
            close_fds=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        return True
    except Exception as e:
        logger.warning("[file_task] failed to start cloud provider %s: %s", exe, e)
        return False


def _default_read(p: Path) -> bytes:
    return p.read_bytes()


def _probe_cloud_file(p: Path) -> bool:
    """Short read to check hydration state; True when bytes are reachable."""
    try:
        with open(p, "rb") as f:
            f.read(16)
        return True
    except OSError:
        return False


async def _read_file_with_cloud_recovery(
    p: Path, _read=None
) -> tuple[bytes | None, dict]:
    """file_task's canonical byte read with cloud-placeholder recovery.

    Returns ``(data, diagnostics)``. ``data`` is None when the file could
    not be read; ``diagnostics`` records the cloud state for the result
    metadata and the user-facing message. ``_read`` is injectable for tests.
    """
    read = _read or _default_read
    diag: dict = {
        "cloud_placeholder": False,
        "provider_running": None,
        "provider_started": False,
        "cloud_error": None,
    }
    attrs = _windows_file_attrs(p)
    diag["cloud_placeholder"] = _attrs_say_cloud_placeholder(attrs)
    try:
        # On a healthy provider this read IS the hydration trigger — the
        # filter driver blocks until the bytes arrive.
        return read(p), diag
    except OSError as e:
        if not _classify_cloud_file_error(e, attrs):
            raise
        diag["cloud_error"] = getattr(e, "winerror", None) or e.errno
        logger.info("[file_task] cloud-file read failed for %s: %s", p, e)

    running = _cloud_provider_running()
    diag["provider_running"] = running
    if running is False:
        exe = _find_cloud_provider_exe()
        if exe is not None and _start_cloud_provider(exe):
            diag["provider_started"] = True
            logger.info("[file_task] started cloud provider %s to hydrate %s", exe, p.name)

    deadline = time.monotonic() + _PROVIDER_START_WAIT_SECONDS
    while time.monotonic() < deadline:
        await asyncio.sleep(_PROVIDER_POLL_INTERVAL_SECONDS)
        # Probe read: succeeds the moment the filter can hydrate.
        if _probe_cloud_file(p):
            return read(p), diag
    # data=None after this point ALWAYS means "timed out waiting for
    # hydration" — cloud_error keeps the original OS error (the root cause).
    return None, diag


def _cloud_file_unavailable_message(p: Path, diag: dict) -> str:
    """Precise, actionable failure text for an unhydrated cloud placeholder."""
    lines = [
        f"Could not read {p}: it is a OneDrive/cloud placeholder whose content is not on disk",
        "(a normal read would download it, but the cloud file provider is not serving this file right now).",
    ]
    if diag.get("provider_started"):
        lines.append(
            f"I started OneDrive and waited {int(_PROVIDER_START_WAIT_SECONDS)}s, "
            "but the file is still not downloaded."
        )
        lines.append(
            "Remedy: give OneDrive a few more seconds to sync, then re-ask to read this file — "
            "the read will then succeed. Do NOT try zipfile/code_exec/shell reads: the file is "
            "unreadable at the OS level until OneDrive hydrates it."
        )
    elif diag.get("provider_running") is False:
        lines.append("OneDrive.exe is not running and could not be started automatically (it may not be installed).")
        lines.append(
            "Remedy: ask the user to start OneDrive (or open the file in its app once), then re-ask. "
            "Do NOT try zipfile/code_exec/shell reads: the file is unreadable at the OS level until "
            "OneDrive hydrates it."
        )
    else:
        lines.append("The OneDrive sync client is running but has not downloaded this file yet.")
        lines.append(
            "Remedy: wait a moment and re-ask, or have the user open the file in its app once. "
            "Do NOT try zipfile/code_exec/shell reads for the same reason."
        )
    lines.append("Never fabricate the file's contents — report this state honestly.")
    return "\n".join(lines)


# ── Content-sniffed parser dispatch (S422) ──────────────────────────────────
# Extension-based dispatch misreads mislabeled files (a renamed .pub served
# line-numbered binary garbage; a text file named .docx died inside
# python-docx). Dispatch is now content-first: magic bytes decide, and the
# extension is trusted only when the content has no known signature.

def _sniff_format(data: bytes) -> str:
    """Magic-byte sniff. Returns a known format token or 'unknown'.

    Only STRONG signatures are sniffed — 2-byte ones like BMP's 'BM' or
    TIFF's 'II*'/'MM*' also prefix ordinary text, so they are left to the
    extension + text-probe path below.
    """
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    signature = (
        (b"%PDF-", "pdf"),
        (b"PK\x03\x04", "zip"),       # DOCX/XLSX/PPTX/any zip container
        (b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1", "ole"),  # legacy .doc/.xls/.pub/.msi
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"\xFF\xD8\xFF", "jpeg"),
        (b"GIF87a", "gif"),
        (b"GIF89a", "gif"),
    )
    for sig, fmt in signature:
        if data[: len(sig)] == sig:
            return fmt
    return "unknown"


def _looks_like_text(data: bytes) -> bool:
    """Cheap text probe: no NULs in the head and the head is valid UTF-8."""
    sample = data[:4096]
    if not sample:
        return True
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _ole_unsupported_text(filename: str) -> str:
    return (
        f"[Unsupported format] {filename} is a legacy OLE2 compound document "
        "(Microsoft Publisher .pub, Word .doc, Excel .xls, ...). This reader "
        "supports PDF, DOCX, XLSX, CSV, images and text. Ask the user to "
        "re-save it as .docx or .pdf, then read that."
    )


def _zip_ambiguous_text(filename: str) -> str:
    return (
        f"[Unsupported format] {filename} is a ZIP archive but not a DOCX or "
        "XLSX document (could be .pptx, .zip, .jar, ...). It cannot be read "
        "as a document; ask the user what the file actually is."
    )


def _resolve_read_kind(ext: str, sniff: str, data: bytes) -> tuple[str, str]:
    """Content-first parser routing. Returns ``(kind, note)``.

    ``kind``: pdf | docx | xlsx | csv | image | text | unsupported_ole |
    zip_ambiguous. ``note`` is a human-readable explanation appended to the
    tool output whenever the routing overrode the extension, so the model
    knows the file's real nature.
    """
    if sniff == "ole":
        return "unsupported_ole", ""
    if sniff in ("png", "jpeg", "gif", "webp"):
        note = "" if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp") else (
            f"content is an image though the extension is '{ext or 'missing'}' — dispatched by content"
        )
        return "image", note
    if sniff == "pdf":
        if ext == ".pdf":
            return "pdf", ""
        return "pdf", f"content is a PDF though the extension is '{ext or 'missing'}' — dispatched by content"
    if sniff == "zip":
        if ext == ".docx":
            return "docx", ""
        if ext == ".xlsx":
            return "xlsx", ""
        return "zip_ambiguous", ""
    # sniff == "unknown": trust the extension unless the content is clearly text.
    if ext == ".csv":
        # CSV is text by nature — the text probe below must not mislabel it.
        return "csv", ""
    if ext in _SPECIAL_FORMAT_EXTS and _looks_like_text(data):
        return "text", f"extension is '{ext}' but the content is plain text — read as text"
    if ext == ".pdf":
        return "pdf", ""
    if ext == ".docx":
        return "docx", ""
    if ext == ".xlsx":
        return "xlsx", ""
    if ext == ".csv":
        return "csv", ""
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff"):
        return "image", ""
    return "text", ""


# Extensions handled by special parsers in parse_file() — these bypass the
# line-numbered plain-text path and use the existing chunked pipeline.
_SPECIAL_FORMAT_EXTS: frozenset[str] = frozenset({
    ".pdf", ".docx", ".xlsx", ".csv",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff",
})

SUPPORTED_EXTS = {
    ".pdf",
    ".docx",
    ".txt",
    ".md",
    ".csv",
    ".xlsx",
    ".py",
    ".js",
    ".ts",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".html",
    ".xml",
    ".sh",
    ".rs",
    ".go",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".webp",
    ".tiff",
}


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text into overlapping token-approximate chunks.

    Guards against infinite loops when overlap >= chunk_size by clamping
    the step to at least 1. Without this guard, a caller passing a small
    chunk_size with the default overlap (e.g. chunk_size=100,
    overlap=200) would loop forever.
    """
    words = text.split()
    if not words:
        return []
    # Ensure forward progress: step must be >= 1 even when overlap >= chunk_size.
    step = max(1, chunk_size - overlap)
    chunks = []
    i = 0
    while i < len(words):
        end = min(i + chunk_size, len(words))
        chunks.append(" ".join(words[i:end]))
        i += step
    return chunks


def _format_with_line_numbers(text: str, max_bytes: int) -> tuple[str, int, bool, int]:
    """Format text with ``cat -n`` style line numbers.

    Returns ``(formatted_text, total_lines, was_truncated, shown_lines)``.

    * For files whose formatted output fits under *max_bytes*, every line
      is shown.
    * For larger files, lines are included until the output size reaches
      *max_bytes*, then a truncation notice is appended so the model knows
      exactly how much content is missing.
    """
    lines = text.splitlines(keepends=True)
    total_lines = len(lines)

    output_parts: list[str] = []
    output_size = 0
    shown = 0

    for i, line in enumerate(lines, 1):
        line_entry = f"{i:>6}\t{line}"
        output_size += len(line_entry.encode("utf-8"))
        if output_size > max_bytes and i > 1:
            break
        output_parts.append(line_entry)
        shown = i

    truncated = shown < total_lines
    if truncated:
        output_parts.append(
            f"\n[truncated at line {shown} of {total_lines} total lines]"
        )

    return "".join(output_parts), total_lines, truncated, shown


def _detect_line_ending(data: bytes) -> str:
    """Detect the dominant line ending from raw file bytes.

    Scans the first 8 KB and returns ``'\\r\\n'`` if CRLF dominates,
    otherwise ``'\\n'``.
    """
    sample = data[:8192]
    crlf_count = sample.count(b"\r\n")
    lf_only = sample.count(b"\n") - crlf_count
    return "\r\n" if crlf_count > lf_only else "\n"


async def _parse_pdf(data: bytes) -> str:
    def _do_parse() -> str:
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(stream=data, filetype="pdf")
            pages = [page.get_text() for page in doc]
            text = "\n\n".join(pages)
            logger.info(f"[file_reader] PDF parsed: {len(text)} chars from {len(pages)} pages")
            return text
        except Exception as e:
            logger.error(f"[file_reader] PDF parse error: {e}")
            return f"[PDF parse error: {e}]"

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_do_parse),
            timeout=FILE_OP_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(f"[file_reader] PDF parse timed out after {FILE_OP_TIMEOUT_SECONDS}s")
        return f"[PDF parse timed out after {FILE_OP_TIMEOUT_SECONDS}s — file may be too large or corrupted]"


async def _parse_docx(data: bytes) -> str:
    def _do_parse() -> str:
        try:
            import io

            from docx import Document

            doc = Document(io.BytesIO(data))
            parts = [p.text for p in doc.paragraphs if p.text.strip()]
            # Tables are NOT in doc.paragraphs — a docx built from table
            # cells (common in CVs/forms) would otherwise read as empty.
            # Order note: all paragraphs first, then all tables row-wise.
            for table in doc.tables:
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells]
                    if any(cells):
                        parts.append(" | ".join(cells))
            text = "\n".join(parts)
            # Embedded images are invisible to text extraction — enumerate
            # them honestly instead of silently dropping that channel.
            try:
                n_images = len(doc.inline_shapes)
            except Exception:
                n_images = 0
            if n_images:
                text += (
                    f"\n\n[{n_images} embedded image(s) present in this DOCX — text extraction "
                    "does not include them. If their content matters, extract them via code_exec "
                    "(a DOCX is a zip; images live in word/media/) and OCR them.]"
                )
            return text
        except Exception as e:
            logger.error(f"[file_reader] DOCX parse error: {e}")
            return f"[DOCX parse error: {e}]"

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_do_parse),
            timeout=FILE_OP_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return f"[DOCX parse timed out after {FILE_OP_TIMEOUT_SECONDS}s]"


async def _parse_image(data: bytes, filename: str) -> str:
    """Parse image using OCR. Returns extracted text and basic metadata."""
    try:
        import io

        from PIL import Image

        image = Image.open(io.BytesIO(data))
        width, height = image.size
        format_name = image.format

        ocr_text = ""
        try:
            import pytesseract

            ocr_text = pytesseract.image_to_string(image).strip()
        except Exception as ocr_error:
            logger.debug(f"[file_reader] OCR unavailable: {ocr_error}")

        result = f"Image: {filename} ({width}x{height}, {format_name})"
        if ocr_text:
            result += f"\n\nExtracted Text:\n{ocr_text}"
        else:
            result += "\n\nNo text could be extracted (pytesseract not installed or image has no readable text)."

        logger.info(
            f"[file_reader] image parsed: {filename} ({width}x{height}) — {len(ocr_text)} OCR chars"
        )
        return result

    except Exception as e:
        logger.error(f"[file_reader] image parse error: {e}")
        return f"[Image parse error: {e}]"


async def _parse_xlsx(data: bytes) -> str:
    def _do_parse() -> str:
        try:
            import io

            import pandas as pd

            df = pd.read_excel(io.BytesIO(data), engine="openpyxl")
            shape_info = f"Shape: {df.shape[0]} rows × {df.shape[1]} columns\nColumns: {', '.join(df.columns.tolist())}\n\n"  # noqa: E501
            preview = df.head(20).to_markdown(index=False)
            return shape_info + preview
        except Exception as e:
            logger.error(f"[file_reader] XLSX parse error: {e}")
            return f"[XLSX parse error: {e}]"

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_do_parse),
            timeout=FILE_OP_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return f"[XLSX parse timed out after {FILE_OP_TIMEOUT_SECONDS}s]"


async def _parse_csv(data: bytes) -> str:
    def _do_parse() -> str:
        try:
            import io

            import pandas as pd

            df = pd.read_csv(io.BytesIO(data))
            shape_info = f"Shape: {df.shape[0]} rows × {df.shape[1]} columns\nColumns: {', '.join(df.columns.tolist())}\n\n"  # noqa: E501
            preview = df.head(20).to_markdown(index=False)
            return shape_info + preview
        except Exception as e:
            logger.error(f"[file_reader] CSV parse error: {e}")
            return f"[CSV parse error: {e}]"

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_do_parse),
            timeout=FILE_OP_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return f"[CSV parse timed out after {FILE_OP_TIMEOUT_SECONDS}s]"


# Spreadsheet preview caps — keep the browser payload sane even for huge files.
MAX_SHEET_ROWS = 200
MAX_SHEET_COLS = 50


def _cell_to_str(value) -> str:
    """Normalize a spreadsheet cell to a JSON-safe display string."""
    import math

    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        # 1.0 -> "1", 3.14 -> "3.14" — avoid pandas float noise.
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)
    return str(value)


def _dataframe_to_sheet(df) -> dict:
    """Convert a DataFrame to a capped {name, rows, truncated} sheet payload."""
    truncated = False
    if df.shape[0] > MAX_SHEET_ROWS:
        df = df.head(MAX_SHEET_ROWS)
        truncated = True
    if df.shape[1] > MAX_SHEET_COLS:
        df = df.iloc[:, :MAX_SHEET_COLS]
        truncated = True
    header = [_cell_to_str(c) for c in df.columns.tolist()]
    rows = [header]
    for _, row in df.iterrows():
        rows.append([_cell_to_str(v) for v in row.tolist()])
    return {"name": "", "rows": rows, "truncated": truncated}


async def parse_spreadsheet(data: bytes, filename: str) -> list[dict]:
    """Parse CSV/XLSX into structured per-sheet row data for the UI table.

    Returns a list of {"name", "rows", "truncated"} — rows[0] is the header,
    cells are JSON-safe strings, capped at MAX_SHEET_ROWS/MAX_SHEET_COLS. The
    flat text from parse_file stays the source of truth for the agent; this is
    the structured preview flavor the FilePreviewDialog renders as tabs.
    """
    def _do_parse() -> list[dict]:
        import io

        import pandas as pd

        if filename.lower().endswith(".xlsx"):
            frames = pd.read_excel(io.BytesIO(data), engine="openpyxl", sheet_name=None)
        else:
            # CSV has no sheet concept — present it as a single tab.
            try:
                df = pd.read_csv(io.BytesIO(data))
            except Exception:
                # Fall back to a raw text split for weird CSV (no pandas
                # dtype guessing games for the UI).
                decoded = data.decode("utf-8", errors="replace")
                import csv as _csv

                parsed = list(_csv.reader(decoded.splitlines()))
                return [{"name": "Sheet 1", "rows": parsed[:MAX_SHEET_ROWS], "truncated": len(parsed) > MAX_SHEET_ROWS}]
            frames = {"Sheet 1": df}

        sheets = []
        for name, df in frames.items():
            sheet = _dataframe_to_sheet(df)
            sheet["name"] = str(name)
            # Skip genuinely empty sheets (no columns at all).
            if not sheet["rows"] or (len(sheet["rows"]) == 1 and sheet["rows"][0] == [""]):
                continue
            sheets.append(sheet)
        return sheets or [{"name": "Sheet 1", "rows": [["(empty file)"]], "truncated": False}]

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_do_parse),
            timeout=FILE_OP_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        msg = f"[CSV/XLSX parse timed out after {FILE_OP_TIMEOUT_SECONDS}s]"
        return [{"name": "Sheet 1", "rows": [["[parse timed out]"], [msg]], "truncated": False}]
    except Exception as e:
        logger.error(f"[file_reader] Spreadsheet parse error for {filename}: {e}")
        return [{"name": "Sheet 1", "rows": [[f"[parse error: {e}]"]], "truncated": False}]


async def parse_file(
    data: bytes,
    filename: str,
    content_type: str,
    chunk_size: int = 1500,
    original_path: str = None,
) -> FileAttachment:
    """Parse raw file bytes into a FileAttachment with text chunks."""
    # settings imported at module level — no inner re-import

    if not data:
        logger.warning(f"[file_reader] Empty file data for {filename}")
        return FileAttachment(
            filename=filename,
            content_type=content_type,
            size_bytes=0,
            chunks=["[Empty file]"],
        )

    ext = Path(filename).suffix.lower()
    overlap = getattr(settings, "localmind_chunk_overlap_tokens", 200)
    logger.info(
        f"[file_reader] Processing file: {filename}, ext: {ext}, content_type: {content_type}, size: {len(data)} bytes"
    )

    text = ""
    try:
        # S422: content-first dispatch — magic bytes decide the parser, the
        # extension is trusted only when the content has no known signature.
        sniff = _sniff_format(data)
        kind, _note = _resolve_read_kind(ext, sniff, data)
        if kind == "pdf":
            text = await _parse_pdf(data)
        elif kind == "docx":
            text = await _parse_docx(data)
        elif kind == "xlsx":
            text = await _parse_xlsx(data)
        elif kind == "csv":
            text = await _parse_csv(data)
        elif kind == "image":
            text = await _parse_image(data, filename)
        elif kind == "unsupported_ole":
            text = _ole_unsupported_text(filename)
        elif kind == "zip_ambiguous":
            text = _zip_ambiguous_text(filename)
        else:
            # Plain text / code — decode as UTF-8.  Truncation is
            # line-aware (never splits a multi-byte character mid-
            # sequence) and reports the exact line count so the model
            # can reason about the file's true size.
            try:
                text = data.decode("utf-8", errors="replace")
                if len(data) > FILE_READ_MAX_BYTES:
                    lines = text.splitlines(keepends=True)
                    truncated_lines: list[str] = []
                    byte_count = 0
                    for line in lines:
                        line_bytes = len(line.encode("utf-8"))
                        if byte_count + line_bytes > FILE_READ_MAX_BYTES:
                            break
                        truncated_lines.append(line)
                        byte_count += line_bytes
                    shown = len(truncated_lines)
                    total = len(lines)
                    text = "".join(truncated_lines)
                    truncated_kb = FILE_READ_MAX_BYTES // 1024
                    original_kb = len(data) // 1024
                    text += (
                        f"\n\n[... file truncated: showing first {shown} lines "
                        f"({truncated_kb} KB) of {total} lines "
                        f"({original_kb} KB) total. "
                        f"Use shell tool to inspect specific lines ...]"
                    )
                    logger.warning(
                        f"[file_reader] {filename}: truncated {original_kb} KB -> {truncated_kb} KB "
                        f"({shown}/{total} lines)"
                    )
            except Exception as e:
                text = f"[Could not read file: {e}]"
                logger.error(f"[file_reader] Text decode error for {filename}: {e}")

        if not text.strip():
            text = f"[File {filename} appears to be empty or contains no readable text]"

    except Exception as e:
        logger.error(f"[file_reader] Parse error for {filename}: {e}", exc_info=True)
        text = f"[File parse error: {e}]"

    try:
        chunks = _chunk_text(text, chunk_size=chunk_size, overlap=overlap)
        if not chunks:
            chunks = [text]  # Ensure at least one chunk
    except Exception as e:
        logger.error(f"[file_reader] Chunking error for {filename}: {e}")
        chunks = [text]  # Fallback to single chunk
    logger.info(f"[file_reader] parsed {filename}: {len(text)} chars → {len(chunks)} chunks")
    return FileAttachment(
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        chunks=chunks,
    )


# Readable file extensions used by the path extractor below.
# S422: .pub added — a Publisher file in a user message must resolve to a
# path so it can reach the honest unsupported_format result (previously it
# was invisible to the extractor and reported not_found).
# S422: image extensions added — the OCR parser existed but a .jpg path in a
# message never resolved ("No file found"), so the capability was unreachable
# by path reference.
_READ_EXTS = (
    r"py|js|ts|txt|md|csv|pdf|docx|xlsx|json|yaml|yml|toml|html|sh|rs|go|log"
    r"|cfg|ini|env|pub|png|jpg|jpeg|gif|bmp|webp|tiff"
)

# Ordered path patterns for pulling a file reference out of a message.
# Matches: "quoted path.ext", C:\Windows\path.ext, /unix/path.ext, ~/path, bare.ext
#
# NOTE ON ORDER: the bare pattern's char class is [\w.\\\-/] — forward slashes
# AND backslashes. A Windows absolute path (C:\Users\tison\Desktop\file.md) would
# otherwise be truncated at the backslashes down to the bare filename, then looked
# up under ~/ and cwd and never found — so a file the agent just wrote to the
# Desktop reads back as not_found (Session 264). The dedicated Windows-drive
# pattern (backslashes OR forward slashes, spaces allowed) MUST run before the
# bare pattern so the full absolute path is offered as the first candidate. The
# backslash in the bare class is what lets a WINDOWS-RELATIVE path
# (dev\test-run\notes.txt) survive whole instead of truncating to notes.txt —
# the read-back-after-write failure reproduced live on Windows (Session 325).
_PATH_PATTERNS = [
    re.compile(rf"""["']([^"'\n]+?\.(?:{_READ_EXTS}))["']""", re.IGNORECASE),
    re.compile(rf"""([A-Za-z]:[\\/][^\n\r"'<>|*?]+?\.(?:{_READ_EXTS}))""", re.IGNORECASE),
    re.compile(rf"((?:~/|\.{{0,2}}/)?[\w.\\\-/]+\.(?:{_READ_EXTS}))", re.IGNORECASE),
]


def _extract_path_candidates(message: str) -> list[str]:
    """Pull candidate file paths out of a message, most-specific first.

    Windows drive-absolute paths are yielded whole (before the bare-filename
    fallback) so a path the writer just produced can be read back on Windows.
    """
    candidates: list[str] = []
    for pat in _PATH_PATTERNS:
        for m in pat.finditer(message):
            grp = m.group(1)
            if grp not in candidates:
                candidates.append(grp)
    return candidates


async def file_task(message: str, original_path: str = None) -> ToolResult:
    """
    FILE_TASK dispatch handler — tries to locate and read a file referenced
    in the message before falling back to asking the user to attach one.

    Resolution order:
      1. original_path param (set by engine from prior upload metadata)
      2. Path extracted from the message text (quoted or bare)
      3. Prompt user to attach
    """
    from pathlib import Path as _Path

    # Try original_path first (engine passes this for files already uploaded)
    candidates: list[str] = []
    if original_path:
        candidates.append(original_path)

    candidates.extend(_extract_path_candidates(message))

    # Expand and validate each candidate
    for raw_path in candidates:
        p = _Path(raw_path).expanduser()
        if not p.is_absolute():
            # Try relative to home and cwd
            for base in (_Path.home(), _Path.cwd()):
                candidate = base / p
                if candidate.exists():
                    p = candidate
                    break
        if p.exists() and p.is_file():
            # SECURITY: Only allow reading files within user-approved folders.
            # Without this check, the agent could read ~/.ssh/id_rsa,
            # ~/.aws/credentials, /etc/passwd, or the LocalMind DB.
            if not settings.is_path_allowed(p):
                logger.warning("[file_task] blocked read of path outside allowed folders: %s", p)
                return ToolResult(
                    content=(
                        f"Access denied: '{p}' is outside the allowed folders. "
                        f"File reading is restricted to your user directories for safety."
                    ),
                    risk=RiskLevel.HIGH,
                    source="file_reader",
                    success=False,
                    error_type="permission_denied",
                    error_message=f"Path not in allowed read paths: {p}",
                )
            try:
                # S422: canonical read with cloud-placeholder recovery. A
                # Files-On-Demand placeholder raises EINVAL when the cloud
                # provider is down; without this the model burningly
                # retried via zipfile / raw reads / shell (the "find my
                # CV" transcript).
                data, cloud_diag = await _read_file_with_cloud_recovery(p)
                if data is None:
                    logger.warning(
                        "[file_task] cloud file unavailable: %s (provider_running=%s, started=%s)",
                        p, cloud_diag.get("provider_running"), cloud_diag.get("provider_started"),
                    )
                    return ToolResult(
                        content=_cloud_file_unavailable_message(p, cloud_diag),
                        risk=RiskLevel.LOW,
                        source="file_reader",
                        success=False,
                        error_type="cloud_file_unavailable",
                        error_message=(
                            f"Cloud placeholder not hydrated: {p} "
                            f"(provider_running={cloud_diag.get('provider_running')}, "
                            f"provider_started={cloud_diag.get('provider_started')})"
                        ),
                        metadata={
                            "path": str(p),
                            "filename": p.name,
                            "size_bytes": _safe_file_size(p),
                            **cloud_diag,
                        },
                    )
                ext = p.suffix.lower()
                sniff = _sniff_format(data)
                kind, note = _resolve_read_kind(ext, sniff, data)

                # ── Honest unsupported-format results ─────────────────────
                if kind in ("unsupported_ole", "zip_ambiguous"):
                    body = _ole_unsupported_text(p.name) if kind == "unsupported_ole" else _zip_ambiguous_text(p.name)
                    logger.info("[file_task] unsupported format (%s): %s", kind, p)
                    return ToolResult(
                        content=body,
                        risk=RiskLevel.LOW,
                        source="file_reader",
                        success=False,
                        error_type="unsupported_format",
                        error_message=f"{kind}: {p}",
                        metadata={
                            "path": str(p),
                            "filename": p.name,
                            "size_bytes": len(data),
                            "sniff": sniff,
                        },
                    )

                # ── Plain text / code files: line-numbered output ────────
                # Bypass the chunked parse_file() pipeline so the model
                # sees exact content, line numbers, and original formatting
                # that edit_file's search/replace can rely on.
                if kind == "text":
                    try:
                        raw_text = data.decode("utf-8")
                    except UnicodeDecodeError:
                        # Fall back to lossy decode rather than failing.
                        raw_text = data.decode("utf-8", errors="replace")

                    line_ending = _detect_line_ending(data)
                    formatted, total_lines, truncated, shown_lines = (
                        _format_with_line_numbers(raw_text, _FULL_CONTENT_MAX_BYTES)
                    )

                    header = f"File: {p}\nSize: {len(data):,} bytes\nLines: {total_lines}"
                    if line_ending == "\r\n":
                        header += "\nLine endings: CRLF (\\r\\n)"
                    if note:
                        header += f"\nNote: {note}"

                    logger.info(
                        "[file_task] read text file: %s (%d bytes, %d lines, truncated=%s)",
                        p, len(data), total_lines, truncated,
                    )
                    return ToolResult(
                        content=header + "\n\n" + formatted,
                        risk=RiskLevel.LOW,
                        source="file_reader",
                        metadata={
                            "path": str(p),
                            "filename": p.name,
                            "size_bytes": len(data),
                            "total_lines": total_lines,
                            "shown_lines": shown_lines,
                            "truncated": truncated,
                            "line_ending": "\\r\\n" if line_ending == "\r\n" else "\\n",
                            "sniff": sniff,
                            "dispatch_note": note,
                        },
                    )

                # ── Structured formats (PDF/DOCX/XLSX/CSV/images): chunked pipeline ──
                attachment = await parse_file(
                    data=data,
                    filename=p.name,
                    content_type="application/octet-stream",
                )
                # Return first chunk as tool result; engine injects full attachment separately
                preview = attachment.chunks[0] if attachment.chunks else "[empty file]"
                if len(attachment.chunks) > 1:
                    preview += f"\n\n[... {len(attachment.chunks) - 1} more chunks available]"
                if note:
                    preview = f"Note: {note}\n\n{preview}"
                logger.info("[file_task] read file from disk: %s (%d bytes)", p, len(data))
                return ToolResult(
                    content=f"File: {p}\nSize: {len(data):,} bytes\n\n{preview}",
                    risk=RiskLevel.LOW,
                    source="file_reader",
                    metadata={
                        "path": str(p),
                        "filename": p.name,
                        "chunks": len(attachment.chunks),
                        "size_bytes": len(data),
                        "sniff": sniff,
                        "dispatch_note": note,
                    },
                )
            except Exception as e:
                logger.warning("[file_task] failed to read %s: %s", p, e)
                return ToolResult(
                    content=f"Could not read {p}: {e}",
                    risk=RiskLevel.LOW,
                    source="file_reader",
                    success=False,
                    error_type="internal_error",
                    error_message=str(e),
                )

    return ToolResult(
        content=(
            "No file found. To read a file:\n"
            "- Attach it with the paperclip button in the chat\n"
            '- Or mention the full path, e.g. "read ~/Documents/notes.txt"'
        ),
        risk=RiskLevel.LOW,
        source="file_reader",
        success=False,
        error_type="not_found",
        error_message="No readable file path found in message or upload context.",
    )


# Register
register_tool(
    Intent.FILE_TASK,
    file_task,
    description="Read the TEXT CONTENTS of a single FILE (code, text, PDF, DOCX, CSV, XLSX). "
    "Do NOT use for directories or folder listings — use shell list_files for that. "
    "Requires a specific file path and a goal (read, summarise, count lines, extract tables).",
    cost=0.01,
    latency_ms=300,
)
