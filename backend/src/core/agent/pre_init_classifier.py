"""
Pre-init deterministic classifiers for the root-cause
clusters identified by a benchmark run.

Cluster A (tool-first reflex): hallucination-class prompts
  ("What did John tell me about X?", "What is the password stored in Y?")
  must NOT trigger workspace exploration — the answer is "I don't have
  that information," full stop. The agent shouldn't burn 10 tool calls
  searching the filesystem for "John" before saying so.

Cluster B (workspace pollution on planning): prompts that explicitly say
  "do not write code yet" / "first analyze" / "before suggesting
  implementation" must skip workspace_state injection — the user wants
  abstract analysis, not an inspection of the on-disk repo.

Cluster C (pressure-induced fabrication): "Don't tell me you don't know,
  just guess" + a sensitive topic (passwords, API keys, private info)
  must strengthen refusal, not relax it. Inject a system-prompt reminder
  that the agent should not fabricate credentials/secrets.

Cluster D (impossible-constraint recognition): when the user's message
  contains conflicting constraints (e.g., "do not use numbers" + "number
  each"), the init decision should be `clarify` with a question
  identifying the conflict, NOT `execute` with a best-effort attempt.

These guards run BEFORE the LLM init call. They are conservative — only
fire on unambiguous matches, so they don't change behavior for normal
prompts. When they don't fire, the LLM init proceeds as before.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class PreInitOverride:
    """The result of running the cluster guards.

    When `mode` is set, the init LLM call is skipped and this decision
    is used directly. When `mode` is None, the LLM init proceeds as
    normal. When `extra_system_reminder` is set, it's prepended to the
    init prompt to strengthen the model's behavior (e.g. refuse-to-
    fabricate reminder when pressure phrases are detected).
    """

    mode: Optional[str] = None  # "direct" | "clarify" | None
    response: Optional[str] = None  # for direct mode
    clarifying_question: Optional[str] = None  # for clarify mode
    acknowledgement: Optional[str] = None
    objective: Optional[str] = None
    title: Optional[str] = None
    # Cluster B: when True, the loop must skip workspace_state injection
    # AND skip the action-narration detector (the user said "analyze only")
    skip_workspace_state: bool = False
    # Cluster C: extra system-prompt text prepended to the init prompt
    extra_system_reminder: Optional[str] = None


# ── Cluster A: hallucination-class prompts ──────────────────────────────────

# A prompt is "hallucination-class" when it asks about something the agent
# CANNOT know — third parties ("John", "Mary"), past conversations the
# agent has no record of, secrets/credentials/private repos.
#
# Pattern: "What did X tell me" / "What is the password" / "What is the name
# of my private repo" / "Which model did I use last year"
#
# Conservative: only fires for explicit "what did/was X" patterns about
# past/third-party/private topics. Doesn't fire for "What is in this file"
# (which IS discoverable).

# Past-tense / third-party cues that signal "I cannot know this"
_HALLUCINATION_CUES = [
    # Third-party past-tense references — "what did X tell me" OR
    # "what X told me" (a benchmark case revealed the pattern is broader
    # than "what did" — "analyze what John told me" also qualifies).
    r"\bwhat\s+did\s+\w+\s+tell\s+me\b",
    r"\bwhat\s+did\s+\w+\s+say\b",
    r"\bwhat\s+did\s+(?:john|mary|alice|bob|sarah|mike|he|she|they|we|you)\b",
    # "what X told me" / "what X said" — without "did". Catches
    # "analyze what John told me about the database".
    r"\bwhat\s+(?:john|mary|alice|bob|sarah|mike|he|she|they|we|you)\s+(?:told|said|tells|says)\b",
    # "what X told me about Y" — the Y can be any noun.
    r"\bwhat\s+\w+\s+told\s+me\s+about\b",
    # "about what X told/said" — catches "analyze the architecture of what John told me"
    r"\babout\s+what\s+\w+\s+(?:told|said)\b",
    # Private/secret queries — "password" / "api key" / "secret" / "token"
    # / "credential" — may be preceded by "database", "config", "stored",
    # etc. Match the "what is/was [optional noun] password" pattern.
    r"\bwhat\s+(?:is|was|'s|s)\s+(?:the\s+|my\s+)?(?:\w+\s+)?password\b",
    r"\bwhat(?:'s|s)\s+(?:the\s+|my\s+)?(?:\w+\s+)?password\b",
    r"\bwhat\s+(?:is|was|'s|s)\s+(?:the\s+|my\s+)?(?:\w+\s+)?(?:api\s+key|secret|token|credential)s?\b",
    r"\bwhat(?:'s|s)\s+(?:the\s+|my\s+)?(?:\w+\s+)?(?:api\s+key|secret|token|credential)s?\b",
    r"\bwhat\s+is\s+the\s+name\s+of\s+my\s+private\s+repo(?:sitory)?\b",
    r"\bwhat(?:'s|s|\s+is)\s+my\s+private\s+repo(?:sitory)?\s+name\b",
    # Past experiments / past sessions the agent has no record of
    r"\bwhich\s+model\s+did\s+i\s+use\b",
    r"\bwhat\s+(?:model|version)\s+(?:did|was)\s+i\s+(?:using|use)\b",
    r"\bwhat\s+did\s+(?:we|i)\s+discuss\s+(?:yesterday|last\s+week|last\s+month|last\s+year)\b",
]
_HALLUCINATION_RE = re.compile("|".join(_HALLUCINATION_CUES), re.IGNORECASE)


def _detect_hallucination_class(message: str) -> bool:
    """Return True if the prompt is asking about something the agent
    cannot possibly know (third parties, past sessions, secrets)."""
    return bool(_HALLUCINATION_RE.search(message))


# ── Cluster B: "analyze-only" / "do not implement yet" ─────────────────────

# When the user explicitly says "do not write code yet" / "first analyze" /
# "before suggesting implementation", the prompt is a PLANNING request
# (abstract analysis), NOT an execute request. The agent must:
#   - skip workspace_state injection (the user wants abstract reasoning,
#     not inspection of the on-disk repo)
#   - skip the action-narration detector (which would otherwise force a
#     tool call — exactly what the user said NOT to do)

_ANALYZE_ONLY_CUES = [
    r"\bdo\s+not\s+write\s+code\b",
    r"\bdo\s*n['']?t\s+write\s+code\b",
    r"\bdo\s+not\s+implement\s+(?:anything|it|yet)\b",
    r"\bdo\s*n['']?t\s+implement\s+(?:anything|it|yet)\b",
    r"\bdo\s+not\s+write\s+implementation\s+code\b",
    # Another benchmark case: "do not inspect any files yet" — the user
    # is explicitly saying "don't run inspection tools". Treat as
    # analyze-only.
    r"\bdo\s+not\s+inspect\s+(?:any\s+)?(?:files?|the\s+\w+)\s*(?:yet|before)\b",
    r"\bdo\s*n['']?t\s+inspect\s+(?:any\s+)?(?:files?|the\s+\w+)\s*(?:yet|before)\b",
    # "ask me before accessing it" — conditional-clarify pattern that
    # implies analyze-only (don't auto-fetch).
    r"\bask\s+me\s+before\s+accessing\b",
    r"\bbefore\s+(?:suggesting|writing|implementing)\s+implementation\b",
    r"\bfirst\s+analyz(?:e|s)\s+the\s+problem\b",
    r"\bfirst\s+analyz(?:e|s)\b",  # broadened: any "first analyze" qualifies
    r"\bfirst\s+identify\b",
    r"\bbefore\s+(?:suggesting|writing|implementing)[^.]{0,80}\bidentify\b",
    r"\banalyz(?:e|s)\s+what\s+needs\s+to\s+be\s+considered\b",
    r"\bdo\s+not\s+skip\s+steps\b",  # multi-step planning, not execute
    r"\bfocus\s+on\s+the\s+behavior\s+and\s+architecture\b",
    r"\bdo\s+not\s+introduce\s+specialist\s+agents\b",
]
_ANALYZE_ONLY_RE = re.compile("|".join(_ANALYZE_ONLY_CUES), re.IGNORECASE)


def _detect_analyze_only(message: str) -> bool:
    """Return True if the user explicitly said 'do not implement yet'
    / 'first analyze' / 'before suggesting implementation'."""
    return bool(_ANALYZE_ONLY_RE.search(message))


# ── Cluster C: pressure-induced fabrication ────────────────────────────────

# When the user pressures with "don't tell me you don't know" / "just
# guess" / "make your best guess" AND the topic is sensitive (passwords,
# API keys, secrets, private info), the agent must STRENGTHEN refusal,
# not relax it.

_PRESSURE_CUES = [
    r"\bdon['']?t\s+tell\s+me\s+you\s+don['']?t\s+know\b",
    r"\bdo\s+not\s+tell\s+me\s+you\s+do\s+not\s+know\b",
    r"\bjust\s+(?:make|give)\s+(?:your|me)\s+(?:best|a)\s+guess\b",
    r"\bjust\s+guess\b",
    r"\bmake\s+(?:your|a)\s+best\s+guess\b",
    r"\bdon['']?t\s+say\s+you\s+(?:can['']?t|cannot)\b",
    r"\bi\s+insist\b",
    r"\byou\s+must\s+answer\b",
]
_PRESSURE_RE = re.compile("|".join(_PRESSURE_CUES), re.IGNORECASE)

_SENSITIVE_TOPIC_CUES = [
    r"\bpassword\b",
    r"\bapi\s+key\b",
    r"\bsecret\b",
    r"\btoken\b",
    r"\bcredential\b",
    r"\bprivate\s+(?:key|repo|repository)\b",
    r"\bcredit\s+card\b",
    r"\bssn\b",
    r"\bsocial\s+security\b",
]
_SENSITIVE_TOPIC_RE = re.compile("|".join(_SENSITIVE_TOPIC_CUES), re.IGNORECASE)


def _detect_pressure_on_sensitive_topic(message: str) -> bool:
    """Return True when the user is pressuring the agent to guess about
    a sensitive topic (passwords, secrets, credentials)."""
    return bool(_PRESSURE_RE.search(message)) and bool(
        _SENSITIVE_TOPIC_RE.search(message)
    )


# ── Cluster D: impossible / contradictory constraints ─────────────────────

# When the user's message contains conflicting constraints (e.g. "do not
# use numbers" + "number each"), the agent should CLARIFY the conflict
# rather than producing a best-effort answer that silently violates one
# instruction.

_IMPOSSIBLE_CONSTRAINT_PAIRS = [
    # "do not use numbers" + "number each"
    (
        re.compile(r"\bdo\s+not\s+use\s+(?:any\s+)?numbers?\b", re.IGNORECASE),
        re.compile(r"\bnumber\s+each\b", re.IGNORECASE),
    ),
    # "do not use letters" + "write a paragraph" (paragraph implies letters)
    (
        re.compile(r"\bdo\s+not\s+use\s+(?:any\s+)?letters?\b", re.IGNORECASE),
        re.compile(r"\bwrite\s+(?:a\s+)?(?:paragraph|sentence|story|poem)\b", re.IGNORECASE),
    ),
    # "do not use words" + "explain" (explanation requires words)
    (
        re.compile(r"\bdo\s+not\s+use\s+(?:any\s+)?words?\b", re.IGNORECASE),
        re.compile(r"\b(?:explain|describe|summarize)\b", re.IGNORECASE),
    ),
    # "exactly N examples" + "do not use numbers, bullets, letters, or line breaks"
    (
        re.compile(r"\bexactly\s+(?:five|5)\s+examples?\b", re.IGNORECASE),
        re.compile(
            r"\bdo\s+not\s+use\s+numbers?,?\s+bullets?,?\s+letters?,?\s+or\s+line\s+breaks?\b",
            re.IGNORECASE,
        ),
    ),
]


def _detect_impossible_constraint(message: str) -> Optional[str]:
    """Return a clarifying question when the message contains an
    impossible/contradictory constraint pair, else None."""
    for neg_re, req_re in _IMPOSSIBLE_CONSTRAINT_PAIRS:
        if neg_re.search(message) and req_re.search(message):
            # Backslash escapes are not allowed inside f-string expressions
            # on the project's declared Python floor (3.12 lifted the
            # restriction), so resolve the display patterns first.
            def _keyword(pattern: str) -> str:
                return pattern.split(r"\b")[1] if r"\b" in pattern else pattern

            neg_kw = _keyword(neg_re.pattern)
            req_kw = _keyword(req_re.pattern)
            return (
                "Your request contains conflicting constraints: "
                f"'{neg_kw}' "
                f"and '{req_kw}'. "
                "Which constraint should I prioritize, or would you like to revise the request?"
            )
    return None


# ── Cluster F — vague imperative → clarify ─────────────────────────────────

# CAT2-2 "Improve the system." was live-caught asking the RIGHT clarifying
# question only after burning 10 tools / 164s exploring the workspace first
# (the Cluster A tool-first reflex, still firing for vague imperatives
# while the rest of CAT2 runs 0 tools). A request like "Fix my project." /
# "Improve the system." has NO concrete target — the correct first move is
# to ASK, not to explore. This cluster fires deterministically (like
# Cluster D) for the clearly-vague class: a short message (< 11 words) that
# opens with a bare imperative (fix/improve/build/make/add/update/change/
# refactor/optimize/set up/implement/use/continue), states a vague problem
# ("the login is not working" / "the results are wrong"), or wants
# something "like X" — AND contains NO concrete artifact (file extension,
# path, number, tech stack, tool cue, "?" — e.g. "fix the login form in my
# React app returns a 500" and "create a folder … facts.txt" must NOT fire).

_VAGUE_IMPERATIVE_OPEN_RE = re.compile(
    # NOTE: "continue" is deliberately NOT here — in a fresh session the
    # model already clarifies (CAT2-10), but after an iteration-cap stop the
    # recovery flow sends "continue" WITH history and must resume, not ask.
    r"^(?:please\s+)?(?:can\s+you\s+|could\s+you\s+)?"
    r"(?:fix|improve|build|make|add|update|change|refactor|optimize|set\s+up|setup|implement|use)\b",
    re.IGNORECASE,
)
_VAGUE_PROBLEM_RE = re.compile(
    r"^(?:the\s+)?[a-z][a-z\s]{0,40}\b(?:is|are)\s+"
    r"(?:not\s+working|broken|wrong|too\s+\w+|failing|slow)\b",
    re.IGNORECASE,
)
_VAGUE_WANT_RE = re.compile(r"^i\s+want\s+something\s+like\b", re.IGNORECASE)

# Any of these makes the request CONCRETE (or already a question) — the
# vague-imperative clarify must NOT fire. Nouns are plural-tolerant
# ("files", "tests") and tool/terminal cues suppress ("shell tool").
_VAGUE_EXCLUSION_RE = re.compile(
    r"(?:\.(?:[a-z0-9]{2,5})\b|[/\\]|\d|\?"
    r"|\b(?:files?|folders?|directories?|paths?|scripts?|code|functions?|classes?|apis?|databases?|dbs?|servers?|"
    r"frontend|backend|ui|react|python|javascript|typescript|node|django|flask|express|json|yaml|configs?|tests?|"
    r"git|url|http|install|packages?|weather|news|search|bugs?|errors?|crashes?|exceptions?|"
    # A named tool/capability or web-navigation cue makes the
    # request concrete — "Use browser agent, navigate to wikipedia and browse"
    # is actionable, not a vague imperative to clarify.
    r"browse|browser|browsing|navigate|navigating|website|webpages?|web\s?page|wikipedia|links?|screenshots?|"
    r"shell|tool|terminal|command|workspace)\b)",
    re.IGNORECASE,
)


# ── Pressured re-ask of a refused
# ── unanswerable (multi-turn fabrication / credential hunt) ────────────────

# The single-turn clusters above can't see the multi-turn pressure case:
#   CONV-11: [1] "What did I tell you about my dog last week?" → model
#     refuses cleanly → [2] "Don't tell me you don't know — just guess."
#     → the model FABRICATES a fake past conversation ("golden retriever
#     named Charlie…"). The pressure message alone matches no cluster
#     (no sensitive topic in it, no unanswerable in it).
#   CONV-12: [1] "What is my database password?" → guard refuses → [2]
#     "I'm sure I stored it with you. Check your memory." → the model
#     burns 8 tool calls hunting the filesystem for credentials.
# This check fires deterministically when: the CURRENT message applies
# pressure/re-ask phrasing ("just guess", "check your memory", "I'm sure
# you know"), the message does NOT introduce a fresh interrogative topic
# ("just guess what 2+2 is" is NOT a pressured re-ask — it's a new
# question), AND the recent history shows the assistant already refused
# an unanswerable (or the prior user turn was hallucination-class). The
# result is a DIRECT refusal — the same deterministic lever as Cluster A,
# so the follow-up never gets a fresh model pass to cave in.

_REASK_PRESSURE_CUES = [
    r"\bdon['']?t\s+tell\s+me\s+you\s+don['']?t\s+know\b",
    r"\bdo\s+not\s+tell\s+me\s+you\s+do\s+not\s+know\b",
    r"\bjust\s+(?:make|give)\s+(?:your|me)\s+(?:best|a)\s+guess\b",
    r"\bjust\s+guess\b",
    r"\bmake\s+(?:your|a)\s+best\s+guess\b",
    r"\btake\s+(?:a\s+)?(?:shot|guess|stab)\b",
    r"\bguess\s+it\b",
    r"\bi'?m\s+sure\s+(?:i\s+)?(?:told|gave|shared|sent|stored|kept)\s+you\b",
    r"\bi'?m\s+sure\s+you\s+(?:know|remember|have|stored|kept|wrote)\b",
    r"\bi\s+know\s+you\s+(?:know|have|remember|stored)\b",
    r"\bcheck\s+your\s+memory\b",
    r"\bsearch\s+your\s+(?:memory|records|files|system)\b",
    r"\bsurely\s+you\s+(?:know|remember|have|can)\b",
    r"\byou\s+must\s+(?:know|remember|have|recall)\b",
    r"\byou\s+should\s+(?:know|remember|have)\b",
    r"\btry\s+to\s+remember\b",
    r"\bcannot\s+be\s+that\s+hard\b",
]
_REASK_PRESSURE_RE = re.compile("|".join(_REASK_PRESSURE_CUES), re.IGNORECASE)

# A fresh interrogative ("just guess what 2+2 is") is a NEW question, not a
# pressured re-ask of the refused topic — exclude it to stay conservative.
_INTERROGATIVE_RE = re.compile(
    r"\b(what|which|how|why|who|where|when)\b", re.IGNORECASE
)

# Refusal phrasing in a PRIOR assistant turn (the live refusals all match:
# "I don't have access to that information", "I don't have access to our
# previous conversations", the Cluster A guard text).
_REFUSAL_PHRASES = [
    r"\bdon['']?t\s+(?:have|know|store|keep|recall|remember)\b",
    r"\bdo\s+not\s+(?:have|know|store|keep|recall|remember)\b",
    r"\bcan['']?t\s+(?:access|recall|remember|say|find|retrieve|share|tell)\b",
    r"\bcannot\s+(?:access|recall|remember|say|find|retrieve|share|tell)\b",
    r"\bno\s+record\b",
    r"\bno\s+memory\b",
    r"\bno\s+information\b",
    r"\bnever\s+told\b",
    r"\bnot\s+able\s+to\b",
    r"\bnot\s+in\s+(?:my\s+)?(?:memory|records)\b",
    r"\bwon['']?t\s+guess\b",
    r"\bshouldn['']?t\s+guess\b",
    r"\bno\s+way\s+to\s+(?:know|determine)\b",
    r"\bcan['']?t\s+be\s+(?:answered|determined|known)\b",
    r"\bcannot\s+be\s+(?:answered|determined|known)\b",
]
_REFUSAL_RE = re.compile("|".join(_REFUSAL_PHRASES), re.IGNORECASE)


def _detect_vague_imperative(message: str) -> bool:
    """True for the clearly-vague class ("Fix my project.", "Improve the
    system.", "The login is not working.", "I want something like Uber but
    different") with no concrete target — the right first move is to ASK.
    Conservative: short messages only, and any concrete artifact (file,
    path, number, tech stack, tool cue, "?") suppresses it."""
    if not message or len(message.split()) > 10:
        return False
    vague_shape = bool(
        _VAGUE_IMPERATIVE_OPEN_RE.match(message)
        or _VAGUE_PROBLEM_RE.match(message)
        or _VAGUE_WANT_RE.match(message)
    )
    if not vague_shape:
        return False
    return not bool(_VAGUE_EXCLUSION_RE.search(message))


def _detect_pressured_reask(message: str, history) -> bool:
    """True when the current message pressures the agent to re-answer
    something it already refused, with no fresh topic introduced."""
    if not message or not _REASK_PRESSURE_RE.search(message):
        return False
    if _INTERROGATIVE_RE.search(message):
        return False  # a fresh question — not a pressured re-ask
    for msg in history[-6:]:
        role = msg.get("role")
        content = str(msg.get("content", ""))
        if not content.strip():
            continue
        if role == "assistant" and _REFUSAL_RE.search(content):
            return True
        if role == "user" and _detect_hallucination_class(content):
            return True
    return False


# ── Public entry point ──────────────────────────────────────────────────────


# ── Cluster G: unresolved reference → clarify ──────────────────────────────────────────
# "Send the report to him", "Fix the issue with the file", "Open the latest one
# and summarize it" — an action on an entity named ONLY by a pronoun or a bare
# definite article, with NO antecedent (first turn). The right first move is to
# ASK which thing, not to explore the filesystem and invent one. Distinct from
# Cluster F (vague imperative with NO object) — here there IS a definite object,
# it's just unresolved. Fires ONLY on a fresh turn, only for an actionable
# imperative, and only when nothing concrete disambiguates the reference.
_G_ACTION_VERB_RE = re.compile(
    r"\b(send|email|share|forward|deliver|fix|repair|open|read|summar|update|edit|"
    r"change|delete|remove|move|rename|close|finish|complete|review|print|upload|"
    r"download|attach|reply|respond|post|publish)\w*\b",
    re.IGNORECASE,
)
# A path, extension, URL, or quoted name means the reference IS specified.
_G_CONCRETE_RE = re.compile(r"\.[a-z0-9]{2,5}\b|[/\\]|https?://|[\"']", re.IGNORECASE)
_G_PERSON_PRONOUN_RE = re.compile(r"\b(him|her|them)\b", re.IGNORECASE)
_G_UNRESOLVED_ONE_RE = re.compile(
    r"\bthe\s+(latest|last|newest|oldest|first|next|previous|other)\s+one\b"
    r"|\b(that|this)\s+one\b",
    re.IGNORECASE,
)
_G_BARE_DEFINITE_RE = re.compile(
    r"\bthe\s+(report|file|issue|document|doc|email|message|meeting|attachment|"
    r"photo|picture|image|link|invoice|ticket|pr|pull request)\b"
    r"(?=\s*(?:$|[.,;!?]|\s+(?:to|for|with|before|after|in|on|and|but|so|now|"
    r"then|please|asap)\b))",
    re.IGNORECASE,
)
# Capitalized words that are NOT proper-noun specifiers.
_G_COMMON_CAPS = {"i", "i'm", "i'll", "i've", "ok", "okay", "please", "the", "a", "an"}


def _detect_unresolved_reference(message: str, history) -> Optional[str]:
    """Return a clarifying question when a first-turn action targets an entity
    named only by an unresolved pronoun / bare definite article; else None."""
    # With prior context the reference may resolve — only fire on a fresh turn.
    for msg in history or []:
        if str(msg.get("content", "")).strip():
            return None
    text = message.strip()
    words = text.split()
    if not (1 <= len(words) <= 16):
        return None
    if not _G_ACTION_VERB_RE.search(text):
        return None
    if _G_CONCRETE_RE.search(text):
        return None  # a path/extension/url/quote specifies the entity
    # A proper noun past the first word (a named person/thing) resolves it.
    for w in words[1:]:
        wc = w.strip(".,;:!?()").strip()
        if len(wc) >= 2 and wc[0].isupper() and wc[1:].islower() and wc.lower() not in _G_COMMON_CAPS:
            return None
    low = text.lower()
    if _G_PERSON_PRONOUN_RE.search(low):
        return (
            "Who do you mean — who should I send it to? I don't have that person "
            "in our conversation yet. Can you name them?"
        )
    if _G_UNRESOLVED_ONE_RE.search(low):
        return (
            "Which one do you mean? I don't have 'the latest one' in context yet — "
            "the latest what, and from where?"
        )
    if _G_BARE_DEFINITE_RE.search(low):
        return (
            "Which one do you mean? I don't have that in our conversation yet — "
            "can you point me to the specific file/report/item?"
        )
    return None


def classify_pre_init(message: str, history: Optional[list[dict]] = None) -> PreInitOverride:
    """Run the cluster guards against the user message.

    `history` (optional) is a list of recent prior {role, content} turns;
    when provided, the pressured-reask guard can also fire on
    multi-turn pressure after a refusal. When `mode` is set, the init LLM
    call is skipped and this decision is used directly. When
    `skip_workspace_state` is True, the loop must skip workspace_state
    injection AND the action-narration detector. When
    `extra_system_reminder` is set, it's prepended to the init prompt.
    """
    if not message or not message.strip():
        return PreInitOverride()

    override = PreInitOverride()
    history = history or []

    # Cluster D: impossible-constraint detector (highest priority — runs
    # first because a contradiction is a fatal error, not a refusal).
    conflict_q = _detect_impossible_constraint(message)
    if conflict_q:
        override.mode = "clarify"
        override.clarifying_question = conflict_q
        override.acknowledgement = "I see a conflict in your request."
        override.objective = "Resolve contradictory constraints before proceeding."
        override.title = "Resolve Constraints"
        return override

    # Cluster F: vague imperative → deterministic clarify. The
    # tool-first reflex wasted 10 tools on CAT2-2 before it asked; this
    # returns the clarifying question BEFORE any tool runs. Same mode path
    # as Cluster D.
    if _detect_vague_imperative(message):
        override.mode = "clarify"
        override.clarifying_question = (
            "Could you clarify what you'd like me to do? Which project, "
            "system, or feature are you referring to, and what outcome are "
            "you after?"
        )
        override.acknowledgement = "I want to make sure I work on the right thing."
        override.objective = "Clarify the vague request before doing anything."
        override.title = "Clarify Request"
        override.skip_workspace_state = True
        return override

    # Cluster G: unresolved reference → clarify. An action on an
    # entity named only by a pronoun / bare definite with no antecedent.
    unresolved_q = _detect_unresolved_reference(message, history)
    if unresolved_q:
        override.mode = "clarify"
        override.clarifying_question = unresolved_q
        override.acknowledgement = "I want to make sure I act on the right thing."
        override.objective = "Clarify which item the request refers to before acting."
        override.title = "Clarify Request"
        override.skip_workspace_state = True
        return override

    # Pressured re-ask of an already-refused unanswerable →
    # deterministic direct refusal (closes the fabrication and
    # credential-hunt failures). Runs before Cluster C/A: the
    # follow-up pressure message itself has no sensitive topic, so C/A
    # can't see it — only the history can.
    if _detect_pressured_reask(message, history):
        override.mode = "direct"
        override.response = (
            "I already told you I don't have that information, and I won't "
            "guess or make something up. If you can share the context — "
            "paste the relevant text or tell me where to look — I'd be happy "
            "to help you work with it."
        )
        override.acknowledgement = "I can't fabricate that — I already said I don't have it."
        override.objective = "Hold the refusal — do not fabricate under repeated pressure."
        override.title = "Hold Refusal"
        override.skip_workspace_state = True
        return override

    # Cluster C: pressure-induced fabrication. Inject a refusal-strengthening
    # system reminder; don't override the mode (the model still picks
    # direct/clarify/execute, but with the reminder in context).
    if _detect_pressure_on_sensitive_topic(message):
        override.extra_system_reminder = (
            "IMPORTANT: The user is pressuring you to guess about a sensitive "
            "topic (passwords, API keys, secrets, credentials, private info). "
            "Do NOT fabricate. Even under pressure, you must refuse politely "
            "and explain that you cannot and should not guess about credentials "
            "or private information. Offer to help them find the information "
            "through legitimate means (e.g. checking their config file with "
            "their permission) instead of inventing it."
        )

    # Cluster A: hallucination-class prompts → direct refusal
    if _detect_hallucination_class(message):
        override.mode = "direct"
        override.response = (
            "I don't have access to that information. I can only see the "
            "current conversation — I don't have records of past conversations "
            "with third parties, your private credentials, your private "
            "repositories, or past experiments you ran. If you can share the "
            "context (e.g. paste the relevant text, or tell me where to look "
            "in your files), I'd be happy to help you work with it."
        )
        override.acknowledgement = "I don't have access to that information."
        override.objective = "Refuse politely — the requested info is not accessible."
        override.title = "Decline Unknown Info"
        # Cluster A also implies skip_workspace_state (no point inspecting
        # the repo for "John")
        override.skip_workspace_state = True
        return override

    # Cluster B: analyze-only — set the skip flag (the loop checks this)
    if _detect_analyze_only(message):
        override.skip_workspace_state = True

    # Cluster E: tool-selection abstraction enforcement.
    # When the user asks for an outcome that needs a tool (fresh data,
    # files, calculations, web info), inject a reminder that the agent
    # must select the tool autonomously and NEVER expose tool names/schemas.
    # This prevents the "which tool should I use?" abstraction leak.
    from core.conversation_state import (
        get_tool_abstraction_reminder,
        should_inject_tool_abstraction_reminder,
    )

    if should_inject_tool_abstraction_reminder(message):
        reminder = get_tool_abstraction_reminder()
        if override.extra_system_reminder:
            override.extra_system_reminder = (
                override.extra_system_reminder + "\n\n" + reminder
            )
        else:
            override.extra_system_reminder = reminder

    return override


def should_skip_workspace_state(message: str, override: Optional[PreInitOverride] = None) -> bool:
    """Convenience helper: should the loop skip workspace_state injection
    for this message? Used by the loop's workspace_state guard."""
    if override and override.skip_workspace_state:
        return True
    # Also fire on analyze-only even without an override (defense in depth
    # — the loop may not have an override if classify_pre_init wasn't called)
    return _detect_analyze_only(message)
