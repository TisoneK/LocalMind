"""Turn-close attribution live verification.

Boots the REAL LocalMind server (port 8765, scratch LOCALMIND_HOME) against
a local deterministic OpenAI-compat provider (the repo's established
`fakeprov` pattern — no external key needed), fires one chat turn through
the real loop + SSE transport, and asserts the turn-close contract on the
captured stream:

  1. a top-level `response_ready` SSE event arrives BEFORE `done`;
  2. the turn_complete observation / metrics carrier carries `turn_stages`
     (turn_started, first_token, last_token, response_ready,
     agent_loop_finished, turn_completed) with monotonic stamps;
  3. the carrier also carries `post_answer_lanes` (a dict — the gate and
     the completion judge are the expected lanes on a plain short reply);
  4. the `done` payload's provider_usage carries turn_stages too.

One script invocation = one self-contained trace; artifacts land in
scratch/ and the server is killed in finally. No API keys are read,
printed, or required.
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
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
sys.path.insert(0, str(REPO / "scripts"))
from harness_common import kill_process_tree, server_popen_kwargs, venv_python  # noqa: E402

PORT = 8765
FAKE_PORT = 18765
HOME = REPO / "scratch" / "b24home"
TRACE = REPO / "scratch" / "sse-b24-live.sse"
REPLY = "Live trace: the answer is complete."


class FakeProvider(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible /chat/completions: streams the reply in
    several chunks, then finish_reason=stop (usage reported on the last)."""

    def log_message(self, *a):  # silence request logging
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        self.rfile.read(length)
        if self.path.endswith("/chat/completions"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            pieces = [REPLY[:8], REPLY[8:20], REPLY[20:]]
            for piece in pieces:
                chunk = {
                    "id": "b24", "object": "chat.completion.chunk", "created": 1,
                    "model": "b24-flash",
                    "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
                }
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
                time.sleep(0.05)
            last = {
                "id": "b24", "object": "chat.completion.chunk", "created": 1,
                "model": "b24-flash",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 120, "completion_tokens": 12,
                    "total_tokens": 132, "prompt_tokens_details": {"cached_tokens": 100},
                },
            }
            self.wfile.write(f"data: {json.dumps(last)}\n\n".encode())
            self.wfile.flush()
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
                "name": "b24-fake",
                "kind": "openai-compat",
                "base_url": f"http://127.0.0.1:{FAKE_PORT}/v1",
                "model": "b24-flash",
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
    log = REPO / "scratch" / "server-b24-live.log"
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


def fire_chat(message: str, timeout: int = 90) -> str:
    body = urllib.parse.urlencode(
        {"message": message, "session_id": "b24-live", "is_first": "true"}
    ).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/chat",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


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


def main() -> int:
    fake = boot_fake()
    server: Optional[subprocess.Popen] = None
    try:
        write_settings()
        server = boot_server()
        raw = fire_chat("Say something short so the turn can close.")
        TRACE.write_text(raw)
        events = parse_events(raw)
        types = [e.get("type") for e in events]

        failures: list[str] = []
        if "response_ready" not in types:
            failures.append("no response_ready event on the wire")
        if "done" not in types:
            failures.append("no done event")
        if "response_ready" in types and "done" in types:
            if types.index("response_ready") > types.index("done"):
                failures.append("response_ready arrived AFTER done")

        rr = next((e for e in events if e.get("type") == "response_ready"), None)
        if rr:
            stages = rr.get("stages") or {}
            for key in ("turn_started", "response_ready"):
                if key not in stages:
                    failures.append(f"response_ready.stages missing {key}")
            stamps = [stages[k] for k in ("turn_started", "response_ready") if k in stages]
            if stamps != sorted(stamps):
                failures.append("response_ready stage stamps not monotonic")
            if not isinstance(rr.get("lanes"), dict):
                failures.append("response_ready.lanes missing")
        else:
            failures.append("response_ready event had no payload")

        metrics = next((e for e in events if e.get("type") == "metrics"), None)
        # Primary carrier: the turn_complete observation (per-chunk bridge).
        # The dedicated metrics SSE event is the final-drain carrier — present
        # when turn_complete lands there; the frontend reads both.
        obs_tc = next(
            (e for e in events
             if isinstance(e.get("obs_event"), dict) and e["obs_event"].get("type") == "turn_complete"),
            None,
        )
        carrier = metrics.get("metrics", {}) if metrics else (
            ((obs_tc or {}).get("obs_event", {}).get("data", {}).get("provider_usage") or {})
            if obs_tc else {}
        )
        mstages = carrier.get("turn_stages") or {}
        expected_stages = [
            "turn_started", "first_token", "last_token",
            "response_ready", "agent_loop_finished", "turn_completed",
        ]
        for key in expected_stages:
            if key not in mstages:
                failures.append(f"turn_complete/metrics carrier missing stage {key}")
        seq = [mstages[k] for k in expected_stages if k in mstages]
        if seq != sorted(seq):
            failures.append(f"stage stamps not monotonic: {mstages}")
        if "post_answer_lanes" not in carrier:
            failures.append("turn_complete/metrics carrier missing post_answer_lanes")

        done = next((e for e in events if e.get("type") == "done"), None)
        if done is not None:
            ustages = (done.get("provider_usage") or {}).get("turn_stages") or {}
            if "turn_started" not in ustages:
                failures.append("done.provider_usage.turn_stages missing")

        answer = "".join(e.get("content", "") for e in events if e.get("type") == "token")
        if REPLY not in answer:
            failures.append(f"answer text incomplete: {answer!r}")

        print("=" * 74)
        print("TURN-CLOSE LIVE TRACE (fakeprov, real server+loop+SSE)")
        print("=" * 74)
        print(f"event types      : {types}")
        if rr:
            print(f"response_ready   : stages={rr.get('stages')}")
            print(f"                   lanes={rr.get('lanes')}")
        if metrics:
            m = metrics.get("metrics", {})
            print(f"metrics.stages   : {m.get('turn_stages')}")
            print(f"metrics.lanes    : {m.get('post_answer_lanes')}")
        elif obs_tc:
            pu = obs_tc.get("obs_event", {}).get("data", {}).get("provider_usage", {})
            print(f"obs turn_complete stages: {pu.get('turn_stages')}")
            print(f"obs turn_complete lanes : {pu.get('post_answer_lanes')}")
        print(f"answer           : {answer!r}")
        print(f"trace saved      : {TRACE}")
        if failures:
            print("FAILURES:")
            for f in failures:
                print(f"  - {f}")
            return 1
        print("RESULT: PASS — response_ready precedes done; stage map complete and monotonic.")
        return 0
    finally:
        if server is not None:
            kill_process_tree(server.pid)
        fake.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
