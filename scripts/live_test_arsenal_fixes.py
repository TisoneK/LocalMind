"""Live verification: the 2026-11-02 Arsenal-export fixes, on the wire.

Boots the REAL LocalMind server (port 8765, scratch LOCALMIND_HOME) against
a local OpenAI-compat fake provider, then asserts the five owner findings
on the actual SSE stream and the actual outgoing provider payloads:

  P5  objective→execution translation — the scripted provider emits a
      NATIVE system_search tool call with STRUCTURED args
      {operation: recent, limit: 1, days: 10}; the tool result the
      provider receives on the next call must show the recent operation
      ran (bounds honored), NOT the misdirected name~'1 10' filter the
      flattened "recent 1 10" string produced in the export.
  P2  evidence-grounded self-evaluation — turn 2 asks the agent about its
      own action; the provider's turn-2 payload must carry the trailing
      "Execution record" turn-context section naming system_search [done].
  P6  deterministic provider management — the turn's done payload reports
      the provider/model that ACTUALLY served (fakeprov/ps-flash), and no
      rotation happens without an explicit fallback_to.
  P4  response-vs-execution finality — the SSE closes right after the
      answer (done), and the post-turn service calls (fact extraction /
      reflection) arrive at the provider AFTER the transport closed,
      detached — the user is not held hostage to them.

One invocation, self-contained; server and fake provider killed in finally.
Artifacts: scratch/arsenal-fixes-live/
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
FAKE_PORT = 18771
HOME = REPO / "scratch" / "arsenal-fixes-live-home"
OUT = REPO / "scratch" / "arsenal-fixes-live"
SESSION = "arsenal-fixes-live"

REQUESTS: list[dict] = []
REQUEST_TIMES: list[float] = []
SSE_CLOSE_TIME: list[float] = []  # wall time the turn-1 SSE transport closed

TURN1_TOOL_ARGS = {"operation": "recent", "limit": 1, "days": 10}


class FakeProvider(BaseHTTPRequestHandler):
    """Turn 1: system_search tool call (structured args) then a text answer.
    Turn 2: a direct text answer (the explain-yourself turn).
    Later requests (the detached post-turn services): plain text."""

    def log_message(self, *a):  # silence request logging
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length)
        try:
            REQUESTS.append(json.loads(raw))
        except Exception:
            REQUESTS.append({})
        REQUEST_TIMES.append(time.monotonic())
        if self.path.endswith("/chat/completions"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()

            def sse(obj):
                self.wfile.write(f"data: {json.dumps(obj)}\n\n".encode())
                self.wfile.flush()

            n = len(REQUESTS)
            # Content-routed, not count-routed (S023): the Planner lane may
            # add a chat call BEFORE the loop's first call on either turn,
            # so "request N" is no longer a stable address. A loop call =
            # the payload carries tool schemas AND the turn is not the
            # explain-yourself turn → the structured system_search call;
            # everything else (planner lane, consults, title, fidelity,
            # post-turn services, turn 2) → the text answer.
            _last_user = ""
            for _m in reversed((REQUESTS[-1] or {}).get("messages") or []):
                if _m.get("role") == "user":
                    _last_user = str(_m.get("content") or "")
                    break
            _has_tool_result = any(
                m.get("role") == "tool" for m in (REQUESTS[-1] or {}).get("messages") or []
            )
            _turn1_loop_call = (
                (REQUESTS[-1] or {}).get("tools")
                and not _has_tool_result
                and "why did you run" not in _last_user.lower()
            )
            if _turn1_loop_call:
                # Turn 1 main call: the structured system_search tool call.
                sse({
                    "id": "af", "object": "chat.completion.chunk", "created": 1,
                    "model": "ps-flash",
                    "choices": [{
                        "index": 0, "delta": {
                            "role": "assistant",
                            "tool_calls": [{
                                "index": 0, "id": "call_1", "type": "function",
                                "function": {
                                    "name": "system_search",
                                    "arguments": json.dumps(TURN1_TOOL_ARGS),
                                },
                            }],
                        }, "finish_reason": None,
                    }],
                })
                sse({
                    "id": "af", "object": "chat.completion.chunk", "created": 1,
                    "model": "ps-flash",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                })
            elif n == 2:
                # Turn 1 answer after the tool result.
                sse({
                    "id": "af", "object": "chat.completion.chunk", "created": 1,
                    "model": "ps-flash",
                    "choices": [{"index": 0, "delta": {"content": "I checked your recent files."}, "finish_reason": None}],
                })
                sse({
                    "id": "af", "object": "chat.completion.chunk", "created": 1,
                    "model": "ps-flash",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 500, "completion_tokens": 8, "total_tokens": 508},
                })
            else:
                # Turn 2's answer + every detached post-turn service call.
                sse({
                    "id": "af", "object": "chat.completion.chunk", "created": 1,
                    "model": "ps-flash",
                    "choices": [{"index": 0, "delta": {"content": "You ran a system search for recent files."}, "finish_reason": None}],
                })
                sse({
                    "id": "af", "object": "chat.completion.chunk", "created": 1,
                    "model": "ps-flash",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 300, "completion_tokens": 10, "total_tokens": 310},
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


def fire(message: str, session: str = SESSION) -> str:
    body = urllib.parse.urlencode({"message": message, "session_id": session}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/chat",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        sse_text = resp.read().decode("utf-8", errors="replace")
    SSE_CLOSE_TIME.append(time.monotonic())
    return sse_text


def tool_messages(payload: dict) -> list[str]:
    msgs = (payload or {}).get("messages") or []
    return [str(m.get("content") or "") for m in msgs if m.get("role") == "tool"]


def trailing_context(payload: dict) -> str:
    """The injected turn-context message that carries the execution record.

    The trailing turn-context renders as a SYSTEM message (messages[1]) —
    scan every role for the section."""
    msgs = (payload or {}).get("messages") or []
    for m in msgs:
        content = str(m.get("content") or "")
        if "Execution record" in content:
            return content
    return ""


def done_payload(sse_text: str) -> dict:
    for line in reversed(sse_text.splitlines()):
        line = line.strip()
        if line.startswith("data: ") and '"done"' in line:
            try:
                obj = json.loads(line[6:])
                if isinstance(obj, dict) and obj.get("done"):
                    return obj
            except Exception:
                pass
        if line.startswith("data: [DONE]"):
            break
    return {}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    import shutil

    if HOME.exists():
        shutil.rmtree(HOME)
    HOME.mkdir(parents=True, exist_ok=True)
    (HOME / "settings.json").write_text(
        json.dumps(
            {
                "adapter": "fakeprov",
                "api_keys": {"fakeprov": "sk-local-fake-not-a-real-key"},
                "connections": [
                    {
                        "id": "fakeprov", "name": "ps-fake", "kind": "openai-compat",
                        "base_url": f"http://127.0.0.1:{FAKE_PORT}/v1",
                        "model": "ps-flash", "enabled": True,
                        "capabilities": {"streaming": True, "tool_calling": True},
                    }
                ],
            }
        )
    )

    fake = boot_fake()
    server = None
    failures: list[str] = []
    try:
        server = boot_server()
        (OUT / "sse-turn1.sse").write_text(
            fire("List the recent files on this machine", SESSION), encoding="utf-8"
        )
        turn1_sse = (OUT / "sse-turn1.sse").read_text()

        # ── P5: the structured args survived dispatch ──
        # The turn-1 LOOP call = the first captured request with tool
        # schemas (the Planner lane may precede it — count-indexing broke,
        # S023). An empty tool-result list must FAIL, not pass: the turn
        # had to actually run the search.
        _t1_tool_results = []
        for _r in REQUESTS:
            if not (_r or {}).get("tools"):
                continue
            _msgs = tool_messages(_r)
            if _msgs:
                _t1_tool_results = _msgs  # the call AFTER the tool ran carries it
                break
        t1_tool_results = _t1_tool_results
        joined = "\n".join(t1_tool_results)
        if "name~'1 10'" in joined or 'name~"1 10"' in joined:
            failures.append(
                f"P5: the tool result still carries the misdirected name filter: {joined[:300]!r}"
            )
        else:
            print("P5 OK: no name~'1 10' filter in the tool result (structured args survived)")
        if not t1_tool_results:
            failures.append("P5: turn 1 ran no tool at all — the loop call never dispatched system_search")
        elif "10 day" not in joined or "newest 1" not in joined:
            failures.append(
                "P5: the recent operation ran but the structured bounds are not visible in its output: "
                f"{joined[:300]!r}"
            )
        else:
            print("P5 OK: the recent operation ran with the structured bounds (10-day window, newest 1)")

        # ── P6: the persisted identity stamps report the actual server ──
        # The stamps ride the persisted message metrics (the export's
        # performance.{model,provider}), not the done payload's totals.
        hist = json.loads(
            urllib.request.urlopen(
                f"http://127.0.0.1:{PORT}/api/sessions/{SESSION}/history", timeout=10
            ).read().decode("utf-8")
        )
        msgs = hist.get("history") or hist.get("messages") or []
        # The history payload exposes the identity stamps under
        # performance.{model, provider} (the export's shape).
        assistant_perf = [
            (m.get("performance") or {})
            for m in msgs
            if m.get("role") == "assistant" and isinstance(m.get("performance"), dict)
        ]
        last_perf = assistant_perf[-1] if assistant_perf else {}
        prov = last_perf.get("provider")
        model = last_perf.get("model")
        if prov == "fakeprov" and model == "ps-flash":
            print("P6 OK: persisted stamps report the ACTUAL server (provider=fakeprov, model=ps-flash)")
        else:
            failures.append(f"P6: identity stamps wrong — provider={prov!r} model={model!r}")
        if last_perf.get("failover"):
            failures.append(
                f"P6: a failover record exists with no explicit fallback configured: {last_perf.get('failover')}"
            )
        else:
            print("P6 OK: no failover occurred (no silent rotation, none configured)")

        # ── P4: services run detached AFTER the SSE closes ──
        n_requests_at_close = len(REQUESTS)
        sse_close = SSE_CLOSE_TIME[-1] if SSE_CLOSE_TIME else time.monotonic()
        time.sleep(4.0)  # give the detached services their window
        post_close = [i for i, t in enumerate(REQUEST_TIMES) if t > sse_close]
        if post_close:
            print(
                f"P4 OK: {len(post_close)} provider call(s) arrived AFTER the SSE closed "
                "(post-turn services detached, not holding the transport)"
            )
        else:
            failures.append(
                "P4: no provider call after SSE close — services may still hold the turn "
                f"(requests at close: {n_requests_at_close}, total now: {len(REQUESTS)})"
            )

        # ── P2: turn 2's payload carries the execution record ──
        (OUT / "sse-turn2.sse").write_text(
            fire("Why did you run that search just now?", SESSION), encoding="utf-8"
        )
        # REQUESTS grew by the turn-2 call + any service calls; find the first
        # request AFTER the services window that carries the user message.
        turn2_idx = None
        for i in range(n_requests_at_close, len(REQUESTS)):
            body = json.dumps(REQUESTS[i])
            if "run that search" in body and "Execution record" in body:
                turn2_idx = i
                break
        ctx = trailing_context(REQUESTS[turn2_idx]) if turn2_idx is not None else ""
        if ctx and "system_search [done]" in ctx:
            print("P2 OK: turn 2's turn-context carries the Execution record naming system_search [done]")
            (OUT / "execution-record.txt").write_text(ctx, encoding="utf-8")
        else:
            failures.append(
                "P2: no 'Execution record … system_search [done]' section in turn 2's "
                f"turn-context (idx={turn2_idx}, ctx head={ctx[:200]!r})"
            )
    finally:
        if server is not None:
            kill_process_tree(server.pid)
        fake.shutdown()
        (OUT / "requests.json").write_text(
            json.dumps(
                [
                    {
                        "n": i,
                        "roles": [m.get("role") for m in (r or {}).get("messages", [])][:6],
                    }
                    for i, r in enumerate(REQUESTS)
                ],
                indent=1,
            )
        )

    print()
    if failures:
        print("FAIL:")
        for f in failures:
            print(" -", f)
        return 1
    print("ALL LIVE CHECKS PASS (deterministic fake provider)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
