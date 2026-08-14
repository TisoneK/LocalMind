"""Regression tests for current time/date handling in the parent loop."""

from __future__ import annotations

from core.agent.text_tools import (
    _authoritative_sysinfo_answer,
    _is_current_system_query,
    _normalize_system_tool_call,
)


_CURRENT_RESULT = (
    "Current date/time: Friday, August 14, 2026  03:36:47 PM "
    "(E. Africa Standard Time, UTC+0300)"
)


def test_current_time_phrasings_are_system_queries() -> None:
    for query in (
        "whats the time?",
        "what's the time?",
        "what is the current time",
        "what time is it",
        "what day is it",
        "what is today's date",
        "current date",
    ):
        assert _is_current_system_query(query), query


def test_unrelated_shell_request_is_not_a_system_query() -> None:
    assert not _is_current_system_query("run Get-Date in the terminal")
    assert not _is_current_system_query("show me the current project files")


def test_shell_clock_call_is_corrected_to_sysinfo() -> None:
    tool, args, corrected = _normalize_system_tool_call(
        "whats the time?",
        "shell",
        {"command": "Get-Date"},
    )
    assert corrected is True
    assert tool == "sysinfo"
    assert args == {"query": "whats the time?"}


def test_non_clock_shell_call_is_unchanged() -> None:
    tool, args, corrected = _normalize_system_tool_call(
        "run Get-Date in the terminal",
        "shell",
        {"command": "Get-Date"},
    )
    assert corrected is False
    assert tool == "shell"
    assert args == {"command": "Get-Date"}


def test_sysinfo_answer_preserves_exact_verified_date() -> None:
    answer = _authoritative_sysinfo_answer(_CURRENT_RESULT, "whats the time?")
    assert answer == _CURRENT_RESULT
    assert "August 14, 2026" in answer
    assert "August 1, 2026" not in answer


def test_non_clock_sysinfo_answer_is_unchanged() -> None:
    content = "OS: Darwin\nRAM: 16 GB"
    assert _authoritative_sysinfo_answer(content, "what are my computer specs?") == content
