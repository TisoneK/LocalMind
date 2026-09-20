"""
Title Generation Subsystem

Two-stage approach:
  Stage 1 (sync, instant): keyword/intent heuristic → placeholder title stored immediately
  Stage 2 (async, ~2s):    LLM call → concise title overwrites the placeholder

Stage 2 fires as a background asyncio task so it never blocks the response stream.

Title-gen is intent-gated, not turn-count-gated. If
the first message is trivial (greeting/thanks/farewell/yes-no/acknowledgment),
Stage 2 is skipped — the placeholder "New Chat" stays until a substantive
message arrives. The LLM title-gen fires on the first non-trivial message,
not on turn 1 blindly. This prevents the "Hi" / "Hello" / "Quick hello"
sidebar pollution the user reported.
"""

from __future__ import annotations

import asyncio
import logging
import re

logger = logging.getLogger(__name__)


# ── Stage 1: instant heuristic placeholder ────────────────────────────────────


def generate_title_smart(message: str, intent: str | None = None) -> str:
    """
    Fast synchronous placeholder title — used immediately so the sidebar
    shows something while the LLM-generated title is being computed.
    Returns a short cleaned version of the user message, max 35 chars.

    Trivial inputs (greetings/thanks/farewells) return "New Chat"
    as the placeholder, NOT the greeting text. This prevents the sidebar
    from filling up with "Hi" / "Hello" / "Quick hello" — the title stays
    "New Chat" until a substantive message triggers the LLM title-gen.
    """
    if not message:
        return "New Chat"

    clean = message.strip()

    # Filter out error messages that should never be session titles.
    _ERROR_PREFIXES = (
        "Cannot connect to",
        "Ollama returned",
        "returned 4",
        "returned 5",
        "timed out",
        "async_generator",
        "object ",
        "Error:",
        "⚠",
        "Connection refused",
        "model not found",
        "ConnectionError",
        "HTTPConnectionPool",
        "No connection adapters",
    )
    for prefix in _ERROR_PREFIXES:
        if clean.startswith(prefix) or clean.startswith(prefix.lower()):
            return "Error — try again"

    # Trivial inputs (greetings/thanks/farewells/yes-no/
    # acknowledgments) return "New Chat" — the LLM title-gen will fire
    # on the first substantive message instead. This prevents the sidebar
    # from filling up with "Hi" / "Hello" / "ok" / "thanks" placeholders
    # that never get refined (because the LLM call on "Hi" either fails
    # or produces a bad title).
    try:
        from core.trivial_input import is_trivial_input

        if is_trivial_input(clean):
            return "New Chat"
    except ImportError:
        # trivial_input module not available — fall through to the old
        # behavior (return the greeting text). Non-blocking.
        pass

    # Strip common leading filler words
    clean = re.sub(
        r"^(please|kindly|help me|can you|could you|would you|i need|i want to"
        r"|i'd like|tell me|show me|write me|give me|create a?|generate a?|make a?)\s+",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip()

    # Strip leading articles
    clean = re.sub(r"^(a|an|the)\s+", "", clean, flags=re.IGNORECASE).strip()

    # Truncate
    if len(clean) > 35:
        # Try to cut at a word boundary
        cut = clean[:32].rsplit(" ", 1)[0]
        clean = cut + "…"

    # Uppercase only the first character — never .capitalize(), which lowercases
    # the rest and mangles proper nouns ("Kitengela" → "kitengela").
    return (clean[:1].upper() + clean[1:]) if clean else "New Chat"


# Titles that are placeholders / not yet a real title — safe to overwrite.
_PLACEHOLDER_TITLES = frozenset({"New Chat", "Error — try again"})


def is_placeholder_title(title: str | None) -> bool:
    """True when the session has no real title yet (None or a placeholder)."""
    return title is None or title in _PLACEHOLDER_TITLES


def title_from_obs(obs) -> str:
    """Reuse the title the parent's classify call already produced this turn.

    The parent's first-turn classify call names the turn with a clean 2-4 word
    action phrase ("Fetch Weather") on the ``agent_initialization_done`` obs
    event. Using it as the session title means the sidebar matches the Agent
    Workspace heading AND costs no extra model call — the second title-gen LLM
    request (``refine_title_async``) is only needed as a fallback when the
    classify call produced no title. Returns "" when none was emitted.
    """
    try:
        for evt in obs.history():
            if evt.type == "agent_initialization_done":
                title = str((evt.data or {}).get("title", "")).strip()
                if title:
                    return title[:50]
    except Exception:  # pragma: no cover — never let title-gen break a turn
        return ""
    return ""


# ── Stage 2: async LLM title ──────────────────────────────────────────────────

# Title generation should be fast — cap at 30s to avoid clogging the Ollama
# instance with a long-running background request that blocks real user queries.
_TITLE_TIMEOUT = 30


async def refine_title_async(session_id: str, message: str) -> None:
    """
    Generate a concise LLM title for the session and write it to the DB.
    Called as a fire-and-forget background task after a substantive turn
    completes. Uses the same adapter as the main engine — respects
    LOCALMIND_ADAPTER setting.

    This function now checks is_trivial_input() first and
    returns immediately for greetings/thanks/farewells — no LLM call
    wasted on "Hi". The title-gen fires on the first SUBSTANTIVE message,
    not on turn 1 blindly.
    """
    from adapters import get_adapter
    from core.config import settings

    # Skip trivial inputs entirely — don't waste an LLM call
    # on "Hi" / "Hello" / "thanks". The title stays "New Chat" until a
    # substantive message triggers this function.
    try:
        from core.trivial_input import is_trivial_input

        if is_trivial_input(message):
            logger.info(
                "[title] skipping LLM title-gen for trivial input %r for %s",
                message[:30],
                session_id[:8],
            )
            return
    except ImportError:
        pass

    try:
        prompt_messages = [
            {
                "role": "system",
                "content": (
                    "You are a title generator. Given a user message, produce a short title "
                    "of 2–5 words that captures the topic. Output ONLY the title — no quotes, "
                    "no punctuation at the end, no explanation.\n"
                    "\n"
                    "RULES:\n"
                    "- Be specific to what the user is asking about, not generic.\n"
                    "- For greetings, describe the interaction: 'Quick hello', 'Evening chat', 'Casual intro'.\n"
                    "- For tasks, describe the task: 'Python debug help', 'File search request', 'Weather check'.\n"
                    "- Never use generic words alone: Greeting, Hello, Chat, Conversation, Question.\n"
                    "- Never copy these examples verbatim — generate a unique title for each message."
                ),
            },
            {"role": "user", "content": message[:300]},
        ]

        adapter = get_adapter(settings.localmind_adapter)
        # A title is cosmetic: it must ride the same provider failover as the turn, so a provider
        # that is out of quota costs a quiet retry elsewhere instead of an error in the log.
        from adapters.base import BaseAdapter
        from adapters.failover import FailoverAdapter

        if isinstance(adapter, BaseAdapter):
            adapter = FailoverAdapter(adapter, settings.localmind_adapter)
        chunks: list[str] = []

        # Use a timeout so title generation doesn't block the model for 90s+
        try:
            async with asyncio.timeout(_TITLE_TIMEOUT):
                async for chunk in adapter.chat(prompt_messages, temperature=0.3, intent="chat"):
                    if chunk.error:
                        logger.warning(
                            "[title] adapter error for %s: %s",
                            session_id[:8],
                            chunk.error[:120],
                        )
                        return
                    if chunk.text:
                        chunks.append(chunk.text)
        except asyncio.TimeoutError:
            logger.warning(f"[title] LLM title generation timed out after {_TITLE_TIMEOUT}s for {session_id[:8]}")
            return

        raw = "".join(chunks).strip()

        # Sanitize: strip quotes, trailing punctuation, limit length
        # re imported at module level — no inner re-import
        raw = re.sub(r'^["\']|["\']$', "", raw).strip()
        raw = re.sub(r"[.!?]+$", "", raw).strip()
        if len(raw) > 50:
            raw = raw[:47] + "…"

        # Reject error messages that shouldn't become titles
        _ERROR_INDICATORS = (
            "cannot connect",
            "returned 4",
            "returned 5",
            "timed out",
            "error",
            "failed",
            "not found",
            "connection refused",
            "ollama returned",
            "model",
        )
        if any(ind in raw.lower() for ind in _ERROR_INDICATORS):
            logger.warning(f"[title] rejecting error-like title: '{raw}' for {session_id[:8]}")
            return

        if not raw:
            return

        # Reuse the engine's SessionStore instead of creating a new one per call
        from api.routes.chat import _engine as _chat_engine

        _chat_engine._store.update_session_title(session_id, raw)
        logger.info(f"[title] LLM title for {session_id[:8]}: '{raw}'")

    except Exception as exc:
        logger.warning(f"[title] refine_title_async failed: {exc}")


def should_generate_title(session_id: str, message_role: str) -> bool:
    """Legacy compat — no longer used in main path."""
    return message_role == "user"


def should_refine_title(message: str, current_title: str | None = None) -> bool:
    """
    Decide whether to fire the LLM title-gen for this message.

    Title-gen should fire when:
    - The message is non-trivial (not a greeting/thanks/farewell/yes-no/
      acknowledgment) — trivial inputs don't carry enough intent to title
    - AND the title hasn't already been refined (current_title is None,
      "New Chat", or "Error — try again" — all indicate a placeholder
      that should be replaced)

    This is the intent-gated trigger the user requested: title-gen fires
    on the first SUBSTANTIVE message, not on turn 1 blindly. If message 1
    is "Hi", title-gen waits. If message 2 is "How do I fix a Python bug?",
    title-gen fires on that.

    Args:
        message: the user's current message.
        current_title: the session's current title (None if no title yet,
            "New Chat" if the placeholder was set, or an already-refined
            title). If the title is already refined (not a placeholder),
            this returns False — don't overwrite a good title.

    Returns:
        True if the LLM title-gen should fire, False to skip.
    """
    # If there's already a real title (not a placeholder), don't overwrite it.
    # Placeholders are: None, "New Chat", "Error — try again".
    if current_title is not None and current_title not in ("New Chat", "Error — try again"):
        return False

    # Check if the message is trivial — skip title-gen for greetings/etc.
    try:
        from core.trivial_input import is_trivial_input

        if is_trivial_input(message):
            return False
    except ImportError:
        # trivial_input not available — fall back to: always refine (old behavior)
        pass

    return True


def generate_title_basic(text: str) -> str:
    """Legacy compat."""
    return generate_title_smart(text)
