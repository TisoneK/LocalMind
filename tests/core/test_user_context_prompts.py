"""Prompt-injection surface for the fused user context.

Pins two contract lines in the prompt assembly:

- the native-bootstrap parent prompt carries the full `User context` block
  next to the System line, so the FIRST call already has the deduction made;
- the per-turn environment context carries a one-line summary (cheap on
  every iteration), while the CHAT system prefix stays byte-stable — the
  chat surface still receives it via the trailing turn-context env.
"""

from __future__ import annotations

import pytest

from core.agent.prompts import build_agent_system_prompt
from core.context_builder import _build_environment_context
from core.models import Intent
from core.user_context import set_cached_fused
from tools import available_tools


@pytest.fixture()
def fused_ke():
    set_cached_fused({"country": "KE", "language": "en", "confidence": "high"})
    yield
    set_cached_fused({})


def test_bootstrap_prompt_carries_user_context(fused_ke):
    # The block rides the native-bootstrap parent surface — the same one the
    # boot-cached System summary uses — so the FIRST call already has the
    # deduction made.
    prompt = build_agent_system_prompt(
        intent=Intent.SHELL,
        available_tools=available_tools(),
        tool_defs=None,
        native_bootstrap=True,
    )
    assert "## User context" in prompt
    assert "Kenya" in prompt


def test_chat_prefix_stays_byte_stable_with_user_context(fused_ke):
    # The CHAT prefix is the cache-critical surface: no per-machine value
    # may leak into it. (Chat turns still get the context via the loop's
    # trailing turn-context environment.)
    prompt = build_agent_system_prompt(intent=Intent.CHAT, available_tools=[])
    assert "Kenya" not in prompt and "## User context" not in prompt


def test_turn_context_env_carries_the_one_liner(fused_ke):
    env = _build_environment_context(include_tool_list=False)
    assert "User context: Kenya (KE) | English" in env


def test_turn_context_env_compact_variant(fused_ke):
    env = _build_environment_context(compact=True)
    assert "User context: Kenya (KE) | English" in env


def test_env_reads_not_deduced_when_cache_empty():
    set_cached_fused({})
    try:
        env = _build_environment_context(include_tool_list=False)
        assert "User context: not deduced" in env
    finally:
        set_cached_fused({})


def test_fast_path_direct_chat_carries_user_context(fused_ke):
    # The trivial/conversational fast path bypasses the agent loop entirely;
    # its one system prompt must still carry the deduced context, or
    # location questions get "I'd need access to your location" on the
    # exact turns that skip every other injection surface.
    import asyncio
    import types

    from core.trivial_input import _direct_chat_response

    class _RecordingAdapter:
        def __init__(self):
            self.calls = []

        async def chat(self, messages, intent=None):
            self.calls.append(list(messages))
            yield types.SimpleNamespace(
                text="ok", done=False, usage={}, thinking=None, error=None
            )

    adapter = _RecordingAdapter()

    async def run():
        async for _ in _direct_chat_response(
            "What is my country?", adapter, None, "You are LocalMind."
        ):
            pass

    asyncio.run(run())
    system = adapter.calls[0][0]["content"]
    assert "User context" in system
    assert "Kenya (KE)" in system
