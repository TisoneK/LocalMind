"""Regression tests for explicit read-only objective tool policy."""

from __future__ import annotations

import pytest

from core.agent.tool_dispatch import dispatch_with_retry
from core.models import Intent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name",
    ["shell", "file_write", "file_edit", "code_exec", "process", "git", "delegate", "memory_op"],
)
async def test_read_only_policy_blocks_mutation_capable_tools(monkeypatch, tool_name):
    """A policy rejection must happen before the real tool dispatcher runs."""
    called = False

    async def unexpected_dispatch(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("blocked objective tool reached the dispatcher")

    monkeypatch.setattr("core.agent.tool_dispatch.dispatch", unexpected_dispatch)

    result, failed, retries = await dispatch_with_retry(
        Intent(tool_name),
        "test input",
        allowed_tool_names=frozenset({"file_task", "web_search", "web_fetch", "sysinfo"}),
    )

    assert result is not None
    assert result.success is False
    assert result.error_type == "permission"
    assert "not available" in result.content
    assert failed is True
    assert retries == 0
    assert called is False


@pytest.mark.asyncio
async def test_read_only_policy_allows_file_task(monkeypatch):
    """An explicitly allowed read-only tool still reaches normal dispatch."""
    calls = []

    async def allowed_dispatch(intent, tool_input):
        calls.append((intent, tool_input))
        from core.models import RiskLevel, ToolResult

        return ToolResult(
            content="file contents",
            source=intent.value,
            success=True,
            risk=RiskLevel.LOW,
        )

    monkeypatch.setattr("core.agent.tool_dispatch.dispatch", allowed_dispatch)

    result, failed, retries = await dispatch_with_retry(
        Intent.FILE_TASK,
        "/tmp/example.txt",
        allowed_tool_names=frozenset({"file_task"}),
    )

    assert result is not None
    assert result.success is True
    assert result.content == "file contents"
    assert failed is False
    assert retries == 0
    assert calls == [(Intent.FILE_TASK, "/tmp/example.txt")]
