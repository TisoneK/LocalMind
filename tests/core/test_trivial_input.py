"""
Tests for the trivial-input detector — the short-circuit that prevents
greetings/thanks/farewells from hitting the full ThinkingDispatcher.
"""

from __future__ import annotations

from core.trivial_input import is_trivial_input, trivial_intent

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
