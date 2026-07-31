"""
Tests for the Process tool (backend/src/tools/process_tool.py).

Tests cover all 6 operations: start, stop, restart, status, logs, wait.
Uses a short-lived subprocess (`sleep 0.1`) so tests don't block.
Also tests: edge cases (missing args, unknown processes, invalid JSON),
tool registration, tool definition presence, and scoped tool filtering.
"""

from __future__ import annotations

import json
import time

import pytest


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the process registry before and after each test."""
    from tools.process_tool import _registry
    _registry.reset()
    yield
    _registry.reset()


@pytest.fixture(autouse=True)
def set_test_cwd(tmp_path, monkeypatch):
    """Set the session CWD context var for process operations."""
    from tools.process_tool import _session_cwd_var
    _session_cwd_var.set(str(tmp_path))
    yield
    _session_cwd_var.set(None)


# ── Module-level imports ───────────────────────────────────────────────────────


def test_process_tool_registered():
    """The process tool should be registered in _REGISTRY."""
    from core.models import Intent
    from tools import _REGISTRY
    assert Intent.PROCESS in _REGISTRY
    assert "description" in _REGISTRY[Intent.PROCESS]


def test_intent_process_exists():
    """Intent.PROCESS should be defined."""
    from core.models import Intent
    assert Intent.PROCESS.value == "process"


def test_process_in_allowed_tools():
    """'process' should be in AGENT_ALLOWED_TOOLS."""
    from core.agent.constants import AGENT_ALLOWED_TOOLS
    assert "process" in AGENT_ALLOWED_TOOLS


def test_process_in_coding_tools():
    """'process' should be in CODING_TOOLS."""
    from agents.coding.tools import CODING_TOOLS
    assert "process" in CODING_TOOLS


def test_process_tool_definition_exists():
    """The process tool should have a definition in TOOL_DEFINITIONS."""
    from core.agent.loop import TOOL_DEFINITIONS
    proc_defs = [td for td in TOOL_DEFINITIONS if td["function"]["name"] == "process"]
    assert len(proc_defs) == 1
    proc_def = proc_defs[0]
    assert "operation" in proc_def["function"]["parameters"]["required"]


def test_process_extract_tool_input():
    """_extract_tool_input should serialize process args as JSON."""
    from core.agent.loop import _extract_tool_input
    result = _extract_tool_input("process", {"operation": "status"})
    parsed = json.loads(result)
    assert parsed["operation"] == "status"


# ── Start ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start():
    """Start a short process and verify it's tracked."""
    from tools.process_tool import process_dispatch, _registry
    args = json.dumps({"operation": "start", "name": "test-sleep", "command": "sleep 0.1"})
    result = await process_dispatch(args)
    assert result.success
    assert "Started process" in result.content
    assert _registry.get("test-sleep") is not None


@pytest.mark.asyncio
async def test_start_duplicate():
    """Starting an already-running process should fail."""
    from tools.process_tool import process_dispatch
    args = json.dumps({"operation": "start", "name": "dup-test", "command": "sleep 5"})
    result = await process_dispatch(args)
    assert result.success
    result2 = await process_dispatch(args)
    assert not result2.success
    assert "already running" in result2.content.lower()


@pytest.mark.asyncio
async def test_start_missing_name():
    """start without a name should fail."""
    from tools.process_tool import process_dispatch
    args = json.dumps({"operation": "start", "command": "sleep 1"})
    result = await process_dispatch(args)
    assert not result.success


@pytest.mark.asyncio
async def test_start_missing_command():
    """start without a command should fail."""
    from tools.process_tool import process_dispatch
    args = json.dumps({"operation": "start", "name": "no-cmd"})
    result = await process_dispatch(args)
    assert not result.success


# ── Stop ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stop():
    """Start and stop a process."""
    from tools.process_tool import process_dispatch, _registry
    # Start
    args = json.dumps({"operation": "start", "name": "stop-test", "command": "sleep 10"})
    result = await process_dispatch(args)
    assert result.success
    # Stop
    args2 = json.dumps({"operation": "stop", "name": "stop-test"})
    result2 = await process_dispatch(args2)
    assert result2.success
    assert "stopped" in result2.content.lower()


@pytest.mark.asyncio
async def test_stop_unknown():
    """Stopping an unknown process should fail."""
    from tools.process_tool import process_dispatch
    args = json.dumps({"operation": "stop", "name": "nonexistent"})
    result = await process_dispatch(args)
    assert not result.success
    assert "no process" in result.content.lower()


@pytest.mark.asyncio
async def test_stop_already_stopped():
    """Stopping an already-stopped process should report stopped."""
    from tools.process_tool import process_dispatch
    # Start and wait for it to finish
    args = json.dumps({"operation": "start", "name": "quick", "command": "sleep 0.1"})
    await process_dispatch(args)
    time.sleep(0.3)  # Wait for process to finish
    # Stop should report already stopped
    args2 = json.dumps({"operation": "stop", "name": "quick"})
    result = await process_dispatch(args2)
    assert result.success
    assert "already stopped" in result.content.lower() or "exited" in result.content.lower()


# ── Restart ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_restart():
    """Restart a running process."""
    from tools.process_tool import process_dispatch
    args = json.dumps({"operation": "start", "name": "restart-test", "command": "sleep 0.1"})
    await process_dispatch(args)
    args2 = json.dumps({"operation": "restart", "name": "restart-test", "command": "sleep 0.1"})
    result = await process_dispatch(args2)
    assert result.success
    assert "Started process" in result.content


