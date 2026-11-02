"""Port occupancy probes — the shared contract behind startup and dev tooling.

`core.ports` is the single home for the occupancy rules the server entrypoint
guards with (exit 42) and the dev orchestrator mirrors in JavaScript:

- `is_port_in_use` must match how uvicorn binds (bind-probe with SO_REUSEADDR
  on POSIX, connect-probe on Windows) — a false "in use" on restart was a live
  finding once already.
- `occupant_is_localmind` names WHO holds a port: a healthy LocalMind instance
  is a different situation from a foreign application, and the startup error
  (and the dev orchestrator's reuse/move decision) depends on telling them
  apart.
- `find_free_port` is the upward scan the "port held by another app" path
  moves to.
"""

from __future__ import annotations

import http.server
import json
import socket
import threading

from core.ports import find_free_port, is_port_in_use, occupant_is_localmind


def _free_ephemeral_port() -> int:
    """Ask the OS for a free port, then release it (the caller rebinds)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _listening_socket(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen(1)
    return sock


class _HealthHandler(http.server.BaseHTTPRequestHandler):
    status_payload = {"status": "ok"}

    def do_GET(self):  # noqa: N802 — http.server API
        if self.path == "/api/health":
            body = json.dumps(self.status_payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, *args):  # silence the per-request stderr noise
        pass


class _ForeignHandler(_HealthHandler):
    status_payload = {"service": "something-else"}  # a 200 that is not LocalMind


def _serve(handler, port: int) -> http.server.HTTPServer:
    server = http.server.HTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# ── is_port_in_use ──────────────────────────────────────────────────────────


def test_free_port_reports_free():
    port = _free_ephemeral_port()
    assert is_port_in_use(port, "127.0.0.1") is False


def test_listening_port_reports_busy():
    port = _free_ephemeral_port()
    sock = _listening_socket(port)
    try:
        assert is_port_in_use(port, "127.0.0.1") is True
    finally:
        sock.close()


# ── occupant_is_localmind ───────────────────────────────────────────────────


def test_occupant_is_localmind_when_health_answers_ok():
    port = _free_ephemeral_port()
    server = _serve(_HealthHandler, port)
    try:
        assert occupant_is_localmind("127.0.0.1", port) is True
    finally:
        server.shutdown()


def test_occupant_is_localmind_accepts_degraded():
    port = _free_ephemeral_port()

    class _Degraded(_HealthHandler):
        status_payload = {"status": "degraded"}

    server = _serve(_Degraded, port)
    try:
        assert occupant_is_localmind("127.0.0.1", port) is True
    finally:
        server.shutdown()


def test_occupant_is_not_localmind_when_200_is_someone_else():
    port = _free_ephemeral_port()
    server = _serve(_ForeignHandler, port)
    try:
        assert occupant_is_localmind("127.0.0.1", port) is False
    finally:
        server.shutdown()


def test_occupant_is_not_localmind_when_nothing_answers():
    port = _free_ephemeral_port()
    assert occupant_is_localmind("127.0.0.1", port) is False


# ── find_free_port ──────────────────────────────────────────────────────────


def test_find_free_port_returns_preferred_when_free():
    port = _free_ephemeral_port()
    assert find_free_port(port, "127.0.0.1", attempts=3) == port


def test_find_free_port_skips_a_busy_port():
    preferred = _free_ephemeral_port()
    sock = _listening_socket(preferred)
    try:
        moved = find_free_port(preferred, "127.0.0.1", attempts=10)
        assert moved is not None and moved > preferred
        assert is_port_in_use(moved, "127.0.0.1") is False
    finally:
        sock.close()


def test_find_free_port_returns_none_when_range_exhausted():
    preferred = _free_ephemeral_port()
    socks = [_listening_socket(p) for p in range(preferred, preferred + 3)]
    try:
        assert find_free_port(preferred, "127.0.0.1", attempts=3) is None
    finally:
        for sock in socks:
            sock.close()
