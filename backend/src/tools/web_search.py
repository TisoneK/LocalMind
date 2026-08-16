"""
Web Search tool - Racing tier architecture: DDG + SearXNG race, Brave as fallback.

Registered as Intent.WEB_SEARCH in the tool registry.

Results are formatted as a compact markdown list so the model can
reason over them without a huge token footprint.

Architecture (v8 — RACING TIERS):
- Tier 1+2 RACE: DuckDuckGo and SearXNG fire in PARALLEL — first to
  return wins. This eliminates the 27s sequential worst-case where DDG
  times out (12s) and then SearXNG is tried (15s).
- Tier 3: Brave - Premium optional layer, requires API key. Only tried
  if both free tiers fail.

v8 changes vs v7:
- BREAKING: DDG and SearXNG now race in parallel instead of sequential.
  Worst-case latency drops from 27s to max(12s, 15s) = 15s.
- SNIPPET_MAX raised from 300 to 800 — 300 chars was too thin for
  weather, scores, and other structured data. The synthesizer handles
  compression; the tool should preserve detail.
- MAX_RESULTS raised from 5 to 8 — more results means better coverage
  for the LLM to synthesize from.

v9 changes vs v8 (Session 268):
- FIX: SearXNG was effectively dead. The default instance (searx.be) is
  behind an Anubis anti-bot challenge that returns HTTP 200 + HTML, so
  ``r.json()`` raised a JSONDecodeError on EVERY search and the tier
  never returned a result. Public instances churn constantly (they are
  rate-limited/blocked within days), so a single hardcoded URL is a
  ticking failure.
- SearXNG now walks a FALLBACK CHAIN of instances (configured
  ``searxng_url`` first — comma-separated supported — then curated
  public fallbacks, capped at ``MAX_SEARXNG_ATTEMPTS``). Anti-bot
  challenge pages (non-JSON responses) and rate limits are detected and
  the search moves to the next instance instead of dying on the first.
- Non-JSON responses (challenge pages) are detected via Content-Type
  and reported as such; ``json.JSONDecodeError`` is caught explicitly
  with a friendly message instead of leaking the raw parser error.
"""

from __future__ import annotations

import asyncio
import json
import logging

from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool

logger = logging.getLogger(__name__)

MAX_RESULTS = 8
SNIPPET_MAX = 800

# SearXNG public instances are churned constantly — a working instance is
# rate-limited or put behind an anti-bot page within days. The configured
# ``searxng_url`` (comma-separated list supported) is tried first, then these
# curated public fallbacks, up to ``MAX_SEARXNG_ATTEMPTS`` total.
DEFAULT_SEARXNG_FALLBACKS = [
    "https://search.bus-hit.me",
    "https://opnxng.com",
    "https://searx.tiekoetter.com",
    "https://priv.au",
    "https://search.hbubli.cc",
]

MAX_SEARXNG_ATTEMPTS = 3


def _searxng_instance_list(configured: str | None) -> list[str]:
    """Expand the configured SearXNG URL into an ordered, deduped instance list.

    ``searxng_url`` may be a single URL or a comma-separated list (so a user
    with a known-good private instance can pin it first). Curated public
    fallbacks are appended after the configured ones.
    """
    urls: list[str] = []
    raw = (configured or "").strip()
    if raw:
        for part in raw.split(","):
            part = part.strip().rstrip("/")
            if part and part not in urls:
                urls.append(part)
    for fallback in DEFAULT_SEARXNG_FALLBACKS:
        if fallback not in urls:
            urls.append(fallback)
    return urls


async def _search_ddg(query: str) -> tuple[list[dict], str, str]:
    """Search DuckDuckGo with an internal retry to handle first-attempt anti-bot failures.

    DDG's HTML scraping often fails on the first request due to anti-bot
    protection (CAPTCHA/challenge page). A single retry after a short delay
    usually succeeds because DDG's rate limiter has a cooldown window.
    """
    max_attempts = 2
    base_delay = 0.8  # seconds between retries

    for attempt in range(max_attempts):
        try:
            from ddgs import DDGS

            safe_query = query.encode("utf-8", errors="replace").decode("utf-8")

            def _run_sync():
                with DDGS() as ddgs:
                    return list(ddgs.text(safe_query, max_results=MAX_RESULTS))

            # DDGS is synchronous and blocks the event loop. Run it in a thread
            # with a hard timeout so a slow/hung search never stalls the server.
            loop = asyncio.get_running_loop()
            results = await asyncio.wait_for(
                loop.run_in_executor(None, _run_sync),
                timeout=12,
            )
            if results:
                return results, "", ""
            # Empty results (anti-bot challenge page) -- retry if we have attempts left
            if attempt < max_attempts - 1:
                logger.info(
                    f"[web_search] DDG returned 0 results (attempt {attempt + 1}), retrying after {base_delay}s..."
                )
                await asyncio.sleep(base_delay)
                base_delay *= 1.5  # exponential backoff
                continue
            return (
                [],
                "network",
                "DuckDuckGo returned no results after retry (possible anti-bot block)",
            )
        except asyncio.TimeoutError:
            logger.warning("[web_search] DDG timed out after 12s")
            return [], "timeout", "DuckDuckGo search timed out after 12 seconds"
        except Exception as e:
            error_msg = str(e).encode("utf-8", errors="ignore").decode("utf-8")
            logger.warning(f"[web_search] DDG failed: {error_msg}")
            return [], "network", f"DuckDuckGo search failed: {error_msg}"
    return [], "network", "DuckDuckGo search returned no results after all attempts"


