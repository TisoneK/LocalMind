"""Questions about the conversation are answered from the conversation.

Field failure (2026-10-31): every question ABOUT the chat was answered as if it
were about long-term memory.

  "Did you answer that from memory?"  -> ran `Memory: list`, printed 4 stored
                                        facts the user never asked about
  "Did I ask about that?"            -> "Yes, you did ask about that" (wrong)
  "Don't you?"                       -> taken as a question about something else
  "What was your reply before that?" -> died on a rejected payload

The rules these tests hold LocalMind to: a recall question is recognised
deterministically, takes the transcript lane with NO memory and NO tools, and a
short follow-up is resolved against the most recent assistant turn.
"""

import pytest
from core.trivial_input import (
    conversational_response,
    is_conversation_recall_question,
    is_conversational_question,
)
from unittest.mock import MagicMock


# ── recognition ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "message",
    [
        "Did you answer that from memory?",
        "Did i ask about that?",
        'When i asked "Do you?" what did I mean?',
        "What was your reply before that question???",
        "what did I ask first?",
        "What did you just say?",
    ],
)
def test_the_real_questions_from_the_failing_chat_are_recognised(message):
    assert is_conversation_recall_question(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "Don't you?",  # a challenge to the previous claim, not a recall question
        "what did I write to app.py?",  # a file question needs the file
        "what did you say about the weather?",  # live data, still a tool question
        "run the tests",
        "",
        None,
    ],
)
def test_questions_that_need_a_tool_or_file_are_not_recall_questions(message):
    assert is_conversation_recall_question(message) is False


# ── the transcript lane ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recall_lane_sends_the_transcript_and_no_stored_memory():
    seen: dict = {}

    async def mock_chat(messages, intent="chat", **kwargs):
        seen["messages"] = messages
        yield MagicMock(text="You said: hi.", done=False)
        yield MagicMock(text="", done=True)

    adapter = MagicMock()
    adapter.chat = mock_chat

    history = [
        {"role": "user", "content": "Hi LM"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "What can you do?"},
        {"role": "assistant", "content": "I can run shell commands."},
    ]

    [c async for c in conversational_response(
        "What was your reply before that question?",
        adapter,
        history,
        memory_facts=["Preferred weather source: https://wttr.in/{place}?format=j1"],
        transcript_only=True,
        first_user_message="Hi LM",
    )]

    system = seen["messages"][0]["content"]
    assert "ABOUT THE CONVERSATION ITSELF" in system
    assert "Hi LM" in system  # the first user message is quoted, not recalled
    assert "wttr.in" not in system  # long-term memory is withheld
    # The transcript itself rides along, in order.
    contents = [m.get("content") for m in seen["messages"][1:]]
    assert "Hi there!" in contents
    assert "I can run shell commands." in contents


@pytest.mark.asyncio
async def test_ordinary_conversation_still_gets_its_memory_facts():
    seen: dict = {}

    async def mock_chat(messages, intent="chat", **kwargs):
        seen["messages"] = messages
        yield MagicMock(text="ok", done=False)
        yield MagicMock(text="", done=True)

    adapter = MagicMock()
    adapter.chat = mock_chat

    [c async for c in conversational_response(
        "What can you do?",
        adapter,
        None,
        memory_facts=["Preferred weather source: wttr.in"],
    )]

    assert "wttr.in" in seen["messages"][0]["content"]


# ── short follow-ups resolve against the previous turn ─────────────────────


def test_a_short_follow_up_reads_the_last_reply_even_if_an_older_turn_ran_tools():
    """"Don't you?" referred to the assistant's own last sentence. An older
    tool-using turn in the same window used to push it into the agent loop,
    where it was answered as a question about something else."""
    history = [
        {"role": "user", "content": "Did i ask about that?"},
        {
            "role": "assistant",
            "content": "Yes, you did ask about that.",
            "tool_calls": [{"id": "tc-1", "type": "function", "function": {"name": "memory_op"}}],
        },
        {"role": "user", "content": "I in my chat where did i mention about weather???"},
        {"role": "assistant", "content": "I do not have any information stored about it."},
    ]
    assert is_conversational_question("Don't you?", history) is True


def test_a_follow_up_to_a_turn_that_ran_tools_still_goes_to_the_agent():
    history = [
        {"role": "user", "content": "list the folder"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "tc-1", "type": "function", "function": {"name": "shell"}}],
        },
    ]
    assert is_conversational_question("Like what?", history) is False
