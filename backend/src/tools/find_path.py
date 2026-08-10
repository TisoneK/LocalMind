"""
Find Path tool — name-match search for files AND folders, path-only output.

Why this exists (Session 124/125): the agent, asked to "check git status on
the localmind repo", ran `dir C:\\Users\\tison` — dumping the ENTIRE home
directory into context (~2K tokens of noise, plus a 20K+ prompt downstream)
when it only needed to locate one folder. The existing shell `find_files`
action searches by FILE TYPE (`*.py`), not by name, and can't match
directories. A narrow find-by-name tool makes the output size bounded BY
CONSTRUCTION: it returns only matching paths, capped, never a full listing.

Design contract (from the Session 124 design discussion):
- SEARCH, DON'T BROWSE: returns only entries whose name matches the pattern.
  Never returns a full directory listing.
- BOUNDED: max_depth and max_results caps prevent slow traversals and output
  floods (the exact failure mode of `dir C:\\Users\\tison`).
- PATH-ONLY: output is a small list of matching paths — a handful of tokens,
  not the 22K-token flood a raw dir produced.
- SKIPS heavy directories (node_modules, .git, __pycache__, …) so a home-dir
  search doesn't crawl the world.

Registered as Intent.FIND_PATH in the tool registry.
"""

from __future__ import annotations

import fnmatch
import json
import logging
from pathlib import Path

from core.config import settings
from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool

logger = logging.getLogger(__name__)

# Bounds — hard caps that make output size predictable.
_DEFAULT_MAX_DEPTH = 4
_DEFAULT_MAX_RESULTS = 10
_HARD_MAX_DEPTH = 8
_HARD_MAX_RESULTS = 25

# Directories never worth descending into during a name search. Searching a
# home directory for "localmind" must not crawl node_modules/.git/__pycache__
# (that's how a "simple find" becomes a 10-second traversal).
_HEAVY_DIR_NAMES = frozenset(
    {
        "node_modules",
        ".git",
        ".svn",
        ".hg",
        "__pycache__",
        ".cache",
        ".gradle",
        ".idea",
        ".vscode",
        ".next",
        ".nuxt",
        "venv",
        ".venv",
        "env",
        "site-packages",
        "dist",
        "build",
        "target",
        "Pods",
    }
)


def _matches(name: str, pattern: str) -> bool:
    """Case-insensitive substring or fnmatch match against a name."""
    pattern_l = pattern.lower().strip()
    if not pattern_l:
        return False
    if any(ch in pattern_l for ch in "*?["):
        return fnmatch.fnmatch(name.lower(), pattern_l)
    return pattern_l in name.lower()


def _search(root: Path, pattern: str, max_depth: int, max_results: int) -> list[Path]:
    """Walk root (bounded by depth + result caps) returning matching paths."""
    matches: list[Path] = []
    # Iterative DFS with explicit depth tracking (os.walk can't cap depth easily).
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack and len(matches) < max_results:
        current, depth = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name.lower())
        except (PermissionError, OSError):
            continue
        for entry in entries:
            if len(matches) >= max_results:
                break
            # Security (Session 125 review): never follow symlinks — a symlink
            # inside the search root could point OUTSIDE the allowed folders
            # (e.g. ~/Library junctions on macOS) and leak paths past the
            # is_path_allowed root check. Skipping them keeps the walk inside
            # the boundary the caller approved.
            try:
                if entry.is_symlink():
                    continue
                is_dir = entry.is_dir()
            except OSError:
                continue
            # Skip heavy directories entirely (never descend, never match).
            if is_dir and entry.name in _HEAVY_DIR_NAMES:
                continue
            if _matches(entry.name, pattern):
                matches.append(entry)
            if is_dir and depth < max_depth:
                stack.append((entry, depth + 1))
    return matches[:max_results]


