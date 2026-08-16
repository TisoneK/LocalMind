"""
ADR-41 regression tests (Session 254): stop disabling GLM's reasoning.

B-2026-08-16-3: `_add_provider_params` unconditionally sent
`thinking: {type: disabled}` for z.ai — a workaround for the ThinkingDispatcher's
10s timeout, a component DELETED in Session 239. That crippled GLM-4.5-flash
into ~28-token terse answers. These tests pin the fix:

1. z.ai thinking DEFAULTS ON (enabled) — the model's reasoning is restored.
2. Tunable via LOCALMIND_THINKING=disabled (opt-out for latency-sensitive use).
3. GLM-5.3 (which rejects `thinking.type=disabled` per z.ai docs) is never
   disabled, even when LOCALMIND_THINKING=disabled.
4. LOCALMIND_REASONING_EFFORT is sent ONLY for GLM-5.2+ models (per z.ai docs,
   reasoning_effort is 5.2+ only; GLM-4.5-flash does NOT support it).
5. The adapter exposes `thinking_enabled` so the loop can pick a thinking-aware
   per-call timeout (REASONING_PER_CALL_TIMEOUT_SECS instead of 45s).
6. The loop forwards StreamChunk.thinking to the SSE route on ALL final-answer
   paths (MiniMax buffer, mid-stream, _force_final_answer) — reasoning reaches
   the ThinkingBlock instead of being dropped.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import core.config as config_mod
from adapters.openai_compat import OpenAICompatAdapter
from core.agent.constants import PER_CALL_TIMEOUT_SECS, REASONING_PER_CALL_TIMEOUT_SECS
from core.models import StreamChunk

# ── 1-4. Thinking policy in _add_provider_params ────────────────────────────


class TestZaiThinkingPolicy:
    """Thinking policy reads the Settings singleton (Settings UI / settings.json
    wins over env — the adapter no longer reads os.getenv directly)."""

    def test_zai_thinking_enabled_by_default(self, monkeypatch):
        """z.ai must NOT send thinking:{type:disabled} anymore — the default is ON."""
        monkeypatch.setenv("ZAI_API_KEY", "sk-fake-test-key")
        monkeypatch.setattr(config_mod.settings, "localmind_thinking", "enabled")
        adapter = OpenAICompatAdapter(provider="zai", model_override="glm-4.5-flash")
        payload = adapter._add_provider_params({})
        assert payload.get("thinking") == {"type": "enabled"}, (
            f"ADR-41: z.ai thinking must default to enabled, got {payload.get('thinking')!r}"
        )
        assert adapter.thinking_enabled is True

    def test_zai_thinking_disabled_via_settings(self, monkeypatch):
        """Settings thinking=disabled (Settings UI / LOCALMIND_THINKING) is the opt-out."""
        monkeypatch.setenv("ZAI_API_KEY", "sk-fake-test-key")
        monkeypatch.setattr(config_mod.settings, "localmind_thinking", "disabled")
        adapter = OpenAICompatAdapter(provider="zai", model_override="glm-4.5-flash")
        payload = adapter._add_provider_params({})
        assert payload.get("thinking") == {"type": "disabled"}
        assert adapter.thinking_enabled is False

    def test_glm_53_never_disabled(self, monkeypatch):
        """GLM-5.3 rejects thinking.type=disabled (z.ai docs) — force enabled."""
        monkeypatch.setenv("ZAI_API_KEY", "sk-fake-test-key")
        monkeypatch.setattr(config_mod.settings, "localmind_thinking", "disabled")
        adapter = OpenAICompatAdapter(provider="zai", model_override="glm-5.3")
        payload = adapter._add_provider_params({})
        assert payload.get("thinking") == {"type": "enabled"}, (
            f"GLM-5.3 must never receive thinking:disabled, got {payload.get('thinking')!r}"
        )
        assert adapter.thinking_enabled is True

    def test_reasoning_effort_applies_to_all_glm(self, monkeypatch):
        """Session 262: the reasoning_effort 'thinking level' applies to ALL GLM
        versions, not just >=5.2 — glm-4.5-flash was live-verified to ACCEPT it
        (and its unbounded thinking was the user's "thinks too hard" complaint).
        A version that rejects it degrades via the 400-retry, so this stays
        additive."""
        monkeypatch.setenv("ZAI_API_KEY", "sk-fake-test-key")
        monkeypatch.setattr(config_mod.settings, "localmind_reasoning_effort", "high")

        for model in ("glm-4.5-flash", "glm-5.2"):
            a = OpenAICompatAdapter(provider="zai", model_override=model)
            payload = a._add_provider_params({})
            assert payload.get("reasoning_effort") == "high", (
                f"{model} must carry the reasoning_effort thinking level — got "
                f"{payload.get('reasoning_effort')!r}"
            )

    def test_no_thinking_param_for_non_zai(self, monkeypatch):
        """Other providers never get the z.ai-specific thinking request param —
        but B-7 makes thinking_enabled True for them (enables the Thinker +
        thinking-aware timeout; the request param stays absent)."""
        monkeypatch.setenv("ZEN_API_KEY", "sk-fake-test-key")
        adapter = OpenAICompatAdapter(provider="zen", model_override="deepseek-v4-flash-free")
        payload = adapter._add_provider_params({})
        assert "thinking" not in payload  # the zai-only request param never leaks
        assert adapter.thinking_enabled is True  # B-7: Thinker applies to all capable models

    def test_thinking_enabled_tunable_off_for_non_zai(self, monkeypatch):
        """B-7: LOCALMIND_THINKING=disabled turns the Thinker/timeout off for
        non-zai providers too (and still no request param)."""
        monkeypatch.setenv("ZEN_API_KEY", "sk-fake-test-key")
        monkeypatch.setattr(config_mod.settings, "localmind_thinking", "disabled")
        adapter = OpenAICompatAdapter(provider="zen", model_override="deepseek-v4-flash-free")
        payload = adapter._add_provider_params({})
        assert "thinking" not in payload
        assert adapter.thinking_enabled is False


# ── 5. Thinking-aware per-call timeout ──────────────────────────────────────


def test_reasoning_timeout_is_larger_than_plain_cap():
    """REASONING_PER_CALL_TIMEOUT_SECS must exist and be >= the plain cap
    (ADR-41: don't truncate a thinking model mid-thought on a slow free tier)."""
    assert REASONING_PER_CALL_TIMEOUT_SECS >= PER_CALL_TIMEOUT_SECS


def test_reasoning_timeout_env_configurable(monkeypatch):
    """LOCALMIND_REASONING_TIMEOUT_SECS must override the default (like
    MAX_ITERATIONS / MAX_WALL_CLOCK_SECS)."""
    import importlib

    import core.agent.constants as constants_mod

    monkeypatch.setenv("LOCALMIND_REASONING_TIMEOUT_SECS", "300")
    importlib.reload(constants_mod)
    try:
        assert constants_mod.REASONING_PER_CALL_TIMEOUT_SECS == 300.0
    finally:
        monkeypatch.delenv("LOCALMIND_REASONING_TIMEOUT_SECS", raising=False)
        importlib.reload(constants_mod)


# ── 5b. Thinking-aware plan/init/orchestrator timeouts ────────────────────


class _ThinkingAdapterStub:
    """Minimal adapter stub exposing thinking_enabled."""

    def __init__(self, thinking: bool) -> None:
        self.thinking_enabled = thinking


class _PlainAdapterStub:
    """Adapter without a thinking_enabled attribute (older stubs)."""

    pass


def test_plan_timeout_scales_with_thinking(monkeypatch):
    """_plan_timeout_for must return the larger budget when the adapter thinks
    (ADR-41: the 8s plan/init cap fires mid-thought on GLM). The Settings
    value (Settings UI) wins when present."""
    from core.agent.constants import (
        PLAN_TIMEOUT_SECS,
        REASONING_PLAN_TIMEOUT_SECS,
    )
    from core.agent.loop import _plan_timeout_for

    monkeypatch.setattr(config_mod.settings, "localmind_reasoning_plan_timeout_secs", 30.0)
    assert _plan_timeout_for(_ThinkingAdapterStub(thinking=True)) == REASONING_PLAN_TIMEOUT_SECS
    assert _plan_timeout_for(_ThinkingAdapterStub(thinking=False)) == PLAN_TIMEOUT_SECS
    # Missing attribute (pre-ADR-41 stubs) must fall back to the plain cap.
    assert _plan_timeout_for(_PlainAdapterStub()) == PLAN_TIMEOUT_SECS
    assert REASONING_PLAN_TIMEOUT_SECS >= PLAN_TIMEOUT_SECS


def test_plan_timeout_uses_settings_value(monkeypatch):
    """A custom Settings UI value must override the module default."""
    from core.agent.loop import _plan_timeout_for

    monkeypatch.setattr(config_mod.settings, "localmind_reasoning_plan_timeout_secs", 60.0)
    assert _plan_timeout_for(_ThinkingAdapterStub(thinking=True)) == 60.0


def test_per_call_timeout_scales_with_thinking(monkeypatch):
    """The per-iteration LLM-call timeout must use the reasoning budget when
    the adapter thinks (ADR-41: don't truncate mid-thought on a slow tier)."""
    from core.agent.constants import PER_CALL_TIMEOUT_SECS
    from core.agent.loop import _per_call_timeout_for

    monkeypatch.setattr(config_mod.settings, "localmind_reasoning_timeout_secs", 180.0)
    assert _per_call_timeout_for(_ThinkingAdapterStub(thinking=True)) == 180.0
    assert _per_call_timeout_for(_ThinkingAdapterStub(thinking=False)) == PER_CALL_TIMEOUT_SECS


def test_orchestrator_timeout_scales_with_thinking(monkeypatch):
    """The orchestrator's planning wait must use the larger budget when the
    adapter thinks — same mid-thought truncation risk as the plan path."""
    from core.agent.constants import ORCHESTRATOR_TIMEOUT_SECS
    from core.agent.orchestrator import _orchestrator_timeout_for

    monkeypatch.setattr(config_mod.settings, "localmind_reasoning_plan_timeout_secs", 30.0)
    assert _orchestrator_timeout_for(_ThinkingAdapterStub(thinking=True)) >= ORCHESTRATOR_TIMEOUT_SECS
    assert _orchestrator_timeout_for(_ThinkingAdapterStub(thinking=False)) == ORCHESTRATOR_TIMEOUT_SECS
    assert _orchestrator_timeout_for(_PlainAdapterStub()) == ORCHESTRATOR_TIMEOUT_SECS


# ── 6. The loop forwards thinking on final-answer paths ─────────────────────


class _ToolThenThinkingAdapter:
    """Stub adapter: call 1 returns a tool call; the next call streams a final
    answer with interleaved reasoning (GLM thinking) + long text so BOTH the
    MiniMax buffer path and the mid-stream path are exercised."""

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, temperature=0.1, intent="chat"):
        # Plain-chat path (parent init + _force_final_answer). The init path
        # parses JSON from text; the force-final path streams the answer.
        yield StreamChunk(text='{"mode": "execute"}', done=False)
        yield StreamChunk(text="", done=True)

    async def chat_with_tools(self, messages, tools, temperature=0.3, intent=None, tool_choice=None):
        self.calls += 1
        if self.calls == 1:
            from adapters.ollama import ToolCallResult

            return ToolCallResult(
                tool_name="shell",
                tool_args={"command": "echo hi"},
                raw_content="I'll run a quick check.",
            )

        async def _stream():
            # GLM-style: reasoning interleaved with a LONG answer (>2000 chars
            # so the MiniMax buffer breaks and the tail streams mid-stream).
            yield StreamChunk(text="", thinking="Let me think about this carefully. ", done=False)
            yield StreamChunk(text="", thinking="The user asked for a summary. ", done=False)
            yield StreamChunk(text="Here is the complete answer: ", done=False)
            block = "lorem ipsum dolor sit amet " * 120  # >2000 chars
            for i in range(0, len(block), 50):
                yield StreamChunk(text=block[i : i + 50], done=False)
            yield StreamChunk(text="", thinking="Final thought before wrapping up. ", done=False)
            yield StreamChunk(text="The summary of everything.", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()


def _collect(loop, adapter) -> list[StreamChunk]:
    async def _run():
        from core.models import Intent

        return [
            chunk
            async for chunk in loop.run(
                messages=[{"role": "user", "content": "summarize this"}],
                intent=Intent.CHAT,
                initial_tool_result=None,
                available_tools=[],
                adapter=adapter,
            )
        ]

    return asyncio.run(_run())


def test_loop_forwards_thinking_on_final_answer():
    """The agent loop must NOT drop StreamChunk.thinking on the final-answer
    streaming path — reasoning reaches the ThinkingBlock AND the answer lands."""
    from core.agent.loop import AgentLoop

    adapter = _ToolThenThinkingAdapter()

    async def _fake_dispatch(tool_intent, tool_input, **kwargs):
        from core.models import RiskLevel, ToolResult

        return ToolResult(content="done", risk=RiskLevel.LOW, source="shell", success=True), False, 0

    with patch("core.agent.loop.dispatch_with_retry", side_effect=_fake_dispatch):
        chunks = _collect(AgentLoop(adapter=adapter), adapter)

    thinking = "".join(chunk.thinking for chunk in chunks if chunk.thinking)
    assert "Let me think about this carefully" in thinking, (
        f"Reasoning must reach the loop output — got thinking={thinking!r}"
    )
    assert "Final thought before wrapping up" in thinking, (
        f"mid-stream reasoning must reach the loop output — got thinking={thinking!r}"
    )
    text = "".join(chunk.text for chunk in chunks)
    assert "summary of everything" in text, f"the answer must still land after thinking — got tail={text[-200:]!r}"


def test_force_final_answer_forwards_thinking():
    """_force_final_answer (hit-limit path) must forward thinking too — its
    StreamChunk(thinking=...) must reach the loop's output."""
    from core.agent.loop import AgentLoop

    adapter = _ToolThenThinkingAdapter()

    async def _fake_dispatch(tool_intent, tool_input, **kwargs):
        from core.models import RiskLevel, ToolResult

        return ToolResult(content="done", risk=RiskLevel.LOW, source="shell", success=True), False, 0

    loop = AgentLoop(adapter=adapter)
    with patch("core.agent.loop.dispatch_with_retry", side_effect=_fake_dispatch):
        # Drive the loop onto the hit-limit path: wall clock effectively 0.
        with patch("core.agent.loop.MAX_ITERATIONS", 1):
            with patch("core.agent.loop.MAX_WALL_CLOCK_SECS", 0.0):
                chunks = _collect(loop, adapter)

    # The hit-limit path streams the trace summary / forced final answer.
    text = "".join(chunk.text for chunk in chunks)
    assert text.strip(), "a final answer must be produced on the hit-limit path"
    # The forced-final synthesis re-yields chunks; nothing may crash and the
    # loop must terminate cleanly (done chunk present).
    assert any(chunk.done for chunk in chunks), "loop must emit a done chunk"


# ── 7. Empty-after-reasoning recovery (Session 256) ────────────────────────
# Live user bug (z.ai/glm-4.5-flash, thinking ON): iter-1 called a tool,
# iter-2 streamed reasoning but returned NO content and NO tool call, and the
# whole turn failed with empty_response. The loop must do ONE bounded retry
# with a nudge when the stream contained reasoning, and still fail fast on a
# second consecutive empty.


class _EmptyAfterToolAdapter:
    """call 1 → shell tool call; call 2 → reasoning-only (no content, no tool
    call — the Session 256 bug); call 3 → final answer with thinking."""

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, temperature=0.1, intent="chat"):
        yield StreamChunk(text='{"mode": "execute"}', done=False)
        yield StreamChunk(text="", done=True)

    async def chat_with_tools(self, messages, tools, temperature=0.3, intent=None, tool_choice=None):
        self.calls += 1
        if self.calls == 1:
            from adapters.ollama import ToolCallResult

            return ToolCallResult(
                tool_name="shell",
                tool_args={"command": "echo hi"},
                raw_content="I'll run a quick check.",
            )
        if self.calls == 2:

            async def _think_only():
                # GLM-style: reasoning streams, then the stream ends with no
                # content and no tool call.
                yield StreamChunk(text="", thinking="I should look at the desktop first. ", done=False)
                yield StreamChunk(text="", thinking="The user wants a recipe. ", done=False)
                yield StreamChunk(text="", done=True)

            return _think_only()

        async def _final():
            yield StreamChunk(text="", thinking="Let me finalize. ", done=False)
            yield StreamChunk(text="Here is the complete recipe: bake salmon with lemon. ", done=False)
            yield StreamChunk(text="", done=True)

        return _final()


def _collect_with_dispatch(loop, adapter, adapter_cls=_EmptyAfterToolAdapter):
    async def _fake_dispatch(tool_intent, tool_input, **kwargs):
        from core.models import RiskLevel, ToolResult

        return ToolResult(content="done", risk=RiskLevel.LOW, source="shell", success=True), False, 0

    with patch("core.agent.loop.dispatch_with_retry", side_effect=_fake_dispatch):
        return _collect(loop, adapter)


def test_empty_after_reasoning_recovers_with_nudge():
    """A reasoning-only response (no text, no tool call) must NOT fail the
    turn — the loop nudges once and the model's next call completes it."""
    from core.agent.loop import AgentLoop

    adapter = _EmptyAfterToolAdapter()
    chunks = _collect_with_dispatch(AgentLoop(adapter=adapter), adapter)

    text = "".join(chunk.text for chunk in chunks)
    assert "complete recipe" in text, (
        f"the turn must recover after the reasoning-only call — got tail={text[-200:]!r}"
    )
    # tool call + reasoning-only + nudge-retry final = 3 LLM calls.
    assert adapter.calls == 3, f"expected 3 chat_with_tools calls, got {adapter.calls}"
    # The reasoning from BOTH the empty call and the final call reaches the UI.
    thinking = "".join(chunk.thinking for chunk in chunks if chunk.thinking)
    assert "desktop first" in thinking and "finalize" in thinking


def test_second_empty_after_reasoning_still_fails_fast():
    """The nudge is BOUNDED: after _MAX_EMPTY_REASONING_RECOVERIES consecutive
    reasoning-only responses, the loop still fails fast with the honest
    evidence fallback (think-only model protection from ADR-41 stays intact)."""
    from core.agent.loop import _MAX_EMPTY_REASONING_RECOVERIES, AgentLoop

    adapter = _EmptyAfterToolAdapter()
    # Make every post-tool call reasoning-only so the retries exhaust.
    adapter.chat_with_tools = _always_empty_after_tool(adapter)
    chunks = _collect_with_dispatch(AgentLoop(adapter=adapter), adapter)

    text = "".join(chunk.text for chunk in chunks)
    assert "empty response" in text.lower() or "what actually ran" in text.lower(), (
        f"exhausted retries must fail with the evidence fallback — got tail={text[-300:]!r}"
    )
    assert _MAX_EMPTY_REASONING_RECOVERIES == 2
    # tool call + recovery-budget empty calls + 1 final empty = total calls.
    assert adapter.calls == 1 + _MAX_EMPTY_REASONING_RECOVERIES + 1


def _always_empty_after_tool(adapter):
    """Replace the stub so EVERY post-tool call is reasoning-only, counting
    every call (call 1 = the tool call, then all-think-only)."""
    original = adapter.chat_with_tools

    async def _patched(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        adapter.calls += 1
        if adapter.calls == 1:
            return await original(messages, tools, temperature=temperature, intent=intent, tool_choice=tool_choice)

        async def _think_only():
            yield StreamChunk(text="", thinking="Still thinking... ", done=False)
            yield StreamChunk(text="", done=True)

        return _think_only()

    return _patched


def test_reasoning_wall_clock_env_configurable(monkeypatch):
    """LOCALMIND_REASONING_MAX_WALL_CLOCK_SECS overrides the thinking wall-clock
    default (>= 180), and the module default exists."""
    import importlib

    import core.agent.constants as constants_mod

    assert constants_mod.REASONING_MAX_WALL_CLOCK_SECS >= 180.0
    monkeypatch.setenv("LOCALMIND_REASONING_MAX_WALL_CLOCK_SECS", "600")
    importlib.reload(constants_mod)
    try:
        assert constants_mod.REASONING_MAX_WALL_CLOCK_SECS == 600.0
    finally:
        monkeypatch.delenv("LOCALMIND_REASONING_MAX_WALL_CLOCK_SECS", raising=False)
        importlib.reload(constants_mod)
