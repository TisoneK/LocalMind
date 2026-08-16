"""
Tests for B-2026-08-02-9 (B4) — inline delegation (delegate_inline).

Covers: the happy-path in-place mutation, the allow_inline_mutation=False
rejection path, the no-scope / depth-cap guards, fail-safe rewrite
validation, the pre-mutation snapshot, the AgentLoop scope publication,
and the ContextPrunerAgent's own run() override.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from agents.base_agent import AgentConfig, BaseAgent
from agents.registry import register
from core.agent.delegation import (
    InlineMutationScope,
    get_inline_mutation_scope,
    reset_inline_mutation_scope,
    set_inline_mutation_scope,
    snapshot_messages,
    validate_rewritten_history,
)
from core.models import Intent, StreamChunk
from tools.delegate import MAX_DELEGATION_DEPTH, _current_depth, set_current_adapter
from tools.delegate_inline import delegate_inline

# ── Stub agents ──────────────────────────────────────────────────────────────


class _InlineStubAgent(BaseAgent):
    """Inline-capable stub: rewrites the parent history via the callback."""

    def __init__(self, adapter):
        super().__init__(adapter)
        self.calls = 0

    def config(self) -> AgentConfig:
        return AgentConfig(
            name="stub_pruner",
            allowed_tools=frozenset(),
            tools_enabled=False,
            allow_inline_mutation=True,
        )

    def build_context(self, messages, intent, memory_facts=None, orchestrator_context=None):
        return ""

    def is_done(self, iterations, wall_clock_secs, last_tool_result, trace):
        return True, "done"

    def description(self) -> str:
        return "stub pruner"

    async def run(self, messages, intent, initial_tool_result, available_tools,
                  confidence=1.0, adapter=None, mutate_parent_history=None, **kwargs):
        self.calls += 1
        if mutate_parent_history is not None:
            mutate_parent_history([{"role": "user", "content": "summarized"}])
        yield StreamChunk(text="pruned to 1 message", done=True)


class _BadRewriteStubAgent(_InlineStubAgent):
    """Inline stub that produces an INVALID rewrite (trailing tool message)."""

    async def run(self, messages, intent, initial_tool_result, available_tools,
                  confidence=1.0, adapter=None, mutate_parent_history=None, **kwargs):
        if mutate_parent_history is not None:
            mutate_parent_history([
                {"role": "user", "content": "kept"},
                {"role": "tool", "tool_call_id": "orphan", "content": "dangling"},
            ])
        yield StreamChunk(text="rewrote with dangling tool message", done=True)


class _PlainStubAgent(_InlineStubAgent):
    """NOT inline-capable (allow_inline_mutation=False — the default)."""

    def config(self) -> AgentConfig:
        return AgentConfig(
            name="plain_stub",
            allowed_tools=frozenset(),
            tools_enabled=False,
            allow_inline_mutation=False,
        )


class _FakeTextAdapter:
    """chat_with_tools returns a plain text stream (no tool calls)."""

    def __init__(self):
        self._model = "fake-model"

    async def chat_with_tools(self, messages, tools=None, temperature=0.7,
                              intent="chat", tool_choice=None):
        async def _gen():
            yield StreamChunk(text="hello from fake", done=False)
            yield StreamChunk(text="", done=True)
        return _gen()

    async def chat(self, messages, temperature=0.7, **kwargs):
        async def _gen():
            yield StreamChunk(text="hello", done=False)
            yield StreamChunk(text="", done=True)
        return _gen()


class _RewriteAdapter:
    """chat() yields a canned text (async generator, like the real adapters)."""

    def __init__(self, output: str):
        self._output = output
        self._model = "fake-rewrite"

    async def chat(self, messages, temperature=0.7, **kwargs):
        yield StreamChunk(text=self._output, done=False)
        yield StreamChunk(text="", done=True)


def _make_scope(msgs: list[dict]) -> InlineMutationScope:
    """Build a loop-style scope whose mutate validates + replaces in place."""
    scope = InlineMutationScope(run_id="test-run", messages=msgs, mutate=lambda _m: False)

    def _mutate(new_messages):
        ok, _reason = validate_rewritten_history(new_messages, original_len=len(msgs))
        if not ok:
            return False
        msgs[:] = new_messages
        scope.applied = True
        return True

    scope.mutate = _mutate
    return scope


# ── delegate_inline tool ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delegate_inline_applies_mutation_in_place():
    """Happy path: the child rewrites the parent's history in place."""
    register("stub_pruner_inline_ok", _InlineStubAgent)
    msgs = [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "long answer"},
    ]
    scope = _make_scope(msgs)
    token = set_inline_mutation_scope(scope)
    set_current_adapter(object())
    try:
        result = await delegate_inline(
            json.dumps({"target_agent": "stub_pruner_inline_ok", "task": "summarize"})
        )
    finally:
        reset_inline_mutation_scope(token)

    assert result.success, f"expected success, got: {result.content}"
    assert scope.applied
    assert msgs == [{"role": "user", "content": "summarized"}]
    assert result.metadata["before_count"] == 2
    assert result.metadata["after_count"] == 1
    assert result.metadata["mutated"] is True


