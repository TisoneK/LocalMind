"""
Deterministic file-ops execution layer (ADR-8 Phase 4, track 2 — Session 193).

The root fix for the "find my CV and read it" failure class: file operations
become RUNTIME behavior, not model choices. The runtime runs the chain
(find_path → pick best match → file_reader) as code; the model is reduced to
its minimum — final synthesis only — and if the model is down or empty the
runtime still yields the deterministic evidence (never a blank bubble, never
a raw provider payload).

Three contracts, all checkable in code (no LLM needed for any of them):

1. ROUTE deterministically — the file-search signal (Session 191) marks
   file-ops phrasing with primary_domain="file_ops"; the engine intercepts
   BEFORE the agent loop, so the free-tier model never routes a file request
   to SHELL (the transcript failure: Get-ChildItem -Recurse 20s timeouts).

2. EXECUTE deterministically — `execute_file_ops()` runs find_path, a pure
   picker (`pick_best_match`) chooses the best match (identity first —
   "I'm Tisone" → CV-TisoneKironget.docx; then exact-name; then files over
   dirs; then shallowest; ambiguous → None → present the list and let the
   user choose), then the file is read with the SAME security boundary as
   file_task (`settings.is_path_allowed`).

3. VERIFY deterministically — FileOpsResult exposes found / chosen / content
   / error as plain fields, so the engine can gate on receipts without
   trusting "the model said done".
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.config import settings
from core.models import Intent
from tools import dispatch
from tools.file_reader import parse_file

logger = logging.getLogger(__name__)

# ── Read-verb detection ────────────────────────────────────────────────
# Verbs that turn a file SEARCH into a file READ chain ("find my cv AND
# READ it", "READ my cv", "SHOW me the invoice", "SUMMARIZE the report").
_READ_VERB = re.compile(
    r"\b(read|open|show me|show|view|display|summariz\w*|review|analy[sz]e|"
    r"print|get me|what(?:'s| is) in|tell me about)\b",
    re.IGNORECASE,
)
# The FOLLOW-UP read phrasing that appears AFTER a find target: the
# "and read it" / "open it" / "show it to me" tail the signal splits off.
_READ_FOLLOW = re.compile(
    r"\b(and\s+)?(read|open|show|view|display|summariz\w*|review|analy[sz]e|"
    r"print|what(?:'s| is) in)\s+(it|this|them|me)\b",
    re.IGNORECASE,
)
# "I'm Tisone, find my cv and read it" — the identity name used by the
# match picker to prefer CV-Tisone*.docx over the other 24 CVs.
_IDENTITY = re.compile(
    r"\b(?:i'?m|i am|my name is)\s+([A-Za-z][A-Za-z0-9_]*)", re.IGNORECASE
)


@dataclass
class FileOpsSpec:
    """The deterministic file-ops request, fully parsed (no LLM involved)."""

    target: str  # user-facing target noun ("cv")
    pattern: str  # find_path name pattern ("cv" or glob)
    root: str = ""  # search root ("" → user home by find_path contract)
    max_depth: int = 4
    max_results: int = 25
    read_requested: bool = False
    identity: str = ""  # user name for match picking ("tisone")

    def to_find_path_args(self) -> str:
        """Serialize the find_path dispatch argument (JSON, like the loop)."""
        return json.dumps(
            {
                "name": self.pattern,
                "root": self.root,
                "max_depth": self.max_depth,
                "max_results": self.max_results,
            }
        )


@dataclass
class FileOpsResult:
    """Deterministic receipts — every field checkable in code."""

    spec: FileOpsSpec
    matches: list[str] = field(default_factory=list)
    chosen: Optional[str] = None
    content: Optional[str] = None
    error: Optional[str] = None  # deterministic error text (not provider JSON)
    read_blocked: bool = False  # found but outside allowed folders


def detect_read_request(message: str) -> tuple[bool, str]:
    """Return (read_requested, identity) for a file-ops message.

    read_requested is True when the message either STARTS with a read verb
    ("read my cv") or contains a read FOLLOW-UP ("find my cv and read it").
    identity is the user name from "I'm X / I am X / my name is X" when
    present, used by the match picker to disambiguate (the transcript's
    "I'm Tisone, find my cv and read it" must prefer CV-TisoneKironget.docx).
    """
    read_requested = bool(_READ_VERB.search(message) or _READ_FOLLOW.search(message))
    m = _IDENTITY.search(message)
    identity = m.group(1).strip().lower() if m else ""
    return read_requested, identity


def pick_best_match(matches: list[str], pattern: str, identity: str = "") -> Optional[str]:
    """Deterministically pick the best match for a file read.

    Scoring (all pure string/path heuristics, no LLM):
      1. Identity hit (filename contains the user's name) — decisive.
      2. Exact-name hit (filename contains the search pattern) — strong.
      3. Regular file over directory.
      4. Shallower path preferred.
    Returns None when the top two are too close → the engine presents the
    list and asks the user instead of guessing (reading the wrong CV is
    worse than asking).
    """
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    pat_l = (pattern or "").lower().strip("* ?")
    ident_l = (identity or "").lower()

    def score(match: str) -> float:
        s = 0.0
        name = Path(match).name.lower()
        full = match.lower()
        if ident_l and ident_l in full:
            s += 100.0
        if pat_l and (pat_l in name or pat_l in full):
            s += 50.0
        try:
            if Path(match).is_file():
                s += 10.0
        except OSError:
            pass
        s -= len(Path(match).parts)  # shallower = better
        return s

    ranked = sorted(matches, key=score, reverse=True)
    top, second = score(ranked[0]), score(ranked[1])
    if top - second >= 10.0:  # decisive winner
        return ranked[0]
    return None  # ambiguous → ask


def _parse_match_paths(result) -> list[str]:
    """Extract match paths from a find_path ToolResult.

    find_path returns path lines in its content ("  📄  C:\\...\\file.docx").
    Primary source: metadata["paths"] (added Session 193); fallback parses
    the content lines for tool runs that predate the metadata key.
    """
    meta = getattr(result, "metadata", None) or {}
    paths = meta.get("paths")
    if paths:
        return [str(p) for p in paths]
    out: list[str] = []
    for line in (getattr(result, "content", "") or "").splitlines():
        line = line.strip()
        if line.startswith(("📄", "📁")):
            p = line.split(" ", 1)[-1].strip()
            if p:
                out.append(p)
    return out


async def _read_path(path: str) -> tuple[Optional[str], bool]:
    """Read a file's full text content deterministically.

    Mirrors file_task's security boundary exactly: never read outside
    settings.is_path_allowed. Returns (content, blocked).
    """
    p = Path(path)
    try:
        if not p.exists() or not p.is_file():
            return None, False
    except OSError:
        return None, False
    if not settings.is_path_allowed(p):
        logger.warning("[file_ops] blocked read of path outside allowed folders: %s", p)
        return None, True
    try:
        data = p.read_bytes()
        attachment = await parse_file(
            data=data,
            filename=p.name,
            content_type="application/octet-stream",
        )
        content = "\n\n---\n\n".join(attachment.chunks or [])
        if not content.strip():
            content = "[File appears to be empty or contains no readable text]"
        return content, False
    except Exception as exc:  # noqa: BLE001 — deterministic, never raise
        logger.error("[file_ops] read failed for %s: %s", p, exc)
        return f"[Could not read file: {exc}]", False


async def execute_file_ops(spec: FileOpsSpec) -> FileOpsResult:
    """Run the deterministic find → pick → read chain.

    Calls the registered find_path tool directly (same security + bounds as
    the agent path), picks the best match with the pure picker, and reads
    the chosen file. No LLM is invoked anywhere in this function.
    """
    result = FileOpsResult(spec=spec)
    try:
        tool_result = await dispatch(Intent.FIND_PATH, spec.to_find_path_args())
    except Exception as exc:  # noqa: BLE001
        logger.error("[file_ops] find_path dispatch failed: %s", exc)
        result.error = f"The file search failed: {exc}"
        return result

    if tool_result is None:
        result.error = "The file search tool is unavailable."
        return result
    if getattr(tool_result, "success", True) is False:
        result.error = tool_result.content or "The file search failed."
        return result

    result.matches = _parse_match_paths(tool_result)
    if not result.matches:
        result.error = (
            f"No files or folders matching '{spec.target}' were found"
            + (f" under {spec.root}." if spec.root else " in your home directory.")
        )
        return result

    if spec.read_requested:
        result.chosen = pick_best_match(result.matches, spec.pattern, spec.identity)
        if result.chosen:
            content, blocked = await _read_path(result.chosen)
            result.read_blocked = blocked
            if blocked:
                result.error = (
                    f"'{result.chosen}' is outside the allowed folders. "
                    "File reading is restricted to your user directories for safety."
                )
            elif content is not None:
                result.content = content
    return result


def format_match_list(result: FileOpsResult, limit: int = 25) -> str:
    """Deterministic, user-facing rendering of the match list."""
    lines = [f"Found {len(result.matches)} match(es) for '{result.spec.target}':"]
    for m in result.matches[:limit]:
        try:
            kind = "📁" if Path(m).is_dir() else "📄"
        except OSError:
            kind = "📄"
        lines.append(f"  {kind}  {m}")
    if len(result.matches) > limit:
        lines.append(f"  … more matches exist (capped at {limit})")
    return "\n".join(lines)


def format_read_evidence(result: FileOpsResult, max_chars: int = 24000) -> str:
    """Deterministic fallback rendering of the read content (bounded)."""
    content = (result.content or "").strip()
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n[... content truncated for performance]"
    return content
