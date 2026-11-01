"""The per-turn relevance budget: the STATIC prefix scoped by the turn's intent.

The owner's finding (2026-10-31 greeting export): a greeting that routed to
the parent loop carried the full ~6K execution prompt — file/web/shell
policies and tool-choosing guidance a conversational turn cannot use. The
budget drops that guidance on conversational turns under ONE hard
constraint (the external-harness study's cache-discipline adoption, G2):
every budgeted render is a byte-PREFIX of the canonical render — cuts are
contiguous suffixes of the section order, never reordering, never a middle
cut (a middle cut forks the cacheable prefix into two mutually-unprefixable
variants; the budget raises instead).
"""

from __future__ import annotations

import pytest
from core.agent.prompt import (
    SOCIAL_DROP_SECTIONS,
    Band,
    Layer,
    PromptStructureError,
    RelevanceHorizon,
    SectionRegistry,
    build_parent_static_registry,
    dropped_sections_for,
    horizon_for_intent,
    horizon_from_string,
    make,
    render_static_budgeted,
)
from core.agent.prompt.budget import _assert_contiguous_suffix
from core.models import Intent


@pytest.fixture(scope="module")
def registry():
    from agents.parent.context_builder import _PARENT_CONTRACT
    from core.agent.tool_schemas import TOOL_DEFINITIONS

    return build_parent_static_registry(
        tool_defs=TOOL_DEFINITIONS,
        agent_context=_PARENT_CONTRACT,
    )


@pytest.fixture(scope="module")
def full_render(registry) -> str:
    return registry.render(Band.STATIC)


class TestHorizonMapping:
    def test_chat_maps_to_social(self):
        assert horizon_for_intent(Intent.CHAT) is RelevanceHorizon.SOCIAL

    def test_raw_chat_string_maps_to_social(self):
        assert horizon_for_intent("chat") is RelevanceHorizon.SOCIAL

    def test_task_intents_map_to_full(self):
        for intent in (Intent.SHELL, Intent.WEB_SEARCH, Intent.ANALYZE):
            assert horizon_for_intent(intent) is RelevanceHorizon.FULL

    def test_unclassified_defaults_to_full(self):
        """The budget cuts only what the classification is confident does
        not matter — an unclassified turn always gets the canonical render."""
        assert horizon_for_intent(None) is RelevanceHorizon.FULL


class TestPrefixStability:
    def test_social_render_is_a_byte_prefix_of_the_full_render(self, full_render):
        """THE hard constraint: the budgeted render never reorders or
        rewrites — it is exactly the canonical render's leading bytes, so
        provider prefix caching survives the cut in both directions."""
        registry = build_parent_static_registry(tool_defs=None, agent_context=None)
        social = render_static_budgeted(registry, RelevanceHorizon.SOCIAL)
        full = registry.render(Band.STATIC)
        assert full.startswith(social)
        assert social and len(social) < len(full)

    def test_social_keeps_the_capability_spine_and_every_constraint(self, registry, full_render):
        social = render_static_budgeted(registry, RelevanceHorizon.SOCIAL)
        # the conversation-or-action constraint points at the tool list —
        # the referenced section must survive the cut
        assert "read the tool list below" in social
        assert "Available tools" in social
        for rule in (
            "You own the user's objective end to end",
            "Multi-part requests are not done until EVERY part is answered",
            "Safety: check current state before writes",
        ):
            assert rule in social, rule

    def test_social_drops_the_tool_choosing_guidance(self, registry, full_render):
        social = render_static_budgeted(registry, RelevanceHorizon.SOCIAL)
        for policy in (
            "Style — terseness",  # style examples: the file/web/shell policy lines
            "Selection hints:",  # request-kind → tool mapping
            "Core tools (",  # on-demand loading mechanics
            "weather in Nairobi",  # the web policy example a greeting carried
            "delete the two .bin files",  # the file-destructive policy example
        ):
            assert policy in full_render and policy not in social, policy

    def test_dropped_sections_are_named_in_render_order(self, registry):
        assert dropped_sections_for(registry, RelevanceHorizon.SOCIAL) == [
            "style_examples",
            "selection_hints",
            "on_demand_loading",
        ]
        assert dropped_sections_for(registry, RelevanceHorizon.FULL) == []

    def test_full_render_is_unchanged_by_the_budget(self, registry, full_render):
        assert render_static_budgeted(registry, RelevanceHorizon.FULL) == full_render


