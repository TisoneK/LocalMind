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
    trivial_response,
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


def test_greeting_addressed_to_localmind():
    """An addressed social greeting must stay on the zero-LLM path."""
    for message in ("Hey LM", "hi lm", "Hello LocalMind", "hey localmind!"):
        assert is_trivial_input(message) is True
        assert trivial_intent(message) == "greeting"


def test_greeting_good_morning():
    assert is_trivial_input("good morning") is True
    assert is_trivial_input("Good evening") is True
    assert is_trivial_input("good afternoon") is True


def test_greeting_whats_up():
    assert is_trivial_input("what's up") is True
    assert is_trivial_input("whats up") is True


def test_wellbeing_questions_not_trivial():
    """'How are you?' is a wellbeing question, not a greeting gesture.

    A canned "Hi! I'm LocalMind" answer to it is a WRONG reply, not a fast
    one — it must fall to the conversational path (a real model answer
    with conversation context). Same for 'how's it going'.
    """
    assert is_trivial_input("how are you") is False
    assert is_trivial_input("how are you?") is False
    assert is_trivial_input("how's it going") is False
    assert is_trivial_input("hows it going?") is False
    # They remain conversational questions (fast path WITH a model call).
    assert is_conversational_question("how are you") is True
    assert is_conversational_question("how's it going") is True


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
    """Over-long or over-wordy messages must fall through.

    Session 334: the word cap was bumped from 20 to 25 (to catch the
    branch-count logic question at 22 words). These fixtures stay above
    the new cap or fail the no-opener fast-path.
    """
    # 30 words — over the 25-word cap.
    assert is_conversational_question("What can you do for me today in terms of helping me with my daily tasks, my productivity, and my general workflow across many different kinds of things?") is False
    # 26 words, no "?" — over the 25-word cap. Falls through.
    assert is_conversational_question("what who how why when where which can you could you do you does are you will you would you should you tell me explain describe define clarify propose recommend") is False


def test_conversational_question_blank():
    assert is_conversational_question("") is False
    assert is_conversational_question("   ") is False
    assert is_conversational_question(None) is False


def test_conversational_intent():
    assert conversational_intent("What can you do?") == "question"
    assert conversational_intent("what is the weather today?") == "chat"


def test_conversational_followup_uses_prior_assistant_context():
    history = [
        {"role": "user", "content": "What can you do?"},
        {"role": "assistant", "content": "I can help with coding and research."},
    ]
    assert is_conversational_question("Like what?", history) is True
    assert is_conversational_question("Like what?") is False
    assert is_conversational_question("Run it", history) is False


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


@pytest.mark.asyncio
async def test_conversational_response_forwards_provider_usage():
    """Provider-reported usage flows through the fast path so the engine can
    emit real prompt/completion token counts (Session 111 — Context Tokens
    and the bottom-bar prompt count were stuck at 0 on fast-path turns)."""

    async def mock_chat(messages, intent="chat", **kwargs):
        yield MagicMock(
            text="I can help with code, files, and more!",
            done=False,
            usage={"prompt_tokens": 84, "completion_tokens": 12},
        )
        yield MagicMock(
            text="",
            done=True,
            usage={"prompt_tokens": 84, "completion_tokens": 12},
        )

    mock_adapter = MagicMock()
    mock_adapter.chat = mock_chat

    chunks = [c async for c in conversational_response("What can you do?", mock_adapter)]
    streamed_usage = [getattr(c, "usage", None) for c in chunks if getattr(c, "text", "")]
    assert streamed_usage, "streamed chunks must forward usage"
    assert streamed_usage[0].get("prompt_tokens") == 84
    assert streamed_usage[0].get("completion_tokens") == 12


