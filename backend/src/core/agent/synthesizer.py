"""
AnswerSynthesizer — Post-tool reasoning layer for LocalMind.

Transforms raw tool output into user-facing answers through a
three-phase pipeline: extraction, sufficiency checking, and synthesis.

The KEY insight: the synthesizer MUST use the LLM to produce a
human-readable summary. Template fallbacks and raw-output dumps are
last-resort measures only.

Pipeline:
    Intent -> Tool Select -> Execute -> Extract -> Check -> LLM Synthesize -> Answer

Design Principles:
  1. LLM synthesis is the PRIMARY path — templates are fallback only
  2. Pre-process messy web content before sending to LLM
  3. Conservative sufficiency — only claim sufficiency when confident
  4. Honest gap reports — never fabricate when data is insufficient
  5. Smart extraction fallback — use regex to extract key data when LLM fails
  6. Graceful degradation — never dump raw HTML/text to the user

Integration Points:
  - core/agent/loop.py: Hook after final AgentLoop iteration
  - core/agent/prompts.py: Synthesis prompt templates
  - core/agent/constants.py: SYNTHESIS_ENABLED, SYNTHESIS_TIMEOUT
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from core.models import Intent, ToolResult

logger = logging.getLogger(__name__)


# ── Data Models ──────────────────────────────────────────────────────


class SufficiencyLevel(Enum):
    """How sufficient the extracted data is for answering the question."""

    SUFFICIENT = "sufficient"  # Data contains the answer
    PARTIALLY_SUFFICIENT = "partial"  # Data has some relevant info
    INSUFFICIENT = "insufficient"  # Data doesn't address the question
    NEEDS_FOLLOWUP = "needs_followup"  # Need more tool calls (e.g., web_fetch)


@dataclass
class ExtractedData:
    """Structured data extracted from raw tool output."""

    intent: Intent
    raw_content: str
    fields: Dict[str, Any] = field(default_factory=dict)
    source_urls: List[str] = field(default_factory=list)
    has_specific_values: bool = False  # Whether concrete data was found
    is_error: bool = False  # Whether the tool returned an error
    is_empty: bool = False  # Whether the tool returned nothing


@dataclass
class SufficiencyResult:
    """Result of the sufficiency check."""

    level: SufficiencyLevel
    reason: str = ""
    followup_tool: Optional[str] = None  # e.g., "web_fetch"
    followup_args: Optional[Dict[str, str]] = None


@dataclass
class SynthesisResult:
    """Final result of the synthesis pipeline."""

    answer: str
    is_synthesized: bool = True  # Whether the answer was synthesized (vs raw)
    is_gap_report: bool = False  # Whether this is an honest gap report
    needs_followup: bool = False  # Whether more tool calls are needed
    followup_tool: Optional[str] = None
    followup_args: Optional[Dict[str, str]] = None


# ── Web Content Pre-Processing ──────────────────────────────────────


def _preprocess_web_content(content: str, user_question: str = "") -> str:
    """
    Clean up messy web fetch content before sending to the LLM.

    Raw web fetch output contains ads, navigation text, duplicate
    headings, and other noise that wastes LLM context tokens and
    degrades synthesis quality. This function strips the noise and
    extracts the most relevant content sections.

    Strategy:
    1. Remove advertisement lines and navigation boilerplate
    2. Remove duplicate headings (weather.com repeats them)
    3. Collapse whitespace while preserving structure
    4. If the question is specific (e.g., "weather"), try to find
       the most relevant section and prioritize it
    """
    if not content or len(content) < 50:
        return content

    lines = content.split("\n")
    cleaned_lines = []

    # Patterns for noise that should be removed entirely
    _NOISE_PATTERNS = [
        re.compile(r"^\s*Advertisement\s*$", re.IGNORECASE),
        re.compile(r"^\s*Ad\s*$", re.IGNORECASE),
        re.compile(r"^\s*Sponsored\s*$", re.IGNORECASE),
        re.compile(r"^\s*Cookie", re.IGNORECASE),
        re.compile(r"^\s*Sign\s*(in|up)", re.IGNORECASE),
        re.compile(r"^\s*Log\s*(in|out)", re.IGNORECASE),
        re.compile(r"^\s*Subscribe", re.IGNORECASE),
        re.compile(r"^\s*Newsletter", re.IGNORECASE),
        re.compile(r"^\s*Accept\s+(all\s+)?cookies", re.IGNORECASE),
        re.compile(r"^\s*Manage\s+(privacy|cookie|consent)", re.IGNORECASE),
        re.compile(r"^\s*Privacy\s+Policy", re.IGNORECASE),
        re.compile(r"^\s*Terms\s+of\s+(Service|Use)", re.IGNORECASE),
        re.compile(r"^\s*All\s+Rights\s+Reserved", re.IGNORECASE),
        re.compile(r"^\s*Copyright\s*\d", re.IGNORECASE),
        re.compile(r"^\s*Source:\s*https?://", re.IGNORECASE),
        re.compile(r"^\s*Play\s*$", re.IGNORECASE),
        re.compile(r"^\s*Video\s*$", re.IGNORECASE),
        re.compile(r"^\s*Heads-up\s*$", re.IGNORECASE),
        re.compile(r"^\s*Moon\s+(Phase|Rise|Set)", re.IGNORECASE),
        re.compile(r"^\s*UV\s+Index", re.IGNORECASE),
        re.compile(r"^\s*Humidity\s*$", re.IGNORECASE),
        re.compile(r"^\s*Add\s*$", re.IGNORECASE),
        re.compile(r"^\s*alertLevel\d", re.IGNORECASE),
        re.compile(r"^\s*Subtract\s*$", re.IGNORECASE),
        re.compile(r"^\s*Waning\s+Crescent", re.IGNORECASE),
        re.compile(r"^\s*Sunrise\s*$", re.IGNORECASE),
        re.compile(r"^\s*Sunset\s*$", re.IGNORECASE),
        re.compile(r"^\s*Moonrise\s*$", re.IGNORECASE),
        re.compile(r"^\s*Moonset\s*$", re.IGNORECASE),
    ]

    seen_headings = set()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append("")
            continue

        # Skip noise lines
        if any(p.match(stripped) for p in _NOISE_PATTERNS):
            continue

        # Skip duplicate headings (weather.com repeats them)
        heading_key = stripped.lower().strip(".:")
        if heading_key in seen_headings and len(stripped) < 80:
            continue
        if len(stripped) < 80:
            seen_headings.add(heading_key)

        cleaned_lines.append(stripped)

    result = "\n".join(cleaned_lines)

    # Collapse 3+ consecutive blank lines into 2
    result = re.sub(r"\n{3,}", "\n\n", result)

    return result.strip()


def _extract_relevant_section(content: str, user_question: str) -> str:
    """
    Try to find the most relevant section of a long web page
    based on the user's question keywords.

    For weather queries, finds the "Today/Tonight" section.
    For other queries, finds the section with the most keyword overlap.
    """
    if not user_question or len(content) < 2000:
        return content

    question_lower = user_question.lower()
    keywords = set(re.findall(r"\b\w{3,}\b", question_lower))

    # For weather queries, try to find the current conditions section
    if any(kw in question_lower for kw in ("weather", "temperature", "temp", "forecast", "rain", "sunny")):
        # Look for "Tonight" or "Today" or "Current" sections
        for marker in ["Tonight", "Today", "Current", "Now", "As of"]:
            idx = content.find(marker)
            if idx > 0:
                # Take a generous window around the marker
                start = max(0, idx - 200)
                end = min(len(content), idx + 3000)
                section = content[start:end]
                if len(section) < len(content):
                    return section + "\n\n[... additional forecast data available ...]"

    # Generic: split into paragraphs and score by keyword overlap
    paragraphs = re.split(r"\n{2,}", content)
    if len(paragraphs) <= 3:
        return content

    scored = []
    for i, para in enumerate(paragraphs):
        para_lower = para.lower()
        overlap = sum(1 for kw in keywords if kw in para_lower)
        scored.append((overlap, i, para))

    # Sort by score descending
    scored.sort(key=lambda x: -x[0])

    # Take top paragraphs up to ~4000 chars
    selected = []
    total_chars = 0
    max_chars = 4000
    for score, idx, para in scored:
        if total_chars + len(para) > max_chars:
            break
        if score > 0 or len(selected) < 2:
            selected.append((idx, para))
            total_chars += len(para)

    # Sort back by original position
    selected.sort(key=lambda x: x[0])

    if selected:
        result = "\n\n".join(para for _, para in selected)
        if len(result) < len(content):
            result += "\n\n[... additional content available ...]"
        return result

    return content


# ── Extraction Templates ────────────────────────────────────────────

_TIME_SENSITIVE_QUERY_RE = re.compile(
    r"\b(weather|temperature|price|score|result|fixture|schedule|news|today|"
    r"yesterday|current|forecast|rain|sunny|snow|wind|humidity|air\s+quality)\b",
    re.IGNORECASE,
)
_MONTH_DATE_RE = re.compile(
    r"\b(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,\s*|\s+)(?P<year>\d{4})\b",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})\b")
_NUMERIC_DATE_RE = re.compile(r"\b(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{4})\b")


def _is_time_sensitive_query(user_question: str) -> bool:
    return bool(_TIME_SENSITIVE_QUERY_RE.search(user_question or ""))


def _dates_in_text(text: str) -> list[date]:
    """Extract unambiguous calendar dates from a search-result block."""
    dates: list[date] = []
    for match in _MONTH_DATE_RE.finditer(text):
        month = match.group("month").rstrip(".")
        try:
            parsed = datetime.strptime(
                f"{month} {match.group('day')} {match.group('year')}",
                "%B %d %Y",
            )
        except ValueError:
            parsed = datetime.strptime(
                f"{month} {match.group('day')} {match.group('year')}",
                "%b %d %Y",
            )
        dates.append(parsed.date())
    for pattern in (_ISO_DATE_RE, _NUMERIC_DATE_RE):
        for match in pattern.finditer(text):
            try:
                dates.append(
                    date(
                        int(match.group("year")),
                        int(match.group("month")),
                        int(match.group("day")),
                    )
                )
            except ValueError:
                continue
    return list(dict.fromkeys(dates))


def _sanitize_time_sensitive_search(
    content: str,
    user_question: str,
    today: date,
) -> tuple[str, dict[str, object]]:
    """Remove explicitly stale result blocks before current-data synthesis.

    Search providers commonly return a mixture of current and archived pages.
    The model must not choose an older dated block merely because it contains
    a concrete value while a same-day result is also present.
    """
    freshness: dict[str, object] = {
        "checked": _is_time_sensitive_query(user_question),
        "today": today.isoformat(),
        "dated_blocks": 0,
        "current_blocks": 0,
        "stale_blocks": 0,
        "filtered_blocks": 0,
        "stale_only": False,
    }
    if not freshness["checked"]:
        return content, freshness

    blocks = [block for block in re.split(r"(?m)(?=^\s*\d+\.\s)", content) if block.strip()]
    dated_blocks: list[tuple[str, list[date]]] = []
    for block in blocks:
        dated_blocks.append((block, _dates_in_text(block)))

    dated = [(block, dates) for block, dates in dated_blocks if dates]
    current = [
        (block, dates)
        for block, dates in dated
        if today in dates
    ]
    stale = [
        (block, dates)
        for block, dates in dated
        if any(item < today for item in dates) and today not in dates
    ]
    freshness["dated_blocks"] = len(dated)
    freshness["current_blocks"] = len(current)
    freshness["stale_blocks"] = len(stale)

    if not dated:
        return content, freshness

    if current:
        kept = [
            block
            for block, dates in dated_blocks
            if not dates or today in dates
        ]
        freshness["filtered_blocks"] = len(blocks) - len(kept)
        return "\n".join(kept).strip(), freshness

    # No result is explicitly dated today. Keep only undated evidence; the
    # caller will return an honest gap report instead of presenting old data.
    kept = [block for block, dates in dated_blocks if not dates]
    freshness["stale_only"] = True
    freshness["filtered_blocks"] = len(blocks) - len(kept)
    return "\n".join(kept).strip(), freshness


def _extract_web_search(
    content: str,
    today: Optional[date] = None,
    user_question: str = "",
) -> ExtractedData:
    """Extract search data and enforce freshness for live-data questions."""
    today = today or date.today()
    sanitized, freshness = _sanitize_time_sensitive_search(content, user_question, today)
    urls = re.findall(r'https?://[^\s<>"\')\]]+', sanitized)
    has_values = bool(
        re.search(r"\d+\.?\d*\s*°[CF]", sanitized)
        or re.search(r"\$\d+[\d,.]*", sanitized)
        or re.search(r"\d{1,2}:\d{2}\s*(AM|PM)", sanitized, re.IGNORECASE)
        or re.search(r"\d{1,2}\s+(vs|v\.?)\s+\d{1,2}", sanitized)
    )
    snippet_lines = [
        line
        for line in sanitized.split("\n")
        if line.strip() and not line.strip().startswith("http") and len(line.strip()) > 20
    ]
    return ExtractedData(
        intent=Intent.WEB_SEARCH,
        raw_content=sanitized,
        fields={
            "urls": urls[:10],
            "url_count": len(urls),
            "snippet_lines": snippet_lines[:5],
            "has_substantive_content": len(snippet_lines) >= 2,
            "freshness": freshness,
        },
        source_urls=urls[:5],
        has_specific_values=has_values,
        is_empty=not content.strip(),
    )


def _extract_web_fetch(content: str) -> ExtractedData:
    """Extract structured data from web fetch output."""
    word_count = len(content.split())
    has_values = bool(
        re.search(r"\d+\.?\d*\s*°[CF]", content)
        or re.search(r"\$\d+[\d,.]*", content)
        or re.search(r"\d{1,2}:\d{2}", content)
    )

    return ExtractedData(
        intent=Intent.WEB_FETCH,
        raw_content=content,
        fields={
            "word_count": word_count,
            "preview": content[:500],
        },
        source_urls=[],
        has_specific_values=has_values,
        is_empty=word_count < 10,
    )


def _extract_shell(content: str) -> ExtractedData:
    """Extract structured data from shell command output."""
    is_error = (
        "command failed" in content.lower()
        or "not found" in content.lower()
        or "error" in content.lower()
        or "permission denied" in content.lower()
    )

    file_names = re.findall(r"(?:\S+\s+)?([\w.\-]+)", content)

    return ExtractedData(
        intent=Intent.SHELL,
        raw_content=content,
        fields={
            "file_names": file_names[:30],
            "file_count": len(file_names),
            "output_length": len(content),
        },
        has_specific_values=len(content.strip()) > 0,
        is_error=is_error,
        is_empty=not content.strip(),
    )


def _extract_code_exec(content: str) -> ExtractedData:
    """Extract structured data from code execution output."""
    is_error = "traceback" in content.lower() or "error" in content.lower()

    return ExtractedData(
        intent=Intent.CODE_EXEC,
        raw_content=content,
        fields={
            "output_length": len(content),
            "has_traceback": "traceback" in content.lower(),
        },
        has_specific_values=bool(content.strip()),
        is_error=is_error,
        is_empty=not content.strip(),
    )


def _extract_generic(intent: Intent, content: str) -> ExtractedData:
    """Fallback extraction for intents without specific templates."""
    return ExtractedData(
        intent=intent,
        raw_content=content,
        fields={"content_length": len(content)},
        has_specific_values=bool(content.strip()),
        is_empty=not content.strip(),
    )


# ── Extraction Router ───────────────────────────────────────────────

_EXTRACTORS = {
    Intent.WEB_SEARCH: _extract_web_search,
    Intent.WEB_FETCH: _extract_web_fetch,
    Intent.SHELL: _extract_shell,
    Intent.CODE_EXEC: _extract_code_exec,
    Intent.FILE_TASK: lambda c: _extract_generic(Intent.FILE_TASK, c),
    Intent.SYSINFO: lambda c: _extract_generic(Intent.SYSINFO, c),
    Intent.MEMORY_OP: lambda c: _extract_generic(Intent.MEMORY_OP, c),
    Intent.FILE_WRITE: lambda c: _extract_generic(Intent.FILE_WRITE, c),
    Intent.FILE_EDIT: lambda c: _extract_generic(Intent.FILE_EDIT, c),
}


# ── Sufficiency Checker ─────────────────────────────────────────────


def _check_sufficiency(
    extracted: ExtractedData,
    user_question: str,
) -> SufficiencyResult:
    """
    Check whether the extracted data is sufficient to answer the question.

    Uses heuristic rules (not LLM) for speed and reliability.
    The LLM is reserved for the synthesis phase.
    """
    if extracted.is_error:
        return SufficiencyResult(
            level=SufficiencyLevel.INSUFFICIENT,
            reason=f"Tool returned an error: {extracted.raw_content[:200]}",
        )

    # ── Intent-specific sufficiency rules ────────────────────────

    if extracted.intent == Intent.WEB_SEARCH:
        freshness = extracted.fields.get("freshness", {})
        if isinstance(freshness, dict) and freshness.get("stale_only"):
            today = freshness.get("today", "today")
            return SufficiencyResult(
                level=SufficiencyLevel.INSUFFICIENT,
                reason=f"Search results contained only dated data older than {today}; current data was not verified",
            )

        if extracted.is_empty:
            return SufficiencyResult(
                level=SufficiencyLevel.INSUFFICIENT,
                reason="Tool returned empty output",
            )
        # Search snippets are almost never sufficient for real answers.
        # They are teasers that point to full pages. Only mark SUFFICIENT
        # when snippets contain the exact answer (specific values).
        if extracted.has_specific_values:
            return SufficiencyResult(
                level=SufficiencyLevel.SUFFICIENT,
                reason="Search snippets contain specific values",
            )

        # If search has substantive content in snippets
        if extracted.fields.get("has_substantive_content"):
            # Check if the question is about time-sensitive data
            is_time_sensitive = _is_time_sensitive_query(user_question)
            if is_time_sensitive and not extracted.has_specific_values:
                urls = extracted.source_urls
                if urls:
                    return SufficiencyResult(
                        level=SufficiencyLevel.NEEDS_FOLLOWUP,
                        reason="Search snippets lack specific data for time-sensitive query",
                        followup_tool="web_fetch",
                        followup_args={"url": urls[0]},
                    )
                else:
                    return SufficiencyResult(
                        level=SufficiencyLevel.INSUFFICIENT,
                        reason="No URLs found in search results for follow-up fetch",
                    )
            # Non-time-sensitive with substantive snippets -> sufficient
            return SufficiencyResult(
                level=SufficiencyLevel.SUFFICIENT,
                reason="Search snippets contain substantive content",
            )

        # Link-only results (URLs without useful snippets) -> need web_fetch
        urls = extracted.source_urls
        if urls:
            return SufficiencyResult(
                level=SufficiencyLevel.NEEDS_FOLLOWUP,
                reason="Search returned link-only results, need web_fetch for actual data",
                followup_tool="web_fetch",
                followup_args={"url": urls[0]},
            )

        # No URLs at all -> insufficient
        return SufficiencyResult(
            level=SufficiencyLevel.INSUFFICIENT,
            reason="Search returned no results",
        )

    if extracted.is_empty:
        return SufficiencyResult(
            level=SufficiencyLevel.INSUFFICIENT,
            reason="Tool returned empty output",
        )

    if extracted.intent == Intent.WEB_FETCH:
        # Fetched page content is almost always sufficient for synthesis
        # — the LLM just needs to extract the answer from it.
        if extracted.has_specific_values:
            return SufficiencyResult(
                level=SufficiencyLevel.SUFFICIENT,
                reason="Fetched page contains specific data values",
            )
        if extracted.fields.get("word_count", 0) > 50:
            return SufficiencyResult(
                level=SufficiencyLevel.PARTIALLY_SUFFICIENT,
                reason="Fetched page has substantial content but no specific values detected",
            )
        return SufficiencyResult(
            level=SufficiencyLevel.INSUFFICIENT,
            reason="Fetched page has insufficient content",
        )

    # For SHELL, CODE_EXEC, FILE_TASK: non-empty output is sufficient
    if extracted.intent in (Intent.SHELL, Intent.CODE_EXEC, Intent.FILE_TASK):
        if extracted.has_specific_values:
            return SufficiencyResult(
                level=SufficiencyLevel.SUFFICIENT,
                reason=f"{extracted.intent.value} output is non-empty",
            )
        return SufficiencyResult(
            level=SufficiencyLevel.INSUFFICIENT,
            reason=f"{extracted.intent.value} returned empty or uninformative output",
        )

    # Default: treat as partially sufficient
    return SufficiencyResult(
        level=SufficiencyLevel.PARTIALLY_SUFFICIENT,
        reason="No specific sufficiency rule for this intent",
    )


# ── Synthesis Prompt Templates ──────────────────────────────────────

_SYNTHESIS_PROMPTS = {
    Intent.WEB_SEARCH: (
        "You are LocalMind's answer synthesizer. Transform the search results "
        "below into a clear, direct answer for the user.\n\n"
        "USER'S QUESTION: {question}\n\n"
        "SEARCH RESULTS:\n{data}\n\n"
        "RULES:\n"
        "1. Answer the question directly using ONLY the data above\n"
        "2. Cite sources by referencing the URLs\n"
        "3. If the data does not contain the answer, say so honestly\n"
        "4. Never fabricate specific numbers, dates, or facts\n"
        "5. If the data is insufficient, say so honestly instead of filling gaps from memory\n"
        "6. For current/time-sensitive questions, never present an explicitly older dated result as current\n"
        "7. Be concise but complete"
    ),
    Intent.WEB_FETCH: (
        "You are LocalMind's answer synthesizer. The user asked a question, and "
        "we fetched a web page to find the answer. Extract and summarize the "
        "specific information the user asked for.\n\n"
        "USER'S QUESTION: {question}\n\n"
        "PAGE CONTENT:\n{data}\n\n"
        "RULES:\n"
        "1. Answer the question directly using ONLY the page content above\n"
        "2. Extract specific numbers, dates, temperatures, prices, etc. from the content\n"
        "3. If the page doesn't contain the answer, say so honestly\n"
        "4. Never add information from your training data\n"
        "5. Be concise — give the key facts the user asked for, not the entire page\n"
        "6. Format the answer in a clean, readable way"
    ),
    Intent.SHELL: (
        "You are LocalMind's answer synthesizer. Report the shell command results "
        "to the user clearly and accurately.\n\n"
        "USER'S QUESTION: {question}\n\n"
        "COMMAND OUTPUT:\n{data}\n\n"
        "RULES:\n"
        "1. Report EXACTLY what the output shows - zero fabrication\n"
        "2. If listing a directory, only report items actually in the output\n"
        "3. Format the output for readability\n"
        "4. If the command failed, explain the error plainly"
    ),
    Intent.CODE_EXEC: (
        "You are LocalMind's answer synthesizer. Report the code execution results "
        "to the user.\n\n"
        "USER'S QUESTION: {question}\n\n"
        "EXECUTION OUTPUT:\n{data}\n\n"
        "RULES:\n"
        "1. Report the actual output - do not paraphrase or fabricate\n"
        "2. If there were errors, explain what went wrong\n"
        "3. If the output is long, summarize the key results"
    ),
}

# Dedicated prompt for combined search + fetch synthesis.
# This is the PRIMARY synthesis path for web queries — the search found
# relevant pages and we fetched the actual content. The LLM must
# summarize the fetched page content into a clean answer.
_COMBINED_SYNTHESIS_PROMPT = (
    "You are LocalMind's answer synthesizer. The user asked a question, and "
    "we searched the web and fetched the most relevant page to find the answer.\n\n"
    "USER'S QUESTION: {question}\n\n"
    "FETCHED PAGE CONTENT (this is the primary source — use it):\n{page_content}\n\n"
    "SEARCH SNIPPETS (for context — the page content takes priority):\n{search_snippets}\n\n"
    "RULES:\n"
    "1. Answer the question directly using the fetched page content above\n"
    "2. Extract specific numbers, dates, temperatures, prices, schedules, etc.\n"
    "3. If the fetched page doesn't fully answer the question, say what you found "
    "and note what's missing\n"
    "4. NEVER add information from your training data — only use the content above\n"
    "5. Be CONCISE — give the key facts the user asked for, not the entire page\n"
    "6. Format for readability with a Markdown table by DEFAULT for structured "
    "data. A WEATHER answer MUST be a GitHub-flavored Markdown table — for a "
    "current-conditions query use a two-column `| Metric | Value |` table "
    "(Temperature, Conditions, Wind, Precipitation, Humidity, UV, Pressure, …); "
    "for a forecast use `| Time | Conditions | Temp |` with one row per hour/day "
    "and a weather emoji (☀️ ⛅ 🌧️ ⛈️) in the conditions cell. Do the same for any "
    "other tabular answer (prices, schedules, specs, comparisons): a header row "
    "then one row per item. Never put raw HTML like <br> in a cell — use separate "
    "rows instead. Add a one-line intro before the table and a short takeaway "
    "after. Use bullet points only for genuinely non-tabular lists.\n"
    "7. Cite the source URL if available"
)

_GAP_REPORT_TEMPLATE = "I wasn't able to find the specific information you asked for. {reason}\n\n{suggestion}"

_GAP_SUGGESTIONS = {
    SufficiencyLevel.INSUFFICIENT: (
        "You could try rephrasing your question, or I can search with different terms if you'd like."
    ),
    SufficiencyLevel.NEEDS_FOLLOWUP: (
        "I found some relevant results but need to read the actual page "
        "content to get the specific details. Let me fetch that for you."
    ),
}


# ── Smart Data Extraction (regex fallback) ──────────────────────────


def _smart_extract_key_data(content: str, user_question: str) -> str:
    """
    When the LLM synthesis fails entirely, use regex to extract the
    most relevant data points from the content. This is a LAST RESORT
    that produces a readable answer without dumping raw HTML/text.

    Returns a structured summary of key findings, not the raw content.
    """
    if not content:
        return "No data was found."

    findings = []

    # Extract temperatures
    temps = re.findall(r"(-?\d+\.?\d*)\s*°\s*([CF])", content)
    if temps:
        temp_strs = [f"{t}°{u}" for t, u in temps[:10]]
        findings.append(f"Temperatures: {', '.join(temp_strs)}")

    # Extract percentages (humidity, chance of rain, etc.)
    percentages = re.findall(r"(\d+)%", content)
    if percentages:
        findings.append(f"Percentages found: {', '.join(percentages[:5])}%")

    # Extract prices
    prices = re.findall(r"\$\d+[\d,.]*", content)
    if prices:
        findings.append(f"Prices: {', '.join(prices[:5])}")

    # Extract times
    times = re.findall(r"\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?", content)
    if times:
        findings.append(f"Times: {', '.join(times[:5])}")

    # Extract dates
    dates = re.findall(
        r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\s+\d{1,2}|\d{1,2}/\d{1,2}/\d{2,4}|\w+ \d{1,2},? \d{4}",
        content,
    )
    if dates:
        findings.append(f"Dates: {', '.join(dates[:5])}")

    # Extract wind speeds
    winds = re.findall(r"(\w{1,3}\s+)?(\d+)\s*mph", content, re.IGNORECASE)
    if winds:
        wind_strs = [f"{d}{s}mph" for d, s in winds[:5]]
        findings.append(f"Wind: {', '.join(wind_strs)}")

    # Extract key phrases from the first ~1000 chars (headings, summary text)
    first_section = content[:1000]
    meaningful_lines = [
        line.strip()
        for line in first_section.split("\n")
        if line.strip()
        and len(line.strip()) > 15
        and len(line.strip()) < 120
        and not line.strip().startswith("http")
        and not line.strip().startswith("Advertisement")
    ]
    if meaningful_lines:
        findings.append(f"Key details: {meaningful_lines[0]}")
        if len(meaningful_lines) > 1:
            findings.append(f"  {meaningful_lines[1]}")

    if findings:
        return (
            "Here's what I found:\n\n"
            + "\n".join(f"- {f}" for f in findings)
            + "\n\n(Note: The full answer could not be generated due to a processing issue. "
            "The data above was extracted automatically.)"
        )

    # Absolute last resort: first 500 chars of cleaned content
    cleaned = _preprocess_web_content(content, user_question)
    if len(cleaned) > 500:
        cleaned = cleaned[:500] + "..."
    return f"Partial content found:\n\n{cleaned}"


# ── AnswerSynthesizer ───────────────────────────────────────────────


class AnswerSynthesizer:
    """
    Post-tool reasoning layer that transforms raw tool output into
    user-facing answers.

    Pipeline:
        Tool Output -> Extract -> Check Sufficiency -> LLM Synthesize -> Answer

    The LLM synthesis is the PRIMARY path. Template fallbacks and raw
    output are last-resort measures only. The synthesizer NEVER dumps
    raw web content to the user.
    """

    def __init__(self, enabled: bool = True, timeout_secs: int = 30):
        self.enabled = enabled
        self.timeout_secs = timeout_secs

    async def synthesize(
        self,
        tool_results: list[ToolResult],
        intent: Intent,
        user_question: str,
        adapter=None,
    ) -> SynthesisResult:
        """
        Run the full extraction -> sufficiency -> LLM synthesis pipeline.

        Args:
            tool_results: List of ToolResult objects from the agent loop.
            intent: The effective intent for this turn.
            user_question: The user's original message.
            adapter: LLM adapter for synthesis calls (optional; if None,
                     falls back to template-based synthesis).

        Returns:
            A SynthesisResult with the answer or gap report.
        """
        if not self.enabled:
            # Synthesis disabled — return first tool result as-is
            if tool_results:
                return SynthesisResult(
                    answer=tool_results[0].content,
                    is_synthesized=False,
                )
            return SynthesisResult(
                answer="No results available.",
                is_synthesized=False,
                is_gap_report=True,
            )

        try:
            # ── Phase 1: Extraction ───────────────────────────────
            extracted = self._extract(tool_results, intent, user_question)

            # ── Phase 2: Sufficiency Check ────────────────────────
            sufficiency = _check_sufficiency(extracted, user_question)

            logger.info(
                f"[synthesizer] intent={intent.value} "
                f"sufficiency={sufficiency.level.value} "
                f"reason={sufficiency.reason[:80]}"
            )

            # Handle follow-up need
            if sufficiency.level == SufficiencyLevel.NEEDS_FOLLOWUP:
                return SynthesisResult(
                    answer="",
                    needs_followup=True,
                    followup_tool=sufficiency.followup_tool,
                    followup_args=sufficiency.followup_args,
                )

            # Handle insufficient data — produce gap report
            if sufficiency.level == SufficiencyLevel.INSUFFICIENT:
                return self._produce_gap_report(sufficiency, user_question)

            # ── Phase 3: LLM Synthesis (PRIMARY PATH) ────────────
            if adapter:
                answer = await self._llm_synthesize(extracted, user_question, intent, adapter)
            else:
                answer = self._template_synthesize(extracted, user_question, intent)

            return SynthesisResult(
                answer=answer,
                is_synthesized=True,
            )

        except asyncio.TimeoutError:
            logger.warning("[synthesizer] Synthesis timed out — using smart extraction fallback")
            # NEVER dump raw content — use smart extraction
            if tool_results:
                combined = "\n\n".join(r.content for r in tool_results if r.content)
                return SynthesisResult(
                    answer=_smart_extract_key_data(combined, user_question),
                    is_synthesized=False,
                )
            return SynthesisResult(
                answer="I encountered a timeout while processing the results.",
                is_synthesized=False,
                is_gap_report=True,
            )
        except Exception as e:
            logger.error(f"[synthesizer] Synthesis failed: {e}")
            # NEVER dump raw content — use smart extraction
            if tool_results:
                combined = "\n\n".join(r.content for r in tool_results if r.content)
                return SynthesisResult(
                    answer=_smart_extract_key_data(combined, user_question),
                    is_synthesized=False,
                )
            return SynthesisResult(
                answer="An error occurred while processing the results.",
                is_synthesized=False,
                is_gap_report=True,
            )

    async def synthesize_combined(
        self,
        search_result: ToolResult,
        fetch_result: ToolResult,
        user_question: str,
        adapter=None,
    ) -> SynthesisResult:
        """
        Synthesize a combined answer from web_search + web_fetch results.

        This is the PRIMARY synthesis path for web queries. The search
        found relevant pages, we fetched the actual content, and now the
        LLM must produce a clean, human-readable summary.

        The fetched page content takes priority over search snippets —
        snippets are teasers, the page has the actual data.

        Args:
            search_result: The web_search ToolResult (URLs + snippets)
            fetch_result: The web_fetch ToolResult (full page content)
            user_question: The user's original question
            adapter: LLM adapter for synthesis

        Returns:
            SynthesisResult with the LLM-summarized answer
        """
        if not self.enabled:
            # Synthesis disabled — use smart extraction instead of raw dump
            combined = f"{search_result.content}\n\n{fetch_result.content}"
            return SynthesisResult(
                answer=_smart_extract_key_data(combined, user_question),
                is_synthesized=False,
            )

        search_snippets = search_result.content or ""
        page_content = fetch_result.content or ""

        # Pre-process the fetched page content to remove noise
        page_content = _preprocess_web_content(page_content, user_question)

        # Extract the most relevant section if the page is very long
        if len(page_content) > 6000:
            page_content = _extract_relevant_section(page_content, user_question)

        if not adapter:
            # No adapter — use smart extraction (NOT raw dump)
            combined = f"{search_snippets}\n\n{page_content}"
            return SynthesisResult(
                answer=_smart_extract_key_data(combined, user_question),
                is_synthesized=False,
            )

        try:
            answer = await self._llm_synthesize_combined(
                search_snippets=search_snippets,
                page_content=page_content,
                user_question=user_question,
                adapter=adapter,
            )
            return SynthesisResult(
                answer=answer,
                is_synthesized=True,
            )
        except asyncio.TimeoutError:
            logger.warning("[synthesizer] Combined synthesis timed out — retrying with shorter content")
            # Retry once with shorter content
            try:
                shorter_page = page_content[:2000] if len(page_content) > 2000 else page_content
                answer = await self._llm_synthesize_combined(
                    search_snippets=search_snippets[:500],
                    page_content=shorter_page,
                    user_question=user_question,
                    adapter=adapter,
                )
                return SynthesisResult(answer=answer, is_synthesized=True)
            except Exception:
                pass
            # Final fallback: smart extraction
            combined = f"{search_snippets}\n\n{page_content}"
            return SynthesisResult(
                answer=_smart_extract_key_data(combined, user_question),
                is_synthesized=False,
            )
        except Exception as e:
            logger.error(f"[synthesizer] Combined synthesis failed: {e}")
            # Retry once with shorter content
            try:
                shorter_page = page_content[:2000] if len(page_content) > 2000 else page_content
                answer = await self._llm_synthesize_combined(
                    search_snippets=search_snippets[:500],
                    page_content=shorter_page,
                    user_question=user_question,
                    adapter=adapter,
                )
                return SynthesisResult(answer=answer, is_synthesized=True)
            except Exception:
                pass
            # Final fallback: smart extraction
            combined = f"{search_snippets}\n\n{page_content}"
            return SynthesisResult(
                answer=_smart_extract_key_data(combined, user_question),
                is_synthesized=False,
            )

    def _extract(
        self,
        tool_results: list[ToolResult],
        intent: Intent,
        user_question: str = "",
    ) -> ExtractedData:
        """Run extraction on the accumulated tool results."""
        combined_content = "\n\n".join(r.content for r in tool_results if r.content)
        if intent == Intent.WEB_SEARCH:
            return _extract_web_search(
                combined_content,
                today=date.today(),
                user_question=user_question,
            )

        extractor = _EXTRACTORS.get(intent, _extract_generic)
        return extractor(combined_content)

    async def _llm_synthesize(
        self,
        extracted: ExtractedData,
        user_question: str,
        intent: Intent,
        adapter,
    ) -> str:
        """
        Use the LLM to synthesize a user-facing answer.

        This is the PRIMARY synthesis method. The LLM receives the
        (pre-processed) data and produces a clean summary.
        """
        prompt_template = _SYNTHESIS_PROMPTS.get(intent, _SYNTHESIS_PROMPTS[Intent.SHELL])

        # Pre-process web content before sending to LLM
        raw_data = extracted.raw_content
        if intent in (Intent.WEB_FETCH, Intent.WEB_SEARCH):
            raw_data = _preprocess_web_content(raw_data, user_question)

        # Extract relevant section for very long content
        if len(raw_data) > 6000:
            raw_data = _extract_relevant_section(raw_data, user_question)

        # Truncate data to prevent context overflow
        # 8000 chars is enough for the LLM to work with while leaving
        # room for the prompt and response in the context window
        max_data_chars = 8000
        data = raw_data[:max_data_chars]
        if len(raw_data) > max_data_chars:
            data += f"\n\n[... {len(raw_data) - max_data_chars} more characters available ...]"

        prompt = prompt_template.format(
            question=user_question,
            data=data,
        )

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_question},
        ]

        # Collect the full response with timeout
        full_response: list[str] = []

        async def _collect():
            async for chunk in adapter.chat(
                messages,
                temperature=0.3,
                intent="chat",
            ):
                if chunk.error:
                    logger.warning("[synthesizer] adapter error: %s", chunk.error[:120])
                    break
                if chunk.text:
                    full_response.append(chunk.text)

        try:
            await asyncio.wait_for(_collect(), timeout=self.timeout_secs)
        except asyncio.TimeoutError:
            # First attempt timed out — retry once with shorter data
            logger.warning("[synthesizer] LLM synthesis timed out on first attempt, retrying with shorter data")
            full_response.clear()
            shorter_data = raw_data[:3000]
            if len(raw_data) > 3000:
                shorter_data += "\n\n[... content truncated for faster processing ...]"

            prompt = prompt_template.format(
                question=user_question,
                data=shorter_data,
            )
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_question},
            ]

            async def _collect_retry():
                async for chunk in adapter.chat(
                    messages,
                    temperature=0.3,
                    intent="chat",
                ):
                    if chunk.error:
                        logger.warning("[synthesizer] adapter error (retry): %s", chunk.error[:120])
                        break
                    if chunk.text:
                        full_response.append(chunk.text)

            await asyncio.wait_for(_collect_retry(), timeout=self.timeout_secs)

        answer = "".join(full_response).strip()

        # Post-synthesis fabrication check
        answer = self._filter_synthesis(answer)

        # If the LLM returned empty or a near-empty response (less than 10
        # chars — e.g. just a newline or a single word with no substance),
        # fall back to smart extraction. This catches cases where Gemini's
        # safety filter produces a 1-token response that technically isn't
        # empty but has no useful content.
        if not answer or len(answer) < 10:
            logger.warning(
                "[synthesizer] LLM returned %d chars — falling back to smart extraction",
                len(answer),
            )
            _smart = _smart_extract_key_data(extracted.raw_content, user_question)
            if _smart:
                return _smart
            # If smart extraction also fails, return whatever we got (even
            # if it's empty) rather than nothing
            return answer or "Unable to generate a response from the available data."

        return answer

    async def _llm_synthesize_combined(
        self,
        search_snippets: str,
        page_content: str,
        user_question: str,
        adapter,
    ) -> str:
        """
        Use the LLM to synthesize a combined answer from search + fetch.

        This uses a dedicated prompt that prioritizes the fetched page
        content over the search snippets.
        """
        prompt = _COMBINED_SYNTHESIS_PROMPT.format(
            question=user_question,
            page_content=page_content[:6000],
            search_snippets=search_snippets[:1000],
        )

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_question},
        ]

        # Collect the full response with timeout
        full_response: list[str] = []

        async def _collect():
            async for chunk in adapter.chat(
                messages,
                temperature=0.3,
                intent="chat",
            ):
                if chunk.error:
                    logger.warning("[synthesizer] adapter error: %s", chunk.error[:120])
                    break
                if chunk.text:
                    full_response.append(chunk.text)

        await asyncio.wait_for(_collect(), timeout=self.timeout_secs)

        answer = "".join(full_response).strip()

        # Post-synthesis fabrication check
        answer = self._filter_synthesis(answer)

        # Same short-response fallback as _llm_synthesize — catches safety
        # filter blocks that produce 1-token responses.
        if not answer or len(answer) < 10:
            logger.warning(
                "[synthesizer] combined LLM returned %d chars — falling back to smart extraction",
                len(answer),
            )
            combined = f"{search_snippets}\n\n{page_content}"
            _smart = _smart_extract_key_data(combined, user_question)
            if _smart:
                return _smart
            return answer or "Unable to generate a response from the available data."

        return answer

    def _template_synthesize(
        self,
        extracted: ExtractedData,
        user_question: str,
        intent: Intent,
    ) -> str:
        """
        Template-based synthesis (no LLM) — LAST RESORT.

        Uses smart extraction to produce a structured answer from the
        data. NEVER dumps raw content to the user.
        """
        content = extracted.raw_content

        # For web content, use smart extraction instead of raw dump
        if intent in (Intent.WEB_SEARCH, Intent.WEB_FETCH):
            return _smart_extract_key_data(content, user_question)

        if intent == Intent.SHELL:
            # Shell output is usually self-explanatory, just format it
            return f"Here are the results:\n\n{content[:2000]}"

        if intent == Intent.CODE_EXEC:
            return f"Code execution output:\n\n{content[:2000]}"

        # Generic: use smart extraction
        return _smart_extract_key_data(content, user_question)

    def _produce_gap_report(
        self,
        sufficiency: SufficiencyResult,
        user_question: str,
    ) -> SynthesisResult:
        """Produce an honest gap report when data is insufficient."""
        reason = sufficiency.reason
        suggestion = _GAP_SUGGESTIONS.get(
            sufficiency.level,
            "You could try rephrasing your question or asking something different.",
        )

        answer = _GAP_REPORT_TEMPLATE.format(
            reason=reason,
            suggestion=suggestion,
        )

        return SynthesisResult(
            answer=answer,
            is_synthesized=True,
            is_gap_report=True,
        )

    @staticmethod
    def _filter_synthesis(text: str) -> str:
        """
        Filter common fabrication patterns from synthesis output.

        Catches cases where the LLM fabricates specific data despite
        instructions not to.
        """
        fabricated_patterns = [
            re.compile(r"Volume Serial Number", re.IGNORECASE),
            re.compile(r"Directory of\s+[A-Za-z]:", re.IGNORECASE),
            re.compile(r"\d+ File\(s\)\s+\d+ bytes", re.IGNORECASE),
        ]
        for pattern in fabricated_patterns:
            if pattern.search(text):
                return (
                    text[:500] + "\n\n[Note: Some content was filtered because it "
                    "appeared to be fabricated rather than derived from "
                    "actual tool results.]"
                )
        return text
