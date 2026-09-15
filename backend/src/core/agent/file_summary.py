"""Deterministic file-task summary for the final answer.

The user wants the file-task facts — paths written, bytes, what was created vs
edited — visible in the summary right where the final output is. Free-tier
models are unreliable at reporting their own writes, so this is derived from
the ACTUAL tool timeline (the durable record), never from what the model claims:
file_write → created, edit_file/propose_write_file → modified. Same evidence
philosophy as the goal-checklist gate.
"""

from __future__ import annotations

_WRITE_TOOLS = ("file_write", "edit_file", "propose_write_file")


def _path_from_call(tc: dict) -> str | None:
    """Extract the target path from a tool-call row.

    file_write tool_args are "path:\\n\\ncontent" (trailing colon dropped);
    edit_file/propose_write_file tool_args are JSON with a "path" key.
    Mirrors sessions.py `_agent_written_paths` so the summary and the history
    endpoint agree on what counts as a written file.
    """
    import json as _json

    name = str(tc.get("name") or tc.get("tool") or "")
    if name not in _WRITE_TOOLS:
        return None
    raw_args = tc.get("tool_args") or tc.get("input") or ""
    if not isinstance(raw_args, str) or not raw_args.strip():
        return None
    if name == "file_write":
        head = raw_args.split("\n\n", 1)[0].strip()
        return head.rstrip(":").strip() if head else None
    try:
        parsed = _json.loads(raw_args)
        if isinstance(parsed, dict) and parsed.get("path"):
            return str(parsed["path"]).strip()
    except Exception:
        return None
    return None


def _bytes_from_call(tc: dict) -> int | None:
    """Approximate written bytes for file_write (content after the path header)."""
    if str(tc.get("name") or tc.get("tool") or "") != "file_write":
        return None
    raw_args = tc.get("tool_args") or tc.get("input") or ""
    if not isinstance(raw_args, str) or not raw_args.strip():
        return None
    body = raw_args.split("\n\n", 1)
    if len(body) < 2 or not body[1].strip():
        return None
    return len(body[1].encode("utf-8"))


def build_file_task_summary(tool_calls: list) -> str:
    """Build the user-facing 'Files:' block for the final answer.

    Returns an empty string when the turn touched no files, so the caller can
    skip appending. Order-preserving: a path's FIRST occurrence decides its
    status (a write-then-edit is reported as created).
    """
    if not tool_calls:
        return ""
    lines: list[str] = []
    seen: set[str] = set()
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        name = str(tc.get("name") or tc.get("tool") or "")
        if name not in _WRITE_TOOLS:
            continue
        path = _path_from_call(tc)
        if not path or path in seen:
            continue
        seen.add(path)
        if name == "file_write":
            size = _bytes_from_call(tc)
            if size is not None:
                lines.append(f"- `{path}` (created, {size} B)")
            else:
                lines.append(f"- `{path}` (created)")
        else:
            lines.append(f"- `{path}` (modified)")
    if not lines:
        return ""
    return "\n\n📁 Files:\n" + "\n".join(lines)