@pytest.mark.asyncio
async def test_conversational_response_prompt_estimate_fallback():
    """When the provider omits usage metadata, the fast path still reports a
    nonzero prompt-token estimate (system prompt + user message), so Context
    Tokens is never a misleading 0 for a real generation."""

    async def mock_chat(messages, intent="chat", **kwargs):
        yield MagicMock(text="I can help with code, files, and more!", done=False)
        yield MagicMock(text="", done=True)

    mock_adapter = MagicMock()
    mock_adapter.chat = mock_chat

    chunks = [c async for c in conversational_response("What can you do?", mock_adapter)]
    done = next(c for c in chunks if getattr(c, "done", False))
    assert done.usage.get("prompt_tokens", 0) > 0
    assert done.usage.get("completion_tokens", 0) == 0  # no completion estimate


@pytest.mark.asyncio
async def test_conversational_response_does_not_override_provider_prompt_count():
    """The local estimate must never override a real provider prompt count."""

    async def mock_chat(messages, intent="chat", **kwargs):
        yield MagicMock(text="Hi there", done=False, usage={"prompt_tokens": 300, "completion_tokens": 5})
        yield MagicMock(text="", done=True, usage={"prompt_tokens": 300, "completion_tokens": 5})

    mock_adapter = MagicMock()
    mock_adapter.chat = mock_chat

    chunks = [c async for c in conversational_response("Hi", mock_adapter)]
    done = next(c for c in chunks if getattr(c, "done", False))
    streamed = [c for c in chunks if getattr(c, "text", "")]
    # Provider's 300 flows through both the streamed chunks AND the done
    # chunk (authoritative final usage); the local estimate must not leak in.
    assert streamed[0].usage.get("prompt_tokens") == 300
    assert done.usage.get("prompt_tokens") == 300
    assert done.usage.get("completion_tokens") == 5


# ── Empty-stream fallback (Session 153 / silent-failure contract) ───────────
# Free-tier models can return EMPTY or reasoning-only streams on the direct
# chat fast path — the provider reports usage but never emits content. Before
# this fix the UI showed a status update with an EMPTY bubble ("message not
# displaying"). The fallback guarantees visible text on every turn.


@pytest.mark.asyncio
async def test_conversational_response_empty_stream_falls_back():
    """A zero-text stream must still yield visible text — not an empty bubble."""

    async def mock_chat(messages, intent="chat", **kwargs):
        yield MagicMock(text="", done=False)  # empty/reasoning-only delta
        yield MagicMock(text="", done=True)   # usage-only terminal delta

    mock_adapter = MagicMock()
    mock_adapter.chat = mock_chat

    chunks = [c async for c in conversational_response("What can you do?", mock_adapter)]
    text = "".join(c.text for c in chunks if getattr(c, "text", ""))
    assert text, "empty stream must yield a fallback message"
    assert any(getattr(c, "done", False) for c in chunks)
    # The fallback must surface concrete next steps, not blame the phrasing.
    assert "try again" in text.lower() or "switch" in text.lower()


@pytest.mark.asyncio
async def test_trivial_response_empty_stream_falls_back():
    """The yes_no short-circuit gets the same empty-stream fallback.
    (Session 187: pure social intents no longer reach the LLM at all —
    "yes" is a yes_no intent that still streams through the adapter.)"""

    async def mock_chat(messages, intent="chat", **kwargs):
        yield MagicMock(text="", done=True)

    mock_adapter = MagicMock()
    mock_adapter.chat = mock_chat

    chunks = [c async for c in trivial_response("yes", mock_adapter)]
    text = "".join(c.text for c in chunks if getattr(c, "text", ""))
    assert text, "empty stream must yield a fallback message"
    assert any(getattr(c, "done", False) for c in chunks)


@pytest.mark.asyncio
async def test_conversational_response_streamed_error_chunk_is_normalized():
    """A streamed provider error (429/auth) must surface in the fallback —
    but as the canonical friendly message, never as the raw provider payload.
    The raw error is forwarded on chunk.error so the SSE boundary emits the
    error card (ADR-20/21)."""

    async def mock_chat(messages, intent="chat", **kwargs):
        yield MagicMock(text="", done=True, error="zen returned 429: rate limit")

    mock_adapter = MagicMock()
    mock_adapter.chat = mock_chat

    chunks = [c async for c in conversational_response("What can you do?", mock_adapter)]
    text = "".join(c.text for c in chunks if getattr(c, "text", ""))
    # Raw provider payload must never reach the message text.
    assert "429" not in text
    assert "zen returned" not in text
    # The canonical friendly message is embedded instead.
    assert "usage limit" in text.lower()
    # The raw error is forwarded so the SSE boundary emits the error card.
    err_chunks = [c for c in chunks if getattr(c, "error", None)]
    assert err_chunks and err_chunks[0].error == "zen returned 429: rate limit"
    assert any(getattr(c, "done", False) for c in chunks)


