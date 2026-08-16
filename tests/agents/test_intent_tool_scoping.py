"""
Session 124: per-intent tool scoping regression tests.

Root cause of the 21.9K-prompt-token bug: every agent-loop step sent ALL 24
tool definitions (~24.2K chars ≈ 6K tokens) regardless of intent — a
git-status request paid the same fixed cost as web research, 4+ times over a
multi-step plan. The fix intersects the agent's toolset with
INTENT_TOOL_SCOPES so local-execution intents only see ~11 relevant tools
(~10.8K chars ≈ 2.7K tokens) — a ~55% cut in the fixed per-step tool payload.

These tests lock:
1. Every intent scope is a valid subset of AGENT_ALLOWED_TOOLS.
2. Local-execution intents exclude web/browse/proposal/subgoal tools.
3. Web intents keep their domain tools and drop local-execution tools.
4. The scoped tool-def payload is materially smaller than the full payload.
5. The AgentLoop scoping logic (intersection + metadata scoping) works.
"""

from __future__ import annotations

import json

import pytest

from core.agent.constants import (
    AGENT_ALLOWED_TOOLS,
    INTENT_TOOL_SCOPES,
)
from core.agent.loop import TOOL_DEFINITIONS, _filtered_tool_defs
from core.models import Intent


def _payload_chars(tool_names: frozenset[str]) -> int:
    defs = [td for td in TOOL_DEFINITIONS if td["function"]["name"] in tool_names]
    return len(json.dumps(defs))


def test_all_intent_scopes_are_subsets_of_allowlist():
    """Every INTENT_TOOL_SCOPES entry is a valid subset of AGENT_ALLOWED_TOOLS."""
    for intent, scope in INTENT_TOOL_SCOPES.items():
        assert scope.issubset(AGENT_ALLOWED_TOOLS), (
            f"{intent.value} scope {scope} not subset of AGENT_ALLOWED_TOOLS"
        )


def test_shell_scope_excludes_web_and_browse_tools():
    """A shell/git task must not carry web/browse tools (the 21.9K bug)."""
    scope = INTENT_TOOL_SCOPES[Intent.SHELL]
    assert "web_search" not in scope
    assert "web_fetch" not in scope
    assert "browse" not in scope
    assert "shell" in scope
    assert "git" in scope
    # Session 125: find_path is the locate-before-listing tool — always in
    # the local-execution scope.
    assert "find_path" in scope


def test_shell_scope_excludes_proposal_and_subgoal_scratchpad():
    """Best-of-N/proposal/subgoal tools are coding-agent editing extras —
    not needed for a git-status request."""
    scope = INTENT_TOOL_SCOPES[Intent.SHELL]
    for extra in ("propose_str_replace", "propose_write_file", "best_of_n_edit"):
        assert extra not in scope
    for scratch in ("add_subgoal", "update_subgoal", "create_plan"):
        assert scratch not in scope


def test_web_search_scope_keeps_web_tools_and_drops_shell():
    """WEB_SEARCH keeps its domain tools and does not carry shell."""
    scope = INTENT_TOOL_SCOPES[Intent.WEB_SEARCH]
    assert "web_search" in scope
    assert "web_fetch" in scope
    assert "shell" not in scope
    assert "git" not in scope


def test_editing_intents_keep_best_of_n_family():
    """FILE_WRITE/FILE_EDIT keep the proposal/best-of-N editing family
    (B-2026-08-02-7/11) — those are real coding-agent features."""
    for intent in (Intent.FILE_WRITE, Intent.FILE_EDIT):
        scope = INTENT_TOOL_SCOPES[intent]
        assert "best_of_n_edit" in scope
        assert "propose_str_replace" in scope
        assert "apply_proposed_edit" in scope


def test_shell_scoped_payload_is_materially_smaller():
    """The SHELL payload must be at least 40% smaller than the full set —
    this is the actual token saving behind the Session 124 fix."""
    full_chars = _payload_chars(AGENT_ALLOWED_TOOLS)
    shell_chars = _payload_chars(INTENT_TOOL_SCOPES[Intent.SHELL])
    assert shell_chars < full_chars * 0.60, (
        f"SHELL payload {shell_chars} chars not < 60% of full {full_chars}"
    )


def test_scoped_defs_respect_intent_scope():
    """_filtered_tool_defs(intent scope) returns exactly the scoped tools."""
    scope = INTENT_TOOL_SCOPES[Intent.SHELL]
    tools = _filtered_tool_defs(scope)
    names = {td["function"]["name"] for td in tools}
    assert names == scope


