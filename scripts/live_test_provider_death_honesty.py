#!/usr/bin/env python3
"""Live verification: provider-death honesty & the provider-death completion
path (roadmap §U item 1, docs/reference-harness-gap-inventory.md).

Reproduces the 2026-10-27 12:45 failure shape with NO provider credential:
a local fake OpenAI-compatible provider returns HTTP 400 with the exact
insufficient-balance body under the connection display name
"BankOfAI (promo free models — time-limited)". Two probes against the REAL
server on isolated port 8765 + scratch LOCALMIND_HOME:

  Probe A (evidence in hand): a URL-fetch message trips the SINGLE_TOOL
  fast path — the engine pre-dispatches web_fetch for real, so successful
  evidence exists when the synthesis call dies. Contract: the SSE stream
  delivers what the evidence supports, framed honestly (provider named,
  code verbatim, "as gathered"), AND the error event carries the parsed
  envelope (provider == the full display name, code payment_required,
  retryable false) — provider never "unknown".

  Probe B (no evidence): a plain greeting dies on the init stream.
  Contract: the error event names the provider and the code verbatim.

PASS rules (all must hold on both probes):
  1. provider is the full display name (never null/"unknown");
  2. code == payment_required, retryable == false;
  3. Probe A's answer text names the provider + code and contains real
     page evidence, with no "try again" / "larger model" advice;
  4. Probe A emits agent_loop_degraded with terminal=true.

Usage:
  cd backend && ../scripts/live_test_provider_death_honesty.py
"""
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_common import kill_port, kill_process_tree, server_popen_kwargs, venv_python  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
VENV_PY = venv_python(BACKEND)
SCRATCH = REPO / "scratch"
HOME = SCRATCH / "deathhome"
PORT = 8765
FAKE_PORT = 18790

PROVIDER_NAME = "BankOfAI (promo free models — time-limited)"
DEATH_BODY = json.dumps(
    {
        "error": {
            "message": "credit insufficient balance: balance=0 required=5196 "
            "(request id: 20261027LIVE0001)",
            "type": "insufficient_balance",
        }
    }
)

URL_MESSAGE = "what is the weather in Kiambu Town today"
GREETING = "hello"