@pytest.mark.asyncio
async def test_trivial_response_zen_payload_never_leaks_raw_json():
    """The exact user-reported case: the full Zen 429 JSON payload must not
    appear in the fallback text — only the friendly message (Session 171).
    (Session 187: uses "yes" — a yes_no intent that still streams through
    the adapter — since pure social intents no longer call the LLM.)"""

    async def mock_chat(messages, intent="chat", **kwargs):
        yield MagicMock(
            text="",
            done=True,
            error=(
                'zen returned 429: {"type":"error","error":{"type":'
                '"FreeUsageLimitError","message":"Error from provider '
                '(Console): Rate limit exceeded. Please try again later."}}'
            ),
        )

    mock_adapter = MagicMock()
    mock_adapter.chat = mock_chat

    chunks = [c async for c in trivial_response("yes", mock_adapter)]
    text = "".join(c.text for c in chunks if getattr(c, "text", ""))
    assert "{" not in text
    assert "FreeUsageLimitError" not in text
    assert "zen" not in text.lower()
    assert "usage limit" in text.lower()
    err_chunks = [c for c in chunks if getattr(c, "error", None)]
    assert err_chunks, "raw error must be forwarded for the canonical card"
    assert any(getattr(c, "done", False) for c in chunks)


@pytest.mark.asyncio
async def test_conversational_response_normal_stream_not_polluted():
    """The fallback must NOT fire when the model actually streamed text."""

    async def mock_chat(messages, intent="chat", **kwargs):
        yield MagicMock(text="I can help with code, files, and more!", done=False)
        yield MagicMock(text="", done=True)

    mock_adapter = MagicMock()
    mock_adapter.chat = mock_chat

    chunks = [c async for c in conversational_response("What can you do?", mock_adapter)]
    text = "".join(c.text for c in chunks if getattr(c, "text", ""))
    assert "help" in text.lower()
    assert "try again" not in text.lower()


# ── Deterministic social replies (Session 187) ─────────────────────────────
# Pure social intents (greeting/farewell/thanks/acknowledgment) are answered
# with canned text and ZERO LLM calls — the provider being down/rate-limited
# must never turn "hi" into an error card.


@pytest.mark.asyncio
async def test_greeting_is_deterministic_no_llm_call():
    """"hi" must be answered instantly with a canned greeting — the adapter
    (and therefore the rate-limited provider) is never touched."""

    async def exploding_chat(messages, intent="chat", **kwargs):
        raise AssertionError("adapter.chat must NOT be called for a greeting")
        yield  # pragma: no cover

    mock_adapter = MagicMock()
    mock_adapter.chat = MagicMock(side_effect=exploding_chat)

    chunks = [c async for c in trivial_response("hi", mock_adapter)]
    text = "".join(c.text for c in chunks if getattr(c, "text", ""))
    assert text, "canned greeting must be yielded"
    assert "help" in text.lower()
    assert any(getattr(c, "done", False) for c in chunks)
    mock_adapter.chat.assert_not_called()
    # The zero-LLM turn must NOT dress estimates up as provider usage — the
    # chunks carry the synthetic flag instead of token numbers. The Session
    # 111 display contract (nonzero prompt estimate on the Observe panel) is
    # served by the runtime epilog's labeled tokens_approx fields, not here.
    done = next(c for c in chunks if getattr(c, "done", False))
    assert done.usage == {"synthetic": True}


