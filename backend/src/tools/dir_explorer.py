"""
Directory Explorer tool — bounded, normalized, READ-ONLY folder inspection.

Design: docs/explorer_tool_design.md.

WHY this exists: LocalMind could FIND files (system_search), READ file bytes
(file_task), and search CONTENT (grep_search), but it had no first-class way
to LOOK AROUND a folder: "what's in this directory?", "sketch this project's
structure", "does this path exist before I write there?" all fell back to raw
shell (`ls`/`dir`/`tree`/`ls -R` — unbounded, un-normalized, exactly the
context-flood pattern the bounded search tools exist to prevent). This tool
gives those questions a bounded home.

Operations (JSON "operation" field):
  list  — one directory level: typed entries + size + mtime (no descent)
  tree  — bounded subtree sketch (depth cap, entry cap, plain-text output)
  stat  — one path's metadata (existence + type + sizes + timestamps)

Contracts (inherited from system_search/find_path hard lessons):
  - SECURITY: every path must pass ``settings.is_path_allowed``; symlinks are
    never followed (a link inside an allowed root could point OUTSIDE it);
    out-of-root attempts are a flat deny, never a prompt.
  - BOUNDED BY CONSTRUCTION: time-budgeted walk (default 2.5s, hard max 10s),
    entry cap (default 200, hard max 500), tree depth hard cap 4; heavy
    directories (node_modules, .git, venvs, …) are listed but never descended,
    marked "skipped".
  - HONEST: ``walk_complete`` + ``scanned`` in metadata AND in the human
    content; a partial scan always says so and never claims absence.
  - NORMALIZED: every row is {type, path, name, size, modified, detail} in
    metadata["results"] so the Parent presents without parsing prose.
  - NEVER RAISES: every failure degrades to ToolResult(success=False).
  - READ-ONLY BY CONSTRUCTION: only os.scandir / os.lstat — no write path
    exists, and no operation returns file BYTES (only names + metadata), so a
    .env inside the tree can leak its NAME (already visible to shell) but
    never its contents.

Parent scope: this is a TOOL of the Parent agent. No specialist agent, no
delegation. Deterministic primitives inspect; the Parent understands and
presents (the same split as system_search).

Registered as Intent.DIR_EXPLORER.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
import stat as stat_module
import time
from pathlib import Path

from core.config import settings
from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool
from tools.find_path import _HEAVY_DIR_NAMES

logger = logging.getLogger(__name__)

# ── Bounds ───────────────────────────────────────────────────────────────────
_DEFAULT_DEPTH = 2
_HARD_MAX_DEPTH = 4
_DEFAULT_MAX_ENTRIES = 200
_HARD_MAX_ENTRIES = 500
_DEFAULT_BUDGET_MS = 2500
_HARD_BUDGET_MS = 10000

_OPERATIONS = ("list", "tree", "stat")

# Weak-model tolerance (system_search precedent): when the tool is called
# with a PLAIN string instead of JSON, recognise operation keywords and a
# path-like token so "list C:\\Users\\me\\Proj" / "structure of the repo"
# still dispatch the right op instead of being treated as a literal path.
_OP_SYNONYMS: dict[str, str] = {
    "list": "list", "listing": "list", "ls": "list", "contents": "list",
    "dir": "list", "folder": "list", "what": "list", "show": "list",
    "tree": "tree", "structure": "tree", "outline": "tree", "sketch": "tree",
    "hierarchy": "tree", "layout": "tree",
    "stat": "stat", "stats": "stat", "info": "stat", "metadata": "stat",
    "exists": "stat", "size": "stat", "properties": "stat", "details": "stat",
}


def _looks_like_path(tok: str) -> bool:
    tc = tok.strip("\"'")
    return tc.startswith("/") or tc.startswith("~") or bool(re.match(r"^[A-Za-z]:[\\/]", tc)) or tc in (".", "..")


def _parse_plain_query(text: str) -> dict:
    """Turn a plain (non-JSON) dir_explorer input into structured args.

    Leading operation keyword → that op with the first path-like token as
    ``path``; no keyword → infer the op from shape: a bare path token means
    "list", otherwise "tree" (a user naming a project without an op verb is
    almost always after its structure).
    """
    toks = text.split()
    args: dict = {}
    rest = toks
    if toks and toks[0].lower().strip(":,") in _OP_SYNONYMS:
        args["operation"] = _OP_SYNONYMS[toks[0].lower().strip(":,")]
        rest = toks[1:]
    path_tok = next((t for t in rest if _looks_like_path(t.strip("\"'"))), None)
    if path_tok:
        args["path"] = path_tok.strip("\"'")
    elif args.get("operation") and rest:
        args["path"] = " ".join(rest).strip("\"'")
    elif rest:
        args["operation"] = "list"
        args["path"] = " ".join(rest).strip("\"'")
    else:
        args["operation"] = args.get("operation", "list")
    return args


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


def _err(content: str, error_type: str, risk: RiskLevel = RiskLevel.LOW) -> ToolResult:
    """Uniform failure envelope — dir_explorer never raises, never prompts."""
    return ToolResult(
        content=content,
        risk=risk,
        source="dir_explorer",
        requires_confirmation=False,
        success=False,
        error_type=error_type,
        error_message=content,
    )


# ── Security-gated path resolution ───────────────────────────────────────────


def _resolve_path(raw: str) -> tuple[Path | None, ToolResult | None]:
    """Expand, normalize and security-gate a requested path.

    Returns (path, error_result). Out-of-root is a flat DENY (never a
    prompt): this tool is read-only, so the gate exists to keep path
    listings inside the folders the user allowed, not to ask permission.
    """
    raw = (raw or "").strip().strip("\"'")
    if not raw:
        return None, _err("dir_explorer requires a 'path' (absolute or ~/).", "invalid_input")
    p = Path(raw).expanduser()
    if not settings.is_path_allowed(p):
        logger.warning("[dir_explorer] blocked inspection outside allowed folders: %s", p)
        return None, _err(
            f"Access denied: '{p}' is outside the allowed folders. "
            "Inspection is restricted to your user directories for safety.",
            "permission_denied",
            risk=RiskLevel.HIGH,
        )
    return p, None


def _classify(entry: os.DirEntry) -> str:
    """dir | file | symlink — never follow the link (it could escape roots)."""
    try:
        if entry.is_symlink():
            return "symlink"
        if entry.is_dir(follow_symlinks=False):
            return "dir"
        return "file"
    except OSError:
        return "file"


def _lstat_row(path: str, name: str, typ: str) -> dict:
    """Normalized row {type, path, name, size, modified, detail}.

    lstat (not stat): a symlink row describes the LINK, never its target.
    """
    try:
        st = os.lstat(path)
        size, mtime = st.st_size, st.st_mtime
    except OSError:
        size, mtime = 0, 0.0
    detail = ""
    if typ == "dir" and name in _HEAVY_DIR_NAMES:
        detail = "skipped — not descended (heavy directory)"
    elif typ == "symlink":
        detail = "symlink — not followed"
    return {"type": typ, "path": path, "name": name, "size": size, "modified": mtime, "detail": detail}


def _budget_note(budget_hit: bool, cap_hit: bool) -> str:
    if budget_hit:
        return "scan PARTIAL (time budget) — narrow the path or re-run on a smaller folder"
    if cap_hit:
        return "scan PARTIAL (entry cap) — more entries exist; narrow the path to see them"
    return "scan complete"


# ── Operation: list (one directory level) ────────────────────────────────────


def _op_list(args: dict) -> ToolResult:
    root, err = _resolve_path(str(args.get("path", "")))
    if err or root is None:
        return err

    cap = _clamp(args.get("max_entries"), _DEFAULT_MAX_ENTRIES, 1, _HARD_MAX_ENTRIES)
    budget_ms = _clamp(args.get("budget_ms"), _DEFAULT_BUDGET_MS, 100, _HARD_BUDGET_MS)
    dirs_first = args.get("dirs_first")
    dirs_first = True if dirs_first is None else bool(dirs_first)

    if not root.exists():
        return _err(f"Path '{root}' does not exist.", "not_found")
    if not root.is_dir():
        return _err(
            f"'{root}' is a file, not a folder — use operation=stat for a file's metadata "
            "or file_task to read its contents.",
            "invalid_input",
        )

    deadline = time.monotonic() + budget_ms / 1000.0
    rows: list[dict] = []
    scanned = 0
    cap_hit = False
    budget_hit = False
    try:
        with os.scandir(root) as it:
            for entry in it:
                scanned += 1
                if len(rows) >= cap:
                    cap_hit = True
                    break
                if scanned % 100 == 0 and time.monotonic() >= deadline:
                    budget_hit = True
                    break
                typ = _classify(entry)
                rows.append(_lstat_row(entry.path, entry.name, typ))
    except PermissionError:
        return _err(f"Permission denied listing '{root}'.", "permission_denied")
    except OSError as exc:
        return _err(f"Cannot list '{root}': {exc}", "internal_error")

    if dirs_first:
        rows.sort(key=lambda r: (0 if r["type"] == "dir" else 1, r["name"].lower()))
    else:
        rows.sort(key=lambda r: r["name"].lower())

    lines = [f"Contents of {root} — {len(rows)} entr{'y' if len(rows) == 1 else 'ies'}"
             + (f" (cap {cap} reached)" if cap_hit else "") + ":"]
    for r in rows:
        icon = {"dir": "📁", "symlink": "🔗"}.get(r["type"], "📄")
        suffix = "/" if r["type"] == "dir" else ""
        size = f" · {_fmt_size(r['size'])}" if r["type"] == "file" else ""
        when = f" · {_fmt_mtime(r['modified'])}" if r["modified"] else ""
        note = f" · {r['detail']}" if r["detail"] else ""
        lines.append(f"  {icon} {r['name']}{suffix}{size}{when}{note}")
    if not rows:
        lines.append("  (empty directory)")
    lines.append(
        f"Listed {len(rows)} of {scanned} seen · {_budget_note(budget_hit, cap_hit)}"
        " · names only — no file contents are ever returned"
    )

    return ToolResult(
        content="\n".join(lines),
        risk=RiskLevel.LOW,
        source="dir_explorer",
        metadata={
            "operation": "list",
            "root": str(root),
            "total": len(rows),
            "truncated": cap_hit or budget_hit,
            "scanned": scanned,
            "walk_complete": not (cap_hit or budget_hit),
            "results": rows,
        },
    )


# ── Operation: tree (bounded subtree sketch) ─────────────────────────────────


def _op_tree(args: dict) -> ToolResult:
    root, err = _resolve_path(str(args.get("path", "")))
    if err or root is None:
        return err

    depth_cap = _clamp(args.get("depth"), _DEFAULT_DEPTH, 1, _HARD_MAX_DEPTH)
    cap = _clamp(args.get("max_entries"), _DEFAULT_MAX_ENTRIES, 1, _HARD_MAX_ENTRIES)
    budget_ms = _clamp(args.get("budget_ms"), _DEFAULT_BUDGET_MS, 100, _HARD_BUDGET_MS)

    if not root.exists():
        return _err(f"Path '{root}' does not exist.", "not_found")
    if not root.is_dir():
        return _err(f"'{root}' is a file, not a folder — use operation=list on its parent.", "invalid_input")

    deadline = time.monotonic() + budget_ms / 1000.0
    rows: list[dict] = []
    lines: list[str] = [f"{root}/"]
    scanned = 0
    unreadable = 0
    depth_limited = False
    cap_hit = False
    budget_hit = False
    # Iterative preorder DFS; children are pushed in reverse so the first
    # (alphabetically) child pops first. Entry cap counts EMITTED rows.
    stack: list[tuple[Path, str]] = [(root, "")]
    while stack and not (cap_hit or budget_hit):
        current, indent = stack.pop()
        if time.monotonic() >= deadline:
            budget_hit = True
            break
        try:
            children = sorted(os.scandir(current), key=lambda e: e.name.lower())
        except (PermissionError, OSError):
            unreadable += 1
            lines.append(f"{indent}  [permission denied — not listed]")
            continue
        subdirs: list[tuple[Path, str]] = []
        for entry in children:
            scanned += 1
            if len(rows) >= cap:
                cap_hit = True
                break
            typ = _classify(entry)
            heavy = typ == "dir" and entry.name in _HEAVY_DIR_NAMES
            row = _lstat_row(entry.path, entry.name, typ)
            rows.append(row)
            label = entry.name + ("/" if typ == "dir" else "")
            notes = []
            if typ == "file":
                notes.append(_fmt_size(row["size"]))
            if heavy:
                notes.append("skipped")
            if typ == "symlink":
                notes.append("symlink (not followed)")
            tail = f"  ({', '.join(notes)})" if notes else ""
            lines.append(f"{indent}  {label}{tail}")
            if typ == "dir" and not heavy:
                # Descend only within the depth budget; a dir AT the cap is
                # noted as cut off so the sketch never implies leaf-ness.
                if len(indent) // 2 + 1 < depth_cap:
                    subdirs.append((Path(entry.path), indent + "  "))
                else:
                    depth_limited = True
                    lines.append(f"{indent}    … (depth limit {depth_cap} — contents not shown)")
            # symlinks are never descended regardless of depth.
        for child in reversed(subdirs):
            stack.append(child)

    footer = (
        f"{len(rows)} entr{'y' if len(rows) == 1 else 'ies'} shown"
        f" · depth limit {depth_cap}"
        f" · scanned {scanned:,} entries"
        + (f" · {unreadable} unreadable folder(s)" if unreadable else "")
        + (f" · deeper levels cut at depth {depth_cap}" if depth_limited else "")
        + f" · {_budget_note(budget_hit, cap_hit)}"
    )
    lines.append(footer)

    return ToolResult(
        content="\n".join(lines),
        risk=RiskLevel.LOW,
        source="dir_explorer",
        metadata={
            "operation": "tree",
            "root": str(root),
            "depth": depth_cap,
            "entries": len(rows),
            "truncated": cap_hit or budget_hit,
            "depth_limited": depth_limited,
            "scanned": scanned,
            "walk_complete": not (cap_hit or budget_hit),
            "results": rows,
        },
    )


# ── Operation: stat (one path's metadata) ────────────────────────────────────


def _op_stat(args: dict) -> ToolResult:
    target, err = _resolve_path(str(args.get("path", "")))
    if err or target is None:
        return err

    try:
        if not os.path.lexists(target):
            return _err(f"Path '{target}' does not exist.", "not_found")
        st = os.lstat(target)
    except PermissionError:
        return _err(f"Permission denied reading metadata of '{target}'.", "permission_denied")
    except OSError as exc:
        return _err(f"Cannot stat '{target}': {exc}", "internal_error")

    if stat_module.S_ISLNK(st.st_mode):
        typ = "symlink"
    elif stat_module.S_ISDIR(st.st_mode):
        typ = "dir"
    else:
        typ = "file"

    if typ == "symlink":
        detail = "symlink — target not followed"
    elif typ == "dir" and target.name in _HEAVY_DIR_NAMES:
        detail = "heavy directory — listed, not descended"
    else:
        detail = ""

    row = {
        "type": typ,
        "path": str(target),
        "name": target.name or str(target),
        "size": st.st_size,
        "modified": st.st_mtime,
        "detail": detail,
    }

    lines = [
        f"Path: {target}",
        f"Type: {typ}",
        f"Size: {_fmt_size(st.st_size)}" + (" (directory entries are not counted here)" if typ == "dir" else ""),
        f"Modified: {_fmt_mtime(st.st_mtime) or 'unknown'}",
        f"Accessed: {_fmt_mtime(st.st_atime) or 'unknown'}",
        f"Created (Windows) / ctime: {_fmt_mtime(st.st_ctime) or 'unknown'}",
        f"Mode: 0o{stat_module.S_IMODE(st.st_mode):03o}",
    ]
    if typ == "symlink":
        lines.append("Link target: not followed (read-only inspection never resolves links).")

    return ToolResult(
        content="\n".join(lines),
        risk=RiskLevel.LOW,
        source="dir_explorer",
        metadata={
            "operation": "stat",
            "path": str(target),
            "scanned": 1,
            "walk_complete": True,
            "results": [row],
            "exists": True,
        },
    )


# ── Dispatch ─────────────────────────────────────────────────────────────────


async def dir_explorer(message: str) -> ToolResult:
    """
    DIR_EXPLORER dispatch — bounded, normalized, read-only folder inspection.

    Args (JSON-encoded from the agent loop; plain string → keyword/path parse):
        operation:   "list" | "tree" | "stat"
        path:        directory (list/tree) or any path (stat); absolute or ~/
        depth:       tree only: max descent (default 2, hard max 4)
        max_entries: list/tree entry cap (default 200, hard max 500)
        dirs_first:  list only: sort folders before files (default true)
        budget_ms:   walk time budget (default 2500, max 10000)
    """
    try:
        if message.strip().startswith("{"):
            args = json.loads(message)
        elif message.strip():
            args = _parse_plain_query(message.strip())
        else:
            return _err(
                "dir_explorer needs a path — e.g. operation=list, path=~/Documents.",
                "invalid_input",
            )
    except json.JSONDecodeError as exc:
        return _err(f"Could not parse dir_explorer arguments: {exc}", "invalid_input")

    operation = str(args.get("operation", "") or "list").strip().lower()
    operation = _OP_SYNONYMS.get(operation, operation)
    if operation not in _OPERATIONS:
        return _err(
            f"Unknown dir_explorer operation '{operation}'. "
            f"Valid operations: {', '.join(_OPERATIONS)}.",
            "invalid_input",
        )

    try:
        if operation == "list":
            return _op_list(args)
        if operation == "tree":
            return _op_tree(args)
        return _op_stat(args)
    except Exception as exc:  # noqa: BLE001 — tool must never raise
        logger.exception("[dir_explorer] %s operation failed", operation)
        return _err(f"dir_explorer ({operation}) failed unexpectedly: {exc}", "internal_error")


register_tool(
    Intent.DIR_EXPLORER,
    dir_explorer,
    description=(
        "Inspect a LOCAL file/folder — read-only, bounded, normalized. Use to look around a "
        "directory, sketch a project's structure, or check a path before writing. Operations: "
        "list (one folder's entries with size+mtime), tree (bounded structure sketch, depth<=4), "
        "stat (one path's metadata). Returns NAMES + METADATA only, never file bytes. For "
        "FINDING files by name use system_search; for READING contents use file_task."
    ),
    cost=0.0,
    latency_ms=150,
    parallelizable=True,
    input_optional=False,
)