class FakeProvider(BaseHTTPRequestHandler):
    """Request 1 answers with a real OpenAI-format web_search tool_call so
    the loop executes a REAL search (evidence in hand). Every later request
    dies with the exact 12:45 shape: HTTP 400, pure-JSON insufficient-balance
    body — the adapter wraps it as "{name} returned 400: {body}". Anything
    else (models list etc.) gets a minimal 200 so startup probes stay quiet."""

    request_count = 0

    def log_message(self, *a):  # keep the scratch log readable
        pass

    def _json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _sse(self, payload: dict):
        body = ("data: " + json.dumps(payload) + "\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._json({"object": "list", "data": [{"id": "deepseek-v4-flash"}]})
        else:
            self._json({"ok": True})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if "/chat/completions" not in self.path:
            self._json({"error": {"message": "not found"}}, 404)
            return
        FakeProvider.request_count += 1
        if FakeProvider.request_count == 1:
            # Round 1: a genuine tool call — the engine executes web_search
            # for real, so the turn owns successful evidence when synthesis
            # dies. Chunked per the adapter's delta accumulation contract.
            chunks = [
                {"id": "c1", "object": "chat.completion.chunk", "created": 1,
                 "model": "deepseek-v4-flash",
                 "choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
                     {"index": 0, "id": "call_1", "type": "function",
                      "function": {"name": "sysinfo",
                                   "arguments": "{\"query\": \"system overview\"}"}}]},
                     "finish_reason": None}]},
                {"id": "c1", "object": "chat.completion.chunk", "created": 1,
                 "model": "deepseek-v4-flash",
                 "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            ]
            for c in chunks:
                self._sse(c)
            body = b"data: [DONE]\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        # Rounds 2+: the provider death — pure JSON body, exactly like the
        # real 12:45 payload (the adapter adds the "name returned 400:" wrap).
        self._json(
            {
                "error": {
                    "message": "credit insufficient balance: balance=0 required=5196 "
                    "(request id: 20261027LIVE0001)",
                    "type": "insufficient_balance",
                }
            },
            400,
        )


def boot_fake() -> ThreadingHTTPServer:
    FakeProvider.request_count = 0
    srv = ThreadingHTTPServer(("127.0.0.1", FAKE_PORT), FakeProvider)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def write_settings() -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    settings = {
        "adapter": "deadprov",
        "api_keys": {"deadprov": "sk-local-fake-not-a-real-key"},
        "connections": [
            {
                "id": "deadprov",
                "name": PROVIDER_NAME,
                "kind": "openai-compat",
                "base_url": f"http://127.0.0.1:{FAKE_PORT}/v1",
                "model": "deepseek-v4-flash",
                "enabled": True,
            }
        ],
    }
    (HOME / "settings.json").write_text(json.dumps(settings, indent=2))


def boot_server(log_file: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env.update(
        {
            "LOCALMIND_PORT": str(PORT),
            "LOCALMIND_HOME": str(HOME),
            "LOCALMIND_ADAPTER": "deadprov",
            "PYTHONPATH": str(BACKEND / "src"),
        }
    )
    proc = subprocess.Popen(
        [VENV_PY, "server.py"],
        cwd=str(BACKEND),
        env=env,
        stdout=open(log_file, "wb"),
        stderr=subprocess.STDOUT,
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


def fire_chat(message: str, session_id: str, timeout: int = 180) -> str:
    body = urllib.parse.urlencode(
        {"message": message, "session_id": session_id, "is_first": "true"}
    ).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/chat",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_sse(raw: str) -> list[dict]:
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):]
        if payload == "[DONE]":
            continue
        try:
            events.append(json.loads(payload))
        except json.JSONDecodeError:
            continue
    return events


def score(label: str, events: list[dict], want_answer: bool) -> list[str]:
    problems: list[str] = []
    text = "".join(e.get("content", "") for e in events if e.get("type") == "token")
    errors = [e.get("error") or {} for e in events if e.get("type") == "error"]
    # Obs events travel wrapped: {"obs_event": {"type": ..., "data": ...}}.
    obs = [
        e["obs_event"]
        for e in events
        if isinstance(e.get("obs_event"), dict)
    ]
    if not errors:
        return [f"{label}: NO error event reached the SSE stream"]
    err = errors[-1]
    provider = err.get("provider")
    if provider != PROVIDER_NAME:
        problems.append(
            f"{label}: provider expected the full display name, got {provider!r}"
        )
    if err.get("code") != "payment_required":
        problems.append(f"{label}: code expected payment_required, got {err.get('code')!r}")
    if err.get("retryable") is not False:
        problems.append(f"{label}: retryable expected False, got {err.get('retryable')!r}")
    if want_answer:
        low = text.lower()
        if PROVIDER_NAME not in text:
            problems.append(f"{label}: answer does not name the provider")
        if "payment_required" not in text:
            problems.append(f"{label}: answer does not state the code verbatim")
        if "try again" in low or "larger model" in low:
            problems.append(f"{label}: answer suggests known-dead retries")
        if "can't continue because the failure is not retryable" in text:
            problems.append(f"{label}: dead-end prose served despite evidence in hand")
        if not any(
            o.get("type") == "agent_loop_degraded"
            and (o.get("data") or {}).get("terminal") is True
            for o in obs
        ):
            problems.append(f"{label}: no agent_loop_degraded(terminal=true) event")
        if not text.strip():
            problems.append(f"{label}: empty answer bubble")
        if len(text.strip()) < 150:
            problems.append(
                f"{label}: answer too short to carry evidence ({len(text)} chars)"
            )
    print(f"--- {label}: {len(events)} events, answer {len(text)} chars ---")
    print(text[:600])
    for o in obs:
        if str(o.get("type", "")).startswith("agent_loop"):
            print(f"--- obs event on the wire: {json.dumps(o)[:300]}")
    print(f"--- error envelope: { {k: err.get(k) for k in ('provider', 'code', 'retryable')} } ---")
    return problems


def main() -> int:
    kill_port(PORT)
    kill_port(FAKE_PORT)
    fake = boot_fake()
    write_settings()
    log = SCRATCH / "deathhome-server.log"
    proc = None
    try:
        proc = boot_server(log)
        raw_a = fire_chat(URL_MESSAGE, session_id="death-probe-a")
        problems = score("probe A (evidence in hand)", parse_sse(raw_a), want_answer=True)
        raw_b = fire_chat(GREETING, session_id="death-probe-b")
        problems += score("probe B (no evidence)", parse_sse(raw_b), want_answer=False)
        print()
        if problems:
            print("FAIL")
            for p in problems:
                print(f"  - {p}")
            return 1
        print("PASS — provider named, code verbatim, evidence delivered, no dead advice")
        return 0
    finally:
        kill_process_tree(proc, use_sigkill=True)
        fake.shutdown()
        # Close the fake's listening socket BEFORE any port sweep: it lives in
        # this process, so a still-open listener makes kill_port(FAKE_PORT)
        # taskkill the harness itself (silently, with no traceback).
        fake.server_close()
        kill_port(PORT)


if __name__ == "__main__":
    sys.exit(main())
