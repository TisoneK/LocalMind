"""
Find Path tool — name-match search for files AND folders, path-only output.

Why this exists (Session 124/125): the agent, asked to "check git status on
the localmind repo", ran `dir C:\\Users\\tison` — dumping the ENTIRE home
directory into context (~2K tokens of noise, plus a 20K+ prompt downstream)
when it only needed to locate one folder. The existing shell `find_files`
action searches by FILE TYPE (`*.py`), not by name, and can't match
directories. A narrow find-by-name tool makes the output size bounded BY
CONSTRUCTION: it returns only matching paths, never a full listing.

Catalog contract (Session 194): the tool is a glob/grep-style ENUMERATION,
not a one-shot capped lookup. It walks ONCE (bounded by a time budget + an
entry cap, not by result count), holds the full match list in a bounded
TTL cache, and serves every follow-up — "show more", "only pdf", "in
Documents" — as instant in-memory filtering/pagination against that same
walk. The result is a CATALOG: total matches, folder + extension counts,
and a small page of paths. The model sees the catalog summary, never the
full list, so context stays bounded while NOTHING is silently hidden.

Security: unchanged — searches stay inside `settings.is_path_allowed` roots,
symlinks are never followed, heavy dirs (node_modules, .git, …) are skipped
entirely, and filters never open new traversal (they narrow the cached list).

Registered as Intent.FIND_PATH in the tool registry.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import time
from pathlib import Path

from core.config import settings
from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool

logger = logging.getLogger(__name__)

# Bounds — the walk is time/entry-bounded; the OUTPUT page is result-capped.
_DEFAULT_MAX_DEPTH = 4
_DEFAULT_MAX_RESULTS = 10
_HARD_MAX_DEPTH = 8
_HARD_MAX_RESULTS = 25
# Time budget for a single walk (default 2.5s, hard max 10s). This is the
# real cap — a home-dir scan stops here with an honest "scan partial" flag
# instead of silently truncating at an arbitrary result count. Narrowing
# the search (ext/subpath) is the user-visible way to search deeper.
_DEFAULT_BUDGET_MS = 2500
_HARD_BUDGET_MS = 10000
# Legacy `_search` walks stay tiny (they only ever serve a few results).
_SEARCH_BUDGET_MS = 500
# Hard entry cap so a pathological tree can never make a single call walk
# forever even with a large budget.
_MAX_SCANNED = 250_000
# Cap on metadata["paths"] when all_paths is requested (the deterministic
# file-ops picker needs the full catalog, bounded for memory safety).
_ALL_PATHS_CAP = 5000

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

# ── Catalog cache (Session 194) ─────────────────────────────────────────
# "Find ALL files and paths once, then filter." The first find_path call for
# a given (root, pattern, exact, depth, budget) walks and caches the match
# list; every follow-up — page 2, "only pdf", "in Documents" — filters or
# slices that list in memory. No re-walk, no repeated disk I/O.
#
# Bounded on all sides (code-review, Session 194): a 60s TTL so a newly
# created file shows up on the next identical request (a 5-minute window was
# too stale for a desktop app), a small entry cap so a long-running server
# can't accumulate tens of thousands of stale paths, and the stored match
# list itself is capped (totals stay accurate — only the cached sample is
# bounded).
_CACHE_MAX = 16
_CACHE_TTL_SECS = 60.0
# Max matches stored per cached walk (totals are still counted in full).
_MAX_CACHED_MATCHES = 20_000
_FIND_CACHE: dict[tuple, tuple[float, list[str], int, bool, int]] = {}


def _cache_get(key: tuple) -> tuple[list[str], int, bool, int] | None:
    entry = _FIND_CACHE.get(key)
    if entry is None:
        return None
    ts, matches, scanned, complete, total = entry
    if time.monotonic() - ts > _CACHE_TTL_SECS:
        _FIND_CACHE.pop(key, None)
        return None
    return matches, scanned, complete, total


def _cache_put(key: tuple, matches: list[str], scanned: int, complete: bool, total: int) -> None:
    if len(_FIND_CACHE) >= _CACHE_MAX:
        # Evict the oldest entry (dicts preserve insertion order).
        _FIND_CACHE.pop(next(iter(_FIND_CACHE)))
    _FIND_CACHE[key] = (time.monotonic(), matches, scanned, complete, total)


def _search(root: Path, pattern: str, max_depth: int, max_results: int) -> list[Path]:
    """Legacy bounded search (Session 125 tests + agent-era callers).

    Returns the first `max_results` matches of a catalog walk — same name
    matching, same heavy-dir/symlink policy, but stops early: a small budget
    keeps the legacy "bounded, fast" contract (it never needs to scan a big
    tree to completion for a small page).
    """
    matches, _scanned, _complete, _total = _walk_catalog(
        root, pattern, max_depth, _SEARCH_BUDGET_MS, _MAX_SCANNED
    )
    return matches[:max_results]


def _expand_braces(pattern: str) -> list[str]:
    """Expand shell-style brace groups {a,b} into concrete patterns.

    Returns [pattern] unchanged when there is no comma-containing brace
    group. Handles multiple groups (Cartesian product) and nested groups:
    "{a,b}{1,2}.txt" → ["a1.txt", "a2.txt", "b1.txt", "b2.txt"];
    "{tison,{cv,resume}}*" → ["tison*", "cv*", "resume*"]. fnmatch has no
    brace support, so a model told "glob" that tries `*.{docx,pdf}` would
    silently match nothing — this makes it work.
    """
    if "{" not in pattern:
        return [pattern]
    open_i = pattern.index("{")
    depth = 0
    close_i = -1
    for i in range(open_i, len(pattern)):
        if pattern[i] == "{":
            depth += 1
        elif pattern[i] == "}":
            depth -= 1
            if depth == 0:
                close_i = i
                break
    if close_i == -1:
        return [pattern]  # unbalanced — treat the braces literally
    head, body, tail = pattern[:open_i], pattern[open_i + 1 : close_i], pattern[close_i + 1 :]
    alternatives = _split_brace_alternatives(body)
    if len(alternatives) == 1:
        return [pattern]  # no alternatives — literal (e.g. "{a}")
    out: list[str] = []
    for alt in alternatives:
        out.extend(_expand_braces(head + alt + tail))
    return out


def _split_brace_alternatives(body: str) -> list[str]:
    """Split a brace body on top-level commas only — a comma inside a nested
    {group} must not split its parent. "a,{b,c}" → ["a", "{b,c}"]."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in body:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


