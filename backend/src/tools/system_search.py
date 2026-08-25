"""
System Search tool — the unified Local Search Intelligence front door.

Feature: system-search-tool (Session 400, user pitch 2026-08-25).

WHY this exists: LocalMind could answer "what is the capital of France" but
not "where is my LocalMind project?", "where did I save that CV I edited last
week?", "do I have multiple copies of this document?", "find the largest
files on my computer", or "where is the program I use to edit PDFs?" — the
model had to improvise with find_path (name search only), sysinfo (apps via
keyword routing), observe (recent files, 60-minute window, 8-file cap) or
raw shell (`du`, `ls -R` — the exact context-flood pattern Sessions 124/125
fixed for name search).

This tool is the "Local Search Interface" of the Local Search Intelligence
capability: ONE entry point, six deterministic sub-capabilities, NORMALIZED
results. The search primitives FIND; the Parent agent UNDERSTANDS, ranks and
PRESENTS (that split is the architecture — the model never crawls the disk).

Operations (JSON "operation" field, default "files"):
  files       — name/pattern discovery for files AND folders (reuses the
                find_path walk machinery: same matching semantics — substring,
                glob, {a,b} braces, unordered multi-token AND).
  recent      — files modified in the last N days under a root, mtime-ranked
                ("what did I work on recently?"). Supersedes observe's
                8-file/60-minute/single-root snapshot for search questions.
  largest     — size-ranked top-N files ("find the largest files").
  duplicates  — same name+size in multiple locations ("do I have multiple
                copies of this document?"), ranked by wasted bytes.
  apps        — installed-application discovery (Windows registry / macOS
                Applications+brew / Linux dpkg+rpm) PLUS PATH executables
                ("do I have VS Code installed?", "where is python?").
  open_with   — which installed application handles a file extension
                ("what program can open this .psd file?").

Contracts (inherited from find_path/observe hard lessons):
  - SECURITY: every root must pass ``settings.is_path_allowed``; symlinks are
    never followed; heavy dirs (node_modules, .git, …) are skipped entirely;
    open_with paths are path-gated too (no existence oracle outside allowed
    roots).
  - BOUNDED BY CONSTRUCTION: time-budgeted walks (default 2.5s files /
    4s stat walks, hard max 10s), 250k entry cap, result page cap (default
    10, hard max 25), heap-bounded memory for recent/largest.
  - HONEST: ``walk_complete`` + ``scanned`` are reported in metadata AND in
    the human content; a partial scan never claims "no results exist".
  - NORMALIZED: every row is {type, path, name, size, modified, detail} in
    metadata["results"] so the Parent presents without parsing prose.
  - NEVER RAISES: every failure degrades to a ToolResult(success=False).

Parent-only scope (ADR-53): this is a TOOL of the Parent agent. No
specialist agent, no delegation, no child agents.

Registered as Intent.SYSTEM_SEARCH.
"""

from __future__ import annotations

import datetime
import heapq
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from core.config import settings
from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool
from tools.find_path import _HEAVY_DIR_NAMES, _matches, _parse_exts, _walk_catalog

logger = logging.getLogger(__name__)

# ── Bounds ───────────────────────────────────────────────────────────────────
_DEFAULT_LIMIT = 10
_HARD_LIMIT = 25
_DEFAULT_BUDGET_FILES_MS = 2500   # matches find_path default
_DEFAULT_BUDGET_STAT_MS = 4000    # stat walks (recent/largest/duplicates)
_HARD_BUDGET_MS = 10000
_MAX_SCANNED = 250_000            # pathological-tree safety net (find_path parity)
_DEFAULT_DAYS = 7
_HARD_DAYS = 365
_MAX_DUP_GROUPS = 25              # duplicates: groups returned, hard cap
_MAX_APPS_SHOWN = 25

_OPERATIONS = ("files", "recent", "largest", "duplicates", "apps", "open_with")

# B-2026-08-25-1: when the tool is called with a PLAIN string (not JSON) — which
# is what weak models do, especially after the shell→system_search redirect
# hands them "operation='largest'" — recognise a leading operation keyword so
# "largest /Users/x", "recent", "duplicates *.jpg", "apps python" run the right
# op instead of being treated as a filename search for the word "largest".
_OP_SYNONYMS: dict[str, str] = {
    "largest": "largest", "biggest": "largest", "large": "largest", "big": "largest",
    "recent": "recent", "recently": "recent", "latest": "recent", "newest": "recent",
    "duplicate": "duplicates", "duplicates": "duplicates", "dupes": "duplicates", "dup": "duplicates",
    "app": "apps", "apps": "apps", "application": "apps", "applications": "apps",
    "installed": "apps", "program": "apps", "programs": "apps",
    "openwith": "open_with", "open_with": "open_with", "opens": "open_with",
    "file": "files", "files": "files", "find": "files", "locate": "files", "search": "files",
}