def _clamp(value, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


async def find_path(message: str) -> ToolResult:
    """
    FIND_PATH dispatch — find files/folders whose NAME matches a pattern.

    Args (JSON-encoded from the agent loop, mirroring git/delegate):
        name:       substring or glob pattern to match (required)
        root:       directory to search under (default: user home)
        max_depth:  recursion depth cap (default 4, max 8)
        max_results: result cap (default 10, max 25)
    """
    try:
        if message.strip().startswith("{"):
            args = json.loads(message)
        else:
            # Legacy plain-string form: treat as the name pattern.
            args = {"name": message.strip()}
    except json.JSONDecodeError as exc:
        return ToolResult(
            content=f"Could not parse find_path arguments: {exc}",
            risk=RiskLevel.LOW,
            source="find_path",
            success=False,
            error_type="invalid_input",
            error_message=str(exc),
        )

    pattern = str(args.get("name", "")).strip()
    if not pattern:
        return ToolResult(
            content="find_path requires a 'name' pattern to search for.",
            risk=RiskLevel.LOW,
            source="find_path",
            success=False,
            error_type="invalid_input",
            error_message="missing 'name'",
        )

    raw_root = str(args.get("root", "")).strip()
    root = Path(raw_root).expanduser() if raw_root else Path.home()
    if not root.exists():
        return ToolResult(
            content=f"Root path '{root}' does not exist.",
            risk=RiskLevel.LOW,
            source="find_path",
            success=False,
            error_type="not_found",
            error_message=f"root {root} missing",
        )
    # SECURITY: mirror file_task — never search outside user-approved folders.
    if not settings.is_path_allowed(root):
        logger.warning("[find_path] blocked search outside allowed folders: %s", root)
        return ToolResult(
            content=(
                f"Access denied: '{root}' is outside the allowed folders. "
                "Searching is restricted to your user directories for safety."
            ),
            risk=RiskLevel.HIGH,
            source="find_path",
            success=False,
            error_type="permission_denied",
            error_message=f"root not in allowed paths: {root}",
        )

    max_depth = _clamp(args.get("max_depth"), _DEFAULT_MAX_DEPTH, 1, _HARD_MAX_DEPTH)
    max_results = _clamp(args.get("max_results"), _DEFAULT_MAX_RESULTS, 1, _HARD_MAX_RESULTS)

    try:
        matches = _search(root, pattern, max_depth, max_results)
    except Exception as exc:  # noqa: BLE001 — tool must never raise
        logger.error("[find_path] search error under %s: %s", root, exc)
        return ToolResult(
            content=f"Search error under {root}: {exc}",
            risk=RiskLevel.LOW,
            source="find_path",
            success=False,
            error_type="internal_error",
            error_message=str(exc),
        )

    if not matches:
        return ToolResult(
            content=f"No files or folders matching '{pattern}' found under {root}.",
            risk=RiskLevel.LOW,
            source="find_path",
            metadata={"matches": 0, "root": str(root)},
        )

    truncated = len(matches) >= max_results
    lines = [
        f"Found {len(matches)} match(es) for '{pattern}' under {root}:",
    ]
    for m in matches:
        kind = "📁" if m.is_dir() else "📄"
        lines.append(f"  {kind}  {m}")
    if truncated:
        lines.append(f"  … more matches exist (capped at {max_results})")
    lines.append(f"(depth cap {max_depth}, result cap {max_results})")

    return ToolResult(
        content="\n".join(lines),
        risk=RiskLevel.LOW,
        source="find_path",
        metadata={"matches": len(matches), "root": str(root), "truncated": truncated},
    )


register_tool(
    Intent.FIND_PATH,
    find_path,
    description=(
        "Find files OR folders whose NAME matches a pattern (substring or glob, "
        "case-insensitive) under a root directory. Returns only matching paths, "
        "capped (default 10, max 25) with a depth cap (default 4, max 8). Use this "
        "to LOCATE a file or folder by name — do NOT use dir/ls to hunt for "
        "something; that dumps the whole listing into context."
    ),
    cost=0.0,
    latency_ms=150,
    parallelizable=True,
)
