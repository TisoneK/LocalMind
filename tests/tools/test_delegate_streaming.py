"""ADR-18 P3 delegation-streaming tests (Session 176).

The delegate tools now stream the sub-agent's user-visible work into the
parent's ObsCollector (so the Actions panel shows it) and emit
delegation_started / delegation_completed lifecycle events. Covers:
  1. ChildObsProxy — forwards only tool_call/tool_status to the parent,
     tags them with the child agent name, keeps its own event list.
  2. delegate() emits delegation lifecycle events into the parent obs.
  3. delegate_parallel() emits lifecycle events + forwards child work.
  4. dispatch_with_retry(obs=...) exposes the collector to the delegate
     tools via the contextvar.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from core.obs import ChildObsProxy, ObsCollector

# ── 1. ChildObsProxy ───────────────────────────────────────────────────────


def test_child_obs_proxy_forwards_only_visible_events():
    parent = ObsCollector()
    proxy = ChildObsProxy(parent, "research")

    proxy.emit("tool_call", tool="web_search", label="Searching", status="done")
    proxy.emit("agent_loop_start", intent="chat")  # must NOT leak to parent
    proxy.emit("tool_status", tool="web_search", status="done")
    proxy.emit("turn_complete", total_latency_ms=123)  # must NOT leak

    parent_events = [e.type for e in parent.history()]
    assert "tool_call" in parent_events
    assert "tool_status" in parent_events
    assert "agent_loop_start" not in parent_events
    assert "turn_complete" not in parent_events

    # Forwarded tool_call carries the child agent tag.
    fwd = next(e for e in parent.history() if e.type == "tool_call")
    assert fwd.data.get("agent") == "research"

    # The child's own list still has everything (its internal behavior —
    # failure memory, SSE — is unchanged).
    child_events = [e.type for e in proxy.history()]
    assert "agent_loop_start" in child_events
    assert "turn_complete" in child_events


def test_child_obs_proxy_without_parent_is_safe():
    proxy = ChildObsProxy(None, "coding")
    proxy.emit("tool_call", tool="shell")
    assert len(proxy.history()) == 1  # no crash, no forward


# ── 2. delegate() lifecycle events ────────────────────────────────────────


@pytest.mark.asyncio
async def test_delegate_emits_lifecycle_events():
    from tools.delegate import delegate

    parent_obs = ObsCollector()

    class _FakeChild:
        def __init__(self, adapter=None):
            pass

        async def run(self, **kwargs):
            yield MagicMock(text="child result", done=False, usage={})
            yield MagicMock(text="", done=True, usage={})

    with patch("tools.delegate.get_current_obs", return_value=parent_obs), patch(
        "tools.delegate._current_adapter",
        type("_CV", (), {"get": lambda self, d=None: MagicMock(), "set": lambda self, v: None})(),
    ), patch("agents.registry.get_agent", return_value=_FakeChild), patch(
        "tools.delegate._current_depth",
        type("_CV", (), {"get": lambda self, d=0: 0, "set": lambda self, v: None})(),
    ):
        result = await delegate('{"target_agent": "research", "task": "find weather"}')

    assert result.success
    types = [e.type for e in parent_obs.history()]
    assert "delegation_started" in types
    assert "delegation_completed" in types
    started = next(e for e in parent_obs.history() if e.type == "delegation_started")
    assert started.data["target_agent"] == "research"
    completed = next(e for e in parent_obs.history() if e.type == "delegation_completed")
    assert completed.data["status"] == "completed"


@pytest.mark.asyncio
async def test_delegate_child_tool_work_streams_to_parent():
    """The child runs with a ChildObsProxy: its tool_call events land in
    the parent collector, tagged with the child agent name."""
    from tools.delegate import delegate

    parent_obs = ObsCollector()
    child_proxy_holder = {}

    class _FakeChild:
        def __init__(self, adapter=None):
            pass

        async def run(self, **kwargs):
            # The child's AgentLoop would emit tool_call into kwargs["obs"].
            child_obs = kwargs.get("obs")
            assert child_obs is not None, "child must receive an obs proxy"
            child_proxy_holder["proxy"] = child_obs
            child_obs.emit("tool_call", tool="web_search", label="Searching", status="running")
            child_obs.emit("tool_call", tool="web_search", label="Searching", status="done")
            yield MagicMock(text="done", done=True, usage={})

    with patch("tools.delegate.get_current_obs", return_value=parent_obs), patch(
        "tools.delegate._current_adapter",
        type("_CV", (), {"get": lambda self, d=None: MagicMock(), "set": lambda self, v: None})(),
    ), patch("agents.registry.get_agent", return_value=_FakeChild), patch(
        "tools.delegate._current_depth",
        type("_CV", (), {"get": lambda self, d=0: 0, "set": lambda self, v: None})(),
    ):
        await delegate('{"target_agent": "research", "task": "find weather"}')

    assert isinstance(child_proxy_holder["proxy"], ChildObsProxy)
    child_tool_events = [
        e for e in parent_obs.history() if e.type == "tool_call" and e.data.get("agent") == "research"
    ]
    assert len(child_tool_events) == 2


@pytest.mark.asyncio
async def test_delegate_failure_emits_completed_with_failed_status():
    from tools.delegate import delegate

    parent_obs = ObsCollector()

    class _FakeChild:
        def __init__(self, adapter=None):
            pass

        async def run(self, **kwargs):
            yield MagicMock(text="", done=True, usage={})  # empty response

    with patch("tools.delegate.get_current_obs", return_value=parent_obs), patch(
        "tools.delegate._current_adapter",
        type("_CV", (), {"get": lambda self, d=None: MagicMock(), "set": lambda self, v: None})(),
    ), patch("agents.registry.get_agent", return_value=_FakeChild), patch(
        "tools.delegate._current_depth",
        type("_CV", (), {"get": lambda self, d=0: 0, "set": lambda self, v: None})(),
    ):
        result = await delegate('{"target_agent": "research", "task": "x"}')

    assert not result.success
    completed = next(e for e in parent_obs.history() if e.type == "delegation_completed")
    assert completed.data["status"] == "failed"
    assert completed.data["error_type"] == "empty_response"


# ── 3. delegate_parallel() lifecycle events ───────────────────────────────


@pytest.mark.asyncio
async def test_delegate_parallel_emits_lifecycle_events():
    from tools.delegate_parallel import delegate_parallel

    parent_obs = ObsCollector()

    class _FakeChild:
        def __init__(self, adapter=None):
            pass

        async def run(self, **kwargs):
            child_obs = kwargs.get("obs")
            if child_obs is not None:
                child_obs.emit("tool_call", tool="web_search", status="done")
            yield MagicMock(text="ok", done=True, usage={})

    with patch(
        "tools.delegate_parallel.get_current_obs", return_value=parent_obs
    ), patch("agents.registry.get_agent", return_value=_FakeChild), patch(
        "tools.delegate_parallel._current_adapter",
        type("_CV", (), {"get": lambda self, d=None: MagicMock(), "set": lambda self, v: None})(),
    ), patch(
        "tools.delegate_parallel._current_depth",
        type("_CV", (), {"get": lambda self, d=0: 0, "set": lambda self, v: None})(),
    ):
        result = await delegate_parallel(
            '{"targets": [{"agent": "research", "task": "a"}, {"agent": "coding", "task": "b"}]}'
        )

    assert result.success
    types = [e.type for e in parent_obs.history()]
    assert "delegation_started" in types
    assert "delegation_completed" in types
    completed = next(e for e in parent_obs.history() if e.type == "delegation_completed")
    assert completed.data["status"] == "completed"
    assert completed.data["completed"] == 2
    # Children's tool work was forwarded with the child agent tags.
    fwd = [e for e in parent_obs.history() if e.type == "tool_call"]
    assert len(fwd) == 2
    assert {e.data.get("agent") for e in fwd} == {"research", "coding"}


# ── 4. dispatch_with_retry obs threading ──────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_with_retry_sets_current_obs():
    from core.agent.tool_dispatch import dispatch_with_retry
    from core.models import Intent, ToolResult

    parent_obs = ObsCollector()
    seen = {}

    async def fake_dispatch(intent, message):
        from tools.delegate import get_current_obs

        seen["obs"] = get_current_obs()
        return ToolResult(content="ok", source="shell", success=True)

    with patch("core.agent.tool_dispatch.dispatch", fake_dispatch):
        result, _failed, _ = await dispatch_with_retry(
            Intent.SHELL, "ls", max_retries=0, obs=parent_obs
        )
    assert result is not None and result.success
    assert seen["obs"] is parent_obs
