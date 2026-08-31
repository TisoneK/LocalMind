"""ToolResult must accept None on error_type/error_message (the natural
'no error' value a tool passes on its success path) and coerce it to "".

Regression: web_research built `ToolResult(success=True, error_type=None,
error_message=None)` on success; the str-typed fields rejected None, the whole
construction raised a ValidationError, and the tool re-wrapped it as a
misleading 'Web research failed: 2 validation errors for ToolResult' even
though the research had SUCCEEDED (user-found, live, 2026-08-31).
"""

from __future__ import annotations

from core.models import ToolResult


def test_success_path_none_error_fields_coerced_to_empty():
    # exactly how web_research constructs on the success branch
    r = ToolResult(
        content="scores...", source="web_research", success=True,
        error_type=None, error_message=None,
    )
    assert r.error_type == ""
    assert r.error_message == ""
    assert r.success is True


def test_failure_path_strings_preserved():
    r = ToolResult(
        content="boom", source="web_research", success=False,
        error_type="acquisition_failed", error_message="no sources",
    )
    assert r.error_type == "acquisition_failed"
    assert r.error_message == "no sources"


def test_defaults_still_empty_strings():
    r = ToolResult(content="ok", source="t")
    assert r.error_type == ""
    assert r.error_message == ""
