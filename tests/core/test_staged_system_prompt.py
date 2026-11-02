"""Input selection by stage: a call that already holds a tool result does not
re-send the guidance for choosing its FIRST tool.

Live (DeepSeek deepseek-chat, fixed fixture, 5 task shapes x 10 rounds, serial,
interleaved): correct 50/50 with the full prompt on every call vs 49/50 with the
selection-only sections dropped on later calls, and the first tool was right every
time (system_search for a find, no tool for a system-facts question). Trimming a
RULE is different: a prompt that lost the multi-part rule ended lookups after one
tool 15 times out of 15 — so every rule must stay.

Prompt-structure registry (2026-11-01): the parent prompt is assembled from
named sections in the 4-layer doctrine order (identity -> constraints ->
relevant context -> execution guidance), so the four section heads now render
in the layer order (safety-grounding as a constraint BEFORE the style/tool
guidance), and the staged cut selects by section NAME from the same registry
the prompt was built with — it cannot drift from the structure the way the
legacy head-string find could.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from adapters.ollama import ToolCallResult
from core.agent.loop import AgentLoop
from core.agent.prompt import (
    _CORE_HEAD,
    _SAFETY_HEAD,
    _STYLE_HEAD,
    _TOOLS_HEAD,
    Band,
    build_parent_static_registry,
    staged_static_content,
    staged_system_prompt,
)
from core.agent.tool_schemas import TOOL_DEFINITIONS
from core.models import Intent, RiskLevel, StreamChunk, ToolResult
from core.obs import ObsCollector

# Every rule the model needs on a LATER call — dropping any of these caused
# premature stops or hedging in live runs.
RULES = [
    "Multi-part requests are not done until EVERY part is answered",
    "never concede a requested part",
    "no narrating your plan. Act instead of announcing",
    "Anti-hedging rules",
    "NEVER ask the user",
    "Do not claim success without evidence",
    "Check current state before any write",
    "Never emit tool-call XML",
]
SELECTION_ONLY = ["how much RAM do I have", "weather in Nairobi", "Selection hints:", "- system_search:"]


@pytest.fixture(scope="module")
def registry():
    from agents.parent.context_builder import _PARENT_CONTRACT

    return build_parent_static_registry(
        tool_defs=TOOL_DEFINITIONS,
        agent_context=_PARENT_CONTRACT,
    )


@pytest.fixture(scope="module")
def prompt(registry) -> str:
    return registry.render(Band.STATIC)


def test_the_builder_emits_every_section_head_in_layer_order(prompt):
    """The 4-layer doctrine order: safety/grounding is a CONSTRAINT and
    renders before the execution-guidance blocks — and the capability index
    (tool list) LEADS the guidance layer (the conversation-or-action
    constraint points at it, so it must survive the conversational
    relevance horizon that drops the tool-choosing sections behind it:
    style examples, selection hints, on-demand loading)."""
    d, b, a, c = (prompt.find(h) for h in (_SAFETY_HEAD, _TOOLS_HEAD, _STYLE_HEAD, _CORE_HEAD))
    assert 0 <= d < b < a < c


def test_a_later_call_keeps_every_rule_and_drops_only_first_tool_guidance(registry, prompt):
    out = staged_static_content(registry, with_tools=True)
    for rule in RULES:
        assert rule in prompt and rule in out, rule
    for gone in SELECTION_ONLY:
        assert gone in prompt and gone not in out, gone
    assert "describe_tool" in out  # a later call may still need an on-demand tool
    assert _SAFETY_HEAD in out
    assert len(out) < len(prompt) * 0.8


def test_an_answer_only_call_also_drops_the_on_demand_paragraph(registry, prompt):
    out = staged_static_content(registry, with_tools=False)
    for rule in RULES:
        assert rule in out, rule
    assert _CORE_HEAD not in out and "describe_tool" not in out
    assert _SAFETY_HEAD in out
    assert len(out) < len(staged_static_content(registry, with_tools=True))


def test_the_registry_cut_is_pure_and_prefix_preserving(registry, prompt):
    """Re-rendering never mutates the registry, and a merged prefix (the
    conversation-summary section) is carried through unstaged."""
    once = staged_static_content(registry, with_tools=True)
    assert staged_static_content(registry, with_tools=True) == once
    merged = staged_static_content(registry, with_tools=True, prefix="Session summary so far.")
    assert merged.startswith("Session summary so far.\n\n")
    assert merged[len("Session summary so far.\n\n"):] == once


def test_the_legacy_cut_still_leaves_other_prompts_alone(prompt):
    """The legacy head-string cut remains for non-registry surfaces; on a
    registry-ordered prompt its head assumptions no longer hold, so it
    must return the input UNTOUCHED (its documented no-op contract) rather
    than silently mis-cut it."""
    other = "You are a title generator. Produce a short title."
    assert staged_system_prompt(other, with_tools=True) == other
    assert staged_system_prompt("", with_tools=False) == ""


def test_staged_excludes_of_absent_sections_are_a_no_op():
    """A registry without the parent sections (any other surface) renders
    unchanged through the staged helper — cutting sections a prompt never
    had is a no-op, never an error."""
    from core.agent.prompt import SECTION_IDENTITY, Layer, SectionRegistry, make

    small = SectionRegistry()
    small.add(make(SECTION_IDENTITY, Band.STATIC, Layer.IDENTITY, 10, "You are a small surface."))
    assert staged_static_content(small, with_tools=False) == "You are a small surface."


# ── the loop applies it to LATER calls only ─────────────────────────────────────


def _stream(text):
    async def s():
        yield StreamChunk(text=text, done=False)
        yield StreamChunk(text="", done=True)

    return s()


@pytest.mark.asyncio
async def test_the_loop_sends_the_full_prompt_first_and_the_staged_one_after_a_tool_result():
    from agents.base_agent import AgentConfig
    from core.agent.constants import AGENT_ALLOWED_TOOLS

    seen: list[dict] = []
    n = {"i": 0}

    async def chat(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        n["i"] += 1
        seen.append({"system": messages[0]["content"], "tools": list(tools),
                     "has_tool_result": any(m.get("role") == "tool" for m in messages)})
        if n["i"] == 1:
            return ToolCallResult(tool_name="dir_explorer", tool_args={"operation": "list", "path": "/x"}, raw_content="")
        return _stream("The folders are alpha and beta.")

    async def dispatch(intent_name, raw_input, allowed_tool_names=None, adapter=None, **kw):
        return ToolResult(content="Contents of /x — 2 entries: alpha/, beta/", risk=RiskLevel.LOW, source="dir_explorer"), False, 0

    class _Noop:
        def __init__(self, timeout_secs=30.0):
            self.last_analysis = None

        async def consult(self, evidence, adapter, temperature=0.4):
            if False:
                yield  # pragma: no cover

    adapter = MagicMock()
    adapter.chat_with_tools = chat
    adapter.chat = lambda *a, **k: iter(())
    adapter.thinking_enabled = True
    loop = AgentLoop(adapter=MagicMock())
    cfg = AgentConfig(name="parent", max_iterations=20, allowed_tools=AGENT_ALLOWED_TOOLS)
    with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), \
         patch("core.agent.loop.dispatch_with_retry", side_effect=dispatch), \
         patch("core.agent.thinker.Thinker", _Noop):
        async for _ in loop.run(messages=[{"role": "user", "content": "list /x"}], intent=Intent.ANALYZE,
                                initial_tool_result=None, available_tools=[], adapter=adapter,
                                obs=ObsCollector(), agent_config=cfg, skip_planning=True):
            pass

    assert len(seen) >= 2
    first, later = seen[0], next(s for s in seen[1:] if s["has_tool_result"])
    assert not first["has_tool_result"] and _STYLE_HEAD in first["system"] and _TOOLS_HEAD in first["system"]
    assert _STYLE_HEAD not in later["system"] and _TOOLS_HEAD not in later["system"]
    assert "Multi-part requests are not done until EVERY part is answered" in later["system"]
    assert later["tools"], "tool schemas are untouched on a later call that may still act"
    assert len(later["system"]) < len(first["system"])
