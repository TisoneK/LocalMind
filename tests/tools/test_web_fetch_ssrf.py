"""
Tests for web_fetch SSRF protection.

Verifies that _is_url_safe() correctly blocks URLs pointing to:
  - Private IP ranges (RFC 1918)
  - Loopback addresses (127/8, ::1)
  - Link-local addresses (169.254/16 — includes cloud metadata)
  - Cloud metadata hostnames
  - Non-http/https schemes (file://, gopher://, etc.)

And allows URLs pointing to public internet addresses.
"""
from __future__ import annotations
import pytest
from tools.web_fetch import _is_url_safe, _is_ip_blocked
import ipaddress


class TestIsIpBlocked:
    """Test the IP address range blocking logic."""

    @pytest.mark.parametrize("ip_str", [
        "10.0.0.1",           # private 10/8
        "10.255.255.255",     # private 10/8 upper bound
        "172.16.0.1",         # private 172.16/12
        "172.31.255.255",     # private 172.16/12 upper bound
        "192.168.1.1",        # private 192.168/16
        "192.168.0.0",        # private 192.168/16 lower bound
        "127.0.0.1",          # loopback
        "127.255.255.255",    # loopback upper bound
        "169.254.169.254",    # link-local / cloud metadata
        "169.254.0.1",        # link-local
        "0.0.0.0",            # unspecified
        "224.0.0.1",          # multicast
        "::1",                # IPv6 loopback
        "fc00::1",            # IPv6 unique-local (private)
        "fd00::1",            # IPv6 unique-local (private)
        "fe80::1",            # IPv6 link-local
        "::",                 # IPv6 unspecified
    ])
    def test_blocks_private_and_internal_ips(self, ip_str: str):
        ip = ipaddress.ip_address(ip_str)
        assert _is_ip_blocked(ip), f"IP {ip_str} should be blocked"

    @pytest.mark.parametrize("ip_str", [
        "8.8.8.8",            # Google DNS (public)
        "1.1.1.1",            # Cloudflare DNS (public)
        "93.184.216.34",      # example.com (public)
        "2606:2800:220:1:248:1893:25c8:1946",  # IPv6 public
    ])
    def test_allows_public_ips(self, ip_str: str):
        ip = ipaddress.ip_address(ip_str)
        assert not _is_ip_blocked(ip), f"IP {ip_str} should be allowed"


class TestIsUrlSafe:
    """Test the URL safety validation."""

    # ── Blocked schemes ──────────────────────────────────────────────────

    @pytest.mark.parametrize("url", [
        "file:///etc/passwd",
        "file:///C:/Windows/System32/config/SAM",
        "gopher://localhost:6379/_INFO",
        "ftp://example.com/file.txt",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
    ])
    def test_blocks_unsafe_schemes(self, url: str):
        is_safe, reason = _is_url_safe(url)
        assert not is_safe, f"URL should be blocked: {url}"
        assert "scheme" in reason.lower() or "not allowed" in reason.lower()

    # ── Blocked IPs (literal IP in URL) ──────────────────────────────────

    @pytest.mark.parametrize("url", [
        "http://127.0.0.1/",
        "http://127.0.0.1:8080/admin",
        "http://localhost/",          # localhost resolves to 127.0.0.1
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://169.254.169.254/latest/meta-data/",    # AWS metadata
        "http://169.254.169.254/computeMetadata/v1/",  # GCP metadata
        "http://0.0.0.0/",
        "http://[::1]/",              # IPv6 loopback
    ])
    def test_blocks_private_and_metadata_ips(self, url: str):
        is_safe, reason = _is_url_safe(url)
        assert not is_safe, f"URL should be blocked: {url} (reason was: {reason})"
        assert "blocked" in reason.lower() or "metadata" in reason.lower() or "private" in reason.lower()

    # ── Blocked metadata hostnames ───────────────────────────────────────

    @pytest.mark.parametrize("url", [
        "http://metadata.google.internal/computeMetadata/v1/",
    ])
    def test_blocks_metadata_hostnames(self, url: str):
        is_safe, reason = _is_url_safe(url)
        assert not is_safe, f"URL should be blocked: {url}"
        assert "metadata" in reason.lower()

    # ── Allowed public URLs ──────────────────────────────────────────────

    @pytest.mark.parametrize("url", [
        "https://example.com/",
        "https://www.google.com/",
        "https://en.wikipedia.org/wiki/SSRF",
        "http://93.184.216.34/",        # example.com IP (public)
        "https://api.github.com/repos",
    ])
    def test_allows_public_urls(self, url: str):
        is_safe, reason = _is_url_safe(url)
        assert is_safe, f"URL should be allowed: {url} (reason was: {reason})"

    # ── Edge cases ───────────────────────────────────────────────────────

    def test_blocks_url_without_hostname(self):
        is_safe, reason = _is_url_safe("https:///path")
        assert not is_safe
        assert "hostname" in reason.lower()

    def test_blocks_url_without_scheme(self):
        # _is_url_safe is called after protocol is prepended in web_fetch,
        # but we test the raw function too — it should reject schemeless URLs
        # because urlparse won't parse a scheme-less URL correctly.
        # This is an edge case; the main web_fetch path prepends https://.
        is_safe, _ = _is_url_safe("example.com")
        # urlparse("example.com") treats "example.com" as a path, not a hostname.
        # So scheme will be "" → blocked. This is correct behavior.
        assert not is_safe
