"""
Grep-like text search tool (B-2026-08-23-31).

Searches file contents for a pattern (regex or literal) without needing shell access.
Works even when the shell tool is disabled.
"""

import logging
import os
import re
from pathlib import Path

from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool

logger = logging.getLogger(__name__)

MAX_RESULTS = 50
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB — skip files larger than this
DEFAULT_ROOTS = [Path.home()]

_SKIP_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".next", ".cache",
    ".localmind", "LocalMind", "dist", "build",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
})

_SKIP_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico",
    ".mp3", ".mp4", ".wav", ".avi", ".mov",
    ".zip", ".tar", ".gz", ".7z", ".rar",
    ".db", ".sqlite", ".sqlite3",
    ".pyc", ".pyo", ".o", ".a", ".so", ".dylib", ".dll",
    ".woff", ".woff2", ".ttf", ".eot",
    ".bin", ".exe",
})


async def grep_search(message: str) -> ToolResult:
    """Search file contents for a pattern.

    Format: "<pattern>" or "<pattern> in <path>"
    Options (appended):
    - case:i  — case insensitive (default: case sensitive)
    - max:N   — max results (default: 50)
    - glob:*.py — only search files matching glob
    """
    import fnmatch

    # Parse pattern and path
    path_part = None
    pattern = message.strip().strip('"').strip("'")
    options = {}

    # Extract options from the message
    for opt in ["case:i", "case:s"]:
        if opt in message.lower():
            options["case"] = "i" if "case:i" in message.lower() else "s"
            pattern = pattern.replace(opt, "").strip()

    for prefix in ["max:", "limit:"]:
        idx = pattern.lower().find(prefix)
        if idx >= 0:
            rest = pattern[idx + len(prefix):]
            num_match = re.match(r'(\d+)', rest)
            if num_match:
                options["max"] = int(num_match.group(1))
                pattern = pattern[:idx] + rest[len(num_match.group(1)):].strip()

    for prefix in ["glob:", "ext:"]:
        idx = pattern.lower().find(prefix)
        if idx >= 0:
            rest = pattern[idx + len(prefix):]
            glob_match = re.match(r'([^\s]+)', rest)
            if glob_match:
                options["glob"] = glob_match.group(1)
                pattern = pattern[:idx] + rest[len(glob_match.group(1)):].strip()

    # Extract path ("pattern in /path/to/dir")
    in_match = re.search(r'\s+in\s+(.+)$', pattern)
    if in_match:
        path_part = in_match.group(1).strip()
        pattern = pattern[:in_match.start()].strip()

    pattern = pattern.strip().strip('"').strip("'")

    if not pattern:
        return ToolResult(
            content="No search pattern provided. Use: \"<pattern>\" or \"<pattern> in <path>\"",
            risk=RiskLevel.LOW,
            source="grep_search",
        )

    # Determine search roots
    roots = []
    if path_part:
        p = Path(os.path.expanduser(path_part))
        if p.is_file():
            roots = [p]
        elif p.is_dir():
            roots = [p]
        else:
            return ToolResult(
                content=f"Path not found: {path_part}",
                risk=RiskLevel.LOW,
                source="grep_search",
                success=False,
                error_type="not_found",
                error_message=f"Path not found: {path_part}",
            )
    else:
        roots = DEFAULT_ROOTS[:]

    flags = re.IGNORECASE if options.get("case") == "i" else 0
    max_results = options.get("max", MAX_RESULTS)
    file_glob = options.get("glob")

    try:
        compiled = re.compile(pattern, flags)
    except re.error as e:
        return ToolResult(
            content=f"Invalid regex pattern: {e}",
            risk=RiskLevel.LOW,
            source="grep_search",
            success=False,
            error_type="invalid_input",
            error_message=str(e),
        )

    results = []
    total_files_scanned = 0

    try:
        for root in roots:
            if root.is_file():
                _search_file(root, compiled, max_results - len(results), results)
                total_files_scanned += 1
                if len(results) >= max_results:
                    break
                continue

            for dirpath, dirnames, filenames in os.walk(root):
                # Skip excluded directories
                dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
                for fname in filenames:
                    if file_glob and not fnmatch.fnmatch(fname, file_glob):
                        continue
                    ext = Path(fname).suffix.lower()
                    if ext in _SKIP_EXTENSIONS:
                        continue
                    fpath = Path(dirpath) / fname
                    total_files_scanned += 1
                    try:
                        fsize = fpath.stat().st_size
                        if fsize > MAX_FILE_SIZE:
                            continue
                    except OSError:
                        continue
                    _search_file(fpath, compiled, max_results - len(results), results)
                    if len(results) >= max_results:
                        break
                if len(results) >= max_results:
                    break
    except PermissionError:
        pass

    if not results:
        return ToolResult(
            content=f"No matches found for '{pattern}' in {total_files_scanned} files.",
            risk=RiskLevel.LOW,
            source="grep_search",
        )

    # Format results
    match_word = "es" if len(results) != 1 else ""
    lines = [
        f"Found {len(results)} match{match_word} for '{pattern}' "
        f"in {total_files_scanned} files:"
    ]
    current_file = None
    for fpath, line_no, line_text in results:
        rel = fpath
        try:
            rel = fpath.relative_to(Path.home())
        except ValueError:
            pass
        if rel != current_file:
            current_file = rel
            lines.append(f"\n{rel}")
        # Truncate long lines
        display_line = line_text.rstrip()[:200]
        lines.append(f"  {line_no}: {display_line}")

    return ToolResult(
        content="\n".join(lines),
        risk=RiskLevel.LOW,
        source="grep_search",
        metadata={"matches": len(results), "files_scanned": total_files_scanned},
    )


def _search_file(fpath: Path, pattern: re.Pattern, remaining: int, results: list):
    """Search a single file for the pattern and append matches."""
    if remaining <= 0:
        return
    try:
        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, 1):
                if pattern.search(line):
                    results.append((fpath, i, line))
                    remaining -= 1
                    if remaining <= 0:
                        return
    except (OSError, UnicodeDecodeError):
        pass


register_tool(
    Intent.GREP_SEARCH,
    grep_search,
    description=(
        'Search file contents for a text pattern (regex supported). Works without shell. '
        'Format: "<pattern>" or "<pattern> in <path>". Options: case:i (insensitive), '
        "max:N (limit results), glob:*.py (file filter). Returns matching lines with "
        "file paths and line numbers."
    ),
    cost=0.02,
    latency_ms=500,
    parallelizable=False,
)