async def _search_searxng_single(
    query: str, searxng_url: str
) -> tuple[list[dict], str, str]:
    """Search one SearXNG instance.

    v9: detects anti-bot challenge pages (Anubis etc.) that answer HTTP 200
    with HTML instead of JSON — they used to raise a JSONDecodeError on every
    request, silently killing the tier. Returns error_type="challenge" so the
    caller can skip to the next instance instead of treating it as terminal.
    """
    try:
        import httpx
    except ImportError:
        return [], "network", "httpx not installed -- cannot search via SearXNG"

    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
            # SearXNG API format
            params = {
                "q": query,
                "format": "json",
                "engines": "google,duckduckgo,bing,startpage",
                "language": "en",
                "safesearch": "moderate",
                "results": MAX_RESULTS,
            }
            r = await client.get(f"{searxng_url}/search", params=params)
            r.raise_for_status()
            # Anti-bot challenge pages (Anubis/Cloudflare) return HTTP 200 + an
            # HTML "verifying your browser" page — never a JSON body. Detect via
            # Content-Type BEFORE parsing so the caller can move to the next
            # instance instead of failing the whole tier.
            content_type = (r.headers.get("content-type") or "").lower()
            if "application/json" not in content_type:
                return (
                    [],
                    "challenge",
                    f"SearXNG at {searxng_url} returned a non-JSON response "
                    "(likely an anti-bot challenge page)",
                )
            data = r.json()

            # Extract results from SearXNG response
            results = []
            for item in data.get("results", [])[:MAX_RESULTS]:
                results.append(
                    {
                        "title": item.get("title", ""),
                        "href": item.get("url", ""),
                        "body": item.get("content", ""),
                    }
                )

            return results, "", ""

    except asyncio.TimeoutError:
        logger.warning(f"[web_search] SearXNG {searxng_url} timed out after 12s")
        return [], "timeout", f"SearXNG at {searxng_url} timed out after 12 seconds"
    except httpx.ConnectError:
        logger.warning(f"[web_search] SearXNG connection failed: {searxng_url}")
        return (
            [],
            "network",
            f"SearXNG instance unreachable at {searxng_url} - check internet connection",
        )
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.warning(f"[web_search] SearXNG HTTP error {status}: {searxng_url}")
        if status == 404:
            return [], "network", f"SearXNG instance not found at {searxng_url}"
        elif status == 429:
            return [], "rate_limit", f"SearXNG at {searxng_url} rate-limited (HTTP 429)"
        elif status >= 500:
            return [], "network", f"SearXNG server error (HTTP {status}) at {searxng_url}"
        else:
            return [], "network", f"SearXNG at {searxng_url} returned HTTP {status}"
    except json.JSONDecodeError:
        # Parsed OK by Content-Type but the body isn't actually JSON (some
        # challenge pages omit the header). Report as a challenge, not a leak.
        return (
            [],
            "challenge",
            f"SearXNG at {searxng_url} returned invalid JSON "
            "(instance misconfigured or behind an anti-bot page)",
        )
    except Exception as e:
        logger.warning(f"[web_search] SearXNG failed: {searxng_url}: {repr(e)}")
        error_str = str(e)
        if "timeout" in error_str.lower():
            return [], "timeout", f"SearXNG at {searxng_url} timed out"
        return [], "network", f"SearXNG search error at {searxng_url}: {error_str}"


