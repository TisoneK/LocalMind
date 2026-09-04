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
import re
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


# ── Cloud-placeholder read failures (B-2026-09-05-1) ────────────────────────
# OneDrive Files-On-Demand placeholders: the directory entry EXISTS (so
# p.exists() passes) but the bytes live in the cloud. When the OneDrive
# provider isn't running, EVERY read fails the same way — open() → errno 22
# "Invalid argument", copies → WinError 362 "cloud file provider is not
# running" — which this tool used to surface as a generic internal_error.
# The recovery directive then nudged the model to "try a different approach",
# and a real session burned 4+ iterations on doomed retries (code_exec, shell
# Copy-Item) before the turn died. These reads are classified so the loop can
# say: no tool can read this file right now — ask the user to materialize it.
_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000

_CLOUD_PLACEHOLDER_HINT = (
    "This file is an OneDrive Files-On-Demand placeholder — its bytes are in "
    "the cloud and the sync provider is not available to fetch them. No local "
    "tool can read it right now (file_task, code_exec, and shell copies all "
    "fail identically), so do NOT retry with another tool or command. Ask the "
    "user to open the file once, or right-click it in Explorer and choose "
    "'Always keep on this device', then try again after they confirm it "
    "downloaded."
)


def _is_cloud_placeholder_file(st_result) -> bool:
    """True when a stat result carries the Files-On-Demand recall attribute.

    Windows-only signal (``st_file_attributes`` is absent elsewhere, which
    reads as False — nothing to detect on other platforms). The attribute
    alone is NOT an error: pinned-but-hydrated files carry it too and read
    fine while OneDrive is healthy, so callers still attempt the read.
    """
    attrs = getattr(st_result, "st_file_attributes", None)
    if attrs is None:
        return False
    return bool(attrs & _FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS)


def _classify_read_error(exc: OSError, has_recall_attr: bool) -> str:
    """Map a failed file read to a recovery error_type.

    winerror 362 is ERROR_CLOUD_FILE_PROVIDER_NOT_RUNNING. errno 22
    (Invalid argument) is what open() returns on a cloud placeholder whose
    provider is down — but it is ambiguous alone, so the placeholder stat
    attribute must corroborate it before we claim "cloud_placeholder".
    """
    if getattr(exc, "winerror", None) == 362:
        return "cloud_placeholder"
    if exc.errno == 22 and has_recall_attr:
        return "cloud_placeholder"
    if exc.errno == 13:
        return "permission_denied"
    return "internal_error"


# ── Binary container sniffing (B-2026-09-05-2) ──────────────────────────────
# Legacy office formats (.pub, .doc, .ppt, .xls) have no parser here, but
# they DID reach the plain-text decode path and returned mojibake garbage
# that the model then treated as the file's contents. Known container
# magics get an honest unsupported_format result instead.
_BINARY_MAGICS: tuple[tuple[bytes, str], ...] = (
    (b"PK\x03\x04", "an Open XML / ZIP-based document (docx, pptx, xlsx, or a zip archive)"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "an OLE2 compound document (e.g. .doc, .pub, .ppt, or .xls)"),
    (b"MZ", "a Windows executable"),
)


def _binary_container_sniff(data: bytes) -> str | None:
    """Return a human description when the head bytes match a known binary
    container we cannot parse; None for everything else (text or unknown)."""
    head = data[:8]
    for magic, label in _BINARY_MAGICS:
        if head.startswith(magic):
            return label
    # Heuristic: a text file's first pages are virtually never majority-NUL.
    sample = data[:4096]
    if sample and sample.count(0) > len(sample) // 2:
        return "a binary file"
    return None


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
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
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


