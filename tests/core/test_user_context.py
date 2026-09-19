"""Tests for the boot-time user-context perception + fusion.

The agent used to answer location-sensitive requests from assumption or by
hedging across candidate countries although the machine already carries the
signals (OS country setting, time zone, locale). These pin the deduction
contract: ONE conclusion from converging signals, an honest unknown when they
don't, stable-only collection, the write-path integration for the durable
fact, and the two prompt surfaces that carry it.
"""

from __future__ import annotations

from core.memory_intent import (
    canonical_key,
    durability_profile,
)
from core.user_context import (
    collect_user_signals,
    format_user_context,
    fuse_user_signals,
    get_cached_fused,
    get_cached_fused_dict,
    get_cached_fused_inline,
    set_cached_fused,
)


class TestSignalCollection:
    def test_collect_never_raises_and_drops_empty(self):
        signals = collect_user_signals()
        assert isinstance(signals, dict)
        for key, values in signals.items():
            assert values, f"empty signal list for {key}"

    def test_every_signal_is_a_string_list(self):
        for values in collect_user_signals().values():
            assert all(isinstance(v, str) and v for v in values)

    def test_stable_only_no_volatile_network_fields(self):
        # Volatile values (IP/ISP/MAC) must never become durable defaults —
        # they are excluded by construction, not filtered later.
        signals = collect_user_signals()
        assert not any(k in signals for k in ("ip", "isp", "mac", "network"))


class TestFusionConverges:
    def test_geo_setting_wins_over_locale_format_tag(self):
        # The real-machine shape: English Windows defaults the locale FORMAT
        # tag to en-US regardless of country. The user's OS country setting
        # is authoritative; the format tag must not override it.
        fused = fuse_user_signals({"locale": ["en-US"], "region": ["KE"]})
        assert fused["country"] == "KE"
        assert fused["confidence"] == "high"
        assert fused["sources"] == ["region"]
        assert "note" not in fused

    def test_convergence_raises_confidence(self):
        fused = fuse_user_signals(
            {"region": ["KE"], "timezone": ["Africa/Nairobi"], "locale": ["en-KE"]}
        )
        assert fused["country"] == "KE"
        assert fused["confidence"] == "high"
        assert set(fused["sources"]) >= {"region", "timezone"}

    def test_timezone_decides_without_geo(self):
        fused = fuse_user_signals({"locale": ["en"], "timezone": ["Africa/Nairobi"]})
        assert fused["country"] == "KE"
        assert fused["confidence"] == "high"

    def test_locale_tag_alone_is_medium(self):
        fused = fuse_user_signals({"locale": ["en-GB"]})
        assert fused["country"] == "GB"
        assert fused["confidence"] == "medium"

    def test_offset_never_votes_but_is_reported(self):
        # Too many countries share a UTC offset — it corroborates, never votes.
        fused = fuse_user_signals({"locale": ["en-KE"], "tz_offset": ["+0300"]})
        assert fused["country"] == "KE"
        assert fused["utc_offset"] == "+0300"


class TestFusionHonesty:
    def test_no_signals_gives_an_honest_unknown(self):
        fused = fuse_user_signals({"tz_offset": ["+0300"]})
        assert fused["country"] is None
        assert fused["confidence"] == "none"

    def test_no_block_text_when_nothing_deduced(self):
        assert format_user_context(fuse_user_signals({})) == ""

    def test_strong_contradiction_is_surfaced_not_hidden(self):
        fused = fuse_user_signals({"region": ["GB"], "timezone": ["Africa/Nairobi"]})
        assert fused["country"] == "GB"  # country setting authoritative
        assert "disagree" in fused["note"]

    def test_locale_format_tag_disagreement_is_known_noise(self):
        # The en-US format-tag default on English Windows is not evidence of
        # the US — it must never turn into a "signals disagree" note.
        fused = fuse_user_signals({"region": ["KE"], "locale": ["en-US"]})
        assert fused["country"] == "KE"
        assert "note" not in fused


class TestFormatting:
    def test_block_carries_one_conclusion_and_the_contract(self):
        fused = fuse_user_signals(
            {"region": ["KE"], "timezone": ["Africa/Nairobi"], "lang": ["en"]}
        )
        block = format_user_context(fused)
        assert "## User context" in block
        assert "Kenya" in block and "(KE)" in block
        assert "Africa/Nairobi" in block
        assert "English" in block
        assert "hedging" in block  # the deduction contract travels with it

    def test_cache_roundtrip(self):
        fused = fuse_user_signals({"region": ["KE"]})
        set_cached_fused(fused)
        try:
            assert "Kenya" in get_cached_fused()
            assert "Kenya" in get_cached_fused_inline()
            assert get_cached_fused_dict()["country"] == "KE"
        finally:
            set_cached_fused({})

    def test_cache_clears_to_empty_surfaces(self):
        set_cached_fused({})
        try:
            assert get_cached_fused() == ""
            assert get_cached_fused_inline() == ""
        finally:
            set_cached_fused({})


class TestWritePathIntegration:
    def test_boot_fact_is_refreshable_stable_and_keyed_to_location(self):
        fact = "My country: KE (deduced from machine settings at boot)"
        durability = durability_profile(fact)
        assert durability.kind.name == "STABLE_FACT"
        assert durability.freshness == "boot"
        assert canonical_key(fact) == "subject:location"

    def test_reworded_or_moved_fact_keeps_the_same_row_key(self):
        # A re-wording or a move must REPLACE the row, not accumulate one.
        base = canonical_key("My country: KE (deduced from machine settings at boot)")
        assert base == canonical_key("My country: TZ (deduced from machine settings at boot)")
        assert base == canonical_key("My country: DE (deduced from machine settings at boot)")
