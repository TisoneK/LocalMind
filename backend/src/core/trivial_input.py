"""
Legacy conversational classifiers and direct-response helpers.

The live request runtime uses these helpers at the conversation boundary.
Obvious social turns and short context-backed questions use one direct-chat
call; ambiguous or tool-bearing turns enter the parent agent, whose
model-owned initialization decision chooses between clarification and
execution. This boundary is generic — it does not special-case individual
capability questions.

Problem: A one-word greeting like "Hi" was burning 11.5s
and ~4.8k tokens because it entered capability inference before being
classified as CHAT. That's massive overkill for inputs that are obviously
conversational.

Fix: detect trivial inputs (greetings, thanks, farewells, yes/no, simple
acknowledgments) and short-circuit them to a direct chat response — no
capability inference, tool planning, or tool loop. The model just streams a
direct reply.

Also short-circuit obviously
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

from core.agent.models import strip_worker_reports_from_history
from core.engine._helpers import _approx_tokens
from core.error_normalizer import normalize_error
from core.models import StreamChunk

logger = logging.getLogger(__name__)

# Capability assertion for the LIGHTWEIGHT reply paths (direct/
# conversational) that don't carry the full agent system prompt. Without it the
# model reverts to generic-LLM behavior and fabricates "I don't have access to
# your filesystem" / "I can't do that" (user live-report — the false claim
# spirals once it starts). These paths answer conversationally (no tools THIS
# turn), but the model must still know LocalMind is a real local agent, and
# point at Agent mode for actions rather than inventing a limitation.
CAPABILITY_NOTE = (
    "You are LocalMind, a real AI agent running ON the user's machine with "
    "actual tools (shell, file read/write/delete, code, web). NEVER claim you "
    "lack access to the filesystem or that you 'can't' do something you could "
    "do with a tool — that is false. You are giving a quick conversational "
    "reply here; if the request needs an ACTION (run a command, edit or delete "
    "files, search the computer), tell the user to switch to Agent mode instead "
    "of inventing a limitation. "
)

# Auto mode has no "other mode" to switch to: one loop decides per message
# whether to act. A lightweight reply that ends up needing a tool must not send
# the user off to a mode that does not exist for them (owner live-report: "Found
# it and???" got a promise plus "flip me to Agent mode" in an Auto session).
AUTO_CAPABILITY_NOTE = (
    "You are LocalMind, a real AI agent running ON the user's machine with "
    "actual tools (shell, file read/write/delete, code, web). NEVER claim you "
    "lack access to the filesystem or that you 'can't' do something you could "
    "do with a tool — that is false. There are no modes for the user to switch "
    "between; never mention modes. This reply has no "
    "tools, so if answering needs an action or live data, say in one sentence "
    "what you will check and end with: Say 'go' and I'll do it. Never narrate "
    "an action as if you were doing it. "
)


def active_capability_note() -> str:
    """The capability note for the lightweight reply paths, by configured chat mode.

    Only an explicit Chat ("direct") mode has an Agent mode to point at; in Auto
    (and Agent) there is nothing to switch to, so the note must not mention one.
    """
    try:
        from core.config import settings as _settings

        if getattr(_settings, "localmind_chat_mode", "auto") == "direct":
            return CAPABILITY_NOTE
    except Exception:
        pass
    return AUTO_CAPABILITY_NOTE


# ── Trivial input patterns ───────────────────────────────────────────────────
# Each pattern is a regex that matches the ENTIRE message (anchored ^...$).
# Conservative: only matches inputs that are obviously conversational.
# Anything ambiguous falls through to the normal pipeline.

# Greetings — "hi", "hello", "hey", "good morning", etc.
# "how are you" / "how's it going" are deliberately NOT here: they are
# wellbeing QUESTIONS, not greeting gestures — a canned "Hi! I'm LocalMind"
# answer to "How are you?" is a wrong reply, not a fast one. They fall to
# is_conversational_question (opener "how", no blocked keywords) and get a
# real model answer with conversation context. True greeting gestures
# ("hi", "hello", "what's up", "sup") route to trivial_response, which
# answers from the MODEL on one call (owner ruling 2026-11-01: a hardcoded
# answer is "not ethical or my design at all"). No input class answers from
# a canned string while the provider is healthy — the canned warm lines are
# the provider-down fallback only (S448 ruling, restated below).
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

# Deterministic replies for PURE SOCIAL intents (greeting /
# farewell / thanks / acknowledgment) — the DEGRADED PATH ONLY. On a healthy
# provider these strings must never be yielded: every social gesture is
# answered by the model via trivial_response (owner rulings S448 "then you
# have all the answers" and 2026-11-01 "hardcoded answers are not ethical or
# my design at all"). They exist so a dead/rate-limited provider still can't
# turn "hi" into an error card: the fallback streams the warm line with the
# synthetic flag (no fabricated provider tokens) instead. "yes_no" and
# conversational questions never take even the fallback — they surface the
# honest provider-dead text (they can be context-dependent).
_SOCIAL_REPLIES: dict[str, str] = {
    "greeting": "Hi! I'm LocalMind, your local AI assistant. How can I help you today?",
    "farewell": "Goodbye! Feel free to come back anytime.",
    "thanks": "You're welcome! Happy to help.",
    "acknowledgment": "Got it! What would you like to do next?",
}


# ── Conversational-question patterns ─────────────────────────────────────────
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
    # Brainstorming/idea imperatives. These signal a
    # conversational request for suggestions/ideas — no tools, files, code,
    # or live data needed. The blocked-keyword guard below still catches
    # tool-bearing phrasings ("give me the weather", "suggest a script that
    # ...", "recommend a file manager").
    r"give me",
    r"suggest",
    r"propose",
    r"recommend",
    r"brainstorm",
    # Knowledge-imperative openers. These signal a request
    # for general-knowledge exposition — no tools, files, code, or live
    # data needed. Even when the message contains a blocked keyword like
    # "RAM" or "disk", the IMPERATIVE makes it clear the user wants an
    # explanation, not a tool action ("summarize the difference between
    # RAM and storage" is exposition, NOT a request for sysinfo).
    # The blocked-keyword guard is bypassed for messages starting with
    # these openers (see _KNOWLEDGE_IMPERATIVES below).
    r"summarize",
    r"compare",
    r"contrast",
    r"outline",
    r"list",
    r"name",
]
_CONVERSATIONAL_OPENER_RE = re.compile(
    r"^(?:" + "|".join(_CONVERSATIONAL_OPENERS) + r")\b",
    re.IGNORECASE,
)

# Knowledge-imperative openers. When a message STARTS with one
# of these, the user is asking for general-knowledge exposition ("Summarize
# the difference between RAM and storage", "Compare TCP vs UDP"). The
# blocked-keyword guard is bypassed because the imperative makes the intent
# unambiguous — "RAM" here is the topic, not a request for the user's RAM.
# Tool/file/code/URL patterns are still checked separately, so "Summarize
# the contents of /etc/passwd" or "Compare these two URLs" still fall
# through.
_KNOWLEDGE_IMPERATIVES = (
    "summarize",
    "compare",
    "contrast",
    "outline",
    "explain",
    "describe",
    "define",
    "brainstorm",
    "suggest",
    "propose",
    "recommend",
    "give me",
    "name",
)

# Debugging-context keywords that remain hard-blocked even
# under knowledge imperatives. "explain this error message" is a debugging
# request — the user has a real error and needs tool evidence (file reads,
# shell output, code inspection) to debug it, not exposition about errors.
_DEBUGGING_BLOCKED_RE = re.compile(
    r"\b(?:error|bug|exception|crash|traceback|stack\s*trace|failed|failure)\b",
    re.IGNORECASE,
)

# History-backed follow-ups may omit an interrogative opener, but they still
# need a conversational shape. This keeps imperative/action messages such as
# "inspect the project" or "build the app" on the parent tool path without
# enumerating individual intents.
_CONVERSATIONAL_FOLLOWUP_RE = re.compile(
    r"^(?:like\b|such\s+as\b|for\s+example\b|and\s+\S+)",
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
    # system info (SYSINFO) — covers all system information queries
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
    r"network",
    r"ip address",
    r"ip ",
    r"mac address",
    r"interface",
    r"uptime",
    r"boot time",
    r"load average",
    r"processes",
    r"environment variable",
    r"env var",
    r"listening port",
    r"service",
    r"whoami",
    r"username",
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

# First-person LOCAL-DISCOVERY questions
# ("where is my LocalMind project?", "where did I save that CV?", "do I
# have multiple copies…", "what's on my computer?") are search questions —
# they need system_search, not exposition. First-person phrasing (my/I/we)
# is the discriminator: "where is the Eiffel Tower?" stays conversational.
# Signal-based local-discovery detection. Real users phrase
# these VAGUELY — "large files", "old photos", "clean up my downloads",
# "what's here", "biggest stuff" — so we detect by CATEGORY signals, not exact
# phrasings. An ambiguous adjective is grounded by a file/disk noun OR local
# context: "largest planet" / "large language model" stay conversational,
# "largest files" / "large downloads" are searches. Each category maps to a
# system_search operation (largest / recent / duplicates / apps / files).
_SIG_SIZE = re.compile(r"\b(?:larg\w*|big|bigger|biggest|huge|massive|enormous|gigantic)\b", re.IGNORECASE)
_SIG_RECENCY = re.compile(
    r"\b(?:recent\w*|latest|newest|lately|today|yesterday|this\s+week"
    r"|last\s+(?:week|month|few\s+days)|old|older|oldest|stale)\b",
    re.IGNORECASE,
)
_SIG_SPACE = re.compile(
    r"\b(?:disk\s*space|free\s+up|freeing\s+up|taking\s+up\s+(?:space|room)"
    r"|running\s+out\s+of\s+space|out\s+of\s+space|clean(?:ing)?\s+up|storage\s+space)\b",
    re.IGNORECASE,
)
_SIG_DUP = re.compile(r"\b(?:duplicate\w*|multiple\s+copies|dupes?|copies\s+of)\b", re.IGNORECASE)
_SIG_INSTALLED = re.compile(
    r"\binstalled\b|\bwhat\s+(?:apps?|programs?|applications?|software)\b"
    r"|\bwhich\s+(?:apps?|programs?|applications?)\b",
    re.IGNORECASE,
)
_SIG_LOCATE = re.compile(r"\b(?:where\s+(?:is|are|did|do|have)|find|locate|search\s+for)\b", re.IGNORECASE)
_SIG_OPENWITH = re.compile(
    r"\bopens?\s+(?:a\s+|an\s+|my\s+|the\s+)?[\w.]+\s+files?\b"
    r"|\bwhich\s+(?:app|application|program)\s+opens?\b",
    re.IGNORECASE,
)
# Folder-inspection phrasings ("what's in my downloads", "show me the
# structure of this repo", "list the files in backend/src", "what does this
# project look like") — the Parent answers these by inspecting the disk, not
# with exposition. Grounded like the size/recency signals: a local noun is
# required, so knowledge questions ("structure of a python class", "what's
# in a name?") stay conversational.
_SIG_INSPECT = re.compile(
    r"\bwhat(?:'s|s)?\s+(?:in|inside|on)\b"
    r"|\b(?:look|looking|looks)\s+(?:at|inside|in|around)\b"
    r"|\b(?:show|see)\s+(?:me\s+)?(?:the\s+|my\s+)?(?:contents?|files?|folders?|structure|layout|tree|shape)\b"
    r"|\b(?:structure|layout|hierarchy|tree|shape)\s+of\b"
    r"|\b(?:list|listing)\s+(?:the\s+|my\s+|out\s+)?(?:contents?|files?|folders?|directories|dir\b|folder\b)"
    r"|\bwhat\s+does\s+(?:this|my|the)\s+\w+\s+look\s+like\b",
    re.IGNORECASE,
)
_INSPECT_CTX = re.compile(
    r"\b(?:folders?|directories|dirs?|files?|repos?|projects?|codebases?|workspaces?"
    r"|computers?|pcs?|macs?|laptops?|drives?)\b",
    re.IGNORECASE,
)
# A noun that makes an otherwise-ambiguous adjective clearly about local content.
_FILE_NOUN = re.compile(
    r"\b(?:files?|folders?|director\w+|documents?|downloads?|photos?|pictures?"
    r"|images?|videos?|apps?|programs?|applications?|stuff|things?)\b",
    re.IGNORECASE,
)
# First-person / this-machine context.
_LOCAL_CTX = re.compile(
    r"\b(?:my|our)\b|\bon\s+(?:my|this)\b"
    r"|\bthis\s+(?:computer|pc|mac|laptop|machine|drive|disk|system)\b",
    re.IGNORECASE,
)
# An adjective bound directly to file content — "large files", "old photos",
# "biggest folder", "recent downloads" — inherently a local search regardless
# of first-person phrasing.
_TROPHY_FILE = re.compile(
    r"\b(?:larg\w*|big|bigger|biggest|huge|massive|small\w*|old\w*|recent\w*|latest|newest|duplicate\w*)"
    r"\s+(?:files?|folders?|documents?|downloads?|photos?|pictures?|images?|videos?|items?|stuff)\b",
    re.IGNORECASE,
)


def _is_local_discovery(message: str) -> bool:
    """True if the message is a first-person/local search question — think like
    a user with a vague prompt, not an exact phrase.  Grounds ambiguous size/
    recency adjectives with a file noun or local context so trivia stays out."""
    m = message
    # Strong standalone signals — almost always about the local machine.
    if _SIG_DUP.search(m) or _SIG_INSTALLED.search(m) or _SIG_SPACE.search(m):
        return True
    if _TROPHY_FILE.search(m) or _SIG_OPENWITH.search(m):
        return True
    if re.search(r"\bwhere\s+(?:did|do|have)\s+i\b", m, re.IGNORECASE):
        return True
    # Recency adjacent to a file-operation verb ("recently modified/edited/
    # saved/downloaded") is a file search even without an explicit noun — but
    # keep ambiguous verbs like "changed" out so "recently changed my mind"
    # stays conversational.
    if re.search(
        r"\brecent\w*\s+(?:modif\w*|edit\w*|sav\w*|download\w*|creat\w*|updat\w*)"
        r"|\b(?:modif\w*|edit\w*|sav\w*|download\w*|creat\w*)\s+(?:recent\w*|lately|today)\b",
        m,
        re.IGNORECASE,
    ):
        return True
    # First-person work history: "what have I been working on / edited / built"
    # → the user wants their recent files (a "recent" search), even with no
    # explicit file noun. Anchored to "i" + a build/edit verb so "what did you
    # do" and "what should I do" stay conversational.
    if re.search(
        r"\bwhat\s+(?:have|did|was|were|am)\s+(?:\w+\s+){0,2}i\b.{0,12}"
        r"\b(?:work\w*|edit\w*|build\w*|creat\w*|sav\w*|download\w*|modif\w*)\b",
        m,
        re.IGNORECASE,
    ):
        return True
    grounded = bool(_FILE_NOUN.search(m) or _LOCAL_CTX.search(m))
    if _SIG_INSPECT.search(m) and (grounded or _INSPECT_CTX.search(m)):
        return True
    if _SIG_LOCATE.search(m) and grounded:
        return True
    if (_SIG_SIZE.search(m) or _SIG_RECENCY.search(m)) and grounded:
        return True
    return False

# File-extension / URL signals that must always route to tools.
_CONVERSATIONAL_FILE_EXT_RE = re.compile(
    r"\b\w+\.(?:py|js|ts|tsx|jsx|md|json|txt|pdf|docx?|xlsx?|csv|html?|css|sh|sql)\b",
    re.IGNORECASE,
)
_CONVERSATIONAL_URL_RE = re.compile(r"https?://", re.IGNORECASE)

# Size caps for the conversational fast-path.
# Bumped from 140/20 to 200/25 to catch short logic questions
# like "We have three branches. One closed. We opened two. How many now?"
# (22 words, 131 chars). The blocked-keyword guard still catches tool/
# realtime/system queries so routing-sensitive prompts fall through.
# 25 words is the sweet spot: branch-count (22w) passes; the original
# over-wordy test fixture (30w) still falls through.
_CONVERSATIONAL_MAX_CHARS = 200
_CONVERSATIONAL_MAX_WORDS = 25
# Minimum word count for a no-opener "?"-ending message to
# qualify as a conversational question. Fragments like "Like what?" (2
# words) need prior assistant context; complete thoughts like "We have
# three branches..." (22 words) stand alone.
_CONVERSATIONAL_NO_OPENER_MIN_WORDS = 5


def is_conversational_question(message: str, history: Optional[list[object]] = None) -> bool:
    """
    Detect whether a message is an OBVIOUSLY-conversational question or
    short follow-up that can be answered with a single direct chat call — no tools.

    Conservative by design: the message must either start with an interrogative
    opener OR be a complete thought ending in "?" (≥5 words),
    AND contain none of the tool/realtime/system keywords, so routing-sensitive
    queries ("what is today's EPL games?", "what time is it", "how much RAM do
    I have", "who wrote app.py") always fall through to the parent agent loop.
    Anything ambiguous → False.

    Args:
        message: the user's message text.
        history: optional prior messages used to recognize short conversational
            follow-ups without routing action-oriented requests away from tools.

    Returns:
        True if the input is a conversational question that should
        short-circuit to a direct chat response. False to run the normal
        pipeline.
    """
    if not message or not message.strip():
        return False

    # Check the trailing "?" BEFORE stripping punctuation —
    # _TRIVIAL_PUNCT includes "?" so the stripped form loses the question
    # marker, breaking the "ends with ?" fast-path below.
    _raw_stripped = message.strip()
    _ends_with_question = _raw_stripped.endswith("?") or _raw_stripped.endswith("?\"") or _raw_stripped.endswith("?'")
    cleaned = _raw_stripped.rstrip(_TRIVIAL_PUNCT).strip()

    # Size caps — conversational questions are short by definition.
    if len(cleaned) > _CONVERSATIONAL_MAX_CHARS:
        return False
    words = cleaned.split()
    if len(words) > _CONVERSATIONAL_MAX_WORDS:
        return False

    # Accept EITHER an opener OR a trailing question mark
    # (with a minimum word count so fragments like "Like what?" don't
    # qualify without history). Previously required an opener, which
    # excluded short logic questions like "We have three branches. One
    # closed. We opened two. How many now?" — these are conversational
    # (no tools needed) but don't start with what/who/how.
    _has_opener = bool(_CONVERSATIONAL_OPENER_RE.match(cleaned))
    if not _has_opener:
        if _ends_with_question and len(words) >= _CONVERSATIONAL_NO_OPENER_MIN_WORDS:
            # Complete thought ending in "?" with no blocked keywords —
            # safe to fast-path. Example: "We have three branches. One
            # closed. We opened two. How many now?"
            pass
        else:
            # No opener + (no "?" or too short) — only a short history-
            # backed follow-up ("Like what?") qualifies.
            if (
                not history
                or len(words) > 8
                or not _ends_with_question
                and not _CONVERSATIONAL_FOLLOWUP_RE.match(cleaned)
            ):
                return False
            # The REFERENT of a short follow-up is the most recent assistant
            # turn, so only that turn's tool calls make it mid-task. Scanning
            # the whole window meant one older tool-using turn dragged every
            # later follow-up into the agent loop — "Don't you?" about a plain
            # text reply was answered as if it were a request to act.
            has_assistant_answer = False
            latest_assistant_ran_tools = False
            for item in reversed(list(history)):
                role = item.get("role") if isinstance(item, dict) else getattr(item, "role", "")
                if getattr(role, "value", role) != "assistant":
                    continue
                has_assistant_answer = True
                latest_assistant_ran_tools = bool(
                    item.get("tool_calls") if isinstance(item, dict) else getattr(item, "tool_calls", None)
                )
                break
            if latest_assistant_ran_tools or not has_assistant_answer:
                return False

    # Must not reference anything that needs tools, live data, or system
    # info — those must reach the dispatcher for correct routing.
    # Knowledge-imperative openers bypass the blocked-keyword
    # guard. "Summarize the difference between RAM and storage" contains
    # "RAM" (a sysinfo keyword) but the IMPERATIVE makes the intent
    # unambiguous — the user wants exposition, not their system's RAM.
    # File-extension and URL patterns are still checked (those are
    # structural signals of tool action regardless of intent).
    # Addendum: error/bug/exception/crash remain hard-blocked
    # even under knowledge imperatives — "explain this error message" is a
    # debugging request that needs tool evidence (file reads, shell, code),
    # not exposition.
    _is_knowledge_imperative = any(
        cleaned.lower().startswith(imp) for imp in _KNOWLEDGE_IMPERATIVES
    )
    if _is_knowledge_imperative:
        # Hard-blocked even under knowledge imperatives (debugging context)
        if _DEBUGGING_BLOCKED_RE.search(cleaned):
            return False
    else:
        if _CONVERSATIONAL_BLOCKED_RE.search(cleaned):
            return False
    if _CONVERSATIONAL_FILE_EXT_RE.search(cleaned):
        return False
    if _CONVERSATIONAL_URL_RE.search(cleaned):
        return False
    # Local-discovery questions are search questions — hard
    # block even under knowledge imperatives ("describe where my CV is"
    # still needs a filesystem search, not exposition).
    if _is_local_discovery(cleaned):
        return False

    return True


# A question about THIS conversation — what was just said, what the user
# asked, what the assistant replied. It must be answered from the visible
# transcript, never by calling a memory tool and never from long-term memory:
# on 2026-10-31 "Did you answer that from memory?" and "Did I ask about that?"
# each ran `Memory: list` and answered by dumping four stored facts.
_CONVERSATION_RECALL_RE = re.compile(
    r"(?:"
    r"\bwhat\s+(?:did|was|were)\s+(?:i|you)\b.{0,40}?"
    r"\b(?:say|said|reply|replied|answer|answered|ask|asked|mean|meant|mention|mentioned)\b"
    r"|\bdid\s+(?:i|you)\b.{0,40}\b(?:say|said|ask|asked|answer|answered|reply|replied|mean|meant|mention|mentioned)\b"
    r"|\b(?:your|my)\s+(?:last|previous|earlier|first)\s+(?:reply|answer|message|response|question)\b"
    r"|\bwhat\s+was\s+(?:your|my)\s+(?:reply|answer|question|message|response)\b"
    r")",
    re.IGNORECASE,
)
# Words that name the conversation itself. They are stripped before the
# tool-signal keyword guard runs ("memory" is a blocked keyword — the very
# word that must not push this question into the tool lane).
_RECALL_SUBJECT_RE = re.compile(
    r"\b(?:memory|memories|remember|recall|conversation|chat|history|stored|store)\b",
    re.IGNORECASE,
)


def is_conversation_recall_question(message: str) -> bool:
    """True when the message asks WHAT WAS SAID in this conversation.

    These questions have a single correct source: the transcript above them.
    LocalMind answered them with a memory lookup instead — printing stored
    facts the user never asked about, and contradicting its own previous
    sentence — so they are recognised deterministically and routed to the
    transcript lane, which carries the recent turns and no tools.

    Conservative: a file, URL or local-discovery reference still needs the
    agent loop ("what did I write to app.py?" is a file question, not a
    transcript one).
    """
    if not message or not message.strip():
        return False
    text = message.strip()
    if len(text) > 300:
        return False
    if not _CONVERSATION_RECALL_RE.search(text):
        return False
    if _CONVERSATIONAL_FILE_EXT_RE.search(text) or _CONVERSATIONAL_URL_RE.search(text):
        return False
    if _is_local_discovery(text):
        return False
    # Blocked keywords still mean "this needs a tool" — except the ones that
    # merely name the conversation being asked about.
    if _CONVERSATIONAL_BLOCKED_RE.search(_RECALL_SUBJECT_RE.sub(" ", text)):
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


def message_implies_tool_action(message: str) -> bool:
    """
    Does this user message imply a tool/file/code action?

    Returns True when the message references tool/file/code/realtime/system
    keywords that would need a tool to satisfy (e.g. "find files in /tmp",
    "run pytest", "create hello.py", "what's the weather"). Returns False
    for purely conversational messages ("give me ideas for a cyber café",
    "what do you think about X", "recommend a book").

    Used by the action-narration detector in the parent-agent loop to scope
    its replan trigger: only fire when the user actually expected a tool
    action, not when the model produced a conversational answer to a
    conversational question.

    Knowledge-imperative openers ("summarize", "compare",
    "explain", etc.) return False even when the message contains a blocked
    keyword like "RAM" — the imperative makes the intent unambiguous
    (exposition, not sysinfo). This prevents the parent-agent loop from
    injecting workspace/git context on knowledge questions.
    """
    if not message:
        return False
    cleaned = message.strip().rstrip(_TRIVIAL_PUNCT).strip()
    # Knowledge-imperative bypass
    if any(cleaned.lower().startswith(imp) for imp in _KNOWLEDGE_IMPERATIVES):
        # Still check file-ext/URL — those are structural tool signals
        if _CONVERSATIONAL_FILE_EXT_RE.search(cleaned):
            return True
        if _CONVERSATIONAL_URL_RE.search(cleaned):
            return True
        return False
    if _CONVERSATIONAL_BLOCKED_RE.search(message):
        return True
    if _CONVERSATIONAL_FILE_EXT_RE.search(message):
        return True
    if _CONVERSATIONAL_URL_RE.search(message):
        return True
    # Local-discovery phrasing implies a search tool action.
    if _is_local_discovery(message):
        return True
    return False


# Explicit approval of a previously narrated pending action ("Go ahead",
# "do it", "please proceed"). Deliberately narrower than _YES_NO /
# _ACKNOWLEDGMENTS: a bare "yes" or "ok" is too ambiguous to force escalation
# without conversation history, but these action-directed phrases are not.
_APPROVAL_TOKENS = [
    r"go\s+ahead",
    r"go\s+for\s+it",
    r"(?:please\s+)?do\s+it(?:\s+please)?",
    r"(?:please\s+)?do\s+that",
    r"(?:please\s+)?proceed",
    r"let'?s\s+do\s+it",
    r"confirmed",
    r"approved",
    r"(?:yes|yeah|yep|ok|okay|sure)[,.]?\s*(?:go\s+ahead|go\s+for\s+it|do\s+it|proceed)",
    r"sounds\s+good,?\s*(?:go\s+ahead|do\s+it|proceed)",
]
_APPROVAL_RE = re.compile(r"^(?:" + "|".join(_APPROVAL_TOKENS) + r")$", re.IGNORECASE)


def message_is_action_approval(message: str) -> bool:
    """
    Does this message approve/confirm a previously narrated pending action?

    Matches short, explicit approval phrases ("go ahead", "do it", "please
    proceed", "confirmed") — deliberately NOT bare "yes"/"ok" alone, which
    are too ambiguous outside conversation history to safely force
    escalation.

    Used by the action-narration detector in the parent-agent loop
    (B-2026-09-15-8): an approval message doesn't itself mention any
    tool/file/code keyword, so message_implies_tool_action() alone would
    miss it and the gate would wrongly suppress as "conversational" — but
    if the agent already narrated a pending action and the user just
    approved it, the gate must still escalate.
    """
    if not message:
        return False
    cleaned = message.strip().rstrip(_TRIVIAL_PUNCT).strip()
    if not cleaned or len(cleaned) > 40:
        return False
    return bool(_APPROVAL_RE.match(cleaned))


_AFFIRMATION_RE = re.compile(
    r"^(?:yes|yeah|yep|yup|ok|okay|sure|please|please do|do it|go|go ahead|go on|proceed|"
    r"sounds good|that works|fine|alright|absolutely|definitely|of course|"
    r"yes please|yes go ahead|ok do it|sure go ahead|ok go ahead)$",
    re.IGNORECASE,
)
_OFFER_RE = re.compile(
    r"(want me to|would you like|shall i|should i|do you want|let me know if|ready when you are|"
    r"i can (?:do|run|check|install|try)|i'?ll (?:need|have) to|need your (?:ok|okay|approval|permission)|"
    r"before i (?:do|run|install|proceed)|confirm|say ['\"]?(?:go|yes)\b|"
    r"let me (?:check|look|search|run|open|read|list|find|fetch|browse))",
    re.IGNORECASE,
)


def approves_pending_offer(message: str, history: Optional[list[dict]] = None) -> bool:
    """A bare "yes / ok / go ahead" that answers something the assistant just offered to do.

    Such a message looks trivial ("yes"), so it used to take the no-tools chat shortcut, and the
    model — told it was in a quick chat — answered "I can't run that from here, switch to Agent
    mode" even in Auto mode. It is an instruction to carry out the offered action, so it must go
    to the full agent loop.
    """
    if not message:
        return False
    cleaned = message.strip().rstrip(_TRIVIAL_PUNCT).strip()
    if not (_AFFIRMATION_RE.match(cleaned) or message_is_action_approval(message)):
        return False
    for h in reversed(history or []):
        if str(h.get("role", "")).lower() != "assistant":
            continue
        text = str(h.get("content") or "").strip()
        return bool(text) and (text.endswith("?") or bool(_OFFER_RE.search(text[-400:])))
    return False


# The assistant's last words announce work it has not done yet ("Let me open
# it", "I'll read the README", "Going in now"). A short reply to that is the
# user saying "and?" — a signal to continue, never a fresh small-talk question.
_PENDING_WORK_RE = re.compile(
    r"(?:let me|let's|i'?ll|i will|i'?m going to|i am going to|going to|next,? i|"
    r"now i|on it|going in|opening|reading|checking|looking|searching)\b[^.?!]{0,120}[.…:]?\s*$",
    re.IGNORECASE,
)
_CONTINUE_MAX_WORDS = 8


def continues_prior_work(message: str, history: Optional[list[dict]] = None) -> bool:
    """A short message that follows an assistant turn which left work undone.

    "Found it and???" / "Whats wrong with you" after "Found it — let me open it"
    are shaped like conversational questions, so they took the no-tools reply
    lane and got a promise instead of the action. The previous assistant turn
    either ran tools (the task is mid-flight) or ended by announcing work; in
    both cases a short follow-up belongs to the agent loop, which can act.
    Bare thanks/greetings never reach here (they are decided as trivial first).
    """
    if not message or not history:
        return False
    if len(message.split()) > _CONTINUE_MAX_WORDS:
        return False
    for h in reversed(history):
        if str(h.get("role", "")).lower() != "assistant":
            continue
        if h.get("tool_calls"):
            return True
        text = str(h.get("content") or "").strip()
        return bool(text) and bool(_PENDING_WORK_RE.search(text[-200:]))
    return False


# ── Direct chat response helper ──────────────────────────────────────────────


def _render_conversational_todos(todo_state: Optional[list[dict]]) -> str:
    """Render the session's persisted todos for the conversational fast-path.

    "what todos are left?" routes to the conversational fast-path
    (no tool keywords, question opener). Without the real checklist the model
    would invent one — inject the persisted state so the answer is grounded.
    Returns "" when there are no todos.
    """
    if not todo_state:
        return ""
    lines = ["\nThe user's current task checklist:"]
    for t in todo_state:
        text = str(t.get("content") or t.get("text") or "").strip()
        if not text:
            continue
        status = str(t.get("status") or "").lower()
        if status not in ("pending", "in_progress", "completed", "blocked", "done"):
            status = "completed" if t.get("completed") else "pending"
        marker = {
            "completed": "[x]",
            "done": "[x]",
            "in_progress": "[~]",
            "blocked": "[!]",
            "pending": "[ ]",
        }.get(status, "[ ]")
        lines.append(f"  - {marker} {text}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def history_fallback_system_note() -> str:
    """System note for the direct-from-history fallback (the init classify
    call flaked and the answer must come straight from the conversation).

    This path used to run with a bare capability note — the ONLY agent
    surface with no user context at all. It now carries the same guarantee
    as every other surface: the boot-fused machine context and the
    user-stated identity facts (stated facts labeled; unstated declared
    absent with the ask-don't-guess rule), so a follow-up like "why did you
    say Kenya?" is answered from knowledge, not another guess.
    """
    try:
        from core.user_context import get_cached_fused_inline

        _user_line = get_cached_fused_inline()
    except Exception:
        _user_line = ""
    try:
        from core.user_profile import get_cached_profile_inline

        _about_line = get_cached_profile_inline()
    except Exception:
        _about_line = ""
    parts = [
        CAPABILITY_NOTE,
        "Answer the user's LATEST message using the conversation above. If "
        "they are questioning or correcting a previous answer, address it "
        "directly and honestly using what was actually said earlier — never "
        "reply with a generic 'tell me more'. Be concise.",
    ]
    if _user_line:
        parts.append(
            "User context (deduced from this machine's settings — use it "
            f"instead of assuming or hedging): {_user_line}"
        )
    parts.append(
        "About the user (the user's own stated facts — trust them over any "
        "inference; anything marked never stated is unknown: ask, never "
        f"guess or infer it from tool results): {_about_line}"
    )
    return " ".join(parts)


def _provider_safe_history(history: Optional[list]) -> list[dict]:
    """History reduced to the fields each role may legally carry on the wire.

    The fast path forwards the caller's history dicts to the provider, and
    those dicts also carry display metadata (``tool_calls``) on EVERY turn.
    Only an assistant turn may carry it in an OpenAI-compatible payload: a
    strict validator rejects the whole request otherwise (Cerebras 400s with
    "messages.2.user.tool_calls: property '...' is unsupported"), which killed
    every fast-path turn that followed a tool-using one. Non-conversational
    rows (system/tool) are dropped — the parent loop's own prompt builder keeps
    the same USER/ASSISTANT-only rule, and the fast path supplies its own
    system prompt.
    """
    safe: list[dict] = []
    for item in history or []:
        if isinstance(item, dict):
            role = str(item.get("role") or "").lower()
            content = item.get("content") or ""
            calls = item.get("tool_calls")
        else:
            role = str(getattr(item.role, "value", item.role) or "").lower() if hasattr(item, "role") else ""
            content = getattr(item, "content", "") or ""
            calls = getattr(item, "tool_calls", None)
        if role not in ("user", "assistant"):
            continue
        msg: dict = {"role": role, "content": content}
        if role == "assistant" and calls:
            msg["tool_calls"] = calls
        safe.append(msg)
    return safe


async def _direct_chat_response(
    message: str,
    adapter,
    history: Optional[list[dict]],
    system_prompt: str,
) -> AsyncIterator[StreamChunk]:
    """Stream a single direct chat call with a minimal system prompt."""
    # The fast path answers from the machine too: the boot-fused user
    # context (country/time zone/language) rides this ONE system prompt so
    # location-sensitive questions are deduced here instead of met with
    # "I'd need access to your location" — the machine already knows.
    try:
        from core.user_context import get_cached_fused_inline

        _user_line = get_cached_fused_inline()
    except Exception:
        _user_line = ""
    _user_suffix = (
        f"\nUser context (deduced from this machine's settings — use it instead of "
        f"assuming or hedging): {_user_line}"
        if _user_line
        else ""
    )
    # The user-STATED identity facts ride the fast path too — the guarantee
    # has no slow-path-only form. Boot-cached (zero I/O), always present:
    # unstated facts arrive declared absent with the ask-don't-guess rule.
    try:
        from core.user_profile import get_cached_profile_inline

        _about_line = get_cached_profile_inline()
    except Exception:
        _about_line = ""
    _about_suffix = (
        f"\nAbout the user (the user's own stated facts — trust them over any "
        f"inference; anything marked never stated is unknown: ask, never guess "
        f"or infer it from tool results): {_about_line}"
    )
    messages = [
        {"role": "system", "content": system_prompt + _user_suffix + _about_suffix},
    ]
    if history:
        # Include the last few turns for context. Assistant turns are stripped
        # of internal evidence-recap blocks — the model must never read that
        # format back, or it starts mimicking it into its own answers.
        messages.extend(
            strip_worker_reports_from_history(_provider_safe_history(history[-4:]))
        )

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
            # Progress from the adapter itself ("X is busy — switching to Y") reaches the UI.
            _status = getattr(chunk, "status", None)
            if isinstance(_status, str) and _status:
                yield StreamChunk(text="", done=False, status=_status)
            # Reasoning-capable models think BRIEFLY before a conversational
            # answer (a "few seconds of thought" that calibrates tone and
            # length — the same shape every mainstream agent UI shows). That
            # reasoning is the model's OWN native think on this same call, so
            # surfacing it costs zero extra round-trips; dropping it here left
            # the user staring at a silent gap while tokens were burning.
            # isinstance guard: fake adapters in tests auto-create truthy
            # MagicMock attributes; only real string reasoning forwards.
            _th = getattr(chunk, "thinking", None)
            if isinstance(_th, str) and _th:
                from core.filters import _filter_system_leaks

                _piece = _filter_system_leaks(_th)
                if _piece:
                    yield StreamChunk(text="", thinking=_piece, done=False)
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
        # Silent-failure contract: when the adapter streamed
        # ZERO text (free-tier models can return empty or reasoning-only
        # streams — the provider reports usage but never emits content), the
        # UI would show a status update with an EMPTY bubble, which reads as
        # "the message never displayed". Yield a meaningful fallback instead
        # — mirroring the agent loop's overload wording (loop.py) — so the
        # turn always ends with visible text. Normal streams are untouched.
        if not _streamed_any_text:
            if _stream_error:
                # Never embed the raw provider
                # payload in the fallback TEXT — the user previously saw
                # "zen returned 429: {…json…}" dumped into the bubble. Use
                # the canonical friendly message instead, and forward the
                # raw error on chunk.error so the SSE boundary emits the
                # canonical error object → the ErrorMessage card renders
                # (Try again / Switch model). The clean text keeps the
                # Visible-text + persistence guarantees.
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
            # Empty stream, no error (free-tier overload shape): a social
            # gesture falls back to its canned warm line so "hi" still gets
            # a hello; anything else keeps the generic retry pointer.
            _canned = _SOCIAL_REPLIES.get(trivial_intent(message))
            _fallback = _canned or (
                "I didn't get a response from the model this time — the "
                "free-tier model may be overloaded. Please try again, or "
                "switch to a faster model."
            )
            yield StreamChunk(text=_fallback, done=False, usage={"synthetic": True})
        yield StreamChunk(text="", done=True, usage=_done_usage)
    except Exception:
        # Provider unreachable mid-call: fall back to a deterministic reply
        # so the turn still ends with visible text — a social gesture gets
        # its canned warm line, anything else the generic pointer. The
        # synthetic flag marks these chunks as NOT provider data (the epilog
        # persists zeros + the flag; never fabricated token counts).
        _canned = _SOCIAL_REPLIES.get(trivial_intent(message))
        yield StreamChunk(
            text=_canned or (
                "Hi! I'm LocalMind. How can I help you?"
            ),
            done=False,
            usage={"synthetic": True},
        )
        yield StreamChunk(text="", done=True, usage={"synthetic": True})


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
    todo_state: Optional[list[dict]] = None,
    memory_facts: Optional[list[str]] = None,
) -> AsyncIterator[StreamChunk]:
    """
    Stream a reply for a trivial input (greeting/thanks/acknowledgment/...).

    The MODEL answers, always — a social gesture gets a real, brief,
    visible-think reply from the configured provider on ONE call, exactly
    like every other conversational turn. The canned strings are NOT the
    primary answer anymore: they are the degraded-path fallback when the
    provider is unreachable, so a dead/rate-limited provider still can't
    turn "hi" into an error card — but a healthy provider never answers a
    human warm-up with a hardcoded string.

    Trivial-shaped does NOT mean context-free: "ok" right after a task turn
    may be acceptance of work that must be described truthfully, and a
    gesture can carry a question. The prompt therefore grounds the reply in
    the conversation, the session's todos and stored memories, and applies
    the same honesty rule as everywhere else: speak only to what the
    evidence supports; if the gesture needs evidence the reply doesn't have,
    say what is known and what's missing — never invent a result.

    Args:
        message: the user's trivial message.
        adapter: the model adapter (already configured with the right model).
        history: optional chat history for context.
        todo_state: the session's current persisted todo list.
        memory_facts: the session's most recent stored memories.

    Yields:
        StreamChunk — the model's reply (or the canned fallback on provider
        failure), streamed token by token.
    """
    _kind = trivial_intent(message)
    todo_block = _render_conversational_todos(todo_state)
    memory_block = _render_conversational_memories(memory_facts)
    async for chunk in _direct_chat_response(
        message,
        adapter,
        history,
        system_prompt=(
            active_capability_note()
            + "The user's message is a brief social gesture "
            f"({_kind}). Reply in kind — one short warm sentence; do not "
            "launch into a capability list. Ground the reply in the "
            "conversation history, checklist, and memories below: if the "
            "gesture follows real work (acceptance, thanks for a result), "
            "your reply must match what actually happened — speak only to "
            "what that evidence supports, and if it asks something the "
            "evidence doesn't cover, say what you know and that the rest "
            "needs a real look (Agent mode), rather than inventing an "
            "answer. Do not output your reasoning process — just give the "
            "response directly."
            f"{todo_block}"
            f"{memory_block}"
        ),
    ):
        yield chunk


def _render_conversational_memories(memory_facts: Optional[list[str]]) -> str:
    """Render recent stored memories for the conversational fast-path.

    "What's it?" after "Remember the source…" died twice — the fast
    path injected todos but never memories, so referential follow-ups
    about remembered things had nothing to resolve against. Recency beats
    semantic similarity for immediate follow-ups, so the caller supplies the
    newest facts. Returns "" when there are none.
    """
    facts = [str(f).strip() for f in (memory_facts or []) if str(f).strip()]
    if not facts:
        return ""
    lines = [
        "\nThings you remember (most recent first — resolve references like "
        "'it' or 'that' against these):"
    ]
    for fact in facts:
        lines.append(f"  - {fact[:200]}")
    return "\n".join(lines)


async def conversational_response(
    message: str,
    adapter,
    history: Optional[list[dict]] = None,
    todo_state: Optional[list[dict]] = None,
    memory_facts: Optional[list[str]] = None,
    transcript_only: bool = False,
    first_user_message: str = "",
) -> AsyncIterator[StreamChunk]:
    """
    Stream a direct chat response for a conversational question.

    Same single-call fast path as `trivial_response`, with a prompt that
    asks for a natural answer to the user's question. Bypasses the parent
    agent loop — verified fix for the ~40s "What can you do?" latency.

    Args:
        message: the user's message text.
        adapter: the model adapter (already configured with the right model).
        history: optional prior messages for context.
        todo_state: the session's current persisted todo list,
            rendered into the prompt so questions like "what todos are left?"
            are answered from the real checklist, not made up.
        memory_facts: the session's most recent stored memories, so
            referential follow-ups ("What's it?") resolve against what was
            actually remembered.
        transcript_only: the question is about THIS conversation ("what did
            you reply before that?"). The answer may only come from the
            transcript above it — long-term memory is withheld, because it
            never answers a question about the chat itself and mentioning it
            produced the irrelevant four-fact dump the user called out.
        first_user_message: the first thing the user said in this session,
            quoted so "what did I ask first?" is answered, not guessed.

    Yields:
        StreamChunk — the model's direct answer, streamed token by token.
    """
    todo_block = _render_conversational_todos(todo_state)
    memory_block = "" if transcript_only else _render_conversational_memories(memory_facts)
    transcript_block = ""
    if transcript_only:
        transcript_block = (
            "THIS QUESTION IS ABOUT THE CONVERSATION ITSELF. Answer it from the "
            "recent messages above: quote what was actually said, in the words it "
            "was said. Never call a tool, never mention stored memory or a memory "
            "store, and never claim you cannot see the conversation.\n"
        )
        if first_user_message:
            transcript_block += (
                "The FIRST thing the user said in this conversation was: "
                f'"{first_user_message.strip()[:500]}"\n'
            )
        transcript_block += (
            "If the transcript above does not settle it, say what you can see and "
            "ask one short clarifying question — do not guess.\n"
        )
    async for chunk in _direct_chat_response(
        message,
        adapter,
        history,
        system_prompt=(
            active_capability_note()
            + transcript_block
            + "You are in a conversation with the user. "
            "Respond naturally and keep the flow going.\n"
            # Brevity contract for casual conversation: a wellbeing check or
            # small-talk turn gets one or two short sentences. Measured live:
            # unhedged, the model produced 89-token replies that at free-tier
            # streaming speeds dominated the turn's wall-clock.
            "Small talk, greetings, and wellbeing checks get ONE short "
            "sentence or two; substantive questions get a real but tight "
            "answer.\n"
            "CRITICAL: When the user asks a QUESTION (like 'can you switch workspace?' "
            "or 'what are you doing?'), ANSWER the question directly — do NOT take "
            "action. 'Can you switch workspace?' means 'do you have this capability?', "
            "not 'switch workspace now.' Only take action when the user gives a "
            "DIRECTIVE ('switch to the dev folder', 'create a file called X').\n"
            "Use the recent conversation history as context. Resolve short follow-ups "
            "against what was just said. Be concise, warm, and direct.\n"
            f"{todo_block}"
            f"{memory_block}"
        ),
    ):
        yield chunk
