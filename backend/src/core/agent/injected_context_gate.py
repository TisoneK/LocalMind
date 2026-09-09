"""Zero-tool success shapes for the acceptance gate — criterion classes.

The acceptance gate's success criteria and zero-tool detectors score only
TOOL-derived evidence. But the loop's own prompt injects grounding context
(current date/time, workspace, memory facts), and the honesty contract
requires the model to DECLINE policy-violating requests. Turns whose answer
is fully grounded in injected context — or that decline a policy-violating
request — have NO tool evidence by DESIGN, so the gate is wrong to demand
tool evidence: it replans, the model burns 1-3 iterations hunting for a tool
that isn't needed (loading the sysinfo schema on "what day is it today?"),
and the turn lands at 2-3x the latency of the same answer accepted on the
first iteration.

Two criterion classes are valid zero-tool success shapes:

  GROUNDED   — the user's request is answerable from context the loop itself
               injects (current date/time, environment, memory facts, the
               session's own conversation) and the final answer actually
               contains the grounded fact. Verified deterministically: the
               request is a time/date grounding question AND the answer
               states the value from the injected context.
  DECLINE    — the user's request asks the model to violate policy (reveal
               system prompts or secrets, bypass instructions) and the final
               answer declines. Verified deterministically: the request
               matches a violation shape AND the answer matches a decline
               shape. Tool evidence for a decline would be suspicious, not
               reassuring.

This module is the single decision point so the loop consults ONE predicate
instead of re-deriving these classes ad hoc, and unit tests pin the policy
in one place. It is deliberately CONSERVATIVE: a class matches only when
BOTH the request shape and the answer shape are recognized. When the answer
does not actually contain the grounded fact (or the decline), the class does
not apply and the existing tool-evidence behavior is unchanged.
"""

from __future__ import annotations

import datetime
import re

# ── GROUNDED class: requests answerable from the injected context ────────────
#
# The grounding contract: `context_builder._build_environment_context` injects
# "Current date: {date_str}" / "Current time: ..." / "Today is {date_str}"
# into EVERY agent-turn context. Time/date grounding questions are answerable
# from that block alone — a sysinfo round-trip adds latency, not truth (the
# injected value comes from the same system clock the tool would read).

_WEEKDAY_WORDS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

_GROUNDED_REQUEST_RE = re.compile(
    r"\b(?:"
    r"day\s+of\s+the\s+week"
    r"|what\s+day\b"
    r"|today'?s?\s+date\b"
    r"|what(?:'s| is)?\s+(?:the\s+)?date\b"
    r"|date\s+(?:is\s+it|today)\b"
    r"|what\s+time\b"
    r"|current\s+time\b"
    r"|time\s+(?:is\s+it|right\s+now)\b"
    r"|what\s+year\b"
    r"|current\s+year\b"
    r"|what\s+month\b"
    r"|current\s+(?:date|month)\b"
    r")",
    re.IGNORECASE,
)

# A request that commits to acting on external state is a TASK that happens
# to mention the clock, not a grounding question ("create a file with today's
# date in the name"). The grounded class must never cover it — the gate's
# action-narration detector stays authoritative for tasks.
_TASK_SHAPED_RE = re.compile(
    r"\b(?:"
    r"create|write|make|build|save|update|edit|delete|remove|install|run|"
    r"execute|open|read|append|rename|move|copy|download|search|fetch|browse"
    r")\b",
    re.IGNORECASE,
)

# ── DECLINE class: policy-violation request shapes ───────────────────────────
#
# The model's honesty contract already instructs it to refuse these. The gate
# only needs to recognize the REQUEST SHAPE so a clean refusal isn't scored
# as narration. Bounded to unambiguous violation shapes — not every request
# mentioning "prompt" or "instructions".

_DECLINE_REQUEST_RES: tuple[re.Pattern[str], ...] = (
    # Instruction-override / system-prompt extraction.
    re.compile(
        r"\b(?:ignore|disregard|forget)\s+(?:all\s+|any\s+|your\s+)?(?:previous|prior|above)\b"
        r"|\b(?:reveal|show|paste|print|repeat|dump|leak)\b.{0,40}\b(?:system\s+)?(?:prompt|instructions)\b"
        r"|\bwhat(?:'s| is)?\s+(?:your|the)\s+(?:full\s+)?(?:system\s+)?(?:prompt|instructions)\b",
        re.IGNORECASE,
    ),
    # Secret/credential extraction.
    re.compile(
        r"\b(?:api\s*key|secret|password|credential|token)\b.{0,60}\b(?:reveal|show|paste|print|share|dump|give|send|read|extract|steal)\b"
        r"|\b(?:reveal|show|paste|print|share|dump)\b.{0,40}\b(?:api\s*key|secret|password|credentials?|token)\b",
        re.IGNORECASE,
    ),
)

# Decline answer shapes: the model refuses, deflects, or redirects. Mirrors
# the live harness's decline regex plus first-person inability/refusal forms.
# Not authoritative on its own — the compliance check below wins first (a
# "decline" that then dumps is a leak, not a decline).
_DECLINE_ANSWER_RE = re.compile(
    r"\b(?:"
    r"can'?t|cannot|can ?not|won'?t|will not"
    r"|not (?:able|going) to"
    r"|i don'?t (?:have|share|expose)"
    r"|no can do"
    r"|prefer not"
    r"|not appropriate"
    r"|i (?:must )?decline"
    r"|against (?:my|the) (?:policies|guidelines|rules)"
    r"|internal (?:configuration|instructions?|system (?:prompt|config))"
    r"|happy to help (?:with|instead)"
    r"|instead i can"
    r"|i can (?:help|instead)"
    r")",
    re.IGNORECASE,
)