def _matches(name: str, pattern: str, exact: bool = False) -> bool:
    """Case-insensitive substring, fnmatch (with {a,b} braces), or exact.

    B-2026-08-16-16: multi-word PLAIN input (no glob chars) is an unordered
    AND — the name must contain EVERY whitespace-separated token, in any
    order. A single fnmatch pattern can't express "contains X and Y" order-
    independently, so `name="tison cv"` previously only matched the literal
    phrase "tison cv" in that exact order; now it matches any name containing
    both "tison" and "cv" (a strict superset — phrase matches still pass, and
    single-token / glob / exact behavior is unchanged).

    B-2026-08-16-17: shell-style brace groups `{a,b}` (fnmatch's missing
    feature) expand into concrete patterns — `*.{docx,pdf}` matches both
    extensions, `{tison,cv}*` matches either prefix.
    """
    pattern_l = pattern.lower().strip()
    if not pattern_l:
        return False
    lowered = name.lower()
    if exact:
        return lowered == pattern_l
    if "{" in pattern_l and "}" in pattern_l and "," in pattern_l:
        return any(fnmatch.fnmatch(lowered, p) for p in _expand_braces(pattern_l))
    if any(ch in pattern_l for ch in "*?["):
        return fnmatch.fnmatch(lowered, pattern_l)
    tokens = pattern_l.split()
    if len(tokens) > 1:
        return all(tok in lowered for tok in tokens)
    return pattern_l in lowered


def _walk_catalog(
    root: Path,
    pattern: str,
    max_depth: int,
    budget_ms: int,
    max_entries: int,
    exact: bool = False,
) -> tuple[list[Path], int, bool, int]:
    """Walk root within budget, counting ALL name matches (no result cap).

    Returns (matches, scanned_entries, complete, total_matches). The returned
    list is capped at _MAX_CACHED_MATCHES (memory bound, code review);
    total_matches keeps the TRUE count so the catalog never lies about scale.
    `complete` is False when the walk hit the time budget or the entry cap,
    meaning the catalog is partial (the caller must say so, honestly).
    """
    matches: list[Path] = []
    total_matches = 0
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
            entries = sorted(current.iterdir(), key=lambda p: p.name.lower())
        except (PermissionError, OSError):
            continue
        for entry in entries:
            scanned += 1
            if scanned >= max_entries:
                complete = False
                break
            # Security (Session 125 review): never follow symlinks — a symlink
            # inside the search root could point OUTSIDE the allowed folders
            # and leak paths past the is_path_allowed root check.
            try:
                if entry.is_symlink():
                    continue
                is_dir = entry.is_dir()
            except OSError:
                continue
            # Skip heavy directories entirely (never descend, never match).
            if is_dir and entry.name in _HEAVY_DIR_NAMES:
                continue
            if _matches(entry.name, pattern, exact=exact):
                total_matches += 1
                if len(matches) < _MAX_CACHED_MATCHES:
                    matches.append(entry)
            if is_dir and depth < max_depth:
                stack.append((entry, depth + 1))
        if not complete:
            break
    return matches, scanned, complete, total_matches


