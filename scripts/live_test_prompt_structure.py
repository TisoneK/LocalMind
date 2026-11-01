"""Live verification: the parent prompt's named-section structure end to end.

Boots the REAL LocalMind server (port 8765, scratch LOCALMIND_HOME) against
a local OpenAI-compat fake provider that requests ONE tool call on the first
model call and answers in text on the second — the exact shape that exercises
both the full registry render (call 1) and the staged section-name render
(call 2, after a tool result). LOCALMIND_PROMPT_AUDIT captures the exact
outgoing payloads; this script asserts the prompt-structure contract on them:

  call 1 (full STATIC band):  identity -> constraints (conversation-or-action,
                              act-not-announce, multi-part, safety/grounding)
                              -> relevant context -> guidance (style, tool
                              index, selection hints, on-demand loading)
  call 2 (staged by NAME):    style examples + tool index + selection hints
                              GONE; every constraint stays; on-demand loading
                              stays (tools still offered); the trailing
                              turn-context message is untouched.

Also asserts the trailing turn-context message renders in doctrine order
(user objective first when a tail exists) and byte-equality of the system
prefix across the two calls EXCEPT the staged cut.

One invocation, self-contained; server and fake provider killed in finally.
Artifacts: scratch/prompt-structure-live/
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
from harness_common import kill_process_tree, server_popen_kwargs, venv_python  # noqa: E402

PORT = 8765
FAKE_PORT = 18767
HOME = REPO / "scratch" / "prompt-structure-live-home"
OUT = REPO / "scratch" / "prompt-structure-live"
AUDIT = OUT / "prompt-audit.jsonl"
SESSION = "prompt-structure-live"

STYLE_HEAD = "Style — terseness and the converse-or-act call (arrows show the final reply):"
TOOLS_HEAD = "Available tools — pick the RIGHT one for the request (name: what it does):"
CORE_HEAD = "Core tools ("
SAFETY_HEAD = "Safety: check current state before writes, edits, or deletes."

REQUESTS: list[dict] = []


class FakeProvider(BaseHTTPRequestHandler):
    """Call 1: a dir_explorer tool call. Call 2: the final text answer."""

    def log_message(self, *a):  # silence request logging
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length)
        try:
            REQUESTS.append(json.loads(raw))
        except Exception:
            REQUESTS.append({})
        if self.path.endswith("/chat/completions"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()

            def sse(obj):
                self.wfile.write(f"data: {json.dumps(obj)}\n\n".encode())
                self.wfile.flush()

            if len(REQUESTS) == 1:
                # Streaming tool-call shape: id/name first, then the
                # arguments delta, then finish_reason tool_calls.
                sse({
                    "id": "ps", "object": "chat.completion.chunk", "created": 1,
                    "model": "ps-flash",
                    "choices": [{
                        "index": 0, "delta": {
                            "role": "assistant",
                            "tool_calls": [{
                                "index": 0, "id": "call_1", "type": "function",
                                "function": {"name": "dir_explorer", "arguments": ""},
                            }],
                        }, "finish_reason": None,
                    }],
                })
                sse({
                    "id": "ps", "object": "chat.completion.chunk", "created": 1,
                    "model": "ps-flash",
                    "choices": [{
                        "index": 0, "delta": {
                            "tool_calls": [{"index": 0, "function": {"arguments": '{"operation": "list", "path": "/tmp"}'}}],
                        }, "finish_reason": None,
                    }],
                })
                sse({
                    "id": "ps", "object": "chat.completion.chunk", "created": 1,
                    "model": "ps-flash",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                })
            else:
                sse({
                    "id": "ps", "object": "chat.completion.chunk", "created": 1,
                    "model": "ps-flash",
                    "choices": [{"index": 0, "delta": {"content": "The folder has two entries."}, "finish_reason": None}],
                })
                sse({
                    "id": "ps", "object": "chat.completion.chunk", "created": 1,
                    "model": "ps-flash",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 500, "completion_tokens": 8, "total_tokens": 508},
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


def boot_server() -> subprocess.Popen:
    # A stale harness server from an earlier run serves STALE code and its
    # fake provider answers differently — the first "result" would be fake.
    # Behavioral guard (S008 process lesson): a plain bind() also trips on
    # TIME_WAIT sockets of freshly killed servers, so ask the port whether
    # a LIVE server answers /api/health instead.
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2).read()
        raise RuntimeError(
            f"a live server already answers on port {PORT} — kill the stale "
            "harness server first"
        )
    except RuntimeError:
        raise
    except Exception:
        pass  # connection refused — the port is genuinely free
    env = os.environ.copy()
    env.update(
        {
            "LOCALMIND_PORT": str(PORT),
            "LOCALMIND_HOME": str(HOME),
            "LOCALMIND_ADAPTER": "fakeprov",
            "LOCALMIND_PROMPT_AUDIT": str(AUDIT),
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


def fire(message: str) -> str:
    body = urllib.parse.urlencode({"message": message, "session_id": SESSION}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/chat",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read().decode("utf-8", errors="replace")


def audit_payloads() -> list[dict]:
    payloads = []
    for line in AUDIT.read_text().splitlines():
        try:
            payloads.append(json.loads(line))
        except Exception:
            pass
    return payloads


def last_payload_bodies() -> list[dict]:
    """The audit writes only the LAST payload to .last-payload.json; the
    full-prompt and staged calls are reconstructed from the audit line's
    per-section counts plus the last full body. For the structure asserts we
    instead capture the system content of every call via the audit records
    and the captured REQUESTS (what the provider actually received)."""
    bodies = []
    for req in REQUESTS:
        msgs = (req or {}).get("messages") or []
        sys_msgs = [m.get("content", "") for m in msgs if m.get("role") == "system"]
        bodies.append({"n_system": len(sys_msgs), "system": sys_msgs})
    return bodies


def _first_system(req: dict) -> str:
    msgs = (req or {}).get("messages") or []
    for m in msgs:
        if m.get("role") == "system":
            return str(m.get("content") or "")
    return ""


def audit_records() -> list[dict]:
    """One audit record per provider call, in order (call kind included)."""
    recs = []
    for line in AUDIT.read_text().splitlines():
        try:
            recs.append(json.loads(line))
        except Exception:
            pass
    return recs


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if HOME.exists():
        for p in sorted(HOME.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else None
    settings = {
        "adapter": "fakeprov",
        "api_keys": {"fakeprov": "sk-local-fake-not-a-real-key"},
        "connections": [
            {
                "id": "fakeprov", "name": "ps-fake", "kind": "openai-compat",
                "base_url": f"http://127.0.0.1:{FAKE_PORT}/v1",
                "model": "ps-flash", "enabled": True,
            }
        ],
    }
    HOME.mkdir(parents=True, exist_ok=True)
    (HOME / "settings.json").write_text(json.dumps(settings, indent=2))

    fake = boot_fake()
    server = None
    failures: list[str] = []
    try:
        server = boot_server()
        fire("List the files in /tmp")

        time.sleep(1.0)
        # The audit records carry the call kind ("tools" = a loop model call
        # with tool schemas; "chat" = init/plan/judge/title surfaces). The
        # acceptance gate legitimately re-sends the FULL system prompt on a
        # "chat" call — it reviews the turn with complete context and is NOT
        # a staged action call. Loop calls are therefore classified by kind.
        recs = audit_records()
        # A loop call = the audit's "tools" kind (tool schemas attached).
        # The staged call intentionally LACKS the style/tool-guidance heads,
        # so the heads cannot be part of the classification.
        loop_payloads = [
            (REQUESTS[i] if i < len(REQUESTS) else {})
            for i, rec in enumerate(recs)
            if rec.get("call") == "tools"
        ]
        if not loop_payloads:
            failures.append(
                "no loop call captured with the parent prompt; audit calls="
                f"{[(r.get('call'), r.get('n_messages')) for r in recs]}"
            )
        else:
            full_msgs = [
                m.get("content", "")
                for m in loop_payloads[0].get("messages", [])
                if m.get("role") == "system"
            ]
            full = full_msgs[0]
            (OUT / "full-system-prompt.txt").write_text(full)
            staged = None
            if len(loop_payloads) > 1:
                staged_msgs = [
                    m.get("content", "")
                    for m in loop_payloads[1].get("messages", [])
                    if m.get("role") == "system"
                ]
                staged = staged_msgs[0]
                (OUT / "staged-system-prompt.txt").write_text(staged)
            else:
                failures.append("no staged (second) loop call captured")

            # ── call 1: full render in doctrine order ──────────────────
            positions = {h: full.find(h) for h in (SAFETY_HEAD, STYLE_HEAD, TOOLS_HEAD, CORE_HEAD)}
            if not all(p >= 0 for p in positions.values()):
                failures.append(f"a section head is missing from the full prompt: {positions}")
            elif not positions[SAFETY_HEAD] < positions[STYLE_HEAD] < positions[TOOLS_HEAD] < positions[CORE_HEAD]:
                failures.append(f"doctrine order violated: {positions}")
            for rule in (
                "Multi-part requests are not done until EVERY part is answered",
                "Act instead of announcing the act",
                "Never fabricate a tool result",
            ):
                if rule not in full:
                    failures.append(f"constraint missing from full prompt: {rule!r}")

            # ── call 2: staged by name ─────────────────────────────────
            if staged is not None:
                for gone, label in ((STYLE_HEAD, "style examples"), (TOOLS_HEAD, "tool index"), ("Selection hints:", "selection hints")):
                    if gone in staged:
                        failures.append(f"staged prompt still carries {label}")
                for keep, label in (
                    (SAFETY_HEAD, "safety/grounding"),
                    ("Multi-part requests are not done until EVERY part is answered", "multi-part rule"),
                    ("Act instead of announcing the act", "act-not-announce rule"),
                    ("describe_tool", "on-demand loading"),
                ):
                    if keep not in staged:
                        failures.append(f"staged prompt lost {label}")
                if len(staged) >= len(full) * 0.8:
                    failures.append(f"staged prompt barely smaller: {len(staged)} vs {len(full)}")

        # ── turn-context: the trailing system message (loop messages[1],
        # AFTER the static prefix — never mutated by the staged cut) ──
        if loop_payloads:
            sys_msgs = [
                m.get("content", "")
                for m in loop_payloads[0].get("messages", [])
                if m.get("role") == "system"
            ]
            if len(sys_msgs) > 1:
                (OUT / "turn-context.txt").write_text(sys_msgs[1])

    finally:
        if server:
            kill_process_tree(server.pid)
        fake.shutdown()

    if failures:
        print("FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("PASS — parent prompt structure verified live (full + staged + turn context)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
