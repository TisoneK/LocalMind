"""
propose_write_file tool — Propose-stage tools.

Stages a full-file write as a PROPOSAL without touching disk. Takes the
same input as file_write (path + content) and applies the same
allowed-folders gate as edit_file. Apply with apply_proposed_edit.

Used with propose_str_replace for best-of-N editing: stage multiple
candidate versions of a file, compare, then apply the winner.
"""

from __future__ import annotations

import json
import re

from core.config import settings
from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool
from tools.edit_file import _resolve_path
from tools.proposals import stage_proposal

# Matches the structured format produced by the agent loop for file_write:
#   "{path}:\n\n{content}"  (same as file_writer._STRUCTURED_FMT_RE)
_STRUCTURED_FMT_RE = re.compile(r"^([^\n]+?):\n\n")


def _parse_error() -> ToolResult:
    return ToolResult(
        content=(
            "Could not parse propose_write_file instruction. Provide the content in "
            "the file_write format 'path:\\n\\ncontent' or a JSON payload "
            '{"path": "...", "content": "..."}.'
        ),
        risk=RiskLevel.LOW,
        source="propose_write_file",
        success=False,
        error_type="parse_error",
        error_message="Invalid propose_write_file payload",
    )


async def propose_write_file(message: str) -> ToolResult:
    """
    Stage a full-file write proposal (validated, NOT written).

    Accepts either the structured "path:\\n\\ncontent" format (same as
    file_write, produced by the agent loop) or a JSON payload.
    """
    if message.strip().startswith("{"):
        try:
            payload = json.loads(message)
            if not isinstance(payload, dict):
                return _parse_error()
            raw_path = str(payload.get("path", "")).strip()
            content = str(payload.get("content", ""))
        except (json.JSONDecodeError, TypeError, ValueError):
            return _parse_error()
    else:
        structured = _STRUCTURED_FMT_RE.match(message)
        if not structured:
            return _parse_error()
        raw_path = structured.group(1).strip().rstrip(":")
        content = message[structured.end() :]

    if not raw_path:
        return ToolResult(
            content="'path' is required for propose_write_file",
            risk=RiskLevel.LOW,
            source="propose_write_file",
            success=False,
            error_type="validation_error",
            error_message="Missing required field 'path'",
        )

    # Resolve exactly like edit_file (absolute, expandvars/expanduser,
    # cwd-relative) so apply_proposed_edit can look the proposal up.
    filepath = _resolve_path(raw_path)

    # Same allowed-folders gate as edit_file — a proposal for
    # ~/.ssh/authorized_keys must never be stagged, let alone applied.
    if not settings.is_path_allowed(filepath):
        return ToolResult(
            content=(
                f"Access denied: '{filepath}' is outside the allowed folders. "
                f"File writing is restricted to your user directories for safety."
            ),
            risk=RiskLevel.HIGH,
            source="propose_write_file",
            success=False,
            error_type="permission_denied",
            error_message=f"Path not in allowed read paths: {filepath}",
        )

    # Stage the proposed content — no disk write.
    stage_proposal(str(filepath), content)

    size = len(content.encode())
    lines = len(content.splitlines()) if content else 0
    return ToolResult(
        content=(
            f"## Staged write proposal (not yet written)\n\n"
            f"**{filepath}** — {size} bytes, {lines} lines staged. "
            f"Call `apply_proposed_edit(path={filepath})` to write it, or stage "
            f"another candidate for the same file and compare."
        ),
        risk=RiskLevel.LOW,
        source="propose_write_file",
        success=True,
        metadata={
            "path": str(filepath),
            "staged": True,
            "applied": False,
            "bytes": size,
            "lines": lines,
            "filename": filepath.name,
        },
    )


# Register the tool — Intent.PROPOSE_WRITE → propose_write_file
register_tool(
    Intent.PROPOSE_WRITE,
    propose_write_file,
    description=(
        "Stage a full-file write as a PROPOSAL without touching disk. Takes the same "
        "arguments as file_write (path + content). The content is stored in a per-run "
        "proposal registry; call apply_proposed_edit to write it. Use with "
        "propose_str_replace for best-of-N editing: stage multiple candidate versions "
        "of a file, compare, then apply the winner."
    ),
    cost=0.01,
    latency_ms=50,
    parallelizable=True,  # pure registry write — safe to stage concurrently
)