def _looks_like_path(tok: str) -> bool:
    tc = tok.strip("\"'")
    return tc.startswith("/") or tc.startswith("~") or bool(re.match(r"^[A-Za-z]:[\\/]", tc))


def _parse_plain_query(text: str) -> dict:
    """Turn a plain (non-JSON) system_search input into structured args.

    Leading operation keyword → that op, with a path-like token as `root` and
    the remaining words as `query`. No leading keyword → a files name search
    (the original behaviour), so genuine name lookups like "README" still work.
    """
    toks = text.split()
    op = _OP_SYNONYMS.get(toks[0].lower()) if toks else None
    if not op:
        return {"operation": "files", "query": text.strip()}
    args: dict = {"operation": op}
    query_terms: list[str] = []
    for t in toks[1:]:
        tc = t.strip("\"'")
        if tc in ("*", "**", "."):  # glob-all / here → no filter
            continue
        if _looks_like_path(tc):
            args["root"] = tc
        else:
            query_terms.append(tc)
    if query_terms:
        args["query"] = " ".join(query_terms)
    return args

# open_with: last-resort extension → candidate application-name fragments,
# matched against the installed-programs list (and PATH). Not a registry —
# a graceful fallback when the platform lookup is unavailable.
_EXT_APP_HINTS: dict[str, tuple[str, ...]] = {
    "pdf": ("adobe", "acrobat", "edge", "chrome", "foxit", "sumatra", "preview", "okular", "evince"),
    "psd": ("photoshop", "gimp", "krita", "affinity"),
    "ai": ("illustrator", "inkscape", "affinity"),
    "doc": ("word", "libreoffice", "pages", "wps"),
    "docx": ("word", "libreoffice", "pages", "wps"),
    "xls": ("excel", "libreoffice", "numbers", "wps"),
    "xlsx": ("excel", "libreoffice", "numbers", "wps"),
    "ppt": ("powerpoint", "libreoffice", "keynote", "wps"),
    "pptx": ("powerpoint", "libreoffice", "keynote", "wps"),
    "py": ("code", "pycharm", "idle", "python", "sublime", "vim", "neovim"),
    "js": ("code", "webstorm", "sublime", "node"),
    "ts": ("code", "webstorm", "sublime"),
    "rs": ("rust", "code"),
    "go": ("goland", "code", "go"),
    "png": ("photos", "gimp", "preview", "xnview", "irfanview", "paint"),
    "jpg": ("photos", "gimp", "preview", "xnview", "irfanview", "paint"),
    "jpeg": ("photos", "gimp", "preview", "xnview", "irfanview", "paint"),
    "mp4": ("vlc", "media player", "quicktime", "mpv", "films"),
    "mp3": ("vlc", "media player", "itunes", "music", "audacity", "spotify"),
    "zip": ("7-zip", "7zip", "winrar", "archive", "unzip"),
    "rar": ("winrar", "7-zip", "7zip", "unrar"),
}

# Common CLI aliases for app-discovery from PATH ("do I have VS Code?" — the
# binary is `code`). Only consulted when the query names a well-known app.
_APP_CLI_ALIASES: dict[str, tuple[str, ...]] = {
    "vs code": ("code", "code-insiders"),
    "vscode": ("code", "code-insiders"),
    "visual studio code": ("code", "code-insiders"),
    "python": ("python3", "python"),
    "node": ("node",),
    "nodejs": ("node",),
    "npm": ("npm", "npx"),
    "git": ("git",),
    "docker": ("docker",),
    "chrome": ("google-chrome", "chrome"),
    "firefox": ("firefox",),
    "edge": ("microsoft-edge", "msedge"),
    "brave": ("brave",),
    "vlc": ("vlc",),
    "gimp": ("gimp",),
    "blender": ("blender",),
}


def _clamp(value, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _fmt_size(n: int | float | None) -> str:
    """Human-readable byte size (B → KB → MB → GB)."""
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        n = 0.0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(n)} {unit}"
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


def _fmt_mtime(ts: float | None) -> str:
    if not ts:
        return ""
    try:
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return ""


# ── Security-gated root resolution ───────────────────────────────────────────


def _resolve_root(raw: str) -> tuple[Path | None, ToolResult | None]:
    """Resolve + security-gate the search root. Returns (root, error_result)."""
    root = Path(raw).expanduser() if raw.strip() else Path.home()
    if not root.exists():
        return None, ToolResult(
            content=f"Root path '{root}' does not exist.",
            risk=RiskLevel.LOW,
            source="system_search",
            success=False,
            error_type="not_found",
            error_message=f"root {root} missing",
        )
    if not settings.is_path_allowed(root):
        logger.warning("[system_search] blocked search outside allowed folders: %s", root)
        return None, ToolResult(
            content=(
                f"Access denied: '{root}' is outside the allowed folders. "
                "Searching is restricted to your user directories for safety."
            ),
            risk=RiskLevel.HIGH,
            source="system_search",
            success=False,
            error_type="permission_denied",
            error_message=f"root not in allowed paths: {root}",
        )
    return root, None


