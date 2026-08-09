"""
Tests for the trivial-input detector — the short-circuit that prevents
greetings/thanks/farewells from hitting the full ThinkingDispatcher.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.trivial_input import (
    conversational_intent,
    conversational_response,
    is_conversational_question,
    is_trivial_input,
    trivial_intent,
)

# ── Greetings ────────────────────────────────────────────────────────────────


def test_greeting_hi():
    assert is_trivial_input("hi") is True
    assert is_trivial_input("Hi") is True
    assert is_trivial_input("HI") is True
    assert is_trivial_input("hiiii") is True


def test_greeting_hello():
    assert is_trivial_input("hello") is True
    assert is_trivial_input("Hello!") is True
    assert is_trivial_input("hello?") is True


def test_greeting_hey():
    assert is_trivial_input("hey") is True
    assert is_trivial_input("heya") is True


def test_greeting_good_morning():
    assert is_trivial_input("good morning") is True
    assert is_trivial_input("Good evening") is True
    assert is_trivial_input("good afternoon") is True


def test_greeting_whats_up():
    assert is_trivial_input("what's up") is True
    assert is_trivial_input("whats up") is True
    assert is_trivial_input("how are you") is True


# ── Farewells ────────────────────────────────────────────────────────────────


def test_farewell_bye():
    assert is_trivial_input("bye") is True
    assert is_trivial_input("Bye!") is True
    assert is_trivial_input("goodbye") is True


def test_farewell_see_you():
    assert is_trivial_input("see you") is True
    assert is_trivial_input("see you later") is True
    assert is_trivial_input("see you tomorrow") is True


def test_farewell_good_night():
    assert is_trivial_input("good night") is True
    assert is_trivial_input("have a good day") is True


# ── Thanks ───────────────────────────────────────────────────────────────────


def test_thanks_basic():
    assert is_trivial_input("thanks") is True
    assert is_trivial_input("thank you") is True
    assert is_trivial_input("thx") is True
    assert is_trivial_input("ty") is True


def test_thanks_appreciate():
    assert is_trivial_input("appreciate it") is True
    assert is_trivial_input("cheers") is True


# ── Acknowledgments ──────────────────────────────────────────────────────────


def test_ack_ok():
    assert is_trivial_input("ok") is True
    assert is_trivial_input("okay") is True
    assert is_trivial_input("k") is True
    assert is_trivial_input("OK!") is True


def test_ack_got_it():
    assert is_trivial_input("got it") is True
    assert is_trivial_input("understood") is True
    assert is_trivial_input("sure") is True
    assert is_trivial_input("will do") is True


# ── Yes/No ───────────────────────────────────────────────────────────────────


def test_yes_no():
    assert is_trivial_input("yes") is True
    assert is_trivial_input("no") is True
    assert is_trivial_input("yep") is True
    assert is_trivial_input("nope") is True
    assert is_trivial_input("yeah") is True
    assert is_trivial_input("nah") is True


# ── Non-trivial inputs (must NOT short-circuit) ─────────────────────────────


def test_question_not_trivial():
    """Questions are not trivial — they need the full pipeline."""
    assert is_trivial_input("what is the weather today?") is False
    assert is_trivial_input("how do I fix a bug in Python?") is False
    assert is_trivial_input("can you help me with coding?") is False


def test_code_request_not_trivial():
    """Code requests are not trivial."""
    assert is_trivial_input("write a function to sort a list") is False
    assert is_trivial_input("fix the bug in app.py") is False
    assert is_trivial_input("run the tests") is False


def test_long_message_not_trivial():
    """Long messages are not trivial."""
    assert is_trivial_input("hi, I'm working on a project and I need help with the agent loop implementation") is False
    assert is_trivial_input("hello, can you help me debug an issue with my FastAPI backend that's failing on startup") is False


def test_complex_greeting_not_trivial():
    """A greeting followed by a real question is NOT trivial."""
    assert is_trivial_input("Hi, can you help me with coding?") is False
    assert is_trivial_input("Hello! I need to fix a bug in my Python code") is False
    assert is_trivial_input("hey, what's the weather?") is False


def test_empty_message_not_trivial():
    """Empty messages are not trivial (handled elsewhere)."""
    assert is_trivial_input("") is False
    assert is_trivial_input("   ") is False
    assert is_trivial_input(None) is False


def test_many_words_not_trivial():
    """Messages with >5 words are not trivial even if they start with a greeting."""
    assert is_trivial_input("hi there how are you doing today my friend") is False


# ── Punctuation handling ─────────────────────────────────────────────────────


def test_punctuation_stripped():
    """Trailing punctuation is stripped before matching."""
    assert is_trivial_input("hi!") is True
    assert is_trivial_input("hello?") is True
    assert is_trivial_input("thanks.") is True
    assert is_trivial_input("ok,") is True
    assert is_trivial_input("bye;") is True


# ── trivial_intent() ─────────────────────────────────────────────────────────


def test_trivial_intent_greeting():
    assert trivial_intent("hi") == "greeting"
    assert trivial_intent("hello") == "greeting"
    assert trivial_intent("good morning") == "greeting"


def test_trivial_intent_farewell():
    assert trivial_intent("bye") == "farewell"
    assert trivial_intent("see you later") == "farewell"


def test_trivial_intent_thanks():
    assert trivial_intent("thanks") == "thanks"
    assert trivial_intent("thank you") == "thanks"


def test_trivial_intent_acknowledgment():
    assert trivial_intent("ok") == "acknowledgment"
    assert trivial_intent("got it") == "acknowledgment"


def test_trivial_intent_yes_no():
    assert trivial_intent("yes") == "yes_no"
    assert trivial_intent("no") == "yes_no"


# ── Edge cases ───────────────────────────────────────────────────────────────


def test_case_insensitive():
    """All patterns are case-insensitive."""
    assert is_trivial_input("HI") is True
    assert is_trivial_input("ByE") is True
    assert is_trivial_input("THANKS") is True
    assert is_trivial_input("Ok") is True


def test_leading_trailing_whitespace():
    """Whitespace is stripped."""
    assert is_trivial_input("  hi  ") is True
    assert is_trivial_input("\thello\n") is True


# ── Conversational questions (Session 68 / ADR-11 fast-path) ────────────────
# B-2026-08-09-1: obviously-conversational questions must short-circuit to a
# single direct chat call, skipping the ThinkingDispatcher's LLM
# capability-inference call (verified root cause of ~40s "What can you do?"
# latency — two sequential LLM calls). The detector is deliberately
# conservative: any tool/realtime/system keyword falls through so routing
# (WEB_SEARCH / SYSINFO / SHELL / FILE_TASK) still works.


def test_conversational_question_fast_path_positives():
    """Conversational questions with no tool/realtime keywords must fast-path."""
    assert is_conversational_question("What can you do?") is True
    assert is_conversational_question("what can you do") is True
    assert is_conversational_question("Who are you?") is True
    assert is_conversational_question("What is LocalMind?") is True
    assert is_conversational_question("what's your name") is True
    assert is_conversational_question("Tell me about yourself") is True
    assert is_conversational_question("Can you help me?") is True
    assert is_conversational_question("What are your capabilities?") is True
    assert is_conversational_question("Explain how you work") is True
    assert is_conversational_question("How does this work?") is True
    assert is_conversational_question("what should I do") is True
    assert is_conversational_question("Why do you exist?") is True


def test_conversational_question_realtime_queries_fall_through():
    """Live-data queries must NOT fast-path — they need WEB_SEARCH routing."""
    assert is_conversational_question("what is the weather today?") is False
    assert is_conversational_question("what is today's EPL games?") is False
    assert is_conversational_question("what's the latest news?") is False
    assert is_conversational_question("how much does a new laptop cost?") is False
    assert is_conversational_question("who won the match yesterday?") is False
    assert is_conversational_question("what is the current temperature?") is False
    assert is_conversational_question("what is the stock price of Apple?") is False


def test_conversational_question_sysinfo_queries_fall_through():
    """Time/date/system queries must NOT fast-path — they need SYSINFO routing."""
    assert is_conversational_question("what time is it") is False
    assert is_conversational_question("what is today's date") is False
    assert is_conversational_question("what day is it") is False
    assert is_conversational_question("how much RAM do I have") is False
    assert is_conversational_question("what are my computer specs") is False
    assert is_conversational_question("what cpu do I have") is False
    assert is_conversational_question("how much disk space is free") is False


def test_conversational_question_tool_file_queries_fall_through():
    """Tool/file/code queries must NOT fast-path — they need tool routing."""
    assert is_conversational_question("how do I fix a bug in Python?") is False
    assert is_conversational_question("can you search for that") is False
    assert is_conversational_question("what does this error mean?") is False
    assert is_conversational_question("who wrote app.py") is False
    assert is_conversational_question("show me projects in Documents") is False
    assert is_conversational_question("can you open the file") is False
    assert is_conversational_question("why is my code failing") is False
    assert is_conversational_question("what is a good way to write tests") is False
    assert is_conversational_question("how do I run this script") is False
    assert is_conversational_question("what does git status do") is False
    assert is_conversational_question("explain this error message") is False


def test_conversational_question_not_an_opener():
    """Messages that don't open like a question must NOT fast-path."""
    assert is_conversational_question("projects in Documents") is False
    assert is_conversational_question("tell me about the file") is False  # "file" blocked
    assert is_conversational_question("I need help with everything") is False  # no opener


