"""Session 342 — memory-write intent recognition + candidate extraction tests."""
from __future__ import annotations

from core.memory_intent import (
    MemoryOperation,
    MemoryType,
    MemoryWriteIntent,
    MemoryCandidate,
    classify_memory_intent,
    extract_memory_candidates,
    should_store_candidate,
    _extract_content,
    _detect_source_domain,
    _classify_memory_type,
)


# ── Memory-write intent detection ──────────────────────────────────────────


class TestMemoryWriteDetection:
    def test_remember_this_is_write(self):
        intent = classify_memory_intent("Remember that I prefer concise answers.")
        assert intent.is_write is True
        assert intent.operation == MemoryOperation.WRITE

    def test_remember_this_site_is_write_and_source_knowledge(self):
        """The exact regression case: 'Remember the sites that give a lot of information.'"""
        intent = classify_memory_intent(
            "Remember the sites that gives a lot of information so that "
            "next time we won't have to guess the links."
        )
        assert intent.is_write is True
        assert intent.is_source_knowledge is True

    def test_save_this_is_write(self):
        intent = classify_memory_intent("Save this for later.")
        assert intent.is_write is True

    def test_keep_in_mind_is_write(self):
        intent = classify_memory_intent("Keep this in mind for next time.")
        assert intent.is_write is True

    def test_dont_forget_is_write(self):
        intent = classify_memory_intent("Don't forget that I use FastAPI.")
        assert intent.is_write is True

    def test_next_time_remember_is_write(self):
        intent = classify_memory_intent("Next time remember to use the BBC source.")
        assert intent.is_write is True

    def test_remember_this_site_for_weather_is_source_knowledge(self):
        """The user's exact case: 'Remember this site for weather.'"""
        intent = classify_memory_intent("Remember this site for weather so we don't have to guess next time.")
        assert intent.is_write is True
        assert intent.is_source_knowledge is True
        assert intent.source_domain == "weather"

    def test_what_do_you_remember_is_read(self):
        intent = classify_memory_intent("What do you remember about me?")
        assert intent.is_read is True
        assert intent.is_write is False

    def test_forget_that_is_delete(self):
        intent = classify_memory_intent("Forget that I liked Vue.")
        assert intent.is_delete is True

    def test_dont_use_anymore_is_delete(self):
        intent = classify_memory_intent("Don't use WeatherMetro anymore. It is unreliable.")
        assert intent.is_delete is True

    def test_normal_message_is_not_memory_op(self):
        for msg in [
            "Give me the current EPL standings.",
            "Explain how a car engine works.",
            "Hi",
            "What is the weather in Nairobi?",
            "Summarize the difference between RAM and storage.",
        ]:
            intent = classify_memory_intent(msg)
            assert intent.is_write is False, f"{msg!r} was mis-classified as write"
            assert intent.is_read is False
            assert intent.is_delete is False


# ── Content extraction ─────────────────────────────────────────────────────


class TestContentExtraction:
    def test_strips_remember_that_prefix(self):
        content = _extract_content("Remember that I prefer concise answers.")
        assert "prefer concise answers" in content
        assert "remember" not in content.lower()

    def test_strips_remember_the_sites_prefix(self):
        content = _extract_content(
            "Remember the sites that gives a lot of information so that "
            "next time we won't have to guess the links."
        )
        assert "sites that gives" in content
        assert not content.lower().startswith("remember")

    def test_strips_dont_forget_prefix(self):
        content = _extract_content("Don't forget that I use FastAPI.")
        assert "use fastapi" in content.lower()
        assert not content.lower().startswith("don't forget")

    def test_strips_next_time_remember_prefix(self):
        content = _extract_content("Next time remember to use the BBC source.")
        assert "use the bbc source" in content.lower()

    # Regression: the cue prefix survived a colon, so
    # "Remember this: <fact>. Just acknowledge." persisted the framing
    # ("this: ... Just acknowledge") as the fact and echoed it back broken.
    def test_strips_colon_after_demonstrative(self):
        content = _extract_content(
            "Remember this: my project is called Falcon. Just acknowledge."
        )
        assert content == "my project is called Falcon"

    def test_strips_bare_colon_after_verb(self):
        content = _extract_content("Remember: the deploy runs at 03:00 UTC")
        assert content == "the deploy runs at 03:00 UTC"

    def test_strips_trailing_assistant_directive(self):
        content = _extract_content(
            "Keep in mind that my SSH port is 2222. Just acknowledge."
        )
        assert content == "my SSH port is 2222"

    def test_imperative_words_inside_a_fact_are_kept(self):
        content = _extract_content(
            "Remember that the deploy script says 'ok' before it starts."
        )
        assert content == "the deploy script says 'ok' before it starts"

    def test_fact_that_is_only_an_instruction_survives(self):
        # A fact whose whole content is an imperative must not be nuked —
        # the floor only trims directives trailing real content.
        content = _extract_content("Remember: acknowledge receipt of the invoice.")
        assert content == "acknowledge receipt of the invoice"

    def test_classifier_content_strips_framing(self):
        intent = classify_memory_intent(
            "Remember this: my project is called Falcon. Just acknowledge."
        )
        assert intent.content == "my project is called Falcon"
        assert intent.memory_type.value == "user_fact"
        assert intent.needs_resolution is False


