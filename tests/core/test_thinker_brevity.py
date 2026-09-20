"""The Thinker is asked for decision-grade reasoning, and cut off if it pads instead."""

import pytest
from core.agent.thinker.contract import Evidence
from core.agent.thinker.prompt import _PRIOR_CHARS, build_thinker_messages
from core.agent.thinker.thinker import MAX_PROSE_CHARS, Thinker
from core.models import StreamChunk


def _evidence(**kw):
    base = {"user_message": "make a game", "objective": "", "observations": "", "iteration": 1}
    base.update(kw)
    return Evidence(**base)


def test_the_prompt_states_a_length_budget():
    system = build_thinker_messages(_evidence())[0]["content"]
    assert "budget" in system.lower() and "200 words" in system
    assert "as long as the decision needs" not in system  # the open-ended wording is gone


def test_earlier_thinking_is_shown_only_by_its_tail():
    long_prior = "A" * 5000 + "THE-LAST-POINT"
    user = build_thinker_messages(_evidence(prior_analysis=long_prior))[1]["content"]
    assert "THE-LAST-POINT" in user
    assert user.count("A") <= _PRIOR_CHARS + 50


class _Adapter:
    def __init__(self, chunks):
        self.chunks = chunks
        self.consumed = 0

    async def chat(self, messages, temperature=0.4, intent="analyze"):
        for c in self.chunks:
            self.consumed += 1
            yield StreamChunk(text=c)


@pytest.mark.asyncio
async def test_a_runaway_reasoning_with_no_decision_is_cut_off():
    adapter = _Adapter(["Considering the options again. " * 10] * 40)  # ~12,000 chars, no JSON
    out = [c async for c in Thinker().consult(_evidence(), adapter)]
    shown = "".join(c.thinking or "" for c in out)
    assert len(shown) <= MAX_PROSE_CHARS + 400
    assert adapter.consumed < 40  # it stopped reading


@pytest.mark.asyncio
async def test_a_short_reasoning_with_its_decision_is_untouched():
    adapter = _Adapter(['The folder is missing; create it first.\n\n{"facts": ["no folder"], "ambiguities": [], "next_step": "create the folder", "confidence": 0.9}'])
    out = [c async for c in Thinker().consult(_evidence(), adapter)]
    assert "create it first" in "".join(c.thinking or "" for c in out)
    assert out[-1].metadata["thinker_analysis"]["next_step"] == "create the folder"
