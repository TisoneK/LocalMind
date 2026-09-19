"""The current user message must reach the model once, not twice.

Live capture: the first model call carried the user's request as two identical
back-to-back user messages (the store already held it; the assembler appended it
again)."""
from __future__ import annotations

import core.engine  # noqa: F401  (import order: agent_runtime resolves its cycle via engine)
from core.agent_runtime import _history_without_current_turn
from core.models import Message, Role


def _m(role, text):
    return Message(role=role, content=text)


def test_trailing_copy_of_the_current_message_is_dropped():
    h = [_m(Role.USER, "hi"), _m(Role.ASSISTANT, "hello"), _m(Role.USER, "list my folders")]
    out = _history_without_current_turn(h, "list my folders")
    assert [x.content for x in out] == ["hi", "hello"]


def test_history_without_the_current_message_is_untouched():
    h = [_m(Role.USER, "hi"), _m(Role.ASSISTANT, "hello")]
    assert _history_without_current_turn(h, "list my folders") == h


def test_a_genuine_earlier_repeat_is_kept():
    h = [_m(Role.USER, "yes"), _m(Role.ASSISTANT, "done"), _m(Role.USER, "yes")]
    out = _history_without_current_turn(h, "yes")
    assert [x.content for x in out] == ["yes", "done"]


def test_whitespace_differences_still_match_and_assistant_tail_is_not_touched():
    assert _history_without_current_turn([_m(Role.USER, " go \n")], "go") == []
    h = [_m(Role.USER, "go"), _m(Role.ASSISTANT, "go")]
    assert _history_without_current_turn(h, "go") == h


def test_empty_history_and_input_list_not_mutated():
    assert _history_without_current_turn([], "x") == []
    h = [_m(Role.USER, "x")]
    _history_without_current_turn(h, "x")
    assert len(h) == 1
