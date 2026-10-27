"""The consult's visible reasoning is the model's own — bounded by the
wall-clock timeout and the provider's reasoning level, never by a prose
budget. What the prompt must NOT do is ask for performed prose."""

import pytest

from core.agent.thinker.contract import Evidence
from core.agent.thinker.prompt import _PRIOR_CHARS, build_thinker_messages
from core.agent.thinker.thinker import Thinker
from core.models import StreamChunk


def _evidence(**kw):
    base = {"user_message": "make a game", "objective": "", "observations": "", "iteration": 1}
    base.update(kw)
    return Evidence(**base)


def test_the_prompt_asks_for_no_prose_at_all():
    system = build_thinker_messages(_evidence())[0]["content"]
    # The answer is the JSON object — nothing else. No monologue to size.
    assert "EXACTLY ONE JSON object" in system
    assert "no prose before or after it" in system
    # The old visible-prose budgets are gone: reasoning length is the
    # reasoning level's and the timeout's business, not a word target.
    assert "200 words" not in system
    assert "as long as the decision needs" not in system
    # Depth lives in the decision rules, not a length rule.
    assert "Depth is the decision's" in system


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
            if isinstance(c, str):
                yield StreamChunk(text=c)
            else:
                yield c


@pytest.mark.asyncio
async def test_a_long_answer_channel_is_never_shown_as_thought():
    """A model that pads the answer channel with thinking-shaped prose gets
    no stage: none of it surfaces, and the consult still completes safely."""
    adapter = _Adapter(["Considering the options again. " * 400])  # ~12,000 chars, no JSON
    out = [c async for c in Thinker().consult(_evidence(), adapter)]
    shown = "".join(c.thinking or "" for c in out)
    assert shown == ""
    assert out[-1].done
    assert adapter.consumed == 1  # the whole stream was read — padding costs no stage time


@pytest.mark.asyncio
async def test_native_reasoning_streams_without_a_paragraph_gate():
    """Real reasoning is passed through untouched — no gate rewriting it,
    no char cut, even when it names the very fields the answer uses."""
    adapter = _Adapter(
        [
            StreamChunk(text="", thinking="Facts: the folder is missing. next_step: create it. ", done=False),
            StreamChunk(
                text='{"facts": ["no folder"], "next_step": "create the folder", "confidence": 0.9}', done=False
            ),
            StreamChunk(text="", done=True),
        ]
    )
    out = [c async for c in Thinker().consult(_evidence(), adapter)]
    shown = "".join(c.thinking or "" for c in out)
    assert shown == "Facts: the folder is missing. next_step: create it. "
    assert out[-1].metadata["thinker_analysis"]["next_step"] == "create the folder"
