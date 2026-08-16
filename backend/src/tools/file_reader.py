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
            # Plain text / code - decode as UTF-8 with a hard size cap to prevent
            # context overflow. Files larger than FILE_READ_MAX_BYTES are truncated
            # with a notice so the model knows content was cut.
            try:
                raw = data[:FILE_READ_MAX_BYTES]
                text = raw.decode("utf-8", errors="replace")
                if len(data) > FILE_READ_MAX_BYTES:
                    truncated_kb = FILE_READ_MAX_BYTES // 1024
                    original_kb = len(data) // 1024
                    text += (
                        f"\n\n[... file truncated: showing first {truncated_kb} KB "
                        f"of {original_kb} KB total. Use shell tool to inspect specific lines ...]"
                    )
                    logger.warning(
                        f"[file_reader] {filename}: truncated {original_kb} KB -> {truncated_kb} KB"
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
_READ_EXTS = r"py|js|ts|txt|md|csv|pdf|docx|xlsx|json|yaml|yml|toml|html|sh|rs|go|log|cfg|ini|env"

# Ordered path patterns for pulling a file reference out of a message.
# Matches: "quoted path.ext", C:\Windows\path.ext, /unix/path.ext, ~/path, bare.ext
#
# NOTE ON ORDER: the bare Unix pattern's char class is [\w.\-/] — forward slash
# ONLY. A Windows absolute path (C:\Users\tison\Desktop\file.md) would otherwise
# be truncated at the backslashes down to the bare filename, then looked up under
# ~/ and cwd and never found — so a file the agent just wrote to the Desktop reads
# back as not_found (Session 264). The dedicated Windows-drive pattern (backslashes
# OR forward slashes, spaces allowed) MUST run before the Unix pattern so the full
# absolute path is offered as the first candidate.
_PATH_PATTERNS = [
    re.compile(rf"""["']([^"'\n]+?\.(?:{_READ_EXTS}))["']"""),
    re.compile(rf"""([A-Za-z]:[\\/][^\n\r"'<>|*?]+?\.(?:{_READ_EXTS}))"""),
    re.compile(rf"((?:~/|\.{{0,2}}/)?[\w.\-/]+\.(?:{_READ_EXTS}))"),
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
                data = p.read_bytes()
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
                    metadata={"path": str(p), "filename": p.name, "chunks": len(attachment.chunks)},
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
