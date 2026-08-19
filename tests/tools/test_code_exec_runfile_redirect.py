"""
code_exec RECOVERS a run-a-file command by running it via the shell tool
(B-2026-08-18-8).

The model often reaches for code_exec to run a script it just wrote
("python C:\\...\\fib_check.py 55"). code_exec runs INLINE Python source, not a
file, so it used to return a dead-end "provide a ```python``` block" error and
the turn stalled (empty_response). A better error message still relies on the
weak model to read it and self-correct — which it doesn't. So the harness now
RECOVERS structurally: it runs the command via shell and returns the output.
Inline code still runs; prose is still rejected.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.code_exec import code_exec


@pytest.fixture(autouse=True)
def _enable_shell(monkeypatch):
    # shell is disabled by default; the run-a-file recovery goes through it.
    monkeypatch.setattr("core.config.settings.localmind_shell_enabled", True, raising=False)


@pytest.mark.asyncio
async def test_run_file_command_is_executed_via_shell(tmp_path: Path):
    script = tmp_path / "hello.py"
    script.write_text("print('FIBTEST_OK', 55)\n")

    res = await code_exec(f"python3 {script}")

    assert res.success is True, res.content
    assert "FIBTEST_OK 55" in res.content  # the file actually ran
    assert "shell" in res.content.lower()  # transparent about how it ran
    assert res.source == "code_exec"


@pytest.mark.asyncio
async def test_windows_style_python_command_is_routed(tmp_path: Path):
    # The exact transcript shape (backslash path); it routes to shell rather than
    # being mis-read as inline code. The file doesn't exist here, so shell reports
    # a failure — the point is it ROUTED (no invalid_input dead-end).
    res = await code_exec(r"python C:\Users\tison\dev\fib_check.py 55")
    assert res.error_type != "invalid_input"
    assert "shell" in res.content.lower()


@pytest.mark.asyncio
async def test_shell_disabled_propagates_permission(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("core.config.settings.localmind_shell_enabled", False, raising=False)
    res = await code_exec(f"python {tmp_path / 'x.py'}")
    assert res.success is False
    assert res.error_type == "permission"


@pytest.mark.asyncio
async def test_inline_code_still_runs():
    res = await code_exec("print(6 * 7)")
    assert res.success is True
    assert "42" in res.content


@pytest.mark.asyncio
async def test_prose_still_rejected_with_a_helpful_message():
    res = await code_exec("please compute the fibonacci numbers for me")
    assert res.success is False
    assert res.error_type == "invalid_input"
    assert "shell" in res.content.lower()
