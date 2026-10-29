#!/usr/bin/env python3
"""Live verification: the done-rules extension (roadmap §U item 4, row E).

Two guarantees, proven on the wire rather than in a unit test:

1. Synthetic results for unanswered calls. A tool call that never reports a
   result still gets a recorded result — an unknown-outcome placeholder that
   says the effect is unknown and forbids a blind re-run. The transcript stays
   usable (every assistant tool call is paired with a tool message) and the
   audit record says what happened.
2. The provider-death completion path IS a done-rule, not a rescue: a turn
   whose synthesis died with evidence in hand delivers what the evidence
   supports, framed with the death (provider named, code verbatim), and a
   terminal death rides the final chunk so the honest card still shows.

No provider credential exists in this sandbox, so the proof is the wire: a
local fake OpenAI-compatible provider CAPTURES every request body the server
sends. Two probes against the REAL server on isolated port 8765 + a scratch
LOCALMIND_HOME (code_exec dispatch timeout pinned to 2s so the unanswered-call
probe stays fast):

  Probe A (unanswered call): the model asks for code_exec running sleep(10);
           the dispatch timeout (2s, two attempts) exhausts, so no result ever
           comes back. The record must carry an unknown-outcome placeholder —
           on the SSE tool_call event AND on the next captured request — and
           the turn must continue to an answer instead of dying.
  Probe B (degraded answer): sysinfo evidence lands, then the provider dies
           with the exact 12:45 insufficient-balance payload. The answer must
           carry the evidence framed with the death, the degraded event must
           be terminal, and the canonical error must ride the stream.
  Pairing  (every request): across every captured request body, no assistant
           tool call may be left without a tool result.

Usage:
  cd backend && ../scripts/live_test_done_rules.py
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
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_common import (
    kill_port,
    kill_process_tree,
    server_popen_kwargs,
    venv_python,
)

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
VENV_PY = venv_python(BACKEND)
SCRATCH = REPO / "scratch"
HOME = SCRATCH / "donehome"
PORT = 8765
FAKE_PORT = 18794

PROVIDER_NAME = "DoneRules Provider (harness)"
INIT_MARKER = "initialization stage of LocalMind's parent agent"
UNKNOWN_MARKER = "OUTCOME UNKNOWN"


class FakeProvider(BaseHTTPRequestHandler):
    """State machine over the probes; replies are composed from the wire."""

    request_count: ClassVar[int] = 0
    captures: ClassVar[list[dict]] = []
    mode: ClassVar[str] = "A"
    # Set when a request arrives carrying the unknown-outcome placeholder in a
    # tool message: the record the loop built is what the provider then sees.
    marker_seen: ClassVar[bool] = False

    log_message = lambda self, *a, **k: None  # noqa: E731 — keep the log readable

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

    def _send_sse_chunks(self, chunks: list[dict]):
        for c in chunks:
            self._sse(c)
        body = b"data: [DONE]\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._json({"object": "list", "data": [{"id": "donerules-flash"}]})
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
        FakeProvider.captures.append(body)

        n = FakeProvider.request_count
        mode = FakeProvider.mode
        text = json.dumps(body)

        if INIT_MARKER in text:
            reply = json.dumps(
                {
                    "mode": "execute",
                    "acknowledgement": "Working from the context I already hold.",
                    "response": "",
                    "objective": "Carry out the request",
                    "title": "Carry Out Request",
                    "plan": ["Do the work with the tools"],
                    "clarifying_question": "",
                    "confidence": 0.9,
                }
            )
            self._send_sse_chunks(self._text_chunks(reply))
            return

        if mode == "A":
            if n == 1:
                self._send_sse_chunks(
                    [
                        {"id": "c1", "object": "chat.completion.chunk", "created": 1,
                         "model": "donerules-flash",
                         "choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
                             {"index": 0, "id": "call_a", "type": "function",
                              "function": {"name": "code_exec",
                                           "arguments": "{\"code\": \"import time\\ntime.sleep(10)\"}"}}]},
                             "finish_reason": None}]},
                        {"id": "c1", "object": "chat.completion.chunk", "created": 1,
                         "model": "donerules-flash",
                         "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
                    ]
                )
                return
            # The record the loop built is what the provider sees: note when a
            # request carries the unknown-outcome placeholder.
            tool_text = "\n".join(
                str(m.get("content", ""))
                for m in body.get("messages", [])
                if isinstance(m, dict) and m.get("role") == "tool"
            )
            if UNKNOWN_MARKER in tool_text:
                FakeProvider.marker_seen = True
            self._send_sse_chunks(
                self._text_chunks("The code run did not report back; I can't say it happened.")
            )
            return

        # mode == "B": sysinfo evidence on the first loop call, then the death.
        if n == 1:
            self._send_sse_chunks(
                [
                    {"id": "c1", "object": "chat.completion.chunk", "created": 1,
                     "model": "donerules-flash",
                     "choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
                         {"index": 0, "id": "call_b", "type": "function",
                          "function": {"name": "sysinfo",
                                       "arguments": "{\"query\": \"clock and platform\"}"}}]},
                         "finish_reason": None}]},
                    {"id": "c1", "object": "chat.completion.chunk", "created": 1,
                     "model": "donerules-flash",
                     "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
                ]
            )
            return
        # The provider death — the exact 12:45 payload shape.
        self._json(
            {
                "error": {
                    "message": "credit insufficient balance: balance=0 required=5196 "
                    "(request id: 20261027DONERULES)",
                    "type": "insufficient_balance",
                }
            },
            400,
        )

    def _text_chunks(self, reply: str) -> list[dict]:
        return [
            {"id": "c1", "object": "chat.completion.chunk", "created": 1,
             "model": "donerules-flash",
             "choices": [{"index": 0, "delta": {"role": "assistant", "content": reply},
                          "finish_reason": None}]},
            {"id": "c1", "object": "chat.completion.chunk", "created": 1,
             "model": "donerules-flash",
             "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ]


def boot_fake() -> ThreadingHTTPServer:
    FakeProvider.request_count = 0
    FakeProvider.captures = []
    FakeProvider.mode = "A"
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
                "name": PROVIDER_NAME,
                "kind": "openai-compat",
                "base_url": f"http://127.0.0.1:{FAKE_PORT}/v1",
                "model": "donerules-flash",
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
            "LOCALMIND_ADAPTER": "fakeprov",
            # Both dispatch attempts must hit the 2s wait_for quickly so the
            # unanswered-call probe does not stall the run.
            "LOCALMIND_CODE_EXEC_TIMEOUT": "2",
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


def api_get(path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=15) as resp:
        return json.loads(resp.read().decode())


def fire_chat(message: str, session_id: str, timeout: int = 240) -> str:
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        # Suppress the trivial fast path so the turn runs the real loop.
        "X-LocalMind-Intent": "tool",
    }
    body = urllib.parse.urlencode(
        {"message": message, "session_id": session_id, "is_first": "true"}
    ).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/chat",
        data=body,
        headers=headers,
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


def sse_answer(events: list[dict]) -> str:
    return "".join(e.get("content", "") for e in events if e.get("type") == "token")


def obs_events(events: list[dict], event_type: str) -> list[dict]:
    out = []
    for e in events:
        obs = e.get("obs_event") or {}
        if obs.get("type") == event_type:
            out.append(obs.get("data") or {})
    return out


def tool_call_events(events: list[dict]) -> list[dict]:
    return [e.get("tool_call") or {} for e in events if e.get("type") == "tool_call"]


def unpaired_ids(body: dict) -> list[str]:
    """Assistant tool calls in one request body that carry no tool result."""
    pending: list[str] = []
    for msg in body.get("messages", []):
        if not isinstance(msg, dict):
            continue
        for call in msg.get("tool_calls") or []:
            if isinstance(call, dict) and isinstance(call.get("id"), str):
                pending.append(call["id"])
        if msg.get("role") == "tool":
            cid = msg.get("tool_call_id")
            if cid in pending:
                pending.remove(cid)
    return pending


def main() -> int:
    problems: list[str] = []
    kill_port(PORT)
    kill_port(FAKE_PORT)
    fake = boot_fake()
    write_settings()
    log = SCRATCH / "donehome-server.log"
    proc = None
    try:
        proc = boot_server(log)

        # ── Probe A: a call that never reported back ──────────────────────
        FakeProvider.mode = "A"
        FakeProvider.request_count = 0
        raw_a = fire_chat("Run the sleep code for me.", session_id="done-probe-a")
        ev_a = parse_sse(raw_a)
        tcs = tool_call_events(ev_a)
        dead = next(
            (tc for tc in tcs if tc.get("name") == "code_exec" and tc.get("status") == "failed"),
            None,
        )
        if dead is None:
            problems.append(
                "probe A: no failed code_exec tool_call on the stream "
                f"(saw: {[(tc.get('name'), tc.get('status')) for tc in tcs]})"
            )
        elif UNKNOWN_MARKER not in str(dead.get("output") or ""):
            problems.append(
                f"probe A: the audit record does not mark the outcome unknown: "
                f"{str(dead.get('output'))[:200]!r}"
            )
        captures_a = list(FakeProvider.captures)
        wire_tool_text = "\n".join(
            str(m.get("content", ""))
            for body in captures_a
            for m in body.get("messages", [])
            if isinstance(m, dict) and m.get("role") == "tool"
        )
        if UNKNOWN_MARKER not in wire_tool_text:
            problems.append(
                "probe A: the next request carried no unknown-outcome result for the lost call"
            )
        if not FakeProvider.marker_seen:
            problems.append(
                "probe A: the placeholder never reached a provider request as a tool message"
            )
        if "do NOT run it again blindly" not in wire_tool_text:
            problems.append(
                "probe A: the placeholder does not forbid a blind re-run"
            )
        ans_a = sse_answer(ev_a)
        if not ans_a.strip():
            problems.append("probe A: the turn produced no answer past the lost call")
        # A turn that cannot act must not keep asking: the completion floor's
        # replan budget bounds it (19 replans — 43 provider calls — before).
        if FakeProvider.request_count > 12:
            problems.append(
                f"probe A: the turn spun for {FakeProvider.request_count} provider calls"
            )
        print(
            f"--- probe A (unanswered call): {FakeProvider.request_count} provider call(s); "
            f"tool_call output: {str((dead or {}).get('output'))[:120]!r}; "
            f"answer head: {ans_a[:100]!r}"
        )

        # ── Probe B: synthesis death with evidence in hand ────────────────
        FakeProvider.mode = "B"
        FakeProvider.request_count = 0
        raw_b = fire_chat("What time is it here? Check the system.", session_id="done-probe-b")
        ev_b = parse_sse(raw_b)
        degraded = obs_events(ev_b, "agent_loop_degraded")
        if not degraded:
            problems.append("probe B: no agent_loop_degraded event on the stream")
        else:
            d = degraded[-1]
            if not d.get("terminal"):
                problems.append(f"probe B: degraded event not terminal: {d}")
            if d.get("provider_error_code") != "payment_required":
                problems.append(
                    f"probe B: degraded event code wrong: {d.get('provider_error_code')!r}"
                )
            if not str(d.get("provider") or ""):
                problems.append(f"probe B: degraded event provider unnamed: {d.get('provider')!r}")
        errs = [e.get("error") or {} for e in ev_b if e.get("type") == "error"]
        if not errs:
            problems.append("probe B: no canonical error object on the stream")
        elif errs[-1].get("code") != "payment_required" or errs[-1].get("retryable"):
            problems.append(f"probe B: error envelope not honest: {errs[-1]}")
        ans_b = sse_answer(ev_b)
        if "payment_required" not in ans_b:
            problems.append(f"probe B: the death was not stated in the answer: {ans_b[:200]!r}")
        # Either delivery shape is honest: an extracted answer is framed "as
        # gathered", and the raw-evidence fallback says so in its own words.
        framed = "as gathered" in ans_b or "raw evidence" in ans_b
        if not framed:
            problems.append(
                f"probe B: the answer does not say what it is: {ans_b[:200]!r}"
            )
        if "try again" in ans_b.lower():
            problems.append("probe B: dead advice ('try again') reached a terminal death")
        print(
            f"--- probe B (degraded answer): {FakeProvider.request_count} provider call(s); "
            f"degraded={degraded[-1] if degraded else None}; answer head: {ans_b[:120]!r}"
        )

        # ── Pairing: no captured request left a call unanswered ───────────
        dangling = [
            (i, ids)
            for i, body in enumerate(FakeProvider.captures)
            if (ids := unpaired_ids(body))
        ]
        if dangling:
            problems.append(f"pairing: request(s) with unanswered calls: {dangling}")
        total_requests = len(FakeProvider.captures)
        total_tool_msgs = sum(
            1
            for body in FakeProvider.captures
            for m in body.get("messages", [])
            if isinstance(m, dict) and m.get("role") == "tool"
        )
        print(
            f"--- pairing: {total_requests} captured request(s), {total_tool_msgs} tool "
            f"message(s), unanswered calls: {len(dangling)}"
        )

        # ── Reload: the degraded phase survives ──────────────────────────
        hist = api_get("/api/sessions/done-probe-b/history")
        messages = hist.get("history") or []
        assistant = [m for m in messages if m.get("role") == "assistant"]
        if not assistant:
            problems.append("reload: no assistant message in the persisted history")
        else:
            phases = assistant[-1].get("agentPhases") or []
            deg = [p for p in phases if p.get("type") == "agent_loop_degraded"]
            if not deg:
                problems.append(
                    "reload: no agent_loop_degraded phase persisted "
                    f"(phases: {[p.get('type') for p in phases]})"
                )
            else:
                print(f"--- reload: degraded phase detail={deg[-1].get('detail')!r}")

        print()
        if problems:
            print("FAIL")
            for p in problems:
                print(f"  - {p}")
            return 1
        print(
            "PASS — a call that never reported back left a recorded unknown-outcome "
            "result on the wire (and forbade a blind re-run), every captured request "
            "paired its tool calls, and a synthesis death with evidence in hand "
            "delivered the evidence framed with the terminal code, still on the record "
            "after a reload"
        )
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
