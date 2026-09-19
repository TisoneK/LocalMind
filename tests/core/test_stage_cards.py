"""Recovery/continue instructions are structured stage cards, not paragraphs of
'do NOT' rules. Live capture: the negative reminder was re-sent on every call and
glm still narrated; one recovery even named a tool (`file_read`) that does not
exist, and another contradicted itself about describe_tool."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.agent import loop as L

REQUEST = "List /Users/bao/Code, then the latest commit, then count the .py files."


def _trace(*steps):
    return SimpleNamespace(steps=[SimpleNamespace(tool_name=n, tool_failed=f) for n, f in steps])


MSGS = [{"role": "user", "content": REQUEST}]


def test_card_has_goal_done_so_far_and_one_decision():
    card = L._stage_card("STAGE: CONTINUE", "continue", L._DECISION_CONTINUE, MSGS,
                         _trace(("dir_explorer", False), ("shell", True)))
    assert card.startswith("\n[STAGE: CONTINUE] Stage: continue.")
    assert f"Goal: {REQUEST}" in card
    assert "Done so far: dir_explorer (ok), shell (failed)." in card
    assert card.count("Decision:") == 1


def test_card_with_nothing_run_says_so():
    card = L._stage_card("TOOL COMMITMENT", "act", L._DECISION_ACT, MSGS, _trace())
    assert "Done so far: nothing yet." in card


@pytest.mark.parametrize("decision", [
    L._DECISION_CONTINUE, L._DECISION_ACT, L._DECISION_ACT_ZERO, L._DECISION_FORCE_TOOL, L._DECISION_ANSWER,
])
def test_decisions_are_positive_and_name_no_wrong_tools(decision):
    low = decision.lower()
    assert "do not" not in low and "don't" not in low and "never" not in low
    assert "file_read" not in low  # not a tool in this app (it is file_task)


def test_card_is_recognised_as_harness_text_and_never_becomes_the_goal():
    card = L._stage_card("ACTION NARRATION", "act", L._DECISION_ACT, MSGS, _trace())
    assert L._is_harness_injected(card)
    msgs = MSGS + [{"role": "assistant", "content": "I'll list."}, {"role": "user", "content": card}]
    assert L._user_message_text(msgs) == REQUEST[:200]


def test_the_card_keeps_the_markers_the_already_nudged_checks_look_for():
    for tag in ("TOOL COMMITMENT", "ACTION NARRATION", "ZERO-TOOL"):
        assert f"[{tag}]" in L._stage_card(tag, "act", L._DECISION_ACT, MSGS, _trace())
