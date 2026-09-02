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
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
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
    SCRAPAMOJA_RENDER = "scrapamoja_render"  # scrapamoja stealth browser (anti-bot/skeleton)
    SEARCH_ONLY = "search_only"  # only snippets available, no full content


# ── Session 341: WebIntent — capability selection, not fallback hierarchy ───
#
# The user's correction:
#   > Do not model the browser as: "Static fetch failed, therefore try browser."
#   > Model it as: "The task requires rendered/live/interactive information;
#   > therefore select the browser capability."
#
# WebIntent is a peer-level classification — DISCOVER/RETRIEVE/BROWSE/RESEARCH.
# BROWSE is NOT a fallback from RETRIEVE; it's a first-class capability selected
# when the task requires a live/interactive/rendered website.


class WebIntent(Enum):
    """The type of web capability the task requires.

    Peers, NOT a fallback chain:
      - DISCOVER: find sources about a topic → search capability
      - RETRIEVE: get the contents of a specific URL → fetch capability
      - BROWSE: navigate/interact with a live website → browser capability
      - RESEARCH: find AND verify information → acquisition planner (orchestrates
        search + fetch + browser as needed, with evidence validation)
    """

    DISCOVER = "discover"
    RETRIEVE = "retrieve"
    BROWSE = "browse"
    RESEARCH = "research"


def classify_web_intent(message: str, url_provided: bool = False) -> WebIntent:
    """Classify the web intent from the user's message.

    This is the capability-selection layer — it determines WHICH web capability
    the parent agent should use, NOT how the capability internally executes.

    Selection rules:
    - If the user provided a specific URL → RETRIEVE (fetch that URL) or BROWSE
      (if the URL is known to need JS rendering — e.g. Twitter, React apps)
    - If the user asks to "open" / "navigate to" / "go to" a website → BROWSE
    - If the user asks to "find" / "search for" sources → DISCOVER
    - If the user asks for "current" / "latest" information without a URL → RESEARCH
      (needs multi-source acquisition + validation)
    - Default → RESEARCH (the safest, most complete path)
    """
    if not message:
        return WebIntent.RESEARCH

    lower = message.lower().strip()

    # BROWSE intent — explicit navigation/interaction cues
    browse_cues = [
        r"\bopen\s+(?:the\s+)?(?:website|page|url|site|dashboard|app)\b",
        r"\bnavigate\s+to\b",
        r"\bgo\s+to\s+(?:the\s+)?(?:website|page|url|site)\b",
        r"\bcheck\s+(?:the\s+)?(?:live|website|page|dashboard)\b",
        r"\binspect\s+(?:the\s+)?(?:page|website|dom)\b",
        r"\binteract\s+with\b",
        r"\bclick\s+on\b",
        r"\bscroll\s+(?:down|up|to)\b",
        r"\bfill\s+(?:in\s+)?(?:the\s+)?(?:form|field)\b",
    ]
    for pattern in browse_cues:
        if re.search(pattern, lower):
            return WebIntent.BROWSE

    # RETRIEVE intent — user provided a specific URL
    if url_provided or re.search(r"https?://\S+", message):
        return WebIntent.RETRIEVE

    # DISCOVER intent — user wants to find sources, not acquire content yet
    discover_cues = [
        r"\bfind\s+(?:articles?|sources?|websites?)\s+(?:about|on|for)\b",
        r"\bsearch\s+for\s+(?:articles?|sources?|websites?)\b",
        r"\blist\s+(?:some\s+)?(?:websites?|sources?)\b",
        r"\bwhere\s+(?:can\s+i\s+find|is\s+there)\b",
    ]
    for pattern in discover_cues:
        if re.search(pattern, lower):
            return WebIntent.DISCOVER

    # RESEARCH intent — user needs verified, current information
    # (the default for "current X", "latest Y", "what is the Z standings")
    research_cues = [
        r"\bcurrent\b",
        r"\blatest\b",
        r"\b(?:today|tonight|tomorrow|now)\b",
        r"\bstandings?\b",
        r"\btable\b",
        r"\bscores?\b",
        r"\bweather\b",
        r"\bnews\b",
        r"\bprice\b",
        r"\bresults?\b",
    ]
    for pattern in research_cues:
        if re.search(pattern, lower):
            return WebIntent.RESEARCH

    # Default — RESEARCH (safest, most complete)
    return WebIntent.RESEARCH