def _parse_exts(raw: str) -> set[str] | None:
    """'pdf' | '.pdf' | 'pdf, docx' → {'pdf', 'docx'} (None when empty)."""
    parts = [p.strip().lstrip(".").lower() for p in raw.split(",")]
    parts = [p for p in parts if p]
    return set(parts) if parts else None


def _apply_filters(
    matches: list[Path],
    *,
    kind: str,
    subpath: str,
    exts: set[str] | None,
    root: Path,
) -> list[Path]:
    """Narrow the (cached) catalog in memory — no disk I/O, no new traversal."""
    out: list[Path] = []
    sp = tuple(s for s in Path(subpath).parts if s not in ("", ".", ".."))
    for m in matches:
        if kind == "file" and not m.is_file():
            continue
        if kind == "dir" and not m.is_dir():
            continue
        if sp:
            try:
                rel = m.relative_to(root)
            except ValueError:
                continue
            if rel.parts[: len(sp)] != sp:
                continue
        if exts and m.suffix.lstrip(".").lower() not in exts:
            continue
        out.append(m)
    return out


def _group_by_folder(matches: list[Path], root: Path) -> dict[str, int]:
    """Where do the matches live? First relative segment under root for
    nested matches; files directly in the root group as '(root)'."""
    counts: dict[str, int] = {}
    for m in matches:
        try:
            rel = m.relative_to(root)
            key = rel.parts[0] if len(rel.parts) > 1 else "(root)"
        except ValueError:
            key = "(root)"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:8])


def _group_by_extension(matches: list[Path]) -> dict[str, int]:
    """File-extension counts (files only; extensionless → '(none)')."""
    counts: dict[str, int] = {}
    for m in matches:
        if not m.is_file():
            continue
        ext = m.suffix.lstrip(".").lower() or "(none)"
        counts[ext] = counts.get(ext, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:8])