@pytest.mark.asyncio
async def test_restart_unknown_no_command():
    """Restarting unknown process without command should fail."""
    from tools.process_tool import process_dispatch
    args = json.dumps({"operation": "restart", "name": "unknown"})
    result = await process_dispatch(args)
    assert not result.success


# ── Status ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_empty():
    """Status with no processes should show empty."""
    from tools.process_tool import process_dispatch
    args = json.dumps({"operation": "status"})
    result = await process_dispatch(args)
    assert result.success
    assert "no processes" in result.content.lower()


@pytest.mark.asyncio
async def test_status_single():
    """Status for a single running process."""
    from tools.process_tool import process_dispatch
    args = json.dumps({"operation": "start", "name": "status-test", "command": "sleep 5"})
    await process_dispatch(args)
    args2 = json.dumps({"operation": "status", "name": "status-test"})
    result = await process_dispatch(args2)
    assert result.success
    assert "status-test" in result.content


@pytest.mark.asyncio
async def test_status_all():
    """Status listing all processes."""
    from tools.process_tool import process_dispatch
    await process_dispatch(json.dumps({"operation": "start", "name": "proc1", "command": "sleep 5"}))
    await process_dispatch(json.dumps({"operation": "start", "name": "proc2", "command": "sleep 5"}))
    args = json.dumps({"operation": "status"})
    result = await process_dispatch(args)
    assert result.success
    assert "proc1" in result.content
    assert "proc2" in result.content


# ── Logs ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_logs():
    """Read logs from a process that produces output."""
    from tools.process_tool import process_dispatch
    args = json.dumps({"operation": "start", "name": "echo-test", "command": "echo hello world"})
    result = await process_dispatch(args)
    assert result.success
    # Wait for process to finish
    time.sleep(0.3)
    args2 = json.dumps({"operation": "logs", "name": "echo-test"})
    result2 = await process_dispatch(args2)
    assert result2.success
    assert "hello world" in result2.content or "Logs for" in result2.content


@pytest.mark.asyncio
async def test_logs_unknown():
    """Logs for unknown process should fail."""
    from tools.process_tool import process_dispatch
    args = json.dumps({"operation": "logs", "name": "nonexistent"})
    result = await process_dispatch(args)
    assert not result.success


# ── Wait ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wait():
    """Wait for a short process to finish."""
    from tools.process_tool import process_dispatch
    args = json.dumps({"operation": "start", "name": "wait-test", "command": "sleep 0.1"})
    await process_dispatch(args)
    args2 = json.dumps({"operation": "wait", "name": "wait-test", "timeout": 5})
    result = await process_dispatch(args2)
    assert result.success
    assert "finished" in result.content.lower()


@pytest.mark.asyncio
async def test_wait_already_stopped():
    """Wait on an already-finished process should report finished."""
    from tools.process_tool import process_dispatch
    args = json.dumps({"operation": "start", "name": "done-test", "command": "sleep 0.1"})
    await process_dispatch(args)
    time.sleep(0.3)
    args2 = json.dumps({"operation": "wait", "name": "done-test"})
    result = await process_dispatch(args2)
    assert result.success
    assert "already" in result.content.lower() or "finished" in result.content.lower()


@pytest.mark.asyncio
async def test_wait_timeout():
    """Wait with a short timeout on a long-running process should report still running."""
    from tools.process_tool import process_dispatch
    args = json.dumps({"operation": "start", "name": "long-test", "command": "sleep 60"})
    await process_dispatch(args)
    args2 = json.dumps({"operation": "wait", "name": "long-test", "timeout": 0.5})
    result = await process_dispatch(args2)
    assert result.success  # Wait timeout is not an error — process is still running
    assert "still running" in result.content.lower() or "timed out" in result.content.lower()


# ── Edge cases ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_json():
    """Invalid JSON input should fail gracefully."""
    from tools.process_tool import process_dispatch
    result = await process_dispatch("not json")
    assert not result.success


@pytest.mark.asyncio
async def test_unknown_operation():
    """Unknown operation should fail with a helpful message."""
    from tools.process_tool import process_dispatch
    args = json.dumps({"operation": "launch"})
    result = await process_dispatch(args)
    assert not result.success
    assert "unknown" in result.content.lower()


# ── Registration / Integration tests ───────────────────────────────────────────


def test_intent_process_in_agent_intents():
    """Intent.PROCESS should be in AGENT_INTENTS for the agent loop."""
    from core.agent.constants import AGENT_INTENTS
    from core.models import Intent
    assert Intent.PROCESS in AGENT_INTENTS


def test_coding_tools_is_subset_of_allowed_tools():
    """CODING_TOOLS must remain a subset of AGENT_ALLOWED_TOOLS."""
    from agents.coding.tools import CODING_TOOLS
    from core.agent.constants import AGENT_ALLOWED_TOOLS
    assert CODING_TOOLS.issubset(AGENT_ALLOWED_TOOLS), (
        f"CODING_TOOLS ({CODING_TOOLS}) must be subset of "
        f"AGENT_ALLOWED_TOOLS ({AGENT_ALLOWED_TOOLS})"
    )


def test_git_and_process_in_tool_definitions():
    """Both git and process should be in TOOL_DEFINITIONS."""
    from core.agent.loop import TOOL_DEFINITIONS
    names = {td["function"]["name"] for td in TOOL_DEFINITIONS}
    assert "git" in names, "git tool definition was lost!"
    assert "process" in names, "process tool definition missing"


def test_process_not_in_direct_agent():
    """DirectAgent should still have no tools."""
    from agents.direct.tools import DIRECT_TOOLS
    assert "process" not in DIRECT_TOOLS
