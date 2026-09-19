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


# Statuses of a tool call that has not (yet) produced a result.
_UNFINISHED = ("started", "running", "pending", "in_progress")


def build_file_task_summary(tool_calls: list) -> str:
    """Build the user-facing 'Files:' block for the final answer.

    Returns an empty string when the turn touched no files, so the caller can
    skip appending. Order-preserving: a path's FIRST successful call decides
    its status (a write-then-edit is reported as created). A path whose every
    call failed or never finished is listed as NOT written — the block is
    evidence, so it must never say "created" for a file that was not.
    """
    if not tool_calls:
        return ""
    # path -> [first successful call (or None), first call of any outcome]
    by_path: dict[str, list] = {}
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        name = str(tc.get("name") or tc.get("tool") or "")
        if name not in _WRITE_TOOLS:
            continue
        path = _path_from_call(tc)
        if not path:
            continue
        entry = by_path.setdefault(path, [None, tc])
        status = str(tc.get("status") or "").lower()
        if entry[0] is None and status != "failed" and status not in _UNFINISHED:
            entry[0] = tc
    lines: list[str] = []
    for path, (ok, first) in by_path.items():
        if ok is None:
            status = str(first.get("status") or "").lower()
            reason = "the write did not finish" if status in _UNFINISHED else "the write failed"
            lines.append(f"- `{path}` (NOT written — {reason})")
        elif str(ok.get("name") or ok.get("tool") or "") == "file_write":
            size = _bytes_from_call(ok)
            lines.append(f"- `{path}` (created, {size} B)" if size is not None else f"- `{path}` (created)")
        else:
            lines.append(f"- `{path}` (modified)")
    if not lines:
        return ""
    return "\n\n📁 Files:\n" + "\n".join(lines)
