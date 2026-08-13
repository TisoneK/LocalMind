"""Regression test for Session 188 — is_port_in_use() SO_REUSEADDR fix.

The pre-check did a plain bind() without SO_REUSEADDR. After the previous
server instance stops (or recent probe connections leave TIME_WAIT sockets
on the port), the plain bind fails with EADDRINUSE — a FALSE positive that
blocked every restart ("Port 8000 is already in use" with nothing listening).
uvicorn itself binds with SO_REUSEADDR, so the pre-check disagreed with the
real server.

With SO_REUSEADDR:
  - a genuinely LISTENING other process still fails the bind → detected ✓
  - a port with only TIME_WAIT/stale sockets binds fine → no false positive ✓
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))
from server import is_port_in_use  # server.py lives outside backend/src


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_port_with_active_listener_is_reported_in_use():
    """A genuinely LISTENING socket must still be detected (SO_REUSEADDR must
    not mask a real conflict)."""
    port = _free_port()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(1)
    try:
        assert is_port_in_use(port) is True, (
            "a LISTENING socket on the port must be reported as in use"
        )
    finally:
        listener.close()


def test_free_port_is_reported_free():
    """A completely free port must be reported as free."""
    port = _free_port()
    assert is_port_in_use(port) is False


def _plain_bind_fails(port: int) -> bool:
    """True if a plain (no SO_REUSEADDR) bind fails — i.e. TIME_WAIT or an
    active listener is occupying the port. Used to prove the stale-socket
    condition is actually present before asserting the fix."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def test_stale_timewait_does_not_false_positive():
    """The exact Session 188 scenario: connections to the port leave TIME_WAIT
    sockets behind after the listener closes; the pre-check must NOT report
    the port as in use (SO_REUSEADDR lets the bind succeed).

    The test first PROVES the stale condition exists — a plain bind() (no
    SO_REUSEADDR) must fail, exactly like the old pre-check did — then asserts
    is_port_in_use() (with SO_REUSEADDR) returns False. If the environment
    never parks the socket in TIME_WAIT, the test is skipped rather than
    passing vacuously (which would let a regression slip through)."""
    import time

    port = _free_port()
    # Establish + close a connection so the port carries a TIME_WAIT socket.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(1)
    conn = socket.create_connection(("127.0.0.1", port), timeout=3)
    listener.accept()[0].close()
    conn.close()
    listener.close()

    # Poll up to 3s for the stale condition to materialize (TIME_WAIT is
    # entered asynchronously by the OS).
    stale = False
    for _ in range(30):
        if _plain_bind_fails(port):
            stale = True
            break
        time.sleep(0.1)
    if not stale:
        pytest.skip("could not reproduce TIME_WAIT stale-socket condition")

    assert is_port_in_use(port) is False, (
        "stale TIME_WAIT sockets must not trigger a false 'port in use'"
    )