def test_conversational_question_size_caps():
    """Over-long or over-wordy messages must fall through."""
    assert is_conversational_question("What can you do for me today in terms of helping me with my daily tasks, my productivity, and my general workflow across many different kinds of things?") is False
    assert is_conversational_question("what who how why when where which can you could you do you does are you will you would you should you tell me explain describe define") is False


def test_conversational_question_blank():
    assert is_conversational_question("") is False
    assert is_conversational_question("   ") is False
    assert is_conversational_question(None) is False


def test_conversational_intent():
    assert conversational_intent("What can you do?") == "question"
    assert conversational_intent("what is the weather today?") == "chat"


# ── Conversational response helper ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_conversational_response_streams_direct_chat():
    """conversational_response streams the adapter's reply with one chat call."""

    async def mock_chat(messages, intent="chat", **kwargs):
        yield MagicMock(text="I can help with code, files, and more!", done=False)
        yield MagicMock(text="", done=True)

    mock_adapter = MagicMock()
    mock_adapter.chat = mock_chat

    chunks = [c async for c in conversational_response("What can you do?", mock_adapter)]
    assert len(chunks) >= 2
    assert chunks[-1].done is True
    text = "".join(c.text for c in chunks if getattr(c, "text", ""))
    assert "help" in text.lower()


