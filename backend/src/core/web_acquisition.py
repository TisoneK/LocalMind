"""
Session 340 — Adaptive Web Acquisition System.

The user's diagnosis:
  > The solution is not "add a browser tool." The solution is to make web
  > access an adaptive acquisition system where static fetch, JavaScript
  > rendering, structured network data, and source fallback are strategies
  > behind one capability.

Architecture:

                    PARENT AGENT
                         │
                         │ Information needed
                         ▼
                 WEB RESEARCH TASK
                         │
                         ▼
                SOURCE DISCOVERY (web_search)
                         │
                         ▼
               ACQUISITION ROUTER
                         │
             ┌───────────┼───────────┐
             ▼           ▼           ▼
          FETCH       BROWSER      NETWORK
          (httpx)     (read/open)  (XHR/fetch)
             │           │           │
             └───────────┼───────────┘
                         ▼
                  NORMALIZATION
                         │
                         ▼
                    VALIDATION
                         │
                    ┌────┴────┐
                    ▼         ▼
                 SUCCESS    FALLBACK
                    │         │
                    └────┬────┘
                         ▼
                    FINAL DATA
                         │
                         ▼
                    PARENT AGENT

Key principles (the user's 7 recommendations):
  1. Search → discovery, not the answer
  2. Fetch → acquisition layer with multiple strategies
  3. Browser → first-class capability (not a last-resort hack)
  4. WebResearchTask → high-level operation (not raw tools)
  5. Validation → did we actually get the requested data?
  6. Failure → automatic escalation (not "ask user what to do")
  7. Tool abstraction → user never sees internal mechanics

Acquisition strategies (progressive escalation):
  Strategy A — Static fetch (httpx GET + HTML parse) — fastest, cheapest
  Strategy B — Browser read (agent-browser read [url]) — JS rendering, one-shot
  Strategy C — Browser open (agent-browser open + snapshot + text) — full interactive
  Strategy D — Alternative source (try the next search result)

The router tries A → B → C → D, validating at each step. If a strategy
returns empty/boilerplate content, it escalates automatically.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


# ── Acquisition result ──────────────────────────────────────────────────────


class AcquisitionStatus(Enum):
    """The status of a web acquisition attempt."""

    SUCCESS = "success"  # got the requested data
    PARTIAL = "partial"  # got something, but may not be the requested data
    FAILED = "failed"  # got nothing useful
    ESCALATED = "escalated"  # this strategy failed, trying the next


class AcquisitionMethod(Enum):
    """How the data was acquired."""

    STATIC_FETCH = "static_fetch"  # httpx GET + HTML parse
    BROWSER_READ = "browser_read"  # agent-browser read [url] (JS render)
    BROWSER_OPEN = "browser_open"  # agent-browser open + snapshot + text
    SEARCH_ONLY = "search_only"  # only snippets available, no full content


@dataclass
class WebResult:
    """The result of a web acquisition attempt.

    Follows the user's acquisition contract:
      WebResult {
          status
          source
          acquisition_method
          content
          structured_data
          freshness
          confidence
      }
    """

    status: AcquisitionStatus
    source: str  # URL
    acquisition_method: AcquisitionMethod
    content: str  # the extracted text
    structured_data: Optional[dict] = None  # tables, JSON, etc.
    freshness: Optional[str] = None  # date string if detectable
    confidence: float = 0.0  # 0.0-1.0 — how confident we got the requested data
    error: Optional[str] = None  # if FAILED, why
    attempted_strategies: list[str] = field(default_factory=list)

    def is_success(self) -> bool:
        return self.status == AcquisitionStatus.SUCCESS

    def to_tool_result_content(self) -> str:
        """Format for ToolResult.content — what the parent agent sees."""
        if self.is_success():
            method_label = {
                AcquisitionMethod.STATIC_FETCH: "static fetch",
                AcquisitionMethod.BROWSER_READ: "JS-rendered (browser read)",
                AcquisitionMethod.BROWSER_OPEN: "JS-rendered (browser interactive)",
                AcquisitionMethod.SEARCH_ONLY: "search snippets only",
            }.get(self.acquisition_method, "unknown")
            parts = [
                f"**Source:** {self.source}",
                f"**Acquisition method:** {method_label}",
            ]
            if self.freshness:
                parts.append(f"**Freshness:** {self.freshness}")
            parts.append(f"**Confidence:** {self.confidence:.0%}")
            parts.append("")
            parts.append(self.content)
            return "\n".join(parts)
        elif self.status == AcquisitionStatus.PARTIAL:
            parts = [
                f"**Source:** {self.source}",
                f"**Acquisition method:** {self.acquisition_method.value}",
                f"**Confidence:** {self.confidence:.0%} (partial — content may be incomplete)",
                "",
                self.content,
            ]
            return "\n".join(parts)
        else:
            return (
                f"**Acquisition failed** for {self.source}.\n"
                f"**Attempted strategies:** {', '.join(self.attempted_strategies) or 'none'}\n"
                f"**Error:** {self.error or 'unknown'}\n"
                f"**Recommendation:** try a different source or rephrase the query."
            )


# ── Content validation ──────────────────────────────────────────────────────


# Boilerplate markers — if the extracted content is mostly these, it's not
# real data. Catches the "Premier League Table / Navigation / Footer /
# Advertisement" failure the user described.
_BOILERPLATE_MARKERS = [
    "javascript",
    "please enable javascript",
    "enable javascript",
    "we use cookies",
    "accept cookies",
    "cookie preferences",
    "sign in",
    "sign up",
    "log in",
    "register",
    "subscribe",
    "newsletter",
    "advertisement",
    "sponsored",
    "related articles",
    "you may also like",
    "recommended",
    "trending",
    "most popular",
    "privacy policy",
    "terms of service",
    "all rights reserved",
    "copyright",
    "menu",
    "navigation",
    "footer",
    "header",
    "sidebar",
    "skip to content",
    "skip to main",
]


def _is_boilerplate(content: str) -> bool:
    """Return True if the content is mostly navigation/boilerplate, not real data."""
    if not content or len(content.strip()) < 50:
        return True
    lower = content.lower()
    marker_count = sum(1 for marker in _BOILERPLATE_MARKERS if marker in lower)
    stripped_len = len(content.strip())
    # Only flag as boilerplate if:
    # 1. Very short (<200 chars) AND has ≥2 markers, OR
    # 2. Short (<500 chars) AND has ≥4 markers (lots of nav, little content)
    # Real articles with 500+ chars are never boilerplate even if they have
    # some nav markers at the edges.
    if stripped_len < 200 and marker_count >= 2:
        return True
    if stripped_len < 500 and marker_count >= 4:
        return True
    return False


def _extract_freshness(content: str) -> Optional[str]:
    """Try to extract a date from the content for freshness checking."""
    if not content:
        return None
    # Look for common date patterns
    date_patterns = [
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b",
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,2}/\d{1,2}/\d{4}\b",
        r"\b\d{4}\b",
    ]
    for pattern in date_patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def _score_content(content: str, query: str) -> float:
    """Score how well the content matches the query (0.0-1.0).

    Simple keyword-overlap heuristic — not a full semantic match, but
    catches the "got navigation instead of EPL table" failure.
    """
    if not content:
        return 0.0
    if not query:
        return 0.5  # no signal — neutral
    if _is_boilerplate(content):
        return 0.0
    # Tokenize the query (drop stopwords)
    stopwords = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                 "have", "has", "had", "do", "does", "did", "will", "would",
                 "could", "should", "may", "might", "must", "can", "of", "in",
                 "on", "at", "to", "for", "with", "and", "or", "but", "not",
                 "from", "by", "as", "this", "that", "these", "those", "i",
                 "you", "he", "she", "it", "we", "they", "me", "him", "her",
                 "us", "them", "my", "your", "his", "its", "our", "their",
                 "give", "me", "please", "what", "whats", "show", "tell"}
    query_words = set(
        w.lower() for w in re.findall(r"\w+", query)
        if w.lower() not in stopwords and len(w) > 2
    )
    if not query_words:
        return 0.5  # no signal — neutral
    content_lower = content.lower()
    # Use substring match (not exact word match) — "standings" matches
    # "standing" and "table" matches "tables". This is more forgiving
    # for the keyword-overlap heuristic.
    hits = 0
    for w in query_words:
        # Check if the word or its stem (first 4 chars) appears in the content
        if w in content_lower or w[:4] in content_lower:
            hits += 1
    return min(1.0, hits / len(query_words))


# ── Acquisition strategies ──────────────────────────────────────────────────


async def _static_fetch(url: str, timeout: int = 15) -> WebResult:
    """Strategy A: httpx GET + HTML parse. Fastest, cheapest.

    Uses the existing web_fetch tool's extraction logic (no JS execution).
    """
    from tools.web_fetch import web_fetch

    try:
        result = await web_fetch(url)
        if result.success and result.content:
            return WebResult(
                status=AcquisitionStatus.SUCCESS,
                source=url,
                acquisition_method=AcquisitionMethod.STATIC_FETCH,
                content=result.content,
                confidence=0.7,  # static fetch is decent but may miss JS content
                freshness=_extract_freshness(result.content),
                attempted_strategies=["static_fetch"],
            )
        else:
            return WebResult(
                status=AcquisitionStatus.FAILED,
                source=url,
                acquisition_method=AcquisitionMethod.STATIC_FETCH,
                content="",
                error=result.content or "static fetch returned no content",
                attempted_strategies=["static_fetch"],
            )
    except Exception as e:
        return WebResult(
            status=AcquisitionStatus.FAILED,
            source=url,
            acquisition_method=AcquisitionMethod.STATIC_FETCH,
            content="",
            error=f"static_fetch exception: {e}",
            attempted_strategies=["static_fetch"],
        )


async def _browser_read(url: str, timeout: int = 30) -> WebResult:
    """Strategy B: agent-browser read [url]. JS rendering in one shot.

    Uses the agent-browser CLI's `read` command, which opens the page,
    waits for JS to execute, and extracts the rendered text. Much lighter
    than the full open→snapshot→text cycle.
    """
    try:
        from tools.browser_agent import _run_browser_cmd

        # agent-browser read [url] — one-shot JS-rendered text extraction
        returncode, stdout, stderr = await _run_browser_cmd(
            ["read", url], timeout=timeout
        )
        if returncode == 0 and stdout and stdout.strip():
            content = stdout.strip()
            return WebResult(
                status=AcquisitionStatus.SUCCESS,
                source=url,
                acquisition_method=AcquisitionMethod.BROWSER_READ,
                content=content,
                confidence=0.85,  # JS-rendered is more complete
                freshness=_extract_freshness(content),
                attempted_strategies=["browser_read"],
            )
        else:
            return WebResult(
                status=AcquisitionStatus.FAILED,
                source=url,
                acquisition_method=AcquisitionMethod.BROWSER_READ,
                content="",
                error=stderr or "browser read returned no content",
                attempted_strategies=["browser_read"],
            )
    except Exception as e:
        return WebResult(
            status=AcquisitionStatus.FAILED,
            source=url,
            acquisition_method=AcquisitionMethod.BROWSER_READ,
            content="",
            error=f"browser_read exception: {e}",
            attempted_strategies=["browser_read"],
        )


# ── The router ──────────────────────────────────────────────────────────────


async def acquire_web_content(
    url: str,
    query: str = "",
    max_strategies: int = 3,
    confidence_threshold: float = 0.3,
) -> WebResult:
    """Acquire web content from a URL using progressive escalation.

    The router tries strategies in order:
      1. Static fetch (httpx GET + HTML parse) — fastest
      2. Browser read (agent-browser read [url]) — JS rendering
      3. (Future) Browser open + snapshot — full interactive

    At each step, the result is validated:
      - Is it boilerplate? → escalate
      - Does it match the query? → if confidence < threshold, escalate
      - Is it empty? → escalate

    If all strategies fail, returns a FAILED result with the attempted
    strategies listed.

    Args:
        url: the URL to acquire content from
        query: the user's original query (for relevance scoring)
        max_strategies: max strategies to try (default 3)
        confidence_threshold: minimum confidence to accept (default 0.3)

    Returns:
        WebResult with the best content found, or a FAILED result.
    """
    attempted: list[str] = []

    # Strategy A: static fetch
    if max_strategies >= 1:
        result = await _static_fetch(url)
        attempted.append("static_fetch")
        if result.is_success():
            # Validate: is it boilerplate? Does it match the query?
            score = _score_content(result.content, query) if query else 0.5
            result.confidence = max(result.confidence, score)
            if not _is_boilerplate(result.content) and score >= confidence_threshold:
                result.attempted_strategies = attempted
                logger.info(
                    "[web-acquire] static_fetch succeeded for %s (confidence=%.2f)",
                    url[:80],
                    result.confidence,
                )
                return result
            logger.info(
                "[web-acquire] static_fetch returned boilerplate/low-confidence "
                "for %s (score=%.2f) — escalating to browser_read",
                url[:80],
                score,
            )
        else:
            logger.info(
                "[web-acquire] static_fetch failed for %s — escalating to browser_read",
                url[:80],
            )

    # Strategy B: browser read (JS rendering)
    if max_strategies >= 2:
        result = await _browser_read(url)
        attempted.append("browser_read")
        if result.is_success():
            score = _score_content(result.content, query) if query else 0.5
            result.confidence = max(result.confidence, score)
            if not _is_boilerplate(result.content) and score >= confidence_threshold:
                result.attempted_strategies = attempted
                logger.info(
                    "[web-acquire] browser_read succeeded for %s (confidence=%.2f)",
                    url[:80],
                    result.confidence,
                )
                return result
            logger.info(
                "[web-acquire] browser_read returned boilerplate/low-confidence "
                "for %s (score=%.2f)",
                url[:80],
                score,
            )
        else:
            logger.info(
                "[web-acquire] browser_read failed for %s: %s",
                url[:80],
                result.error,
            )

    # All strategies failed or returned low-confidence content
    # Return the last result (or a synthesized failure)
    if "result" in locals() and result.content:
        # We got SOMETHING — return it as PARTIAL
        result.status = AcquisitionStatus.PARTIAL
        result.attempted_strategies = attempted
        return result

    return WebResult(
        status=AcquisitionStatus.FAILED,
        source=url,
        acquisition_method=AcquisitionMethod.STATIC_FETCH,  # best-effort label
        content="",
        error="all acquisition strategies failed",
        attempted_strategies=attempted,
    )


async def web_research(
    query: str,
    max_sources: int = 3,
    freshness_required: bool = False,
) -> WebResult:
    """High-level web research operation.

    The parent agent calls this instead of web_search + web_fetch directly.
    Internally:
      1. Search for sources (web_search)
      2. Rank candidates by authority/freshness
      3. Try static fetch on the top candidate
      4. If that fails, escalate to browser_read
      5. If that fails, try the next source
      6. Validate the result
      7. Return the best content

    This keeps the parent agent at the intent level:
      "I need current EPL standings" → web_research("current EPL standings")

    The user never sees web_search/web_fetch/browser mechanics.
    """
    from tools.web_search import web_search

    logger.info("[web-research] starting for query=%r", query[:80])

    # Step 1: discover sources
    search_result = await web_search(query)
    if not search_result.success:
        return WebResult(
            status=AcquisitionStatus.FAILED,
            source="(search)",
            acquisition_method=AcquisitionMethod.SEARCH_ONLY,
            content="",
            error="web_search failed — no sources discovered",
            attempted_strategies=["web_search"],
        )

    # Extract URLs from the search result
    urls = _extract_urls_from_search(search_result.content)
    if not urls:
        # No URLs — return the search snippets as a SEARCH_ONLY result
        return WebResult(
            status=AcquisitionStatus.PARTIAL,
            source="(search snippets)",
            acquisition_method=AcquisitionMethod.SEARCH_ONLY,
            content=search_result.content,
            confidence=0.3,
            attempted_strategies=["web_search"],
        )

    logger.info(
        "[web-research] discovered %d sources, trying top %d",
        len(urls),
        min(max_sources, len(urls)),
    )

    # Step 2-6: try each source with progressive escalation
    best_result: Optional[WebResult] = None
    for i, url in enumerate(urls[:max_sources]):
        logger.info(
            "[web-research] trying source %d/%d: %s",
            i + 1,
            min(max_sources, len(urls)),
            url[:80],
        )
        result = await acquire_web_content(url, query=query)
        if result.is_success():
            return result  # got it — return immediately
        if result.status == AcquisitionStatus.PARTIAL:
            # Keep the best partial result as a fallback
            if best_result is None or result.confidence > best_result.confidence:
                best_result = result

    # All sources failed — return the best partial or a failure
    if best_result:
        return best_result

    return WebResult(
        status=AcquisitionStatus.FAILED,
        source="(multiple)",
        acquisition_method=AcquisitionMethod.STATIC_FETCH,
        content="",
        error=f"all {len(urls[:max_sources])} sources failed — no reliable content acquired",
        attempted_strategies=["web_search", "static_fetch", "browser_read"],
    )


def _extract_urls_from_search(search_content: str) -> list[str]:
    """Extract URLs from web_search's formatted result."""
    urls = []
    # web_search formats results as: "1. **Title**\n   URL\n   Snippet"
    # The URL is on its own line after the title
    for line in search_content.splitlines():
        line = line.strip()
        if line.startswith("http://") or line.startswith("https://"):
            urls.append(line)
    return urls[:5]  # cap at 5 sources
