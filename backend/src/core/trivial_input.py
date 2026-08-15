"""
Legacy conversational classifiers and direct-response helpers.

The live request runtime no longer invokes these functions for routing. Every
turn enters the parent agent, whose model-owned initialization decision chooses
between a direct response, clarification, and tool execution. These helpers
remain available for isolated utilities and compatibility tests only.

Problem (Session 21): A one-word greeting like "Hi" was burning 11.5s
and ~4.8k tokens because it entered capability inference before being
classified as CHAT. That's massive overkill for inputs that are obviously
conversational.

Fix: detect trivial inputs (greetings, thanks, farewells, yes/no, simple
acknowledgments) and short-circuit them to a direct chat response — no
capability inference, tool planning, or tool loop. The model just streams a
direct reply.

Session 68 / ADR-11 (B-2026-08-09-1): also short-circuit obviously
conversational QUESTIONS ("What can you do?", "Who are you?", "Tell me
about yourself"). Before this, such a question paid TWO sequential LLM
calls (dispatcher capability-inference + chat generation) — verified as
the root cause of ~40s latency on "What can you do?". The new detector
is deliberately conservative: any tool/realtime/system keyword (weather,
time, ram, search, file, code, ...) falls through to the parent runtime
so capability handling still works ("what is today's EPL games?" still
reaches web search; "what time is it" still reaches system info).

This is deterministic and free (no LLM call for classification). The
detector
is conservative — it only short-circuits when the input is truly
conversational. Anything ambiguous falls through to normal request handling.

Compatibility usage (not used by the live parent runtime):
    from core.trivial_input import is_trivial_input, trivial_response
    from core.trivial_input import is_conversational_question, conversational_response

    if is_trivial_input(message, history):
        async for chunk in trivial_response(message, adapter, history):
            yield chunk
        return

    if is_conversational_question(message):
        async for chunk in conversational_response(message, adapter, history):
            yield chunk
        return
"""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator, Optional

from core.engine._helpers import _approx_tokens
from core.error_normalizer import normalize_error
from core.models import StreamChunk

logger = logging.getLogger(__name__)

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
    # Addressed greetings are still social turns: "Hey LM" and
    # "Hello LocalMind" must not enter the parent/tool loop.
    r"(?:hi+|hello+|hey+|heya+)\s+(?:lm|localmind)",
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

# Session 187: deterministic replies for PURE SOCIAL intents (greeting /
# farewell / thanks / acknowledgment). These carry no information request —
# the user said "hi" and expects a greeting, NOT a rate-limit error card when
# the free-tier provider is throttled. Yielding a canned reply here means the
# short-circuit NEVER touches the LLM for these inputs: instant, offline-safe,
# and immune to 429s. "yes_no" and conversational questions stay on the LLM
# path (they can be context-dependent).
_SOCIAL_REPLIES: dict[str, str] = {
    "greeting": "Hi! I'm LocalMind, your local AI assistant. How can I help you today?",
    "farewell": "Goodbye! Feel free to come back anytime.",
    "thanks": "You're welcome! Happy to help.",
    "acknowledgment": "Got it! What would you like to do next?",
}


# ── Conversational-question patterns (Session 68 / ADR-11) ───────────────────
# Unlike the trivial patterns above, these do NOT match the whole message.
# A conversational question must:
#   1. START with an interrogative opener ("what", "who", "can you", "tell me", ...)
#   2. NOT contain any tool/realtime/system keyword (weather, time, ram,
#      search, file, code, ...) — those must still reach the dispatcher
#      so they route to WEB_SEARCH / SYSINFO / SHELL / FILE_TASK correctly.
#   3. Be reasonably short (<= 140 chars, <= 20 words).