@pytest.mark.asyncio
async def test_all_social_intents_are_deterministic():
    """Every pure-social intent gets a canned reply without an LLM call."""

    async def exploding_chat(messages, intent="chat", **kwargs):
        raise AssertionError("adapter.chat must NOT be called for social intents")
        yield  # pragma: no cover

    mock_adapter = MagicMock()
    mock_adapter.chat = MagicMock(side_effect=exploding_chat)

    for msg, kind in [
        ("hello", "greeting"),
        ("bye", "farewell"),
        ("thanks", "thanks"),
        ("ok", "acknowledgment"),
        ("got it", "acknowledgment"),
    ]:
        chunks = [c async for c in trivial_response(msg, mock_adapter)]
        text = "".join(c.text for c in chunks if getattr(c, "text", ""))
        assert text, f"{msg!r} ({kind}) must yield a canned reply"
        assert any(getattr(c, "done", False) for c in chunks)
    mock_adapter.chat.assert_not_called()


@pytest.mark.asyncio
async def test_yes_no_still_streams_from_adapter():
    """yes_no is context-dependent — it must still go through the LLM path."""

    async def mock_chat(messages, intent="chat", **kwargs):
        yield MagicMock(text="Sure, go ahead!", done=False)
        yield MagicMock(text="", done=True)

    mock_adapter = MagicMock()
    mock_adapter.chat = MagicMock(side_effect=mock_chat)

    chunks = [c async for c in trivial_response("yes", mock_adapter)]
    text = "".join(c.text for c in chunks if getattr(c, "text", ""))
    assert "go ahead" in text
    mock_adapter.chat.assert_called_once()


# ── Engine wiring (Session 68 / ADR-11) ────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_conversational_question_skips_dispatcher():
    """The engine must short-circuit a conversational question BEFORE the
    parent agent loop (single LLM call — the ADR-11 fix)."""
    from core.engine import Engine

    engine = Engine()

    async def mock_chat(messages, intent="chat", **kwargs):
        yield MagicMock(text="I can help you with code, files, and more!", done=False, error=None)
        yield MagicMock(text="", done=True, error=None)

    mock_adapter = MagicMock()
    mock_adapter.chat = mock_chat

    with patch("core.engine.get_adapter", return_value=mock_adapter):
        chunks = [c async for c in engine.process("Why is Python popular?", "sess-conv-fast")]

    text = "".join(c.text for c in chunks if getattr(c, "text", ""))
    assert "help" in text.lower()


@pytest.mark.asyncio
async def test_engine_conversational_question_emits_prompt_tokens():
    """End-to-end: the conversational fast-path turn_complete must carry
    prompt_tokens_approx (provider-reported, not 0) so the Observe panel
    Context Tokens and the bottom-bar prompt count populate (Session 111 —
    both were stuck at 0 / "—" on fast-path turns)."""
    from core.engine import Engine
    from core.obs import ObsCollector

    engine = Engine()

    async def mock_chat(messages, intent="chat", **kwargs):
        yield MagicMock(
            text="I can help you with code, files, and more!",
            done=False,
            error=None,
            usage={"prompt_tokens": 84, "completion_tokens": 12},
        )
        yield MagicMock(
            text="",
            done=True,
            error=None,
            usage={"prompt_tokens": 84, "completion_tokens": 12},
        )

    mock_adapter = MagicMock()
    mock_adapter.chat = mock_chat

    obs = ObsCollector()
    with patch("core.engine.get_adapter", return_value=mock_adapter):
        chunks = [c async for c in engine.process("Why is Python popular?", "sess-conv-usage", obs=obs)]

    assert any(getattr(c, "text", "") for c in chunks), "expected a streamed reply"
    turn_completes = [e for e in obs.history() if e.type == "turn_complete"]
    assert turn_completes, "conversational fast path must emit turn_complete"
    data = turn_completes[0].data
    assert data.get("prompt_tokens_approx") == 84
    assert data.get("tokens_approx") == 12
    # The stored per-session observation carries the same prompt count.
    stored = engine._last_observation.get("sess-conv-usage")
    assert stored and stored.get("context_tokens") == 84


