"""Tests for the Thinker module (ADR-42) — the agent's reasoning backbone."""

from __future__ import annotations

import pytest
from core.agent.thinker import (
    Evidence,
    Thinker,
    ThinkerAnalysis,
    parse_thinker_analysis,
)
from core.agent.thinker.prompt import build_thinker_messages
from core.models import StreamChunk


# ── Prompt anchors on the real request, not a generic fallback (S263) ─────────
def test_prompt_shows_user_request_even_when_objective_is_generic():
    ev = Evidence(
        objective="Determine and complete the user's request.",  # init fallback
        user_message="Create a recipe on desktop for a nice dinner",
        observations="ls output: Facebook.lnk, WhatsApp Web.lnk",
        last_action="shell",
    )
    msg = build_thinker_messages(ev)[1]["content"]
    assert "Create a recipe on desktop" in msg, "the real request must be shown"
    # The generic fallback objective must NOT appear (it confused the Thinker).
    assert "Determine and complete the user's request" not in msg
    # And it must tell the Thinker not to get stuck on irrelevant evidence.
    assert "irrelevant" in msg.lower()


def test_prompt_shows_meaningful_objective_alongside_request():
    ev = Evidence(objective="Find and read the user's CV", user_message="read my cv", observations="found a.pdf")
    msg = build_thinker_messages(ev)[1]["content"]
    assert "read my cv" in msg
    assert "Find and read the user's CV" in msg  # meaningful objective still shown


# ── Contract ────────────────────────────────────────────────────────────────
def test_evidence_has_evidence_gate():
    assert Evidence(observations="").has_evidence is False
    assert Evidence(observations="   ").has_evidence is False
    assert Evidence(observations="found 3 files").has_evidence is True


def test_analysis_is_empty():
    assert ThinkerAnalysis().is_empty is True
    assert ThinkerAnalysis(next_step="call shell").is_empty is False
    assert ThinkerAnalysis(reasoning="hmm").is_empty is False


# ── S425 continuity: prior analysis compounds instead of restarting ─────────
def test_prompt_renders_prior_analysis_block():
    ev = Evidence(
        user_message="read my cv",
        observations="found cv.pdf",
        prior_analysis="  • cv.pdf is the newest\nNext step I was taking: read it",
    )
    msg = build_thinker_messages(ev)[1]["content"]
    assert "YOUR EARLIER THINKING THIS TURN" in msg
    assert "cv.pdf is the newest" in msg
    assert "do not repeat it" in msg, "the block must demand the DELTA, not a repetition"


def test_prompt_omits_prior_analysis_when_empty():
    ev = Evidence(user_message="read my cv", observations="found cv.pdf")
    msg = build_thinker_messages(ev)[1]["content"]
    assert "YOUR EARLIER THINKING" not in msg


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
async def test_consult_streams_prose_but_never_the_json():
    """ADR-57 slice 1 (S425): the consult's prose reasoning streams live as
    `thinking` chunks — no call runs silent — but the JSON structure NEVER
    surfaces (Session 324's leak, now enforced structurally: surfacing stops
    at the JSON marker). The structured analysis still parses so the loop can
    inject it into the agent's context."""
    chunks = [
        StreamChunk(text="Found two files; ", done=False),
        StreamChunk(text="the newer one matches the ask. ", done=False),
        StreamChunk(text='{"facts": ["f1"], "next_step": "read it", ', done=False),
        StreamChunk(text='"confidence": 0.7}', done=False),
        StreamChunk(text="", done=True),
    ]
    thinker = Thinker()
    surfaced = []
    final = None
    async for ch in thinker.consult(Evidence(observations="ls output"), _MockAdapter(chunks)):
        if ch.thinking:
            surfaced.append(ch.thinking)
        if ch.done:
            final = ch
    # The prose streamed; the JSON (split across chunks) never did.
    joined = "".join(surfaced)
    assert "the newer one matches" in joined
    assert '"facts"' not in joined and '"confidence"' not in joined and "{" not in joined
    # Structured analysis still parsed + attached for the agent's context.
    assert thinker.last_analysis.facts == ["f1"]
    assert thinker.last_analysis.next_step == "read it"
    assert final.metadata["thinker_analysis"]["next_step"] == "read it"


@pytest.mark.asyncio
async def test_consult_fenced_json_never_surfaces():
    """A ```json fence split across chunks must not leak either — the fence
    itself is held back and cut at the JSON start."""
    chunks = [
        StreamChunk(text="The newest report matches. ", done=False),
        StreamChunk(text="```json\n{\"next_step\": \"synthesize\"", done=False),
        StreamChunk(text="}\n```", done=False),
        StreamChunk(text="", done=True),
    ]
    thinker = Thinker()
    joined = ""
    async for ch in thinker.consult(Evidence(observations="x"), _MockAdapter(chunks)):
        if ch.thinking:
            joined += ch.thinking
    assert "matches" in joined
    assert "```" not in joined and '"next_step"' not in joined
    assert thinker.last_analysis.next_step == "synthesize"


@pytest.mark.asyncio
async def test_consult_no_json_streams_all_prose():
    """A JSON-less response is still useful reasoning — all of it streams."""
    chunks = [
        StreamChunk(text="Nothing conclusive here; ", done=False),
        StreamChunk(text="ask the user for the missing year.", done=False),
        StreamChunk(text="", done=True),
    ]
    thinker = Thinker()
    joined = ""
    async for ch in thinker.consult(Evidence(observations="x"), _MockAdapter(chunks)):
        if ch.thinking:
            joined += ch.thinking
    assert joined.strip() == "Nothing conclusive here; ask the user for the missing year."
    assert thinker.last_analysis.is_empty is False  # prose is the reasoning


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
