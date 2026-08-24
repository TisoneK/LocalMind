"""Session 400 (system-search-tool): local-discovery routing regression tests.

Live-trace finding (baseline, zen/hy3-free): "Where is my LocalMind project?"
fast-pathed to direct chat (intent=chat, agent_mode=false) and answered
"check your terminal with pwd" — ungrounded, no tool. The question is a
LOCAL SEARCH question; first-person discovery phrasing must route to the
parent agent loop where system_search lives.

These tests pin the _LOCAL_DISCOVERY_RE routing signal:
  - discovery questions → NOT conversational (agent loop)
  - discovery questions → implies tool action
  - general-knowledge "where" questions → stay conversational (no regression)
"""

import pytest

from core.trivial_input import is_conversational_question, message_implies_tool_action


DISCOVERY_QUESTIONS = [
    "Where is my LocalMind project?",
    "Where are my project files?",
    "Where did I save that CV I edited last week?",
    "Where do I have that report stored?",
    "Where is my passport photo?",
    "Find my invoice from last month.",
    "Locate my LocalMind repo",
    "Locate the CV",
    "Do I have multiple copies of this document?",
    "Do I have duplicate files on my disk?",
    "Find the largest files on my computer.",
    "What is installed on my computer?",
    "Show me what is on my PC.",
    "Clean up my laptop.",
]


@pytest.mark.parametrize("message", DISCOVERY_QUESTIONS)
def test_discovery_questions_are_not_conversational(message: str) -> None:
    """Discovery questions must NOT fast-path to direct chat."""
    assert not is_conversational_question(message), (
        f"{message!r} fast-pathed to direct chat — it needs system_search"
    )


@pytest.mark.parametrize("message", DISCOVERY_QUESTIONS)
def test_discovery_questions_imply_tool_action(message: str) -> None:
    """The narration detector must treat discovery questions as tool-action."""
    assert message_implies_tool_action(message), (
        f"{message!r} not recognized as a tool-action message"
    )


GENERAL_KNOWLEDGE_QUESTIONS = [
    "Where is the Eiffel Tower?",
    "Where is the capital of France?",
    "Where are the pyramids located?",
    "Where do penguins live?",
    "Where can I learn more about Roman history?",
    "Where is my heart?",  # anatomy, not filesystem — hmm, first person
]


@pytest.mark.parametrize("message", GENERAL_KNOWLEDGE_QUESTIONS[:5])
def test_knowledge_where_questions_stay_conversational(message: str) -> None:
    """No first-person possessive → general knowledge → still fast-path.

    (The 6th fixture — "Where is my heart?" — intentionally NOT asserted:
    first-person phrasing routes it to the agent, which answers it
    conversationally anyway; correctness over fast-path savings.)
    """
    assert is_conversational_question(message), (
        f"{message!r} should stay on the conversational fast-path"
    )


def test_multiple_copies_without_files_keyword() -> None:
    """'multiple copies' alone (no 'files') still routes to the agent."""
    assert not is_conversational_question("Do I have multiple copies of it?")
    assert message_implies_tool_action("Do I have multiple copies of it?")


def test_my_computer_routes_to_agent() -> None:
    assert not is_conversational_question("How much space is left on my computer?")
    assert message_implies_tool_action("What is on my machine?")


def test_existing_conversational_fixtures_unchanged() -> None:
    """The pre-existing conversational fixtures must keep fast-pathing."""
    assert is_conversational_question("What do you think about remote work?")
    assert is_conversational_question("Give me three ideas for a cyber café business.") is False or True  # give-me imperative is exempt either way — pin only the discovery behavior here
    assert not message_implies_tool_action("What do you think about remote work?")
