"""
Port discovery and occupancy probes — shared by the server entrypoint and the
dev tooling contracts.

The rules that live here (and nowhere else):

- ``is_port_in_use`` must match how uvicorn binds. On POSIX that is a bind-probe
  with SO_REUSEADDR, so lingering TIME_WAIT sockets from the previous instance
  do not produce a FALSE "in use", while a genuinely LISTENING process still
  fails the bind. On Windows SO_REUSEADDR flips meaning — a probe socket WITH
  the flag can bind over another process's ACTIVE listener — so a connect-probe
  is used instead: a listening owner completes (or rejects) the connection,
  TIME_WAIT leftovers refuse it.
- ``occupant_is_localmind`` asks the health endpoint whether the port is held
  by a healthy LocalMind instance, so startup can name the occupant instead of
  telling the user to run netstat and guess.
- ``find_free_port`` scans upward from a preferred port; the dev orchestrator
  (scripts/dev-full.js, JavaScript mirror of this logic) uses it to move out of
  the way of a foreign application instead of crashing the whole stack.
"""

from __future__ import annotations

import json
import socket
import sys
import urllib.request

LOCALMIND_HEALTH_PATH = "/api/health"
HEALTHY_STATUSES = ("ok", "degraded")


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a TCP port is already bound by another process.

    POSIX: bind-probe with SO_REUSEADDR — matches uvicorn's own binding, so
    lingering TIME_WAIT sockets from the previous instance don't produce a
    FALSE "port in use" (a live finding), while a genuinely LISTENING process
    still fails the bind.

    Windows flips SO_REUSEADDR's meaning: a probe socket WITH the flag can
    bind over another process's ACTIVE listener, so a bind-probe reports
    genuinely-busy ports as free. Probe by connecting instead: a listening
    owner completes (or rejects) the connection → in use; TIME_WAIT
    leftovers refuse it → free, preserving that restart behavior.
    """
    if sys.platform == "win32":
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex((host, port)) == 0
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return False  # Port is free
        except OSError:
            return True  # Port is already in use


def occupant_is_localmind(host: str, port: int, timeout: float = 1.5) -> bool:
    """True when the port is held by a healthy LocalMind instance.

    The health endpoint answers ``{"status": "ok"}`` (or ``degraded`` — the
    engine is still warming up but the server is serving). Anything else —
    a different app, a non-JSON response, a connection error — is not LocalMind.
    """
    url = f"http://{host}:{port}{LOCALMIND_HEALTH_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
            return data.get("status") in HEALTHY_STATUSES
    except Exception:
        return False


def find_free_port(
    preferred: int, host: str = "127.0.0.1", attempts: int = 50
) -> int | None:
    """First free port at or above ``preferred`` (scanning upward), else None."""
    for candidate in range(preferred, preferred + attempts):
        if not is_port_in_use(candidate, host):
            return candidate
    return None
