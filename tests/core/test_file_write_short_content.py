"""file_write's short-content guard, and what a rejection looks like from outside.

The guard exists to catch placeholder bodies ("read", "yes") a model passes
when it means another tool. It used to refuse a short body the USER spelled out
(`containing "eta"`), so the model padded the file with invented text; and the
rejection emitted no result event, so the UI tool call sat at "started" forever.
"""
from unittest.mock import MagicMock, patch

import core.config as config_module
import pytest
from core.agent.loop import _content_requested_by_user, _user_message_text


class TestContentRequestedByUser:
    REQ = 'Create a file notes.txt containing "eta", then read it back and confirm.'

    def test_quoted_literal_is_requested(self):
        assert _content_requested_by_user("eta", self.REQ)
        assert _content_requested_by_user("ETA", self.REQ)  # case-insensitive
        assert _content_requested_by_user("42", "put “42” in a file")
        assert _content_requested_by_user("ok", "write 'ok' into flag.txt")

    def test_literal_after_an_explicit_cue_is_requested(self):
        assert _content_requested_by_user("eta", "make notes.txt containing eta.")
        assert _content_requested_by_user("yes", "a file that says yes")

    def test_a_word_merely_in_the_sentence_is_not_requested(self):
        # "read" appears in the request, but not as a literal the user asked for.
        assert not _content_requested_by_user("read", self.REQ)
        assert not _content_requested_by_user("code", "write some code to a file")

    def test_placeholders_and_empty_are_not_requested(self):
        assert not _content_requested_by_user("yes", "write a file about cats")
        assert not _content_requested_by_user("", self.REQ)
        assert not _content_requested_by_user("eta", "")

    def test_user_message_text_can_be_uncapped(self):
        long_req = "x " * 300 + '"eta"'
        msgs = [{"role": "user", "content": long_req}]
        assert len(_user_message_text(msgs)) == 200
        assert _user_message_text(msgs, limit=None) == long_req


def _allow(tmp_path):
    patcher = patch.object(config_module, "_allowed_user_folders", return_value=[str(tmp_path)])
    patcher.start()
    return patcher


async def _run_write(tmp_path, request, content, target_name="short.txt", extra_args=None):
    """Drive the real loop once: the model calls file_write(content), then answers."""
    from adapters.ollama import ToolCallResult
    from core.agent.loop import AgentLoop
    from core.models import Intent, StreamChunk
    from core.obs import ObsCollector

    target = tmp_path / target_name
    seen = {"n": 0}

    async def chat_with_tools(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen["n"] += 1
        if seen["n"] == 1:
            return ToolCallResult(
                tool_name="file_write",
                tool_args={"path": str(target), "content": content, **(extra_args or {})},
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
    obs = ObsCollector()
    loop = AgentLoop(adapter=MagicMock())
    patcher = _allow(tmp_path)
    try:
        with (
            patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x),
            patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x),
        ):
            async for _ in loop.run(
                messages=[{"role": "user", "content": request.format(path=target)}],
                intent=Intent.FILE_WRITE,
                initial_tool_result=None,
                available_tools=[],
                adapter=adapter,
                obs=obs,
            ):
                pass
    finally:
        patcher.stop()
    return target, obs.drain_matching({"tool_call"})


@pytest.mark.asyncio
async def test_short_body_the_user_asked_for_is_written_exactly(tmp_path):
    target, calls = await _run_write(tmp_path, 'Create {path} containing "eta"', "eta")
    assert target.read_text(encoding="utf-8") == "eta"
    assert any(c.data.get("status") == "done" for c in calls)
    assert not any(c.data.get("status") == "failed" for c in calls)


@pytest.mark.asyncio
async def test_a_tiny_body_for_a_new_file_is_written_and_flagged_not_blocked(tmp_path):
    """Whether "yes" is a placeholder cannot be known without a model, so a new file gets it. The
    model — which can tell — is shown exactly what landed and told to write again if that was wrong."""
    target, calls = await _run_write(tmp_path, "Write a poem about cats to {path}", "yes")
    assert target.read_text(encoding="utf-8") == "yes"
    done = [c for c in calls if c.data.get("status") == "done"]
    assert done and "only 3 bytes" in done[0].data.get("output", "")
    assert not any(c.data.get("status") == "failed" for c in calls)


@pytest.mark.asyncio
async def test_an_empty_body_never_creates_a_file(tmp_path):
    target, calls = await _run_write(tmp_path, "Write a poem about cats to {path}", "   ")
    assert not target.exists()
    assert not any(c.data.get("status") == "done" for c in calls)


@pytest.mark.asyncio
async def test_a_stub_that_would_replace_a_real_file_is_refused(tmp_path):
    original = tmp_path / "notes.txt"
    original.write_text("real notes worth keeping, several words long", encoding="utf-8")
    target, calls = await _run_write(tmp_path, "Update the notes in {path}", "ok", target_name="notes.txt")
    assert target.read_text(encoding="utf-8").startswith("real notes")
    assert "REJECTED" in next(c for c in calls if c.data.get("status") == "failed").data.get("output", "")


@pytest.mark.asyncio
async def test_the_model_can_confirm_a_deliberate_overwrite_with_a_signal(tmp_path):
    """The refusal to replace a real file with a stub is a question, not a wall: overwrite=true answers it."""
    original = tmp_path / "flag.txt"
    original.write_text("old contents that are long enough to matter", encoding="utf-8")
    target, calls = await _run_write(
        tmp_path, "Reset the flag in {path}", "0", target_name="flag.txt", extra_args={"overwrite": True}
    )
    assert target.read_text(encoding="utf-8") == "0"
    assert not any(c.data.get("status") == "failed" for c in calls)