@pytest.mark.asyncio
async def test_conversational_response_fallback_on_adapter_error():
    """Adapter failure yields a minimal fallback + done — no pipeline fall-through."""

    async def mock_chat(messages, intent="chat", **kwargs):
        raise RuntimeError("provider down")
        yield  # pragma: no cover

    mock_adapter = MagicMock()
    mock_adapter.chat = mock_chat

    chunks = [c async for c in conversational_response("Who are you?", mock_adapter)]
    assert any(getattr(c, "done", False) for c in chunks)


# ── Engine wiring (Session 68 / ADR-11) ────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_conversational_question_skips_dispatcher():
    """The engine must short-circuit a conversational question BEFORE the
    ThinkingDispatcher is invoked (single LLM call — the ADR-11 fix)."""
    from core.engine import Engine

    engine = Engine()

    async def mock_chat(messages, intent="chat", **kwargs):
        yield MagicMock(text="I can help you with code, files, and more!", done=False, error=None)
        yield MagicMock(text="", done=True, error=None)

    mock_adapter = MagicMock()
    mock_adapter.chat = mock_chat

    with patch("core.engine.get_adapter", return_value=mock_adapter), \
            patch("core.thinking_dispatcher.ThinkingDispatcher.dispatch") as mock_dispatch:
        chunks = [c async for c in engine.process("What can you do?", "sess-conv-fast")]

    # The dispatcher must NEVER run for a conversational question.
    mock_dispatch.assert_not_called()
    text = "".join(c.text for c in chunks if getattr(c, "text", ""))
    assert "help" in text.lower()
