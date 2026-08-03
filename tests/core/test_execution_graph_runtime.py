"""Tests for the first live, read-only ExecutionGraph runtime boundary."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from core.execution_graph import (
    GRAPH_RUNTIME_SAFE_INTENTS,
    ExecutionGraph,
    ExecutionNode,
    NodeStatus,
    _serialize_tool_args,
    execute_graph,
    format_graph_results,
    graph_runtime_errors,
)
from core.models import Capability, ExecutionConstraints, Intent, RiskLevel, ToolResult


def _node(
    node_id: str,
    capability: Capability,
    intent: Intent,
    *,
    depends_on: list[str] | None = None,
    args: dict | None = None,
    optional: bool = False,
) -> ExecutionNode:
    return ExecutionNode(
        id=node_id,
        capability=capability,
        intent=intent,
        depends_on=depends_on or [],
        tool_args=args or {},
        optional=optional,
    )


def test_read_only_runtime_admits_only_safe_intents():
    assert GRAPH_RUNTIME_SAFE_INTENTS == {
        Intent.WEB_SEARCH,
        Intent.WEB_FETCH,
        Intent.SYSINFO,
    }

    graph = ExecutionGraph(
        nodes=[
            _node("search", Capability.WEB_SEARCH, Intent.WEB_SEARCH),
            _node("write", Capability.FILE_WRITE, Intent.FILE_WRITE),
        ]
    )

    errors = graph_runtime_errors(graph)

    assert any("write" in error for error in errors)
    assert any("not admitted" in error for error in errors)


def test_graph_runtime_rejects_invalid_dependencies_before_execution():
    graph = ExecutionGraph(
        nodes=[
            _node(
                "fetch",
                Capability.WEB_FETCH,
                Intent.WEB_FETCH,
                depends_on=["missing"],
            )
        ]
    )

    errors = graph_runtime_errors(graph)

    assert "Node 'fetch' depends on non-existent node 'missing'" in errors


def test_graph_serializer_preserves_url_argument():
    node = _node(
        "fetch",
        Capability.WEB_FETCH,
        Intent.WEB_FETCH,
        args={"url": "https://example.com/article"},
    )

    assert _serialize_tool_args(node) == "https://example.com/article"


@pytest.mark.asyncio
async def test_execute_graph_runs_dependency_waves_and_records_results():
    graph = ExecutionGraph(
        nodes=[
            _node("search", Capability.WEB_SEARCH, Intent.WEB_SEARCH, args={"query": "local AI"}),
            _node(
                "fetch",
                Capability.WEB_FETCH,
                Intent.WEB_FETCH,
                depends_on=["search"],
                args={"url": "https://example.com"},
            ),
        ]
    )
    constraints = ExecutionConstraints(allow_parallel=False, tool_retry_base_delay=0)
    results = [
        ToolResult(content="search result", source="web_search", risk=RiskLevel.LOW),
        ToolResult(content="page content", source="web_fetch", risk=RiskLevel.LOW),
    ]

    with patch("tools.dispatch", new=AsyncMock(side_effect=results)) as dispatch:
        executed = await execute_graph(graph, constraints)

    assert [node.status for node in executed.nodes] == [NodeStatus.COMPLETED, NodeStatus.COMPLETED]
    assert executed.completed_results()["fetch"].content == "page content"
    assert [call.args for call in dispatch.await_args_list] == [
        (Intent.WEB_SEARCH, "local AI"),
        (Intent.WEB_FETCH, "https://example.com"),
    ]


@pytest.mark.asyncio
async def test_execute_graph_marks_required_tool_failure_and_skips_dependents():
    graph = ExecutionGraph(
        nodes=[
            _node("search", Capability.WEB_SEARCH, Intent.WEB_SEARCH, args={"query": "local AI"}),
            _node(
                "fetch",
                Capability.WEB_FETCH,
                Intent.WEB_FETCH,
                depends_on=["search"],
                args={"url": "https://example.com"},
            ),
        ]
    )
    failure = ToolResult(
        content="provider unavailable",
        source="web_search",
        success=False,
        error_type="provider_error",
    )

    with patch("tools.dispatch", new=AsyncMock(return_value=failure)) as dispatch:
        executed = await execute_graph(
            graph,
            ExecutionConstraints(tool_retry_base_delay=0),
        )

    assert executed.nodes[0].status is NodeStatus.FAILED
    assert executed.nodes[1].status is NodeStatus.SKIPPED
    assert executed.has_failed_required()
    assert dispatch.await_count == 2


@pytest.mark.asyncio
async def test_execute_graph_blocks_node_outside_tool_policy_without_dispatching():
    graph = ExecutionGraph(
        nodes=[_node("sysinfo", Capability.SYSINFO, Intent.SYSINFO, args={"query": "date"})]
    )

    with patch("tools.dispatch", new=AsyncMock()) as dispatch:
        executed = await execute_graph(
            graph,
            ExecutionConstraints(tool_retry_base_delay=0),
            allowed_tool_names=frozenset({Intent.WEB_SEARCH.value}),
        )

    node = executed.nodes[0]
    assert node.status is NodeStatus.FAILED
    assert node.result is not None
    assert node.result.error_type == "permission"
    dispatch.assert_not_awaited()


def test_format_graph_results_is_bounded_and_includes_failures():
    graph = ExecutionGraph(
        nodes=[
            ExecutionNode(
                id="search",
                capability=Capability.WEB_SEARCH,
                intent=Intent.WEB_SEARCH,
                status=NodeStatus.COMPLETED,
                result=ToolResult(content="a" * 5000, source="web_search"),
            ),
            ExecutionNode(
                id="fetch",
                capability=Capability.WEB_FETCH,
                intent=Intent.WEB_FETCH,
                status=NodeStatus.FAILED,
                result=ToolResult(
                    content="provider unavailable",
                    source="web_fetch",
                    success=False,
                    error_type="execution_error",
                ),
            ),
        ]
    )

    rendered = format_graph_results(graph, max_chars=500)

    assert len(rendered) <= 500
    assert "search" in rendered
    assert "fetch" in rendered or "provider unavailable" in rendered
    assert "truncated" in rendered.lower()
