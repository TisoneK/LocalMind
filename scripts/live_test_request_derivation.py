#!/usr/bin/env python3
"""LIVE verification — request derivation from the durable record (G7).

Boots the REAL LocalMind server (port 8765, scratch LOCALMIND_HOME) against
the local deterministic OpenAI-compat fake provider, with the env-gated
prompt-assembly audit ENABLED, and proves the G7 bar end to end:

  1. a loop turn that calls a tool (two iterations) persists the G7 stamps —
     the budget event's full registry composition + render fingerprint, the
     injected-items ledger's rendered sha + per-section composition, and per
     call the input-selection stage + system fingerprint;
  2. GET /api/observability/{sid}/trace/{turn}?derive=1 returns a derivation
     report whose verdicts are ALL green on the healthy record: exact char
     arithmetic for the STATIC band, the TURN message rebuilt byte-for-byte
     (or honestly `unverifiable` when the environment section is present),
     budget drop contract, render order, stage validity, sha reuse;
  3. the audit level links: with the audit running, every loop call links to
     its audit line by payload sha (byte-proof) or chars (input→wire
     transform evidence) — never `none`;
  4. the negative control: one tampered stamp in a copy of the record and
     the deriver MUST flag a failure — the checker checks;
  5. a fast-path turn derives honestly: its calls classify as `unpaired`
     (the loop surface is this increment's scope), zero failures.

Usage:
  cd backend && ../scripts/live_test_request_derivation.py
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

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(BACKEND / "src"))
from harness_common import kill_process_tree, server_popen_kwargs, venv_python

PORT = 8765
FAKE_PORT = 18796
HOME = REPO / "scratch" / "derive-home"
OUT = REPO / "scratch" / "derive"
SESSION = "derive-live"

INIT_MARKER = "initialization stage of LocalMind's parent agent"
TOOL_TURN = "Please run the sysinfo tool and tell me the platform."
FAST_TURN = "What can you do?"

REPLY = "The machine reports a test platform; everything looks normal."


class FakeProvider(BaseHTTPRequestHandler):
    """Deterministic: FIRST init classify → execute JSON (the loop turn);
    every later call → plain text (so a later conversational turn takes its
    natural routing, like the turn-trace harness's fake)."""

    tool_call_issued: ClassVar[bool] = False
    request_count: ClassVar[int] = 0
    init_calls: ClassVar[int] = 0

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
            {"id": "d1", "object": "chat.completion.chunk", "created": 1,
             "model": "derive-flash",
             "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]},
            {"id": "d1", "object": "chat.completion.chunk", "created": 1,
             "model": "derive-flash",
             "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 500, "completion_tokens": 12,
                       "total_tokens": 512}},
        ]

    def do_GET(self):
        body = json.dumps({"object": "list", "data": [{"id": "derive-flash"}]}).encode()
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
        FakeProvider.request_count += 1
        text = json.dumps(body)

        if INIT_MARKER in text:
            FakeProvider.init_calls += 1
            if FakeProvider.init_calls == 1:
                reply = json.dumps(
                    {
                        "mode": "execute",
                        "acknowledgement": "Working from the context I already hold.",
                        "response": "",
                        "objective": "Run sysinfo and report",
                        "title": "Run Sysinfo",
                        "plan": ["Call sysinfo", "Report the result"],
                        "clarifying_question": "",
                        "confidence": 0.9,
                    }
                )
                self._sse_chunks(self._text_chunks(reply))
            else:
                # later init calls: plain text, no executable plan — the turn
                # falls through to its own routing (the fast path for a
                # capabilities question), like the turn-trace harness's fake
                self._sse_chunks(self._text_chunks(REPLY))
            return

        has_tools = isinstance(body.get("tools"), list) and body["tools"]
        if has_tools and not FakeProvider.tool_call_issued:
            FakeProvider.tool_call_issued = True
            self._sse_chunks(
                [
                    {"id": "d2", "object": "chat.completion.chunk", "created": 1,
                     "model": "derive-flash",
                     "choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
                         {"index": 0, "id": "call_d1", "type": "function",
                          "function": {"name": "sysinfo",
                                       "arguments": "{\"query\": \"platform\"}"}}]},
                         "finish_reason": None}]},
                    {"id": "d2", "object": "chat.completion.chunk", "created": 1,
                     "model": "derive-flash",
                     "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
                ]
            )
            return

        self._sse_chunks(self._text_chunks(REPLY))


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
                "name": "derive-fake",
                "kind": "openai-compat",
                "base_url": f"http://127.0.0.1:{FAKE_PORT}/v1",
                "model": "derive-flash",
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
            "LOCALMIND_PROMPT_AUDIT": str(OUT / "audit.jsonl"),
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


