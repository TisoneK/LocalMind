"""The user-stated identity facts — the guaranteed injection contract.

Pins core/user_profile.py end to end:

- stated facts render labeled as stated (provenance on every line);
- unstated facts render DECLARED ABSENT with the ask-don't-guess rule —
  the block always says something (an unconditional guarantee; a block
  that rendered only when facts exist would reintroduce the guess-by-
  default it exists to remove);
- the machine-reported time zone composes from the fused cache and is
  labeled as machine-reported, never as user-stated;
- the inline form carries the same contract in one lean line (the fast
  path's suffix must stay static-length — no per-turn I/O);
- the cache round-trips through set_cached_profile (the boot hook and
  the settings endpoint both refresh through it).
"""

from __future__ import annotations

import pytest

from core.user_profile import (
    format_identity_context,
    get_cached_profile,
    get_cached_profile_inline,
    set_cached_profile,
)
from core.user_context import set_cached_fused


@pytest.fixture(autouse=True)
def _clean_caches():
    set_cached_profile("", "")
    set_cached_fused({})
    yield
    set_cached_profile("", "")
    set_cached_fused({})


class TestStatedFacts:
    def test_stated_facts_are_labeled_as_stated(self):
        block = set_cached_profile("Amani", "Nairobi, Kenya")
        assert "## About this user" in block
        assert "- Name: Amani (the user stated this in Settings)" in block
        assert "- Place: Nairobi, Kenya (the user stated this in Settings)" in block

    def test_stated_contract_is_authoritative_over_tools(self):
        block = set_cached_profile("Amani", "Nairobi, Kenya")
        assert "authoritative" in block
        assert "never let a tool result override them" in block

    def test_machine_timezone_is_labeled_machine_reported(self):
        set_cached_fused({"timezone_name": "Africa/Nairobi", "country": "KE"})
        block = set_cached_profile("Amani", "Nairobi, Kenya")
        assert "- Time zone: Africa/Nairobi (reported by this machine's clock)" in block
        # The machine deduction must never wear the user's label.
        assert "the user stated this in Settings)" not in block.split("- Time zone:")[1].split("\n")[0]


class TestAbsentFacts:
    def test_nothing_stated_still_renders_the_block(self):
        block = set_cached_profile("", "")
        assert "## About this user" in block
        assert "never stated" in block

    def test_absent_name_declares_unknown_and_forbids_guessing(self):
        block = set_cached_profile("", "Nairobi, Kenya")
        assert "- Name: never stated" in block
        assert "never guess" in block
        assert "- Place: Nairobi, Kenya (the user stated this in Settings)" in block

    def test_absent_place_forbids_inference_from_tools(self):
        block = set_cached_profile("Amani", "")
        assert "- Place: never stated" in block
        assert "never infer it from tool or search results" in block

    def test_inline_form_always_renders(self):
        set_cached_profile("", "")
        line = get_cached_profile_inline()
        assert line, "the inline guarantee must never be empty"
        assert "never stated" in line
        assert "never infer" in line


class TestInlineForm:
    def test_both_stated_is_one_lean_line(self):
        set_cached_profile("Amani", "Nairobi, Kenya")
        line = get_cached_profile_inline()
        assert '\n' not in line
        assert 'name "Amani"' in line
        assert 'place "Nairobi, Kenya"' in line
        assert "authoritative" in line

    def test_partial_stated_carries_both_tiers(self):
        set_cached_profile("Amani", "")
        line = get_cached_profile_inline()
        assert 'name "Amani" (stated' in line
        assert "place never stated" in line

    def test_no_per_turn_io_shape(self):
        # The fast path appends this per turn: it must be a pure cache read.
        set_cached_profile("Amani", "Nairobi, Kenya")
        first = get_cached_profile_inline()
        second = get_cached_profile_inline()
        assert first == second


class TestCacheRoundTrip:
    def test_get_cached_profile_reflects_the_set(self):
        set_cached_profile("  Amani  ", "Nairobi, Kenya")
        assert get_cached_profile() == {"name": "Amani", "place": "Nairobi, Kenya"}

    def test_empty_set_clears(self):
        set_cached_profile("Amani", "Nairobi, Kenya")
        set_cached_profile("", "")
        assert get_cached_profile() == {"name": "", "place": ""}

    def test_values_are_stripped_not_padded(self):
        block = set_cached_profile("  Amani ", " Nairobi, Kenya ")
        assert "- Name: Amani (" in block
        assert "- Place: Nairobi, Kenya (" in block
