"""Cross-platform helpers for the live-test harness scripts.

The harnesses were originally written on a Linux dev box and used
POSIX-only constructs: a hardcoded `.venv/bin/python` path, `os.setsid`
process-group creation, `os.killpg`/`os.getpgid` teardown, and the
`pkill` CLI. This module centralizes platform-correct versions so the
same scripts run on Windows (`.venv\\Scripts\\python.exe`,
`CREATE_NEW_PROCESS_GROUP`, `taskkill /F /T /PID`, netstat+taskkill for
port cleanup) and macOS/Linux.

Usage:
    from harness_common import (
        venv_python, server_popen_kwargs, kill_process_tree, kill_port,
    )
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


def provider_key(provider: str) -> str:
    """Read a provider API key without ever printing or logging it.

    Order: env var <PROVIDER>_API_KEY (e.g. ZAI_API_KEY), then the app's
    settings file (~/LocalMind/settings.json -> api_keys[provider]).
    Returns "" when no key is configured - callers must fail fast on that
    (a missing credential is a missing input, never a hardcoded literal).
    """
    val = os.environ.get(f"{provider.upper()}_API_KEY", "")
    if val:
        return val
    settings = Path.home() / "LocalMind" / "settings.json"
    try:
        keys = json.loads(settings.read_text(encoding="utf-8")).get("api_keys", {})
        return keys.get(provider, "") or ""
    except Exception:
        return ""


def venv_python(backend: Path) -> str:
    """Return the backend's venv interpreter for the current platform.

    Windows venvs put the interpreter at `.venv\\Scripts\\python.exe`;
    POSIX at `.venv/bin/python`. If the venv is missing, fall back to the
    interpreter running the harness (dev convenience, used by older scripts).
    """
    if IS_WINDOWS:
        exe = backend / ".venv" / "Scripts" / "python.exe"
        return str(exe) if exe.exists() else sys.executable
    exe = backend / ".venv" / "bin" / "python"
    return str(exe) if exe.exists() else sys.executable


def server_popen_kwargs() -> dict:
    """Popen kwargs that put the server in its own process group so a later
    kill_process_tree() can take the whole tree down.

    Windows has no setsid; CREATE_NEW_PROCESS_GROUP is the equivalent, and
    taskkill /T walks the child tree.
    """
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def kill_process_tree(proc: subprocess.Popen | None, use_sigkill: bool = False) -> None:
    """Kill a server process and its whole tree, cross-platform.

    - Windows: `taskkill /F /T /PID <pid>` (force + tree).
    - POSIX: SIGTERM to the process group, then SIGKILL (unless the caller
      explicitly wants to skip the graceful round via use_sigkill=True).
    """
    if proc is None:
        return
    try:
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
            )
        else:
            pgid = os.getpgid(proc.pid)
            if not use_sigkill:
                os.killpg(pgid, signal.SIGTERM)
                time.sleep(1)
                os.killpg(pgid, signal.SIGKILL)
            else:
                os.killpg(pgid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def kill_port(port: int) -> None:
    """Best-effort kill of anything still listening on `port`.

    - Windows: netstat -ano -p TCP, parse LISTENING PIDs, taskkill each.
    - POSIX: `pkill -f LOCALMIND_PORT=<port>` (the server's env carries it).
    """
    if IS_WINDOWS:
        try:
            out = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True,
                text=True,
            ).stdout
        except Exception:
            return
        pids = {
            ln.split()[-1]
            for ln in out.splitlines()
            if f":{port}" in ln and "LISTENING" in ln
        }
        for pid in pids:
            if pid.isdigit() and pid != "0":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", pid],
                    capture_output=True,
                    check=False,
                )
    else:
        subprocess.run(
            ["pkill", "-f", f"LOCALMIND_PORT={port}"],
            capture_output=True,
            check=False,
        )
