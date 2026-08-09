"""
propose_str_replace tool — B-2026-08-02-7 (B2, propose-stage tools).

Stages a search/replace-style edit as a PROPOSAL without touching disk.
The model can stage MULTIPLE candidate edits for the same file
(best-of-N editing), review the diff previews, then apply the winner with
apply_proposed_edit. Nothing is written until apply.

Borrowed from Codebuff's propose-str-replace pattern. Takes the same
JSON payload as edit_file and runs the IDENTICAL validation / permission
gates (via edit_file.prepare_edit) — only the write step differs.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool
from tools.edit_file import (
    _diff_hunks,
    _diff_summary,
    _infer_language,
    prepare_edit,
)
from tools.proposals import stage_proposal


async def propose_str_replace(message: str) -> ToolResult:
    """
    Stage a proposed edit (validated + diff-computed, NOT written).

    Accepts the same JSON payload as edit_file:
      {"path": "file.py", "action": "replace", "search": "old", "replace": "new"}
    Returns a diff preview and stores the modified content in the per-run
    proposal registry under the resolved path. Call apply_proposed_edit with
    that path to write it.
    """
    # Same JSON payload contract as edit_file
    try:
        payload: Dict[str, Any] = json.loads(message) if message.strip().startswith("{") else {}
        if not isinstance(payload, dict):
            payload = {}
    except (json.JSONDecodeError, TypeError):
        payload = {}

    if not payload:
        return ToolResult(
            content=(
                "Could not parse propose_str_replace instruction. Provide a JSON payload "
                "with 'path', 'action', and 'search'/'replace' (the same arguments as "
                "edit_file). "
                'Example: {"path": "file.py", "action": "replace", '
                '"search": "old", "replace": "new"}'
            ),
            risk=RiskLevel.LOW,
            source="propose_str_replace",
            success=False,
            error_type="parse_error",
            error_message="Invalid propose_str_replace payload — expected JSON",
        )

    # The TOOL_DEFINITION documents action as optional with "default:
    # replace" — honor that promise here (prepare_edit itself requires an
    # explicit action, same as edit_file).
    payload.setdefault("action", "replace")

    # prepare_edit runs the exact edit_file validation + permission gates
    # (path required, allowed folders, file exists, size cap, encoding,
    # apply errors) without creating a backup or writing anything.
    error, prepared = prepare_edit(payload, source="propose_str_replace")
    if error is not None:
        return error

    filepath = prepared.filepath
    if prepared.modified == prepared.original:
        return ToolResult(
            content=f"No changes to stage for {filepath} (edit had no effect)",
            risk=RiskLevel.LOW,
            source="propose_str_replace",
            success=True,
        )

    # Stage the computed content — the registry is per-run, so this is
    # visible to a later apply_proposed_edit call in the same run only.
    stage_proposal(str(filepath), prepared.modified)

    summary = _diff_summary(prepared.original, prepared.modified, str(filepath))
    hunks = _diff_hunks(prepared.original, prepared.modified, str(filepath))
    orig_lines = len(prepared.original.splitlines())
    mod_lines = len(prepared.modified.splitlines())
    additions = sum(1 for h in hunks for line in h.get("lines", []) if line.get("type") == "added")
    deletions = sum(1 for h in hunks for line in h.get("lines", []) if line.get("type") == "removed")

    return ToolResult(
        content=(
            f"## Staged edit proposal (not yet written)\n\n{summary}\n\n"
            f"**{filepath}** — staged {orig_lines} → {mod_lines} lines. "
            f"Call `apply_proposed_edit(path={filepath})` to write it, or stage "
            f"another candidate for the same file and compare the previews."
        ),
        risk=RiskLevel.LOW,
        source="propose_str_replace",
        success=True,
        metadata={
            "path": str(filepath),
            "staged": True,
            "applied": False,
            "original_lines": orig_lines,
            "modified_lines": mod_lines,
            "lines_changed": abs(mod_lines - orig_lines),
            "diff_hunks": hunks,
            "diff_additions": additions,
            "diff_deletions": deletions,
            "diff_language": _infer_language(str(filepath)),
        },
    )


# Register the tool — Intent.PROPOSE_EDIT → propose_str_replace
register_tool(
    Intent.PROPOSE_EDIT,
    propose_str_replace,
    description=(
        "Stage a search/replace-style edit as a PROPOSAL without touching disk. "
        "Takes the same arguments as edit_file (path, action, search, replace, etc.) "
        "and returns a diff preview; the modified content is stored in a per-run "
        "proposal registry. Use this for best-of-N editing: stage 2-3 candidate "
        "fixes for the same file, compare the previews, then apply the winner with "
        "apply_proposed_edit. Nothing is written until you apply."
    ),
    cost=0.01,
    latency_ms=50,
    parallelizable=True,  # pure registry write — safe to stage concurrently
)
