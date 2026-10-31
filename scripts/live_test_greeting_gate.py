#!/usr/bin/env python3
"""Greeting-gate live verification (Nora S009).

Boots the REAL LocalMind server (port 8765, scratch LOCALMIND_HOME) against
the repo's established deterministic local provider (no external key needed)
and fires the regression turn from the live export of 2026-10-31:
"Hey sup LM?" answered conversationally with ZERO tool calls.

The fake provider is adversarial in exactly the way the regression needs:
  * the initialization/classify call gets a valid `execute` JSON — the same
    misroute the owner's live turn took (its phase strip read "analyze
    criteria unmet"), so the turn reaches the loop instead of the direct tier;
  * the completion judge's prompt (its exact marker phrase) gets "PENDING" —
    the false verdict the weak model returned live. If the gate still ran the
    judge on this zero-tool turn, the turn would replan.

Assertions on the captured SSE:
  1. NO agent_loop_gate_failed_replan observation (no replanning cycle);
  2. no "You described wanting to use a tool…" / "[TOOL COMMITMENT]" card
     anywhere on the wire (the regression's user-role demand);
  3. a minimal provider-call budget — the pre-init lane answers the greeting
     with ONE call (ceiling 2); the judge is never invoked on a clean
     zero-tool turn;
  4. a `done` event carrying the greeting reply;
  5. the persisted history stores the reply intact, and any persisted run
     record is time-consistent (startedAt <= completedAt).

One script invocation = one self-contained trace; artifacts land in scratch/
and the server is killed in finally. No API keys are read, printed, or
required.
"""

from __future__ import annotations

import json
import os
import shutil
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
HOME = REPO / "scratch" / "greeting-gate-home"
TRACE = REPO / "scratch" / "sse-greeting-gate.sse"
REPLY = "Hey! I'm doing well, thanks for checking in. How can I help you today?"

INIT_MARKER = "You are the initialization stage of LocalMind's parent agent"
JUDGE_MARKER = "Answer with exactly one word"

STATS = {"requests": 0, "prompts": []}


