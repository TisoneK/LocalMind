"""Content-absent shell detection + raw-evidence cleaning.

Two user-visible fixes from the 'trending stories' trace:
1. JS-gate / bare-loading pages (content absent) must be treated as boilerplate
   so the router escalates them to a rendering strategy instead of accepting the
   'enable JavaScript' notice as the answer.
2. When synthesis is rate-limited and the agent must dump raw evidence, page
   chrome (Subscribe now / LOGOUT / Loading…) is stripped so the user sees
   actual headlines.
"""

from __future__ import annotations

from core.web_acquisition import _is_boilerplate, _is_content_gated_shell
from core.agent.loop import _clean_evidence_text


class TestContentGatedShell:
    def test_js_gate_is_flagged(self):
        assert _is_content_gated_shell("Please enable JavaScript to view this site.") is True
        assert _is_boilerplate("Please enable JavaScript to view. Home Menu Footer") is True

    def test_loading_shell_is_flagged(self):
        assert _is_content_gated_shell("Loading…") is True
        assert _is_content_gated_shell("Loading... Loading Loading") is True

    def test_real_long_article_with_js_mention_not_flagged(self):
        article = (
            "The match ended 2-1 with a late winner. " * 60
            + " (Please enable javascript to see reader comments.)"
        )
        assert _is_content_gated_shell(article) is False
        assert _is_boilerplate(article) is False

    def test_real_content_not_flagged(self):
        assert _is_content_gated_shell(
            "Manchester City beat Arsenal 2-1 in a thrilling encounter at the Etihad."
        ) is False


class TestEvidenceCleaning:
    def test_strips_chrome_keeps_headlines(self):
        dirty = (
            "You are logged in\nLOGOUT\nSubscribe now\nLoading...\n"
            "Iran says US strike killed four at wedding\nMenu\n"
            "EU and Nato vow to step up pressure on Russia\nAdvertisement"
        )
        cleaned = _clean_evidence_text(dirty)
        assert "Iran says US strike killed four at wedding" in cleaned
        assert "EU and Nato vow to step up pressure on Russia" in cleaned
        assert "Subscribe now" not in cleaned
        assert "LOGOUT" not in cleaned
        assert "Loading" not in cleaned
        assert "Menu" not in cleaned

    def test_keeps_source_header_and_numbered_lines(self):
        text = "**Source:** https://x.com\n1. First headline here\nSign in"
        cleaned = _clean_evidence_text(text)
        assert "**Source:**" in cleaned
        assert "1. First headline here" in cleaned
        assert "Sign in" not in cleaned

    def test_empty_input_safe(self):
        assert _clean_evidence_text("") == ""
        assert _clean_evidence_text(None) == ""
