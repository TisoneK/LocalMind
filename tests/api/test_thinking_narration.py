"""B-2026-08-24-1 / B-2026-08-30-7: curated narration is a STATUS label.

The narration helper emits a short plain-language line when each tool
STARTS — on the status_update channel (its documented home), NOT as
thinking_token. The Thinking box is reserved for the model's actual
(leak-filtered) reasoning; tool labels masquerading as thinking was the
B-2026-08-30-7 bug. These tests pin the narration helper's contract.
"""

from __future__ import annotations

import json

from api.routes.chat import _narration_sse


def _payload(sse: str | None) -> dict | None:
    if sse is None:
        return None
    assert sse.startswith("data: ")
    return json.loads(sse[len("data: "):].strip())


def test_start_events_emit_a_curated_status_line() -> None:
    p = _payload(_narration_sse("sysinfo", "started"))
    assert p is not None
    assert p["type"] == "status_update"
    assert "Checking your system" in p["status"]
    # Plain language — no tool name / internal wiring leaked.
    assert "sysinfo" not in p["status"]


def test_narration_never_emits_thinking_token() -> None:
    """B-2026-08-30-7 regression guard: tool labels must not masquerade as
    model reasoning on the thinking_token channel."""
    p = _payload(_narration_sse("web_research", "started"))
    assert p is not None
    assert p["type"] != "thinking_token"


def test_unknown_tool_gets_a_generic_line() -> None:
    p = _payload(_narration_sse("some_new_tool", "running"))
    assert p is not None and "Working on it" in p["status"]


def test_non_start_status_emits_nothing() -> None:
    assert _narration_sse("shell", "done") is None
    assert _narration_sse("shell", "failed") is None


def test_internal_tools_are_not_narrated() -> None:
    for tool in ("todo_write", "describe_tool", "create_plan", "delegate"):
        assert _narration_sse(tool, "started") is None


def test_common_tools_have_plain_language_lines() -> None:
    for tool, expect in [
        ("system_search", "Searching your files"),
        ("shell", "Running a command"),
        ("web_search", "Searching the web"),
        ("file_write", "Writing a file"),
    ]:
        p = _payload(_narration_sse(tool, "started"))
        assert p is not None and expect in p["status"]