# ── Stat walker (recent / largest / duplicates) ─────────────────────────────


def _stat_walk(
    root: Path,
    budget_ms: int,
    max_depth: int = 8,
) -> tuple[list[tuple[Path, int, float]], int, bool]:
    """Walk root collecting (path, size, mtime) for FILES within budget.

    Same traversal policy as find_path's _walk_catalog (symlinks skipped,
    heavy dirs skipped, sorted iteration) but stats every file so the caller
    can rank by size or mtime. Returns (entries, scanned, complete) — the
    entry list itself is NOT result-capped (callers heap-trim per-operation
    to keep memory bounded: recent/largest keep top-N, duplicates groups).
    """
    entries: list[tuple[Path, int, float]] = []
    scanned = 0
    deadline = time.monotonic() + (budget_ms / 1000.0)
    stack: list[tuple[Path, int]] = [(root, 0)]
    complete = True
    while stack:
        if time.monotonic() >= deadline:
            complete = False
            break
        current, depth = stack.pop()
        try:
            children = sorted(current.iterdir(), key=lambda p: p.name.lower())
        except (PermissionError, OSError):
            continue
        for entry in children:
            scanned += 1
            if scanned >= _MAX_SCANNED:
                complete = False
                break
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if entry.name not in _HEAVY_DIR_NAMES and depth < max_depth:
                        stack.append((entry, depth + 1))
                    continue
                st = entry.stat()
            except (PermissionError, OSError):
                continue
            entries.append((entry, st.st_size, st.st_mtime))
        if not complete:
            break
    return entries, scanned, complete


def _entry_matches(path: Path, query: str, exts: set[str] | None) -> bool:
    """Filter a stat-walk entry by optional name query + extension set."""
    if exts and path.suffix.lstrip(".").lower() not in exts:
        return False
    q = (query or "").strip()
    if not q:
        return True
    # Reuse find_path's matching semantics (tokens AND, glob, braces).
    return _matches(path.name, q)


# ── Operation: files (name discovery — find_path parity, normalized) ────────


def _op_files(args: dict) -> ToolResult:
    query = str(args.get("query", "") or args.get("name", "")).strip()
    if not query:
        return ToolResult(
            content="system_search files requires a 'query' (name pattern).",
            risk=RiskLevel.LOW,
            source="system_search",
            success=False,
            error_type="invalid_input",
            error_message="missing 'query' for files operation",
        )
    raw_root = str(args.get("root", "")).strip()
    root, err = _resolve_root(raw_root)
    if err:
        return err

    max_depth = _clamp(args.get("max_depth"), 4, 1, 8)
    limit = _clamp(args.get("limit"), _DEFAULT_LIMIT, 1, _HARD_LIMIT)
    offset = max(0, _clamp(args.get("offset"), 0, 0, 1_000_000))
    budget_ms = _clamp(args.get("budget_ms"), _DEFAULT_BUDGET_FILES_MS, 100, _HARD_BUDGET_MS)
    kind = str(args.get("kind", "") or "").strip().lower()
    if kind not in ("file", "dir"):
        kind = ""
    exts = _parse_exts(str(args.get("ext", "") or ""))

    try:
        matches, scanned, complete, total_matches = _walk_catalog(
            root, query, max_depth, budget_ms, _MAX_SCANNED
        )
        # Weak-model tolerance (Session 400 live trace): models pass noun
        # phrases ("LocalMind project") as the query. Multi-token AND
        # matching finds 0 (no file is named that). Fall back to the
        # longest single token and SAY SO — never silently return nothing
        # when a relaxed match exists.
        relaxed_note = ""
        if total_matches == 0 and len(query.split()) > 1:
            tokens = sorted(query.split(), key=len, reverse=True)
            for tok in tokens:
                if len(tok) < 3:
                    continue
                m2, s2, c2, t2 = _walk_catalog(
                    root, tok, max_depth, budget_ms, _MAX_SCANNED
                )
                if t2 > 0:
                    matches, scanned, complete, total_matches = m2, s2, c2, t2
                    relaxed_note = (
                        f"No exact match for '{query}'; showing matches for "
                        f"'{tok}' instead — narrow the query for precision."
                    )
                    break
    except Exception as exc:  # noqa: BLE001 — tool must never raise
        logger.error("[system_search] files walk error under %s: %s", root, exc)
        return ToolResult(
            content=f"Search error under {root}: {exc}",
            risk=RiskLevel.LOW,
            source="system_search",
            success=False,
            error_type="internal_error",
            error_message=str(exc),
        )

    # In-memory narrowing (no re-traversal), same policy as find_path.
    filtered = []
    for m in matches:
        try:
            if kind == "file" and not m.is_file():
                continue
            if kind == "dir" and not m.is_dir():
                continue
        except OSError:
            continue
        if exts and m.suffix.lstrip(".").lower() not in exts:
            continue
        filtered.append(m)
    total = len(filtered)
    page = filtered[offset : offset + limit]

    results = []
    for p in page:
        try:
            st = p.stat()
            results.append(
                {
                    "type": "dir" if p.is_dir() else "file",
                    "path": str(p),
                    "name": p.name,
                    "size": st.st_size,
                    "modified": st.st_mtime,
                }
            )
        except OSError:
            results.append({"type": "file", "path": str(p), "name": p.name, "size": 0, "modified": 0.0})

    lines = [f"Found {total:,} file/folder match(es) for '{query}' under {root}:"]
    if relaxed_note:
        lines.append(f"  ({relaxed_note})")
    for r in results:
        icon = "📁" if r["type"] == "dir" else "📄"
        size = f" · {_fmt_size(r['size'])}" if r["type"] == "file" else ""
        when = f" · {_fmt_mtime(r['modified'])}" if r.get("modified") else ""
        lines.append(f"  {icon}  {r['path']}{size}{when}")
    if offset + len(page) < total:
        lines.append(f"  … {total - offset - len(page):,} more (offset={offset + len(page)} to continue)")
    completeness = (
        "scan complete" if complete else
        "scan PARTIAL (time budget) — narrow the root or raise budget_ms to search deeper"
    )
    lines.append(f"Catalog: {total:,} shown of {total_matches:,} walked · scanned {scanned:,} entries · {completeness}")

    return ToolResult(
        content="\n".join(lines),
        risk=RiskLevel.LOW,
        source="system_search",
        metadata={
            "operation": "files",
            "total": total,
            "offset": offset,
            "truncated": offset + len(page) < total,
            "scanned": scanned,
            "walk_complete": complete,
            "results": results,
        },
    )