@pytest.mark.asyncio
async def test_delegate_inline_rejects_agent_without_allow_inline_mutation():
    """Mitigation (a): agents must opt in with allow_inline_mutation=True."""
    register("stub_plain_inline_no", _PlainStubAgent)
    msgs = [{"role": "user", "content": "question"}]
    scope = _make_scope(msgs)
    token = set_inline_mutation_scope(scope)
    set_current_adapter(object())
    try:
        result = await delegate_inline(
            json.dumps({"target_agent": "stub_plain_inline_no", "task": "summarize"})
        )
    finally:
        reset_inline_mutation_scope(token)

    assert not result.success
    assert result.error_type == "inline_mutation_not_allowed"
    assert msgs == [{"role": "user", "content": "question"}], "history must be unchanged"
    assert not scope.applied


@pytest.mark.asyncio
async def test_delegate_inline_rejects_outside_agent_loop():
    """No published scope → the tool refuses (not_inline_context)."""
    set_current_adapter(object())
    result = await delegate_inline(
        json.dumps({"target_agent": "stub_pruner_inline_ok", "task": "summarize"})
    )
    assert not result.success
    assert result.error_type == "not_inline_context"


@pytest.mark.asyncio
async def test_delegate_inline_rejects_at_depth_cap():
    """Recursion depth cap applies to inline delegation too."""
    register("stub_pruner_inline_depth", _InlineStubAgent)
    msgs = [{"role": "user", "content": "question"}]
    scope = _make_scope(msgs)
    token = set_inline_mutation_scope(scope)
    set_current_adapter(object())
    depth_token = _current_depth.set(MAX_DELEGATION_DEPTH)
    try:
        result = await delegate_inline(
            json.dumps({"target_agent": "stub_pruner_inline_depth", "task": "summarize"})
        )
    finally:
        _current_depth.reset(depth_token)
        reset_inline_mutation_scope(token)

    assert not result.success
    assert result.error_type == "recursion_limit"
    assert msgs == [{"role": "user", "content": "question"}], "history must be unchanged"


@pytest.mark.asyncio
async def test_delegate_inline_fail_safe_on_invalid_rewrite():
    """A structurally invalid rewrite must NOT be applied (fail-safe)."""
    register("stub_pruner_inline_bad", _BadRewriteStubAgent)
    msgs = [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
    ]
    scope = _make_scope(msgs)
    token = set_inline_mutation_scope(scope)
    set_current_adapter(object())
    try:
        result = await delegate_inline(
            json.dumps({"target_agent": "stub_pruner_inline_bad", "task": "summarize"})
        )
    finally:
        reset_inline_mutation_scope(token)

    assert not result.success
    assert not scope.applied
    assert msgs == [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "answer"},
    ], "history must be unchanged on an invalid rewrite"
    assert result.metadata["mutated"] is False