@pytest.mark.parametrize("message", ["Hi", "Hey LM", "Hello LocalMind"])
@pytest.mark.asyncio
async def test_engine_greeting_uses_the_warm_parent_boundary(message):
    """Session 332-C: greetings use the trivial fast-path — canned reply,
    zero LLM calls (immune to provider rate-limits). Previously the parent
    agent handled greetings via a native call (1 LLM call); the user's
    review flagged this as overkill for trivial inputs.
    """
    from core.engine import Engine
    from core.obs import ObsCollector

    engine = Engine()
    obs = ObsCollector()
    calls = 0

    async def mock_chat(messages, intent="chat", **kwargs):
        nonlocal calls
        calls += 1
        yield MagicMock(
            text="Hi! I am LocalMind. How can I help?",
            done=False,
            error=None,
            usage={"prompt_tokens": 20, "completion_tokens": 12},
        )
        yield MagicMock(text="", done=True, error=None, usage={})

    mock_adapter = MagicMock()
    mock_adapter.chat = mock_chat

    with patch("core.agent_runtime.get_adapter", return_value=mock_adapter):
        chunks = [c async for c in engine.process(message, f"sess-greeting-direct-{message}", obs=obs)]

    text = "".join(c.text for c in chunks if getattr(c, "text", ""))
    assert "localmind" in text.lower()
    assert any(getattr(c, "done", False) for c in chunks)
    # Session 332-C: trivial greetings get a canned reply — zero LLM calls.
    assert calls == 0
    assert not any(event.type == "agent_initialization_done" for event in obs.history())
    assert not any(event.type == "tool_call" for event in obs.history())


@pytest.mark.asyncio
async def test_engine_conversational_followup_uses_direct_chat_context():
    """Direct follow-ups use one generic chat boundary, not a phrase shortcut."""
    from core.engine import Engine
    from core.obs import ObsCollector

    engine = Engine()
    obs = ObsCollector()
    calls: list[list[dict]] = []

    async def mock_chat(messages, intent="chat", **kwargs):
        calls.append(messages)
        # Session 354: the Thinker now runs on the conversational fast-path,
        # so the first call is the Thinker consult, the second is the actual
        # response. Adjust the call-counting accordingly.
        answer = (
            "I can help with coding, files, and research."
            if len(calls) == 2
            else "For example, I can create a script or find a document."
        )
        yield MagicMock(text=answer, done=False, error=None, usage={"prompt_tokens": 30})
        yield MagicMock(text="", done=True, error=None, usage={"prompt_tokens": 30, "completion_tokens": 12})

    mock_adapter = MagicMock()
    mock_adapter.chat = mock_chat
    with patch("core.agent_runtime.get_adapter", return_value=mock_adapter):
        first = [c async for c in engine.process("What can you do?", "sess-conversation-fast", obs=obs)]
        second = [c async for c in engine.process("Like what?", "sess-conversation-fast", obs=obs)]

    first_text = "".join(c.text for c in first if getattr(c, "text", ""))
    second_text = "".join(c.text for c in second if getattr(c, "text", ""))
    assert "coding" in first_text.lower()
    assert "script" in second_text.lower()
    # Session 354: the Thinker now runs on the conversational fast-path,
    # adding 1 extra LLM call per conversational turn. 2 turns × (Thinker + response) = 4 calls.
    assert len(calls) == 4
    # Turn 1 = Thinker consult, turn 2 = the response call. The response
    # request must carry THIS run's user message — not residue from prior
    # runs leaked through a shared data home (the old assertion matched the
    # assistant reply inside calls[1], which only passed when history from
    # earlier contaminated runs was present).
    assert any(
        message.get("role") == "user" and message.get("content") == "What can you do?"
        for message in calls[1]
    )
    # The follow-up call must carry the prior exchange from this same run
    # as conversation context.
    assert any(
        message.get("role") == "assistant" and message.get("content") == "I can help with coding, files, and research."
        for message in calls[3]
    )
    assert all(event.data.get("fast_path") for event in obs.history() if event.type == "agent_initialization_done")


# ── Session 332-D — message_implies_tool_action helper ─────────────────────


