"""Tests for the Thinker module  — the agent's reasoning backbone."""

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


# ── S425: the visible prose stays on the task, free of agent machinery ──────
def test_prompt_forbids_internals_in_visible_reasoning():
    """Owner directive: the streamed thinking reads like a person thinking
    about the TASK — no tool names, no 'tool', no steps/loops/iterations/
    prompts/'synthesize'/'the system' in the prose. The JSON tail is exempt
    (the agent's mechanics may name tools)."""
    system = build_thinker_messages(Evidence(user_message="x"))[0]["content"]
    assert "free of machinery" in system
    assert "never name a tool" in system
    assert "MAY name tools" in system, "the JSON exemption must be explicit"


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
    """ADR-57 slice 1: the consult's prose reasoning streams live as
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


# ── the Thinker's reasoning about its own output format never reaches the user ──

CONTRACT_META = (
    "Now I need to format my response as JSON with:\n"
    "- facts: What I know for certain\n"
    "- ambiguities: Any uncertainties\n"
    "- next_step: What I should do next\n"
    "- confidence: A confidence score between 0.0 and 1.0"
)


def test_contract_paragraphs_are_recognised():
    from core.agent.thinker.thinker import _is_contract_meta

    assert _is_contract_meta(CONTRACT_META)
    assert _is_contract_meta("Facts:\n- User is asking for current weather in Kitengela")
    assert _is_contract_meta("Ambiguities:\n- I don't know the exact conditions")
    assert _is_contract_meta("I'll write the answer as JSON with a next_step field.")


def test_ordinary_reasoning_is_not_mistaken_for_contract():
    from core.agent.thinker.thinker import _is_contract_meta

    assert not _is_contract_meta("The user wants the weather right now, so I should search the web.")
    assert not _is_contract_meta("The facts are clear: the tool returned 0 matches for 'disk'.")
    assert not _is_contract_meta("Kitengela is in Kenya, based on my knowledge.")


def test_gate_streams_whole_paragraphs_and_drops_contract_ones():
    from core.agent.thinker.thinker import _ProseGate

    gate = _ProseGate()
    out: list[str] = []
    # Arrives in awkward fragments, as a token stream does.
    for piece in ("The user wants the wea", "ther now.\n\nNow I need to format my resp",
                  "onse as JSON with:\n- facts: x\n- next_step: y\n\nSo I should search the web."):
        out += gate.feed(piece)
    out += gate.flush()
    text = "".join(out)
    assert "The user wants the weather now." in text
    assert "So I should search the web." in text
    assert "JSON" not in text and "next_step" not in text


@pytest.mark.asyncio
async def test_consult_surfaces_only_the_real_reasoning():
    prose = (
        "The user asks about disk space, which the system line already carries.\n\n"
        f"{CONTRACT_META}\n\n"
        "Facts:\n- disk has 16.1 GB free\n\n"
    )
    json_block = '{"facts": ["16.1 GB free"], "ambiguities": [], "next_step": "answer", "confidence": 0.9}'

    class FakeAdapter:
        async def chat(self, messages, temperature=0.4, **kwargs):
            yield StreamChunk(text=prose + json_block, done=False)
            yield StreamChunk(text="", done=True)

    surfaced = ""
    evidence = Evidence(user_message="how much free disk space do I have?", observations="none")
    async for chunk in Thinker().consult(evidence, FakeAdapter()):
        surfaced += chunk.thinking or ""
    assert "system line already carries" in surfaced
    assert "JSON" not in surfaced and "Facts:" not in surfaced and "next_step" not in surfaced