async def _search_searxng(
    query: str, searxng_url: str | None = None
) -> tuple[list[dict], str, str]:
    """Search SearXNG, walking a fallback chain of instances.

    v9: a single hardcoded public instance is a ticking failure — every one is
    behind an anti-bot page or rate-limited within days. Try the configured
    URL(s) first (comma-separated supported), then curated public fallbacks,
    capped at ``MAX_SEARXNG_ATTEMPTS``. Challenge pages / rate limits move to
    the next instance; the first instance that returns JSON results wins.
    """
    try:
        import httpx
    except ImportError:
        return [], "network", "httpx not installed -- cannot search via SearXNG"

    urls = _searxng_instance_list(searxng_url)
    attempts = urls[:MAX_SEARXNG_ATTEMPTS]
    errors: list[str] = []
    for index, url in enumerate(attempts):
        try:
            results, err_type, err_msg = await _search_searxng_single(query, url)
        except Exception as e:  # defensive — the single-instance call never raises
            logger.warning(f"[web_search] SearXNG {url} raised: {e}")
            results, err_type, err_msg = [], "exception", str(e)
        if results:
            return results, "", ""
        errors.append(f"{url} ({err_type}: {err_msg})")
        if index < len(attempts) - 1:
            logger.info(
                "[web_search] SearXNG %s failed (%s) — trying next instance",
                url, err_type,
            )

    if not errors:
        return [], "network", "No SearXNG instances configured"
    return [], "network", "; ".join(errors)


async def _search_brave(query: str, api_key: str) -> tuple[list[dict], str, str]:
    try:
        import httpx
    except ImportError:
        return [], "network", "httpx not installed -- cannot search via Brave"

    try:
        # Pass query directly as string - httpx handles UTF-8 encoding automatically
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": MAX_RESULTS},
                headers={"Accept": "application/json", "x-subscription-token": api_key},
            )
            r.raise_for_status()
            data = r.json()
            results = [
                {
                    "title": w.get("title", ""),
                    "href": w.get("url", ""),
                    "body": w.get("description", ""),
                }
                for w in data.get("web", {}).get("results", [])
            ]
            return results, "", ""
    except asyncio.TimeoutError:
        logger.warning("[web_search] Brave timed out after 10s")
        return [], "timeout", "Brave Search API timed out after 10 seconds"
    except httpx.ConnectError as e:
        logger.warning(f"[web_search] Brave connection failed: {e}")
        return [], "network", "Brave Search API unreachable - check internet connection"
    except httpx.HTTPStatusError as e:
        logger.warning(f"[web_search] Brave HTTP error: {e.response.status_code}")
        if e.response.status_code == 422:
            return [], "api_key", "Brave Search API key invalid or request format error (HTTP 422)"
        elif e.response.status_code == 401:
            return [], "api_key", "Brave Search API key unauthorized (HTTP 401)"
        else:
            return [], "network", f"Brave Search API returned HTTP {e.response.status_code}"
    except Exception as e:
        logger.warning(f"[web_search] Brave failed: {repr(e)}")
        error_str = str(e)
        if "timeout" in error_str.lower():
            return [], "timeout", "Brave Search API timed out"
        else:
            return [], "network", f"Brave Search API error: {error_str}"


def _format_results(results: list[dict]) -> str:
    """Format search results as compact markdown.

    v8: SNIPPET_MAX raised to 800 to preserve more detail for synthesis.
    The AnswerSynthesizer handles compression; the tool should preserve data.
    """
    if not results:
        return "No results found."
    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "").strip()
        url = r.get("href", r.get("url", "")).strip()
        body = r.get("body", r.get("description", "")).strip()
        if len(body) > SNIPPET_MAX:
            body = body[:SNIPPET_MAX] + "..."
        # Ensure proper Unicode handling
        title = title.encode("utf-8", errors="ignore").decode("utf-8")
        url = url.encode("utf-8", errors="ignore").decode("utf-8")
        body = body.encode("utf-8", errors="ignore").decode("utf-8")
        lines.append(f"{i}. **{title}**\n   {url}\n   {body}")
    return "\n\n".join(lines)


# -- Available tools discovery -------------------------------------------------


def list_available_tools() -> list[dict]:
    """
    Return metadata about available search capabilities.

    This allows the agent to discover what search tiers are available
    and which providers are configured. Useful for:
    - Determining if premium search (Brave) is available
    - Checking if SearXNG has a custom URL configured
    - Providing the agent with context about search capabilities

    Returns a list of dicts, each describing a search tier:
      - name: human-readable provider name
      - tier: priority order (1 = first tried)
      - available: whether this tier is currently usable
      - requires_auth: whether an API key is needed
      - description: brief description of the provider
    """
    from core.config import settings

    tiers = [
        {
            "name": "DuckDuckGo",
            "tier": 1,
            "available": True,
            "requires_auth": False,
            "description": "Fast first attempt, no auth required. Uses ddgs library.",
        },
        {
            "name": "SearXNG",
            "tier": 2,
            "available": True,
            "requires_auth": False,
            "description": (
                "Stable core fallback, multi-source aggregation. "
                "Walks a fallback chain (configured instance first, then public "
                f"fallbacks). Configured: {getattr(settings, 'searxng_url', 'https://searx.be')}"
            ),
        },
        {
            "name": "Brave",
            "tier": 3,
            "available": bool(getattr(settings, "brave_search_api_key", "")),
            "requires_auth": True,
            "description": "Premium optional layer. Requires BRAVE_SEARCH_API_KEY env var.",
        },
    ]
    return tiers


