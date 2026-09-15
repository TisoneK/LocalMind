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

# Patterns that signal a memory-read request
_READ_CUES = [
    r"\bwhat\s+do\s+you\s+(?:know|remember)\b",
    r"\blist\s+(?:all\s+|my\s+)?(?:facts?|memory|memories)\b",
    r"\bshow\s+(?:me\s+)?(?:my\s+)?memory\b",
    r"\brecall\s+(?:all|everything|what)\b",
    r"\bwhat\s+have\s+you\s+remembered\b",
]
_READ_RE = re.compile("|".join(_READ_CUES), re.IGNORECASE)

# Patterns that signal a memory-delete request
# Note: "don't forget" is a WRITE cue, NOT a delete. We only match
# "forget" as a standalone command (optionally preceded by "please"),
# not when it's part of "don't forget" / "do not forget".
_DELETE_CUES = [
    r"(?:^|\.\s+|!\s+)\s*(?:please\s+)?forget\s+",
    r"\bdelete\s+(?:that|this|my)\b",
    r"\bremove\s+(?:that|this|from\s+memory)\b",
    r"\bdon'?t\s+use\s+\S+\s+anymore\b",
    r"\bstop\s+remembering\b",
]
_DELETE_RE = re.compile("|".join(_DELETE_CUES), re.IGNORECASE)

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
        content = re.sub(
            r"^\s*(forget|delete|remove|don'?t\s+use|stop\s+remembering)\s+",
            "",
            message,
            flags=re.IGNORECASE,
        ).strip()
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