# ── Operation: recent ───────────────────────────────────────────────────────


def _op_recent(args: dict) -> ToolResult:
    raw_root = str(args.get("root", "")).strip()
    root, err = _resolve_root(raw_root)
    if err:
        return err
    # B-2026-08-25-1 live finding: models pass `minutes` (e.g. 120) — parse it
    # instead of silently falling back to the 7-day default with a wrong label.
    # Explicit minutes win over the days DEFAULT (both explicit = the more
    # specific unit, minutes, decides the window).
    minutes_raw = args.get("minutes")
    minutes = 0
    try:
        minutes = int(float(minutes_raw)) if minutes_raw is not None else 0
    except (TypeError, ValueError):
        minutes = 0
    minutes = max(0, min(minutes, _HARD_DAYS * 1440))
    if minutes > 0:
        days = minutes / 1440.0
        window_label = f"last {minutes} minute(s)"
    else:
        days = _clamp(args.get("days"), _DEFAULT_DAYS, 1, _HARD_DAYS)
        window_label = f"last {days} day(s)"
    limit = _clamp(args.get("limit"), _DEFAULT_LIMIT, 1, _HARD_LIMIT)
    budget_ms = _clamp(args.get("budget_ms"), _DEFAULT_BUDGET_STAT_MS, 100, _HARD_BUDGET_MS)
    query = str(args.get("query", "") or "").strip()
    exts = _parse_exts(str(args.get("ext", "") or ""))
    cutoff = time.time() - days * 86400.0

    try:
        entries, scanned, complete = _stat_walk(root, budget_ms)
    except Exception as exc:  # noqa: BLE001
        logger.error("[system_search] recent walk error under %s: %s", root, exc)
        return ToolResult(
            content=f"Search error under {root}: {exc}",
            risk=RiskLevel.LOW,
            source="system_search",
            success=False,
            error_type="internal_error",
            error_message=str(exc),
        )

    # Keep only the newest `limit` (min-heap on mtime — memory stays tiny
    # even when the walk sees tens of thousands of in-window files).
    heap: list[tuple[float, str, int]] = []
    in_window = 0
    for path, size, mtime in entries:
        if mtime < cutoff:
            continue
        if not _entry_matches(path, query, exts):
            continue
        in_window += 1
        item = (mtime, str(path), size)
        if len(heap) < limit:
            heapq.heappush(heap, item)
        elif mtime > heap[0][0]:
            heapq.heapreplace(heap, item)

    ranked = sorted(heap, key=lambda t: -t[0])
    results = [
        {
            "type": "file",
            "path": p,
            "name": Path(p).name,
            "size": size,
            "modified": mtime,
        }
        for mtime, p, size in ranked
    ]

    lines = [f"Files modified in the {window_label} under {root} ({in_window:,} in window, newest {len(results)}):"]
    for r in results:
        lines.append(
            f"  🕒 {_fmt_mtime(r['modified'])} · {_fmt_size(r['size'])} · {r['path']}"
        )
    if not results:
        lines.append("  (no matching files in the window)")
    completeness = "scan complete" if complete else "scan PARTIAL (time budget) — narrow the root or raise budget_ms"
    lines.append(f"Scanned {scanned:,} entries · {completeness}")
    if query or exts:
        lines.append(f"Filter: name~'{query or '*'}'" + (f" · ext {sorted(exts)}" if exts else ""))

    return ToolResult(
        content="\n".join(lines),
        risk=RiskLevel.LOW,
        source="system_search",
        metadata={
            "operation": "recent",
            "days": round(days, 4),
            "minutes": minutes or None,
            "total": in_window,
            "returned": len(results),
            "truncated": in_window > len(results),
            "scanned": scanned,
            "walk_complete": complete,
            "results": results,
        },
    )


