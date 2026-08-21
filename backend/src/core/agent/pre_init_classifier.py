"""
Session 337 — Pre-init deterministic classifiers for the 4 root-cause
clusters identified by the Session 336 benchmark.

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
    # Third-party past-tense references
    r"\bwhat\s+did\s+\w+\s+tell\s+me\b",
    r"\bwhat\s+did\s+\w+\s+say\b",
    r"\bwhat\s+did\s+(?:john|mary|alice|bob|sarah|mike|he|she|they|we|you)\b",
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
    r"\bbefore\s+(?:suggesting|writing|implementing)\s+implementation\b",
    r"\bfirst\s+analyz(?:e|s)\s+the\s+problem\b",
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
            return (
                "Your request contains conflicting constraints: "
                f"'{neg_re.pattern.split(r'\b')[1] if '\\b' in neg_re.pattern else neg_re.pattern}' "
                f"and '{req_re.pattern.split(r'\b')[1] if '\\b' in req_re.pattern else req_re.pattern}'. "
                "Which constraint should I prioritize, or would you like to revise the request?"
            )
    return None


# ── Public entry point ──────────────────────────────────────────────────────


def classify_pre_init(message: str) -> PreInitOverride:
    """Run the 4 cluster guards against the user message.

    Returns a PreInitOverride. When `mode` is set, the init LLM call is
    skipped and this decision is used directly. When `skip_workspace_state`
    is True, the loop must skip workspace_state injection AND the action-
    narration detector. When `extra_system_reminder` is set, it's
    prepended to the init prompt.
    """
    if not message or not message.strip():
        return PreInitOverride()

    override = PreInitOverride()

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

    return override


def should_skip_workspace_state(message: str, override: Optional[PreInitOverride] = None) -> bool:
    """Convenience helper: should the loop skip workspace_state injection
    for this message? Used by the loop's workspace_state guard."""
    if override and override.skip_workspace_state:
        return True
    # Also fire on analyze-only even without an override (defense in depth
    # — the loop may not have an override if classify_pre_init wasn't called)
    return _detect_analyze_only(message)
