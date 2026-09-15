"""Local-discovery routing must cover the whole search space.

`_LOCAL_DISCOVERY_RE` forces first-person "find/where/what-on-my-machine"
questions to the agent (so system_search runs) instead of a tool-less
conversational answer. It was tuned to a few prompts (where/find/duplicates +
"on my computer"), so recency, size/space, installed-apps, and open-with
phrasings slipped through and got answered without any search. These tests pin
category coverage AND guard against over-matching genuine conversation.
"""

from __future__ import annotations

import pytest

from core.trivial_input import (
    _is_local_discovery,
    is_conversational_question,
    message_implies_tool_action,
)

_DISCOVERY = [
    # locate
    "Where is my LocalMind project?",
    "Where did I save that CV?",
    "Find my tax documents",
    # recent
    "What files did I work on recently?",
    "Show me my recent files",
    "What have I been working on lately?",
    "recently modified files",
    # largest / space
    "Find the largest files on my computer",
    "What are the biggest files?",
    "What's taking up space on my disk?",
    "help me free up disk space",
    # duplicates
    "Do I have duplicate photos?",
    "Do I have multiple copies of this?",
    # installed apps
    "Do I have Python installed?",
    "Is Docker installed?",
    "What apps do I have?",
    # open-with
    "What can open a .psd file?",
]

_CONVERSATIONAL = [
    "Where is the Eiffel Tower?",
    "What is the largest planet?",
    "How do I install Python?",
    "What is the biggest challenge in AI?",
    "Tell me a joke",
    "Can you help me write a function?",
]


@pytest.mark.parametrize("msg", _DISCOVERY)
def test_discovery_questions_are_not_conversational(msg: str) -> None:
    # A discovery question must be detected as local-discovery, fall through to
    # the agent (system_search), and imply a tool action.
    assert _is_local_discovery(msg) is True, msg
    assert is_conversational_question(msg) is False, msg
    assert message_implies_tool_action(msg) is True, msg


@pytest.mark.parametrize("msg", _CONVERSATIONAL)
def test_genuine_conversation_is_not_hijacked_to_search(msg: str) -> None:
    # These must NOT be forced to SEARCH by the discovery detector. (Some may
    # still imply OTHER tool actions — "install"/"write" — which is fine; the
    # concern here is only that they aren't mistaken for a filesystem search.)
    assert _is_local_discovery(msg) is False, msg
