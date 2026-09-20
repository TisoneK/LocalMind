"""Input selection by stage: a call that already holds a tool result does not
re-send the guidance for choosing its FIRST tool.

Live (DeepSeek deepseek-chat, fixed fixture, 5 task shapes x 10 rounds, serial,
interleaved): correct 50/50 with the full prompt on every call vs 49/50 with the
selection-only sections dropped on later calls, and the first tool was right every
time (system_search for a find, no tool for a system-facts question). Trimming a
RULE is different: a prompt that lost the multi-part rule ended lookups after one
tool 15 times out of 15 — so every rule must stay."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from adapters.ollama import ToolCallResult
from core.agent.loop import AgentLoop
from core.agent.prompts import (
    _CORE_HEAD,
    _SAFETY_HEAD,
    _STYLE_HEAD,
    _TOOLS_HEAD,
    build_agent_system_prompt,
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
def prompt() -> str:
    from agents.parent.context_builder import _PARENT_CONTRACT

    return build_agent_system_prompt(
        intent=Intent.ANALYZE,
        available_tools=[],
        tool_defs=TOOL_DEFINITIONS,
        native_bootstrap=True,
        agent_context=_PARENT_CONTRACT,
    )


def test_the_builder_emits_every_section_head_in_order(prompt):
    a, b, c, d = (prompt.find(h) for h in (_STYLE_HEAD, _TOOLS_HEAD, _CORE_HEAD, _SAFETY_HEAD))
    assert 0 <= a < b < c < d


def test_a_later_call_keeps_every_rule_and_drops_only_first_tool_guidance(prompt):
    out = staged_system_prompt(prompt, with_tools=True)
    for rule in RULES:
        assert rule in prompt and rule in out, rule
    for gone in SELECTION_ONLY:
        assert gone in prompt and gone not in out, gone
    assert "describe_tool" in out  # a later call may still need an on-demand tool
    assert _SAFETY_HEAD in out
    assert len(out) < len(prompt) * 0.8


def test_an_answer_only_call_also_drops_the_on_demand_paragraph(prompt):
    out = staged_system_prompt(prompt, with_tools=False)
    for rule in RULES:
        assert rule in out, rule
    assert _CORE_HEAD not in out and "describe_tool" not in out
    assert _SAFETY_HEAD in out
    assert len(out) < len(staged_system_prompt(prompt, with_tools=True))


def test_it_is_idempotent_and_leaves_other_prompts_alone(prompt):
    once = staged_system_prompt(prompt, with_tools=True)
    assert staged_system_prompt(once, with_tools=True) == once
    other = "You are a title generator. Produce a short title."
    assert staged_system_prompt(other, with_tools=True) == other
    assert staged_system_prompt("", with_tools=False) == ""


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
