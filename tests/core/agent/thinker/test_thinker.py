"""Tests for the Thinker module — the agent's reasoning backbone."""

from __future__ import annotations

import asyncio

import pytest

from core.agent.thinker import (
    Evidence,
    Thinker,
    ThinkerAnalysis,
    parse_thinker_analysis,
)
from core.agent.thinker.prompt import build_thinker_messages
from core.models import StreamChunk


# ── Prompt anchors on the real request, not a generic fallback  ─────────
def test_prompt_shows_user_request_even_when_objective_is_generic():
    ev = Evidence(
        objective="Determine and complete the user's request.",  # init fallback
        user_message="Create a recipe on desktop for a nice dinner",
        observations="ls output: Facebook.lnk, WhatsApp Web.lnk",
        last_action="shell",
    )
    msg = build_thinker_messages(ev)[1]["content"]
    assert "Create a recipe on desktop" in msg, "the real request must be shown"
    # The generic fallback objective must NOT appear (it confused the analyst).
    assert "Determine and complete the user's request" not in msg
    # And the standing rule lives in the system prompt: don't get stuck on
    # irrelevant evidence.
    system = build_thinker_messages(ev)[0]["content"]
    assert "irrelevant" in system.lower()


def test_prompt_shows_meaningful_objective_alongside_request():
    ev = Evidence(objective="Find and read the user's CV", user_message="read my cv", observations="found a.pdf")
    msg = build_thinker_messages(ev)[1]["content"]
    assert "read my cv" in msg
    assert "Find and read the user's CV" in msg  # meaningful objective still shown


# ── The native-reasoning contract: decide, don't perform ────────────────────
def test_prompt_demands_a_json_only_answer_and_no_performed_prose():
    """The consult never asks the model to author thinking-shaped text: the
    reasoning happens in the model's reasoning channel; the answer channel
    carries exactly one JSON object. An 'inner voice' casting would be an
    instruction to perform thinking, and a performance is not shown."""
    system = build_thinker_messages(Evidence(user_message="x"))[0]["content"]
    assert "EXACTLY ONE JSON object" in system
    assert "no prose before or after it" in system
    assert "reasoning channel" in system, "the model must be told where reasoning happens"
    assert "inner voice" not in system
    assert "thinking out loud" not in system
    assert "first person" not in system


def test_prompt_keeps_the_decision_quality_rules():
    system = build_thinker_messages(Evidence(user_message="x"))[0]["content"]
    assert "QUESTIONS from DIRECTIVES" in system
    assert "Invent nothing" in system
    assert "DEFAULT" in system, "ambiguities must carry the default to proceed on"


# ── Contract ────────────────────────────────────────────────────────────────
def test_evidence_has_evidence_gate():
    assert Evidence(observations="").has_evidence is False
    assert Evidence(observations="   ").has_evidence is False
    assert Evidence(observations="found 3 files").has_evidence is True


def test_analysis_is_empty():
    assert ThinkerAnalysis().is_empty is True
    assert ThinkerAnalysis(next_step="call shell").is_empty is False
    assert ThinkerAnalysis(reasoning="hmm").is_empty is False


# ── Continuity: prior analysis compounds instead of restarting ─────────────
def test_prompt_renders_prior_analysis_block():
    ev = Evidence(
        user_message="read my cv",
        observations="found cv.pdf",
        prior_analysis="  • cv.pdf is the newest\nNext step I was taking: read it",
    )
    msg = build_thinker_messages(ev)[1]["content"]
    assert "YOUR EARLIER ANALYSIS THIS TURN" in msg
    assert "cv.pdf is the newest" in msg
    assert "do not repeat it" in msg, "the block must demand the DELTA, not a repetition"


def test_prompt_omits_prior_analysis_when_empty():
    ev = Evidence(user_message="read my cv", observations="found cv.pdf")
    msg = build_thinker_messages(ev)[1]["content"]
    assert "YOUR EARLIER ANALYSIS" not in msg


# ── Parser ──────────────────────────────────────────────────────────────────
def test_parse_json_with_native_reasoning():
    a = parse_thinker_analysis(
        '{"facts": ["report_2024.pdf is the newest"], '
        '"ambiguities": [{"text": "which format", "default": "pdf"}], '
        '"next_step": "read report_2024.pdf", "confidence": 0.8}',
        reasoning="Two candidates found; the 2024 one matches the ask.",
    )
    assert a.reasoning == "Two candidates found; the 2024 one matches the ask."
    assert a.facts == ["report_2024.pdf is the newest"]
    assert a.ambiguities[0].text == "which format" and a.ambiguities[0].default == "pdf"
    assert a.next_step == "read report_2024.pdf"
    assert a.confidence == 0.8


