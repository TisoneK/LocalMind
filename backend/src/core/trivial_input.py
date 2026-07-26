"""
Trivial-input detector — short-circuits greetings/simple chat before
the full intent-classification pipeline runs.

Problem (Session 21): A one-word greeting like "Hi" was burning 11.5s
and ~4.8k tokens because it hit the full ThinkingDispatcher (JSON-schema
capability inference LLM call) before being classified as CHAT. That's
massive overkill for inputs that are obviously conversational.

Fix: detect trivial inputs (greetings, thanks, farewells, yes/no, simple
acknowledgments) and short-circuit them to a direct chat response — no
dispatcher call, no JSON-schema planning, no agent loop. The model just
streams a direct reply.

This is deterministic and free (no LLM call for classification). The
detector is conservative — it only short-circuits when the input is
truly trivial. Anything ambiguous falls through to the normal pipeline.

Usage (in engine._pipeline.process()):
    from core.trivial_input import is_trivial_input, trivial_response

    if is_trivial_input(message, history):
        async for chunk in trivial_response(message, adapter, history):
            yield chunk
        return
"""

from __future__ import annotations

import re
from typing import AsyncIterator, Optional

from core.models import StreamChunk

# ── Trivial input patterns ───────────────────────────────────────────────────
# Each pattern is a regex that matches the ENTIRE message (anchored ^...$).
# Conservative: only matches inputs that are obviously conversational.
# Anything ambiguous falls through to the normal pipeline.

# Greetings — "hi", "hello", "hey", "good morning", etc.
_GREETINGS = [
    r"hi+",
    r"hello+",
    r"hey+",
    r"heya+",
    r"howdy",
    r"sup\b",
    r"yo\b",
    r"good\s*(morning|afternoon|evening|day)",
    r"greetings",
    r"nice to (meet you|see you)",
    r"what'?s up",
    r"how'?s it going",
    r"how are you",
]

# Farewells — "bye", "goodbye", "see you", etc.
_FAREWELLS = [
    r"bye+",
    r"goodbye+",
    r"see\s+you(\s+(later|soon|tomorrow))?",
    r"later+",
    r"cya\b",
    r"good\s+night",
    r"have a (good|great|nice) (day|night|weekend)",
    r"farewell",
    r"take care",
]

# Thanks — "thanks", "thank you", "appreciate it", etc.
_THANKS = [
    r"thanks+",
    r"thank\s+you+",
    r"thx+",
    r"ty\b",
    r"appreciate\s+it",
    r"much\s+obliged",
    r"grateful",
    r"cheers",
]

# Simple acknowledgments — "ok", "okay", "got it", "sure", etc.
_ACKNOWLEDGMENTS = [
    r"ok+",
    r"okay+",
    r"k\b",
    r"got\s+it",
    r"understood",
    r"sure",
    r"will\s+do",
    r"roger",
    r"acknowledged",
    r"makes\s+sense",
    r"gotcha",
    r"i see",
]

# Yes/No — single-word answers
_YES_NO = [
    r"yes+",
    r"no+",
    r"yep+",
    r"nope+",
    r"yeah+",
    r"nah+",
    r"yup+",
    r"sure",
]

# Compile all patterns into a single regex with alternation.
# Case-insensitive, anchored to match the ENTIRE message (after stripping
# whitespace and trailing punctuation).
_ALL_PATTERNS = _GREETINGS + _FAREWELLS + _THANKS + _ACKNOWLEDGMENTS + _YES_NO
_TRIVIAL_RE = re.compile(
    r"^(?:" + "|".join(_ALL_PATTERNS) + r")$",
    re.IGNORECASE,
)

# Punctuation that's commonly appended to trivial inputs (e.g., "Hi!" or "ok.")
# We strip these before matching so "Hi!" matches the "hi" pattern.
_TRIVIAL_PUNCT = "!.?.,;:"


def is_trivial_input(message: str, history: Optional[list[dict]] = None) -> bool:
    """
    Detect whether a message is trivial (greeting/thanks/farewell/etc.).

    Conservative: only returns True for inputs that are OBVIOUSLY
    conversational. Anything ambiguous falls through to the normal
    pipeline.

    Args:
        message: the user's message text.
        history: optional chat history. If the conversation already has
            substantial turns, we're less likely to short-circuit (the
            user might be saying "ok" in the middle of a complex task).
            For now, history isn't used — the patterns are conservative
            enough. Reserved for future tuning.

    Returns:
        True if the input is trivial and should short-circuit to a
        direct chat response. False to run the normal pipeline.
    """
    if not message or not message.strip():
        return False

    # Strip whitespace and trailing punctuation
    cleaned = message.strip().rstrip(_TRIVIAL_PUNCT).strip()

    # Trivial inputs are short — if it's more than ~40 chars, it's not trivial
    if len(cleaned) > 40:
        return False

    # Must be 1-5 words (split on whitespace)
    words = cleaned.split()
    if len(words) > 5:
        return False

    # Check against the trivial patterns
    return bool(_TRIVIAL_RE.match(cleaned))


def trivial_intent(message: str) -> str:
    """
    Return the conversation intent for a trivial input, for logging/obs.

    Returns one of: "greeting", "farewell", "thanks", "acknowledgment",
    "yes_no", or "trivial" (fallback).
    """
    cleaned = message.strip().rstrip(_TRIVIAL_PUNCT).strip().lower()
    for pattern, label in [
        (_GREETINGS, "greeting"),
        (_FAREWELLS, "farewell"),
        (_THANKS, "thanks"),
        (_ACKNOWLEDGMENTS, "acknowledgment"),
        (_YES_NO, "yes_no"),
    ]:
        for p in pattern:
            if re.match(f"^(?:{p})$", cleaned, re.IGNORECASE):
                return label
    return "trivial"


async def trivial_response(
    message: str,
    adapter,
    history: Optional[list[dict]] = None,
) -> AsyncIterator[StreamChunk]:
    """
    Stream a direct chat response for a trivial input.

    This bypasses the ThinkingDispatcher entirely — no JSON-schema
    planning, no capability inference, no agent loop. The model just
    streams a direct reply.

    The prompt is minimal: "You are LocalMind. The user said: '<message>'.
    Respond naturally and briefly." This keeps the token cost low for
    trivial inputs (target: <500 tokens, <2s).

    Args:
        message: the user's trivial message.
        adapter: the model adapter (already configured with the right model).
        history: optional chat history for context.

    Yields:
        StreamChunk — the model's direct response, streamed token by token.
    """
    # Build a minimal prompt — no system prompt machinery, no tool defs,
    # no JSON schema. Just a direct instruction.
    messages = []
    if history:
        # Include the last few turns for context (greetings in context
        # might get a different response than out-of-context)
        messages.extend(history[-4:])

    messages.append(
        {
            "role": "user",
            "content": message,
        }
    )

    # Stream the response directly from the adapter — no agent loop,
    # no tool calls, no planning. Just chat.
    try:
        async for chunk in adapter.chat(messages=messages, stream=True):
            if hasattr(chunk, "text") and chunk.text:
                yield StreamChunk(text=chunk.text, done=False)
            elif hasattr(chunk, "delta") and chunk.delta:
                yield StreamChunk(text=chunk.delta, done=False)
        yield StreamChunk(text="", done=True)
    except Exception:
        # If the direct chat fails, yield a minimal fallback and done.
        # Do NOT fall through to the full pipeline — that would defeat
        # the purpose of the short-circuit.
        yield StreamChunk(
            text="Hi! I'm LocalMind. How can I help you?",
            done=False,
        )
        yield StreamChunk(text="", done=True)
