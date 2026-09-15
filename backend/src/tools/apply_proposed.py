"""
apply_proposed_edit tool — Propose-stage tools.

Writes a staged proposal (from propose_str_replace / propose_write_file)
to disk. Inherits file_writer's safety gates:
  - allowed-folders gate (is_path_allowed, same as edit_file)
  - localmind_require_write_permission confirmation gate (same as file_writer)

The staged content lives in the per-run proposal registry — a proposal is
only visible to apply calls in the SAME agent run.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from core.config import settings
from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool
from tools.edit_file import _resolve_path
from tools.proposals import discard_proposal, get_proposal, get_proposals

logger = logging.getLogger(__name__)


def _find_staged(
    raw_path: str,
) -> tuple[Optional[Path], Optional[str], list[str]]:
    """
    Resolve `raw_path` and find staged content for it.

    Returns (filepath, staged_content, ambiguous_matches).
    - Exact resolved match first (the norm — the model gets the full
      resolved path back from the propose result metadata).
    - Falls back to suffix/basename matching for small path variations
      (~ vs absolute, trailing slash, relative). The fallback only
      returns a match when it is UNIQUE: if two staged files share a
      basename in different directories, we never guess — the caller
      returns an ambiguity error instead of writing to the wrong file.
    """
    target = _resolve_path(raw_path)
    staged = get_proposal(str(target))
    if staged is not None:
        return target, staged, []

    matches = [
        key for key in get_proposals()
        if key.endswith(raw_path) or Path(key).name == target.name
    ]
    if len(matches) == 1:
        return Path(matches[0]), get_proposal(matches[0]), []
    if len(matches) > 1:
        return None, None, matches
    return None, None, []


async def apply_proposed_edit(message: str) -> ToolResult:
    """
    Write a staged proposal to disk.

    Accepts a bare path string (from the agent loop's single-arg case) or
    a JSON payload {"path": "..."}.
    """
    raw_path = message.strip()
    if raw_path.startswith("{"):
        try:
            payload = json.loads(raw_path)
            raw_path = str(payload.get("path", "")).strip() if isinstance(payload, dict) else ""
        except (json.JSONDecodeError, TypeError):
            return ToolResult(
                content=(
                    "Invalid apply_proposed_edit payload — expected a path string or "
                    '{"path": "..."}.'
                ),
                risk=RiskLevel.LOW,
                source="apply_proposed_edit",
                success=False,
                error_type="parse_error",
                error_message="Invalid apply_proposed_edit payload",
            )

    if not raw_path:
        return ToolResult(
            content="'path' is required for apply_proposed_edit",
            risk=RiskLevel.LOW,
            source="apply_proposed_edit",
            success=False,
            error_type="validation_error",
            error_message="Missing required field 'path'",
        )

    filepath, staged, ambiguous = _find_staged(raw_path)
    if ambiguous:
        return ToolResult(
            content=(
                f"Ambiguous proposal match for {raw_path!r}: multiple staged files "
                f"match ({', '.join(ambiguous)}). Pass the exact path shown in the "
                f"proposal's diff preview."
            ),
            risk=RiskLevel.LOW,
            source="apply_proposed_edit",
            success=False,
            error_type="ambiguous_proposal",
        )
    if staged is None:
        return ToolResult(
            content=(
                f"No staged proposal for {raw_path}. Stage one first with "
                f"propose_str_replace or propose_write_file — proposals only live "
                f"for the current run."
            ),
            risk=RiskLevel.LOW,
            source="apply_proposed_edit",
            success=False,
            error_type="no_proposal",
        )

    # SECURITY: same allowed-folders gate as edit_file (HIGH risk).
    if not settings.is_path_allowed(filepath):
        return ToolResult(
            content=(
                f"Access denied: '{filepath}' is outside the allowed folders. "
                f"File writing is restricted to your user directories for safety."
            ),
            risk=RiskLevel.HIGH,
            source="apply_proposed_edit",
            success=False,
            error_type="permission_denied",
            error_message=f"Path not in allowed read paths: {filepath}",
        )

    # Same write-permission gate as file_writer — when confirmation is
    # required, surface the pending write for the user to approve.
    if settings.localmind_require_write_permission:
        return ToolResult(
            content=(
                f"I want to write the staged proposal to:\n`{filepath}`\n\n"
                "Reply **yes** to confirm or specify a different path."
            ),
            risk=RiskLevel.LOW,
            source="apply_proposed_edit",
            metadata={
                "requires_permission": True,
                "pending_path": str(filepath),
                "pending_content": staged,
                "filename": filepath.name,
                "final_dest": str(filepath),
            },
            requires_confirmation=True,
        )

    # Write the staged content
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(staged, encoding="utf-8")
    except Exception as exc:
        logger.error("[apply_proposed_edit] write failed for %s: %s", filepath, exc)
        return ToolResult(
            content=f"Write failed: {exc}",
            risk=RiskLevel.HIGH,
            source="apply_proposed_edit",
            success=False,
            error_type="io_error",
            error_message=str(exc),
        )

    # Applied — remove from the registry so a second apply is a no-op error.
    discard_proposal(str(filepath))

    size = len(staged.encode())
    lines = len(staged.splitlines()) if staged else 0
    return ToolResult(
        content=f"Applied staged proposal → {filepath} ({size} bytes, {lines} lines)",
        risk=RiskLevel.LOW,
        source="apply_proposed_edit",
        success=True,
        metadata={
            "path": str(filepath),
            "staged": False,
            "applied": True,
            "bytes": size,
            "lines": lines,
        },
    )


# Register the tool — Intent.APPLY_PROPOSED → apply_proposed_edit
register_tool(
    Intent.APPLY_PROPOSED,
    apply_proposed_edit,
    description=(
        "Write a staged proposal to disk. Applies the content staged by "
        "propose_str_replace or propose_write_file for the given path. Inherits "
        "the same permission gating as file_write — nothing is written without "
        "confirmation when write permission is required."
    ),
    cost=0.02,
    latency_ms=100,
    parallelizable=False,  # disk write — stateful, don't run concurrently
)