def test_parse_fenced_json():
    a = parse_thinker_analysis(
        '```json\n{"next_step": "synthesize the final answer"}\n```',
        reasoning="Enough is known.",
    )
    assert a.next_step == "synthesize the final answer"
    assert a.reasoning == "Enough is known."


def test_parse_text_prose_is_never_cast_as_reasoning():
    """Prose in the answer channel is a contract violation, not a thought:
    it must never surface as the analysis reasoning."""
    a = parse_thinker_analysis(
        "I looked and found nothing conclusive.",
        reasoning="the results carry no temperature figure",
    )
    assert a.reasoning == "the results carry no temperature figure"
    assert "nothing conclusive" not in a.reasoning
    assert a.facts == [] and a.next_step == ""


def test_parse_no_json_no_native_reasoning_is_empty():
    a = parse_thinker_analysis("Here is my analysis as requested.")
    assert a.reasoning == ""
    assert a.facts == [] and a.next_step == ""
    assert a.is_empty is True  # nothing usable — the loop proceeds on its own


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
async def test_consult_streams_native_reasoning_verbatim_and_never_the_answer():
    """The thinking channel streams as it arrives, untouched. The answer
    channel — JSON or any prose — never surfaces: the visible thought is
    the model's actual reasoning, not text authored to look like it."""
    chunks = [
        StreamChunk(text="", thinking="two candidates; checking dates first. ", done=False),
        StreamChunk(text="the 2024 file matches. ", done=False),
        StreamChunk(text="", thinking="the older one predates the request. ", done=False),
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
    joined = "".join(surfaced)
    # Native reasoning streamed verbatim, in order.
    assert joined == "two candidates; checking dates first. the older one predates the request. "
    # The answer channel never leaked — neither the JSON nor its prose.
    assert '"facts"' not in joined and "{" not in joined
    assert "the 2024 file matches" not in joined
    # The structured analysis still parsed for the agent's context.
    assert thinker.last_analysis.facts == ["f1"]
    assert thinker.last_analysis.next_step == "read it"
    assert final.metadata["thinker_analysis"]["next_step"] == "read it"


@pytest.mark.asyncio
async def test_consult_text_only_answer_shows_nothing_but_still_decides():
    """A provider that streams no reasoning channel: the consult honestly
    shows nothing — silence, not a performance — and the JSON decision
    still parses so the loop is shaped by it."""
    chunks = [
        StreamChunk(text='{"facts": ["f1"], "next_step": "read it", "confidence": 0.9}', done=False),
        StreamChunk(text="", done=True),
    ]
    thinker = Thinker()
    surfaced = ""
    async for ch in thinker.consult(Evidence(observations="x"), _MockAdapter(chunks)):
        surfaced += ch.thinking or ""
    assert surfaced == ""
    assert thinker.last_analysis.next_step == "read it"


@pytest.mark.asyncio
async def test_consult_json_less_answer_stays_honest():
    """No reasoning channel and no JSON: nothing is shown and the analysis is
    empty — the loop proceeds on its own next step (never a fabricated
    thought to fill the silence)."""
    chunks = [
        StreamChunk(text="Nothing conclusive here; ask the user.", done=False),
        StreamChunk(text="", done=True),
    ]
    thinker = Thinker()
    surfaced = ""
    async for ch in thinker.consult(Evidence(observations="x"), _MockAdapter(chunks)):
        surfaced += ch.thinking or ""
    assert surfaced == ""
    assert thinker.last_analysis.is_empty is True


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


@pytest.mark.asyncio
async def test_consult_timeout_keeps_the_reasoning_it_saw():
    """A wall-clock timeout mid-reasoning yields what arrived — real
    reasoning, not a substitute — plus the safe empty analysis."""

    class _SlowAdapter:
        async def chat(self, messages, temperature=0.4, intent="analyze", **kwargs):
            yield StreamChunk(text="", thinking="still weighing the sources...", done=False)
            await asyncio.sleep(10)  # far past the consult timeout
            yield StreamChunk(text='{"next_step": "x"}', done=False)  # pragma: no cover

    thinker = Thinker(timeout_secs=0.05)
    surfaced = ""
    async for ch in thinker.consult(Evidence(observations="x"), _SlowAdapter()):
        if ch.done:
            break
        surfaced += ch.thinking or ""
    assert "still weighing" in surfaced
    assert thinker.last_analysis is not None
