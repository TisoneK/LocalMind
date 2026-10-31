"""
Deterministic memory-write recognition + source-knowledge extraction.

The user's diagnosis:
  > EXPLICIT MEMORY REQUESTS ARE ACTION REQUESTS,
  > NOT SUGGESTIONS FOR THE LLM TO CONSIDER.

The failure: user said "Remember the sites that gives a lot of information
so that next time we won't have to guess the links." LocalMind recognized
the memory intent, reasoned about memory_op, considered asking for
clarification, considered describe_tool, replanned, and ultimately called
ZERO tools in 65.7 seconds. It then fake-confirmed: "I'll remember it."

This module provides:
  1. MemoryWriteIntent — deterministic recognition of "remember this" cues
  2. Content extraction — what to remember (from the message + conversation context)
  3. Source-knowledge detection — when the user says "remember this site",
     extract the source from current-turn tool results, not invent general sites
  4. Memory-type classification — user_preference / user_fact / source_knowledge /
     project_decision / general

When a memory-write intent is detected, the pre-init classifier short-circuits
to a direct memory_op call — no LLM planning, no describe_tool, no replanning.
The user only sees confirmation AFTER successful persistence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MemoryOperation(Enum):
    """The type of memory operation the user is requesting."""

    WRITE = "write"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"


class MemoryType(Enum):
    """The category of memory being stored.

    Follows the user's memory taxonomy:
      Memory
      ├── User (preferences, facts, goals, corrections)
      ├── Knowledge (useful facts, source knowledge, discoveries)
      ├── Project (architecture decisions, rules, conventions)
      └── Operational (successful strategies, reliable sources, failure lessons)
    """

    USER_PREFERENCE = "user_preference"
    USER_FACT = "user_fact"
    SOURCE_KNOWLEDGE = "source_knowledge"
    PROJECT_DECISION = "project_decision"
    GENERAL = "general"


@dataclass
class MemoryWriteIntent:
    """The result of detecting a memory-write request.

    When `is_write` is True, the pre-init classifier should bypass the LLM
    and call memory_op directly with `content` and `memory_type`.

    `needs_resolution` is True when `content` is a BARE REFERENT
    ("the source for EPL table", "the score", "it") — a phrase that cannot
    be used later without the conversation's evidence. Such writes get ONE
    evidence-grounded resolution step before persisting; the confirmation
    must echo the RESOLVED fact, never the echoed phrase.
    """

    is_write: bool
    operation: MemoryOperation = MemoryOperation.WRITE
    content: str = ""  # what to remember (extracted from the message)
    memory_type: MemoryType = MemoryType.GENERAL
    is_source_knowledge: bool = False  # True when the user says "remember this site"
    source_url: Optional[str] = None  # extracted from conversation context
    source_domain: Optional[str] = None  # e.g. "weather", "sports", "news"
    raw_message: str = ""
    needs_resolution: bool = False  # bare referent → resolve against evidence first

    @property
    def is_read(self) -> bool:
        return self.operation == MemoryOperation.READ

    @property
    def is_delete(self) -> bool:
        return self.operation == MemoryOperation.DELETE


# ── Memory-write cue detection ─────────────────────────────────────────────

# Patterns that signal an explicit memory-write request
_WRITE_CUES = [
    r"^\s*remember\s+(?:that\s+|this\s+)?",
    r"^\s*remember\s+(?:the\s+)?sites?\s+",
    r"^\s*save\s+(?:this\s+|that\s+)?",
    r"^\s*store\s+(?:this\s+|that\s+)?",
    r"^\s*keep\s+(?:this\s+|that\s+)?in\s+(?:mind|memory)\b",
    r"^\s*don'?t\s+forget\s+(?:that\s+|this\s+)?",
    r"^\s*next\s+time\s+(?:remember|use|try)\b",
    r"^\s*for\s+next\s+time[,\.]?\s*remember\b",
    r"^\s*note\s+(?:that\s+|this\s+)?down\b",
    r"\bremember\s+(?:this\s+)?(?:site|website|page|source|link)\b",
    r"\bremember\s+(?:which\s+)?(?:sites?|websites?|sources?)\s+(?:give|provide|are)\b",
]
_WRITE_RE = re.compile("|".join(_WRITE_CUES), re.IGNORECASE)

# Patterns that signal a memory-read request.
#
# A read is routed straight to the store, so these patterns must mean "the
# stored facts about me" and not merely contain the words. "What do you know
# about Python?" is a general-knowledge question that must reach the model;
# "What do you know about me?" / "What do you remember?" is the store. The
# lookahead rejects an "about <anything but me/my>" tail for exactly that
# reason.
_READ_CUES = [
    r"\bwhat\s+do\s+you\s+(?:know|remember)\b(?!\s+about\s+(?!me\b|myself\b|us\b|my\s+(?:memory|memories|facts?)\b))",
    r"\blist\s+(?:all\s+|my\s+)?(?:facts?|memory|memories)\b",
    r"\bshow\s+(?:me\s+)?(?:my\s+)?memory\b",
    r"\brecall\s+(?:all\b|everything\b|(?:my\s+)?(?:memory|memories|facts?)\b)",
    r"\bwhat\s+have\s+you\s+(?:remembered|stored)\b",
]
_READ_RE = re.compile("|".join(_READ_CUES), re.IGNORECASE)

# Patterns that signal a memory-delete request.
# Note: "don't forget" is a WRITE cue, NOT a delete. We only match
# "forget" as a standalone command (optionally preceded by "please"),
# not when it's part of "don't forget" / "do not forget".
#
# Delete is the dangerous route: it is deterministic (the model never sees the
# turn), and "delete that" / "remove this" is ordinary file-and-code language.
# So a bare "delete/remove <that|this|my>" is NOT enough — the target must name
# memory itself ("delete that memory", "remove this fact from memory").
_DELETE_CUES = [
    r"(?:^|\.\s+|!\s+)\s*(?:please\s+)?forget\s+",
    r"\b(?:delete|remove)\s+(?:that|this|my|the)\s+(?:memory|memories|fact|facts|entry|entries|note|notes)\b",
    r"\b(?:delete|remove)\s+(?:that|this|it)\s+from\s+(?:my\s+)?memory\b",
    r"\bdon'?t\s+use\s+.+?\s+anymore\b",
    r"\bstop\s+remembering\b",
]
_DELETE_RE = re.compile("|".join(_DELETE_CUES), re.IGNORECASE)

# "Forget that." / "forget that, let's move on" references the PRIOR TURN —
# the demonstrative is punctuation-pinned discourse, not a named fact. These
# fall through to the model, which has the conversation and can act on it.
_DELETE_DISCOURSE_RE = re.compile(
    r"\b(?:forget|delete|remove)\s+(?:that|this|it)\b\s*[,.!?;]", re.IGNORECASE
)

# Tokens that carry no fact of their own: discourse pronouns, and the memory
# words the delete cue is built from.
_DELETE_TARGET_FILLER = frozenset(
    {
        "it",
        "that",
        "this",
        "them",
        "those",
        "these",
        "all",
        "everything",
        "anything",
        "memory",
        "memories",
        "fact",
        "facts",
        "entry",
        "entries",
        "note",
        "notes",
        "of",
        "from",
        "about",
        "my",
        "the",
        "a",
        "an",
        "and",
        "in",
    }
)


def _delete_target_names_a_fact(content: str) -> bool:
    """True when a delete target names something that could be removed.

    "Forget it" / "forget that, let's move on" drops the *topic*; "delete that
    memory" still needs its target. A deterministic delete needs a nameable
    fact, so those messages fall through to the model rather than reaching the
    store and coming back as a miss.
    """
    words = re.findall(r"[a-z0-9]+", (content or "").lower())
    return any(word not in _DELETE_TARGET_FILLER for word in words)

# Source-knowledge detection — "remember this site/website/source for X"
_SOURCE_KNOWLEDGE_CUES = [
    r"\bremember\s+(?:this|the)\s+(?:site|website|page|source|link)\b",
    r"\bremember\s+(?:which\s+)?(?:the\s+)?(?:sites?|websites?|sources?)\s+(?:that\s+)?(?:give|gives|gave|provides?|are|work)\b",
    r"\bsave\s+(?:this|the)\s+(?:site|website|source)\b",
    r"\bkeep\s+(?:this|the)\s+(?:site|website|source)\b",
    r"\bdon'?t\s+forget\s+(?:this|the)\s+(?:site|website|source)\b",
    r"\bnext\s+time\s+(?:use|try)\s+(?:this|the)\s+(?:site|website|source)\b",
]
_SOURCE_KNOWLEDGE_RE = re.compile("|".join(_SOURCE_KNOWLEDGE_CUES), re.IGNORECASE)

# Memory-type classification from the content
_PREFERENCE_CUES = [
    r"\b(?:i\s+)?prefer\b",
    r"\b(?:i\s+)?like\b",
    r"\bfavourite\b",
    r"\bfavorite\b",
    r"\balways\b",
    r"\bnever\b",
    r"\bconcise\b",
    r"\bdetailed\b",
    r"\bdark\s+(?:mode|interface|theme)\b",
    r"\blight\s+(?:mode|interface|theme)\b",
]
_PREFERENCE_RE = re.compile("|".join(_PREFERENCE_CUES), re.IGNORECASE)

_FACT_CUES = [
    r"\bi\s+(?:live|am|work|use|build|am\s+building)\b",
    r"\bmy\s+(?:name|project|app|company|stack|backend|frontend)\b",
    r"\bi'?m\s+(?:building|working|developing)\b",
]
_FACT_RE = re.compile("|".join(_FACT_CUES), re.IGNORECASE)

_PROJECT_DECISION_CUES = [
    r"\barchitecture\s+decision\b",
    r"\bwe\s+(?:decided|should|must|will)\b",
    r"\bthe\s+(?:approach|strategy|design)\s+(?:is|should\s+be)\b",
    r"\bdon'?t\s+(?:use|treat)\b.*\b(?:as\s+a|like)\b",
]
_PROJECT_DECISION_RE = re.compile("|".join(_PROJECT_DECISION_CUES), re.IGNORECASE)


def _classify_memory_type(content: str, is_source_knowledge: bool) -> MemoryType:
    """Classify the type of memory being stored."""
    if is_source_knowledge:
        return MemoryType.SOURCE_KNOWLEDGE
    if _PROJECT_DECISION_RE.search(content):
        return MemoryType.PROJECT_DECISION
    if _PREFERENCE_RE.search(content):
        return MemoryType.USER_PREFERENCE
    if _FACT_RE.search(content):
        return MemoryType.USER_FACT
    return MemoryType.GENERAL


# ── Durability: what may be remembered at all ────────────────────────────────
# MemoryType says what a fact is ABOUT. Durability is the other axis: does the
# fact stay true? Two failure modes come from conflating them — a live value
# (the machine's public IP / ISP) stored as a durable default, and the cleanup
# session that then had to hunt the stale copies down. A value that drifts on
# its own is re-derived when it is asked for, never remembered. This is policy
# in code: it must hold whatever the prompt says and whichever model runs.


class MemoryDurability(Enum):
    """Whether a fact belongs in durable storage, and how fresh it stays.

    PREFERENCE   — how the user wants things done. Durable, never drifts.
    STABLE_FACT  — true of the user/machine/project, may need a refresh
                   (locale, timezone, hardware, project name).
    VOLATILE     — live state: network identity, momentary resource readings,
                   "right now" snapshots. Never persisted as a durable default.
    """

    PREFERENCE = "preference"
    STABLE_FACT = "stable_fact"
    VOLATILE = "volatile"


@dataclass(frozen=True)
class Durability:
    """A durability verdict plus the tags a stored fact carries with it.

    `freshness` — "static" (does not drift) or "boot" (re-derived at startup,
    so a stored copy is a cache that can self-heal rather than a claim of
    permanent truth).
    `confidence` — how much the statement should be trusted as a default.
    `reason`     — plain words explaining the verdict, used when a volatile
                   fact is refused so the user hears WHY, not just "no".
    """

    kind: MemoryDurability
    freshness: str
    confidence: float
    reason: str = ""


# A remembered URL is source knowledge, not a live value — strip URLs before
# the identity checks so a stored endpoint is never read as an IP fact.
_URL_IN_TEXT_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6_RE = re.compile(r"\b(?:[0-9a-f]{1,4}:){3,}[0-9a-f]{1,4}\b", re.IGNORECASE)
_MAC_RE = re.compile(r"\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b", re.IGNORECASE)

# Network identity: who the machine is talking through changes with every
# reconnect, VPN toggle, or carrier reassignment.
_VOLATILE_INFRA_RE = re.compile(
    r"\b(?:isp|internet service provider|broadband provider|carrier|public ip"
    r"|external ip|assigned ip|dynamic ip|ip address|vpn exit|dns server)\b",
    re.IGNORECASE,
)
# Momentary machine state: true only while it is being read.
_VOLATILE_LIVE_RE = re.compile(
    r"\b(?:battery (?:level|percentage|charge|state)|charging now"
    r"|free (?:ram|memory|disk|space)|available (?:ram|memory|disk|space)"
    r"|cpu (?:load|usage|temperature)|uptime|running processes"
    r"|ambient temperature|weather right now|what am i running)\b",
    re.IGNORECASE,
)
# Explicitly framed as momentary. Checked after the preference markers so
# "I prefer concise answers right now" stays a preference.
_VOLATILE_MOMENT_RE = re.compile(
    r"\b(?:right now|at the moment|for now|this session|currently (?:using|running|at|on))\b",
    re.IGNORECASE,
)
# Facts that are true of the user/environment but can be re-derived at startup.
_STABLE_REFRESH_RE = re.compile(
    r"\b(?:i (?:live|am based|am located)|my (?:city|country|town|timezone|time zone"
    r"|locale|region|machine|workstation|laptop|desktop)\b|local time|utc ?[+-]?\d|gmt\b)",
    re.IGNORECASE,
)

_VOLATILE_FRESHNESS_REASON = (
    "it is live state that changes on its own (network identity and momentary "
    "readings are wrong as soon as they are written down)"
)


def _volatile(freshness_reason: str) -> Durability:
    """One verdict shape for every volatile rule — never persisted."""
    return Durability(
        MemoryDurability.VOLATILE,
        freshness="on_demand",
        confidence=0.0,
        reason=f"{freshness_reason} and {_VOLATILE_FRESHNESS_REASON}",
    )


def durability_profile(content: str) -> Durability:
    """Decide whether a fact may be persisted, and with which freshness tags.

    Rules run in a fixed order so the verdict is predictable: hard live-value
    shapes first (an IP literal, ISP, a battery reading), then preference
    wording, then explicit "right now" framing, then refreshable environment
    facts, and finally a durable fact by default. Only wildly-shaped live
    values are refused — a false positive would reject something the user
    explicitly asked to keep.
    """
    text = (content or "").strip()
    if not text:
        return Durability(MemoryDurability.STABLE_FACT, "static", 0.5)

    without_urls = _URL_IN_TEXT_RE.sub(" ", text)

    if _IPV4_RE.search(without_urls):
        return _volatile("it is an IP address")
    if _MAC_RE.search(without_urls) or _IPV6_RE.search(without_urls):
        return _volatile("it is a network address")
    if _VOLATILE_INFRA_RE.search(without_urls):
        return _volatile("your network provider changes with every reconnect")
    if _VOLATILE_LIVE_RE.search(without_urls):
        return _volatile("it is a live reading of the machine")

    if _PREFERENCE_RE.search(text):
        return Durability(MemoryDurability.PREFERENCE, "static", 0.9)

    if _VOLATILE_MOMENT_RE.search(without_urls):
        return _volatile("it is described as momentary")

    if _STABLE_REFRESH_RE.search(text):
        # Stored, but tagged as re-derivable: the value can be refreshed on a
        # later boot instead of being treated as a permanent claim.
        return Durability(MemoryDurability.STABLE_FACT, "boot", 0.7)

    return Durability(MemoryDurability.STABLE_FACT, "static", 0.6)


# ── Fact identity: one row per fact, whatever the wording ────────────────────

_KEY_STOPWORDS = frozenset(
    {
        "a", "an", "the", "my", "me", "i", "im", "i'm", "is", "are", "was", "be",
        "of", "to", "and", "or", "for", "with", "that", "this", "it", "in", "on",
        "at", "as", "by", "from", "user", "users", "you", "your", "please", "just",
    }
)

# Subjects that describe ONE thing, so two statements about them are the same
# fact and must land on the same row. Anything else falls back to its leading
# content words — deliberately conservative, because collapsing two unrelated
# preferences into one row would lose data.
_SINGLE_VALUED_SUBJECTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:live|living|based|located|hometown|city|country|town|region)\b", re.IGNORECASE), "location"),
    (re.compile(r"\b(?:time ?zone|utc|gmt)\b", re.IGNORECASE), "timezone"),
    # Both voices: facts reach the store BOTH first-person ("my name is …", how
    # the user says it) and third-person ("User's name is …", how the memory
    # tool writes it back). Only the first-person forms were listed, so a
    # correction written in the third person hashed to a CONTENT-derived key
    # ("fact:s-name-tisone") and sat next to the fact it was meant to replace —
    # two name facts, one calling the pronunciation "tee-SONE", the other
    # "Tyson", each contradicting the other on every recall. Field report,
    # 2026-10-31: "it created another memory on top of another memory".
    (re.compile(
        r"\b(?:my name|call me|i am called|i'm called"
        r"|user'?s name|user is (?:called|named)"
        r"|prefers? to be (?:called|addressed|known as))\b",
        re.IGNORECASE,
    ), "name"),
    (re.compile(r"\b(?:e-?mail)\b", re.IGNORECASE), "email"),
    (re.compile(r"\b(?:phone|mobile) (?:number|no)\b", re.IGNORECASE), "phone"),
    (re.compile(r"\b(?:company|employer|works? (?:at|for))\b", re.IGNORECASE), "employer"),
)


def canonical_key(content: str, max_words: int = 6, subject_hint: str | None = None) -> str:
    """A deterministic identity for a fact, independent of embeddings.

    The store dedups paraphrases by vector distance, but that only works while
    the embedding backend answers — the degraded plain-text path used to append
    a new row per write. A key hashed into the row id gives every fact a stable
    identity that survives restarts, backend changes, and re-phrasing, so
    re-stating it replaces the row instead of accumulating near-copies.

    Single-valued subjects (location, timezone, name, email, phone, employer)
    map to a named subject key; everything else uses its leading content words.

    `subject_hint` lets the caller assert the subject when the statement's own
    wording doesn't carry it ("I'm in Nairobi this week" says where the user
    IS without saying "live"). The hint lands on the same single-valued row as
    an explicitly-worded statement of that subject, so a casual restatement
    replaces the row instead of accumulating a near-copy.
    """
    text = (content or "").strip()
    if not text:
        return "fact:empty"

    for pattern, subject in _SINGLE_VALUED_SUBJECTS:
        if pattern.search(text):
            return f"subject:{subject}"

    if subject_hint:
        return f"subject:{subject_hint}"

    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _KEY_STOPWORDS]
    if not words:
        return f"fact:{abs(hash(text)) % (10**12)}"
    return "fact:" + "-".join(words[:max_words])


# ── Deterministic content extraction ────────────────────────────────────────
# The memory-cue prefix strip. Two forms consume the cue:
#   verb + space + optional ("two things:" / "this:") → "Remember this: X"
#   verb + colon directly                                          → "Remember: X"
# The old form required whitespace after the demonstrative, so
# "Remember this: X" survived extraction and the framing was persisted
# verbatim as the fact; a quantified "things" tail ("Remember two things:
# X and Y") is the same disease in batch-8 — stripped ONLY when punctuation
# follows it, so "the two things that matter for the deploy" stays intact.
_QUANTIFIERS = (
    r"one|two|three|four|five|six|seven|eight|nine|ten|several|both|\d+"
    r"|a couple of|a few|these|those"
)
_CUE_PREFIX_RE = re.compile(
    r"^\s*(?:remember|save|store|keep in mind|don'?t forget|note down)"
    r"(?:\s+(?:(?:" + _QUANTIFIERS + r")?\s*things?\s*[:;,]\s+"  # "… two things: X"
    r"|(?:that|this|these|those|the)\s*[:;,]?\s+)?"  # "remember this: X"
    r"|\s*[:;,]\s+)",  # bare "remember: X" — keep a leading article intact
    re.IGNORECASE,
)

# A trailing assistant-directed instruction ("Just acknowledge.", "No reply
# needed.") is framing, not durable content. Stripped only at a sentence
# boundary, and `_extract_content` never lets it empty the fact.
_TRAILING_IMPERATIVE_RE = re.compile(
    r"(?:^|(?<=[.!?]))\s*"
    r"(?:just\s+|only\s+|simply\s+|please\s+)?"
    r"(?:acknowledge|confirm|reply|respond|say|note)(?:\s+only)?\b"
    r"[^.!?]*[.!?]*\s*$",
    re.IGNORECASE,
)


def _extract_content(message: str) -> str:
    """Extract the content to remember from the user's message.

    Strips the memory-write cue prefix and returns the remaining content.
    For "remember that I prefer concise answers" → "I prefer concise answers"
    For "remember the sites that give a lot of information" → "sites that give a lot of information"
    For "remember this: my project is called Falcon. Just acknowledge." →
    "my project is called Falcon" — the cue demonstrative survives a colon
    ("this:") and the trailing imperative is a framing instruction, not the
    fact (live echo artifact: "Remembered: *this: … Just acknowledge*").
    For "remember two things: X and Y" → "X and Y" — the quantified
    "things:" tail is framing too; it is stripped only when punctuation
    follows ("two things matter for the deploy" keeps every word).
    """
    # Strip common prefixes
    content = message.strip()
    # Remove leading "remember that" / "remember this" / "save this" etc.,
    # tolerating punctuation after the verb and after the demonstrative
    # ("Remember this:" / "Remember:").
    content = _CUE_PREFIX_RE.sub("", content, count=1)
    # Remove "next time remember" prefix
    content = re.sub(
        r"^\s*(?:for\s+)?next\s+time[,\.]?\s*remember\s+(?:that\s+|to\s+)?",
        "",
        content,
        flags=re.IGNORECASE,
    )
    # Floor: drop a trailing assistant-directed imperative sentence ("Just
    # acknowledge.") — it's framing, not durable content. Only after a
    # sentence boundary, and only while a fact survives ahead of it.
    while True:
        stripped = _TRAILING_IMPERATIVE_RE.sub("", content).strip()
        if not stripped or stripped == content:
            break
        content = stripped
    # Clean up
    content = content.strip().rstrip(".").strip()
    # If the content starts with "so that" / "so we won't", it's a reason clause
    # — keep it as part of the content for context
    return content


def extract_memory_content(message: str) -> str:
    """Public handle on the deterministic cue extractor (memory write paths)."""
    return _extract_content(message)


# ── Referential-content detection ─────────────────────────────────────
# A memory write whose content is a BARE REFERENT ("the source for EPL table",
# "the score", "it") cannot be used later — the fact only exists in the
# conversation's evidence. Live proof: "Remember the source for EPL
# table" stored the literal phrase "source for EPL table" and confirmed it;
# the URL the user meant was in the turn-1 context. Such writes MUST be
# resolved against the conversation before persisting. Self-contained
# content (URLs, paths, dates, quoted strings, complete statements) keeps
# the zero-LLM deterministic write — the speed win stays where it works.

_CONCRETE_PAYLOAD_RE = re.compile(
    r"https?://|www\."                                       # URLs
    r"|\b[\w.+-]+@[\w-]+\.[\w.]+\b"                          # emails
    r"|[/\\][\w.-]+(?:[/\\][\w.-]+)+"                        # filesystem paths
    r"|\b\d{1,3}(?:\.\d{1,3}){3}\b"                          # IPv4 addresses
    r"|\b\d+(?:[.,]\d+)?\s*(?:%|kb|mb|gb|tb|kg|km|mi|lbs?|usd|kes|eur|sh|\$)"  # number+unit
    r"|\"[^\"]{3,}\"|'[^']{3,}'"                             # quoted strings
    r"|\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b",                 # numeric dates
    re.IGNORECASE,
)

# Bare determiner openings and pronoun referents — "the source", "this site",
# "that score", "it". First-person openers (I/we/my/our) are usually
# self-contained statements and are handled by the verb check below.
_BARE_REFERENT_RE = re.compile(
    r"^(?:the|a|an|this|that|these|those)\b"
    r"|\b(?:it|that one|this one|the above|the same)\b",
    re.IGNORECASE,
)

_FIRST_PERSON_RE = re.compile(r"^(?:i|we|my|our)\b", re.IGNORECASE)

# A statement verb marks complete, usable-on-its-own content ("I prefer
# concise answers", "sites that give a lot of information") — the
# original examples, which persist fine as the user's words.
_STATEMENT_VERB_RE = re.compile(
    r"\b(?:is|are|was|were|be|prefer|prefers|liked?|likes?|us(?:e|es|ed)|"
    r"wants?|needs?|gives?|gave|provides?|provided|works?|worked|should|must|"
    r"will|has|have|had|lives?|builds?|building|am|runs?|running)\b",
    re.IGNORECASE,
)


def needs_resolution(content: str, is_source_knowledge: bool = False) -> bool:
    """True when the extracted content is a bare referent that must be
    resolved against conversation evidence before it is stored.

    The contract (user directive): memory should understand what the
    user wants remembered, ground it in the conversation's evidence, and
    distill it into a self-contained one-liner — never store the user's
    words when those words only name a referent.
    """
    content = (content or "").strip()
    if not content:
        return False
    # Concrete payload → usable as-is regardless of phrasing.
    if _CONCRETE_PAYLOAD_RE.search(content):
        return False
    # Source-knowledge noun phrases ("the source for EPL table", "this
    # site", "source for the youth program") always need evidence — the
    # phrase names a referent, not a fact. General capability statements
    # ("sites that give a lot of information") carry a verb and fall through
    # to the statement check below (they persist as the
    # user's words).
    if is_source_knowledge and not _STATEMENT_VERB_RE.search(content):
        return True
    # Complete statements persist as-is (behavior preserved).
    if _STATEMENT_VERB_RE.search(content):
        return False
    if _BARE_REFERENT_RE.search(content):
        return True
    # Short noun phrase with no verb and no payload — "my project folder",
    # "the score" — unusable without its antecedent.
    return len(content.split()) <= 6


def _detect_source_domain(message: str) -> Optional[str]:
    """Detect what information domain the source knowledge is about.

    For "remember this site for weather" → "weather"
    For "remember the sites that give a lot of information" → None (too generic)
    """
    lower = message.lower()
    domain_patterns = {
        "weather": [r"\bweather\b", r"\btemperature\b", r"\bforecast\b"],
        "sports": [r"\bsports?\b", r"\bstandings?\b", r"\bscores?\b", r"\bEPL\b", r"\bpremier\s+league\b"],
        "news": [r"\bnews\b", r"\bheadlines\b", r"\btrending\b"],
        "finance": [r"\bprice\b", r"\bstock\b", r"\bexchange\s+rate\b"],
        "documentation": [r"\bdocs?\b", r"\bdocumentation\b", r"\bAPI\s+reference\b"],
    }
    for domain, patterns in domain_patterns.items():
        for p in patterns:
            if re.search(p, lower):
                return domain
    return None


def classify_memory_intent(message: str) -> MemoryWriteIntent:
    """Classify whether the user's message is a memory operation.

    This is the deterministic guard that runs BEFORE the LLM init call.
    When it detects an explicit memory-write request, the pre-init classifier
    should bypass the LLM and call memory_op directly.

    The user's principle:
      > EXPLICIT MEMORY REQUESTS ARE ACTION REQUESTS,
      > NOT SUGGESTIONS FOR THE LLM TO CONSIDER.
    """
    if not message or not message.strip():
        return MemoryWriteIntent(is_write=False, raw_message=message or "")

    # Check for delete first (most specific)
    if _DELETE_RE.search(message):
        # Strip the cue verb AND the discourse demonstratives that can ride
        # right behind it ("forget THAT I prefer dark mode"). The demonstrative
        # is part of the sentence, not of the stored fact — leaving it in made
        # the deterministic target "that I prefer dark mode", whose signature
        # can never match the stored "I prefer dark mode", so the delete
        # always reported a miss on the most natural phrasing.
        content = re.sub(
            r"^\s*(forget|delete|remove|don'?t\s+use|stop\s+remembering)\s+"
            r"(?:(?:that|this|it|them|about|the\s+fact\s+that)\s+)*",
            "",
            message,
            flags=re.IGNORECASE,
        ).strip()
        # A demonstrative pinned by punctuation ("forget that, let's move on")
        # references the prior turn — the model owns it, not the store.
        if _DELETE_DISCOURSE_RE.search(message):
            pass  # fall through to read/write checks below
        # Only a target that actually names a fact is a store deletion; a
        # discourse marker is a topic change, not a memory operation.
        elif _delete_target_names_a_fact(content):
            return MemoryWriteIntent(
                is_write=False,
                operation=MemoryOperation.DELETE,
                content=content,
                raw_message=message,
            )

    # Check for read
    if _READ_RE.search(message):
        return MemoryWriteIntent(
            is_write=False,
            operation=MemoryOperation.READ,
            raw_message=message,
        )

    # Check for write
    if _WRITE_RE.search(message):
        is_source_knowledge = bool(_SOURCE_KNOWLEDGE_RE.search(message))
        content = _extract_content(message)
        memory_type = _classify_memory_type(content, is_source_knowledge)
        source_domain = _detect_source_domain(message) if is_source_knowledge else None

        return MemoryWriteIntent(
            is_write=True,
            operation=MemoryOperation.WRITE,
            content=content,
            memory_type=memory_type,
            is_source_knowledge=is_source_knowledge,
            source_domain=source_domain,
            raw_message=message,
            needs_resolution=needs_resolution(content, is_source_knowledge),
        )

    return MemoryWriteIntent(is_write=False, raw_message=message)


# ── Memory candidate extraction (lightweight, post-turn) ───────────────────
#
# The user's broader vision:
#   > LocalMind should identify, evaluate, store, update, and retrieve
#   > useful information autonomously, while avoiding noisy or stale memory.
#
# This is a lightweight candidate extractor that identifies durable information
# from the conversation without requiring the user to explicitly say "remember."
# It's called AFTER the turn completes, not before.


@dataclass
class MemoryCandidate:
    """A potential memory item extracted from the conversation.

    Not all candidates are stored — the evaluator decides based on
    importance, durability, and usefulness.
    """

    content: str
    memory_type: MemoryType
    confidence: float = 0.5  # 0.0-1.0 — how confident this is worth storing
    durability: str = "persistent"  # "persistent" / "session" / "ephemeral"
    source: str = "conversation"  # "conversation" / "tool_outcome" / "user_correction"
    importance: float = 0.5  # 0.0-1.0


# Cues that signal a correction (high-priority memory candidate)
_CORRECTION_CUES = [
    r"\bno[,\.]?\s+(?:that'?s\s+not|you'?re\s+wrong|i\s+disagree)\b",
    r"\bdon'?t\s+(?:do\s+that|use\s+that\s+approach|treat)\b",
    r"\bactually,?\s+(?:change|don'?t|no)\b",
    r"\bthat'?s\s+(?:wrong|incorrect|not\s+right)\b",
    r"\bi\s+(?:didn'?t\s+mean|don'?t\s+want)\b",
    # Broadened: "No, X is Y, not Z" — a common correction pattern
    r"^\s*no[,\.]?\s+\S+.{0,40}\bnot\s+(?:a|an|the)\b",
    r"\bnot\s+(?:a\s+)?(?:fallback|last\s+resort|recovery)\b",
]
_CORRECTION_RE = re.compile("|".join(_CORRECTION_CUES), re.IGNORECASE)

# Cues that signal a preference (medium-priority candidate)
_AUTONOMOUS_PREFERENCE_CUES = [
    r"\bi\s+prefer\b",
    r"\bi\s+like\b",
    r"\bi\s+(?:always|usually|typically)\s+(?:use|want|need)\b",
    r"\bkeep\s+(?:it\s+)?(?:short|concise|brief)\b",
    r"\bkeep\s+(?:it\s+)?(?:detailed|thorough|comprehensive)\b",
]
_AUTONOMOUS_PREFERENCE_RE = re.compile("|".join(_AUTONOMOUS_PREFERENCE_CUES), re.IGNORECASE)

# Cues that signal temporary/ephemeral information (should NOT be stored)
_EPHEMERAL_CUES = [
    r"\bi'?m\s+(?:having|eating|going\s+to|about\s+to)\b",
    r"\bright\s+now\s+i'?m\b",
    r"\btoday\s+i\b",
    r"\bjust\s+(?:finished|done|completed)\b",
]
_EPHEMERAL_RE = re.compile("|".join(_EPHEMERAL_CUES), re.IGNORECASE)


def extract_memory_candidates(
    user_message: str,
    assistant_response: str = "",
    tool_results: Optional[list[str]] = None,
) -> list[MemoryCandidate]:
    """Extract memory candidates from a conversation turn.

    This is a lightweight heuristic extractor — not a full NLP pipeline.
    It identifies:
      - Corrections (high priority — architectural decisions, rules)
      - Preferences (medium priority — user likes/uses/prefers)
      - Source knowledge (from successful tool outcomes)
      - Facts (user's location, project, stack)

    It explicitly REJECTS:
      - Ephemeral information ("I'm having lunch")
      - Casual conversation ("How's it going?")
      - Tool output that is just data (weather readings, scores)

    The user's principle:
      > Will retaining this information make future reasoning,
      > decisions, or interactions meaningfully better?
    """
    candidates: list[MemoryCandidate] = []

    if not user_message:
        return candidates

    # Reject ephemeral information
    if _EPHEMERAL_RE.search(user_message):
        return candidates  # don't store "I'm having lunch"

    # 1. Corrections — highest priority
    if _CORRECTION_RE.search(user_message):
        candidates.append(MemoryCandidate(
            content=user_message[:500],
            memory_type=MemoryType.PROJECT_DECISION,
            confidence=0.85,
            durability="persistent",
            source="user_correction",
            importance=0.9,
        ))

    # 2. Autonomous preferences (not "remember this" — just stated preferences)
    if _AUTONOMOUS_PREFERENCE_RE.search(user_message):
        # Extract the preference sentence
        sentences = re.split(r"[.!?]+", user_message)
        for sent in sentences:
            if _AUTONOMOUS_PREFERENCE_RE.search(sent):
                candidates.append(MemoryCandidate(
                    content=sent.strip()[:300],
                    memory_type=MemoryType.USER_PREFERENCE,
                    confidence=0.7,
                    durability="persistent",
                    source="conversation",
                    importance=0.7,
                ))
                break  # one preference per turn is enough

    # 3. User facts (location, project, stack)
    if _FACT_RE.search(user_message):
        sentences = re.split(r"[.!?]+", user_message)
        for sent in sentences:
            if _FACT_RE.search(sent):
                candidates.append(MemoryCandidate(
                    content=sent.strip()[:300],
                    memory_type=MemoryType.USER_FACT,
                    confidence=0.6,
                    durability="persistent",
                    source="conversation",
                    importance=0.6,
                ))
                break

    # 4. Source knowledge from tool results
    if tool_results:
        for result in tool_results:
            # Check if a web_fetch/web_research succeeded with good content
            if isinstance(result, str) and ("http" in result.lower() or "source:" in result.lower()):
                # Extract URL
                url_match = re.search(r"https?://[^\s\n]+", result)
                if url_match:
                    url = url_match.group(0).rstrip(".,;\"')")
                    # Extract domain for categorization
                    domain_match = re.search(r"https?://(?:www\.)?([^/]+)", url)
                    domain = domain_match.group(1) if domain_match else "unknown"
                    candidates.append(MemoryCandidate(
                        content=(
                            f"Source {domain} ({url}) provided useful information. "
                            "Consider this source for future queries in the same domain."
                        ),
                        memory_type=MemoryType.SOURCE_KNOWLEDGE,
                        confidence=0.6,
                        durability="persistent",
                        source="tool_outcome",
                        importance=0.5,
                    ))
                    break  # one source per turn

    return candidates


def should_store_candidate(candidate: MemoryCandidate) -> bool:
    """Decide whether a memory candidate should be persisted.

    The user's decision model:
      > Is it meaningful?
      > Is it durable?
      > Is it useful later?

    Corrections and preferences are always stored (high signal).
    Facts are stored (medium signal).
    Source knowledge is stored (medium signal — helps future acquisition).
    General conversation is NOT stored (low signal).
    """
    if candidate.durability == "ephemeral":
        return False
    if candidate.importance < 0.4:
        return False
    # Corrections are always worth storing
    if candidate.source == "user_correction":
        return True
    # Preferences are worth storing
    if candidate.memory_type == MemoryType.USER_PREFERENCE:
        return True
    # Source knowledge is worth storing (connects to web acquisition)
    if candidate.memory_type == MemoryType.SOURCE_KNOWLEDGE:
        return True
    # Facts are worth storing
    if candidate.memory_type == MemoryType.USER_FACT:
        return True
    # Project decisions are worth storing
    if candidate.memory_type == MemoryType.PROJECT_DECISION:
        return True
    # General — only if importance is high enough
    return candidate.importance >= 0.7


# ── Passive context awareness (conversation-signal half of the user profile) ──
#
# The boot-deduced profile (core/user_context.py) covers what the MACHINE
# knows: country, timezone, locale. The other half of the profile is what the
# USER says in passing — "I work at Acme Corp", "My name is Tisone" — facts
# that arrive inside ordinary conversation with no "remember this" trigger.
# This pass extracts those from the user's message after the turn, so the
# second time the user mentions their work the agent already knows.
#
# Policy constraints (backlog -3 / -4): the durability gate and the keyed
# identity stay the ONLY accept/refuse authorities — extraction proposes,
# the write path disposes. Mechanics: one candidate per fact with a subject
# hint so the keyed write lands on the same row as an explicit statement.


@dataclass
class PassiveCandidate:
    """A durable self-fact stated incidentally (no explicit memory cue).

    `subject_hint` — the single-valued subject the statement is about
    ("location"), when the extractor can tell but the WORDING doesn't say it
    ("I'm in Nairobi" carries no "live"). Feeds canonical_key so the write
    lands on the same row as an explicitly-worded statement.
    """

    content: str
    memory_type: MemoryType = MemoryType.USER_FACT
    subject_hint: str = ""


# Where the user is / is from. Worded tightly: "I'm in Nairobi" (a statement
# about the speaker), not "is it in Nairobi?" (a question about a thing).
_LOCATION_CUES = [
    r"\bi(?:'m| am)\s+(?:currently\s+)?(?:in|at|from|near)\b",
    r"\bi\s+(?:live|lived|am\s+stationed|am\s+posted)\s+(?:in|at|near)\b",
    r"\bi(?:'m| am)\s+(?:living|based)\s+(?:in|at|near)\b",
    r"\bmy\s+(?:office|home|place|apartment|house|flat)\s+is\s+(?:in|at|near)\b",
    r"\bwe(?:'re| are)\s+(?:in|at|based\s+in|moving\s+to|relocating\s+to)\b",
]
_LOCATION_RE = re.compile("|".join(_LOCATION_CUES), re.IGNORECASE)

# Who the user is: name, occupation, field of study.
_IDENTITY_CUES = [
    r"\bmy\s+name\s+is\b",
    r"\bcall\s+me\b",
    r"\bi\s+work\s+(?:as|at|for|in|on)\b",
    r"\bi(?:'m| am)\s+(?:a|an)\s+[a-z]",
    r"\bi\s+study\s+[a-z]",
    r"\bi(?:'m| am)\s+studying\s+[a-z]",
]
_IDENTITY_RE = re.compile("|".join(_IDENTITY_CUES), re.IGNORECASE)

# Work / project context that shapes future collaboration.
_ENVIRONMENT_CUES = [
    r"\bmy\s+(?:team|company|employer|startup|project)\s+(?:is|is\s+called|consists)\b",
    r"\bwe\s+(?:build|make|ship|develop)\b",
    r"\bi\s+(?:run|own|manage)\s+(?:a|an|the)\b",
]
_ENVIRONMENT_RE = re.compile("|".join(_ENVIRONMENT_CUES), re.IGNORECASE)

# Hypothetical / conditional framing — never a fact about the user.
_HYPOTHETICAL_RE = re.compile(
    r"^(?:if|when|whether|what\s+if|maybe|perhaps|suppose|imagine|should)\b",
    re.IGNORECASE,
)

# Time-boxed framing: true of a PERIOD, not of the user. This is the single
# most misleading thing the passive path could persist — "I'm in Nairobi this
# week" stored as a location fact would override the boot-deduced (and every
# later) default long after the week ended.
_TIME_BOXED_RE = re.compile(
    r"\b(?:this|next|last)\s+(?:week|month|year|weekend|summer|winter|spring|fall|autumn|semester|quarter|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
    r"|\b(?:today|tonight|tomorrow)\b",
    re.IGNORECASE,
)


_PASSIVE_CUE_SETS: tuple[tuple[re.Pattern[str], MemoryType, str], ...] = (
    (_LOCATION_RE, MemoryType.USER_FACT, "location"),
    (_IDENTITY_RE, MemoryType.USER_FACT, ""),
    (_ENVIRONMENT_RE, MemoryType.USER_FACT, ""),
)


def extract_passive_facts(message: str) -> list[PassiveCandidate]:
    """Extract durable self-facts stated incidentally from a user message.

    One per matching sentence, capped at two per message, and NOTHING when
    the message is ephemeral small talk ("I'm having lunch"), a hypothetical
    ("If I move to Nairobi…"), or time-boxed ("I'm in Nairobi this week" —
    rejected at extraction, not stored, so a period-statement can never
    masquerade as a durable trait).
    """
    text = (message or "").strip()
    if not text:
        return []
    if _EPHEMERAL_RE.search(text):
        return []

    candidates: list[PassiveCandidate] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        sentence = sentence.strip()
        words = sentence.split()
        if len(words) < 3 or len(words) > 60:
            continue
        if _HYPOTHETICAL_RE.search(sentence):
            continue
        if _TIME_BOXED_RE.search(sentence):
            continue
        for cue_re, memory_type, subject in _PASSIVE_CUE_SETS:
            if cue_re.search(sentence):
                candidates.append(
                    PassiveCandidate(
                        content=sentence.rstrip(".,;!"),
                        memory_type=memory_type,
                        subject_hint=subject,
                    )
                )
                break
        if len(candidates) >= 2:
            break
    return candidates
