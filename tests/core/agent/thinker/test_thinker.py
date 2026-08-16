"""Tests for the Thinker module (ADR-42) — the agent's reasoning backbone."""

from __future__ import annotations

import pytest

from core.agent.thinker import (
    Evidence,
    Thinker,
    ThinkerAnalysis,
    parse_thinker_analysis,
)
from core.models import StreamChunk


# ── Contract ────────────────────────────────────────────────────────────────
def test_evidence_has_evidence_gate():
    assert Evidence(observations="").has_evidence is False
    assert Evidence(observations="   ").has_evidence is False
    assert Evidence(observations="found 3 files").has_evidence is True


def test_analysis_is_empty():
    assert ThinkerAnalysis().is_empty is True
    assert ThinkerAnalysis(next_step="call shell").is_empty is False
    assert ThinkerAnalysis(reasoning="hmm").is_empty is False


# ── Parser ──────────────────────────────────────────────────────────────────
def test_parse_prose_plus_json():
    text = (
        "Two candidates found: report_2024.pdf and report_old.pdf; the 2024 one matches.\n"
        '{"facts": ["report_2024.pdf is the newest"], '
        '"ambiguities": [{"text": "which format", "default": "pdf"}], '
        '"next_step": "read report_2024.pdf", "confidence": 0.8}'
    )
    a = parse_thinker_analysis(text)
    assert "Two candidates found" in a.reasoning
    assert a.facts == ["report_2024.pdf is the newest"]
    assert a.ambiguities[0].text == "which format" and a.ambiguities[0].default == "pdf"
    assert a.next_step == "read report_2024.pdf"
    assert a.confidence == 0.8


def test_parse_fenced_json():
    text = "Reasoning here.\n```json\n{\"next_step\": \"synthesize the final answer\"}\n```"
    a = parse_thinker_analysis(text)
    assert a.next_step == "synthesize the final answer"
    assert a.reasoning.strip() == "Reasoning here."
    assert "```" not in a.reasoning


def test_parse_no_json_keeps_prose_as_reasoning():
    a = parse_thinker_analysis("I looked and found nothing conclusive.")
    assert a.reasoning == "I looked and found nothing conclusive."
    assert a.facts == [] and a.next_step == ""
    assert a.is_empty is False  # the reasoning is still usable


def test_parse_malformed_never_raises():
    a = parse_thinker_analysis('garbage {not json at all "')
    assert isinstance(a, ThinkerAnalysis)


def test_parse_string_ambiguity_and_bad_confidence():
    a = parse_thinker_analysis('{"ambiguities": ["unclear path"], "confidence": "high"}')
    assert a.ambiguities[0].text == "unclear path"
    assert a.confidence == 0.0  # non-numeric confidence fails safe


# ── Thinker.consult (streaming) ──────────────────────────────────────────────
class _MockAdapter:
    def __init__(self, chunks):
        self._chunks = chunks

    async def chat(self, messages, temperature=0.4, intent="analyze", **kwargs):
        for c in self._chunks:
            yield c


@pytest.mark.asyncio
async def test_consult_streams_reasoning_then_analysis():
    chunks = [
        StreamChunk(text="Found two files; ", done=False),
        StreamChunk(text="the newer one matches. ", done=False),
        StreamChunk(text='{"facts": ["f1"], "next_step": "read it", "confidence": 0.7}', done=False),
        StreamChunk(text="", done=True),
    ]
    thinker = Thinker()
    thought = []
    final = None
    async for ch in thinker.consult(Evidence(observations="ls output"), _MockAdapter(chunks)):
        if ch.thinking:
            thought.append(ch.thinking)
        if ch.done:
            final = ch
    joined = "".join(thought)
    # Prose reasoning surfaced; the JSON tail did NOT leak into the thought.
    assert "Found two files" in joined and "the newer one matches" in joined
    assert "{" not in joined and "facts" not in joined
    # Structured analysis parsed + attached.
    assert thinker.last_analysis.facts == ["f1"]
    assert thinker.last_analysis.next_step == "read it"
    assert final.metadata["thinker_analysis"]["next_step"] == "read it"


@pytest.mark.asyncio
async def test_analyze_returns_structured_analysis():
    chunks = [StreamChunk(text='{"next_step": "synthesize"}', done=False), StreamChunk(text="", done=True)]
    a = await Thinker().analyze(Evidence(observations="x"), _MockAdapter(chunks))
    assert a.next_step == "synthesize"


@pytest.mark.asyncio
async def test_consult_survives_provider_error():
    chunks = [StreamChunk(text="", done=True, error="boom 429")]
    thinker = Thinker()
    final = None
    async for ch in thinker.consult(Evidence(observations="x"), _MockAdapter(chunks)):
        if ch.done:
            final = ch
    # No crash; a safe (empty) analysis is still produced.
    assert final is not None
    assert thinker.last_analysis is not None