FAST_SESSION = "derive-live-fast"


def http_post_chat(message: str, session_id: str = SESSION, timeout: int = 120) -> str:
    body = urllib.parse.urlencode(
        {"message": message, "session_id": session_id}
    ).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/chat",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode(errors="replace")


def http_get_json(path: str, timeout: int = 15) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def check(condition: bool, label: str, failures: list[str]) -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"    [{mark}] {label}")
    if not condition:
        failures.append(label)


def latest_trace_id(session_id: str = SESSION) -> str | None:
    history = http_get_json(f"/api/sessions/{session_id}/history")
    assistants = [m for m in history.get("history", []) if m.get("role") == "assistant"]
    for m in reversed(assistants):
        tid = (m.get("performance") or {}).get("traceId")
        if tid:
            return tid
    return None


def verdict_names(result: dict) -> list[tuple[str, str]]:
    out = []
    for key in ("static_checks", "turn_checks", "sha_reuse_checks"):
        for c in result.get(key) or []:
            out.append((c["check"], c["status"]))
    for call in result.get("calls") or []:
        for c in call.get("checks") or []:
            out.append((c["check"], c["status"]))
    return out


def verify_loop_turn(failures: list[str]) -> None:
    print("  loop turn (tool call + answer):")
    tid = latest_trace_id()
    check(tid is not None, "history carries a traceId", failures)
    if not tid:
        return
    trace = http_get_json(f"/api/observability/{SESSION}/trace/{tid}?derive=1")
    derivation = trace.get("derivation")
    check(derivation is not None, "trace replay carries a derivation report", failures)
    if not derivation:
        return
    summary = derivation.get("summary") or {}
    print(f"    derivation: level={derivation.get('derivation_level')} summary={summary}")
    check(summary.get("fail") == 0, "zero FAIL verdicts on the healthy record", failures)

    loop_calls = [c for c in derivation.get("calls") or [] if c.get("surface") == "loop"]
    check(len(loop_calls) >= 2, f"loop surface derived for >=2 calls ({len(loop_calls)})", failures)
    for call in loop_calls:
        statuses = {c["check"]: c["status"] for c in call.get("checks") or []}
        for name in ("fingerprint_present", "assembly_paired", "stage_valid", "system_chars_arithmetic"):
            if statuses.get(name) != "pass":
                check(False, f"call {call.get('call_id')} check {name}={statuses.get(name)}", failures)
    check(all(c["surface"] != "loop" or c.get("iteration") is not None for c in loop_calls),
          "every loop call carries its iteration", failures)

    # audit level: with the audit running, loop calls must link
    links = [ (c.get("audit") or {}).get("link") for c in loop_calls ]
    check(derivation.get("derivation_level") == "audit",
          "derivation runs at the audit level (audit lines matched)", failures)
    check(all(l in ("sha", "chars") for l in links),
          f"every loop call links to its audit line ({links})", failures)

    # static + turn verdicts green
    for key in ("static_checks", "turn_checks", "sha_reuse_checks"):
        bad = [c for c in derivation.get(key) or [] if c["status"] == "fail"]
        check(not bad, f"{key}: no failures ({[c['check'] for c in bad]})", failures)
    rebuilt = next((c for c in derivation.get("turn_checks") or [] if c["check"] == "turn_message_rebuilt"), None)
    check(rebuilt is not None and rebuilt["status"] in ("pass", "unverifiable"),
          f"turn message rebuilt ({rebuilt['status'] if rebuilt else 'missing'})", failures)

    # the stamps are on the raw stream too
    rtypes = [e["type"] for e in trace.get("events", [])]
    check("relevance_budget" in rtypes, "record carries the budget stamp", failures)
    check("context_injected" in rtypes, "record carries the injected-items ledger", failures)

    # audit JSONL exists and lines carry the linkage fingerprint
    audit_path = OUT / "audit.jsonl"
    check(audit_path.exists(), "prompt-assembly audit file written", failures)
    if audit_path.exists():
        lines = [json.loads(l) for l in audit_path.read_text().splitlines() if l.strip()]
        check(bool(lines) and all("payload_sha" in l for l in lines),
              f"audit lines carry the payload fingerprint ({len(lines)} lines)", failures)

    # negative control: the checker checks. The staged call's recorded size
    # is fully constrained (its prefix was pinned by the first call), so a
    # drifted size MUST break the arithmetic.
    import copy
    sys.path.insert(0, str(BACKEND / "src"))
    from core.agent.trace_derive import derive_from_trace_payload

    tampered = copy.deepcopy(trace)
    done = False
    for e in tampered["events"]:
        if (
            e["type"] == "context_assembly_completed"
            and (e["data"] or {}).get("system_stage") == "tool_result"
            and (e["data"] or {}).get("system_chars") is not None
        ):
            e["data"]["system_chars"] = int(e["data"]["system_chars"]) + 5
            done = True
            break
    if not done:  # single-iteration fallback: tamper any assembly size
        for e in tampered["events"]:
            if e["type"] == "context_assembly_completed" and (e["data"] or {}).get("system_chars") is not None:
                e["data"]["system_chars"] = int(e["data"]["system_chars"]) + 7
                break
    bad = derive_from_trace_payload(tampered)
    check((bad.get("summary") or {}).get("fail", 0) >= 1,
          "negative control: a tampered stamp is flagged", failures)


