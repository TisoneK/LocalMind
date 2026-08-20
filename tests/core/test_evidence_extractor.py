"""Tests for the deterministic evidence extractor (B-2026-08-20-15, Session 316).

Verifies that the extractor pulls the answer directly from the reasoning
buffer + tool observations with ZERO LLM calls — the user's insight: "the
thinking text and other evidence already has all the answers."
"""

from __future__ import annotations

import pytest

from core.agent.loop import AgentLoop


@pytest.fixture
def loop():
    return AgentLoop(adapter=None)


# ── Reasoning buffer extraction ─────────────────────────────────────────────


def test_extract_from_reasoning_weather(loop):
    """The model's reasoning contains the weather answer directly."""
    reasoning = (
        "The user is asking about the weather in Kitengela. I can see from "
        "the search results that there are mentions of current temperature "
        "(16°C), overcast conditions, and various weather details. The current "
        "temperature is 16°C and it's overcast. I should fetch a page to get "
        "more details."
    )
    extracted = loop._extract_answer_sentence(reasoning, "weather in Kitengela")
    # Should extract a sentence with the temperature + entity, NOT the
    # meta-reasoning ("I should fetch...").
    assert extracted
    assert "16" in extracted or "overcast" in extracted
    assert "I should" not in extracted  # meta-reasoning penalized


def test_extract_from_reasoning_hostname(loop):
    reasoning = (
        "The user wants the hostname. I can see from the environment that "
        "the hostname is my-machine.local. Let me verify with the shell. "
        "Actually, the hostname is my-machine.local."
    )
    extracted = loop._extract_answer_sentence(reasoning, "what is the hostname")
    assert extracted
    assert "my-machine" in extracted


def test_extract_from_reasoning_penalizes_meta_reasoning(loop):
    """Meta-reasoning ('I should search', 'let me check') is penalized."""
    reasoning = (
        "I should search for the weather. Let me check the results. "
        "I'll use the web_search tool to find current weather information."
    )
    extracted = loop._extract_answer_sentence(reasoning, "weather")
    # None of these sentences contain a factual answer — should return "".
    assert extracted == ""


def test_extract_from_reasoning_empty(loop):
    assert loop._extract_answer_sentence("", "weather") == ""
    assert loop._extract_answer_sentence(None, "weather") == ""  # type: ignore[arg-type]


# ── Observation log extraction ──────────────────────────────────────────────


def test_extract_from_observations_search_snippet(loop):
    """Search result snippets often contain the answer directly."""
    obs_log = (
        "Search results via DuckDuckGo (8 results):\n"
        "1. Weather today - Kitengela, Kenya\n"
        "   https://www.weather-atlas.com/en/kenya/kitengela\n"
        "   Current Time: 7 июн 2026 г. 02:45:08.12 °C\n"
        "2. Another result\n"
        "   https://example.com\n"
    )
    extracted = loop._extract_answer_from_observations(obs_log, "weather in Kitengela")
    # Should extract the line with the temperature, not the URL.
    assert extracted
    assert "°" in extracted or "12" in extracted
    assert not extracted.startswith("http")


def test_extract_from_observations_penalizes_urls(loop):
    """URLs are penalized — they're not answers."""
    obs_log = (
        "https://www.weather-atlas.com/en/kenya/kitengela\n"
        "https://example.com/weather\n"
    )
    extracted = loop._extract_answer_from_observations(obs_log, "weather")
    assert extracted == ""


def test_extract_from_observations_empty(loop):
    assert loop._extract_answer_from_observations("", "weather") == ""
    assert loop._extract_answer_from_observations(None, "weather") == ""  # type: ignore[arg-type]


# ── Full extraction (reasoning + observations) ──────────────────────────────


def test_extract_answer_from_evidence_reasoning_first(loop):
    """Reasoning buffer is checked first (higher priority)."""
    reasoning = "The temperature is 16°C and overcast in Kitengela."
    obs_log = "Search results: Current Time: 12 °C"
    extracted = loop._extract_answer_from_evidence(
        reasoning_buffer=reasoning,
        observation_log=obs_log,
        trace=None,
        user_message="weather in Kitengela",
    )
    assert extracted
    assert "16" in extracted  # from reasoning, not observations


def test_extract_answer_from_evidence_falls_back_to_observations(loop):
    """When reasoning has no answer, fall back to observations."""
    reasoning = "I should search for the weather. Let me check."
    obs_log = "Current Time: 7 июн 2026 г. 02:45:08.12 °C"
    extracted = loop._extract_answer_from_evidence(
        reasoning_buffer=reasoning,
        observation_log=obs_log,
        trace=None,
        user_message="weather in Kitengela",
    )
    assert extracted
    assert "°" in extracted or "12" in extracted  # from observations


def test_extract_answer_from_evidence_both_empty(loop):
    """No reasoning + no observations → empty string."""
    extracted = loop._extract_answer_from_evidence(
        reasoning_buffer="",
        observation_log="",
        trace=None,
        user_message="weather",
    )
    assert extracted == ""


# ── Integration: the extractor runs with zero LLM calls ────────────────────


def test_extractor_makes_zero_llm_calls(loop):
    """The extractor is purely deterministic — no adapter calls."""
    reasoning = "The temperature is 16°C and overcast in Kitengela."
    # The loop has adapter=None — if the extractor tried to call the adapter,
    # it would raise. Verify it returns without touching the adapter.
    extracted = loop._extract_answer_from_evidence(
        reasoning_buffer=reasoning,
        observation_log="",
        trace=None,
        user_message="weather in Kitengela",
    )
    assert extracted  # got an answer
    # No exception means no adapter call was made.