def test_message_implies_tool_action_positive():
    """Messages with tool/file/code keywords must return True (need tools)."""
    from core.trivial_input import message_implies_tool_action

    assert message_implies_tool_action("find files in /tmp") is True
    assert message_implies_tool_action("run pytest in the backend") is True
    assert message_implies_tool_action("create hello.py") is True
    assert message_implies_tool_action("what's the weather today") is True
    assert message_implies_tool_action("search the web for news") is True
    assert message_implies_tool_action("open the file at /etc/hosts") is True
    assert message_implies_tool_action("https://example.com") is True
    assert message_implies_tool_action("how much RAM do I have") is True


def test_message_implies_tool_action_negative():
    """Purely conversational messages must return False (don't need tools)."""
    from core.trivial_input import message_implies_tool_action

    assert message_implies_tool_action("Give me three ideas for a cyber café") is False
    assert message_implies_tool_action("What can you do?") is False
    assert message_implies_tool_action("Recommend a good book on business") is False
    assert message_implies_tool_action("Suggest a name for my project") is False
    assert message_implies_tool_action("Brainstorm marketing strategies") is False
    assert message_implies_tool_action("Propose three solutions") is False
    assert message_implies_tool_action("What do you think about remote work") is False
    assert message_implies_tool_action("") is False


# ── Session 334 — fast-path for complete thoughts ending in "?" ────────────


def test_conversational_question_complete_thought_ending_in_question_mark():
    """A short complete thought ending in "?" with no blocked keywords must
    fast-path — even without an interrogative opener. Session 334: this is
    the cyber-café-style logic question that previously fell through to the
    parent-agent pipeline (which polluted the prompt with git workspace
    context, causing the model to waste tokens wondering if "branches"
    meant git branches)."""
    # The branch-count prompt from the user's report:
    assert is_conversational_question(
        "We have three branches. Actually, one branch closed last month. We opened two new branches. How many branches do we currently have?"
    ) is True
    # Similar shape:
    assert is_conversational_question(
        "I have 10 apples. I gave 3 to my friend. How many do I have left?"
    ) is True
    assert is_conversational_question(
        "The recipe calls for 2 cups of flour and 1 cup of sugar. What's the ratio?"
    ) is True


def test_conversational_question_short_fragment_without_history_falls_through():
    """Short fragments like 'Like what?' need history to qualify — without
    prior assistant context they fall through. Session 334: the
    _CONVERSATIONAL_NO_OPENER_MIN_WORDS=5 guard prevents fragments from
    being mis-classified as complete thoughts."""
    # 2 words, ends with "?", no opener — under the 5-word minimum.
    assert is_conversational_question("Like what?") is False
    assert is_conversational_question("And why?") is False
    assert is_conversational_question("So what?") is False


def test_conversational_question_blocked_keywords_override_question_mark():
    """A complete thought ending in "?" with a blocked keyword must fall
    through to the parent agent. The blocked-keyword guard catches
    routing-sensitive queries even when the '?' fast-path would otherwise
    fire."""
    # "weather" is blocked — must fall through.
    assert is_conversational_question(
        "We had storms yesterday and today looks calm. What is the weather going to be like tomorrow?"
    ) is False
    # "file" is blocked — must fall through.
    assert is_conversational_question(
        "I created three notes and deleted one. How many files do I have now?"
    ) is False


def test_message_implies_tool_action_branch_count_is_false():
    """The branch-count prompt must NOT imply a tool action — so the
    parent-agent loop's workspace_state injection (Branch: main, dirty
    tree) is skipped. Session 334: this is the system-prompt pollution
    fix."""
    from core.trivial_input import message_implies_tool_action

    assert message_implies_tool_action(
        "We have three branches. Actually, one branch closed last month. We opened two new branches. How many branches do we currently have?"
    ) is False


def test_message_implies_tool_action_git_branch_is_true():
    """A message that actually references git must still imply a tool
    action — so the workspace_state injection fires."""
    from core.trivial_input import message_implies_tool_action

    assert message_implies_tool_action("What is the current git branch?") is True
    assert message_implies_tool_action("Show me the diff on this branch") is True