# ── Operation: largest ──────────────────────────────────────────────────────


def _op_largest(args: dict) -> ToolResult:
    raw_root = str(args.get("root", "")).strip()
    root, err = _resolve_root(raw_root)
    if err:
        return err
    limit = _clamp(args.get("limit"), _DEFAULT_LIMIT, 1, _HARD_LIMIT)
    budget_ms = _clamp(args.get("budget_ms"), _DEFAULT_BUDGET_STAT_MS, 100, _HARD_BUDGET_MS)
    query = str(args.get("query", "") or "").strip()
    exts = _parse_exts(str(args.get("ext", "") or ""))

    try:
        entries, scanned, complete = _stat_walk(root, budget_ms)
    except Exception as exc:  # noqa: BLE001
        logger.error("[system_search] largest walk error under %s: %s", root, exc)
        return ToolResult(
            content=f"Search error under {root}: {exc}",
            risk=RiskLevel.LOW,
            source="system_search",
            success=False,
            error_type="internal_error",
            error_message=str(exc),
        )

    heap: list[tuple[int, str]] = []
    for path, size, _mtime in entries:
        if size <= 0:
            continue
        if not _entry_matches(path, query, exts):
            continue
        item = (size, str(path))
        if len(heap) < limit:
            heapq.heappush(heap, item)
        elif size > heap[0][0]:
            heapq.heapreplace(heap, item)

    ranked = sorted(heap, key=lambda t: -t[0])
    results = [
        {"type": "file", "path": p, "name": Path(p).name, "size": size, "modified": None}
        for size, p in ranked
    ]

    total_bytes = sum(size for size, _ in ranked)
    lines = [f"Largest files under {root} (top {len(results)}, {_fmt_size(total_bytes)} combined):"]
    for i, r in enumerate(results, 1):
        lines.append(f"  {i}. {_fmt_size(r['size']):>10}  {r['path']}")
    if not results:
        lines.append("  (no files matched)")
    completeness = (
        "scan complete" if complete else
        "scan PARTIAL (time budget) — sizes shown are only from the scanned portion; "
        "narrow the root or raise budget_ms for a fuller picture"
    )
    lines.append(f"Scanned {scanned:,} entries · {completeness}")

    return ToolResult(
        content="\n".join(lines),
        risk=RiskLevel.LOW,
        source="system_search",
        metadata={
            "operation": "largest",
            "returned": len(results),
            "truncated": False,
            "scanned": scanned,
            "walk_complete": complete,
            "results": results,
        },
    )


# ── Operation: duplicates ───────────────────────────────────────────────────


def _op_duplicates(args: dict) -> ToolResult:
    raw_root = str(args.get("root", "")).strip()
    root, err = _resolve_root(raw_root)
    if err:
        return err
    limit = _clamp(args.get("limit"), _DEFAULT_LIMIT, 1, _HARD_LIMIT)
    budget_ms = _clamp(args.get("budget_ms"), _DEFAULT_BUDGET_STAT_MS, 100, _HARD_BUDGET_MS)
    query = str(args.get("query", "") or "").strip()
    exts = _parse_exts(str(args.get("ext", "") or ""))

    try:
        entries, scanned, complete = _stat_walk(root, budget_ms)
    except Exception as exc:  # noqa: BLE001
        logger.error("[system_search] duplicates walk error under %s: %s", root, exc)
        return ToolResult(
            content=f"Search error under {root}: {exc}",
            risk=RiskLevel.LOW,
            source="system_search",
            success=False,
            error_type="internal_error",
            error_message=str(exc),
        )

    # Group by (lowercase name, size). Same name+size is a strong duplicate
    # signal without hashing petabytes; a hash pass is a later phase.
    groups: dict[tuple[str, int], list[str]] = {}
    for path, size, _mtime in entries:
        if not _entry_matches(path, query, exts):
            continue
        key = (path.name.lower(), size)
        groups.setdefault(key, []).append(str(path))
    dup_groups = [
        (name, size, paths) for (name, size), paths in groups.items() if len(paths) > 1
    ]
    # Rank by wasted bytes: size × (copies − 1).
    dup_groups.sort(key=lambda g: -(g[1] * (len(g[2]) - 1)))
    dup_groups = dup_groups[: min(_MAX_DUP_GROUPS, max(limit, 10))]

    results = []
    wasted_total = 0
    for name, size, paths in dup_groups:
        wasted = size * (len(paths) - 1)
        wasted_total += wasted
        results.append(
            {
                "type": "duplicate_group",
                "name": name,
                "size": size,
                "copies": len(paths),
                "paths": paths,
                "wasted_bytes": wasted,
            }
        )

    lines = []
    if results:
        lines.append(
            f"Found {len(results)} file(s) stored in multiple locations under {root} "
            f"(≈{_fmt_size(wasted_total)} reclaimable):"
        )
        for r in results:
            lines.append(
                f"  ⧉ {r['name']} · {_fmt_size(r['size'])} each · {r['copies']} copies"
            )
            for p in r["paths"]:
                lines.append(f"      {p}")
    else:
        lines.append(f"No duplicate files (same name + size) found under {root}.")
    completeness = (
        "scan complete" if complete else
        "scan PARTIAL (time budget) — this is NOT proof there are no duplicates; "
        "narrow the root or raise budget_ms"
    )
    lines.append(f"Scanned {scanned:,} entries · {completeness}")
    if query or exts:
        lines.append(f"Filter: name~'{query or '*'}'" + (f" · ext {sorted(exts)}" if exts else ""))

    return ToolResult(
        content="\n".join(lines),
        risk=RiskLevel.LOW,
        source="system_search",
        metadata={
            "operation": "duplicates",
            "groups": len(results),
            "wasted_bytes": wasted_total,
            "truncated": False,
            "scanned": scanned,
            "walk_complete": complete,
            "results": results,
        },
    )