class TestContiguousSuffixGuard:
    def test_suffix_cut_passes(self):
        _assert_contiguous_suffix(["a", "b", "c"], ("b", "c"))
        _assert_contiguous_suffix(["a", "b", "c"], ("a", "b", "c"))

    def test_middle_cut_raises(self):
        with pytest.raises(PromptStructureError, match="MIDDLE section"):
            _assert_contiguous_suffix(["a", "b", "c"], ("a", "c"))

    def test_absent_sections_are_a_no_op(self):
        _assert_contiguous_suffix(["a"], ("style_examples",))

    def test_empty_drop_is_a_no_op(self):
        _assert_contiguous_suffix(["a", "b"], ())


class TestNonParentSurfaces:
    def test_registry_without_the_drop_set_renders_unchanged(self):
        small = SectionRegistry()
        small.add(make("identity", Band.STATIC, Layer.IDENTITY, 10, "Small surface."))
        assert (
            render_static_budgeted(small, RelevanceHorizon.SOCIAL)
            == "Small surface."
        )
        assert dropped_sections_for(small, RelevanceHorizon.SOCIAL) == []


class TestHorizonRoundTrip:
    def test_persisted_value_round_trips(self):
        assert horizon_from_string("social") is RelevanceHorizon.SOCIAL
        assert horizon_from_string("full") is RelevanceHorizon.FULL

    def test_unknown_or_none_parses_to_full(self):
        assert horizon_from_string("kitchen_sink") is RelevanceHorizon.FULL
        assert horizon_from_string(None) is RelevanceHorizon.FULL


class TestDropSetContract:
    def test_drop_set_is_name_based_and_stable(self):
        assert SOCIAL_DROP_SECTIONS == (
            "style_examples",
            "selection_hints",
            "on_demand_loading",
        )


# ── the loop applies it to the FIRST call of a conversational turn ─────────────


def _stream(text):
    from core.models import StreamChunk

    async def s():
        yield StreamChunk(text=text, done=False)
        yield StreamChunk(text="", done=True)

    return s()


async def _run_loop_and_collect(intent: Intent) -> tuple[list[dict], list]:
    from unittest.mock import MagicMock, patch

    from agents.base_agent import AgentConfig
    from core.agent.constants import AGENT_ALLOWED_TOOLS
    from core.agent.loop import AgentLoop
    from core.obs import ObsCollector

    seen: list[dict] = []

    async def chat(messages, tools, temperature=0.3, intent=None, tool_choice=None):
        seen.append({"system": messages[0]["content"], "tools": list(tools)})
        return _stream("Happy to help — what shall we do?")

    adapter = MagicMock()
    adapter.chat_with_tools = chat
    adapter.chat = lambda *a, **k: iter(())
    adapter.thinking_enabled = True
    loop = AgentLoop(adapter=MagicMock())
    cfg = AgentConfig(name="parent", max_iterations=20, allowed_tools=AGENT_ALLOWED_TOOLS)
    obs = ObsCollector()

    class _Noop:
        def __init__(self, timeout_secs=30.0):
            self.last_analysis = None

        async def consult(self, evidence, adapter, temperature=0.4):
            if False:
                yield  # pragma: no cover

    with patch("core.agent.loop._filter_tool_injection", side_effect=lambda x: x), \
         patch("core.agent.loop._filter_system_leaks", side_effect=lambda x: x), \
         patch("core.agent.thinker.Thinker", _Noop):
        async for _ in loop.run(messages=[{"role": "user", "content": "hey there, sup?"}],
                                intent=intent, initial_tool_result=None, available_tools=[],
                                adapter=adapter, obs=obs, agent_config=cfg, skip_planning=True):
            pass
    events = [e.data for e in obs.history() if e.type == "relevance_budget"]
    return seen, events


@pytest.mark.asyncio
async def test_a_conversational_loop_turn_sends_the_budgeted_prefix_first():
    from core.agent.prompt import _STYLE_HEAD

    seen, events = await _run_loop_and_collect(Intent.CHAT)
    assert seen, "the loop made no model call"
    first = seen[0]["system"]
    assert "Available tools" in first, "the capability spine must survive the budget"
    assert _STYLE_HEAD not in first, "a conversational turn must not carry the style/tool policies"
    assert "Multi-part requests are not done until EVERY part is answered" in first
    assert events, "the budget decision must be on the record"
    assert events[0]["horizon"] == "social"
    assert events[0]["dropped_sections"] == ["style_examples", "selection_hints", "on_demand_loading"]
    assert events[0]["static_chars"] == len(first)


@pytest.mark.asyncio
async def test_a_task_turn_records_the_full_horizon():
    from core.agent.prompt import _STYLE_HEAD

    seen, events = await _run_loop_and_collect(Intent.ANALYZE)
    assert seen
    first = seen[0]["system"]
    assert _STYLE_HEAD in first, "a task turn carries the canonical render"
    assert events and events[0]["horizon"] == "full"
    assert events[0]["dropped_sections"] == []
