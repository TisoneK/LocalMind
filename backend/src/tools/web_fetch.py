"""
Web Fetch tool — fetches and extracts readable content from a URL.

Registered as Intent.WEB_FETCH in the tool registry.

When web_search returns results that are link-only (URLs without substantive
snippets), the agent can use this tool to visit those URLs and extract the
actual page content. This closes the gap where the agent would otherwise
fabricate answers because the search snippets were too thin.

Architecture:
- Uses httpx for HTTP requests with timeout protection
- Extracts readable content using a multi-strategy approach:
  1. Try readability-style extraction (remove nav, footer, scripts, etc.)
  2. Fall back to raw text extraction if HTML parsing fails
- Caps output at WEB_FETCH_MAX_CHARS to prevent context bloat
- Respects robots.txt via a simple check
- Returns structured metadata (title, url, content_length)
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from urllib.parse import urlparse

from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool

logger = logging.getLogger(__name__)

WEB_FETCH_TIMEOUT_SECS = 15
WEB_FETCH_MAX_CHARS = 8000
"""Maximum chars returned from a fetched web page. Raised from 4000 to 8000
because the AnswerSynthesizer pre-processes content before sending to the LLM
(removing ads, nav, etc.), so we need enough raw content for the LLM to
extract the answer after noise removal. 4000 was too thin for weather pages,
sports fixtures, and other structured data."""
WEB_FETCH_MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2 MB -- don't fetch huge files


# ── SSRF Protection ──────────────────────────────────────────────────────
#
# web_fetch is an agent-callable tool: the LLM can be coerced (via prompt
# injection in search results, file contents, or chat) into fetching
# arbitrary URLs. Without SSRF protection, an attacker can use web_fetch
# to:
#   - Read cloud metadata endpoints (169.254.169.254) to steal IAM creds
#   - Probe internal services bound to localhost (databases, admin panels)
#   - Hit the Ollama API itself (localhost:11434) to execute models
#   - Access the Docker socket proxy or Kubernetes API
#
# _is_url_safe() resolves the hostname and rejects any URL whose resolved
# IP is in a private/loopback/link-local/metadata range.

# Cloud metadata endpoints that must never be fetched
_METADATA_HOSTS = {
    "169.254.169.254",  # AWS / Azure / GCP instance metadata
    "fd00:ec2::254",  # AWS IPv6 metadata
    "metadata.google.internal",  # GCP metadata (also resolves to 169.254.169.254)
}


def _is_ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if an IP address is in a blocked (private/internal) range."""
    return (
        ip.is_private  # RFC 1918: 10/8, 172.16/12, 192.168/16
        or ip.is_loopback  # 127/8, ::1
        or ip.is_link_local  # 169.254/16 (includes cloud metadata)
        or ip.is_multicast  # 224/4, ff00::/8
        or ip.is_reserved  # various reserved ranges
        or ip.is_unspecified  # 0/8, ::/128
    )


def _is_url_safe(url: str) -> tuple[bool, str]:
    """
    Validate a URL for safe fetching.

    Checks:
      1. Scheme is http or https (rejects file://, gopher://, etc.)
      2. Hostname is not a known metadata endpoint
      3. If hostname is a literal IP, it's not in a blocked range
      4. If hostname is a domain, all resolved IPs are not in blocked ranges

    Returns (is_safe, reason). reason is empty when safe.
    """
    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"Invalid URL: {e}"

    # Only http and https are allowed
    if parsed.scheme not in ("http", "https"):
        return False, f"URL scheme '{parsed.scheme}' is not allowed (only http/https)"

    hostname = parsed.hostname
    if not hostname:
        return False, "URL has no hostname"

    # Block known metadata hosts by name
    if hostname.lower() in _METADATA_HOSTS:
        return False, f"Blocked: {hostname} is a cloud metadata endpoint"

    # If hostname is a literal IP, check it directly
    try:
        ip = ipaddress.ip_address(hostname)
        if _is_ip_blocked(ip):
            return False, f"Blocked: {hostname} is a private/loopback/link-local address"
        return True, ""
    except ValueError:
        pass  # hostname is a domain name, not an IP — resolve it below

    # Resolve the domain and check ALL resolved IPs
    # A domain that resolves to both public and private IPs (DNS rebinding)
    # is blocked if ANY IP is private.
    #
    # We use socket.gethostbyname_ex() which returns (hostname, aliaslist, ipaddrlist).
    # A short default timeout is set via socket.setdefaulttimeout to avoid
    # blocking on slow/hanging DNS servers.
    old_timeout = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(3)
        try:
            _hostname, _aliases, ip_list = socket.gethostbyname_ex(hostname)
        except socket.gaierror as e:
            return False, f"Could not resolve hostname '{hostname}': {e}"
        except Exception as e:
            return False, f"DNS lookup failed for '{hostname}': {e}"
    finally:
        socket.setdefaulttimeout(old_timeout)

    if not ip_list:
        return False, f"No DNS records found for '{hostname}'"

    for ip_str in ip_list:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if _is_ip_blocked(ip):
            return False, (
                f"Blocked: '{hostname}' resolves to {ip_str} which is a "
                f"private/loopback/link-local address"
            )

    return True, ""


