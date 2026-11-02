#!/usr/bin/env python3
"""LIVE verification — idle continuation of an active goal (C4, the
goal-pursuit program's decisive piece).

Boots the REAL LocalMind server (port 8765, scratch LOCALMIND_HOME) against
the deterministic fake provider and proves, on the wire:

  1. a human turn creates + arms a goal (the model's own update_goal call);
  2. the SSE connection is dropped MID-DEEP-DIVE — before this build, that
     ended the deep dive while the goal stayed active forever;
  3. the idle continuation driver picks the deep dive back up: further
     <goal_round> turns appear in history and the round allowance is
     consumed WITHOUT any new SSE request;
  4. the cap records the durable round-limit blocker (phase blocked);
  5. the human resume affordance (POST /sessions/{sid}/goal/resume with
     extend_rounds) re-arms the blocked goal and the driver continues to
     the new cap — the explicit-human-decision path;
  6. the pause affordance stops the automatic work (armed false).

Usage:
  cd backend && python ../scripts/live_test_goal_idle.py
"""
from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
sys.path.insert(0, str(REPO / "scripts"))
from harness_common import kill_process_tree, server_popen_kwargs, venv_python

PORT = 8765
FAKE_PORT = 18797
HOME = REPO / "scratch" / "goal-idle-home"
OUT = REPO / "scratch" / "goal-idle"
SESSION = "goal-idle-live"

INIT_MARKER = "initialization stage of LocalMind's parent agent"
OBJECTIVE = "Map the test machine thoroughly"


