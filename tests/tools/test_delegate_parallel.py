"""
Session 81: B-2026-08-02-6 (B1) — delegate_parallel tool tests.

The parallel delegation primitive: fans out up to 5 independent sub-task
delegations to specialized agents concurrently via asyncio.gather,
returning a markdown summary of every child's output. Partial failure is
first-class (one child erroring doesn't cancel the others).
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest
from core.agent.delegation import get_current_run_id
from core.models import Intent, StreamChunk

# ── Registration / wiring ───────────────────────────────────────────────


def test_delegate_parallel_intent_exists():
    assert Intent.DELEGATE_PARALLEL.value == "delegate_parallel"


def test_delegate_parallel_tool_is_registered():
    """Registered in the tool registry with parallelizable=True."""
    from tools import _REGISTRY

    assert Intent.DELEGATE_PARALLEL in _REGISTRY, (
        "Intent.DELEGATE_PARALLEL not registered — delegate_parallel must be "
        "imported in tools/__init__.py"
    )
    entry = _REGISTRY[Intent.DELEGATE_PARALLEL]
    assert entry["description"], "delegate_parallel has no description"
    assert entry["cost"] > 0
    assert entry["parallelizable"] is True, (
        "delegate_parallel IS the parallel primitive — must be parallelizable=True"
    )


def test_delegate_parallel_in_agent_allowed_tools():
    from core.agent.constants import AGENT_ALLOWED_TOOLS

    assert "delegate_parallel" in AGENT_ALLOWED_TOOLS


def test_delegate_parallel_in_coding_tools():
    from agents.coding.tools import CODING_TOOLS

    assert "delegate_parallel" in CODING_TOOLS


def test_delegate_parallel_in_tool_definitions():
    from core.agent.loop import TOOL_DEFINITIONS

    names = [t["function"]["name"] for t in TOOL_DEFINITIONS]
    assert "delegate_parallel" in names


def test_extract_tool_input_delegate_parallel():
    """The loop serializes the targets array as JSON for the tool."""
    from core.agent.loop import _extract_tool_input

    out = _extract_tool_input(
        "delegate_parallel", {"targets": [{"agent": "research", "task": "summarize docs"}]}
    )
    parsed = json.loads(out)
    assert parsed["targets"][0]["task"] == "summarize docs"


# ── Tool behavior ───────────────────────────────────────────────────────


def _set_registry(registry_map: dict):
    from agents.registry import _REGISTRY

    saved = dict(_REGISTRY)
    _REGISTRY.clear()
    _REGISTRY.update(registry_map)
    return saved


def _restore_registry(saved: dict):
    from agents.registry import _REGISTRY

    _REGISTRY.clear()
    _REGISTRY.update(saved)


def _set_adapter_and_depth():
    """Return (adapter_token, depth_token) — reset both in finally."""
    from tools import delegate_parallel as dp_mod

    adapter_token = dp_mod._current_adapter.set(MagicMock())
    depth_token = dp_mod._current_depth.set(0)
    return adapter_token, depth_token


def _reset_adapter_and_depth(adapter_token, depth_token):
    from tools import delegate_parallel as dp_mod

    dp_mod._current_depth.reset(depth_token)
    dp_mod._current_adapter.reset(adapter_token)


@pytest.mark.asyncio
async def test_delegate_parallel_runs_children_concurrently():
    """Two children must run SIMULTANEOUSLY — proven with a barrier: each
    child waits until BOTH have entered before returning. If the children
    ran serially, the second would never start and the fan-out would hit
    the wall-clock cap."""
    from tools.delegate_parallel import delegate_parallel

    barrier = {"entered": 0, "go": asyncio.Event()}

    class _BarrierAgent:
        def __init__(self, adapter=None):
            self.adapter = adapter

        async def run(self, **kwargs):
            barrier["entered"] += 1
            if barrier["entered"] == 2:
                barrier["go"].set()
            await barrier["go"].wait()
            yield StreamChunk(text="child output", done=False)
            yield StreamChunk(text="", done=True)

    saved = _set_registry({"research": _BarrierAgent, "analyst": _BarrierAgent})
    adapter_token, depth_token = _set_adapter_and_depth()
    try:
        result = await delegate_parallel(
            json.dumps(
                {
                    "targets": [
                        {"agent": "research", "task": "task one"},
                        {"agent": "analyst", "task": "task two"},
                    ]
                }
            )
        )
    finally:
        _reset_adapter_and_depth(adapter_token, depth_token)
        _restore_registry(saved)

    assert result.success is True
    assert result.source == "delegate_parallel"
    assert "2/2" in result.content
    assert result.metadata["completed"] == 2
    statuses = [r["status"] for r in result.metadata["results"]]
    assert statuses == ["completed", "completed"]
    assert get_current_run_id() is None, "child run_id must be reset after the fan-out"


@pytest.mark.asyncio
async def test_parallel_child_sees_incremented_depth():
    """A child running under gather() must see depth = parent+1 in ITS OWN
    context — the contextvar propagation that makes nested delegation from
    a parallel child safe. The depth-cap test sets the contextvar manually;
    this proves the gather-time increment actually happens."""
    from tools import delegate as handoff_mod
    from tools.delegate_parallel import delegate_parallel

    observed = {}

    class _NestingChild:
        def __init__(self, adapter=None):
            self.adapter = adapter

        async def run(self, **kwargs):
            observed["depth"] = handoff_mod.get_current_depth()
            yield StreamChunk(text="child done", done=False)
            yield StreamChunk(text="", done=True)

    saved = _set_registry({"research": _NestingChild})
    adapter_token, depth_token = _set_adapter_and_depth()
    try:
        result = await delegate_parallel(
            json.dumps({"targets": [{"agent": "research", "task": "x"}]})
        )
    finally:
        _reset_adapter_and_depth(adapter_token, depth_token)
        _restore_registry(saved)

    assert result.success is True
    assert observed.get("depth") == 1, (
        "parallel child must see depth = parent(0) + 1 in its own context; "
        f"got {observed.get('depth')!r}"
    )


@pytest.mark.asyncio
async def test_delegate_parallel_partial_failure():
    """One child erroring must not cancel the others — the caller gets both
    results and the call counts as a (partial) success."""
    from tools.delegate_parallel import delegate_parallel

    class _Boom:
        def __init__(self, adapter=None):
            self.adapter = adapter

        async def run(self, **kwargs):
            raise RuntimeError("child exploded")
            yield  # pragma: no cover

    class _Fine:
        def __init__(self, adapter=None):
            self.adapter = adapter

        async def run(self, **kwargs):
            yield StreamChunk(text="good output here", done=False)
            yield StreamChunk(text="", done=True)

    saved = _set_registry({"research": _Boom, "analyst": _Fine})
    adapter_token, depth_token = _set_adapter_and_depth()
    try:
        result = await delegate_parallel(
            json.dumps(
                {
                    "targets": [
                        {"agent": "research", "task": "task one"},
                        {"agent": "analyst", "task": "task two"},
                    ]
                }
            )
        )
    finally:
        _reset_adapter_and_depth(adapter_token, depth_token)
        _restore_registry(saved)

    assert result.success is True, "partial success counts as success"
    assert result.metadata["completed"] == 1
    by_agent = {r["agent_name"]: r for r in result.metadata["results"]}
    assert by_agent["analyst"]["status"] == "completed"
    assert by_agent["research"]["status"] == "failed"
    assert by_agent["research"]["error_type"] == "child_exception"
    assert "good output here" in result.content


@pytest.mark.asyncio
async def test_delegate_parallel_rejects_more_than_5_targets():
    from tools.delegate_parallel import MAX_PARALLEL_TARGETS, delegate_parallel

    targets = [
        {"agent": "research", "task": f"task {i}"} for i in range(MAX_PARALLEL_TARGETS + 1)
    ]
    result = await delegate_parallel(json.dumps({"targets": targets}))
    assert result.success is False
    assert result.error_type == "too_many_targets"


@pytest.mark.asyncio
async def test_delegate_parallel_depth_cap():
    """Depth is tracked via the shared contextvar — at MAX_DELEGATION_DEPTH
    the fan-out refuses (same hard limit as the handoff delegate)."""
    from tools import delegate_parallel as dp_mod
    from tools.delegate_parallel import MAX_DELEGATION_DEPTH, delegate_parallel

    token = dp_mod._current_depth.set(MAX_DELEGATION_DEPTH)
    try:
        result = await delegate_parallel(
            json.dumps({"targets": [{"agent": "research", "task": "x"}]})
        )
    finally:
        dp_mod._current_depth.reset(token)

    assert result.success is False
    assert result.error_type == "recursion_limit"


@pytest.mark.asyncio
async def test_delegate_parallel_wall_clock_cap():
    """The wall-clock budget applies to the whole gather — a slow child is
    cancelled and reported timed_out."""
    from unittest.mock import patch

    from tools.delegate_parallel import delegate_parallel

    class _Slow:
        def __init__(self, adapter=None):
            self.adapter = adapter

        async def run(self, **kwargs):
            await asyncio.sleep(1.0)
            yield StreamChunk(text="late", done=False)
            yield StreamChunk(text="", done=True)

    saved = _set_registry({"research": _Slow})
    adapter_token, depth_token = _set_adapter_and_depth()
    try:
        with patch("tools.delegate_parallel.DELEGATION_WALL_CLOCK_SECS", 0.05):
            result = await delegate_parallel(
                json.dumps({"targets": [{"agent": "research", "task": "x"}]})
            )
    finally:
        _reset_adapter_and_depth(adapter_token, depth_token)
        _restore_registry(saved)

    assert result.success is False
    assert result.error_type == "wall_clock_cap"
    assert result.metadata["results"][0]["status"] == "timed_out"


@pytest.mark.asyncio
async def test_delegate_parallel_rejects_non_json():
    from tools.delegate_parallel import delegate_parallel

    result = await delegate_parallel("not json at all")
    assert result.success is False
    assert result.error_type == "invalid_input"


@pytest.mark.asyncio
async def test_delegate_parallel_rejects_empty_targets():
    from tools.delegate_parallel import delegate_parallel

    result = await delegate_parallel(json.dumps({"targets": []}))
    assert result.success is False
    assert result.error_type == "invalid_input"