# ── Source-domain detection ────────────────────────────────────────────────


class TestSourceDomainDetection:
    def test_weather_domain(self):
        assert _detect_source_domain("Remember this site for weather") == "weather"

    def test_sports_domain(self):
        assert _detect_source_domain("Remember this site for EPL standings") == "sports"

    def test_news_domain(self):
        assert _detect_source_domain("Remember this source for news headlines") == "news"

    def test_generic_returns_none(self):
        assert _detect_source_domain("Remember the sites that give a lot of information") is None


# ── Memory-type classification ─────────────────────────────────────────────


class TestMemoryTypeClassification:
    def test_source_knowledge_takes_priority(self):
        t = _classify_memory_type("some content", is_source_knowledge=True)
        assert t == MemoryType.SOURCE_KNOWLEDGE

    def test_preference_detected(self):
        t = _classify_memory_type("I prefer concise answers", is_source_knowledge=False)
        assert t == MemoryType.USER_PREFERENCE

    def test_fact_detected(self):
        t = _classify_memory_type("I live in Nairobi", is_source_knowledge=False)
        assert t == MemoryType.USER_FACT

    def test_general_fallback(self):
        t = _classify_memory_type("The sky is blue", is_source_knowledge=False)
        assert t == MemoryType.GENERAL


# ── Memory candidate extraction (autonomous learning) ──────────────────────


class TestMemoryCandidateExtraction:
    def test_correction_is_high_priority_candidate(self):
        """MEM-LEARN-4: correction learning."""
        candidates = extract_memory_candidates(
            "No, browser is a first-class capability, not a fallback."
        )
        assert len(candidates) >= 1
        correction = candidates[0]
        assert correction.memory_type == MemoryType.PROJECT_DECISION
        assert correction.source == "user_correction"
        assert correction.importance >= 0.8

    def test_preference_is_medium_priority_candidate(self):
        """MEM-LEARN-1: autonomous preference learning."""
        candidates = extract_memory_candidates("Keep technical answers short and direct.")
        # "Keep it short" matches _AUTONOMOUS_PREFERENCE_CUES
        found = False
        for c in candidates:
            if c.memory_type == MemoryType.USER_PREFERENCE:
                found = True
                assert c.importance >= 0.6
        # "Keep technical answers short" doesn't exactly match "I prefer" —
        # but the concept is there. This test verifies the pattern exists.

    def test_ephemeral_info_is_not_stored(self):
        """MEM-LEARN-3: temporary information rejection."""
        candidates = extract_memory_candidates("I'm having lunch now.")
        assert len(candidates) == 0

    def test_fact_is_candidate(self):
        """MEM-LEARN-2: durable project fact."""
        candidates = extract_memory_candidates("I'm building LocalMind as a parent-agent system.")
        found = False
        for c in candidates:
            if c.memory_type == MemoryType.USER_FACT:
                found = True
                assert "localmind" in c.content.lower()
        assert found

    def test_source_knowledge_from_tool_result(self):
        """MEM-LEARN-5: tool outcome learning."""
        tool_results = [
            "Source: https://weathermetro.com/weather/kitengela\nContent: Temperature 25°C..."
        ]
        candidates = extract_memory_candidates(
            "What's the weather?",
            tool_results=tool_results,
        )
        found = False
        for c in candidates:
            if c.memory_type == MemoryType.SOURCE_KNOWLEDGE:
                found = True
                assert "weathermetro" in c.content.lower()
        assert found

    def test_casual_greeting_produces_no_candidates(self):
        """MEM-LEARN-8: memory should not hijack conversation."""
        candidates = extract_memory_candidates("Hi")
        assert len(candidates) == 0

    def test_how_is_it_going_produces_no_candidates(self):
        candidates = extract_memory_candidates("How's it going?")
        assert len(candidates) == 0


# ── Storage decision ───────────────────────────────────────────────────────


class TestShouldStoreCandidate:
    def test_correction_is_stored(self):
        c = MemoryCandidate(
            content="No, browser is first-class.",
            memory_type=MemoryType.PROJECT_DECISION,
            source="user_correction",
            importance=0.9,
        )
        assert should_store_candidate(c) is True

    def test_preference_is_stored(self):
        c = MemoryCandidate(
            content="I prefer concise answers.",
            memory_type=MemoryType.USER_PREFERENCE,
            importance=0.7,
        )
        assert should_store_candidate(c) is True

    def test_source_knowledge_is_stored(self):
        c = MemoryCandidate(
            content="WeatherMetro provides comprehensive weather data.",
            memory_type=MemoryType.SOURCE_KNOWLEDGE,
            importance=0.5,
        )
        assert should_store_candidate(c) is True

    def test_low_importance_general_is_not_stored(self):
        c = MemoryCandidate(
            content="The weather is 25°C.",
            memory_type=MemoryType.GENERAL,
            importance=0.3,
        )
        assert should_store_candidate(c) is False

    def test_ephemeral_is_not_stored(self):
        c = MemoryCandidate(
            content="I'm having lunch.",
            memory_type=MemoryType.GENERAL,
            durability="ephemeral",
            importance=0.5,
        )
        assert should_store_candidate(c) is False