async def web_search(query: str) -> ToolResult:
    """
    Search the web using a racing-tier architecture.

    v8: DDG and SearXNG fire in PARALLEL (asyncio race). First provider
    to return results wins. This eliminates the worst-case 27s sequential
    delay where DDG times out and then SearXNG is tried.

    If both free tiers fail, Brave is tried as a premium fallback.
    """
    from core.config import settings

    results = []
    error_type = ""
    error_message = ""
    successful_provider = ""

    # -- Racing Tier 1+2: DDG + SearXNG in parallel ----------------------
    # Fire both searches concurrently. Use whichever returns first with
    # valid results. This drops worst-case latency from 27s to ~15s.
    # searxng_url may be a comma-separated list; _search_searxng expands it
    # into the fallback chain.
    searxng_url = getattr(settings, "searxng_url", None)

    ddg_task = asyncio.create_task(_search_ddg(query))
    searxng_task = asyncio.create_task(_search_searxng(query, searxng_url))

    # Race: wait for the first task to complete with results
    pending = {ddg_task, searxng_task}
    first_error_type = ""
    first_error_message = ""

    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            try:
                task_results, task_err_type, task_err_msg = task.result()
            except Exception as e:
                logger.warning(f"[web_search] Search task raised exception: {e}")
                task_results, task_err_type, task_err_msg = [], "exception", str(e)

            if task_results:
                # First provider to return results wins!
                results = task_results
                successful_provider = "duckduckgo" if task is ddg_task else "searxng"
                logger.info(
                    f"[web_search] Race winner: {successful_provider} with {len(results)} results"
                )
                # Cancel the other task
                for t in pending:
                    t.cancel()
                pending = set()
                break
            else:
                # This provider failed — track error and wait for the other
                if not first_error_type:
                    first_error_type = task_err_type
                    first_error_message = task_err_msg

    # If we got results from the race, skip Brave
    if not results:
        # Both free tiers failed — try Brave if available
        if getattr(settings, "brave_search_api_key", ""):
            logger.info("[web_search] Free tiers failed, trying Brave")
            results, error_type, error_message = await _search_brave(
                query, settings.brave_search_api_key
            )
            if results:
                successful_provider = "brave"
                logger.info(f"[web_search] Brave succeeded with {len(results)} results")
        else:
            error_type = first_error_type or "all_tiers_failed"
            error_message = first_error_message or "All search providers failed"

    # Check if we have results
    if not results:
        logger.warning(f"[web_search] All tiers failed. Final error: {error_message}")
        return ToolResult(
            content=f"All search providers failed. Last error: {error_message}"
            if error_message
            else "No results found from any provider.",
            risk=RiskLevel.LOW,
            source="web_search",
            success=False,
            error_type=error_type or "all_tiers_failed",
            error_message=error_message or "All search providers failed",
            metadata={
                "query": query,
                "result_count": 0,
                "sources": [],
                "successful_provider": "",
                "attempted_providers": [
                    "duckduckgo",
                    "searxng",
                    "brave"
                    if getattr(settings, "brave_search_api_key", "")
                    else "duckduckgo,searxng",
                ],
            },
        )

    content = _format_results(results)
    source_urls = [
        r.get("href", r.get("url", "")) for r in results if r.get("href") or r.get("url")
    ]

    logger.info(f"[web_search] Success via {successful_provider}: {len(results)} results")
    return ToolResult(
        content=content,
        risk=RiskLevel.LOW,
        source="web_search",
        success=True,
        error_type="",
        error_message="",
        metadata={
            "query": query,
            "result_count": len(results),
            "sources": source_urls[:8],
            "successful_provider": successful_provider,
            "attempted_providers": [
                "duckduckgo",
                "searxng",
                "brave" if getattr(settings, "brave_search_api_key", "") else "duckduckgo,searxng",
            ],
        },
    )


# Register into the tool registry
register_tool(
    Intent.WEB_SEARCH,
    web_search,
    description="Search the web for current information, news, prices, or recent events",
    cost=0.05,
    latency_ms=1500,
)
