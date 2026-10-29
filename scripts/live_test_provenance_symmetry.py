#!/usr/bin/env python3
"""Live verification: provenance & audit symmetry (roadmap §U item 3,
docs/reference-harness-gap-inventory.md — rows B + G, fixes F5).

The guarantees under test:

1. Record == wire: every injected context item the backend records
   (kind/source/EXACT text) appears verbatim in the prompt the provider
   actually received. The record can claim nothing the wire didn't carry —
   the audit view is a projection of what the model saw, not a parallel
   story.
2. Failed attempts survive recovery: a tool that exhausts its retries
   puts the attempt ledger on the wire — the failed tool_call event
   carries the retry count and every failed attempt's error.
3. The provider-death degraded signal reaches the wire as a first-class
   event, the canonical error object rides the final chunk, and the
   PERSISTED history carries both the injected-items ledger and the
   degraded phase — the audit survives a reload.

No provider credential exists in this sandbox, so the proof is the wire:
a local fake OpenAI-compatible provider CAPTURES the exact request bodies
the server sends. Four probes against the REAL server on isolated port
8765 + scratch LOCALMIND_HOME (code_exec dispatch timeout pinned to 2s so
the retry probe stays fast):

  Probe A (record == wire): an agent-mode identity turn — the SSE stream
           must carry context_injected events whose every item's text
           appears verbatim in at least one captured request body, and the
           stated identity must ride the record as a typed item.
  Probe B (retry ledger): code_exec sleeping past the 2s dispatch timeout —
           two timed-out attempts, then the failed tool_call event on the
           SSE must carry retry_count=1 with both attempts and their
           errors.
  Probe C (degraded death): sysinfo evidence lands, then the provider
           dies with the exact 12:45 insufficient-balance payload — the
           SSE must carry agent_loop_degraded (terminal, payment_required,
           provider named) plus the canonical error object.
  Reload  (persistence): GET /api/sessions/<id>/history for probe C's
           session must return the injectedItems ledger and the
           agent_loop_degraded phase — the record outlives the stream.

Usage:
  cd backend && ../scripts/live_test_provenance_symmetry.py
"""
import json
import os
import re
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
HOME = SCRATCH / "provenancehome"
PORT = 8765
FAKE_PORT = 18793

PROVIDER_NAME = "WireProof Provider (provenance harness)"
STATED_NAME = "Amani"
STATED_PLACE = "Nairobi, Kenya"

INIT_MARKER = "initialization stage of LocalMind's parent agent"