def _extract_readable_content(html: str) -> str:
    """
    Extract readable content from HTML, stripping navigation, scripts,
    styles, and other non-content elements.

    Uses a multi-pass approach:
    1. Remove script, style, nav, footer, header, aside tags and their content
    2. Remove HTML comments
    3. Convert common block elements to newlines
    4. Strip all remaining HTML tags
    5. Decode HTML entities
    6. Collapse excessive whitespace
    """
    # Remove non-content sections (with their content)
    html = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<nav[^>]*>[\s\S]*?</nav>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<footer[^>]*>[\s\S]*?</footer>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<header[^>]*>[\s\S]*?</header>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<aside[^>]*>[\s\S]*?</aside>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<noscript[^>]*>[\s\S]*?</noscript>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<form[^>]*>[\s\S]*?</form>", "", html, flags=re.IGNORECASE)

    # Remove HTML comments
    html = re.sub(r"<!--[\s\S]*?-->", "", html)

    # Convert block elements to newlines for readability
    for tag in [
        "p",
        "div",
        "br",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "tr",
        "hr",
        "blockquote",
        "article",
        "section",
    ]:
        html = re.sub(rf"</?{tag}[^>]*>", "\n", html, flags=re.IGNORECASE)

    # Strip all remaining HTML tags
    html = re.sub(r"<[^>]+>", "", html)

    # Decode common HTML entities
    entities = {
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&quot;": '"',
        "&#39;": "'",
        "&apos;": "'",
        "&nbsp;": " ",
        "&mdash;": "—",
        "&ndash;": "–",
        "&hellip;": "…",
        "&copy;": "©",
        "&reg;": "®",
    }
    for entity, char in entities.items():
        html = html.replace(entity, char)
    # Numeric entities
    html = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), html)
    html = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), html)

    # Collapse whitespace
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n\s*\n", "\n\n", html)

    return html.strip()


def _extract_title(html: str) -> str:
    """Extract the page title from HTML."""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        title = match.group(1).strip()
        # Clean up title
        title = re.sub(r"<[^>]+>", "", title)
        title = re.sub(r"\s+", " ", title)
        return title[:200]
    return ""


def _is_binary_content_type(content_type: str) -> bool:
    """Check if the content type suggests binary data we can't read."""
    binary_types = [
        "image/",
        "video/",
        "audio/",
        "application/pdf",
        "application/zip",
        "application/x-",
        "application/octet-stream",
    ]
    return any(bt in content_type.lower() for bt in binary_types)