def verify_fast_turn(failures: list[str]) -> None:
    print("  fast-path turn (fresh session — no carried objective):")
    tid = latest_trace_id(FAST_SESSION)
    check(tid is not None, "history carries a traceId", failures)
    if not tid:
        return
    trace = http_get_json(f"/api/observability/{FAST_SESSION}/trace/{tid}?derive=1")
    d = trace.get("derivation")
    check(d is not None, "derivation report present", failures)
    if not d:
        return
    summary = d.get("summary") or {}
    print(f"    derivation: level={d.get('derivation_level')} summary={summary}")
    check(summary.get("fail") == 0, "zero FAIL verdicts", failures)
    unpaired = [c for c in d.get("calls") or [] if c.get("surface") == "unpaired"]
    check(len(unpaired) >= 1,
          "fast-path call(s) derive honestly as `unpaired` on the loop surface", failures)


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
        print(f"server up on {PORT} (fake provider on {FAKE_PORT}, audit enabled)")
        for message, session in ((TOOL_TURN, SESSION), (FAST_TURN, FAST_SESSION)):
            raw = http_post_chat(message, session_id=session)
            (OUT / "last.sse.txt").write_text(raw)
            time.sleep(1.5)  # let the final drain + persist settle
            if message == TOOL_TURN:
                verify_loop_turn(failures)
            else:
                verify_fast_turn(failures)
        if failures:
            print(f"\nRESULT: FAIL — {len(failures)} check(s):")
            for f in failures:
                print(f"  - {f}")
            return 1
        print("\nRESULT: PASS — the durable record derives every loop call's payload.")
        return 0
    finally:
        if server is not None:
            kill_process_tree(server.pid)
        fake.shutdown()


if __name__ == "__main__":
    sys.exit(main())
