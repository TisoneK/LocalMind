"""The response-formatting contract rides EVERY answer surface.

The owner's 2026-11-03 report ("the UI does not format the output in
style eg tables etc its just text") traced to a structural gap: the
response_formatting section existed ONLY in the scoped execution-agent
registry, while the two surfaces that actually answer ordinary turns —
the parent warm-kernel (native bootstrap) and the chat surface —
registered none. The model was never asked for markdown on the turns
users ask for tables, so the (working) frontend renderer had nothing to
render.

These pins hold the fix in place:

1. All three STATIC registries carry the section, byte-identical, from
   the one shared source (sections/formatting.py).
2. The shared slot is 405 — after the tool index (400) so the SOCIAL
   relevance cut (a contiguous-suffix drop of tool-choosing guidance)
   can never strip the contract from a conversational turn, before
   style_examples (410) so the suffix property holds.
3. The SOCIAL render keeps the contract AND stays a byte-prefix of the
   full render (the cache-forking guard).
4. The section text carries the GFM pipe-table contract — the renderer
   side (react-markdown + remark-gfm) only parses standard GFM.
"""

import pytest
from core.agent.prompt.names import SECTION_RESPONSE_FORMATTING, SECTION_SLOTS
from core.agent.prompt.sections.agent import build_agent_static_registry
from core.agent.prompt.sections.chat import build_chat_static_registry
from core.agent.prompt.sections.formatting import RESPONSE_FORMATTING_TEXT
from core.agent.prompt.sections.parent import build_parent_static_registry
from core.agent.prompt.structure import Band

GFM_MARKER = "standard GFM pipe tables"


def _registry_order(registry, name: str) -> int:
    matches = [s.order for s in registry.render_sections(Band.STATIC) if s.name == name]
    assert len(matches) == 1, f"{name} registered {len(matches)} times"
    return matches[0]


@pytest.fixture
def parent_registry():
    return build_parent_static_registry(tool_defs=[])


@pytest.fixture
def chat_registry():
    return build_chat_static_registry()


@pytest.fixture
def agent_registry():
    return build_agent_static_registry([])


def test_parent_surface_carries_the_formatting_contract(parent_registry):
    render = parent_registry.render(Band.STATIC)
    assert "RESPONSE FORMATTING" in render
    assert render.count("RESPONSE FORMATTING") == 1, "duplicated registration"


def test_chat_surface_carries_the_formatting_contract(chat_registry):
    render = chat_registry.render(Band.STATIC)
    assert "RESPONSE FORMATTING" in render
    assert render.count("RESPONSE FORMATTING") == 1


def test_agent_surface_carries_the_formatting_contract(agent_registry):
    render = agent_registry.render(Band.STATIC)
    assert "RESPONSE FORMATTING" in render
    assert render.count("RESPONSE FORMATTING") == 1


def test_all_three_surfaces_share_one_byte_identical_text(
    parent_registry, chat_registry, agent_registry
):
    expected = RESPONSE_FORMATTING_TEXT
    for name, registry in (
        ("parent", parent_registry),
        ("chat", chat_registry),
        ("agent", agent_registry),
    ):
        section = registry.get(SECTION_RESPONSE_FORMATTING)
        assert section.text == expected, f"{name} surface drifted from the shared text"


def test_shared_slot_is_405_on_every_surface(parent_registry, chat_registry, agent_registry):
    for name, registry in (
        ("parent", parent_registry),
        ("chat", chat_registry),
        ("agent", agent_registry),
    ):
        assert _registry_order(registry, SECTION_RESPONSE_FORMATTING) == 405, name
    assert SECTION_SLOTS[SECTION_RESPONSE_FORMATTING] == 405, (
        "the allocation table must pin the shared slot the surfaces render"
    )


def test_slot_sits_between_tool_index_and_style_examples(parent_registry):
    orders = {
        s.name: s.order for s in parent_registry.render_sections(Band.STATIC)
    }
    assert orders["tool_index"] == 400
    assert orders["response_formatting"] == 405
    assert orders["style_examples"] == 410


def test_social_render_keeps_the_contract_and_stays_a_byte_prefix(parent_registry):
    from core.agent.prompt.budget import RelevanceHorizon, render_static_budgeted

    full = parent_registry.render(Band.STATIC)
    social = render_static_budgeted(parent_registry, RelevanceHorizon.SOCIAL)
    assert "RESPONSE FORMATTING" in social, (
        "the conversational horizon dropped the formatting contract — "
        "conversational turns are exactly where tables are asked for"
    )
    assert full.startswith(social), "the SOCIAL render is not a byte-prefix (cache fork)"
    # The dropped suffix is exactly the tool-choosing guidance.
    assert "Style — terseness" not in social
    assert "Selection hints:" not in social


def test_staged_cuts_keep_the_contract(parent_registry):
    from core.agent.prompt.staging import staged_static_content

    staged = staged_static_content(parent_registry, with_tools=True)
    assert "RESPONSE FORMATTING" in staged
    staged_answer_only = staged_static_content(parent_registry, with_tools=False)
    assert "RESPONSE FORMATTING" in staged_answer_only


def test_section_text_carries_the_gfm_table_contract():
    """The renderer parses standard GFM only — the prompt must ask for it."""
    assert GFM_MARKER in RESPONSE_FORMATTING_TEXT
    assert "| --- |" in RESPONSE_FORMATTING_TEXT
    assert "｜" in RESPONSE_FORMATTING_TEXT  # names the full-width lookalike
