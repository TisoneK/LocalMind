"""
Session 375: edit_file native calls work + emit the file_diff obs event.

Live trace (B-2026-08-23-18 live check, bankofai/deepseek-v4-flash): every
native edit_file call died with

    UnboundLocalError: cannot access local variable 'tool_result' ...

Root cause: the native tool-call path did `Intent(tool_name)`, but the tool
name is ``edit_file`` while the Intent value is ``file_edit`` — so
`Intent("edit_file")` raised ValueError. The outer dispatch `except` marked
the tool failed, and the failed-branch emit then referenced the never-assigned
`tool_result`. Every native edit_file call crashed the whole turn (and with
it the diff SSE event the preview dialog's Diff mode needs).

Fixes:
- `_intent_for_tool()` maps tool names → Intents (edit_file → FILE_EDIT,
  everything else by identity, unknown → SHELL).
- `tool_result` is bound to None before the dispatch try in both the native
  and MiniMax paths, so a pre-assignment exception can never leave it unbound.

These tests drive the loop with a fake adapter that makes a REAL edit_file
call and assert: the file is edited (no crash), the `file_diff` obs event
fires with hunks + the absolute path, and a malformed payload surfaces as a
failed tool call instead of crashing.
"""
from unittest.mock import MagicMock, patch

import pytest

import core.config as config_module
from adapters.ollama import ToolCallResult
from core.agent.loop import AgentLoop, _intent_for_tool
from core.models import Intent, StreamChunk
from core.obs import ObsCollector


def _adapter_that_calls(tool_name: str, tool_args: dict):
    """Fake adapter: first call returns a native tool call, later calls stream text."""
    seen = {"n": 0}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen["n"] += 1
        if seen["n"] == 1:
            return ToolCallResult(tool_name=tool_name, tool_args=tool_args, raw_content="Running")
        async def _stream():
            yield StreamChunk(text="Done.", done=False)
            yield StreamChunk(text="", done=True)
        return _stream()

    async def empty_chat(messages, temperature=0.4, **kwargs):
        return
        yield

    mock_adapter = MagicMock()
    mock_adapter.chat_with_tools = chat_with_tools
    mock_adapter.chat = empty_chat
    return mock_adapter


def _allow(tmp_path):
    """Scoped helper: allow the tmp dir so edit_file's path gate passes."""
    patcher = patch.object(config_module, "_allowed_user_folders", return_value=[str(tmp_path)])
    patcher.start()
    return patcher


async def _run_edit(loop, adapter, tmp_path, target, obs):
    with (
        patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x),
        patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x),
    ):
        async for _ in loop.run(
            messages=[{"role": "user", "content": f"edit {target}"}],
            intent=Intent.FILE_EDIT,
            initial_tool_result=None,
            available_tools=[],
            adapter=adapter,
            obs=obs,
        ):
            pass


def test_intent_for_tool_maps_edit_file():
    assert _intent_for_tool("edit_file") == Intent.FILE_EDIT
    assert _intent_for_tool("file_write") == Intent.FILE_WRITE
    assert _intent_for_tool("shell") == Intent.SHELL


@pytest.mark.asyncio
async def test_native_edit_file_edits_file_and_emits_file_diff(tmp_path):
    """A correct native edit_file call must (a) not crash, (b) edit the file,
    and (c) emit a file_diff obs event with hunks + the absolute path — the
    data source for the preview dialog's Diff mode."""
    target = tmp_path / "notes.txt"
    target.write_text("original line one\noriginal line two\n", encoding="utf-8")
    obs_collector = ObsCollector()
    loop = AgentLoop(adapter=MagicMock())
    adapter = _adapter_that_calls(
        "edit_file",
        {
            "path": str(target),
            "action": "replace",
            "search": "original line one",
            "replace": "edited line one",
            "all": True,
        },
    )
    patcher = _allow(tmp_path)
    try:
        await _run_edit(loop, adapter, tmp_path, target, obs_collector)
    finally:
        patcher.stop()

    # The edit actually landed on disk.
    assert "edited line one" in target.read_text(encoding="utf-8")

    # The diff obs event carries hunks + the path.
    diffs = obs_collector.drain_matching({"file_diff"})
    assert diffs, "expected a file_diff obs event from the successful edit"
    data = diffs[-1].data
    assert data.get("path") == str(target)
    assert data.get("diff_hunks"), "file_diff must carry structured hunks"
    assert data.get("diff_additions", 0) > 0


@pytest.mark.asyncio
async def test_invalid_edit_file_surfaces_failure_not_crash(tmp_path):
    """An unknown-action payload is a validation failure — it must surface as
    a failed tool call, never crash the loop with an unbound `tool_result`
    (the Session 375 live bug). Note: a content-only payload is NO LONGER
    malformed — it means a full-file rewrite (Session 376 aliases)."""
    target = tmp_path / "notes.txt"
    target.write_text("hello\n", encoding="utf-8")
    obs_collector = ObsCollector()
    loop = AgentLoop(adapter=MagicMock())
    adapter = _adapter_that_calls("edit_file", {"action": "nonsense", "path": str(target)})
    patcher = _allow(tmp_path)
    try:
        await _run_edit(loop, adapter, tmp_path, target, obs_collector)
    finally:
        patcher.stop()

    calls = obs_collector.drain_matching({"tool_call"})
    assert any(c.data.get("status") == "failed" for c in calls)
    # File untouched.
    assert "hello\n" == target.read_text(encoding="utf-8")