async def _parse_csv_xlsx(data: bytes, filename: str) -> str:
    def _do_parse() -> str:
        try:
            import io

            import pandas as pd

            if filename.endswith(".xlsx"):
                df = pd.read_excel(io.BytesIO(data), engine="openpyxl")
            else:
                df = pd.read_csv(io.BytesIO(data))

            # Summary + first rows
            shape_info = f"Shape: {df.shape[0]} rows × {df.shape[1]} columns\nColumns: {', '.join(df.columns.tolist())}\n\n"  # noqa: E501
            preview = df.head(20).to_markdown(index=False)
            return shape_info + preview
        except Exception as e:
            logger.error(f"[file_reader] CSV/XLSX parse error: {e}")
            return f"[CSV/XLSX parse error: {e}]"

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_do_parse),
            timeout=FILE_OP_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return f"[CSV/XLSX parse timed out after {FILE_OP_TIMEOUT_SECONDS}s]"


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
        if ext == ".pdf" or content_type == "application/pdf":
            text = await _parse_pdf(data)
        elif ext == ".docx":
            text = await _parse_docx(data)
        elif ext in (".csv", ".xlsx"):
            text = await _parse_csv_xlsx(data, filename)
        elif ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff"):
            text = await _parse_image(data, filename)
        else:
            # Legacy/binary containers (.pub, .doc, renamed .zip, …) used to
            # hit the UTF-8 decode below and come back as mojibake chunks the
            # model treated as the file's real contents. Sniff and refuse
            # honestly instead (same guard as file_task's text path).
            container = _binary_container_sniff(data)
            if container:
                text = (
                    f"[Unsupported binary format: {filename} is {container}. "
                    "LocalMind parses PDF, DOCX, XLSX, CSV, images, and text/code — "
                    "convert the file (open it in its app and Save As PDF or DOCX) "
                    "and attach the converted copy.]"
                )
            else:
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
# Legacy office extensions (.doc/.pub/.ppt/.pptx/.xls/.xlsx) are included so
# "read my CV.pub" extracts the path — the reader then answers honestly
# (unsupported_format) instead of the message failing path extraction and
# returning the generic not_found prompt to attach a file.
_READ_EXTS = r"py|js|ts|txt|md|csv|pdf|docx|doc|pub|ppt|pptx|xlsx|xls|json|yaml|yml|toml|html|sh|rs|go|log|cfg|ini|env"

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
    re.compile(rf"""["']([^"'\n]+?\.(?:{_READ_EXTS}))["']"""),
    re.compile(rf"""([A-Za-z]:[\\/][^\n\r"'<>|*?]+?\.(?:{_READ_EXTS}))"""),
    re.compile(rf"((?:~/|\.{{0,2}}/)?[\w.\\\-/]+\.(?:{_READ_EXTS}))"),
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
            # Probe for a cloud placeholder BEFORE the read. A healthy
            # OneDrive hydrates on open and this flag costs nothing; a
            # downed provider fails the read and the flag corroborates the
            # errno-22 classification.
            try:
                has_recall = _is_cloud_placeholder_file(p.stat())
            except OSError:
                has_recall = False
            try:
                data = p.read_bytes()
            except OSError as read_err:
                err_class = _classify_read_error(read_err, has_recall)
                logger.warning(
                    "[file_task] read failed [%s]: %s: %s", err_class, p, read_err
                )
                content = f"Could not read {p}: {read_err}"
                if err_class == "cloud_placeholder":
                    content += f"\n\n{_CLOUD_PLACEHOLDER_HINT}"
                elif err_class == "permission_denied":
                    content += (
                        "\n\nThe file exists but access was denied — check its "
                        "permissions, or ask the user to move it into an allowed "
                        "folder."
                    )
                return ToolResult(
                    content=content,
                    risk=RiskLevel.LOW,
                    source="file_reader",
                    success=False,
                    error_type=err_class,
                    error_message=str(read_err),
                )
            ext = p.suffix.lower()

            try:
                # ── Plain text / code files: line-numbered output ────────
                # Bypass the chunked parse_file() pipeline so the model
                # sees exact content, line numbers, and original formatting
                # that edit_file's search/replace can rely on.
                if ext not in _SPECIAL_FORMAT_EXTS:
                    container = _binary_container_sniff(data)
                    if container:
                        logger.info(
                            "[file_task] unsupported binary format: %s (%s)", p, container
                        )
                        return ToolResult(
                            content=(
                                f"File: {p}\nSize: {len(data):,} bytes\n\n"
                                f"This is {container}, which LocalMind cannot parse yet "
                                "(supported: PDF, DOCX, XLSX, CSV, images, text/code). "
                                "Do not read it again — the bytes are binary, not text. "
                                "Tell the user which formats are supported and offer to "
                                "convert the file first (open it in its app and 'Save As' "
                                "PDF or DOCX), then read the converted copy."
                            ),
                            risk=RiskLevel.LOW,
                            source="file_reader",
                            success=False,
                            error_type="unsupported_format",
                            error_message=f"no parser for {container}",
                        )
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
                        },
                    )

                # ── Special formats (PDF, DOCX, XLSX, images): chunked pipeline ──
                attachment = await parse_file(
                    data=data,
                    filename=p.name,
                    content_type="application/octet-stream",
                )
                # Return first chunk as tool result; engine injects full attachment separately
                preview = attachment.chunks[0] if attachment.chunks else "[empty file]"
                if len(attachment.chunks) > 1:
                    preview += f"\n\n[... {len(attachment.chunks) - 1} more chunks available]"
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
