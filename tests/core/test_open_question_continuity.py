"""Cross-turn continuity: the open-question reply seam and the two new
TURN-band sections (the carried objective and the open question).

Contract under test:
- answers_open_question: a SHORT reply that is not a pure social gesture is
  an answer attempt against the outstanding question; social gestures and
  long messages are not. No record → False for everything.
- The new sections register in their doctrine slots (carried_objective in
  the objective layer at 1020; open_question in the context layer at 1095)
  and are TURN-only — a static registration is the cache-buster bug class
  and the registry refuses it.
- The forced-clarify stand-down condition: with an open question on record
  the gate must NOT fire, because the referent is known — it is the agent's
  own outstanding question (the repeated-clarification loop this build kills).
"""

from __future__ import annotations

import pytest

from core.agent.prompt import (
    Band,
    Layer,
    PromptStructureError,
    SectionRegistry,
    make,
    SECTION_CARRIED_OBJECTIVE,
    SECTION_OPEN_QUESTION,
    TURN_ONLY_SECTION_NAMES,
)
from core.trivial_input import (
    answers_open_question,
    is_pure_social_gesture,
    is_short_reply,
)


class TestAnswersOpenQuestion:
    def test_short_answers_resolve(self):
        q = "What specific location information are you looking for?"
        for reply in ("yes", "YES!", "nope", "ok", "sure", "what?", "CSV please", "city"):
            assert answers_open_question(reply, q), reply

    def test_pure_social_stays_light(self):
        q = "Do you want me to proceed with the install?"
        for gesture in ("lol", "haha", "nice", "cool", "wow", "hi", "hello", "lol!"):
            assert not answers_open_question(gesture, q), gesture

    def test_substantive_replies_are_not_short_answers(self):
        q = "Do you want me to proceed?"
        assert not answers_open_question(
            "Yes — but first check whether the config file already has the key set",
            q,
        )
        assert not answers_open_question("a" * 60, q)

    def test_no_record_means_no_resolution(self):
        assert not answers_open_question("yes", None)
        assert not answers_open_question("yes", "")

    def test_empty_message(self):
        assert not answers_open_question("   ", "Any question?")


class TestShapeHelpers:
    """The record lifecycle needs to tell three short-reply classes apart:
    an ANSWER (consume), a social GESTURE (leave outstanding), and anything
    longer (a substantive message — supersede)."""

    def test_short_reply_shape_without_pattern_list(self):
        # "lol" is short-shaped but NOT on the trivial pattern list — the
        # shape test must still call it short (the lifecycle then asks the
        # gesture question separately).
        assert is_short_reply("lol")
        assert is_short_reply("CSV please")
        assert not is_short_reply("a" * 50)
        assert not is_short_reply("six whole words in this message here ok")
        assert not is_short_reply("")

    def test_pure_social_gesture_detection(self):
        for gesture in ("lol", "haha", "nice!", "cool", "hi", "wow..."):
            assert is_pure_social_gesture(gesture), gesture
        for answer in ("yes", "nope", "CSV please", "what?"):
            assert not is_pure_social_gesture(answer), answer


def _sec(name, band, layer, order):
    return make(name, band, layer, order, f"{name} body text.")


class TestContinuitySections:
    def test_carried_objective_registers_in_objective_layer(self):
        r = SectionRegistry()
        r.add(_sec(SECTION_CARRIED_OBJECTIVE, Band.TURN, Layer.OBJECTIVE, 1020))
        rendered = r.render(Band.TURN)
        assert "carried_objective body text." in rendered

    def test_open_question_registers_in_context_layer(self):
        r = SectionRegistry()
        r.add(_sec(SECTION_OPEN_QUESTION, Band.TURN, Layer.CONTEXT, 1095))
        rendered = r.render(Band.TURN)
        assert "open_question body text." in rendered

    def test_both_names_are_turn_only(self):
        assert SECTION_CARRIED_OBJECTIVE in TURN_ONLY_SECTION_NAMES
        assert SECTION_OPEN_QUESTION in TURN_ONLY_SECTION_NAMES
        with pytest.raises(PromptStructureError):
            _sec(SECTION_CARRIED_OBJECTIVE, Band.STATIC, Layer.CONSTRAINTS, 120)
        with pytest.raises(PromptStructureError):
            _sec(SECTION_OPEN_QUESTION, Band.STATIC, Layer.CONSTRAINTS, 121)

    def test_doctrine_order_objective_before_context(self):
        r = SectionRegistry()
        r.add(_sec(SECTION_CARRIED_OBJECTIVE, Band.TURN, Layer.OBJECTIVE, 1020))
        r.add(_sec(SECTION_OPEN_QUESTION, Band.TURN, Layer.CONTEXT, 1095))
        r.add(_sec("late_context", Band.TURN, Layer.CONTEXT, 1100))
        names = [s.name for s in r.render_sections(Band.TURN)]
        assert names == [SECTION_CARRIED_OBJECTIVE, SECTION_OPEN_QUESTION, "late_context"]