# ── Operation: apps ─────────────────────────────────────────────────────────


def _installed_list() -> list[dict]:
    from tools.installed_programs import _list_linux, _list_macos, _list_windows

    if sys.platform == "win32":
        return _list_windows()
    if sys.platform == "darwin":
        return _list_macos()
    return _list_linux()


def _path_executables(query: str, cap: int = 10) -> list[dict]:
    """Executables on PATH whose name matches the query (e.g. 'where is python?')."""
    q = (query or "").lower().strip()
    if not q:
        return []
    aliases: tuple[str, ...] = ()
    for app, bins in _APP_CLI_ALIASES.items():
        if app in q or q in app:
            aliases = bins
            break
    out: list[dict] = []
    seen: set[str] = set()
    # Alias hits first — `which` is exact and cheap.
    for bin_name in aliases:
        loc = shutil.which(bin_name)
        if loc and loc not in seen:
            seen.add(loc)
            out.append({"name": bin_name, "path": loc, "source": "PATH"})
    if out:
        return out[:cap]
    # Fall back to scanning PATH dirs for name-fragment matches (flat dirs,
    # fast). Only when a concrete query exists.
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    for d in path_dirs:
        if len(out) >= cap:
            break
        try:
            for f in sorted(Path(d).iterdir()):
                if f.name.lower() in seen:
                    continue
                if q in f.name.lower():
                    if os.access(f, os.X_OK):
                        out.append({"name": f.name, "path": str(f), "source": "PATH"})
                        seen.add(f.name.lower())
                        if len(out) >= cap:
                            break
        except (PermissionError, OSError):
            continue
    return out


def _app_detail(p: dict) -> str:
    """'v1.2 · Publisher' / 'v1.2' / '' — compact one-line app detail."""
    if p.get("publisher"):
        return f"v{p['version']} · {p['publisher']}" if p.get("version") else str(p["publisher"])
    return f"v{p['version']}" if p.get("version") else ""


def _op_apps(args: dict) -> ToolResult:
    query = str(args.get("query", "") or "").strip()
    limit = _clamp(args.get("limit"), _DEFAULT_LIMIT, 1, _HARD_LIMIT)

    try:
        programs = _installed_list()
    except Exception as exc:  # noqa: BLE001 — degrade, never raise
        logger.error("[system_search] installed-programs listing failed: %s", exc)
        programs = []

    results: list[dict] = []
    if query:
        tokens = [t for t in query.lower().split() if len(t) > 2]
        matches = [
            p
            for p in programs
            if not tokens or any(t in p["name"].lower() for t in tokens)
        ]
        seen_names: set[str] = set()
        for p in matches[:limit]:
            if p["name"].lower() in seen_names:
                continue
            seen_names.add(p["name"].lower())
            results.append(
                {
                    "type": "app",
                    "name": p["name"],
                    "detail": _app_detail(p),
                    "installed": True,
                }
            )
        # PATH executables answer "where is python installed?" style questions.
        # Skip an executable whose name is already covered by a package row
        # (dpkg lists `python3` AND PATH has `python3` — one row is enough).
        for e in _path_executables(query):
            if e["name"].lower() in seen_names:
                continue
            seen_names.add(e["name"].lower())
            results.append(
                {"type": "app", "name": e["name"], "path": e["path"], "detail": "executable on PATH", "installed": True}
            )
        heading = f"Installed applications matching '{query}':"
    else:
        for p in programs[:limit]:
            results.append(
                {
                    "type": "app",
                    "name": p["name"],
                    "detail": _app_detail(p),
                    "installed": True,
                }
            )
        heading = f"Installed applications ({len(programs):,} total, first {len(results)}):"

    lines = [heading]
    for r in results:
        detail = f" — {r['detail']}" if r.get("detail") else ""
        loc = f" [{r['path']}]" if r.get("path") else ""
        lines.append(f"  📦 {r['name']}{detail}{loc}")
    if not results:
        lines.append(f"  No installed applications match '{query}'.")
        lines.append("  Tip: try the generic name (e.g. 'code' for VS Code) or check PATH executables.")
    if len(programs) > limit and not query:
        lines.append(f"  … and {len(programs) - limit} more — narrow with a 'query'.")

    return ToolResult(
        content="\n".join(lines),
        risk=RiskLevel.LOW,
        source="system_search",
        metadata={
            "operation": "apps",
            "total_programs": len(programs),
            "returned": len(results),
            "results": results,
        },
    )


