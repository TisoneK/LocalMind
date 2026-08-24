"""Regression tests for the degenerate-input guard's input_optional exemption.

Sessions 399/400 (chat exports 2026-08-24): the parent loop's degenerate-input
guard rejected a bare ``sysinfo()`` call as "input is empty or too short",
even though sysinfo returns the full default summary when called with no query.
The rejection sent the model into a retry/flail spiral — wasted iterations,
narration instead of answers, and (for "Show me my storage") an iteration-limit
worker-report leak. The fix: tools declare ``input_optional=True`` and the guard
exempts them. These tests pin that contract at every layer.
"""

from __future__ import annotations

from core.models import Intent
from tools import input_is_optional


def _guard_rejects(tool_name: str, tool_input: str) -> bool:
    """Mirror the loop's degenerate-input guard condition (loop.py)."""
    from core.agent.loop import _tool_allows_empty_input

    return (
        not tool_input or len(tool_input.strip("?. \t")) < 3
    ) and not _tool_allows_empty_input(tool_name)


def test_sysinfo_and_observe_declare_input_optional() -> None:
    assert input_is_optional(Intent.SYSINFO) is True
    assert input_is_optional(Intent.OBSERVE) is True


def test_input_requiring_tools_are_not_optional() -> None:
    # shell / web_search etc. must still reject empty input.
    assert input_is_optional(Intent.SHELL) is False
    assert input_is_optional(Intent.WEB_SEARCH) is False


def test_bare_sysinfo_is_not_rejected_by_guard() -> None:
    # The exact failure: empty query on a system-info call.
    assert _guard_rejects("sysinfo", "") is False
    assert _guard_rejects("sysinfo", "ip") is False  # short-but-valid section
    assert _guard_rejects("observe", "") is False


def test_bare_shell_is_still_rejected_by_guard() -> None:
    # No regression: input-requiring tools keep the guard.
    assert _guard_rejects("shell", "") is True
    assert _guard_rejects("web_search", "ab") is True


def test_unknown_tool_defaults_to_requiring_input() -> None:
    assert _guard_rejects("not_a_real_tool", "") is True
