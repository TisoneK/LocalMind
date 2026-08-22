"""
Session 339 — Conversation-state awareness + memory-relevance gating.

The user's diagnosis (verbatim):
  > Memory should enrich the current conversation, not choose its topic.
  > The current user message determines the topic.
  > Memory can only contribute if it passes a relevance threshold.
  > A new conversation should start with an open beginning by default.

This module implements 3 things:

1. ConversationMode — OPEN / ESTABLISHED / CONTINUATION
   - OPEN: first turn of a new chat. No memory injection, no topic assumption.
     User says "Hi" / "Hello" / "How's it going?" → just respond, don't
     retrieve old memories or resurrect old tasks.
   - ESTABLISHED: the user has stated a topic ("Let's work on LocalMind",
     "Give me the EPL standings"). Memory can SUPPORT the topic but
     cannot introduce a new one.
   - CONTINUATION: the user explicitly says "Continue" / "Pick up where
     we left off" / "What about that task?" → retrieve pending work
     and resume.

2. Memory-relevance gate
   - Casual/opening prompts ("Hi", "How's it going?", "What's up?")
     must NOT trigger memory retrieval. The user is starting a conversation,
     not asking about old work.
   - Memory is only retrieved when the user's message establishes a topic
     or explicitly continues prior work.

3. Tool-selection abstraction
   - The agent must NEVER ask the user "which tool should I use?" or
     "please provide the tool name." Tool selection is the agent's job.
   - This is enforced via a system-prompt reminder injected when the
     user's message asks for an outcome that needs a tool.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ConversationMode(Enum):
    """The conversation's current mode — determines memory retrieval behavior.

    - OPEN: first turn of a new chat. No memory injection. User establishes direction.
    - ESTABLISHED: user has stated a topic. Memory can support but not steer.
    - CONTINUATION: user explicitly asked to continue prior work. Retrieve pending.
    """

    OPEN = "open"
    ESTABLISHED = "established"
    CONTINUATION = "continuation"


@dataclass
class ConversationState:
    """The conversation's state, derived from the parent session + user message.

    `mode` determines whether memory retrieval is appropriate.
    `reason` is a human-readable explanation for logging/observability.
    """

    mode: ConversationMode
    reason: str
    turn_count: int  # from ParentSession
    should_retrieve_memory: bool
    should_retrieve_pending_work: bool


# ── Casual/opening prompts that must NOT trigger memory retrieval ───────────

# These are the "Hi" / "How's it going?" / "What's up?" prompts.
# They're already caught by the trivial fast-path (Session 332-C) when
# they're short enough, but this module catches the broader pattern:
# "How's it going" / "How are you doing today" / "What's new" — even when
# they're long enough to fall through the fast-path.

_CASUAL_OPENING_CUES = [
    r"^\s*hi+\s*[!.?]?\s*$",
    r"^\s*hello+\s*[!.?]?\s*$",
    r"^\s*hey+\s*[!.?]?\s*$",
    r"^\s*yo\b",
    r"^\s*sup\b",
    r"^\s*howdy\b",
    r"^\s*greetings\s*[!.?]?\s*$",
    r"^\s*good\s+(?:morning|afternoon|evening|day)\s*[!.?]?\s*$",
    # "How's it going" / "How are you" — the EPL-hijack case
    r"^\s*how(?:'s|s|\s+is)\s+(?:it\s+going|it\s+going|everything|things|the\s+going)\s*[!.?]?\s*$",
    r"^\s*how\s+are\s+you\s*[!.?]?\s*$",
    r"^\s*how\s+are\s+(?:things|you\s+doing)\s*[!.?]?\s*$",
    r"^\s*what(?:'s|s|\s+is)\s+up\s*[!.?]?\s*$",
    r"^\s*what(?:'s|s|\s+is)\s+new\s*[!.?]?\s*$",
    r"^\s*how\s+do\s+you\s+do\s*[!.?]?\s*$",
    r"^\s*nice\s+to\s+(?:meet|see)\s+you\s*[!.?]?\s*$",
    # "How's the going" / "How's it" — common colloquial variants
    r"^\s*how(?:'s|s|\s+is)\s+(?:the\s+going|it)\s*[!.?]?\s*$",
    r"^\s*whats\s+up\s*[!.?]?\s*$",
    r"^\s*how\s+goes\s+it\s*[!.?]?\s*$",
    r"^\s*what\s+good\s*[!.?]?\s*$",
    r"^\s*everything\s+(?:good|ok|cool|alright)\s*[!.?]?\s*$",
    r"^\s*you\s+good\s*\??\s*$",
]
_CASUAL_OPENING_RE = re.compile("|".join(_CASUAL_OPENING_CUES), re.IGNORECASE)


def _is_casual_opening(message: str) -> bool:
    """Return True if the message is a casual/opening greeting that
    must NOT trigger memory retrieval.

    Conservative: only matches messages that are PURELY social openers
    with no topic content. "Hi, can you help with X?" does NOT match
    (the user established a topic). "How's it going?" DOES match.
    """
    if not message:
        return False
    return bool(_CASUAL_OPENING_RE.match(message.strip()))


# ── Explicit continuation cues ──────────────────────────────────────────────

_CONTINUATION_CUES = [
    r"\bcontinue\s+(?:from|with|where|the)\b",
    r"\bpick\s+up\s+where\s+we\s+left\s+off\b",
    r"\bresume\s+(?:the|that|our|work|task)\b",
    r"\bwhat\s+happened\s+(?:to|with)\s+(?:that|the)\b",
    r"\bdid\s+you\s+finish\b",
    r"\bwhat\s+about\s+(?:that|the)\s+(?:task|work|request)\b",
    r"\bback\s+to\s+(?:our|the)\s+(?:work|task|project)\b",
    r"\bwhere\s+were\s+we\b",
    r"\blet'?s\s+continue\b",
    r"\bcarry\s+on\b",
]
_CONTINUATION_RE = re.compile("|".join(_CONTINUATION_CUES), re.IGNORECASE)


def _is_explicit_continuation(message: str) -> bool:
    """Return True if the user explicitly asked to continue prior work."""
    if not message:
        return False
    return bool(_CONTINUATION_RE.search(message))


# ── Topic-establishment detection ───────────────────────────────────────────

# A message "establishes a topic" when it contains substantive content beyond
# a casual opener. We use a simple heuristic: ≥3 words AND not a casual opener
# AND not just a question mark / acknowledgment.

_TOPIC_MIN_WORDS = 3


def _establishes_topic(message: str) -> bool:
    """Return True if the user's message establishes a conversation topic.

    A message establishes a topic when it has substantive content (≥3 words)
    and is not a pure social opener. This is the threshold for memory
    retrieval to activate.
    """
    if not message or not message.strip():
        return False
    if _is_casual_opening(message):
        return False
    words = message.strip().split()
    return len(words) >= _TOPIC_MIN_WORDS


# ── Public entry point ──────────────────────────────────────────────────────


def classify_conversation(
    message: str,
    turn_count: int,
    has_pending_work: bool = False,
) -> ConversationState:
    """Classify the conversation state for memory-relevance gating.

    Args:
        message: the user's current message.
        turn_count: the parent session's turn count (0 = first turn of a new chat).
        has_pending_work: whether there's unresolved work from a prior turn
            in THIS session (not cross-session — cross-session pending work
            is only retrieved on explicit CONTINUATION).

    Returns:
        ConversationState with the mode + retrieval flags.

    Rules (the user's 6 invariants):
      1. A new conversation begins without an assumed topic.
      2. Memory may support the user's intent, but may not introduce a new
         topic unprompted.
      3. Unresolved tasks are conversation state, not ordinary semantic memory.
      4. Users specify desired outcomes. The parent agent selects tools autonomously.
      5. Tool names, schemas, parameters must remain implementation details.
      6. Internal instructions, tool results, user messages, and memory must
         remain source-separated.
    """
    # Rule 1: a new conversation (turn_count == 0) starts OPEN — UNLESS
    # the user's first message establishes a topic (substantive content).
    # "Hi" on turn 0 → OPEN (no memory). "Give me EPL standings" on turn 0
    # → ESTABLISHED (memory can support the topic).
    is_casual = _is_casual_opening(message)
    is_continuation = _is_explicit_continuation(message)
    establishes_topic = _establishes_topic(message)

    # Explicit continuation on a new chat with pending work → CONTINUATION
    if is_continuation and has_pending_work:
        return ConversationState(
            mode=ConversationMode.CONTINUATION,
            reason="explicit continuation request + pending work exists",
            turn_count=turn_count,
            should_retrieve_memory=True,
            should_retrieve_pending_work=True,
        )

    # Explicit continuation WITHOUT pending work → OPEN (nothing to continue,
    # the agent should ask what to continue). This is the safe fallback —
    # don't retrieve memory because there's nothing to retrieve.
    if is_continuation and not has_pending_work:
        return ConversationState(
            mode=ConversationMode.OPEN,
            reason="continuation request but no pending work — ask what to continue",
            turn_count=turn_count,
            should_retrieve_memory=False,
            should_retrieve_pending_work=False,
        )

    # Casual opener (any turn) → OPEN. No memory, no topic assumption.
    if is_casual:
        return ConversationState(
            mode=ConversationMode.OPEN,
            reason="casual opener — no topic assumed",
            turn_count=turn_count,
            should_retrieve_memory=False,
            should_retrieve_pending_work=False,
        )

    # First turn with substantive content → ESTABLISHED (memory can support)
    if turn_count == 0 and establishes_topic:
        return ConversationState(
            mode=ConversationMode.ESTABLISHED,
            reason="first turn — user established a topic, memory can support",
            turn_count=turn_count,
            should_retrieve_memory=True,
            should_retrieve_pending_work=False,
        )

    # First turn with short non-casual content (rare: "ok", "yes") → OPEN
    if turn_count == 0:
        return ConversationState(
            mode=ConversationMode.OPEN,
            reason="first turn, ambiguous content — no topic assumed",
            turn_count=turn_count,
            should_retrieve_memory=False,
            should_retrieve_pending_work=False,
        )

    # Non-first turn with topic → ESTABLISHED
    if establishes_topic:
        return ConversationState(
            mode=ConversationMode.ESTABLISHED,
            reason="user established a topic — memory can support",
            turn_count=turn_count,
            should_retrieve_memory=True,
            should_retrieve_pending_work=False,
        )

    # Fallback: short non-casual message on a non-first turn. Treat as
    # ESTABLISHED (the conversation already has context) but don't
    # aggressively retrieve memory.
    return ConversationState(
        mode=ConversationMode.ESTABLISHED,
        reason="continuing established conversation",
        turn_count=turn_count,
        should_retrieve_memory=False,  # conservative — don't inject on ambiguous
        should_retrieve_pending_work=False,
    )


# ── Tool-selection abstraction enforcement ──────────────────────────────────

# When the user's message asks for an outcome that needs a tool (fresh data,
# files, calculations, web info), inject a reminder that the agent must
# select the tool autonomously and NEVER expose tool names/schemas to the user.

_TOOL_ABSTRACTION_REMINDER = (
    "TOOL SELECTION RULE: The user specifies desired OUTCOMES, not tools. "
    "You must autonomously select the appropriate capability (web_search, "
    "file_read, calculator, etc.) based on the user's request. NEVER ask "
    "the user 'which tool should I use?' or 'please provide the tool name' "
    "or 'what parameters should I pass?'. Tool names, schemas, and API "
    "mechanics are implementation details that must remain invisible to "
    "the user. If the user asks for current information, search the web. "
    "If they ask about files, read them. If they ask for a calculation, "
    "compute it. The user's responsibility is WHAT; your responsibility is HOW."
)

# Cues that signal the user is asking for an outcome that needs a tool
_OUTCOME_REQUIRES_TOOL_CUES = [
    r"\bcurrent\b.*\b(?:news|weather|score|price|standings?|table|results?)\b",
    r"\blatest\b.*\b(?:news|info|data|results?|update)\b",
    r"\b(?:search|find|look\s+up)\b.*\b(?:web|online|internet)\b",
    r"\bcalculate\b",
    r"\b(?:find|search|locate)\b.*\bfiles?\b",
    r"\b(?:standings?|table|results?)\b.*\b(?:EPL|Premier\s+League|football|soccer)\b",
    r"\bweather\s+in\b",
    r"\b(?:news|headlines|trending)\b",
]
_OUTCOME_REQUIRES_TOOL_RE = re.compile(
    "|".join(_OUTCOME_REQUIRES_TOOL_CUES), re.IGNORECASE
)


def should_inject_tool_abstraction_reminder(message: str) -> bool:
    """Return True when the user's message asks for an outcome that needs
    a tool AND the reminder hasn't been injected yet this turn.

    This prevents the agent from asking 'which tool should I use?' — the
    user should never see tool names or schemas.
    """
    if not message:
        return False
    return bool(_OUTCOME_REQUIRES_TOOL_RE.search(message))


def get_tool_abstraction_reminder() -> str:
    """Return the tool-selection abstraction reminder text."""
    return _TOOL_ABSTRACTION_REMINDER