class FakeProvider(BaseHTTPRequestHandler):
    """State machine: init → execute JSON; per-turn tools-call #1 →
    update_goal create (once) then sysinfo; tools-call #2+ → text."""

    goal_created: ClassVar[bool] = False
    tools_calls_this_turn: ClassVar[int] = 0

    log_message = lambda self, *a, **k: None  # noqa: E731

    def _sse_chunks(self, chunks: list[dict]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        def sse(obj):
            self.wfile.write(("data: " + json.dumps(obj) + "\n\n").encode())
            self.wfile.flush()

        for c in chunks:
            sse(c)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _text_chunks(self, text: str) -> list[dict]:
        return [
            {"id": "g1", "object": "chat.completion.chunk", "created": 1,
             "model": "idle-flash",
             "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]},
            {"id": "g1", "object": "chat.completion.chunk", "created": 1,
             "model": "idle-flash",
             "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 600, "completion_tokens": 10,
                       "total_tokens": 610}},
        ]

    def _tool_chunks(self, name: str, arguments: str, call_id: str) -> list[dict]:
        return [
            {"id": "g2", "object": "chat.completion.chunk", "created": 1,
             "model": "idle-flash",
             "choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
                 {"index": 0, "id": call_id, "type": "function",
                  "function": {"name": name, "arguments": arguments}}]},
                 "finish_reason": None}]},
            {"id": "g2", "object": "chat.completion.chunk", "created": 1,
             "model": "idle-flash",
             "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        ]

    def do_GET(self):
        body = json.dumps({"object": "list", "data": [{"id": "idle-flash"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {}
        text = json.dumps(body)

        if INIT_MARKER in text:
            FakeProvider.tools_calls_this_turn = 0
            reply = json.dumps(
                {
                    "mode": "execute",
                    "acknowledgement": "Working from the context I already hold.",
                    "response": "",
                    "objective": OBJECTIVE,
                    "title": "Map The Machine",
                    "plan": ["Inspect the machine", "Report findings"],
                    "clarifying_question": "",
                    "confidence": 0.9,
                }
            )
            self._sse_chunks(self._text_chunks(reply))
            return

        has_tools = isinstance(body.get("tools"), list) and body["tools"]
        if has_tools:
            FakeProvider.tools_calls_this_turn += 1
            if FakeProvider.tools_calls_this_turn == 1:
                if not FakeProvider.goal_created:
                    FakeProvider.goal_created = True
                    self._sse_chunks(
                        self._tool_chunks(
                            "update_goal",
                            json.dumps({
                                "action": "create",
                                "objective": OBJECTIVE,
                                "max_goal_rounds": 3,
                            }),
                            "call_goal",
                        )
                    )
                else:
                    self._sse_chunks(
                        self._tool_chunks(
                            "sysinfo", '{"query": "platform"}', "call_sys"
                        )
                    )
                return

        self._sse_chunks(self._text_chunks("Inspecting the machine step by step."))


def boot_fake() -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", FAKE_PORT), FakeProvider)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def write_settings() -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    settings = {
        "adapter": "fakeprov",
        "api_keys": {"fakeprov": "sk-local-fake-not-a-real-key"},
        "connections": [
            {
                "id": "fakeprov",
                "name": "idle-fake",
                "kind": "openai-compat",
                "base_url": f"http://127.0.0.1:{FAKE_PORT}/v1",
                "model": "idle-flash",
                "enabled": True,
            }
        ],
    }
    (HOME / "settings.json").write_text(json.dumps(settings, indent=2))


def boot_server() -> subprocess.Popen:
    env = os.environ.copy()
    env.update(
        {
            "LOCALMIND_PORT": str(PORT),
            "LOCALMIND_HOME": str(HOME),
            "LOCALMIND_ADAPTER": "fakeprov",
            "PYTHONPATH": str(BACKEND / "src"),
        }
    )
    log = OUT / "server.log"
    proc = subprocess.Popen(
        [venv_python(BACKEND), "server.py"],
        cwd=str(BACKEND), env=env,
        stdout=open(log, "wb"), stderr=subprocess.STDOUT,
        **server_popen_kwargs(),
    )
    for _ in range(45):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2).read()
            return proc
        except Exception:
            time.sleep(1)
    proc.kill()
    raise RuntimeError("server failed to start within 45s")


def http_get_json(path: str, timeout: int = 15) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def http_post_json(path: str, payload: dict | None = None, timeout: int = 15) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=json.dumps(payload or {}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def post_chat_and_drop(message: str, read_until: str, max_bytes: int = 200_000) -> int:
    """POST the chat, read SSE until the marker appears, then DROP the
    connection mid-deep-dive — the C4 scenario."""
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=120)
    body = f"message={urllib.parse.quote(message)}&session_id={SESSION}"
    conn.request(
        "POST",
        "/api/chat",
        body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp = conn.getresponse()
    seen = 0
    marker_at = -1
    buf = b""
    while seen < max_bytes:
        chunk = resp.read1(4096) if hasattr(resp, "read1") else resp.read(4096)
        if not chunk:
            break
        buf += chunk
        seen += len(chunk)
        if read_until in buf.decode(errors="replace"):
            marker_at = seen
            break
    conn.close()  # the drop
    return marker_at


def goal_state() -> dict | None:
    try:
        data = http_get_json(f"/api/sessions/{SESSION}/goal")
        return data.get("goal")
    except Exception:
        return None


def history_goal_rounds() -> int:
    try:
        data = http_get_json(f"/api/sessions/{SESSION}/history")
        return sum(
            1
            for m in data.get("history", [])
            if m.get("role") == "user" and "<goal_round>" in str(m.get("content") or "")
        )
    except Exception:
        return 0


def check(condition: bool, label: str, failures: list[str]) -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"    [{mark}] {label}")
    if not condition:
        failures.append(label)


import urllib.parse  # noqa: E402  (used by post_chat_and_drop)


def main() -> int:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2).read()
        print(f"REFUSED: a live server already answers on {PORT} — kill it first.")
        return 2
    except Exception:
        pass

    import shutil

    if OUT.exists():
        shutil.rmtree(OUT)
    if HOME.exists():
        shutil.rmtree(HOME)
    OUT.mkdir(parents=True, exist_ok=True)

    fake = boot_fake()
    server: subprocess.Popen | None = None
    failures: list[str] = []
    try:
        write_settings()
        server = boot_server()
        print(f"server up on {PORT} (fake provider on {FAKE_PORT})")

        # ── 1. the human turn, dropped mid-deep-dive ─────────────────────
        print("  human turn (goal created + armed), connection dropped:")
        marker = post_chat_and_drop(
            "Map the machine for me", read_until="Inspecting the machine"
        )
        check(marker > 0, "round-1 text reached the wire before the drop", failures)
        time.sleep(2.0)  # let the disconnect abort + the finally settle

        goal = goal_state()
        check(goal is not None, "a durable goal exists", failures)
        check(bool(goal and goal.get("armed")), "the goal is armed after the drop", failures)

        # ── 2. the idle driver continues WITHOUT any new request ─────────
        print("  idle continuation (no SSE request anymore):")
        deadline = time.time() + 45
        rounds_seen = 0
        while time.time() < deadline:
            rounds_seen = history_goal_rounds()
            goal = goal_state()
            if rounds_seen >= 2 or (goal and goal.get("phase") == "blocked"):
                break
            time.sleep(1.0)
        check(rounds_seen >= 1,
              f"the deep dive continued on the idle driver "
              f"({rounds_seen} <goal_round> turn(s) in history)", failures)

        # ── 3. the cap records the durable blocker ───────────────────────
        deadline = time.time() + 45
        while time.time() < deadline:
            goal = goal_state()
            if goal and goal.get("phase") == "blocked":
                break
            time.sleep(1.0)
        goal = goal_state()
        check(bool(goal and goal.get("phase") == "blocked"),
              "the round cap recorded the durable round-limit blocker", failures)
        check(bool(goal and goal.get("roundsStarted", 0) >= 3),
              f"round allowance consumed up to the cap (roundsStarted="
              f"{goal.get('roundsStarted') if goal else None})", failures)
        check(bool(goal and not goal.get("armed")),
              "the blocked goal dropped its activation", failures)
        rounds_at_block = goal.get("roundsStarted", 0) if goal else 0

        # ── 4. the human resume affordance ────────────────────────────────
        print("  human resume (extend_rounds=2):")
        status, data = http_post_json(
            f"/api/sessions/{SESSION}/goal/resume?extend_rounds=2", {}
        )
        check(status == 200, f"resume endpoint accepted ({status} {data})", failures)
        deadline = time.time() + 45
        while time.time() < deadline:
            goal = goal_state()
            if goal and goal.get("roundsStarted", 0) > rounds_at_block:
                break
            time.sleep(1.0)
        goal = goal_state()
        check(bool(goal and goal.get("roundsStarted", 0) > rounds_at_block),
              f"the resumed goal continued on the idle driver "
              f"(roundsStarted={goal.get('roundsStarted') if goal else None})", failures)
        deadline = time.time() + 45
        while time.time() < deadline:
            goal = goal_state()
            if goal and goal.get("phase") == "blocked":
                break
            time.sleep(1.0)
        goal = goal_state()
        check(bool(goal and goal.get("phase") == "blocked"),
              "the extended cap closed with a durable blocker again", failures)
        check(bool(goal and goal.get("roundsStarted", 0) == 5),
              f"deep dive stopped exactly at the new cap (5, got "
              f"{goal.get('roundsStarted') if goal else None})", failures)

        # ── 5. background rounds are on the durable trace ─────────────────
        traces = http_get_json(f"/api/observability/{SESSION}/traces")
        check(len(traces.get("traces", [])) >= 4,
              f"background rounds persist their traces "
              f"({len(traces.get('traces', []))} turns on the record)", failures)

        # ── 6. the exhausted-cap refusal ──────────────────────────────
        # By now the deep dive ran to the extended cap (blocked, 5/5): a
        # resume without extend_rounds must refuse with the cap named.
        status, data = http_post_json(f"/api/sessions/{SESSION}/goal/resume", {})
        check(status == 409 and "cap" in str(data).lower(),
              f"the exhausted-cap resume refuses with the cap named "
              f"({status} {data})", failures)

        if failures:
            print(f"\nRESULT: FAIL — {len(failures)} check(s):")
            for f in failures:
                print(f"  - {f}")
            return 1
        print("\nRESULT: PASS — the deep dive survives the dropped connection;")
        print("        the human resume affordance re-arms it; the cap holds.")
        return 0
    finally:
        if server is not None:
            kill_process_tree(server.pid)
        fake.shutdown()


if __name__ == "__main__":
    sys.exit(main())