@dataclass
class WebResult:
    """The result of a web acquisition attempt.

    Session 341: extended with evidence-validation fields per the user's
    recommendation:
      WebResult {
          status
          source
          method
          content
          freshness
          confidence
          acquisition_trace        ← NEW
          failure_reason           ← NEW
          source_timestamp         ← NEW
          retrieved_at             ← NEW
          entity_validated         ← NEW
          freshness_validated      ← NEW
          authority_score          ← NEW
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

    # Session 341: evidence-validation fields
    acquisition_trace: list[str] = field(default_factory=list)  # ordered steps taken
    failure_reason: Optional[str] = None  # categorized failure: "stale", "wrong_entity", "boilerplate", "unreachable", "js_render_failed"
    source_timestamp: Optional[str] = None  # when the source's data was last updated (if known)
    retrieved_at: Optional[str] = None  # when we retrieved it (ISO timestamp)
    entity_validated: bool = False  # did we verify the content is about the right entity?
    freshness_validated: bool = False  # did we verify the data is current enough?
    authority_score: float = 0.0  # 0.0-1.0 — how authoritative is the source?

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

# Below this many chars of extracted static text, treat the result as a JS
# skeleton/shell and escalate to a rendering strategy instead of accepting it.
_MIN_STATIC_SUBSTANCE_CHARS = 250

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


def _scrapamoja_paths() -> Optional[tuple[str, str]]:
    """Return (venv_python, project_dir) for scrapamoja, or None if unavailable.

    Availability = the configured project dir exists AND has a venv interpreter.
    Cheap and side-effect-free so it can gate the strategy on every call.
    """
    try:
        from core.config import settings
        base = str(getattr(settings, "localmind_scrapamoja_path", "") or "").strip()
    except Exception:
        base = ""
    if not base:
        return None
    proj = Path(base)
    if not proj.is_dir():
        return None
    for rel in ("bin/python", "Scripts/python.exe"):  # POSIX, Windows
        py = proj / ".venv" / rel
        if py.exists():
            return (str(py), str(proj))
    return None


def scrapamoja_available() -> bool:
    return _scrapamoja_paths() is not None


async def _scrapamoja_render(url: str, timeout: Optional[int] = None) -> WebResult:
    """Strategy C: scrapamoja stealth render. Strongest option for heavy-JS /
    skeleton / anti-bot sites — a real stealth Chromium that waits for
    client-side hydration, in scrapamoja's own venv (subprocess, no in-process
    Playwright dependency for LocalMind).
    """
    paths = _scrapamoja_paths()
    if paths is None:
        return WebResult(
            status=AcquisitionStatus.FAILED, source=url,
            acquisition_method=AcquisitionMethod.SCRAPAMOJA_RENDER, content="",
            error="scrapamoja not available", attempted_strategies=["scrapamoja_render"],
        )
    venv_py, proj = paths
    if timeout is None:
        try:
            from core.config import settings
            timeout = int(getattr(settings, "localmind_scrapamoja_timeout", 45))
        except Exception:
            timeout = 45
    sentinel = "@@RENDER_JSON@@ "
    try:
        proc = await asyncio.create_subprocess_exec(
            venv_py, "-m", "src.render", url, "--json", "--timeout", str(timeout),
            cwd=proj, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out_b, _err_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout + 20
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await asyncio.wait_for(proc.communicate(), timeout=2)
            except Exception:
                pass
            return WebResult(
                status=AcquisitionStatus.FAILED, source=url,
                acquisition_method=AcquisitionMethod.SCRAPAMOJA_RENDER, content="",
                error=f"scrapamoja render timed out after {timeout + 20}s",
                attempted_strategies=["scrapamoja_render"],
            )
        # The JSON is on a sentinel line (scrapamoja logs to stdout too).
        payload = None
        for line in out_b.decode("utf-8", "replace").splitlines():
            idx = line.find(sentinel)
            if idx != -1:
                try:
                    payload = json.loads(line[idx + len(sentinel):])
                except Exception:
                    payload = None
        if not payload or not (payload.get("text") or "").strip():
            return WebResult(
                status=AcquisitionStatus.FAILED, source=url,
                acquisition_method=AcquisitionMethod.SCRAPAMOJA_RENDER, content="",
                error=(payload or {}).get("error", "scrapamoja render returned no content"),
                attempted_strategies=["scrapamoja_render"],
            )
        content = payload["text"].strip()
        title = (payload.get("title") or "").strip()
        body = f"**{title}**\n{content}" if title else content
        return WebResult(
            status=AcquisitionStatus.SUCCESS, source=url,
            acquisition_method=AcquisitionMethod.SCRAPAMOJA_RENDER, content=body,
            confidence=0.9,  # stealth-rendered DOM is the most complete we get
            freshness=_extract_freshness(content),
            attempted_strategies=["scrapamoja_render"],
        )
    except Exception as e:
        return WebResult(
            status=AcquisitionStatus.FAILED, source=url,
            acquisition_method=AcquisitionMethod.SCRAPAMOJA_RENDER, content="",
            error=f"scrapamoja_render exception: {e}",
            attempted_strategies=["scrapamoja_render"],
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
            # A very short static body is almost always a JS skeleton/shell (the
            # data hasn't hydrated). Don't accept it — escalate so browser_read /
            # scrapamoja can render the real content. It's still kept as the
            # best-effort PARTIAL fallback if every richer strategy also fails.
            substantive = len(result.content.strip()) >= _MIN_STATIC_SUBSTANCE_CHARS
            if not _is_boilerplate(result.content) and score >= confidence_threshold and substantive:
                result.attempted_strategies = attempted
                logger.info(
                    "[web-acquire] static_fetch succeeded for %s (confidence=%.2f)",
                    url[:80],
                    result.confidence,
                )
                return result
            logger.info(
                "[web-acquire] static_fetch boilerplate/low-confidence/thin "
                "for %s (score=%.2f, chars=%d) — escalating",
                url[:80],
                score,
                len(result.content.strip()),
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
            substantive = len(result.content.strip()) >= _MIN_STATIC_SUBSTANCE_CHARS
            if not _is_boilerplate(result.content) and score >= confidence_threshold and substantive:
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

    # Strategy C: scrapamoja stealth render — strongest option for heavy-JS /
    # skeleton / anti-bot sites (real stealth Chromium, waits for hydration).
    # Only engages when static + agent-browser did not yield accepted content
    # AND scrapamoja is installed; otherwise it's silently skipped.
    if max_strategies >= 3 and scrapamoja_available():
        sresult = await _scrapamoja_render(url)
        attempted.append("scrapamoja_render")
        if sresult.is_success():
            score = _score_content(sresult.content, query) if query else 0.5
            sresult.confidence = max(sresult.confidence, score)
            if not _is_boilerplate(sresult.content) and score >= confidence_threshold:
                sresult.attempted_strategies = attempted
                logger.info(
                    "[web-acquire] scrapamoja_render succeeded for %s (confidence=%.2f)",
                    url[:80],
                    sresult.confidence,
                )
                return sresult
            logger.info(
                "[web-acquire] scrapamoja_render low-confidence for %s (score=%.2f)",
                url[:80],
                score,
            )
            result = sresult  # keep as best-effort PARTIAL candidate below
        else:
            logger.info(
                "[web-acquire] scrapamoja_render failed for %s: %s",
                url[:80],
                sresult.error,
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
        # Session 341: run evidence validation after acquisition
        result = validate_web_result(result, query=query)
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


# ── Session 341: Evidence-aware validation pipeline ─────────────────────────
#
# The user's diagnosis:
#   > keyword overlap can produce false confidence. A page containing
#   > "Premier League Standings 2024/25" may have excellent keyword overlap
#   > while being stale.
#
# This pipeline validates:
#   1. Entity — is the content about the right thing (not the Championship)?
#   2. Data presence — are there actual data rows (not just nav)?
#   3. Temporal/freshness — is the data current enough for the request?
#   4. Authority — is the source credible?
#   5. Cross-source consistency — do multiple sources agree?


# Known-authoritative domains for common topics
_AUTHORITY_DOMAINS = {
    # Sports
    "premierleague.com": 0.95,
    "bbc.com": 0.90, "bbc.co.uk": 0.90,
    "skysports.com": 0.85,
    "espn.com": 0.85,
    "fotmob.com": 0.80,
    # General reference
    "wikipedia.org": 0.75,
    "python.org": 0.95,
    "docs.python.org": 0.95,
    # News
    "reuters.com": 0.90,
    "apnews.com": 0.90,
    "theguardian.com": 0.80,
    # Weather
    "weather.com": 0.85,
    "metoffice.gov.uk": 0.85,
}

# Domains known to be low-authority or user-generated
_LOW_AUTHORITY_DOMAINS = {
    "reddit.com": 0.40,
    "quora.com": 0.35,
    "pinterest.com": 0.20,
    "facebook.com": 0.30,
}


def _assess_authority(url: str) -> float:
    """Score the authority of a source URL (0.0-1.0)."""
    if not url:
        return 0.0
    lower = url.lower()
    # Check high-authority domains
    for domain, score in _AUTHORITY_DOMAINS.items():
        if domain in lower:
            return score
    # Check low-authority domains
    for domain, score in _LOW_AUTHORITY_DOMAINS.items():
        if domain in lower:
            return score
    # Unknown domain — neutral
    return 0.5


def _validate_entity(content: str, query: str) -> tuple[bool, Optional[str]]:
    """Validate that the content is about the right entity.

    Returns (is_valid, failure_reason).
    Catches the "Championship standings when user asked for EPL" failure.
    """
    if not content or not query:
        return True, None  # can't validate — assume valid

    lower_content = content.lower()
    lower_query = query.lower()

    # Entity mismatch detection — if the query asks for one thing and the
    # content clearly discusses a different entity, flag it.
    entity_pairs = [
        # (query_entity, wrong_entity)
        ("premier league", "championship"),
        ("epl", "championship"),
        ("premier league", "la liga"),
        ("premier league", "serie a"),
        ("premier league", "bundesliga"),
        ("nairobi", "lagos"),
        ("nairobi", "cape town"),
        ("python", "javascript"),
        ("python", "java"),
    ]
    for query_entity, wrong_entity in entity_pairs:
        if query_entity in lower_query and wrong_entity in lower_content:
            # Only flag if the wrong entity is MORE prominent than the right one
            # (the content might mention both in a comparison)
            if lower_content.count(wrong_entity) > lower_content.count(query_entity):
                return False, f"wrong_entity: content is about {wrong_entity}, query asked for {query_entity}"

    return True, None


def _validate_freshness(
    content: str,
    query: str,
    freshness: Optional[str],
) -> tuple[bool, Optional[str]]:
    """Validate that the data is fresh enough for the request.

    Returns (is_fresh, failure_reason).
    Catches the "2024/25 table when user asked for current" failure.
    """
    if not query:
        return True, None  # can't validate — assume fresh

    lower_query = query.lower()
    # Only enforce freshness if the user explicitly asked for "current" / "latest"
    requires_fresh = any(
        w in lower_query for w in ["current", "latest", "today", "now", "live"]
    )
    if not requires_fresh:
        return True, None  # no freshness requirement

    if not freshness:
        # No date detected — can't validate. Don't fail, but don't mark as validated.
        return True, None

    # Check if the freshness year is current
    import datetime as _dt
    current_year = _dt.datetime.now().year
    try:
        # Extract year from the freshness string
        year_match = re.search(r"\b(20\d{2})\b", freshness)
        if year_match:
            content_year = int(year_match.group(1))
            # Allow current year and previous year (for season-spanning data)
            if content_year < current_year - 1:
                return False, f"stale: content is from {content_year}, current year is {current_year}"
    except (ValueError, AttributeError):
        pass

    return True, None


def _validate_data_presence(content: str) -> tuple[bool, Optional[str]]:
    """Validate that the content has actual data rows, not just navigation.

    Returns (has_data, failure_reason).
    Catches the "got navigation/footer/cookie-banner instead of the table" failure.
    """
    if not content:
        return False, "empty_content"
    if _is_boilerplate(content):
        return False, "boilerplate: content is navigation/cookie-banner, not data"
    # Check for table-like data (numbered rows, or rows with numbers)
    lines = content.splitlines()
    data_lines = 0
    for line in lines:
        # A "data line" has a number (points, score, etc.) or looks like a table row
        if re.search(r"\d+", line) and len(line.strip()) > 5:
            data_lines += 1
    if data_lines < 2:
        return False, f"no_data: content has {data_lines} data lines (expected ≥2)"
    return True, None


def validate_web_result(
    result: WebResult,
    query: str,
) -> WebResult:
    """Run the evidence-validation pipeline on a WebResult.

    Updates the result's evidence fields (entity_validated, freshness_validated,
    authority_score, failure_reason) and may downgrade the status if validation
    fails.

    Pipeline:
      1. Entity validation — is the content about the right thing?
      2. Data presence — are there actual data rows?
      3. Temporal/freshness — is the data current enough?
      4. Authority assessment — is the source credible?
    """
    if not result.is_success() and result.status != AcquisitionStatus.PARTIAL:
        return result  # already failed — no point validating

    # 1. Authority assessment (always runs)
    result.authority_score = _assess_authority(result.source)

    # 2. Entity validation
    entity_ok, entity_reason = _validate_entity(result.content, query)
    result.entity_validated = entity_ok
    if not entity_ok:
        result.failure_reason = entity_reason
        result.status = AcquisitionStatus.FAILED
        result.confidence = 0.0
        logger.info(
            "[web-validate] entity validation failed for %s: %s",
            result.source[:80],
            entity_reason,
        )
        return result

    # 3. Data presence validation
    data_ok, data_reason = _validate_data_presence(result.content)
    if not data_ok:
        result.failure_reason = data_reason
        result.status = AcquisitionStatus.FAILED
        result.confidence = 0.0
        logger.info(
            "[web-validate] data presence failed for %s: %s",
            result.source[:80],
            data_reason,
        )
        return result

    # 4. Freshness validation
    fresh_ok, fresh_reason = _validate_freshness(result.content, query, result.freshness)
    result.freshness_validated = fresh_ok
    if not fresh_ok:
        result.failure_reason = fresh_reason
        result.status = AcquisitionStatus.FAILED
        result.confidence = 0.0
        logger.info(
            "[web-validate] freshness validation failed for %s: %s",
            result.source[:80],
            fresh_reason,
        )
        return result

    # All validations passed — boost confidence
    result.confidence = min(1.0, result.confidence + 0.1)
    if result.authority_score > 0.8:
        result.confidence = min(1.0, result.confidence + 0.1)  # authoritative source bonus

    return result