# Start-anchored openers. "show me ..." and "open ..." are deliberately NOT
# included — they usually imply filesystem/screen actions ("show me projects
# in Documents" must route to SHELL, not chat — see worklog-2025-01).
_CONVERSATIONAL_OPENERS = [
    r"what'?s",
    r"whats",
    r"what",
    r"who'?s",
    r"whos",
    r"who",
    r"how'?s",
    r"hows",
    r"how",
    r"why'?s",
    r"whys",
    r"why",
    r"when",
    r"where'?s",
    r"wheres",
    r"where",
    r"which",
    r"can you",
    r"can i",
    r"could you",
    r"could i",
    r"do you",
    r"does",
    r"are you",
    r"am i",
    r"is it",
    r"is there",
    r"will you",
    r"would you",
    r"should i",
    r"should we",
    r"tell me",
    r"explain",
    r"describe",
    r"define",
    r"help me understand",
    r"help me with",
    r"what can you",
    r"what do you",
    r"how do you",
]
_CONVERSATIONAL_OPENER_RE = re.compile(
    r"^(?:" + "|".join(_CONVERSATIONAL_OPENERS) + r")\b",
    re.IGNORECASE,
)

# Keywords that force a message through normal parent-agent handling. Word-boundary
# matched, case-insensitive. Organized by why they must NOT be fast-pathed:
#  - realtime/data → dispatcher adds WEB_SEARCH + realtime_sensitive
#  - time/date → dispatcher SYSINFO signal
#  - system info → dispatcher SYSINFO
#  - tool/file/action → dispatcher routes to SHELL/FILE_TASK/CODE_EXEC/etc.
_CONVERSATIONAL_BLOCKED_KEYWORDS = (
    # realtime / live data
    r"weather",
    r"forecast",
    r"temperature",
    r"today",
    r"tomorrow",
    r"tonight",
    r"latest",
    r"current",
    r"news",
    r"score",
    r"scores",
    r"match",
    r"matches",
    r"game",
    r"games",
    r"price",
    r"prices",
    r"cost",
    r"exchange",
    r"stock",
    r"shares",
    r"election",
    # time / date (SYSINFO)
    r"time",
    r"date",
    r"what day",
    r"day of the week",
    # system info (SYSINFO)
    r"ram",
    r"cpu",
    r"memory",
    r"disk",
    r"storage",
    r"specs",
    r"hardware",
    r"installed",
    r"processor",
    r"gpu",
    # tool / file / code / execution
    r"search",
    r"fetch",
    r"web",
    r"browse",
    r"url",
    r"http",
    r"download",
    r"open",
    r"read",
    r"write",
    r"create",
    r"edit",
    r"delete",
    r"save",
    r"file",
    r"files",
    r"folder",
    r"directory",
    r"code",
    r"script",
    r"program",
    r"function",
    r"bug",
    r"error",
    r"exception",
    r"crash",
    r"run",
    r"execute",
    r"install",
    r"command",
    r"terminal",
    r"shell",
    r"python",
    r"node",
    r"git",
    r"pdf",
    r"doc",
    r"docx",
    r"xlsx",
    r"csv",
    r"json",
    r"database",
    r"api",
    r"test",
    r"tests",
    r"show",
    r"list",
    r"find",
    r"fix",
    r"debug",
    r"log",
    r"logs",
)
_CONVERSATIONAL_BLOCKED_RE = re.compile(
    r"\b(?:" + "|".join(_CONVERSATIONAL_BLOCKED_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# File-extension / URL signals that must always route to tools.
_CONVERSATIONAL_FILE_EXT_RE = re.compile(
    r"\b\w+\.(?:py|js|ts|tsx|jsx|md|json|txt|pdf|docx?|xlsx?|csv|html?|css|sh|sql)\b",
    re.IGNORECASE,
)
_CONVERSATIONAL_URL_RE = re.compile(r"https?://", re.IGNORECASE)

# Size caps for the conversational fast-path.
_CONVERSATIONAL_MAX_CHARS = 140
_CONVERSATIONAL_MAX_WORDS = 20


def is_conversational_question(message: str) -> bool:
    """
    Detect whether a message is an OBVIOUSLY-conversational question that
    can be answered with a single direct chat call — no tools.

    Conservative by design: the message must start with an interrogative
    opener AND contain none of the tool/realtime/system keywords, so
    routing-sensitive queries ("what is today's EPL games?", "what time is
    it", "how much RAM do I have", "who wrote app.py") always fall through
    to the parent agent loop. Anything ambiguous → False (full pipeline).

    Args:
        message: the user's message text.

    Returns:
        True if the input is a conversational question that should
        short-circuit to a direct chat response. False to run the normal
        pipeline.
    """
    if not message or not message.strip():
        return False

    cleaned = message.strip().rstrip(_TRIVIAL_PUNCT).strip()

    # Size caps — conversational questions are short by definition.
    if len(cleaned) > _CONVERSATIONAL_MAX_CHARS:
        return False
    words = cleaned.split()
    if len(words) > _CONVERSATIONAL_MAX_WORDS:
        return False

    # Must open like a question about the assistant/itself/ideas.
    if not _CONVERSATIONAL_OPENER_RE.match(cleaned):
        return False

    # Must not reference anything that needs tools, live data, or system
    # info — those must reach the dispatcher for correct routing.
    if _CONVERSATIONAL_BLOCKED_RE.search(cleaned):
        return False
    if _CONVERSATIONAL_FILE_EXT_RE.search(cleaned):
        return False
    if _CONVERSATIONAL_URL_RE.search(cleaned):
        return False

    return True


def conversational_intent(message: str) -> str:
    """
    Return the conversation intent for a conversational-question input,
    for logging/obs.

    Returns "question" when the message qualifies as a conversational
    question, otherwise "chat" (fallback).
    """
    if is_conversational_question(message):
        return "question"
    return "chat"


# ── Direct chat response helper ──────────────────────────────────────────────


async def _direct_chat_response(
    message: str,
    adapter,
    history: Optional[list[dict]],
    system_prompt: str,
) -> AsyncIterator[StreamChunk]:
    """Stream a single direct chat call with a minimal system prompt."""
    messages = [
        {"role": "system", "content": system_prompt},
    ]
    if history:
        # Include the last few turns for context.
        messages.extend(history[-4:])

    messages.append({"role": "user", "content": message})

    # Local prompt-token estimate for the exact prompt we send, used as a
    # fallback when the provider omits usage metadata on the streaming
    # response (mirrors the engine's _approx_tokens fallback on the full
    # pipeline path). Without this, prompt/context token accounting on the
    # trivial/conversational short-circuit stays 0 — completion tokens were
    # populated but prompt tokens never were.
    _prompt_est = _approx_tokens(
        "\n".join(str(m.get("content", "")) for m in messages if isinstance(m, dict))
    )

    try:
        _usage_agg: dict[str, int] = {}
        _streamed_any_text = False
        _stream_error: str | None = None
        async for chunk in adapter.chat(messages, intent="chat"):
            # Only forward real usage dicts — MagicMock-based fake adapters in
            # tests auto-create truthy usage attributes that aren't dicts.
            _u = chunk.usage if isinstance(getattr(chunk, "usage", None), dict) else {}
            _usage_agg.update(_u)
            # Same guard for error chunks: streamed provider errors (429, auth
            # failure, ...) surface in the fallback instead of being masked by
            # the generic overload message.
            _err = getattr(chunk, "error", None)
            if isinstance(_err, str) and _err:
                _stream_error = _err
            if hasattr(chunk, "text") and chunk.text:
                _streamed_any_text = True
                yield StreamChunk(text=chunk.text, done=False, usage=dict(_u))
        # Forward the authoritative final usage on the done chunk — streaming
        # providers often report usage only on the final, text-less delta, so
        # per-chunk forwarding alone would drop it. The pipeline's `.update()`
        # merge makes the done chunk the final word. The local estimate is used
        # ONLY when the provider reported nothing at all — never overriding a
        # real prompt count.
        _done_usage: dict[str, int] = dict(_usage_agg)
        if not _usage_agg and _prompt_est:
            _done_usage["prompt_tokens"] = _prompt_est
        # Session 153 / silent-failure contract: when the adapter streamed
        # ZERO text (free-tier models can return empty or reasoning-only
        # streams — the provider reports usage but never emits content), the
        # UI would show a status update with an EMPTY bubble, which reads as
        # "the message never displayed". Yield a meaningful fallback instead
        # — mirroring the agent loop's overload wording (loop.py) — so the
        # turn always ends with visible text. Normal streams are untouched.
        if not _streamed_any_text:
            if _stream_error:
                # ADR-20/21 (Session 171): never embed the raw provider
                # payload in the fallback TEXT — the user previously saw
                # "zen returned 429: {…json…}" dumped into the bubble. Use
                # the canonical friendly message instead, and forward the
                # raw error on chunk.error so the SSE boundary emits the
                # canonical error object → the ErrorMessage card renders
                # (Try again / Switch model). The clean text keeps the
                # Session 153 visible-text + persistence guarantees.
                _norm = normalize_error(_stream_error)
                yield StreamChunk(
                    text=(
                        "I couldn't get a response from the model. "
                        f"{_norm['message']}"
                    ),
                    done=False,
                )
                yield StreamChunk(
                    text="",
                    done=True,
                    error=_stream_error,
                    usage=_done_usage,
                )
                return
            _fallback = (
                "I didn't get a response from the model this time — the "
                "free-tier model may be overloaded. Please try again, or "
                "switch to a faster model."
            )
            yield StreamChunk(text=_fallback, done=False)
        yield StreamChunk(text="", done=True, usage=_done_usage)
    except Exception:
        # If the direct chat fails, yield a minimal fallback and done.
        # Do NOT fall through to the parent-agent runtime — that would defeat
        # the purpose of the short-circuit.
        yield StreamChunk(
            text="Hi! I'm LocalMind. How can I help you?",
            done=False,
        )
        yield StreamChunk(text="", done=True)


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

    This is a lightweight conversational response — no capability inference
    or tool execution is needed. The model just streams a direct reply.

    Session 187: pure social intents (greeting/farewell/thanks/
    acknowledgment) are answered DETERMINISTICALLY with zero LLM calls —
    the provider being down/rate-limited must never turn "hi" into an
    error card. "yes_no" and conversational questions still use the model.

    Args:
        message: the user's trivial message.
        adapter: the model adapter (already configured with the right model).
        history: optional chat history for context.

    Yields:
        StreamChunk — the model's direct response, streamed token by token.
    """
    _kind = trivial_intent(message)
    _canned = _SOCIAL_REPLIES.get(_kind)
    if _canned:
        logger.info(
            "[trivial] %r → deterministic %s reply (no LLM call)",
            message[:40],
            _kind,
        )
        # Session 111 accounting: even a zero-LLM turn must report a nonzero
        # prompt estimate (system+user prompt) so the Observe panel Context
        # Tokens and the bottom-bar prompt count don't drop to a misleading 0
        # on greeting turns (the reviewer flagged this gap).
        _est = _approx_tokens(f"You are LocalMind.\n{message}")
        yield StreamChunk(text=_canned, done=False, usage={"prompt_tokens": _est})
        yield StreamChunk(
            text="",
            done=True,
            usage={"prompt_tokens": _est, "completion_tokens": len(_canned) // 4},
        )
        return
    async for chunk in _direct_chat_response(
        message,
        adapter,
        history,
        system_prompt=(
            "You are LocalMind, a local AI assistant. Respond naturally "
            "and briefly. Do not output your reasoning process — just "
            "give the response directly."
        ),
    ):
        yield chunk


async def conversational_response(
    message: str,
    adapter,
    history: Optional[list[dict]] = None,
) -> AsyncIterator[StreamChunk]:
    """
    Stream a direct chat response for a conversational question.

    Same single-call fast path as `trivial_response`, with a prompt that
    asks for a natural answer to the user's question. Bypasses the parent
    agent loop — verified fix for the ~40s "What can you do?" latency
    (ADR-11 / B-2026-08-09-1).

    Args:
        message: the user's conversational question.
        adapter: the model adapter (already configured with the right model).
        history: optional chat history for context.

    Yields:
        StreamChunk — the model's direct answer, streamed token by token.
    """
    async for chunk in _direct_chat_response(
        message,
        adapter,
        history,
        system_prompt=(
            "You are LocalMind, a local AI assistant. Answer the user's "
            "question naturally and briefly. Do not output your reasoning "
            "process — just give the response directly."
        ),
    ):
        yield chunk