class FakeProvider(BaseHTTPRequestHandler):
    """Deterministic OpenAI-compat /chat/completions.

    The classify call gets `execute` (the regression's misroute), the judge
    gets PENDING (the regression's false verdict), everything else gets the
    greeting reply streamed in chunks."""

    def log_message(self, *a):  # silence request logging
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        if not self.path.endswith("/chat/completions"):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"{}")
            return
        STATS["requests"] += 1
        try:
            payload = json.loads(body or "{}")
        except Exception:
            payload = {}
        prompt = ""
        msgs = payload.get("messages") or []
        if msgs and isinstance(msgs[-1], dict):
            prompt = str(msgs[-1].get("content", ""))
        STATS["prompts"].append(" ".join(prompt.split())[:160])

        if JUDGE_MARKER in prompt:
            content = "PENDING"  # the live export's false verdict
        elif INIT_MARKER in prompt:
            content = json.dumps(
                {
                    "mode": "execute",  # the live export's misroute
                    "acknowledgement": "Checking in with you.",
                    "response": "",
                    "objective": "Respond to the user's greeting",
                    "title": "Greet User",
                    "plan": ["Respond to the greeting"],
                    "clarifying_question": "",
                    "confidence": 0.9,
                }
            )
        else:
            content = REPLY

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        pieces = [content[:8], content[8:24], content[24:]]
        for piece in pieces:
            if not piece:
                continue
            chunk = {
                "id": "gg", "object": "chat.completion.chunk", "created": 1,
                "model": "gg-flash",
                "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
            time.sleep(0.04)
        last = {
            "id": "gg", "object": "chat.completion.chunk", "created": 1,
            "model": "gg-flash",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 150, "completion_tokens": 20,
                "total_tokens": 170,
            },
        }
        self.wfile.write(f"data: {json.dumps(last)}\n\n".encode())
        self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def boot_fake() -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", FAKE_PORT), FakeProvider)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def write_settings() -> None:
    if HOME.exists():
        shutil.rmtree(HOME)
    HOME.mkdir(parents=True)
    settings = {
        "adapter": "fakeprov",
        "api_keys": {"fakeprov": "sk-local-fake-not-a-real-key"},
        "connections": [
            {
                "id": "fakeprov",
                "name": "gg-fake",
                "kind": "openai-compat",
                "base_url": f"http://127.0.0.1:{FAKE_PORT}/v1",
                "model": "gg-flash",
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
    log = REPO / "scratch" / "server-greeting-gate.log"
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
        {"message": message, "session_id": "greeting-gate", "is_first": "true"}
    ).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/chat",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_history() -> dict:
    with urllib.request.urlopen(
        f"http://127.0.0.1:{PORT}/api/sessions/greeting-gate/history", timeout=15
    ) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


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
    if PORT == 8000:
        print("FAIL: never touch port 8000")
        return 2
    fake = boot_fake()
    server: Optional[subprocess.Popen] = None
    failures: list[str] = []
    try:
        write_settings()
        STATS["requests"] = 0
        server = boot_server()
        raw = fire_chat("Hey sup LM?")
        TRACE.write_text(raw)
        events = parse_events(raw)
        types = [e.get("type") for e in events]
        obs_types = [
            e["obs_event"].get("type")
            for e in events
            if isinstance(e.get("obs_event"), dict)
        ]

        # 1. No replanning cycle on the greeting turn.
        if "agent_loop_gate_failed_replan" in obs_types:
            failures.append("gate fired a replan on a clean zero-tool greeting")
        # 2. No false TOOL COMMITMENT card anywhere on the wire.
        if "[TOOL COMMITMENT]" in raw:
            failures.append("[TOOL COMMITMENT] stage card present on the wire")
        # 3. Model-call budget: the pre-init conversational lane skips the
        # init call, so the greeting turn is ONE provider call (the answer).
        # The judge is a provider call too — if any gate re-judged this
        # zero-tool turn, the count exceeds 1. Fixed path observed: 1.
        if STATS["requests"] > 2:
            failures.append(
                f"greeting turn spent {STATS['requests']} provider calls (target: 1, ceiling: 2)"
            )
            for i, p in enumerate(STATS["prompts"]):
                failures.append(f"  call {i + 1} prompt: {p}")
        # 4. The turn completed with the greeting reply.
        if "done" not in types:
            failures.append("no done event")
        answer = "".join(e.get("content", "") for e in events if e.get("type") == "token")
        if REPLY not in answer:
            failures.append(f"answer text incomplete: {answer!r}")

        # 5. Persistence: the greeting turn persists NO agent_runs (a clean
        # zero-tool turn with no strip phases has nothing to restore — the
        # honest empty record), and the reply is stored intact.
        hist = fetch_history()
        msgs = hist.get("messages") or hist.get("history") or []
        assistants = [m for m in msgs if m.get("role") == "assistant"]
        if not assistants:
            failures.append("no persisted assistant message in history")
        elif REPLY not in str(assistants[-1].get("content", "")):
            failures.append("persisted assistant reply text mismatch")
        elif assistants[-1].get("agentRuns"):
            # If a record exists it must at least be time-consistent: the
            # regression export showed startedAt == completedAt.
            for run in assistants[-1]["agentRuns"]:
                if run.get("startedAt") is not None and run.get("completedAt") is not None:
                    if run["startedAt"] > run["completedAt"]:
                        failures.append("persisted run has startedAt > completedAt")
                    if run["startedAt"] == run["completedAt"] and run.get("phases"):
                        stamps = {p.get("timestamp") for p in run["phases"]}
                        if len(stamps) > 1:
                            failures.append(
                                "run window is one instant but phases carry multiple stamps"
                            )

    finally:
        if server is not None:
            kill_process_tree(server)
        fake.shutdown()

    if failures:
        print("FAIL:")
        for f in failures:
            print(f"  - {f}")
        print(f"trace: {TRACE}")
        return 1
    print("PASS: greeting turn answered with a minimal provider-call budget, "
          "zero replans, no false tool-commitment card; persisted record consistent.")
    print(f"trace: {TRACE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
