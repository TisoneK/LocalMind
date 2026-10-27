"""Deterministic evidence-grounding check for figure-bearing final answers.

Why this exists (the Kitengela weather trace, 2026-10-27)
---------------------------------------------------------
A turn fetched a JavaScript-rendered weather page whose readable extract was
navigation chrome — language lists, promos, and other cities' temperatures.
The fetch legitimately succeeded (the page was reached and text was
extracted), but it carried no data for the subject place. The model then
answered with a full forecast ("26°C high and 17°C low, wind 24 km/h, 4
hours of sunshine, 0-5 mm rain") assembled from nothing, and the
final-answer acceptance gate let it through: its detectors judge whether
the model ACTED or ANSWERED, never whether the figures it asserted exist
in the evidence the turn produced.

The zero-tool path already intercepts that fabrication shape (the
fabricated-data detector on the answer's head). The tools-then-answer path
had the hole. This module closes it: every figure-bearing assertion about
measured quantities (temperatures, wind, precipitation bands, humidity,
sunshine hours, prices) in a final answer must appear — as numbers —
somewhere in the evidence the conversation actually holds. A figure that
appears nowhere was invented.

Design constraints
------------------
- Deterministic, no LLM call: the acceptance gate runs this inline and
  pays no extra latency.
- Conservative: a figure passes if its number appears anywhere in the
  evidence pool (the model's whole visible conversation plus the trace's
  tool observations and inputs). Only absence from EVERYTHING flags, so a
  legitimately scraped figure never trips the check.
- Single-digit runs must appear as standalone numbers. Otherwise "0-5 mm"
  would pass because "2026" contains a 0 and "25°C" contains a 5.
- Association (which city, which day a figure belongs to) is deliberately
  NOT checked: that needs semantics, and quoting the right numbers for the
  wrong row is a softer failure than inventing numbers from nothing. It
  stays open and belongs to a judge, not a regex.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# Figure-bearing assertions about measured quantities — the shapes that get
# invented when evidence is thin. Each match contributes the number runs it
# contains; every run must be findable in the evidence pool.
_ASSERTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 26°C / 77 °F / 26-degrees-C
    re.compile(r"\b\d+(?:\.\d+)?\s*°\s*[CF]\b"),
    # wind 24 km/h, 10 mph, 3 m/s, 15 knots
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:km/h|kph|mph|m/s|knots?|kmh)\b", re.IGNORECASE),
    # precipitation bands and depths: 0-5 mm, 10-20 mm, 2 mm
    re.compile(r"\b\d+(?:\.\d+)?(?:\s*[-–—]\s*\d+(?:\.\d+)?)?\s*mm\b", re.IGNORECASE),
    # humidity / probability: "68% humidity", "humidity: 68%", "chance of rain 20%"
    re.compile(
        r"\b\d+\s*%\s*(?:humidity|chance|probability|likelihood)"
        r"|(?:humidity|chance of (?:rain|precipitation|snow|showers))\s*(?:is|of|:|was)?\s*\d+\s*%",
        re.IGNORECASE,
    ),
    # 4 hours of sunshine
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:hours?|hrs?)\s+of\s+(?:sunshine|sun)\b", re.IGNORECASE),
    # prices: $12.50, €9, 1200 KES, 45 USD
    re.compile(
        r"[\$€£₹]\s*\d+(?:[.,]\d+)?"
        r"|\b\d+(?:[.,]\d+)?\s*(?:USD|EUR|GBP|KES|NGN|TZS|UGX|ZAR|INR|CAD|AUD)\b",
        re.IGNORECASE,
    ),
)

# Every number run inside an assertion match ("0-5" -> ["0", "5"]).
_DIGIT_RUN_RE = re.compile(r"\d+(?:\.\d+)?")


@dataclass
class GroundingReport:
    """Outcome of checking one answer against one evidence pool."""

    checked: int = 0
    """Figure-bearing assertion matches found in the answer."""
    ungrounded: list[str] = field(default_factory=list)
    """Matched spans (verbatim) whose numbers appear nowhere in the evidence."""

    @property
    def grounded(self) -> bool:
        return not self.ungrounded


def collect_evidence_text(trace, loop_messages: Optional[list] = None) -> str:
    """Assemble everything the model could have grounded its figures on.

    Tool evidence only: the observations and inputs of steps that actually
    ran a tool, plus every message content in the turn's conversation —
    tool messages, stored-result retrievals, earlier answers. Steps without
    a tool are the answer's own records, never evidence: the loop appends
    the final answer as a tool-less step BEFORE the gate runs, so counting
    step thoughts would let an answer ground its own invented figures.
    Lowercased once; callers enrich the pool with the full text of stubbed
    large results before checking.
    """
    parts: list[str] = []
    for step in getattr(trace, "steps", None) or []:
        if not getattr(step, "tool_name", ""):
            continue
        parts.append(getattr(step, "observation", "") or "")
        parts.append(getattr(step, "tool_input", "") or "")
    for msg in loop_messages or []:
        if isinstance(msg, dict):
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                parts.append(content)
    return "\n".join(parts).lower()


def _run_present(run: str, evidence_norm: str, evidence_raw_lower: str) -> bool:
    """Is one number run findable in the evidence?

    Runs of two or more digits may appear anywhere (27 inside "27.5" counts —
    a rounded quotation). Single digits must appear as a standalone number:
    "0" inside "2026" or "5" inside "25" is not the number 0 or 5.
    """
    if len(run) >= 2:
        return run in evidence_norm
    return re.search(rf"(?<!\d){re.escape(run)}(?!\d)", evidence_raw_lower) is not None


def check_answer_grounding(answer: str, evidence: str) -> GroundingReport:
    """Check every figure-bearing assertion in ``answer`` against ``evidence``.

    An assertion is ungrounded when at least one of its number runs appears
    nowhere in the evidence — that figure was invented, because a figure
    read from any source leaves its digits behind. An empty evidence pool
    makes every asserted figure ungrounded by definition.
    """
    report = GroundingReport()
    if not answer:
        return report
    evidence_norm = evidence.replace(",", "")
    evidence_raw_lower = evidence
    for pattern in _ASSERTION_PATTERNS:
        for match in pattern.finditer(answer):
            report.checked += 1
            runs = _DIGIT_RUN_RE.findall(match.group(0).replace(",", ""))
            if runs and all(
                _run_present(run, evidence_norm, evidence_raw_lower) for run in runs
            ):
                continue
            span = match.group(0).strip()
            if span not in report.ungrounded:
                report.ungrounded.append(span)
    return report
