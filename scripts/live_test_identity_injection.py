#!/usr/bin/env python3
"""Live verification: identity context injection (roadmap §U item 2,
docs/reference-harness-gap-inventory.md).

The guarantee under test: the model is told WHO and WHERE the user is
BEFORE it acts — user-stated facts ride every chat path as labeled
context, and facts the user never stated are DECLARED ABSENT with a
clarify-don't-guess contract (never inferred from tool results).

No provider credential exists in this sandbox, so the proof is the wire:
a local fake OpenAI-compatible provider CAPTURES the exact request bodies
the server sends, and composes its replies ONLY from what those bodies
actually carried. If the identity block were missing from the wire, the
reply could not contain the facts — the answer text is therefore derived
evidence of injection, not a canned string.

Three probes against the REAL server on isolated port 8765 + scratch
LOCALMIND_HOME:

  Setup  : POST /api/settings/identity (Amani / Nairobi, Kenya) persists
           and hot-applies; GET /api/settings reflects it.
  Probe A (stated facts, auto mode): "What's my name?" — the fast path's
           single system prompt must carry the stated facts.
  Probe B (agent mode): "Where am I? Answer from what you already know
           about me." — the loop's env context must carry the About line,
           the answer must state the place, and the turn must complete
           with ZERO tool calls (the acceptance gate accepts an identity
           answer grounded in the injected block instead of forcing a
           tool — the exact 12:45 failure shape, now answered honestly).
  Probe C (nothing stated): identity cleared; "What's my name?" — the
           wire must carry the declared-absent form and the honest
           ask-back must be accepted, not force-tooled.

PASS rules:
  1. setup round-trip: POST then GET agree on both facts;
  2. every probe's captured wire contains the identity line for its state;
  3. probe B's wire also carries the zone-named clock (UTC offset + zone
     name in one parenthesis);
  4. every probe's SSE answer states what the wire carried (or asks back
     for probe C) with NO error event and NO forced-tool narration;
  5. probe B and C turns complete as accepted answers (no failure deck).

Usage:
  cd backend && ../scripts/live_test_identity_injection.py
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
HOME = SCRATCH / "identityhome"
PORT = 8765
FAKE_PORT = 18791

PROVIDER_NAME = "WireProof Provider (identity harness)"
STATED_NAME = "Amani"
STATED_PLACE = "Nairobi, Kenya"

INIT_MARKER = "initialization stage of LocalMind's parent agent"


def extract_facts(body: dict) -> dict:
    """Pull the identity facts OUT of a captured request body — the reply
    may use nothing the wire did not carry."""
    contents = "\n".join(
        str(m.get("content", "")) for m in body.get("messages", []) if isinstance(m, dict)
    )
    name_m = re.search(r'name "([^"]+)"', contents) or re.search(
        r"- Name: ([^\n(]+?)\s*\(", contents
    )
    place_m = re.search(r'place "([^"]+)"', contents) or re.search(
        r"- Place: ([^\n(]+?)\s*\(", contents
    )
    time_m = re.search(r"Current time: (\d{2}:\d{2})", contents)
    clock_line_m = re.search(r"- Current time: [^\n]*", contents)
    # The zone NAME rides the offset in one parenthesis. The machine
    # reports its own truth: this sandbox says Etc/UTC, the owner's machine
    # says Africa/Nairobi — the contract is that a name IS present, not
    # which one.
    zone_m = re.search(r"Current time: \d{2}:\d{2} \(UTC[+-]\d{2}:\d{2}, ([^)]+)\)", contents)
    absent = "name and place never stated" in contents
    return {
        "name": name_m.group(1).strip() if name_m else "",
        "place": place_m.group(1).strip() if place_m else "",
        "time": time_m.group(1) if time_m else "",
        "clock_line": clock_line_m.group(0) if clock_line_m else "",
        "zone_name": zone_m.group(1).strip() if zone_m else "",
        "zone_named": bool(zone_m),
        "absent": absent,
        "about_block": "About the user" in contents,
    }


class FakeProvider(BaseHTTPRequestHandler):
    """Captures every /chat/completions body (the wire under test). The
    init/classify call gets a valid execute-plan JSON so the turn reaches
    the real loop iterations; every other call gets a reply composed ONLY
    from the facts the captured wire carried."""

    request_count = 0
    captures: ClassVar[list[dict]] = []
    probe = "A"

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

        text = json.dumps(body)
        if INIT_MARKER in text:
            # Classify-only call: force the execute tier so the turn runs
            # real loop iterations (where the full env context rides).
            reply = json.dumps(
                {
                    "mode": "execute",
                    "acknowledgement": "Checking what I know about you.",
                    "response": "",
                    "objective": "Answer the user's identity question from known context",
                    "title": "Answer Identity Question",
                    "plan": [
                        "Answer the user's identity question from the context you already have"
                    ],
                    "clarifying_question": "",
                    "confidence": 0.9,
                }
            )
        else:
            facts = extract_facts(body)
            p = FakeProvider.probe
            if p == "A":
                if facts["name"] and facts["place"]:
                    reply = (
                        f"Your name is {facts['name']} and you are in "
                        f"{facts['place']} — you told me yourself."
                    )
                else:
                    reply = f"WIRE-MISS-A: name={facts['name']!r} place={facts['place']!r}"
            elif p == "B":
                if facts["place"]:
                    reply = (
                        f"You are in {facts['place']} — you told me in Settings. "
                        f"(clock on my side reads {facts['time']}, zone "
                        f"{'named' if facts['zone_named'] else 'UNNAMED'}.)"
                    )
                else:
                    reply = f"WIRE-MISS-B: place={facts['place']!r}"
            else:  # C — nothing stated; the honest ask-back
                if facts["absent"]:
                    reply = (
                        "You haven't told me your name yet — what should I call you?"
                    )
                else:
                    reply = f"WIRE-MISS-C: absent={facts['absent']!r}"

        chunks = [
            {"id": "c1", "object": "chat.completion.chunk", "created": 1,
             "model": "wireproof-flash",
             "choices": [{"index": 0, "delta": {"role": "assistant", "content": reply},
                          "finish_reason": None}]},
            {"id": "c1", "object": "chat.completion.chunk", "created": 1,
             "model": "wireproof-flash",
             "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ]
        for c in chunks:
            self._sse(c)
        body = b"data: [DONE]\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def boot_fake() -> ThreadingHTTPServer:
    FakeProvider.request_count = 0
    FakeProvider.captures = []
    FakeProvider.probe = "A"
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
        # Deliberately NO user_name / user_place here: the setup step below
        # states them through the REAL endpoint, proving the write path.
    }
    (HOME / "settings.json").write_text(json.dumps(settings, indent=2))


def boot_server(log_file: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env.update(
        {
            "LOCALMIND_PORT": str(PORT),
            "LOCALMIND_HOME": str(HOME),
            "LOCALMIND_ADAPTER": "fakeprov",
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


def fire_chat(message: str, session_id: str, timeout: int = 180, intent_hint: str = "") -> str:
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if intent_hint:
        # A non-chat client hint suppresses the trivial/conversational fast
        # path (agent_runtime's eligibility gate) so the turn runs the REAL
        # agent loop — the surface whose wire this probe must inspect.
        headers["X-LocalMind-Intent"] = intent_hint
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


def sse_errors(events: list[dict]) -> list[dict]:
    return [e.get("error") or {} for e in events if e.get("type") == "error"]


def main() -> int:
    problems: list[str] = []
    kill_port(PORT)
    kill_port(FAKE_PORT)
    fake = boot_fake()
    write_settings()
    log = SCRATCH / "identityhome-server.log"
    proc = None
    try:
        proc = boot_server(log)

        # ── Setup: state the facts through the REAL endpoint ──────────────
        posted = api_post(
            "/api/settings/identity",
            {"user_name": STATED_NAME, "user_place": STATED_PLACE},
        )
        got = api_get("/api/settings")
        if posted.get("user_name") != STATED_NAME or posted.get("user_place") != STATED_PLACE:
            problems.append(f"setup: POST response wrong: {posted}")
        if got.get("user_name") != STATED_NAME or got.get("user_place") != STATED_PLACE:
            problems.append(
                f"setup: GET /api/settings does not reflect the stated facts "
                f"(name={got.get('user_name')!r}, place={got.get('user_place')!r})"
            )
        print(f"--- setup: identity stated via POST /api/settings/identity -> {posted['message']}")

        # ── Probe A: stated facts on the fast path (auto mode) ────────────
        FakeProvider.probe = "A"
        raw_a = fire_chat("What's my name?", session_id="identity-probe-a")
        ev_a = parse_sse(raw_a)
        ans_a = sse_answer(ev_a)
        wire_a = [extract_facts(b) for b in FakeProvider.captures]
        if not any(w["name"] == STATED_NAME and w["place"] == STATED_PLACE for w in wire_a):
            problems.append(
                "probe A: no captured request carried the stated name+place "
                f"(saw: {[(w['name'], w['place']) for w in wire_a]})"
            )
        if sse_errors(ev_a):
            problems.append(f"probe A: error events on the stream: {sse_errors(ev_a)[-1]}")
        if STATED_NAME not in ans_a or STATED_PLACE not in ans_a:
            problems.append(f"probe A: answer does not state the facts the wire carried: {ans_a[:200]!r}")
        print(f"--- probe A (auto mode): {FakeProvider.request_count} provider call(s); answer: {ans_a[:160]!r}")

        # ── Probe B: the loop path, zero-tool acceptance ──────────────────
        before_b = FakeProvider.request_count
        FakeProvider.probe = "B"
        api_post("/api/settings/chat-mode", {"chat_mode": "agent"})
        raw_b = fire_chat(
            "Where am I? Answer from what you already know about me.",
            session_id="identity-probe-b",
            intent_hint="tool",
        )
        ev_b = parse_sse(raw_b)
        ans_b = sse_answer(ev_b)
        wire_b = [extract_facts(b) for b in FakeProvider.captures[before_b:]]
        if not any(w["about_block"] and w["place"] == STATED_PLACE for w in wire_b):
            problems.append(
                "probe B: no loop request carried the About line with the stated place "
                f"(saw: {[(w['about_block'], w['place']) for w in wire_b]})"
            )
        if not any(w["zone_named"] for w in wire_b):
            problems.append(
                "probe B: no captured request carried a zone-named clock "
                "(Current time … (UTC±HH:MM, <zone>))"
            )
        if sse_errors(ev_b):
            problems.append(f"probe B: error events on the stream: {sse_errors(ev_b)[-1]}")
        if STATED_PLACE not in ans_b:
            problems.append(f"probe B: answer does not state the stated place: {ans_b[:200]!r}")
        if "tool_call" in ans_b or "emit the tool" in ans_b.lower():
            problems.append(f"probe B: answer carries forced-tool narration: {ans_b[:200]!r}")
        b_calls = FakeProvider.request_count - before_b
        _zb = next((w["zone_name"] for w in wire_b if w["zone_name"]), "")
        _cl = next((w["clock_line"] for w in wire_b if w["clock_line"]), "")
        print(f"--- probe B (agent mode): {b_calls} provider call(s); clock line on the wire: {_cl!r}; answer: {ans_b[:140]!r}")

        # ── Probe C: nothing stated → declared absent, honest ask-back ────
        before_c = FakeProvider.request_count
        FakeProvider.probe = "C"
        api_post("/api/settings/identity", {"user_name": "", "user_place": ""})
        raw_c = fire_chat(
            "What's my name?", session_id="identity-probe-c", intent_hint="tool"
        )
        ev_c = parse_sse(raw_c)
        ans_c = sse_answer(ev_c)
        wire_c = [extract_facts(b) for b in FakeProvider.captures[before_c:]]
        if not any(w["absent"] for w in wire_c):
            problems.append(
                "probe C: no captured request carried the declared-absent form "
                "after the clear"
            )
        if sse_errors(ev_c):
            problems.append(f"probe C: error events on the stream: {sse_errors(ev_c)[-1]}")
        if "?" not in ans_c:
            problems.append(
                f"probe C: the honest ask-back did not reach the user: {ans_c[:200]!r}"
            )
        c_calls = FakeProvider.request_count - before_c
        print(f"--- probe C (nothing stated): {c_calls} provider call(s); answer: {ans_c[:160]!r}")

        print()
        if problems:
            print("FAIL")
            for p in problems:
                print(f"  - {p}")
            return 1
        print(
            "PASS — the model is told who and where the user is before it acts: "
            "stated facts on the wire (fast path + loop), zone-named clock, "
            "absent facts declared absent, honest ask-back accepted with zero tools"
        )
        return 0
    finally:
        kill_process_tree(proc, use_sigkill=True)
        fake.shutdown()
        kill_port(PORT)
        kill_port(FAKE_PORT)


if __name__ == "__main__":
    sys.exit(main())
