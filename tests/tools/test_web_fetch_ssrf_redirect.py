"""
Regression test for the SSRF redirect bypass fix in web_fetch.

Verifies that web_fetch re-validates each redirect target via _is_url_safe().
Without the fix, a public URL returning a 302 to an internal IP (e.g.
169.254.169.254) would be followed by httpx without re-validation, bypassing
the SSRF protection and allowing the agent to read cloud metadata endpoints,
internal services, or the Ollama API itself.

The test mocks httpx.AsyncClient (so no real network calls are made) AND
mocks _is_url_safe (so DNS resolution of example domains doesn't interfere).
_is_url_safe is mocked to return True for the initial public URL and False
for any URL pointing at a private/internal/metadata address — exactly the
behaviour the real function would exhibit if the DNS resolved.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.web_fetch import web_fetch


# URLs we consider "safe" (public) in these tests. Everything else is
# treated as blocked. This lets us test the redirect-following logic in
# isolation without depending on real DNS resolution.
_SAFE_URLS = {
    "https://example.com/old-path",
    "https://example.com/new-path",
    "https://example.com/start",
    "https://example.com/step2",
    "https://attacker.example.com/redirect",
}


def _fake_is_url_safe(url: str):
    """Mock _is_url_safe: safe for known public URLs, blocked for everything else."""
    if url in _SAFE_URLS:
        return True, ""
    return False, f"Blocked: {url} resolves to a private/loopback/link-local address"


def _make_response(status_code: int, headers: dict | None = None, text: str = ""):
    """Build a mock httpx.Response with the given status, headers, and body."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.text = text
    resp.aread = AsyncMock(return_value=b"")
    resp.aclose = AsyncMock()
    return resp


@pytest.mark.asyncio
async def test_web_fetch_blocks_redirect_to_private_ip():
    """A 302 redirect to 169.254.169.254 must be blocked — not followed."""
    public_url = "https://attacker.example.com/redirect"
    metadata_url = "http://169.254.169.254/latest/meta-data/"

    redirect_response = _make_response(
        302,
        headers={"location": metadata_url},
    )
    # If the bug exists and web_fetch follows the redirect, this second
    # response would be returned. The test fails if this is ever reached.
    metadata_response = _make_response(
        200,
        headers={"content-type": "text/html"},
        text="<html><body>IAM_TOKEN=AKIAIOSFODNN7EXAMPLE</body></html>",
    )

    with patch("tools.web_fetch._is_url_safe", side_effect=_fake_is_url_safe), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=[redirect_response, metadata_response])
        mock_client.head = AsyncMock(
            return_value=_make_response(200, headers={"content-type": "text/html"})
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await web_fetch(public_url)

    # The result must be an SSRF block, NOT a successful fetch of the
    # metadata endpoint.
    assert result.success is False, "web_fetch must refuse to follow the redirect"
    assert result.error_type == "ssrf_blocked", (
        f"Expected ssrf_blocked, got {result.error_type}"
    )
    assert "169.254.169.254" in result.error_message or "private" in result.error_message.lower(), (
        f"Error message should mention the blocked IP, got: {result.error_message}"
    )
    # Critical: the metadata page content must NEVER appear in the result.
    assert "AKIAIOSFODNN7EXAMPLE" not in result.content, (
        "SSRF bypass — the agent fetched the cloud metadata endpoint!"
    )
    # And the second GET (to the metadata IP) must never have been called.
    assert mock_client.get.call_count == 1, (
        f"Expected exactly 1 GET (the initial fetch), got {mock_client.get.call_count} "
        "— the redirect must not have been followed."
    )


@pytest.mark.asyncio
async def test_web_fetch_allows_redirect_to_public_url():
    """A 302 redirect to another public URL should be followed normally."""
    public_url = "https://example.com/old-path"
    redirect_target = "https://example.com/new-path"

    redirect_response = _make_response(
        302,
        headers={"location": redirect_target},
    )
    final_response = _make_response(
        200,
        headers={"content-type": "text/html"},
        text="<html><head><title>Example</title></head><body><p>Hello world content here</p></body></html>",
    )

    with patch("tools.web_fetch._is_url_safe", side_effect=_fake_is_url_safe), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=[redirect_response, final_response])
        mock_client.head = AsyncMock(
            return_value=_make_response(200, headers={"content-type": "text/html"})
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await web_fetch(public_url)

    # The redirect to a public URL should be followed successfully.
    assert result.success is True, (
        f"Redirect to public URL should be followed, got error: {result.error_message}"
    )
    assert "Hello world" in result.content
    # Two GETs: the initial fetch + the redirect target.
    assert mock_client.get.call_count == 2


@pytest.mark.asyncio
async def test_web_fetch_blocks_redirect_chain_to_localhost():
    """A chain: public → public → localhost must be blocked at the localhost hop."""
    public_url = "https://example.com/start"

    first_redirect = _make_response(
        302,
        headers={"location": "https://example.com/step2"},
    )
    second_redirect = _make_response(
        302,
        headers={"location": "http://localhost:11434/api/tags"},
    )
    # This should never be reached, but include it so the test fails loudly
    # if the bypass exists.
    ollama_response = _make_response(
        200,
        headers={"content-type": "application/json"},
        text='{"models":[{"name":"llama3.1"}]}',
    )

    with patch("tools.web_fetch._is_url_safe", side_effect=_fake_is_url_safe), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get = AsyncMock(
            side_effect=[first_redirect, second_redirect, ollama_response]
        )
        mock_client.head = AsyncMock(
            return_value=_make_response(200, headers={"content-type": "text/html"})
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        result = await web_fetch(public_url)

    assert result.success is False
    assert result.error_type == "ssrf_blocked"
    # The Ollama API response must never leak into the result.
    assert "llama3.1" not in result.content, "SSRF bypass — Ollama API was accessed!"
    # Only 2 GETs should have happened: the initial + the first redirect target.
    # The third GET (to localhost) must never fire.
    assert mock_client.get.call_count == 2, (
        f"Expected 2 GETs (initial + first redirect), got {mock_client.get.call_count}"
    )
