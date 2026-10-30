#!/usr/bin/env python3
"""Live verification: permission modes + durability barriers (§U item 5, H + J).

Proven against the REAL server on isolated port 8765 with a local fake
OpenAI-compatible provider that emits tool calls, so the permission gate runs
on the real dispatch path — not a unit stub. Four probes:

  A (read-only denies a write): session pinned ``read_only``. The model emits a
    file_write. The gate must deny it BEFORE the body runs — the file must not
    exist, the SSE tool_call must be a permission failure, and the session's
    permission audit must carry a 'deny' row for file_write.

  B (workspace_write allows + journals): a fresh session pinned
    ``workspace_write``. The same file_write must succeed — the file exists, and
    the audit carries an 'allow' row whose write-ahead journal outcome resolved
    to 'done' (pending→done across the tool body).

  C (pin survives restart): the mode pinned in probe A is still ``read_only``
    after the server is stopped and booted again — a durable, session-scoped
    pin, not process state.

  D (interrupted call → unknown): while the server is down, a journal row left
    'pending' (a side-effecting call made durable before its body, then
    interrupted) is reconciled to 'unknown' on the next store open — never
    silently re-executed.

Usage:
  cd backend && ../scripts/live_test_permission_durability.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_common import kill_port, kill_process_tree, server_popen_kwargs, venv_python

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
VENV_PY = venv_python(BACKEND)
SCRATCH = REPO / "scratch"
HOME = SCRATCH / "permhome"
PORT = 8765
FAKE_PORT = 18795

# Absolute targets under HOME (which is under the user's home → an allowed
# folder). The read_only gate must stop A from ever being written.
TARGET_A = HOME / "probe_read_only.txt"
TARGET_B = HOME / "probe_workspace.txt"

INIT_MARKER = "initialization stage of LocalMind's parent agent"


class FakeProvider(BaseHTTPRequestHandler):
    """Emits one file_write tool call, then plain-text answers thereafter."""

    request_count: ClassVar[int] = 0
    target: ClassVar[str] = str(TARGET_A)
    log_message = lambda self, *a, **k: None  # noqa: E731

    def _sse_chunks(self, chunks: list[dict]):
        for c in chunks:
            body = ("data: " + json.dumps(c) + "\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        body = b"data: [DONE]\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, reply: str) -> list[dict]:
        return [
            {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "perm-flash",
             "choices": [{"index": 0, "delta": {"role": "assistant", "content": reply},
                          "finish_reason": None}]},
            {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "perm-flash",
             "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ]

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._json({"object": "list", "data": [{"id": "perm-flash"}]})
        else:
            self._json({"ok": True})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        if "/chat/completions" not in self.path:
            self._json({"error": {"message": "not found"}}, 404)
            return
        FakeProvider.request_count += 1
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {}
        text = json.dumps(body)

        if INIT_MARKER in text:
            self._sse_chunks(self._text(json.dumps({
                "mode": "execute",
                "acknowledgement": "Working from the context I already hold.",
                "response": "", "objective": "Create the file", "title": "Create File",
                "plan": ["Write the file"], "clarifying_question": "", "confidence": 0.9,
            })))
            return

        # The first non-init request gets the file_write call; everything after
        # (tool result carried back, any verification round) gets a plain answer
        # so the turn terminates quickly whatever the gate decided.
        has_tool_msg = any(
            isinstance(m, dict) and m.get("role") == "tool" for m in body.get("messages", [])
        )
        if not has_tool_msg:
            args = json.dumps({"path": FakeProvider.target, "content": "written by the probe\n"})
            self._sse_chunks([
                {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "perm-flash",
                 "choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
                     {"index": 0, "id": "call_w", "type": "function",
                      "function": {"name": "file_write", "arguments": args}}]},
                     "finish_reason": None}]},
                {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "perm-flash",
                 "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            ])
            return
        self._sse_chunks(self._text("Done — I have handled the file request."))


def boot_fake() -> ThreadingHTTPServer:
    FakeProvider.request_count = 0
    srv = ThreadingHTTPServer(("127.0.0.1", FAKE_PORT), FakeProvider)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def write_settings() -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    (HOME / "settings.json").write_text(json.dumps({
        "adapter": "fakeprov",
        "api_keys": {"fakeprov": "sk-local-fake-not-a-real-key"},
        "connections": [{
            "id": "fakeprov", "name": "Perm Provider (harness)", "kind": "openai-compat",
            "base_url": f"http://127.0.0.1:{FAKE_PORT}/v1", "model": "perm-flash", "enabled": True,
        }],
    }, indent=2))


def boot_server(log_file: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env.update({
        "LOCALMIND_PORT": str(PORT), "LOCALMIND_HOME": str(HOME),
        "LOCALMIND_ADAPTER": "fakeprov", "PYTHONPATH": str(BACKEND / "src"),
    })
    proc = subprocess.Popen(
        [VENV_PY, "server.py"], cwd=str(BACKEND), env=env,
        stdout=open(log_file, "wb"), stderr=subprocess.STDOUT, **server_popen_kwargs(),
    )
    for _ in range(45):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2).read()
            return proc
        except Exception:
            time.sleep(1)
    proc.kill()
    raise RuntimeError("server failed to start within 45s")


def api_get(path: str) -> dict | list:
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=15) as resp:
        return json.loads(resp.read().decode())


def api_post_json(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def set_mode(session_id: str, mode: str) -> dict:
    return api_post_json(f"/api/sessions/{session_id}/permission-mode", {"mode": mode})


def fire_chat(message: str, session_id: str, timeout: int = 180) -> str:
    body = urllib.parse.urlencode(
        {"message": message, "session_id": session_id, "is_first": "true"}
    ).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/chat", data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "X-LocalMind-Intent": "tool"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def tool_calls(raw: str) -> list[dict]:
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):]
        if payload == "[DONE]":
            continue
        try:
            e = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if e.get("type") == "tool_call" and (e.get("tool_call") or {}).get("name") == "file_write":
            out.append(e["tool_call"])
    return out


def main() -> int:
    problems: list[str] = []
    kill_port(PORT)
    kill_port(FAKE_PORT)
    for t in (TARGET_A, TARGET_B):
        try:
            t.unlink()
        except FileNotFoundError:
            pass
    fake = boot_fake()
    write_settings()
    log = SCRATCH / "permhome-server.log"
    proc = None
    try:
        proc = boot_server(log)

        # ── Probe A: read_only denies the write ──────────────────────────
        set_mode("perm-ro", "read_only")
        FakeProvider.target = str(TARGET_A)
        raw_a = fire_chat("Please create the file.", session_id="perm-ro")
        tcs_a = tool_calls(raw_a)
        if TARGET_A.exists():
            problems.append("probe A: read_only let the write through — the file exists")
        denied = [t for t in tcs_a if t.get("status") in ("failed", "error")]
        if not denied:
            problems.append(
                f"probe A: no failed file_write tool_call on the stream "
                f"(saw {[(t.get('status')) for t in tcs_a]})"
            )
        audit_a = api_get("/api/sessions/perm-ro/permission-audit")
        deny_rows = [r for r in audit_a if r.get("tool") == "file_write" and r.get("decision") == "deny"]
        if not deny_rows:
            problems.append(f"probe A: no deny row in the permission audit (saw {audit_a})")
        print(f"--- probe A (read_only): file exists={TARGET_A.exists()}; "
              f"denied tool_calls={len(denied)}; audit deny rows={len(deny_rows)}")

        # ── Probe B: workspace_write allows + journals pending→done ───────
        set_mode("perm-ww", "workspace_write")
        FakeProvider.target = str(TARGET_B)
        raw_b = fire_chat("Please create the file.", session_id="perm-ww")
        _ = raw_b
        if not TARGET_B.exists():
            problems.append("probe B: workspace_write did not let the write through — file absent")
        audit_b = api_get("/api/sessions/perm-ww/permission-audit")
        allow_rows = [r for r in audit_b if r.get("tool") == "file_write" and r.get("decision") == "allow"]
        if not allow_rows:
            problems.append(f"probe B: no allow row in the permission audit (saw {audit_b})")
        elif allow_rows[0].get("outcome") != "done":
            problems.append(
                f"probe B: journal outcome not resolved to 'done': {allow_rows[0].get('outcome')!r}"
            )
        print(f"--- probe B (workspace_write): file exists={TARGET_B.exists()}; "
              f"allow rows={len(allow_rows)}; "
              f"journal outcome={allow_rows[0].get('outcome') if allow_rows else None!r}")

        # Pin something to verify survival across a restart.
        set_mode("perm-pin", "read_only")

        # ── Stop the server, plant a 'pending' journal row (a crashed call) ─
        kill_process_tree(proc, use_sigkill=True)
        proc = None
        kill_port(PORT)
        # Plant a 'pending' journal row directly (raw sqlite3 — the harness runs
        # under system python and must not import the backend): a side-effecting
        # call made durable before its body, then interrupted by the "crash".
        import sqlite3

        con = sqlite3.connect(str(HOME / "localmind.db"))
        con.execute(
            "INSERT INTO permission_audit(session_id, tool, mode, decision, reason, "
            "fail_closed, outcome, created_at) VALUES(?,?,?,?,?,?,?,?)",
            ("perm-crash", "shell", "workspace_write", "allow",
             "interrupted mid-call", 0, "pending", time.time()),
        )
        con.commit()
        planted = con.execute(
            "SELECT outcome FROM permission_audit WHERE session_id='perm-crash'"
        ).fetchone()
        con.close()
        if not planted or planted[0] != "pending":
            problems.append(f"setup: planted row is not pending: {planted!r}")

        # ── Boot again: reconcile on open + the pin survived ──────────────
        proc = boot_server(log)
        mode_after = api_get("/api/sessions/perm-pin/permission-mode")
        if mode_after.get("mode") != "read_only":
            problems.append(f"probe C: pin did not survive restart: {mode_after}")
        audit_crash = api_get("/api/sessions/perm-crash/permission-audit")
        crash_outcome = audit_crash[0].get("outcome") if audit_crash else None
        if crash_outcome != "unknown":
            problems.append(
                f"probe D: interrupted 'pending' call not reconciled to 'unknown' "
                f"on restart (got {crash_outcome!r})"
            )
        print(f"--- probe C (pin survives restart): mode={mode_after.get('mode')!r}")
        print(f"--- probe D (interrupted → unknown): outcome={crash_outcome!r}")

        print()
        if problems:
            print("FAIL")
            for p in problems:
                print(f"  - {p}")
            return 1
        print(
            "PASS — read-only denied a write before its body ran (file absent, deny audited); "
            "workspace_write allowed the same write and its write-ahead journal resolved "
            "pending→done; the pinned mode survived a real server restart; and a call left "
            "'pending' by a crash was reconciled to 'unknown' on the next store open, never "
            "silently re-executed"
        )
        return 0
    finally:
        if proc is not None:
            kill_process_tree(proc, use_sigkill=True)
        fake.shutdown()
        fake.server_close()
        kill_port(PORT)


if __name__ == "__main__":
    sys.exit(main())
