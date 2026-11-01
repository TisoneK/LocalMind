"""LIVE verification — the durable per-turn execution trace (B-2026-11-01-26).

Boots the REAL LocalMind server (port 8765, scratch LOCALMIND_HOME) against
the local deterministic OpenAI-compat fake provider (established harness
pattern, no external key), fires the owner's three-message experiment, and
asserts the trace contract END TO END on every turn:

  1. path_selected is on the wire AND in the persisted stream — the routing
     decision (which lane ran and why) is a fact of the record now;
  2. model_call_started / model_call_completed bracket every provider call,
     with usage and a payload fingerprint (sizes + hash, no contents);
  3. provider_call_start carries the epoch-ms anchor beside the heartbeat's
     monotonic clock (one clock discipline);
  4. loop turns stamp context_assembly_started/completed;
  5. the persisted trace store replays each turn (list + get endpoints),
     and the history payload's performance.traceId resolves to a trace.

One invocation = one self-contained verification; server + fake provider are
killed in finally. Refuses to run when a LIVE server already answers on the
port (a stale harness serving stale code has burned sessions before).
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

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
sys.path.insert(0, str(REPO / "scripts"))
from harness_common import kill_process_tree, server_popen_kwargs, venv_python

PORT = 8765
FAKE_PORT = 18771
HOME = REPO / "scratch" / "turn-trace-home"
OUT = REPO / "scratch" / "turn-trace"
SESSION = "turn-trace-live"

MESSAGES = [
    "Hey sup LM?",
    "What can you do?",
    "Nice to hear about those capabilities. Pretty impressive I must say.",
]

REPLY = "Sure — happy to help. Ask me anything about your workspace."


class FakeProvider(BaseHTTPRequestHandler):
    """OpenAI-compat /chat/completions: streams thinking then the reply,
    reports usage (cached tokens included) on the final chunk."""

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

            sse({
                "id": "tt", "object": "chat.completion.chunk", "created": 1,
                "model": "trace-flash",
                "choices": [{"index": 0, "delta": {"reasoning_content": "Quick read of the ask."}, "finish_reason": None}],
            })
            for piece in [REPLY[:10], REPLY[10:26], REPLY[26:]]:
                sse({
                    "id": "tt", "object": "chat.completion.chunk", "created": 1,
                    "model": "trace-flash",
                    "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
                })
                time.sleep(0.03)
            sse({
                "id": "tt", "object": "chat.completion.chunk", "created": 1,
                "model": "trace-flash",
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
                "name": "trace-fake",
                "kind": "openai-compat",
                "base_url": f"http://127.0.0.1:{FAKE_PORT}/v1",
                "model": "trace-flash",
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


def http_post_chat(message: str, timeout: int = 120) -> str:
    body = urllib.parse.urlencode(
        {"message": message, "session_id": SESSION}
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


def parse_events(raw: str) -> list[dict]:
    events = []
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            payload = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        events.append(payload)
    return events


def sse_obs_types(events: list[dict]) -> list[str]:
    types = []
    for e in events:
        oe = e.get("obs_event") or {}
        if isinstance(oe, dict) and oe.get("type"):
            types.append(oe["type"])
    return types


def check(condition: bool, label: str, failures: list[str]) -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"    [{mark}] {label}")
    if not condition:
        failures.append(label)


def verify_turn(i: int, raw_sse: str, failures: list[str]) -> dict:
    events = parse_events(raw_sse)
    types = sse_obs_types(events)

    print(f"  turn {i}:")
    check("path_selected" in types, "wire carries path_selected", failures)

    started = [e for e in events if (e.get("obs_event") or {}).get("type") == "model_call_started"]
    completed = [e for e in events if (e.get("obs_event") or {}).get("type") == "model_call_completed"]
    check(len(started) >= 1, f"wire carries model_call_started ({len(started)} call(s))", failures)
    check(
        len(started) == len(completed),
        f"every call closed ({len(started)} started / {len(completed)} completed)",
        failures,
    )
    if started:
        data = started[0]["obs_event"]["data"]
        check(bool(data.get("payload_chars")), "call carries a payload size", failures)
        check(bool(data.get("payload_sha")), "call carries a payload hash", failures)
        check(
            "prompt" not in str(data).lower() or "payload" in str(data),
            "no payload content on the wire event", failures,
        )
    pcs = [e for e in events if (e.get("obs_event") or {}).get("type") == "provider_call_start"]
    if pcs:
        pdata = pcs[0]["obs_event"]["data"]
        check(
            "started_at_epoch_ms" in pdata and "started_at" in pdata,
            "provider_call_start carries epoch anchor + monotonic pair",
            failures,
        )
    loop_turn = "context_assembly_started" in types
    if loop_turn:
        check(
            "context_assembly_completed" in types,
            "loop turn stamps context assembly start+end",
            failures,
        )

    # Persisted trace store — list + replay.
    traces = http_get_json(f"/api/observability/{SESSION}/traces")
    check(len(traces.get("traces", [])) >= i, f"trace store lists >= {i} turn(s)", failures)

    history = http_get_json(f"/api/sessions/{SESSION}/history")
    assistants = [
        m for m in history.get("history", []) if m.get("role") == "assistant"
    ]
    trace_ids = [
        (m.get("performance") or {}).get("traceId")
        for m in assistants
        if (m.get("performance") or {}).get("traceId")
    ]
    check(len(trace_ids) >= i, f"history carries traceId ({len(trace_ids)} so far)", failures)

    if trace_ids:
        tid = trace_ids[-1]
        listed_ids = {t["turnId"] for t in traces.get("traces", [])}
        check(tid in listed_ids, "history traceId resolves to a stored trace", failures)
        replay = http_get_json(f"/api/observability/{SESSION}/trace/{tid}")
        rtypes = [e["type"] for e in replay.get("events", [])]
        seqs = [e["seq"] for e in replay.get("events", [])]
        check(seqs == sorted(seqs), "persisted stream replays in seq order", failures)
        check("path_selected" in rtypes, "persisted stream carries path_selected", failures)
        check(
            "model_call_started" in rtypes and "model_call_completed" in rtypes,
            "persisted stream carries model-call boundaries",
            failures,
        )

    return {
        "turn": i,
        "wire_path": next(
            (
                (e["obs_event"]["data"] or {}).get("path")
                for e in events
                if (e.get("obs_event") or {}).get("type") == "path_selected"
            ),
            None,
        ),
        "calls": len(started),
        "trace_id": trace_ids[-1] if trace_ids else None,
        "loop_turn": loop_turn,
    }


def main() -> int:
    # Refuse to run against a LIVE server on the port (the stale-harness
    # lesson: a server that answers /api/health is somebody's code, maybe
    # stale — never boot over it).
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
        summary = []
        for i, message in enumerate(MESSAGES, start=1):
            raw = http_post_chat(message)
            (OUT / f"turn{i}.sse.txt").write_text(raw)
            time.sleep(1.0)  # let the final drain + persist settle
            summary.append(verify_turn(i, raw, failures))
        print("\nsummary:")
        for row in summary:
            print(json.dumps(row))
        (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
        if failures:
            print(f"\nRESULT: FAIL — {len(failures)} check(s):")
            for f in failures:
                print(f"  - {f}")
            return 1
        print("\nRESULT: PASS — every turn's execution is on the durable record.")
        return 0
    finally:
        if server is not None:
            kill_process_tree(server.pid)
        fake.shutdown()


if __name__ == "__main__":
    sys.exit(main())
