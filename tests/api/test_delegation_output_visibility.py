"""Regression tests for delegated-output presentation isolation."""

from __future__ import annotations

import pytest

from api.routes.chat import _visible_tool_output


@pytest.mark.parametrize(
    ("tool_name", "agent_name", "output", "expected"),
    [
        ("delegate", None, "child report", ""),
        ("delegate_parallel", None, "parallel child report", ""),
        ("delegate_inline", None, "inline child report", ""),
        ("web_search", "research", "raw child search result", ""),
        ("shell", "coding", "raw child shell output", ""),
        ("web_search", None, "parent search output", "parent search output"),
        ("shell", None, "parent shell output", "parent shell output"),
    ],
)
def test_visible_tool_output_hides_only_delegated_results(
    tool_name: str,
    agent_name: str | None,
    output: str,
    expected: str,
) -> None:
    assert _visible_tool_output(tool_name, agent_name, output) == expected