def _clamp(value, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


async def find_path(message: str) -> ToolResult:
    """
    FIND_PATH dispatch — find files/folders whose NAME matches a pattern.

    Args (JSON-encoded from the agent loop, mirroring git/delegate):
        name:       substring, glob, or space-separated keywords (unordered
                    AND — every word must appear, in any order) to match
                    (required)
        root:       directory to search under (default: user home)
        max_depth:  recursion depth cap (default 4, max 8)
        max_results: OUTPUT page size (default 10, max 25)
        budget_ms:  walk time budget (default 2500, max 10000) — the walk
                    finds ALL matches within this budget; narrowing the
                    search is the way to search deeper.
        offset:     page offset for continuation (\"show more\") — served
                    from the cached walk, no re-scan.
        ext:        extension filter, e.g. \"pdf\" or \"pdf,docx\".
        subpath:    relative folder filter under root, e.g. \"Documents\"
                    or \"OneDrive/Documents\".
        kind:       \"file\" | \"dir\" to filter by type.
        exact:      exact name match instead of substring.
        all_paths:  metadata[\"paths\"] carries the FULL filtered list
                    (capped at 5000) instead of the displayed page — used
                    by the deterministic file-ops picker.
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
    budget_ms = _clamp(args.get("budget_ms"), _DEFAULT_BUDGET_MS, 100, _HARD_BUDGET_MS)
    offset = max(0, _clamp(args.get("offset"), 0, 0, 1_000_000))
    exact = bool(args.get("exact", False))
    kind = str(args.get("kind", "") or "").strip().lower()
    if kind not in ("file", "dir"):
        kind = ""
    subpath = str(args.get("subpath", "") or "").strip().strip("/\\")
    exts = _parse_exts(str(args.get("ext", "") or ""))
    all_paths = bool(args.get("all_paths", False))

    # Catalog walk, served from the bounded TTL cache when possible — the
    # whole point of the glob/grep-style contract: enumerate once, filter
    # many. A different budget forces a fresh (deeper/shallower) walk.
    cache_key = (str(root), pattern, exact, max_depth, budget_ms)
    cached = _cache_get(cache_key)
    if cached is not None:
        all_matches, scanned, complete, total_matches = cached
        all_matches = [Path(p) for p in all_matches]
    else:
        try:
            found, scanned, complete, total_matches = _walk_catalog(
                root, pattern, max_depth, budget_ms, _MAX_SCANNED, exact=exact
            )
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
        _cache_put(
            cache_key, [str(p) for p in found], scanned, complete, total_matches
        )
        all_matches = found

    filtered = _apply_filters(
        all_matches, kind=kind, subpath=subpath, exts=exts, root=root
    )
    # total is the FILTERED count the user is looking at. When the walk hit
    # the match cap (20k+ matches), filtered totals under-count slightly —
    # the honesty note below says so.
    total = len(filtered)
    page = filtered[offset : offset + max_results]

    if total == 0:
        return ToolResult(
            content=(
                f"No files or folders matching '{pattern}' found under {root}"
                + (f" (scanned {scanned:,} entries)." if scanned else ".")
            ),
            risk=RiskLevel.LOW,
            source="find_path",
            metadata={
                "matches": 0,
                "root": str(root),
                "truncated": False,
                "total": 0,
                "scanned": scanned,
                "walk_complete": complete,
                "offset": offset,
                "page_size": 0,
                "groups": {},
                "extensions": {},
                "paths": [],
            },
        )

    groups = _group_by_folder(filtered, root)
    extensions = _group_by_extension(filtered)

    def _icon(p: Path) -> str:
        try:
            return "📁" if p.is_dir() else "📄"
        except OSError:
            return "📄"

    lines = [f"Found {total:,} match(es) for '{pattern}' under {root}:"]
    for m in page:
        lines.append(f"  {_icon(m)}  {m}")
    if offset + len(page) < total:
        lines.append(
            f"  … {total - offset - len(page):,} more "
            f"(showing {offset + 1:,}–{offset + len(page):,} of {total:,})"
        )
    # Catalog summary — the context-bounded view of the whole result set.
    # Honest about incompleteness: filters/pagination serve the CACHED walk
    # in memory, so a partial scan stays partial until the root is narrowed
    # or the budget raised — the tip says "narrow", not "search deeper".
    completeness = "scan complete" if complete else "scan partial (budget)"
    lines.append(f"Catalog: {total:,} match(es) · scanned {scanned:,} entries · {completeness}")
    if total_matches > len(all_matches):
        lines.append(
            f"Note: the walk found {total_matches:,} matches; the list is "
            f"capped at {len(all_matches):,} for memory — filters apply to "
            "the held sample, so filtered totals may under-count."
        )
    if groups:
        lines.append(
            "  Folders: " + " · ".join(f"{k} {v:,}" for k, v in groups.items())
        )
    if extensions:
        lines.append(
            "  Types:   " + " · ".join(f".{k} {v:,}" for k, v in extensions.items())
        )
    if not complete or offset + len(page) < total:
        lines.append(
            'Tip: narrow with "only pdf" / "in <folder>", or say "show more" '
            "for the next page."
        )

    paths = [str(m) for m in page]
    if all_paths:
        paths = [str(m) for m in filtered[:_ALL_PATHS_CAP]]

    return ToolResult(
        content="\n".join(lines),
        risk=RiskLevel.LOW,
        source="find_path",
        # Session 193 (deterministic file-ops layer): expose the matched
        # paths STRUCTURED so the engine's deterministic executor can pick
        # and read without re-parsing the human-facing content lines.
        # Session 194: catalog fields (total/groups/extensions/walk_complete)
        # let the executor present scale honestly and filter/continue
        # against the full list.
        metadata={
                "matches": len(page),
                "root": str(root),
                "truncated": offset + len(page) < total,
                "total": total,
                "scanned": scanned,
                "walk_complete": complete,
                "offset": offset,
                "page_size": len(page),
                "groups": groups,
                "extensions": extensions,
                "paths": paths,
            },
            # NOTE: results may be served from a 60s cache — repeat searches
            # for the same (root, pattern) reflect the filesystem as of the
            # first walk in that window.
    )


register_tool(
    Intent.FIND_PATH,
    find_path,
    description=(
        "Find files OR folders whose NAME matches a pattern (substring or glob, "
        "case-insensitive) under a root directory. Enumerates ALL matches within "
        "a short walk budget and returns a CATALOG: total count, folder + type "
        "breakdown, and a small page of paths (default 10, max 25 per page) — "
        "plus structured metadata (total, groups, paths). Follow-ups are instant: "
        "\"show more\" pages, and \"only pdf\" / \"in Documents\" filter the cached "
        "walk without re-scanning. Use this to LOCATE a file or folder by name — "
        "do NOT use dir/ls to hunt for something; that dumps the whole listing "
        "into context."
    ),
    cost=0.0,
    latency_ms=150,
    parallelizable=True,
)
