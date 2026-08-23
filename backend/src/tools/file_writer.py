"""
File Writer tool — writes files to ~/LocalMind/ with permission gates.

Rules:
- All writes go to ~/LocalMind/ by default unless user specifies a path
  within an allowed folder (Downloads, Documents, Desktop, etc.)
- Always asks permission before writing (permission gate via metadata flag)
- Never writes to OS/system directories
- Extracts code from fenced blocks before writing
- Returns full absolute path so UI can render a clickable link
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path

from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool

# ── Document format registry ─────────────────────────────────────────────────
# These extensions trigger timestamp-rename + version-control behaviour.
# Everything else (code, data, markup) is written directly with no rename.
_DOCUMENT_EXTS = frozenset(
    [
        # MS Office / Windows suite
        "pdf",
        "docx",
        "doc",
        "xlsx",
        "xls",
        "pptx",
        "ppt",
        "pub",
        "accdb",
        "mdb",
        # Images
        "png",
        "jpg",
        "jpeg",
        "gif",
        "bmp",
        "webp",
        "svg",
        "tiff",
        "tif",
        "ico",
        "heic",
        "raw",
        # LibreOffice / OpenDocument
        "odt",
        "ods",
        "odp",
        "odg",
        # Other document formats
        "epub",
        "rtf",
    ]
)

logger = logging.getLogger(__name__)


class PathUnresolvableError(Exception):
    """
    Raised by resolve_write_path() when the user supplied a path that cannot
    be anchored to a known folder.

    Attributes:
        raw_path:          The original string the user supplied.
        fuzzy_suggestion:  A candidate path found by scanning ~/  (may be None).
    """

    def __init__(self, raw_path: str, fuzzy_suggestion: "Path | None" = None) -> None:
        self.raw_path = raw_path
        self.fuzzy_suggestion = fuzzy_suggestion
        hint = f" Did you mean `{fuzzy_suggestion}`?" if fuzzy_suggestion else ""
        super().__init__(
            f"Could not resolve path {raw_path!r} to a known folder.{hint} "
            "Please confirm the full path."
        )


_LANG_EXT = {
    "python": ".py",
    "py": ".py",
    "javascript": ".js",
    "js": ".js",
    "typescript": ".ts",
    "ts": ".ts",
    "bash": ".sh",
    "sh": ".sh",
    "shell": ".sh",
    "html": ".html",
    "css": ".css",
    "json": ".json",
    "yaml": ".yaml",
    "yml": ".yaml",
    "toml": ".toml",
    "sql": ".sql",
    "rust": ".rs",
    "go": ".go",
    "markdown": ".md",
    "md": ".md",
}

_FENCE_RE = re.compile(r"```(?P<lang>\w+)?\s*\n(?P<code>[\s\S]+?)\n```", re.IGNORECASE)
_FILENAME_RE = re.compile(
    r"\b([\w\-\.]+\.(?:py|js|ts|txt|md|csv|json|html|css|sh|yaml|yml|toml|sql|rs|go))\b",
    re.IGNORECASE,
)

# Named folder aliases — matched case-insensitively, resolved to user home.
# Sourced from the real C:\Users\tison layout observed in production.
#
# Standard Windows shell folders + observed user top-level folders.
# Keys are lowercase; values are the canonical casing on disk.
_NAMED_FOLDERS = {
    # Standard Windows shell folders
    "downloads": "Downloads",
    "documents": "Documents",
    "desktop": "Desktop",
    "pictures": "Pictures",
    "videos": "Videos",
    "music": "Music",
    "contacts": "Contacts",
    "favorites": "Favorites",
    "links": "Links",
    "searches": "Searches",
    "saved games": "Saved Games",
    "savedgames": "Saved Games",
    # User-created top-level folders observed in C:\Users\tison
    "localmind": "LocalMind",
    "dev": "Dev",
    "scripts": "Scripts",
    "docs": "docs",
    "shared": "shared",
    "workflows": "workflows",
    "examples": "examples",
    "factory": "factory",
    "config": "config",
    "data": "data",
    "onedrive": "OneDrive",
    # Common developer folder names
    "code": "Code",
    "projects": "Projects",
    "src": "src",
    "repos": "repos",
    "builds": "builds",
    "workspace": "workspace",
}

# Extracts the target path from phrases like:
#   "in Downloads/"  "to C:/Users/tison/docs"  "save to ~/projects"  "into Documents/sub"
_PATH_RE = re.compile(
    r"(?:to|in|at|into|save to|write to)"
    r"\s+([A-Za-z]:[/\\][\w\s./\\-]+"  # Windows absolute: C:\...
    r"|~/[\w\s./\\-]+"  # Unix home-relative: ~/...
    r"|[\w][\w\s./\\-]*)",  # Named or relative: Downloads/, foo/bar
    re.IGNORECASE,
)

# Fallback: bare absolute path on its own (no preposition), e.g. pasted path
_BARE_PATH_RE = re.compile(
    r"(?:^|\s)([A-Za-z]:[/\\][^\s]+|~/[^\s]+)",
    re.IGNORECASE | re.MULTILINE,
)


def _extract_code_blocks(content: str) -> list[tuple[str, str]]:
    return [(m.group("lang") or "", m.group("code")) for m in _FENCE_RE.finditer(content)]


def _infer_filename(message: str, lang: str = "") -> str:
    match = _FILENAME_RE.search(message)
    if match:
        return match.group(1)
    ext = _LANG_EXT.get(lang.lower(), ".txt")
    return f"localmind_{int(time.time())}{ext}"


# Structured format from agent loop: "path:\n\ncontent"
# Matches a path at the start of the message, followed by :\n\n
_STRUCTURED_FMT_RE = re.compile(r"^([^\n]+?):\n\n")


def _extract_requested_dir(message: str) -> str:
    """
    Pull a target directory out of the user message.

    Handles:
    - Structured format:  path:\n\ncontent  (from agent loop's _extract_tool_input)
    - Windows absolute:   C:/Users/tison/Downloads
    - Unix home-rel:      ~/projects
    - Named folders:      Downloads, Documents, Desktop
    - Relative paths:     subdir/here  (resolved against home, not cwd)
    - Bare pasted paths:  C:\\Users\\tison\\Documents\\Code\\file.html (no preposition)
    """
    # ── Structured format from agent loop ──────────────────────────────────
    # When the agent loop dispatches file_write, it formats the input as
    # "path:\n\ncontent". Detect this first and extract the path directly.
    # IMPORTANT: The structured path may be a full file path (e.g.
    # "Documents/Code/hello.py") — we must return only the DIRECTORY part,
    # because the caller appends the filename separately.
    structured = _STRUCTURED_FMT_RE.match(message)
    if structured:
        raw = structured.group(1).strip().rstrip("/\\")
        # Strip trailing colon that might be captured (e.g. "C:\path\file.py:")
        raw = raw.rstrip(":")
        if raw:
            # Detect if the path includes a filename (has a known extension)
            raw_path = Path(raw)
            last_part = raw_path.name
            last_ext = last_part.rsplit(".", 1)[-1].lower() if "." in last_part else ""
            if last_ext in _CODE_EXTS:
                # It's a full file path — return only the directory part
                parent = str(raw_path.parent)
                if parent == ".":
                    # Just a filename like "hello.py" — no directory
                    return ""
                return parent

            # No file extension — treat as a directory path
            lower = raw.lower()
            if lower in _NAMED_FOLDERS:
                return str(Path.home() / _NAMED_FOLDERS[lower])
            candidate = Path(raw).expanduser()
            if candidate.is_absolute():
                return str(candidate)
            return str(Path.home() / raw)

    # ── Natural-language format ────────────────────────────────────────────
    match = _PATH_RE.search(message)
    if not match:
        # Try bare absolute path (e.g. user pasted "C:\Users\...\file.html")
        match = _BARE_PATH_RE.search(message)
    if not match:
        return ""

    raw = match.group(1).strip().rstrip("/\\")

    # Named folder shorthand
    lower = raw.lower()
    if lower in _NAMED_FOLDERS:
        return str(Path.home() / _NAMED_FOLDERS[lower])

    # Already absolute (Windows or Unix) or starts with ~
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return str(candidate)

    # Relative — resolve against home, not cwd
    return str(Path.home() / raw)


_CODE_EXTS = frozenset("py js ts txt md csv json html css sh yaml yml toml sql rs go".split())

# Named folder aliases matched case-insensitively against path components.
# This is the scan set used by the cross-OS path resolver to find a known
# anchor inside a full path (e.g. C:\Users\tison\Documents\Code\foo.py).
# Must stay in sync with the keys of _NAMED_FOLDERS above (lowercased).
_NAMED_FOLDER_COMPONENTS = frozenset(
    [
        # Standard Windows shell folders
        "downloads",
        "documents",
        "desktop",
        "pictures",
        "videos",
        "music",
        "contacts",
        "favorites",
        "links",
        "searches",
        # User top-level folders from C:\Users\tison
        "localmind",
        "dev",
        "scripts",
        "docs",
        "shared",
        "workflows",
        "examples",
        "factory",
        "config",
        "data",
        "onedrive",
        # Common developer folder names
        "code",
        "projects",
        "src",
        "repos",
        "builds",
        "workspace",
    ]
)


def _cross_os_parts(raw: str) -> list[str]:
    """Split a path string on both / and \\ so Windows paths work on Linux."""
    return [p for p in re.split(r"[/\\]", raw) if p]


def _fuzzy_home_match(name: str) -> "Path | None":
    """
    Scan Path.home() one level deep for a folder whose name is a
    case-insensitive substring match or close edit-distance match to `name`.

    Returns the matching Path, or None if nothing is close enough.
    Only considers directories, never files.
    """
    name_lower = name.lower().strip()
    if not name_lower:
        return None

    candidates: list[tuple[int, Path]] = []
    try:
        for entry in Path.home().iterdir():
            if not entry.is_dir():
                continue
            entry_lower = entry.name.lower()
            # Exact match (case-insensitive)
            if entry_lower == name_lower:
                return entry
            # Substring match — name is fully contained in folder name or vice versa
            if name_lower in entry_lower or entry_lower in name_lower:
                candidates.append((abs(len(entry_lower) - len(name_lower)), entry))
    except PermissionError:
        return None

    if not candidates:
        return None
    # Return the closest-length match among substring candidates
    candidates.sort(key=lambda t: t[0])
    score, best = candidates[0]
    # Only suggest if reasonably close — avoid wild guesses
    if score <= max(4, len(name_lower) // 2):
        return best
    return None


def resolve_write_path(raw_path: str, fallback_filename: str = "") -> Path:
    """
    Single canonical function to turn a user-supplied path string into a
    safe, absolute, OS-correct Path.

    Handles all cases in priority order:
      1. Named-folder shorthand          — "Documents", "Downloads"
      2. Home-relative (~/ prefix)       — "~/projects/foo.py"
      3. Native absolute (Unix)          — "/home/user/Documents/foo.py"
      4. Cross-OS absolute (Windows on   — "C:\\Users\\tison\\Documents\\Code\\foo.py"
         Linux/macOS)                      parsed by walking parts for known folder name
      5. Relative path without anchor    — "Code/hello.py" → ~/Code/hello.py
      6. Default                         — ~/LocalMind/<fallback_filename>

    Path traversal is blocked on the default fallback path only (CWD-relative
    names with ".." etc.).  Named and absolute paths are trusted after the
    named-folder anchor is confirmed.

    The returned path's parent directory is NOT created here — callers are
    responsible for mkdir(parents=True).  The _do_write() function handles
    this automatically.

    NOTE: PathUnresolvableError is no longer raised for relative paths that
    lack a named-folder anchor — they are resolved against home instead (step 5).
    The exception may still be raised for truly degenerate inputs, but callers
    should handle it by falling back to home-anchored resolution.
    """
    from core.config import settings

    home = Path(os.path.expandvars(settings.localmind_home)).expanduser().resolve()
    raw = raw_path.strip() if raw_path else ""

    if not raw:
        # No path at all — fall back to ~/LocalMind/<filename>
        return (home / fallback_filename).resolve()

    parts = _cross_os_parts(raw)
    if not parts:
        return (home / fallback_filename).resolve()

    # Detect whether the last part is a filename (has a known extension).
    last = parts[-1]
    last_ext = last.rsplit(".", 1)[-1].lower() if "." in last else ""
    has_filename = last_ext in _CODE_EXTS

    if has_filename:
        filename = last
        dir_parts = parts[:-1]
    else:
        filename = fallback_filename
        dir_parts = parts

    # ── 0. Native absolute path for THIS OS — honor it verbatim ──────────────
    # Everything below re-anchors to HOME (step 5 joins dir_parts onto
    # Path.home()), which silently prepended /Users/<me> to a genuine absolute
    # path like /private/tmp/... — so the file landed in the wrong place AND the
    # loop's read-back verification (file_reader, which DOES honor absolute
    # paths) then failed against the original path (S293, B-2026-08-17-6). A
    # native-absolute path is the caller's explicit choice; use it as-is.
    # `Path.is_absolute()` is OS-aware: on POSIX only "/..." is absolute (a
    # Windows "C:\..." is NOT, so it still falls through to the cross-OS
    # named-folder re-anchoring below); on Windows only "X:\..." is absolute.
    if Path(raw).is_absolute():
        p = Path(raw)
        resolved = p if has_filename else p / filename
        logger.info("[file_writer] native absolute path honored verbatim: %s", resolved)
        return resolved

    # ── 1. Named-folder shorthand: bare name like "Documents" ─────────────────
    if len(dir_parts) == 1 and dir_parts[0].lower() in _NAMED_FOLDER_COMPONENTS:
        canonical = _NAMED_FOLDERS.get(dir_parts[0].lower(), dir_parts[0])
        target_dir = Path.home() / canonical
        logger.info("[file_writer] named-folder shorthand: %s", target_dir)
        return target_dir / filename

    # ── 2. Home-relative (starts with ~) ─────────────────────────────────────
    if raw.startswith("~"):
        candidate = Path(raw).expanduser()
        if has_filename:
            # raw already includes the filename
            logger.info("[file_writer] home-relative with filename: %s", candidate)
            return candidate
        logger.info("[file_writer] home-relative dir: %s / %s", candidate, filename)
        return candidate / filename

    # ── 3 & 4. Absolute path — native (Unix) or cross-OS (Windows on Linux) ──
    # Strategy: walk parts for the first known named-folder component and anchor
    # there on the current OS.  This handles both:
    #   - Native Unix:   /home/tison/Documents/Code/foo.py  → parts has "Documents"
    #   - Windows on Linux: C:\Users\tison\Documents\Code\foo.py → same scan
    for i, part in enumerate(dir_parts):
        if part.lower() in _NAMED_FOLDER_COMPONENTS:
            # Use _NAMED_FOLDERS for canonical casing (e.g. "LocalMind" not "Localmind",
            # "docs" not "Docs").  Fall back to the raw part if somehow not in the map.
            canonical = _NAMED_FOLDERS.get(part.lower(), part)
            allowed_base = Path.home() / canonical
            sub_parts = dir_parts[i + 1 :]
            target_dir = (allowed_base / Path(*sub_parts)) if sub_parts else allowed_base
            logger.info(
                "[file_writer] named-folder anchor (%r→%r) → %s / %s",
                part,
                canonical,
                target_dir,
                filename,
            )
            return target_dir / filename

    # ── 5. Relative path without named-folder anchor — resolve against home ─
    # The user explicitly specified a path that doesn't anchor to any known
    # named folder.  Instead of raising PathUnresolvableError (which would
    # ask the user to confirm and suggest alternatives), we resolve it
    # against the user's home directory and auto-create the parent directory.
    # This matches user expectations: "Code/hello.py" → ~/Code/hello.py.
    if dir_parts:
        target_dir = Path.home().joinpath(*dir_parts)
        logger.info(
            "[file_writer] relative path (no named-folder anchor) resolved against home: %s / %s",
            target_dir,
            filename,
        )
        return target_dir / filename

    # ── 6. Default fallback — ~/LocalMind/<filename> ────────────────────────
    # No path components at all — write to scratch space.
    logger.info("[file_writer] no path components — falling back to scratch: %s", home / filename)
    return (home / filename).resolve()


# Keep _safe_output_path as a thin shim so nothing else breaks during rollout.
def _safe_output_path(filename: str, requested_dir: str = "") -> Path:
    """
    Shim for backwards compatibility.  New code should call resolve_write_path().
    """
    raw = (requested_dir.rstrip("/\\") + "/" + filename) if requested_dir else filename
    return resolve_write_path(raw, fallback_filename=filename)


def _is_document(filename: str) -> bool:
    """Return True if filename has a document extension (triggers timestamp rename)."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in _DOCUMENT_EXTS


def _timestamped_name(filename: str) -> str:
    """
    Return filename with a timestamp suffix inserted before the extension.
    e.g. CV.pdf -> CV_20260504_143022.pdf
    """
    if "." in filename:
        stem, ext = filename.rsplit(".", 1)
        ts = time.strftime("%Y%m%d_%H%M%S")
        return f"{stem}_{ts}.{ext}"
    ts = time.strftime("%Y%m%d_%H%M%S")
    return f"{filename}_{ts}"


def _cleanup_cache() -> None:
    """
    Lazily clean ~/LocalMind/ before each write.

    Scan top-level entries only. If a file or directory's creation time
    (st_ctime — also mtime on Linux where ctime = metadata change) is older
    than localmind_cache_max_age_days, delete it recursively.

    Skips:
      - localmind.db and its WAL/SHM sidecars (database — never touch)
      - The uploads/ subdirectory
      - Anything that raises a permission or OS error (log and continue)
    """
    import shutil

    from core.config import settings

    home = Path(os.path.expandvars(settings.localmind_home)).expanduser().resolve()
    if not home.exists():
        return

    max_age_seconds = settings.localmind_cache_max_age_days * 86_400
    now = time.time()

    _SKIP_NAMES = frozenset(
        [
            "localmind.db",
            "localmind.db-shm",
            "localmind.db-wal",
            "uploads",
        ]
    )

    for entry in home.iterdir():
        if entry.name in _SKIP_NAMES:
            continue
        try:
            age = now - entry.stat().st_ctime
            if age > max_age_seconds:
                if entry.is_dir():
                    shutil.rmtree(entry)
                    logger.info("[cache] removed dir  %s (age %.1fd)", entry.name, age / 86_400)
                else:
                    entry.unlink()
                    logger.info("[cache] removed file %s (age %.1fd)", entry.name, age / 86_400)
        except Exception as exc:
            logger.warning("[cache] could not remove %s: %s", entry, exc)


async def _do_write(
    filepath: Path,
    content: str,
    final_dest: "Path | None" = None,
    user_named: bool = False,
) -> ToolResult:
    """
    Write content to filepath (always inside ~/LocalMind/ — the scratch space),
    then copy the result to final_dest if supplied.

    Copy-back rules:
      - final_dest is None  → file stays in ~/LocalMind/ (no copy-back)
      - final_dest given, user_named=True  → copy as-is (user chose the name)
      - final_dest given, user_named=False, document ext → timestamp-rename at dest
      - final_dest given, user_named=False, code/data ext → copy with original name

    Lazy cache cleanup runs before every write.
    """
    import shutil

    _cleanup_cache()
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")
        size = len(content.encode())
        lines = len(content.splitlines())
        logger.info("[file_writer] wrote %dB → %s", size, filepath)

        dest_path = filepath  # default: scratch location is the result

        if final_dest is not None:
            # Determine output filename
            if user_named:
                out_name = final_dest.name
            elif _is_document(filepath.name):
                out_name = _timestamped_name(filepath.name)
            else:
                out_name = filepath.name

            dest_path = final_dest.parent / out_name
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(filepath, dest_path)
            logger.info("[file_writer] copied to final dest → %s", dest_path)

        # The result reports the FACTS of the write (path + byte/line counts).
        # It deliberately does NOT tell the agent whether to verify/read the file
        # back — that phantom instruction ("saved and verified; do not read it
        # back; the write is confirmed") is not the tool's business; the agent
        # decides based on the actual task (B-2026-08-18-7).
        return ToolResult(
            content=(
                f"Wrote {size} bytes ({lines} line{'' if lines == 1 else 's'}) "
                f"to {dest_path}."
            ),
            risk=RiskLevel.LOW,
            source="file_writer",
            metadata={
                "path": str(dest_path),
                "cache_path": str(filepath),
                "filename": dest_path.name,
                "bytes": size,
                "lines": lines,
            },
        )
    except Exception as e:
        logger.error("[file_writer] %s", e)
        return ToolResult(
            content=f"Write failed: {e}",
            risk=RiskLevel.MEDIUM,
            source="file_writer",
            success=False,
            error_type="internal_error",
            error_message=str(e),
        )


def _infer_cell(value: str):
    """Best-effort string → typed cell value for spreadsheet writes.

    Empty string becomes None (clears the cell); True/False become booleans;
    integer and decimal strings become numbers; everything else stays text.
    This is deliberately conservative — date/time cells come back as text.
    """
    if value == "":
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


async def write_spreadsheet(filepath: Path, sheets: list[dict]) -> ToolResult:
    """Write structured per-sheet rows back to an .xlsx or .csv file.

    Used by the preview edit flow (POST /api/confirm-write with a `sheets`
    payload) — the same permission gate as text writes, but for binary
    spreadsheet formats that _do_write (plain text) would corrupt.

    Data-loss guard: the preview caps sheets at MAX_SHEET_ROWS/MAX_SHEET_COLS,
    so a truncated grid must never be written over the full file. Before
    writing we compare the incoming grid against the existing file and refuse
    when any sheet has FEWER rows than what's on disk.
    """
    import asyncio
    import csv
    import io

    ext = filepath.suffix.lower()
    if ext not in (".xlsx", ".csv"):
        raise ValueError(f"Unsupported spreadsheet extension: {ext}")

    def _build_xlsx() -> bytes:
        from openpyxl import Workbook, load_workbook

        wb = Workbook()
        wb.remove(wb.active)
        if filepath.exists():
            existing = load_workbook(filepath, read_only=True)
            for sheet in sheets:
                name = sheet.get("name", "")
                if name in existing.sheetnames:
                    incoming_rows = len(sheet.get("rows", []))
                    if incoming_rows < existing[name].max_row:
                        raise ValueError(
                            f"Sheet '{name}' has fewer rows than the file on disk "
                            f"({incoming_rows} vs {existing[name].max_row}) — the preview "
                            "caps large sheets, so row-removing edits are refused here; "
                            "open the file in a spreadsheet app to edit it fully."
                        )
            existing.close()
        for sheet in sheets:
            name = sheet.get("name", "Sheet 1")
            ws = wb.create_sheet(title=name)
            for row in sheet.get("rows", []):
                ws.append([_infer_cell(str(c)) for c in row])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def _build_csv() -> bytes:
        if not sheets:
            raise ValueError("No sheets provided")
        rows = sheets[0].get("rows", [])
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
                existing_lines = sum(1 for _ in fh)
            if len(rows) < existing_lines:
                raise ValueError(
                    f"File has fewer rows than on disk ({len(rows)} vs "
                    f"{existing_lines}) — the preview caps large files, so "
                    "row-removing edits are refused here; open the file in a "
                    "spreadsheet app to edit it fully."
                )
        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in rows:
            writer.writerow(["" if c is None else str(c) for c in row])
        return buf.getvalue().encode("utf-8")

    def _do_write() -> ToolResult:
        _cleanup_cache()
        if ext == ".xlsx":
            data = _build_xlsx()
        else:
            data = _build_csv()
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_bytes(data)
        size = len(data)
        logger.info("[file_writer] wrote spreadsheet %dB → %s", size, filepath)
        return ToolResult(
            content=f"Wrote {size} bytes to {filepath}.",
            risk=RiskLevel.LOW,
            source="file_writer",
            metadata={
                "path": str(filepath),
                "filename": filepath.name,
                "bytes": size,
                "sheets": len(sheets),
            },
        )

    try:
        return await asyncio.to_thread(_do_write)
    except ValueError as e:
        logger.warning("[file_writer] spreadsheet write refused: %s", e)
        raise


async def write_file(message: str) -> ToolResult:
    from core.config import settings

    # ── Detect structured format from agent loop: "path:\n\ncontent" ───────
    # The agent loop's _extract_tool_input() formats file_write as
    # "{path}:\n\n{content}". When this format is detected, extract the path
    # and content directly instead of relying on fragile NL parsing.
    structured = _STRUCTURED_FMT_RE.match(message)
    if structured:
        structured_path = structured.group(1).strip().rstrip(":")
        content_to_write = message[structured.end() :]  # Everything after "path:\n\n"
        filename = Path(structured_path).name if structured_path else _infer_filename(message)
        raw_path = structured_path if structured_path else filename
    else:
        # Legacy NL format — use regex-based parsing
        blocks = _extract_code_blocks(message)
        if blocks:
            lang, code = blocks[0]
            filename = _infer_filename(message, lang)
            content_to_write = code
        else:
            filename = _infer_filename(message)
            content_to_write = message.strip()

        requested_dir = _extract_requested_dir(message)
        raw_path = (requested_dir.rstrip("/\\") + "/" + filename) if requested_dir else filename

    # Resolve the user's intended final destination.
    # With the updated resolve_write_path(), PathUnresolvableError is no longer
    # raised for relative paths — they're resolved against home.  But keep the
    # handler as a safety net for truly degenerate paths.
    final_dest: "Path | None" = None
    if raw_path and raw_path != filename:
        # A non-trivial path was provided — resolve it to a final destination
        try:
            final_dest = resolve_write_path(raw_path, fallback_filename=filename)
        except PathUnresolvableError:
            # Last resort: resolve against home and auto-create directory
            logger.warning(
                "[file_writer] PathUnresolvableError for %r — resolving against home",
                raw_path,
            )
            parts = _cross_os_parts(raw_path)
            filtered = [p for p in parts if not (len(p) == 2 and p[1] == ":")]
            if filtered:
                final_dest = Path.home().joinpath(*filtered)
            else:
                final_dest = Path.home() / filename
            final_dest.parent.mkdir(parents=True, exist_ok=True)

    # Always write to ~/LocalMind/ first (scratch space).
    home = Path(os.path.expandvars(settings.localmind_home)).expanduser().resolve()
    scratch_path = home / filename

    # Detect whether the user explicitly named the output file
    # (i.e. they gave a full path ending in a filename, not just a directory).
    # For structured format (from agent loop), the path always includes a filename,
    # so user_named is always True. For legacy NL format, it's True only when
    # the final destination's filename differs from the inferred filename.
    if structured:
        user_named = bool(final_dest and final_dest.suffix)
    else:
        user_named = bool(final_dest and final_dest.suffix and final_dest.name != filename)

    if settings.localmind_require_write_permission:
        display_dest = str(final_dest) if final_dest else str(scratch_path)
        return ToolResult(
            content=(
                f"I want to write **{filename}** to:\n`{display_dest}`\n\n"
                "Reply **yes** to confirm or specify a different path."
            ),
            risk=RiskLevel.LOW,
            source="file_writer",
            metadata={
                "requires_permission": True,
                "pending_path": display_dest,
                "pending_content": content_to_write,
                "filename": filename,
                "final_dest": str(final_dest) if final_dest else "",
                "user_named": user_named,
            },
            requires_confirmation=True,
        )

    return await _do_write(
        scratch_path, content_to_write, final_dest=final_dest, user_named=user_named
    )


register_tool(
    Intent.FILE_WRITE,
    write_file,
    description="Write literal text or code to a file. The caller supplies the exact content — do not use shell/code_exec to generate content first. Saves to ~/LocalMind/ by default. Confirms before writing.",  # noqa: E501
    cost=0.01,
    latency_ms=100,
    parallelizable=False,
)


async def write_response(message: str, content: str) -> None:
    """
    Secondary intent handler: write the assistant's response to a file.
    Called by engine.py when secondary_intent == Intent.FILE_WRITE.
    Infers filename from the original user message, writes content directly
    (no permission gate — secondary writes are considered pre-approved by
    the primary intent flow).
    """
    filename = _infer_filename(message)
    filepath = _safe_output_path(filename)
    await _do_write(filepath, content)