# ── Rewrite validation (fail-safe contract) ──────────────────────────────────


def test_validate_rewritten_history_accepts_good():
    ok, reason = validate_rewritten_history(
        [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}],
        original_len=5,
    )
    assert ok
    assert not reason


def test_validate_rewritten_history_rejects_trailing_tool():
    ok, reason = validate_rewritten_history(
        [{"role": "user", "content": "a"}, {"role": "tool", "tool_call_id": "x", "content": "r"}],
        original_len=5,
    )
    assert not ok
    assert "tool" in reason  # rejected by pairing and/or trailing-tool rules


def test_validate_rewritten_history_rejects_growth():
    ok, reason = validate_rewritten_history(
        [{"role": "user", "content": str(i)} for i in range(5)],
        original_len=2,
    )
    assert not ok
    assert "grew" in reason


def test_validate_rewritten_history_rejects_bad_roles():
    ok, reason = validate_rewritten_history(
        [{"role": "user", "content": "a"}, {"role": "wizard", "content": "b"}],
        original_len=5,
    )
    assert not ok
    assert "invalid role" in reason


def test_validate_rewritten_history_rejects_tool_missing_call_id():
    ok, reason = validate_rewritten_history(
        [{"role": "user", "content": "a"}, {"role": "tool", "content": "no id"}],
        original_len=5,
    )
    assert not ok
    assert "tool_call_id" in reason


def test_validate_rewritten_history_rejects_dangling_mid_history_tool():
    """A tool message whose id never appeared in an assistant tool_calls must fail."""
    ok, reason = validate_rewritten_history(
        [
            {"role": "user", "content": "q"},
            {"role": "tool", "tool_call_id": "orphan", "content": "result"},
        ],
        original_len=5,
    )
    assert not ok
    assert "orphaned" in reason


def test_validate_rewritten_history_accepts_paired_tools():
    """A tool message correctly paired with its assistant tool_calls passes
    (and the history must not end on the tool message)."""
    ok, reason = validate_rewritten_history(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "x", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "result"},
            {"role": "assistant", "content": "done"},
        ],
        original_len=5,
    )
    assert ok, reason


def test_validate_rewritten_history_rejects_reused_tool_id():
    """Each tool_call id is consumed at most once — a second tool message with
    the same id is a corrupt pairing."""
    ok, reason = validate_rewritten_history(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "x", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "first"},
            {"role": "tool", "tool_call_id": "call_1", "content": "second"},
        ],
        original_len=5,
    )
    assert not ok
    assert "orphaned" in reason


# ── Snapshot ─────────────────────────────────────────────────────────────────


def test_snapshot_messages_writes_file(tmp_path, monkeypatch):
    class _FakeSettings:
        localmind_home = str(tmp_path)

    monkeypatch.setattr("core.config.settings", _FakeSettings(), raising=False)
    path = snapshot_messages([{"role": "user", "content": "hi"}], "test-run")
    assert path, "snapshot should return a path"
    assert Path(path).exists()
    data = json.loads(Path(path).read_text())
    assert data[0]["role"] == "user"
    assert data[0]["content"] == "hi"


# ── AgentLoop publishes its scope ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_loop_publishes_inline_scope():
    """AgentLoop.run() publishes a scope bound to its live loop_messages."""
    from core.agent.loop import AgentLoop

    loop = AgentLoop(_FakeTextAdapter())
    chunks = []
    async for chunk in loop.run(
        messages=[{"role": "user", "content": "hi"}],
        intent=Intent.SHELL,
        initial_tool_result=None,
        available_tools=[],
        skip_planning=True,
    ):
        chunks.append(chunk)
    assert chunks, "loop should have yielded chunks"

    scope = get_inline_mutation_scope()
    assert scope is not None, "loop must publish an inline scope"
    # Session 245 Lever 1: the loop now emits a byte-stable system prefix plus
    # a trailing turn-context system message (env/workspace/task-state), then
    # the conversation. The scope binds to the live loop_messages either way.
    assert scope.messages[0]["role"] == "system"
    roles = [m["role"] for m in scope.messages]
    assert "user" in roles, f"user turn must be present: {roles}"
    assert callable(scope.mutate)


