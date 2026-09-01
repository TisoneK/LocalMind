"""Browser command timeout must return promptly, not hang to the outer cap.

Regression (B-2026-09-01 browser slowness): _run_browser_cmd's timeout handler
did `proc.kill(); await proc.communicate()`. kill() reaps only the CLI wrapper;
a grandchild (Chromium) that inherited the stdout/stderr pipes keeps them open,
so communicate() never sees EOF and blocks until the OUTER 180s dispatch
timeout — the exact 3m browse hang on a trivial page.

Fix: start_new_session=True + process-group kill + a bounded drain, so the
internal timeout returns at ~`timeout`.
"""

from __future__ import annotations

import sys
import time

import pytest

import tools.browser_agent as ba


@pytest.mark.asyncio
async def test_run_browser_cmd_timeout_returns_promptly(monkeypatch):
    # Point the "browser binary" at a Python that spawns a grandchild which
    # inherits the pipes and sleeps well past our timeout — the pre-fix hang
    # scenario. A bare communicate() after kill() would block on that pipe.
    monkeypatch.setattr(ba, "_AGENT_BROWSER_BIN", sys.executable)
    monkeypatch.setattr(ba, "BROWSER_AVAILABLE", True)

    child_script = (
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "time.sleep(30)"
    )

    start = time.monotonic()
    rc, out, err = await ba._run_browser_cmd(["-c", child_script], timeout=1)
    elapsed = time.monotonic() - start

    assert rc == 1
    assert "timed out" in err.lower()
    # Must return near the 1s timeout + a small drain budget — NOT hang for 30s
    # (the pre-fix bug) or the 180s dispatch cap.
    assert elapsed < 8, f"timeout cleanup hung: {elapsed:.1f}s"


def test_terminate_proc_group_is_safe_on_dead_proc():
    class _Dead:
        pid = -1

        def kill(self):
            raise ProcessLookupError

    # Must swallow lookup errors, never raise.
    ba._terminate_proc_group(_Dead())
