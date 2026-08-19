"""
Shell propagates a command FAILURE as a real tool error (B-2026-08-18-10).

Shell used to return success=True even when a command timed out or exited
nonzero (the failure was buried as "Command failed: ..." in the output), so the
loop's recovery layer never engaged — the agent could spin on a timing-out
command (e.g. a recursive disk scan) and then give up (empty_response). Now a
failure sets success=False + a classified error_type, which drives the
[RECOVERY] directive, the same-tool-failure streak, and the completion floor.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.models import RiskLevel
from tools.shell import shell_exec


@pytest.fixture(autouse=True)
def _enable_shell(monkeypatch):
    monkeypatch.setattr("core.config.settings.localmind_shell_enabled", True, raising=False)


@pytest.mark.asyncio
async def test_nonzero_exit_surfaces_as_command_failed():
    res = await shell_exec("cat /nonexistent_xyz_123")
    assert res.success is False
    assert res.error_type == "command_failed"
    assert res.content.startswith("Command failed:")


@pytest.mark.asyncio
async def test_timeout_surfaces_as_timeout_error():
    # Don't wait 20s for a real timeout — simulate the timeout output _run emits.
    def _timed_out(command, cwd=None):
        return ("Command failed:\nCommand timed out after 20s", RiskLevel.MEDIUM)

    with patch("tools.shell._run_command", side_effect=_timed_out):
        res = await shell_exec("Get-ChildItem -Path C:\\ -Recurse")

    assert res.success is False
    assert res.error_type == "timeout"  # → the transient recovery class (retry smaller / different)


@pytest.mark.asyncio
async def test_successful_command_stays_success():
    res = await shell_exec("echo hello-shell")
    assert res.success is True
    assert res.error_type == ""
    assert "hello-shell" in res.content