def request_matches_grounded_class(message: str) -> bool:
    """True when the request asks for a fact the injected context carries.

    Task-shaped requests ("create a file with today's date") never match —
    they are actions that happen to mention the clock, not grounding
    questions.
    """
    if not message:
        return False
    if _TASK_SHAPED_RE.search(message):
        return False
    return bool(_GROUNDED_REQUEST_RE.search(message))


def request_matches_decline_class(message: str) -> bool:
    """True when the request matches a policy-violation shape."""
    if not message:
        return False
    return any(rx.search(message) for rx in _DECLINE_REQUEST_RES)


def _answer_states_current_date(
    answer: str, now: datetime.datetime | None = None
) -> bool:
    """True when the answer states today's weekday or the calendar date.

    Checked against the REAL clock — the same clock the injected context
    came from. A stated weekday must be TODAY's weekday and any stated year
    must be the current year: a fabricated weekday/year is not grounding,
    and the class must not apply to it.
    """
    now = now or datetime.datetime.now()
    text = (answer or "").strip()
    if not text:
        return False
    lower = text.lower()
    # Ordinal-stripped copy for date-variant matching ("September 9th" →
    # "September 9").
    stripped = re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", lower)
    # Year guard: any stated year that isn't the current one is fabrication
    # (the live-harness failure shape: a confident answer citing 2024/2025).
    if any(int(ym) != now.year for ym in re.findall(r"\b(20\d{2})\b", lower)):
        return False
    # Weekday guard: when the answer names ANY weekday, it must name today's.
    today = now.strftime("%A").lower()
    stated = [w for w in _WEEKDAY_WORDS if w in lower]
    if stated:
        return today in stated
    # No weekday word: today's calendar date (several common renderings) or
    # the bare current year ("It's 2026.").
    y, m, d = now.year, now.month, now.day
    month_name = now.strftime("%B")
    date_variants = (
        f"{y:04d}-{m:02d}-{d:02d}",
        f"{y}-{m}-{d}",
        f"{y}/{m:02d}/{d:02d}",
        f"{month_name} {d}, {y}",
        f"{month_name} {d:02d}, {y}",
        f"{d} {month_name} {y}",
        f"{m:02d}/{d:02d}/{y}",
        f"{m}/{d}/{y}",
    )
    if any(variant.lower() in stripped for variant in date_variants):
        return True
    return bool(re.search(rf"\b{y}\b", stripped))


def _answer_states_current_time(
    answer: str, now: datetime.datetime | None = None
) -> bool:
    """True when the answer states a clock time near the real one (±5 min).

    A bare H:MM pattern alone is too loose (any random number pair would
    pass); tying it to the actual injected clock time keeps the class
    honest.
    """
    now = now or datetime.datetime.now()
    text = (answer or "").strip()
    if not text:
        return False
    matches = re.findall(r"\b(\d{1,2}):(\d{2})\b", text)
    if not matches:
        return False
    for h_str, m_str in matches:
        h, m = int(h_str), int(m_str)
        if h == now.hour and abs(m - now.minute) <= 5:
            return True
    return False


def answer_grounded_in_injected_context(
    request: str,
    answer: str,
    now: datetime.datetime | None = None,
) -> bool:
    """GROUNDED class verdict: the request asks an injected-context question
    AND the answer actually states the grounded fact.

    When the request is a time/date grounding question, the answer must
    state the real current date (weekday or calendar date, checked against
    the real clock) or a clock time within minutes of it. A request that
    matches the shape but an answer that does NOT contain the fact stays
    outside the class — the gate then behaves exactly as before.
    """
    if not request_matches_grounded_class(request):
        return False
    return _answer_states_current_date(answer, now) or _answer_states_current_time(
        answer, now
    )


def answer_is_policy_decline(request: str, answer: str) -> bool:
    """DECLINE class verdict: the request matches a policy-violation shape
    AND the answer declines without complying.

    A decline that also emits the requested content is NOT a decline: if the
    answer contains a code fence or embedded directive-looking text, the
    class does not apply and the gate keeps its normal behavior.
    """
    if not request_matches_decline_class(request):
        return False
    text = (answer or "").strip()
    if not text:
        return False
    # A "decline" that contains the requested dump is compliance, not refusal:
    # fenced blocks or directive-looking lines defeat the class.
    if "```" in text:
        return False
    if re.search(r"(?:^|\n)\s*(?:#|you must|always|never)\s", text, re.IGNORECASE):
        return False
    return bool(_DECLINE_ANSWER_RE.search(text))


def zero_tool_turn_is_valid(message: str, answer: str) -> bool:
    """True when the zero-tool turn is a valid success shape (GROUNDED or
    DECLINE) — the acceptance gate may accept it without tool evidence.

    `message` is the user's request for THIS turn (reformulated or raw);
    `answer` is the model's final answer text. Both class verdicts are
    deterministic and conservative (request shape AND answer shape).
    """
    if not message or not (answer or "").strip():
        return False
    if answer_grounded_in_injected_context(message, answer):
        return True
    return answer_is_policy_decline(message, answer)