class FakeProvider(BaseHTTPRequestHandler):
    """State machine over the probes: each probe sets `mode` and the
    request counter decides what the provider does — classify JSON, a real
    tool call, a final answer, or (probe C) the death."""

    request_count: ClassVar[int] = 0
    captures: ClassVar[list[dict]] = []
    mode: ClassVar[str] = "A"

    log_message = lambda self, *a, **k: None  # noqa: E731 — keep the log readable

    def _json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
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

    def _sse(self, payload: dict):
        body = ("data: " + json.dumps(payload) + "\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._json({"object": "list", "data": [{"id": "wireproof-flash"}]})
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
            # Classify-only call: force the execute tier so the turn runs
            # real loop iterations (the surfaces the audit records).
            reply = json.dumps(
                {
                    "mode": "execute",
                    "acknowledgement": "Working from the context I already hold.",
                    "response": "",
                    "objective": "Answer from the injected context",
                    "title": "Answer From Context",
                    "plan": ["Answer the user's question from the context you already have"],
                    "clarifying_question": "",
                    "confidence": 0.9,
                }
            )
            self._send_sse_chunks(self._text_chunks(reply))
            return

        if mode == "A":
            contents = "\n".join(
                str(m.get("content", "")) for m in body.get("messages", []) if isinstance(m, dict)
            )
            if STATED_NAME in contents and STATED_PLACE in contents:
                reply = f"Your name is {STATED_NAME} and you are in {STATED_PLACE} — you told me yourself."
            else:
                reply = "WIRE-MISS-A: the stated facts were not on the wire."
            self._send_sse_chunks(self._text_chunks(reply))
            return

        if mode == "B":
            if n == 1:
                # First loop call: a code_exec tool call that sleeps well
                # past the 2s dispatch timeout — both attempts will time out.
                chunks = [
                    {"id": "c1", "object": "chat.completion.chunk", "created": 1,
                     "model": "wireproof-flash",
                     "choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
                         {"index": 0, "id": "call_b", "type": "function",
                          "function": {"name": "code_exec",
                                       "arguments": "{\"code\": \"import time\\ntime.sleep(10)\"}"}}]},
                         "finish_reason": None}]},
                    {"id": "c1", "object": "chat.completion.chunk", "created": 1,
                     "model": "wireproof-flash",
                     "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
                ]
                self._send_sse_chunks(chunks)
                return
            reply = (
                "The code never ran — every attempt timed out, and I am not "
                "going to pretend otherwise."
            )
            self._send_sse_chunks(self._text_chunks(reply))
            return

        # mode == "C": sysinfo evidence on the first loop call, then the death.
        if n == 1:
            chunks = [
                {"id": "c1", "object": "chat.completion.chunk", "created": 1,
                 "model": "wireproof-flash",
                 "choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
                     {"index": 0, "id": "call_c", "type": "function",
                      "function": {"name": "sysinfo",
                                   "arguments": "{\"query\": \"clock and platform\"}"}}]},
                     "finish_reason": None}]},
                {"id": "c1", "object": "chat.completion.chunk", "created": 1,
                 "model": "wireproof-flash",
                 "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            ]
            self._send_sse_chunks(chunks)
            return
        # The provider death — pure JSON body, exactly like the real 12:45
        # payload (the adapter adds the "name returned 400:" wrap).
        self._json(
            {
                "error": {
                    "message": "credit insufficient balance: balance=0 required=5196 "
                    "(request id: 20261027PROV0001)",
                    "type": "insufficient_balance",
                }
            },
            400,
        )

    def _text_chunks(self, reply: str) -> list[dict]:
        return [
            {"id": "c1", "object": "chat.completion.chunk", "created": 1,
             "model": "wireproof-flash",
             "choices": [{"index": 0, "delta": {"role": "assistant", "content": reply},
                          "finish_reason": None}]},
            {"id": "c1", "object": "chat.completion.chunk", "created": 1,
             "model": "wireproof-flash",
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
                "model": "wireproof-flash",
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
            # The retry probe needs a SHORT code_exec dispatch timeout so
            # both attempts hit the dispatch-level wait_for quickly.
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


def api_post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def api_get(path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=15) as resp:
        return json.loads(resp.read().decode())


def fire_chat(message: str, session_id: str, timeout: int = 240) -> str:
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        # A non-chat client hint suppresses the trivial/conversational fast
        # path so the turn runs the REAL agent loop — the surfaces whose
        # injected items this proof inspects.
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


def main() -> int:
    problems: list[str] = []
    kill_port(PORT)
    kill_port(FAKE_PORT)
    fake = boot_fake()
    write_settings()
    log = SCRATCH / "provenancehome-server.log"
    proc = None
    try:
        proc = boot_server(log)

        # ── Setup: state the identity facts through the REAL endpoint ─────
        api_post(
            "/api/settings/identity",
            {"user_name": STATED_NAME, "user_place": STATED_PLACE},
        )
        print("--- setup: identity stated via POST /api/settings/identity")

        # ── Probe A: record == wire (the audit-symmetry invariant) ────────
        FakeProvider.mode = "A"
        FakeProvider.request_count = 0  # per-probe counter: the triggers below are mode-local
        raw_a = fire_chat(
            "What's my name and where am I? Answer from what you already know.",
            session_id="prov-probe-a",
        )
        ev_a = parse_sse(raw_a)
        inj = obs_events(ev_a, "context_injected")
        if not inj:
            problems.append("probe A: no context_injected event reached the SSE stream")
        items = [it for ev in inj for it in (ev.get("items") or [])]
        if not items:
            problems.append("probe A: context_injected carried no items")
        wire_bodies = [
            "\n".join(
                str(m.get("content", ""))
                for m in b.get("messages", [])
                if isinstance(m, dict)
            )
            for b in FakeProvider.captures
        ]
        wire_all = "\n".join(wire_bodies)
        drifted = [
            it["kind"] for it in items if it.get("text") and it["text"] not in wire_all
        ]
        if drifted:
            problems.append(
                f"probe A: recorded items whose text never rode the wire: {drifted}"
            )
        kinds = {it.get("kind") for it in items}
        for required in ("environment.clock", "user_identity.stated", "environment.paths"):
            if required not in kinds:
                problems.append(f"probe A: the record lacks the {required} item (saw: {sorted(kinds)})")
        identity = next((it for it in items if it.get("kind") == "user_identity.stated"), {})
        if STATED_PLACE not in (identity.get("text") or ""):
            problems.append(
                f"probe A: the identity item does not carry the stated place: {identity.get('text')!r}"
            )
        empty_items = [it for it in items if not (it.get("text") or "").strip() or not it.get("source")]
        if empty_items:
            problems.append(f"probe A: items with empty text/source on the record: {len(empty_items)}")
        surfaces = {ev.get("surface") for ev in inj}
        ans_a = sse_answer(ev_a)
        if STATED_PLACE not in ans_a:
            problems.append(f"probe A: answer does not state the place the wire carried: {ans_a[:200]!r}")
        print(
            f"--- probe A (record == wire): {FakeProvider.request_count} provider call(s); "
            f"{len(items)} items across surfaces {sorted(s for s in surfaces if s)}; kinds: {sorted(k for k in kinds if k)}; "
            f"answer head: {ans_a[:100]!r}"
        )

        # ── Probe B: the retry ledger survives on the wire ────────────────
        FakeProvider.mode = "B"
        FakeProvider.request_count = 0
        raw_b = fire_chat(
            "Run the sleep code for me.",
            session_id="prov-probe-b",
        )
        ev_b = parse_sse(raw_b)
        tcs = tool_call_events(ev_b)
        failed_tc = next(
            (tc for tc in tcs if tc.get("status") == "failed" and tc.get("name") == "code_exec"),
            None,
        )
        if failed_tc is None:
            problems.append(
                f"probe B: no failed code_exec tool_call event on the stream (saw statuses: "
                f"{[(tc.get('name'), tc.get('status')) for tc in tcs]})"
            )
        else:
            rc = int(failed_tc.get("retry_count") or 0)
            att = failed_tc.get("retry_attempts") or []
            if rc < 1:
                problems.append(f"probe B: failed tool_call carries retry_count={rc}")
            if len(att) < 2:
                problems.append(
                    f"probe B: the attempt ledger is missing entries (got {len(att)}: {att})"
                )
            else:
                errs = " | ".join(str(a.get("error", "")) for a in att)
                if "timed out" not in errs:
                    problems.append(f"probe B: the attempts do not record the timeouts: {errs}")
            print(
                f"--- probe B (retry ledger): failed tool_call retry_count={failed_tc.get('retry_count')}; "
                f"attempts={[(a.get('attempt'), a.get('error')) for a in att]}"
            )

        # ── Probe C: the degraded death, named on the wire ────────────────
        FakeProvider.mode = "C"
        FakeProvider.request_count = 0
        raw_c = fire_chat(
            "What time is it here? Check the system.",
            session_id="prov-probe-c",
        )
        ev_c = parse_sse(raw_c)
        degraded = obs_events(ev_c, "agent_loop_degraded")
        if not degraded:
            problems.append("probe C: no agent_loop_degraded obs event reached the SSE stream")
        else:
            d = degraded[-1]
            if not d.get("terminal"):
                problems.append(f"probe C: degraded event not terminal: {d}")
            if d.get("provider_error_code") != "payment_required":
                problems.append(f"probe C: degraded event code wrong: {d.get('provider_error_code')!r}")
            if PROVIDER_NAME.split(" ")[0] not in str(d.get("provider") or ""):
                problems.append(f"probe C: degraded event provider unnamed: {d.get('provider')!r}")
        errs = [e.get("error") or {} for e in ev_c if e.get("type") == "error"]
        if not errs:
            problems.append("probe C: no canonical error object on the stream")
        else:
            err = errs[-1]
            if err.get("code") != "payment_required" or err.get("retryable"):
                problems.append(f"probe C: error envelope not honest: {err}")
        ans_c = sse_answer(ev_c)
        if "payment_required" not in ans_c:
            problems.append(f"probe C: the death note did not reach the answer text: {ans_c[:200]!r}")
        print(
            f"--- probe C (degraded death): {FakeProvider.request_count} provider call(s); "
            f"degraded={degraded[-1] if degraded else None}; answer head: {ans_c[:120]!r}"
        )

        # ── Reload: the ledger and the degraded phase survive ─────────────
        hist = api_get("/api/sessions/prov-probe-c/history")
        messages = hist.get("history") or []
        assistant = [m for m in messages if m.get("role") == "assistant"]
        if not assistant:
            problems.append("reload: no assistant message in the persisted history")
        else:
            last = assistant[-1]
            persisted_items = last.get("injectedItems") or []
            if not persisted_items:
                problems.append("reload: the persisted message carries no injectedItems ledger")
            phases = last.get("agentPhases") or []
            deg = [p for p in phases if p.get("type") == "agent_loop_degraded"]
            if not deg:
                problems.append(
                    f"reload: no agent_loop_degraded phase persisted (phases: {[p.get('type') for p in phases]})"
                )
            else:
                if "payment_required" not in str(deg[-1].get("detail") or ""):
                    problems.append(f"reload: degraded phase detail lost the code: {deg[-1]}")
            print(
                f"--- reload: persisted injectedItems={len(persisted_items)} item(s); "
                f"degraded phase present={bool(deg)}; detail={deg[-1].get('detail') if deg else None!r}"
            )

        print()
        if problems:
            print("FAIL")
            for p in problems:
                print(f"  - {p}")
            return 1
        print(
            "PASS — the audit record and the wire agree: every injected item's text rode "
            "the captured prompt verbatim; a tool that exhausted its retries kept its "
            "attempt ledger on the wire; the provider death surfaced as a terminal "
            "degraded event with the canonical error object; and the ledger + phase "
            "survive a reload"
        )
        return 0
    finally:
        kill_process_tree(proc, use_sigkill=True)
        fake.shutdown()
        kill_port(PORT)
        kill_port(FAKE_PORT)


if __name__ == "__main__":
    sys.exit(main())