# ── Operation: open_with ────────────────────────────────────────────────────


def _assoc_windows(ext: str) -> str:
    try:
        out = subprocess.check_output(
            ["cmd", "/c", "assoc", f".{ext}"], stderr=subprocess.DEVNULL, timeout=5
        ).decode("utf-8", "replace")
        # ".pdf=AcroExch.Document" → prog id; then ftype maps prog id → command.
        if "=" in out:
            prog_id = out.split("=", 1)[1].strip()
            ftype = subprocess.check_output(
                ["cmd", "/c", "ftype", prog_id], stderr=subprocess.DEVNULL, timeout=5
            ).decode("utf-8", "replace")
            if "=" in ftype:
                return ftype.split("=", 1)[1].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def _assoc_linux(path_or_ext: str) -> str:
    try:
        if os.path.isfile(path_or_ext):
            mime = subprocess.check_output(
                ["file", "--brief", "--mime-type", path_or_ext],
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).decode().strip()
        else:
            return ""
        desktop = subprocess.check_output(
            ["xdg-mime", "query", "default", mime], stderr=subprocess.DEVNULL, timeout=5
        ).decode().strip()
        if desktop:
            return f"{desktop} ({mime})"
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def _assoc_macos(ext: str) -> str:
    try:
        script = (
            'tell application "System Events" to get name of '
            f'first application process whose name contains "{ext}"'
        )
        out = subprocess.check_output(
            ["osascript", "-e", script],
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode("utf-8", "replace")
        if out.strip():
            return out.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def _op_open_with(args: dict) -> ToolResult:
    raw_path = str(args.get("path", "") or "").strip()
    query = str(args.get("query", "") or "").strip()
    ext_raw = str(args.get("ext", "") or "").strip()

    # Prefer an explicit extension; else derive from the path.
    if ext_raw:
        ext = ext_raw.lstrip(".").lower()
        target = f".{ext}"
    elif raw_path:
        ext = Path(raw_path).suffix.lstrip(".").lower()
        target = raw_path
    elif query:
        ext = query.lstrip("./* ").lower()
        target = f".{ext}"
    else:
        return ToolResult(
            content="system_search open_with requires a 'path', 'ext', or 'query' naming a file/extension.",
            risk=RiskLevel.LOW,
            source="system_search",
            success=False,
            error_type="invalid_input",
            error_message="missing target for open_with",
        )
    if not ext or "/" in ext or "\\" in ext:
        return ToolResult(
            content=f"Could not determine a file extension from '{target}'.",
            risk=RiskLevel.LOW,
            source="system_search",
            success=False,
            error_type="invalid_input",
            error_message=f"bad extension from {target!r}",
        )

    # Path-gate: a concrete path must be inside allowed roots (no existence
    # oracle outside them).
    if raw_path and not ext_raw:
        p = Path(raw_path).expanduser()
        if p.exists() and not settings.is_path_allowed(p):
            logger.warning("[system_search] open_with path outside allowed folders: %s", p)
            return ToolResult(
                content=f"Access denied: '{p}' is outside the allowed folders.",
                risk=RiskLevel.HIGH,
                source="system_search",
                success=False,
                error_type="permission_denied",
                error_message=f"path not allowed: {p}",
            )

    # 1) Platform association (best-effort, graceful degradation).
    assoc = ""
    try:
        if sys.platform == "win32":
            assoc = _assoc_windows(ext)
        elif sys.platform == "darwin":
            assoc = _assoc_macos(ext)
        else:
            probe = raw_path if (raw_path and os.path.isfile(raw_path)) else ""
            assoc = _assoc_linux(probe)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[system_search] association lookup failed for .%s: %s", ext, exc)
        assoc = ""

    # 2) Hint map + installed list (works offline on every platform).
    results: list[dict] = []
    if assoc:
        results.append({"type": "association", "detail": assoc, "source": "system"})
    try:
        programs = _installed_list()
    except Exception:  # noqa: BLE001
        programs = []
    hints = _EXT_APP_HINTS.get(ext, ())
    for p in programs:
        if any(h in p["name"].lower() for h in hints):
            results.append(
                {"type": "app", "name": p["name"], "detail": "installed · can open this file type", "installed": True}
            )
    if not results and hints:
        # Not installed either — say what WOULD open it.
        pretty = ", ".join(h.title() for h in hints[:4])
        results.append(
            {"type": "suggestion", "detail": f"Typical apps for .{ext}: {pretty} (none of these appear installed)"}
        )

    lines = [f"How to open .{ext} files:"]
    for r in results:
        name = r.get("name", "")
        detail = r.get("detail", "")
        src = r.get("source", "")
        if name:
            lines.append(f"  📦 {name} — {detail}")
        elif src == "system":
            lines.append(f"  ⚙️ System association: {detail}")
        else:
            lines.append(f"  💡 {detail}")
    if not results:
        lines.append(f"  No system association or known installed app for .{ext} found.")
        lines.append("  Tip: ask me to search installed apps by name, or install a viewer for this type.")

    return ToolResult(
        content="\n".join(lines),
        risk=RiskLevel.LOW,
        source="system_search",
        metadata={
            "operation": "open_with",
            "ext": ext,
            "results": results,
        },
    )


# ── Dispatch ────────────────────────────────────────────────────────────────


async def system_search(message: str) -> ToolResult:
    """
    SYSTEM_SEARCH dispatch — the unified local search front door.

    Args (JSON-encoded from the agent loop; plain string → files op):
        operation: "files" | "recent" | "largest" | "duplicates" |
                   "apps" | "open_with" (default "files")
        query:     name pattern (files/duplicates/apps) or optional filter
                   (recent/largest); app name for apps; extension for
                   open_with fallback
        root:      directory to search under (default: user home)
        ext:       extension filter, e.g. "pdf" or "pdf,docx"
        kind:      "file" | "dir" (files op)
        days:      recency window in days (recent op, default 7, max 365)
        minutes:   recency window in MINUTES (recent op) — wins over days
                   when given (B-2026-08-25-1: models pass minutes)
        limit:     result cap (default 10, max 25)
        offset:    page offset (files op)
        path:      concrete file path (open_with op)
        budget_ms: walk time budget (default 2500/4000, max 10000)
    """
    try:
        if message.strip().startswith("{"):
            args = json.loads(message)
        elif message.strip():
            # Plain string → parse a leading operation keyword if present,
            # else a name query (B-2026-08-25-1).
            args = _parse_plain_query(message.strip())
        else:
            # Bare call → the most useful overview: recent work.
            args = {"operation": "recent"}
    except json.JSONDecodeError as exc:
        return ToolResult(
            content=f"Could not parse system_search arguments: {exc}",
            risk=RiskLevel.LOW,
            source="system_search",
            success=False,
            error_type="invalid_input",
            error_message=str(exc),
        )

    operation = str(args.get("operation", "") or "files").strip().lower()
    if operation not in _OPERATIONS:
        return ToolResult(
            content=(
                f"Unknown system_search operation '{operation}'. "
                f"Valid operations: {', '.join(_OPERATIONS)}."
            ),
            risk=RiskLevel.LOW,
            source="system_search",
            success=False,
            error_type="invalid_input",
            error_message=f"bad operation: {operation}",
        )

    try:
        if operation == "files":
            return _op_files(args)
        if operation == "recent":
            return _op_recent(args)
        if operation == "largest":
            return _op_largest(args)
        if operation == "duplicates":
            return _op_duplicates(args)
        if operation == "apps":
            return _op_apps(args)
        return _op_open_with(args)
    except Exception as exc:  # noqa: BLE001 — tool must never raise
        logger.exception("[system_search] %s operation failed", operation)
        return ToolResult(
            content=f"system_search ({operation}) failed unexpectedly: {exc}",
            risk=RiskLevel.LOW,
            source="system_search",
            success=False,
            error_type="internal_error",
            error_message=str(exc),
        )


register_tool(
    Intent.SYSTEM_SEARCH,
    system_search,
    description=(
        "Unified LOCAL SEARCH over this computer: use FIRST for any find/locate/"
        "discover question about files, folders, recent work, largest files, "
        "duplicate copies, installed applications, or which program opens a file "
        "type. Operations: files (name/pattern search), recent (modified in last "
        "N days), largest (size-ranked), duplicates (same name+size, multiple "
        "locations), apps (installed programs + PATH executables, e.g. 'where is "
        "python'), open_with (which app handles .psd/.pdf/…). Returns a small "
        "ranked page + structured metadata — do NOT dump dir listings or run "
        "du/find via shell for these questions."
    ),
    cost=0.0,
    latency_ms=200,
    parallelizable=True,
    input_optional=True,
)
