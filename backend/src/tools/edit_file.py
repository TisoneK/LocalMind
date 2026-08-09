"""
edit_file tool — in-place file editing with search/replace, insert, delete, append, prepend operations.

Registered as Intent.FILE_EDIT in the tool registry.

Creates a backup (.bak) before editing. Returns diff-style summaries showing
what changed. Supports both JSON payloads (from the contract layer) and
NL-style instructions (from legacy dispatch).

Actions:
  - replace:       Replace first (or all) occurrences of `search` with `replace`
  - regex_replace: Replace regex `pattern` matches with `replace`
  - insert:        Insert `insert_text` at a specific line number
  - delete:        Delete lines from `start_line` to `end_line`
  - append:        Append `insert_text` to end of file
  - prepend:       Prepend `insert_text` to beginning of file
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from core.config import settings
from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

_BACKUP_SUFFIX = ".bak"
_MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB — refuse to edit files larger than this
_MAX_DIFF_LINES = 50  # maximum lines to show in the diff summary


# ── Path resolution ───────────────────────────────────────────────────────────


def _resolve_path(raw_path: str) -> Path:
    """
    Resolve a user-supplied path to an absolute Path.

    Handles:
      - Home-relative paths (~/...)
      - Environment variables ($HOME/...)
      - Relative paths (resolved against CWD, not home)
      - Already-absolute paths
    """
    expanded = os.path.expandvars(os.path.expanduser(raw_path))
    p = Path(expanded)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


# ── Backup ─────────────────────────────────────────────────────────────────────


def _create_backup(filepath: Path) -> Path:
    """
    Create a backup of the file by copying it to {filepath}.bak.

    Returns the backup path. If the file doesn't exist or backup fails,
    logs a warning and returns the intended backup path anyway.
    """
    backup_path = filepath.parent / (filepath.name + _BACKUP_SUFFIX)
    try:
        if filepath.exists():
            shutil.copy2(filepath, backup_path)
            logger.info("[edit_file] backup created: %s", backup_path)
        else:
            logger.warning("[edit_file] cannot backup non-existent file: %s", filepath)
    except OSError as exc:
        logger.warning("[edit_file] backup failed for %s: %s", filepath, exc)
    return backup_path


# ── Diff summary ───────────────────────────────────────────────────────────────


def _diff_summary(original: str, modified: str, path: str) -> str:
    """
    Produce a simple unified-diff-style summary of changes.

    Shows up to _MAX_DIFF_LINES of context. Returns a human-readable string.
    """
    import difflib

    orig_lines = original.splitlines(keepends=True)
    mod_lines = modified.splitlines(keepends=True)

    diff = difflib.unified_diff(
        orig_lines,
        mod_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    )
    diff_lines = list(diff)

    if not diff_lines:
        return f"No changes in {path}"

    # Truncate if too many lines
    if len(diff_lines) > _MAX_DIFF_LINES:
        shown = diff_lines[:_MAX_DIFF_LINES]
        remaining = len(diff_lines) - _MAX_DIFF_LINES
        shown.append(f"... {remaining} more diff lines omitted ...\n")
        diff_lines = shown

    orig_count = len(orig_lines)
    mod_count = len(mod_lines)
    header = f"Edited: {path}\nLines: {orig_count} → {mod_count} ({mod_count - orig_count:+d})\n"
    return header + "".join(diff_lines)


def _diff_hunks(original: str, modified: str, path: str) -> list[dict]:
    """
    Produce structured diff hunks suitable for frontend rendering.

    Each hunk dict contains:
      - filePath: str
      - oldStart, oldLines, newStart, newLines: int
      - lines: list of {type, content, oldLine?, newLine?}

    This enables the frontend DiffBlock component to render green/red
    highlighted lines with line numbers — like Cursor/GitHub diffs.
    """
    import difflib

    orig_lines = original.splitlines(keepends=True)
    mod_lines = modified.splitlines(keepends=True)

    diff = difflib.unified_diff(
        orig_lines,
        mod_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
        n=3,  # 3 lines of context
    )
    diff_lines = list(diff)

    if not diff_lines:
        return []

    hunks: list[dict] = []
    current_hunk: dict | None = None
    old_line = 0
    new_line = 0

    for line in diff_lines:
        # Hunk header: @@ -oldStart,oldLines +newStart,newLines @@
        hunk_match = re.match(r"^@@@? -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if hunk_match:
            if current_hunk:
                hunks.append(current_hunk)
            old_start = int(hunk_match.group(1))
            old_count = int(hunk_match.group(2) or "1")
            new_start = int(hunk_match.group(3))
            new_count = int(hunk_match.group(4) or "1")
            current_hunk = {
                "filePath": path,
                "oldStart": old_start,
                "oldLines": old_count,
                "newStart": new_start,
                "newLines": new_count,
                "lines": [
                    {
                        "type": "hunk_header",
                        "content": line,
                        "oldLine": old_start,
                        "newLine": new_start,
                    }
                ],
            }
            old_line = old_start
            new_line = new_start
            continue

        if current_hunk is None:
            continue

        if line.startswith("+"):
            current_hunk["lines"].append(
                {
                    "type": "added",
                    "content": line[1:],
                    "newLine": new_line,
                }
            )
            new_line += 1
        elif line.startswith("-"):
            current_hunk["lines"].append(
                {
                    "type": "removed",
                    "content": line[1:],
                    "oldLine": old_line,
                }
            )
            old_line += 1
        elif line.startswith(" "):
            current_hunk["lines"].append(
                {
                    "type": "context",
                    "content": line[1:],
                    "oldLine": old_line,
                    "newLine": new_line,
                }
            )
            old_line += 1
            new_line += 1

    if current_hunk:
        hunks.append(current_hunk)

    return hunks


# ── Edit operations ────────────────────────────────────────────────────────────


def _do_replace(content: str, search: str, replace: str, replace_all: bool = False) -> str:
    """Replace occurrences of `search` with `replace`."""
    if replace_all:
        count = content.count(search)
        result = content.replace(search, replace)
        if count == 0:
            raise ValueError("Search text not found in file")
        return result
    else:
        idx = content.find(search)
        if idx == -1:
            raise ValueError("Search text not found in file")
        return content.replace(search, replace, 1)


def _do_regex_replace(content: str, pattern: str, replace: str, replace_all: bool = False) -> str:
    """Replace regex `pattern` matches with `replace`."""
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"Invalid regex pattern: {exc}")

    count = 0 if replace_all else 1
    result, n_subs = compiled.subn(replace, content, count=count)
    if n_subs == 0:
        raise ValueError("Regex pattern not found in file")
    return result


def _do_insert(content: str, insert_text: str, line: int) -> str:
    """Insert `insert_text` at line number `line` (1-based)."""
    lines = content.split("\n")
    # Clamp line number to valid range
    line = max(1, min(line, len(lines) + 1))
    # Convert to 0-based index
    idx = line - 1
    lines.insert(idx, insert_text)
    return "\n".join(lines)


def _do_delete(content: str, start_line: int, end_line: int) -> str:
    """Delete lines from `start_line` to `end_line` (1-based, inclusive)."""
    lines = content.split("\n")
    total = len(lines)
    # Clamp to valid range
    start_line = max(1, start_line)
    end_line = min(end_line, total)
    if start_line > end_line:
        raise ValueError(f"start_line ({start_line}) > end_line ({end_line})")
    # Convert to 0-based indices
    del lines[start_line - 1 : end_line]
    return "\n".join(lines)


def _do_append(content: str, insert_text: str) -> str:
    """Append `insert_text` to the end of the file."""
    if content and not content.endswith("\n"):
        content += "\n"
    content += insert_text
    return content


def _do_prepend(content: str, insert_text: str) -> str:
    """Prepend `insert_text` to the beginning of the file."""
    if not insert_text.endswith("\n"):
        insert_text += "\n"
    return insert_text + content


# ── Core edit function ─────────────────────────────────────────────────────────


def _apply_edit(
    content: str,
    action: str,
    search: str = "",
    replace: str = "",
    insert_text: str = "",
    line: int = 0,
    start_line: int = 0,
    end_line: int = 0,
    pattern: str = "",
    replace_all: bool = False,
) -> str:
    """
    Apply an edit action to the file content and return the modified content.

    Raises ValueError if the action is invalid or parameters are missing.
    """
    if action == "replace":
        if not search:
            raise ValueError("'search' parameter is required for replace action")
        return _do_replace(content, search, replace, replace_all)

    elif action == "regex_replace":
        if not pattern:
            raise ValueError("'pattern' parameter is required for regex_replace action")
        return _do_regex_replace(content, pattern, replace, replace_all)

    elif action == "insert":
        if not insert_text:
            raise ValueError("'insert_text' parameter is required for insert action")
        if line < 1:
            raise ValueError("'line' parameter must be >= 1 for insert action")
        return _do_insert(content, insert_text, line)

    elif action == "delete":
        if start_line < 1 or end_line < 1:
            raise ValueError("'start_line' and 'end_line' must be >= 1 for delete action")
        return _do_delete(content, start_line, end_line)

    elif action == "append":
        if not insert_text:
            raise ValueError("'insert_text' parameter is required for append action")
        return _do_append(content, insert_text)

    elif action == "prepend":
        if not insert_text:
            raise ValueError("'insert_text' parameter is required for prepend action")
        return _do_prepend(content, insert_text)

    else:
        raise ValueError(
            f"Unknown action '{action}'. "
            f"Valid actions: replace, regex_replace, insert, delete, append, prepend"
        )


# ── Shared no-write edit preparation (B-2026-08-02-7 / B2) ────────────────────
#
# edit_file writes the result of an edit to disk; propose_str_replace stages
# the SAME result as a proposal (no write). Both must run the identical
# validation, permission, size, and encoding gates — so they share
# prepare_edit(). Never duplicate these gates in propose_edit.py: if the
# safety rules change, they change here only.


class PreparedEdit:
    """A validated, computed file edit that has NOT been written to disk.

    Attributes:
        filepath: Resolved absolute Path of the file.
        original: The file's current content.
        modified: The content after applying the requested edit action.
    """

    __slots__ = ("filepath", "original", "modified")

    def __init__(self, filepath: Path, original: str, modified: str) -> None:
        self.filepath = filepath
        self.original = original
        self.modified = modified


def prepare_edit(
    payload: Dict[str, Any],
    source: str = "edit_file",
) -> tuple[Optional[ToolResult], Optional[PreparedEdit]]:
    """
    Validate an edit payload and compute the modified content WITHOUT
    touching disk (no backup created, nothing written).

    Shared by edit_file() (which then writes) and propose_str_replace()
    (which stages the proposal). The permission gates, size limits, and
    error messages are identical to the original edit_file flow — this is
    the single source of truth for "is this edit even allowed".

    Args:
        payload: The edit parameters (path, action, search, replace, ...).
        source:  ToolResult.source to tag error results with. Defaults to
                 "edit_file"; propose_str_replace passes its own name.

    Returns:
        (None, prepared) on success — the caller is responsible for the
        "no change" check (prepared.modified == prepared.original) and
        the actual write.
        (error_result, None) on any validation/read/apply failure — the
        returned ToolResult can be returned to the user as-is.
    """
    raw_path = payload.get("path", "")
    action = payload.get("action", "")

    if not raw_path:
        return (
            ToolResult(
                content="'path' is required for edit_file",
                risk=RiskLevel.LOW,
                source=source,
                success=False,
                error_type="validation_error",
                error_message="Missing required field 'path'",
            ),
            None,
        )

    if not action:
        return (
            ToolResult(
                content="'action' is required for edit_file",
                risk=RiskLevel.LOW,
                source=source,
                success=False,
                error_type="validation_error",
                error_message="Missing required field 'action'",
            ),
            None,
        )

    valid_actions = {"replace", "regex_replace", "insert", "delete", "append", "prepend"}
    if action not in valid_actions:
        return (
            ToolResult(
                content=f"Unknown action '{action}'. Valid: {', '.join(sorted(valid_actions))}",
                risk=RiskLevel.LOW,
                source=source,
                success=False,
                error_type="validation_error",
                error_message=f"Invalid action '{action}'",
            ),
            None,
        )

    # Resolve path
    filepath = _resolve_path(raw_path)

    # SECURITY: Only allow editing files within user-approved folders.
    # Without this check, the agent could edit ~/.ssh/authorized_keys,
    # ~/.bashrc, ~/.aws/credentials, or the LocalMind DB itself.
    if not settings.is_path_allowed(filepath):
        return (
            ToolResult(
                content=(
                    f"Access denied: '{filepath}' is outside the allowed folders. "
                    f"File editing is restricted to your user directories for safety."
                ),
                risk=RiskLevel.HIGH,
                source=source,
                success=False,
                error_type="permission_denied",
                error_message=f"Path not in allowed read paths: {filepath}",
            ),
            None,
        )

    # Check file exists
    if not filepath.exists():
        return (
            ToolResult(
                content=f"File not found: {filepath}",
                risk=RiskLevel.LOW,
                source=source,
                success=False,
                error_type="file_not_found",
                error_message=f"File does not exist: {filepath}",
            ),
            None,
        )

    # Check file is not too large
    try:
        file_size = filepath.stat().st_size
    except OSError as exc:
        return (
            ToolResult(
                content=f"Cannot stat file: {exc}",
                risk=RiskLevel.MEDIUM,
                source=source,
                success=False,
                error_type="io_error",
                error_message=str(exc),
            ),
            None,
        )

    if file_size > _MAX_FILE_SIZE:
        return (
            ToolResult(
                content=f"File too large to edit ({file_size} bytes, max {_MAX_FILE_SIZE}). "
                f"Use file_write to overwrite instead.",
                risk=RiskLevel.MEDIUM,
                source=source,
                success=False,
                error_type="file_too_large",
                error_message=f"File size {file_size} exceeds max edit size {_MAX_FILE_SIZE}",
            ),
            None,
        )

    # Read original content
    try:
        original = filepath.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            original = filepath.read_text(encoding="latin-1")
        except Exception as exc:
            return (
                ToolResult(
                    content=f"Cannot read file (encoding error): {exc}",
                    risk=RiskLevel.MEDIUM,
                    source=source,
                    success=False,
                    error_type="encoding_error",
                    error_message=str(exc),
                ),
                None,
            )
    except Exception as exc:
        return (
            ToolResult(
                content=f"Cannot read file: {exc}",
                risk=RiskLevel.MEDIUM,
                source=source,
                success=False,
                error_type="io_error",
                error_message=str(exc),
            ),
            None,
        )

    # Apply the edit (compute only — no disk write)
    try:
        modified = _apply_edit(
            content=original,
            action=action,
            search=payload.get("search", ""),
            replace=payload.get("replace", ""),
            insert_text=payload.get("insert_text", ""),
            line=int(payload.get("line", 0)),
            start_line=int(payload.get("start_line", 0)),
            end_line=int(payload.get("end_line", 0)),
            pattern=payload.get("pattern", ""),
            replace_all=bool(payload.get("all", False)),
        )
    except ValueError as exc:
        return (
            ToolResult(
                content=f"Edit failed: {exc}",
                risk=RiskLevel.LOW,
                source=source,
                success=False,
                error_type="edit_error",
                error_message=str(exc),
            ),
            None,
        )

    return None, PreparedEdit(filepath=filepath, original=original, modified=modified)


# ── Public entry point (legacy dispatch) ───────────────────────────────────────


async def edit_file(message: str) -> ToolResult:
    """
    Legacy dispatch entry point for the edit_file tool.

    Accepts a JSON string with the edit parameters. If the message is not
    valid JSON, attempts to interpret it as a natural-language instruction
    (limited support).
    """
    # Try to parse as JSON first (from contract layer or agent loop)
    try:
        payload = json.loads(message)
        if isinstance(payload, dict):
            return await _edit_from_payload(payload)
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback: attempt NL interpretation (very limited)
    return ToolResult(
        content=(
            "Could not parse edit_file instruction. Please provide a JSON payload "
            "with 'path', 'action', and the relevant parameters. "
            'Example: {"path": "file.py", "action": "replace", '
            '"search": "old", "replace": "new"}'
        ),
        risk=RiskLevel.LOW,
        source="edit_file",
        success=False,
        error_type="parse_error",
        error_message="Invalid edit_file payload — expected JSON",
    )


async def _edit_from_payload(payload: Dict[str, Any]) -> ToolResult:
    """
    Execute an edit from a parsed payload dict.

    Expected keys:
      - path (required): file path to edit
      - action (required): one of replace, regex_replace, insert, delete, append, prepend
      - search: text to search for (replace/delete actions)
      - replace: replacement text (replace/regex_replace actions)
      - insert_text: text to insert (insert/append/prepend actions)
      - line: line number for insert action
      - start_line, end_line: line range for delete action
      - pattern: regex pattern for regex_replace action
      - all: if true, replace all occurrences (default false)
    """
    error, prepared = prepare_edit(payload)
    if error is not None:
        return error

    action = payload.get("action", "")
    filepath = prepared.filepath
    original = prepared.original
    modified = prepared.modified

    # Create backup before editing (propose_str_replace skips this — it never writes)
    backup_path = _create_backup(filepath)

    # Check if anything actually changed
    if modified == original:
        return ToolResult(
            content=f"No changes made to {filepath} (edit had no effect)",
            risk=RiskLevel.LOW,
            source="edit_file",
            success=True,
        )

    # Write the modified content
    try:
        filepath.write_text(modified, encoding="utf-8")
    except Exception as exc:
        # Attempt to restore from backup
        try:
            if backup_path.exists():
                shutil.copy2(backup_path, filepath)
                logger.info("[edit_file] restored from backup after write failure")
        except Exception:
            logger.error("[edit_file] failed to restore backup after write failure!")

        return ToolResult(
            content=f"Write failed: {exc}",
            risk=RiskLevel.HIGH,
            source="edit_file",
            success=False,
            error_type="io_error",
            error_message=str(exc),
        )

    # Generate diff summary (text) and structured diff hunks (for frontend)
    summary = _diff_summary(original, modified, str(filepath))
    hunks = _diff_hunks(original, modified, str(filepath))

    orig_lines = len(original.splitlines())
    mod_lines = len(modified.splitlines())

    # Count additions/deletions from hunks
    additions = sum(1 for h in hunks for line in h.get("lines", []) if line.get("type") == "added")
    deletions = sum(1 for h in hunks for line in h.get("lines", []) if line.get("type") == "removed")

    return ToolResult(
        content=summary,
        risk=RiskLevel.LOW,
        source="edit_file",
        success=True,
        metadata={
            "path": str(filepath),
            "action": action,
            "original_lines": orig_lines,
            "modified_lines": mod_lines,
            "backup_path": str(backup_path),
            "lines_changed": abs(mod_lines - orig_lines),
            # Structured diff data for frontend DiffBlock component
            "diff_hunks": hunks,
            "diff_additions": additions,
            "diff_deletions": deletions,
            "diff_language": _infer_language(str(filepath)),
        },
    )


# ── Language inference for diff display ────────────────────────────────────────

_LANG_EXT_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".jsx": "jsx",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".sql": "sql",
    ".sh": "bash",
    ".bash": "bash",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".md": "markdown",
    ".xml": "xml",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".dart": "dart",
    ".lua": "lua",
    ".r": "r",
    ".pl": "perl",
}


def _infer_language(filepath: str) -> str:
    """Infer the programming language from a file path for diff syntax highlighting."""
    ext = Path(filepath).suffix.lower()
    return _LANG_EXT_MAP.get(ext, "")


# ── Register with tool registry ───────────────────────────────────────────────

register_tool(
    Intent.FILE_EDIT,
    edit_file,
    description="Edit an existing file in-place with search/replace, insert, delete, append, or prepend operations. Creates backups automatically.",
    cost=0.01,
    latency_ms=50,
    parallelizable=False,  # file edits are stateful — don't run concurrently
)