# ── ContextPrunerAgent run() override ────────────────────────────────────────


@pytest.mark.asyncio
async def test_context_pruner_rewrites_history():
    from agents.context_pruner.agent import ContextPrunerAgent

    msgs = [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "very long answer that should be summarized"},
    ]
    applied = {"v": False}

    def mutate(new_messages):
        msgs[:] = new_messages
        applied["v"] = True
        return True

    agent = ContextPrunerAgent(
        _RewriteAdapter(
            '[{"role": "user", "content": "question"}, '
            '{"role": "assistant", "content": "short"}]'
        )
    )
    texts = []
    async for chunk in agent.run(
        messages=msgs,
        intent=Intent.CHAT,
        initial_tool_result=None,
        available_tools=[],
        mutate_parent_history=mutate,
        task="summarize",
    ):
        texts.append(chunk.text)

    assert applied["v"], "mutate_parent_history must have been called"
    assert msgs == [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "short"},
    ]
    assert any("pruned" in t for t in texts)


@pytest.mark.asyncio
async def test_context_pruner_failsafe_on_unparseable_output():
    from agents.context_pruner.agent import ContextPrunerAgent

    msgs = [{"role": "user", "content": "q"}]
    applied = {"v": False}

    def mutate(new_messages):
        applied["v"] = True
        return True

    agent = ContextPrunerAgent(_RewriteAdapter("I cannot help with that."))
    async for _chunk in agent.run(
        messages=msgs,
        intent=Intent.CHAT,
        initial_tool_result=None,
        available_tools=[],
        mutate_parent_history=mutate,
        task="summarize",
    ):
        pass

    assert not applied["v"], "no mutation on unparseable output (fail-safe)"


@pytest.mark.asyncio
async def test_context_pruner_requires_callback():
    from agents.context_pruner.agent import ContextPrunerAgent

    agent = ContextPrunerAgent(_RewriteAdapter("[]"))
    texts = []
    async for chunk in agent.run(
        messages=[{"role": "user", "content": "q"}],
        intent=Intent.CHAT,
        initial_tool_result=None,
        available_tools=[],
    ):
        texts.append(chunk.text)

    assert any("delegate_inline" in t for t in texts), (
        "pruner without a callback must explain it must be spawned inline"
    )


@pytest.mark.asyncio
async def test_context_pruner_missing_adapter_uses_constructor_adapter():
    """Without an env override, the pruner uses the constructor adapter."""
    from agents.context_pruner.agent import ContextPrunerAgent

    msgs = [{"role": "user", "content": "q"}]
    applied = {"v": False}
    seen_output = []

    class _RecordingAdapter(_RewriteAdapter):
        async def chat(self, messages, temperature=0.7, **kwargs):
            seen_output.append(messages)
            async for chunk in super().chat(messages, temperature=temperature, **kwargs):
                yield chunk

    def mutate(new_messages):
        msgs[:] = new_messages
        applied["v"] = True
        return True

    agent = ContextPrunerAgent(
        _RecordingAdapter('[{"role": "user", "content": "q"}]')
    )
    async for _chunk in agent.run(
        messages=msgs,
        intent=Intent.CHAT,
        initial_tool_result=None,
        available_tools=[],
        mutate_parent_history=mutate,
        task="summarize",
    ):
        pass

    assert applied["v"]
    assert seen_output, "the pruner must call its adapter's chat()"
    assert seen_output[0][0]["role"] == "system"