def test_description_trims_reduced_total_payload():
    """The verbose tool descriptions were trimmed (Session 124) — the full
    payload stays far below what untrimmed descriptions would cost. Baseline:
    the ORIGINAL pre-trim 24-tool payload was 24,229 chars. Each new tool
    adds its trimmed description: find_path (Session 125) kept 25 tools
    under    the baseline; Session 130 (observe) + Sessions 131-132 (calculator,
    csv, json, sql — B-2026-07-31-10) grew the set to 30 tools / ~25.1K
    chars. The bound is the documented durable ceiling: trims + new tools
    stay net-negative against untrimmed descriptions."""
    assert _payload_chars(AGENT_ALLOWED_TOOLS) <= 25400


# ── AgentLoop integration: intent scoping reaches the adapter ─────────────


@pytest.mark.asyncio
async def test_loop_sends_intent_scoped_tools_to_adapter():
    """AgentLoop.run() for a SHELL intent passes only the SHELL-scoped tools
    to chat_with_tools — the actual 21.9K-bug fix at the wire level."""
    from core.agent.loop import AgentLoop

    captured_tools = {}
    emitted = []

    class _StubAdapter:
        _model = "stub"

        async def chat_with_tools(self, messages, tools, **kwargs):
            captured_tools["tools"] = tools
            names = [t["function"]["name"] for t in tools]
            assert "shell" in names
            assert "git" in names
            assert "web_search" not in names  # the Session 124 fix
            assert "browse" not in names
            # Yield a plain final answer so the loop terminates quickly.
            return _FinalAnswerStream()

    loop = AgentLoop(adapter=_StubAdapter())
    async for chunk in loop.run(
        messages=[{"role": "user", "content": "git status please"}],
        intent=Intent.SHELL,
        initial_tool_result=None,
        available_tools=[{"intent": "shell", "description": "x"}, {"intent": "git", "description": "y"}],
        skip_planning=True,
    ):
        emitted.append(chunk)

    assert captured_tools, "chat_with_tools was never called"
    names = {t["function"]["name"] for t in captured_tools["tools"]}
    # ADR-40 option C: the param is the scoped CORE surface + describe_tool
    # (long-tail tools in the scope are NOT pre-loaded; the model loads one
    # with describe_tool when it needs it).
    from core.agent.tool_schemas import CORE_TOOL_NAMES

    assert names == (INTENT_TOOL_SCOPES[Intent.SHELL] & CORE_TOOL_NAMES) | {"describe_tool"}, names
    assert any(c.done for c in emitted)


@pytest.mark.asyncio
async def test_loop_respects_explicit_caller_scope_over_intent_scope():
    """When the CALLER explicitly scopes tools (allowed_tool_names — the
    execution-graph/objective path), the loop must NOT further narrow by
    intent: the graph policy is authoritative and a web tool in it must
    survive even for a SHELL intent."""
    from core.agent.loop import AgentLoop

    captured_tools = {}
    emitted = []

    class _StubAdapter2:
        _model = "stub"

        async def chat_with_tools(self, messages, tools, **kwargs):
            captured_tools["tools"] = tools
            return _FinalAnswerStream()

    loop = AgentLoop(adapter=_StubAdapter2())
    explicit_scope = frozenset({"shell", "git", "web_search"})
    async for chunk in loop.run(
        messages=[{"role": "user", "content": "git status"}],
        intent=Intent.SHELL,
        initial_tool_result=None,
        available_tools=[
            {"intent": "shell", "description": "x"},
            {"intent": "git", "description": "y"},
            {"intent": "web_search", "description": "z"},
        ],
        skip_planning=True,
        allowed_tool_names=explicit_scope,
    ):
        emitted.append(chunk)

    assert captured_tools, "chat_with_tools was never called"
    names = {t["function"]["name"] for t in captured_tools["tools"]}
    # web_search survives even though SHELL intent would normally exclude it
    assert "web_search" in names
    # ADR-40 option C: the explicit scope's core tools + describe_tool (the
    # meta-tool that loads on-demand tools).
    assert names == explicit_scope | {"describe_tool"}, names


class _FinalAnswerStream:
    """Minimal async iterator that yields one final text chunk."""

    def __init__(self):
        self._done = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._done:
            self._done = True
            from core.models import StreamChunk

            return StreamChunk(text="working tree clean", done=True)
        raise StopAsyncIteration
