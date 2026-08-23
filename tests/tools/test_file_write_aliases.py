"""
Session 376: file_write accepts free-tier model field aliases.

Mirrors the edit_file alias work: models commonly pass the destination as
`file_path`/`filepath`/`full_path` and the content as `text`/`body`/
`file_content`/`contents`/`code`/`data`. Without normalization the loop's
content-length guard rejects `{file_path, text}` as \"content too short\" and
the contract writes an empty/wrong file. Now the first attempt succeeds.

Covers:
- the normalizer itself (canonical wins, idempotent),
- the typed FileWriteContract end-to-end (file actually written),
- the agent loop's file_write branch (guard passes after normalization).
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

import core.config as config_module
from tools.contracts.schemas import FileWriteContract
from tools.file_writer import _normalize_write_payload


def _allow(tmp_path):
    patcher = patch.object(config_module, "_allowed_user_folders", return_value=[str(tmp_path)])
    patcher.start()
    return patcher


# ── normalization unit tests ────────────────────────────────────────────────


def test_path_aliases_map_to_path():
    for alias in ("file_path", "filepath", "full_path"):
        p = _normalize_write_payload({alias: "/tmp/x.txt", "content": "hi"})
        assert p["path"] == "/tmp/x.txt", alias


def test_content_aliases_map_to_content():
    for alias in ("text", "body", "file_content", "contents", "code", "data"):
        p = _normalize_write_payload({"path": "/tmp/x.txt", alias: "hello"})
        assert p["content"] == "hello", alias


def test_canonical_field_wins_over_alias():
    p = _normalize_write_payload({"path": "/tmp/keep.txt", "file_path": "/tmp/drop.txt", "content": "c", "text": "t"})
    assert p["path"] == "/tmp/keep.txt"
    assert p["content"] == "c"


def test_normalize_is_idempotent():
    p = _normalize_write_payload({"file_path": "/tmp/x.txt", "text": "hello"})
    assert _normalize_write_payload(p) == p


# ── typed contract end-to-end ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_contract_writes_with_file_path_and_text(tmp_path):
    target = tmp_path / "out.txt"
    patcher = _allow(tmp_path)
    try:
        result = await FileWriteContract().execute({"file_path": str(target), "text": "hello world"})
    finally:
        patcher.stop()
    assert result.success, result.content
    assert target.read_text(encoding="utf-8") == "hello world"


@pytest.mark.asyncio
async def test_contract_writes_with_code_alias(tmp_path):
    target = tmp_path / "app.py"
    patcher = _allow(tmp_path)
    try:
        result = await FileWriteContract().execute({"filepath": str(target), "code": "print('hi')\n"})
    finally:
        patcher.stop()
    assert result.success, result.content
    assert target.read_text(encoding="utf-8") == "print('hi')\n"


# ── agent loop: the content-length guard must not reject aliased payloads ───


@pytest.mark.asyncio
async def test_loop_guard_accepts_text_alias(tmp_path):
    """The loop's file_write content-length guard ran on `content` only — a
    `{file_path, text}` payload was rejected before the contract ever saw it.
    The branch now normalizes first, so the write proceeds."""
    from adapters.ollama import ToolCallResult
    from core.agent.loop import AgentLoop
    from core.models import Intent, StreamChunk
    from core.obs import ObsCollector

    target = tmp_path / "guard.txt"
    seen = {"n": 0}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen["n"] += 1
        if seen["n"] == 1:
            return ToolCallResult(
                tool_name="file_write",
                tool_args={"file_path": str(target), "text": "written via text alias"},
                raw_content="Writing",
            )
        async def _stream():
            yield StreamChunk(text="Done.", done=False)
            yield StreamChunk(text="", done=True)
        return _stream()

    async def empty_chat(messages, temperature=0.4, **kwargs):
        return
        yield

    adapter = MagicMock()
    adapter.chat_with_tools = chat_with_tools
    adapter.chat = empty_chat

    obs_collector = ObsCollector()
    loop = AgentLoop(adapter=MagicMock())
    patcher = _allow(tmp_path)
    try:
        with (
            patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x),
            patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x),
        ):
            async for _ in loop.run(
                messages=[{"role": "user", "content": f"write {target}"}],
                intent=Intent.FILE_WRITE,
                initial_tool_result=None,
                available_tools=[],
                adapter=adapter,
                obs=obs_collector,
            ):
                pass
    finally:
        patcher.stop()

    assert target.read_text(encoding="utf-8") == "written via text alias"
    calls = obs_collector.drain_matching({"tool_call"})
    # No rejection: the call completes (started → done, never a failed guard).
    assert any(c.data.get("status") == "done" for c in calls)