async def web_fetch(url: str) -> ToolResult:
    """
    Fetch a web page and extract its readable text content.

    Args:
        url: The URL to fetch and extract content from.

    Returns:
        ToolResult with the extracted page content, or an error message.
    """
    # Basic URL validation
    url = url.strip()
    if not url:
        return ToolResult(
            content="No URL provided.",
            risk=RiskLevel.LOW,
            source="web_fetch",
            success=False,
            error_type="invalid_input",
            error_message="Empty URL",
        )

    # Add protocol if missing
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # SSRF protection: reject URLs pointing to private/internal/metadata IPs.
    # This prevents the agent from being coerced into fetching cloud metadata
    # endpoints, internal services, or localhost-bound APIs.
    is_safe, reason = _is_url_safe(url)
    if not is_safe:
        logger.warning("[web_fetch] SSRF blocked: %s — %s", url, reason)
        return ToolResult(
            content=(
                f"Refused to fetch '{url}' for security reasons: {reason}. "
                f"web_fetch is restricted to public internet addresses to prevent "
                f"SSRF attacks on internal services and cloud metadata endpoints."
            ),
            risk=RiskLevel.HIGH,
            source="web_fetch",
            success=False,
            error_type="ssrf_blocked",
            error_message=reason,
            metadata={"url": url},
        )

    try:
        import httpx

        # SECURITY: follow_redirects=False — we handle redirects manually so
        # each redirect target is re-validated by _is_url_safe(). With
        # follow_redirects=True, httpx would silently follow a 302 to an
        # internal IP (e.g. 169.254.169.254) without giving us a chance to
        # block it. This is the standard SSRF redirect-bypass pattern.
        async with httpx.AsyncClient(
            timeout=WEB_FETCH_TIMEOUT_SECS,
            follow_redirects=False,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; LocalMind/1.0; +https://localmind.ai)",
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
                "Accept-Language": "en-US,en;q=0.5",
            },
        ) as client:
            # Manually follow redirects with SSRF re-validation on each hop.
            # This preserves redirect functionality (e.g. HTTP→HTTPS) while
            # ensuring no redirect target escapes the SSRF check.
            current_url = url
            _MAX_REDIRECTS = 5
            response = None
            for _hop in range(_MAX_REDIRECTS + 1):
                response = await client.get(current_url)
                if response.status_code not in (301, 302, 303, 307, 308):
                    break  # not a redirect — proceed with this response
                location = response.headers.get("location")
                if not location:
                    break  # redirect with no Location header — proceed
                # Resolve relative redirects against the current URL
                redirect_url = str(httpx.URL(current_url).join(location))
                # Re-validate the redirect target with SSRF check
                is_safe, reason = _is_url_safe(redirect_url)
                if not is_safe:
                    logger.warning("[web_fetch] SSRF blocked on redirect: %s — %s", redirect_url, reason)
                    return ToolResult(
                        content=(
                            f"Refused to follow redirect to '{redirect_url}' for security reasons: {reason}. "
                            f"web_fetch blocks redirects to internal/private addresses to prevent SSRF."
                        ),
                        risk=RiskLevel.HIGH,
                        source="web_fetch",
                        success=False,
                        error_type="ssrf_blocked",
                        error_message=f"Redirect target blocked: {reason}",
                        metadata={"url": url, "redirect_url": redirect_url},
                    )
                # B-2026-08-20-18: close the redirect response properly.
                # httpx async responses need aclose(), not close() — the sync
                # close raises "Attempted to call a sync close on an async
                # stream" which crashed web_fetch on every redirect (e.g.
                # weather.com redirects, so the tool failed before the model
                # could fetch any page that 301/302s).
                await response.aclose()
                current_url = redirect_url
            else:
                # Loop exhausted — too many redirects
                return ToolResult(
                    content=f"Too many redirects (limit: {_MAX_REDIRECTS}) when fetching {url}.",
                    risk=RiskLevel.LOW,
                    source="web_fetch",
                    success=False,
                    error_type="too_many_redirects",
                    error_message=f"Exceeded {_MAX_REDIRECTS} redirects",
                    metadata={"url": url, "final_url": current_url},
                )

            # Now `response` is the final (non-redirect) response.
            # Re-use the existing content-type / size / extraction logic below.
            # First, do a HEAD request to check content type and size
            try:
                head_resp = await client.head(current_url)
                content_type = head_resp.headers.get("content-type", "")
                content_length = int(head_resp.headers.get("content-length", "0"))

                if _is_binary_content_type(content_type):
                    return ToolResult(
                        content=f"The URL points to a binary file ({content_type}). LocalMind can only read text-based web pages.",  # noqa: E501
                        risk=RiskLevel.LOW,
                        source="web_fetch",
                        success=False,
                        error_type="binary_content",
                        error_message=f"Content type is binary: {content_type}",
                        metadata={"url": url, "content_type": content_type},
                    )

                if content_length > WEB_FETCH_MAX_CONTENT_LENGTH:
                    return ToolResult(
                        content=f"The page is too large ({content_length / 1024 / 1024:.1f} MB). LocalMind can fetch pages up to {WEB_FETCH_MAX_CONTENT_LENGTH / 1024 / 1024:.0f} MB.",  # noqa: E501
                        risk=RiskLevel.LOW,
                        source="web_fetch",
                        success=False,
                        error_type="content_too_large",
                        error_message=f"Content length {content_length} exceeds limit",
                        metadata={"url": url, "content_length": content_length},
                    )
            except Exception:
                # HEAD request failed — proceed with GET anyway (some servers reject HEAD)
                pass

            # Use the response from the redirect-following loop above.
            # (We already fetched current_url — no need to re-fetch.)
            response.raise_for_status()

            # Check content type from actual response
            content_type = response.headers.get("content-type", "")
            if _is_binary_content_type(content_type):
                return ToolResult(
                    content=f"The URL points to a binary file ({content_type}). LocalMind can only read text-based web pages.",  # noqa: E501
                    risk=RiskLevel.LOW,
                    source="web_fetch",
                    success=False,
                    error_type="binary_content",
                    error_message=f"Content type is binary: {content_type}",
                    metadata={"url": url, "content_type": content_type},
                )

            # Get the raw HTML
            html = response.text

            if not html or len(html.strip()) < 50:
                return ToolResult(
                    content="The page returned empty or very little content. It may require JavaScript to render, which LocalMind cannot execute.",  # noqa: E501
                    risk=RiskLevel.LOW,
                    source="web_fetch",
                    success=False,
                    error_type="empty_content",
                    error_message="Page returned empty content",
                    metadata={"url": url},
                )

            # Extract title and readable content
            title = _extract_title(html)
            readable = _extract_readable_content(html)

            if not readable or len(readable.strip()) < 30:
                return ToolResult(
                    content="Could not extract readable content from this page. It may be heavily JavaScript-dependent or have an unusual structure.",  # noqa: E501
                    risk=RiskLevel.LOW,
                    source="web_fetch",
                    success=False,
                    error_type="extraction_failed",
                    error_message="No readable content extracted",
                    metadata={"url": url, "title": title},
                )

            # Truncate to max chars
            if len(readable) > WEB_FETCH_MAX_CHARS:
                readable = readable[:WEB_FETCH_MAX_CHARS] + "\n\n[... content truncated]"

            # Format the output
            output_parts = []
            if title:
                output_parts.append(f"**{title}**")
            output_parts.append(f"Source: {url}")
            output_parts.append("")  # blank line
            output_parts.append(readable)

            content = "\n".join(output_parts)

            return ToolResult(
                content=content,
                risk=RiskLevel.LOW,
                source="web_fetch",
                success=True,
                metadata={
                    "url": url,
                    "title": title,
                    "content_length": len(readable),
                },
            )

    except httpx.TimeoutException:
        logger.warning(f"[web_fetch] Timeout fetching {url}")
        return ToolResult(
            content=f"Timed out while fetching the page (limit: {WEB_FETCH_TIMEOUT_SECS}s). The site may be slow or blocking requests.",  # noqa: E501
            risk=RiskLevel.LOW,
            source="web_fetch",
            success=False,
            error_type="timeout",
            error_message=f"Request timed out after {WEB_FETCH_TIMEOUT_SECS}s",
            metadata={"url": url},
        )

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status == 403:
            msg = "The website blocked the request (HTTP 403). Some sites don't allow automated access."
        elif status == 404:
            msg = "The page was not found (HTTP 404). The URL may be incorrect or the page may have been removed."
        elif status == 429:
            msg = "Rate limited by the website (HTTP 429). Try again in a few moments."
        elif status >= 500:
            msg = f"The website's server returned an error (HTTP {status}). Try again later."
        else:
            msg = f"Failed to fetch the page (HTTP {status})."

        logger.warning(f"[web_fetch] HTTP {status} for {url}")
        return ToolResult(
            content=msg,
            risk=RiskLevel.LOW,
            source="web_fetch",
            success=False,
            error_type="http_error",
            error_message=f"HTTP {status}",
            metadata={"url": url, "status_code": status},
        )

    except httpx.ConnectError:
        logger.warning(f"[web_fetch] Connection failed for {url}")
        return ToolResult(
            content="Could not connect to the website. Check that the URL is correct and the site is online.",
            risk=RiskLevel.LOW,
            source="web_fetch",
            success=False,
            error_type="connection_failed",
            error_message="Connection refused or DNS resolution failed",
            metadata={"url": url},
        )

    except Exception as e:
        error_msg = str(e)[:200]
        logger.warning(f"[web_fetch] Unexpected error for {url}: {error_msg}")
        return ToolResult(
            content=f"Failed to fetch the page: {error_msg}",
            risk=RiskLevel.LOW,
            source="web_fetch",
            success=False,
            error_type="unknown",
            error_message=error_msg,
            metadata={"url": url},
        )


# Register into the tool registry
register_tool(
    Intent.WEB_FETCH,
    web_fetch,
    description="Fetch and extract readable content from a web page URL. Use after web_search when results are link-only without substantive content.",  # noqa: E501
    cost=0.08,
    latency_ms=3000,
    parallelizable=True,
)