# ── Session 335 — knowledge-imperative openers (RAM-vs-storage bug) ───────


def test_conversational_question_knowledge_imperative_openers():
    """Knowledge-imperative openers (summarize, compare, explain, describe,
    etc.) fast-path even when the message contains a blocked keyword like
    'RAM' — the imperative makes the intent unambiguous (exposition, not
    sysinfo). Session 335: this is the RAM-vs-storage system-prompt
    pollution fix.
    """
    # The user's actual report:
    assert is_conversational_question(
        "Summarize the difference between RAM and storage."
    ) is True
    # Similar shapes:
    assert is_conversational_question("Compare TCP and UDP.") is True
    assert is_conversational_question("Contrast TCP vs UDP.") is True
    assert is_conversational_question("Explain how gravity works.") is True
    assert is_conversational_question("Describe photosynthesis.") is True
    assert is_conversational_question("Outline the steps for brewing coffee.") is True
    assert is_conversational_question("Name three planets in our solar system.") is True


def test_knowledge_imperative_bypasses_blocked_keywords():
    """Knowledge imperatives skip the blocked-keyword guard. 'RAM' and
    'disk' are sysinfo keywords, but 'Summarize the difference between
    RAM and storage' is exposition, not a request for the user's RAM."""
    # Without the bypass, these would all be False (blocked by RAM/disk/etc.)
    assert is_conversational_question("Summarize the difference between RAM and storage.") is True
    assert is_conversational_question("Explain how CPU caches work.") is True
    assert is_conversational_question("Compare SSD vs HDD storage types.") is True
    assert is_conversational_question("Describe how a GPU renders a frame.") is True


def test_knowledge_imperative_does_not_bypass_file_or_url_patterns():
    """File-extension and URL patterns are still checked even under
    knowledge imperatives — those are structural tool signals regardless
    of intent."""
    assert is_conversational_question("Summarize the contents of app.py.") is False
    assert is_conversational_question("Compare the script.py and module.py files.") is False
    assert is_conversational_question("Explain what's at https://example.com.") is False


def test_knowledge_imperative_does_not_bypass_debugging_keywords():
    """Debugging-context keywords (error, bug, exception, crash) remain
    hard-blocked even under knowledge imperatives. 'Explain this error
    message' is a debugging request — the user has a real error and needs
    tool evidence, not exposition about errors."""
    assert is_conversational_question("Explain this error message") is False
    assert is_conversational_question("Describe the bug in my code.") is False
    assert is_conversational_question("Summarize the traceback I just saw.") is False
    assert is_conversational_question("Explain why this exception is thrown.") is False
    assert is_conversational_question("Describe how to fix this crash.") is False


def test_message_implies_tool_action_knowledge_imperative_is_false():
    """The RAM-vs-storage prompt must NOT imply a tool action — so the
    parent-agent loop's workspace_state injection is skipped. Session 335:
    this prevents the model from seeing 'Branch: main' / 'dirty working
    tree' on knowledge questions."""
    from core.trivial_input import message_implies_tool_action

    assert message_implies_tool_action(
        "Summarize the difference between RAM and storage."
    ) is False
    assert message_implies_tool_action("Compare TCP and UDP.") is False
    assert message_implies_tool_action("Explain how gravity works.") is False


def test_message_implies_tool_action_real_sysinfo_still_true():
    """Real sysinfo queries must still imply a tool action — so
    workspace_state injection fires (the user actually wants their RAM
    specs)."""
    from core.trivial_input import message_implies_tool_action

    assert message_implies_tool_action("How much RAM do I have?") is True
    assert message_implies_tool_action("What's my disk space?") is True
    assert message_implies_tool_action("Check my CPU specs") is True


def test_message_implies_tool_action_knowledge_with_file_pattern():
    """Knowledge imperatives with file/URL patterns still imply a tool
    action — the file/URL is a structural signal that tools are needed."""
    from core.trivial_input import message_implies_tool_action

    assert message_implies_tool_action("Summarize the contents of app.py.") is True
    assert message_implies_tool_action("Explain what's at https://example.com") is True
