"""The prompt-structure registry: named sections, order slots, strict assembly.

Contract under test:
- Duplicate section names fail registration (two producers appending the same
  name is a structure bug, not a rendering detail).
- Unknown `include` references fail rendering; unknown `exclude` references
  are a no-op (cutting a section a prompt never had is already true).
- A section's order must fall inside its layer's documented slot range, and
  the layer must be legal for its band (the user objective is per-turn and
  can never live in the STATIC band; static layers can never live in TURN).
- Rendering is deterministic: (order, name) within a band, doctrine layers
  ascending; the render never mutates the registry.
- staged_static_content drops exactly the first-tool-choice guidance and
  keeps every rule.
"""
from __future__ import annotations

import pytest

from core.agent.prompt import (
    Band,
    Layer,
    PromptStructureError,
    Section,
    SectionRegistry,
    make,
    staged_static_content,
    SECTION_IDENTITY,
    SECTION_MEMORY_FACTS,
    SECTION_CURRENT_INTENT,
    SECTION_ENVIRONMENT,
    SECTION_STYLE_EXAMPLES,
    SECTION_TOOL_INDEX,
)


def _sec(name, band=Band.STATIC, layer=Layer.CONSTRAINTS, order=110, text=None):
    return make(name, band, layer, order, text if text is not None else f"{name} body text.")


class TestRegistration:
    def test_duplicate_names_fail_loud(self):
        r = SectionRegistry()
        r.add(_sec("rules"))
        with pytest.raises(PromptStructureError, match="duplicate"):
            r.add(_sec("rules", text="a second copy"))

    def test_empty_text_fails_registration(self):
        with pytest.raises(PromptStructureError, match="no text"):
            _sec("empty", text="   ")

    def test_order_outside_layer_range_fails(self):
        with pytest.raises(PromptStructureError, match="slot range"):
            _sec("misplaced", layer=Layer.CONSTRAINTS, order=305)

    def test_objective_cannot_be_static(self):
        with pytest.raises(PromptStructureError, match="STATIC"):
            _sec("objective", band=Band.STATIC, layer=Layer.OBJECTIVE, order=0)

    def test_static_layers_cannot_be_turn(self):
        with pytest.raises(PromptStructureError, match="static"):
            _sec("rule", band=Band.TURN, layer=Layer.CONSTRAINTS, order=1050)


class TestRendering:
    def test_renders_in_order_within_a_band(self):
        r = SectionRegistry()
        r.add(_sec("b_late", layer=Layer.CONTEXT, order=220))
        r.add(_sec("a_early", layer=Layer.CONSTRAINTS, order=110))
        r.add(_sec("c_guidance", layer=Layer.GUIDANCE, order=400))
        assert r.render(Band.STATIC).split("\n\n") == ["a_early body text.", "b_late body text.", "c_guidance body text."]

    def test_equal_orders_break_by_name(self):
        r = SectionRegistry()
        r.add(_sec("zeta", order=110))
        r.add(_sec("alpha", order=110))
        assert r.render(Band.STATIC).split("\n\n") == ["alpha body text.", "zeta body text."]

    def test_bands_render_independently(self):
        r = SectionRegistry()
        r.add(_sec("static_rule", band=Band.STATIC, layer=Layer.CONSTRAINTS, order=110))
        r.add(_sec("turn_fact", band=Band.TURN, layer=Layer.CONTEXT, order=1050))
        assert r.render(Band.STATIC) == "static_rule body text."
        assert r.render(Band.TURN) == "turn_fact body text."

    def test_include_with_unknown_name_raises(self):
        r = SectionRegistry()
        r.add(_sec("real"))
        with pytest.raises(PromptStructureError, match="unknown prompt section 'ghost'"):
            r.render(Band.STATIC, include=["real", "ghost"])

    def test_exclude_with_unknown_name_is_a_no_op(self):
        r = SectionRegistry()
        r.add(_sec("real"))
        assert r.render(Band.STATIC, exclude=["never_registered"]) == "real body text."

    def test_include_and_exclude_are_mutually_exclusive(self):
        r = SectionRegistry()
        with pytest.raises(PromptStructureError, match="mutually exclusive"):
            r.render(Band.STATIC, include=["a"], exclude=["b"])

    def test_render_does_not_mutate_the_registry(self):
        r = SectionRegistry()
        r.add(_sec("a", order=110))
        r.add(_sec("b", layer=Layer.CONTEXT, order=220))
        full = r.render(Band.STATIC)
        cut = r.render(Band.STATIC, exclude=["b"])
        assert cut == "a body text."
        assert r.render(Band.STATIC) == full

    def test_char_sizes_reports_per_section(self):
        r = SectionRegistry()
        r.add(_sec("a", order=110, text="12345"))
        r.add(_sec("b", layer=Layer.CONTEXT, order=220, text="1234567890"))
        assert r.char_sizes(Band.STATIC) == {"a": 5, "b": 10}


class TestStagedStaticContent:
    def _parent_like_registry(self):
        r = SectionRegistry()
        r.add(_sec(SECTION_IDENTITY, layer=Layer.IDENTITY, order=10, text="You are LocalMind."))
        r.add(_sec("safety_grounding", layer=Layer.CONSTRAINTS, order=140, text="Safety: check current state before writes."))
        r.add(_sec("multi_part_completion", layer=Layer.CONSTRAINTS, order=130, text="Multi-part requests are not done until EVERY part is answered."))
        r.add(_sec(SECTION_STYLE_EXAMPLES, layer=Layer.GUIDANCE, order=400, text="Style — terseness: examples here"))
        r.add(_sec(SECTION_TOOL_INDEX, layer=Layer.GUIDANCE, order=410, text="Available tools — pick the RIGHT one: list"))
        return r

    def test_later_call_with_tools_drops_only_first_tool_guidance(self):
        r = self._parent_like_registry()
        out = staged_static_content(r, with_tools=True)
        assert "Style — terseness" not in out and "Available tools" not in out
        assert "Multi-part requests" in out and "Safety:" in out and "You are LocalMind." in out

    def test_answer_only_call_also_drops_on_demand(self):
        r = self._parent_like_registry()
        r.add(_sec("on_demand_loading", layer=Layer.GUIDANCE, order=430, text="Core tools are loaded with full schemas."))
        out = staged_static_content(r, with_tools=False)
        assert "Core tools are loaded" not in out
        assert "Multi-part requests" in out

    def test_prefix_is_preserved_unstaged(self):
        out = staged_static_content(self._parent_like_registry(), with_tools=True, prefix="Session summary.")
        assert out.startswith("Session summary.\n\nYou are LocalMind.")


class TestTurnRegistryShape:
    def test_doctrine_order_objective_context_guidance(self):
        r = SectionRegistry()
        r.add(_sec(SECTION_SKILL := "skill_fragment", band=Band.TURN, layer=Layer.GUIDANCE, order=1160))
        r.add(_sec(SECTION_ENVIRONMENT, band=Band.TURN, layer=Layer.CONTEXT, order=1050))
        r.add(_sec(SECTION_CURRENT_INTENT, band=Band.TURN, layer=Layer.OBJECTIVE, order=1010))
        assert r.names(Band.TURN) == [SECTION_CURRENT_INTENT, SECTION_ENVIRONMENT, "skill_fragment"]

    def test_memory_is_a_turn_section(self):
        # The G2 cache rule made structural: retrieved memory is per-turn
        # content and physically cannot be registered into the STATIC band.
        with pytest.raises(PromptStructureError):
            make(SECTION_MEMORY_FACTS, Band.STATIC, Layer.CONTEXT, 260, "facts")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
