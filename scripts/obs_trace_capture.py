"""Full-execution-observability investigation capture (Zuri S011).

INVESTIGATION TOOL — records what the running system actually emits and
persists; changes no product code.

Boots the REAL LocalMind server (port 8765, scratch LOCALMIND_HOME) against
the local deterministic OpenAI-compat fake provider (established harness
pattern, no external key), fires the owner's three-turn experiment shape in
one session:

    1. "Hey sup LM?"
    2. "What can you do?"
    3. "Nice to hear about those capabilities. Pretty impressive I must say."

and after EVERY turn captures five surfaces:

  A. the complete SSE stream (every event, in arrival order);
  B. GET /api/sessions/<id>/history  — the exact source the chat export reads;
  C. GET /api/observability/<id>     — the persisted observation snapshot;
  D. the raw sqlite `messages` row    — every telemetry column that persists;
  E. the server log                   — logger-only lines (log-only stages).

Artifacts land in scratch/obs-trace/ (one JSON per turn + a compact
per-turn inventory on stdout). One invocation = one self-contained trace;
the server and fake provider are killed in finally.

The fake provider reports realistic usage and streams thinking + answer so
both path shapes (direct conversational and parent-loop) produce full wire
traffic.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
sys.path.insert(0, str(REPO / "scripts"))
from harness_common import kill_process_tree, server_popen_kwargs, venv_python  # noqa: E402

PORT = 8765
FAKE_PORT = 18766
HOME = REPO / "scratch" / "obs-trace-home"
OUT = REPO / "scratch" / "obs-trace"
SESSION = "obs-trace-live"

MESSAGES = [
    "Hey sup LM?",
    "What can you do?",
    "Nice to hear about those capabilities. Pretty impressive I must say.",
]

REPLY = "Sure — happy to help. Ask me anything about your workspace."


class FakeProvider(BaseHTTPRequestHandler):
    """OpenAI-compat /chat/completions: streams a thinking block then the
    reply in pieces, reports usage on the final chunk (cached tokens too)."""

    def log_message(self, *a):  # silence request logging
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        self.rfile.read(length)
        if self.path.endswith("/chat/completions"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()

            def sse(obj):
                self.wfile.write(f"data: {json.dumps(obj)}\n\n".encode())
                self.wfile.flush()

            think = {
                "id": "obs", "object": "chat.completion.chunk", "created": 1,
                "model": "obs-flash",
                "choices": [{"index": 0, "delta": {"reasoning_content": "Quick read of the ask."}, "finish_reason": None}],
            }
            sse(think)
            for piece in [REPLY[:10], REPLY[10:26], REPLY[26:]]:
                sse({
                    "id": "obs", "object": "chat.completion.chunk", "created": 1,
                    "model": "obs-flash",
                    "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
                })
                time.sleep(0.03)
            sse({
                "id": "obs", "object": "chat.completion.chunk", "created": 1,
                "model": "obs-flash",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 480, "completion_tokens": 21,
                    "total_tokens": 501,
                    "prompt_tokens_details": {"cached_tokens": 380},
                },
            })
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"{}")


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
                "name": "obs-fake",
                "kind": "openai-compat",
                "base_url": f"http://127.0.0.1:{FAKE_PORT}/v1",
                "model": "obs-flash",
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


def http_post_chat(message: str, timeout: int = 90) -> str:
    body = urllib.parse.urlencode(
        {"message": message, "session_id": SESSION}
    ).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/chat",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def http_get_json(path: str, timeout: int = 15) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_events(raw: str) -> list[dict]:
    events = []
    for block in raw.split("\n\n"):
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[6:]))
                except Exception:
                    pass
    return events


def event_type(e: dict) -> str:
    if "type" in e:
        return e["type"]
    if "obs_event" in e:
        inner = e["obs_event"] or {}
        return f"obs_event:{inner.get('type', '?')}"
    return "<raw>"


def db_rows() -> list[dict]:
    db_path = HOME / "localmind.db"
    if not db_path.exists():
        for cand in HOME.rglob("*.db"):
            db_path = cand
            break
    if not db_path.exists():
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id", (SESSION,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def inventory(turn: int, sse_events: list[dict], history: dict, obsnap: dict, rows: list[dict], log_tail: str) -> dict:
    types = [event_type(e) for e in sse_events]
    hist_msgs = history.get("messages") or history.get("history") or []
    inv: dict = {
        "turn": turn,
        "sse_event_count": len(sse_events),
        "sse_type_histogram": {},
        "sse_order": types,
        "history_shape": {
            "top_level_keys": sorted(history.keys()),
            "message_keys": sorted({k for m in hist_msgs for k in (m or {}).keys()}) if hist_msgs else [],
        },
        "observation_snapshot_keys": sorted(obsnap.keys()) if isinstance(obsnap, dict) else str(type(obsnap)),
        "persisted_message_rows": [
            {
                "role": r.get("role"),
                "timestamp": r.get("timestamp"),
                "has_metrics": r.get("metrics") is not None,
                "metrics_keys": sorted((json.loads(r["metrics"]) if r.get("metrics") else {}).keys()),
                "has_thinking": bool(r.get("thinking")),
                "tool_calls_present": bool(r.get("tool_calls")),
                "agent_runs_present": bool(r.get("agent_runs")),
                "agent_phases_present": bool(r.get("agent_phases")),
                "injected_items_present": bool(r.get("injected_items")),
            }
            for r in rows
            if r.get("role") in ("user", "assistant")
        ][: 2 * turn + 2],
        "log_lines_this_turn": [
            line
            for line in log_tail.splitlines()
            if "fast-path" in line or "pre-init" in line or "classified" in line.lower()
        ][-6:],
    }
    for t in types:
        inv["sse_type_histogram"][t] = inv["sse_type_histogram"].get(t, 0) + 1
    return inv


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    fake = boot_fake()
    server: Optional[subprocess.Popen] = None
    try:
        write_settings()
        server = boot_server()
        log_path = OUT / "server.log"
        summaries = []
        for i, message in enumerate(MESSAGES, start=1):
            raw = http_post_chat(message)
            (OUT / f"turn{i}.sse.txt").write_text(raw)
            events = parse_events(raw)
            time.sleep(1.5)  # let background lanes flush
            try:
                history = http_get_json(f"/api/sessions/{SESSION}/history")
            except Exception as exc:
                history = {"error": repr(exc)}
            try:
                obsnap = http_get_json(f"/api/observability/{SESSION}")
            except Exception as exc:
                obsnap = {"error": repr(exc)}
            rows = db_rows()
            log_tail = log_path.read_text(errors="replace") if log_path.exists() else ""
            (OUT / f"turn{i}.history.json").write_text(json.dumps(history, indent=2))
            (OUT / f"turn{i}.observation.json").write_text(json.dumps(obsnap, indent=2))
            (OUT / f"turn{i}.db-rows.json").write_text(
                json.dumps(rows, indent=2, default=str)
            )
            inv = inventory(i, events, history, obsnap, rows, log_tail)
            summaries.append(inv)
            print(json.dumps(inv, indent=2))
        (OUT / "summary.json").write_text(json.dumps(summaries, indent=2))
        print(f"\nartifacts: {OUT}")
        return 0
    finally:
        if server is not None:
            kill_process_tree(server.pid)
        fake.shutdown()


if __name__ == "__main__":
    sys.exit(main())
