"""Prompt-injection surface for the fused user context and the stated identity.

Pins four contract lines in the prompt assembly:

- the native-bootstrap parent prompt carries the full `User context` block
  next to the System line, plus the guaranteed `About this user` block, so
  the FIRST call already has the deduction made AND the stated facts;
- the per-turn environment context carries a one-line summary of each
  (cheap on every iteration), while the CHAT system prefix stays byte-stable
  — the chat surface still receives both via the trailing turn-context env;
- the stated identity is UNCONDITIONAL: even with nothing declared, the env
  carries the declared-absent line, so "who/where am I" is answerable or
  asked about — never inferred from tool results;
- the fast path (which bypasses the loop entirely) carries both on its one
  system prompt.
"""

from __future__ import annotations

import pytest

from core.agent.prompts import build_agent_system_prompt
from core.context_builder import _build_environment_context
from core.models import Intent
from core.user_context import set_cached_fused
from core.user_profile import set_cached_profile
from tools import available_tools


@pytest.fixture()
def fused_ke():
    set_cached_fused({"country": "KE", "language": "en", "confidence": "high"})
    yield
    set_cached_fused({})


@pytest.fixture()
def stated_identity():
    set_cached_profile("Amani", "Nairobi, Kenya")
    yield
    set_cached_profile("", "")


def test_bootstrap_prompt_carries_user_context(fused_ke, stated_identity):
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
    assert "## About this user" in prompt
    assert "Amani (the user stated this in Settings)" in prompt


def test_bootstrap_identity_block_is_unconditional(fused_ke):
    # Even with nothing stated, the bootstrap prompt declares the absence —
    # the guarantee has no "only when facts exist" form.
    prompt = build_agent_system_prompt(
        intent=Intent.SHELL,
        available_tools=available_tools(),
        tool_defs=None,
        native_bootstrap=True,
    )
    assert "## About this user" in prompt
    assert "never stated" in prompt
    assert "nfer an unstated name or place" in prompt


def test_chat_prefix_stays_byte_stable_with_user_context(fused_ke, stated_identity):
    # The CHAT prefix is the cache-critical surface: no per-machine value
    # may leak into it. (Chat turns still get the context via the loop's
    # trailing turn-context environment.)
    prompt = build_agent_system_prompt(intent=Intent.CHAT, available_tools=[])
    assert "Kenya" not in prompt and "## User context" not in prompt
    # The stated identity is also boot-cached, not per-turn — but the chat
    # prefix deliberately carries nothing of it; the trailing env covers it.
    assert "Amani" not in prompt and "## About this user" not in prompt


def test_turn_context_env_carries_the_one_liner(fused_ke, stated_identity):
    env = _build_environment_context(include_tool_list=False)
    assert "User context: Kenya (KE) | English" in env
    assert '- About the user: name "Amani" and place "Nairobi, Kenya"' in env


def test_turn_context_env_compact_variant(fused_ke):
    # The compact variant feeds the init/classify call, whose budget is
    # nearly saturated: the stated identity deliberately rides only the
    # full env (which covers every iteration that ANSWERS).
    env = _build_environment_context(compact=True)
    assert "User context: Kenya (KE) | English" in env
    assert "About the user:" not in env


def test_env_reads_not_deduced_when_cache_empty():
    set_cached_fused({})
    try:
        env = _build_environment_context(include_tool_list=False)
        assert "User context: not deduced" in env
    finally:
        set_cached_fused({})


def test_env_carries_declared_absent_identity_when_nothing_stated(fused_ke):
    # The guarantee is unconditional: with nothing stated, the env line
    # still tells the model the facts are unknown and must be asked about.
    env = _build_environment_context(include_tool_list=False)
    assert "- About the user: name and place never stated" in env
    assert "never infer from tool results" in env


def test_env_clock_carries_the_zone_name(fused_ke):
    # "(UTC+03:00, Africa/Nairobi)" — when AND where the clock lives, so a
    # time answer never has to guess the zone from the offset alone.
    set_cached_fused({"timezone_name": "Africa/Nairobi", "country": "KE"})
    env = _build_environment_context(include_tool_list=False)
    assert "Current time: " in env
    # The offset is whatever this machine's clock says; the NAME comes from
    # the fused cache and must ride the same parenthesis.
    assert "Africa/Nairobi" in env
    line = next(l for l in env.splitlines() if l.startswith("- Current time:"))
    assert ", Africa/Nairobi)" in line


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


def test_fast_path_carries_stated_identity(fused_ke, stated_identity):
    # The identity guarantee has no slow-path-only form: the fast path's
    # single system prompt must tell the model WHO the user stated they are.
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
            "What is my name?", adapter, None, "You are LocalMind."
        ):
            pass

    asyncio.run(run())
    system = adapter.calls[0][0]["content"]
    assert "About the user" in system
    assert 'name "Amani"' in system
    assert 'place "Nairobi, Kenya"' in system
    assert "never guess" in system


def test_history_fallback_note_carries_both_contexts(fused_ke, stated_identity):
    # The direct-from-history fallback used to be the one agent surface
    # with NO user context at all — its system note now carries the machine
    # deduction and the stated identity like every other surface.
    from core.trivial_input import history_fallback_system_note

    note = history_fallback_system_note()
    assert "Kenya (KE)" in note
    assert 'name "Amani"' in note
    assert "never guess" in note
