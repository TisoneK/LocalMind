"""Live verification: the model's own plan rewrite on the wire (S024).

B-2026-11-02-2 remainder. Before this, a mid-turn todo_write call silently
full-replaced the Todos panel (todo_cleared + one todo_created per item):
closed rows vanished, no revision diff landed, and the acceptance contract
ignored the rewrite. This harness boots the REAL server (port 8765, scratch
LOCALMIND_HOME) against a local fake provider and asserts, on the actual SSE
stream:

  RW1  the Planner lane draws the plan (todo_cleared + plan-0/plan-1 rows
       with the RAM outcome carried) — exactly ONE todo_cleared on the turn;
  RW2  the model's todo_write rewrite DIFFS: plan-1 ("Prepare the answer")
       retires with a reason on the row, the rewritten work ("Note the
       available memory too") appends as plan-2 CARRYING its expected_outcome,
       plan-0 updates in place — and no second todo_cleared ever fires;
  RW3  todo_revised {added: 1, retired: 1} lands on the wire (the generic
       obs_event wrapper — the panel derives its revision marker from the
       retired rows);
  RW4  the revised contract gates the close: the available-memory outcome
       joins the acceptance criteria and the turn closes on the WORK's
       evidence (the honest echo of the real sysinfo reading), with no
       [ACCEPTANCE GATE] replan;
  RW5  a retired row takes no more lifecycle — the cursor's finalize never
       ticks plan-1 back to completed.

One invocation, self-contained; server and fake provider killed in finally.
Artifacts: scratch/todo-rewrite-live/
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
FAKE_PORT = 18773
HOME = REPO / "scratch" / "todo-rewrite-live-home"
OUT = REPO / "scratch" / "todo-rewrite-live"
SESSION = "todo-rewrite-live"

REQUESTS: list[dict] = []

PLANNER_JSON = {
    "mode": "execute",
    "acknowledgement": "Checking that for you",
    "response": "",
    "objective": "this machine's RAM total",
    "title": "Check Machine RAM",
    "plan": [
        {
            "todo": "Read this machine's RAM from system info",
            "outcome": "the machine's RAM total, quoted from the sysinfo tool's own reading",
        },
        {"todo": "Prepare the answer", "outcome": ""},
    ],
    "clarifying_question": "",
    "confidence": 0.9,
}

CONSULT_JSON = {
    "facts": ["The sysinfo tool reported a RAM total"],
    "ambiguities": [],
    "next_step": "synthesize the final answer",
    "confidence": 0.9,
}

REWRITE = {
    "todos": [
        {"text": "Read this machine's RAM from system info", "status": "in_progress"},
        {
            "text": "Note the available memory too",
            "status": "pending",
            "expected_outcome": "the available memory, quoted from the sysinfo tool's own reading",
        },
    ]
}


def _chunk(delta: dict, finish=None, usage=None) -> dict:
    obj = {
        "id": "tw", "object": "chat.completion.chunk", "created": 1,
        "model": "ps-flash",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    if usage:
        obj["usage"] = usage
    return obj


class FakeProvider(BaseHTTPRequestHandler):
    """Content-routed responses:

    - system says "initialization stage"            → the Planner lane
    - system says "read-only analyst"               → the Thinker consult
    - no tool messages yet                          → the todo_write REWRITE
    - a todo_write result, no sysinfo result yet    → the sysinfo tool call
    - otherwise                                     → the evidence-grounded answer

    Routing keys off the ASSISTANT's tool_calls in the history (what the
    agent has DONE), with the tool-result text as fallback only — the
    todo_write observation echoes the plan rows verbatim (labels and
    outcome contracts), so a naive "RAM in the tool results" sniff
    misfires on the checklist itself and the provider never calls sysinfo.
    Loop calls also carry `tools` in the payload while the planner, the
    Thinker consult, and the post-turn lanes do not — and the consult's
    findings are INJECTED as a system-role message mentioning the read-only
    analyst, so the consult branch must be gated on `not tools` or the
    final answer call routes to it (the answer becomes the consult's JSON).
    The final answer honestly ECHOES the real sysinfo reading (the
    planner-lane harness pattern) — a canned figure would contradict the
    real tool evidence and the gate would rightly fail the turn.
    """

    def log_message(self, *a):  # silence request logging
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {}
        REQUESTS.append(payload)
        # ground-truth dump: every request the server actually sent
        try:
            (OUT / "requests.json").write_text(
                json.dumps(REQUESTS, indent=1)[:2_000_000], encoding="utf-8"
            )
        except Exception:
            pass
        if not self.path.endswith("/chat/completions"):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"{}")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        def sse(obj):
            # ground-truth dump: what this request was answered with
            try:
                with open(OUT / "responses.log", "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(obj)[:300] + "\n")
            except Exception:
                pass
            self.wfile.write(f"data: {json.dumps(obj)}\n\n".encode())
            self.wfile.flush()

        # route on THIS handler's own payload — REQUESTS[-1] races under
        # ThreadingHTTPServer when the background consult overlaps the
        # final answer call (both handlers read the other's payload).
        messages = payload.get("messages") or []
        system = " ".join(str(m.get("content") or "") for m in messages if m.get("role") == "system")
        tool_results = [str(m.get("content") or "") for m in messages if m.get("role") == "tool"]
        called = set()
        for m in messages:
            if m.get("role") == "assistant":
                for tc in m.get("tool_calls") or []:
                    _fn = ((tc.get("function") or {}).get("name")) or ""
                    if _fn:
                        called.add(_fn)
        has_rewrite_result = "todo_write" in called or any("Todo list" in t for t in tool_results)
        has_sysinfo_result = "sysinfo" in called or any(
            ("RAM" in t or "GB" in t) and "Todo list" not in t for t in tool_results
        )
        # Loop calls carry tool schemas; the planner, the Thinker consult,
        # and the post-turn lanes (judge/title) are plain chat calls.
        has_tools = bool(payload.get("tools"))

        if "initialization stage" in system:
            sse(_chunk({"content": json.dumps(PLANNER_JSON)}))
            sse(_chunk({}, finish="stop", usage={"prompt_tokens": 400, "completion_tokens": 90, "total_tokens": 490}))
        elif "read-only analyst" in system and not has_tools:
            sse(_chunk({"reasoning_content": "The evidence covers RAM and battery; answer next."}))
            sse(_chunk({"content": json.dumps(CONSULT_JSON)}))
            sse(_chunk({}, finish="stop"))
        elif has_tools and not tool_results:
            # The model reshapes its own checklist BEFORE acting: drop the
            # filler row, keep the RAM row (rephrased status), add memory.
            sse(_chunk({
                "role": "assistant",
                "tool_calls": [{
                    "index": 0, "id": "call_rw", "type": "function",
                    "function": {"name": "todo_write", "arguments": json.dumps(REWRITE)},
                }],
            }))
            sse(_chunk({}, finish="tool_calls"))
        elif has_tools and has_rewrite_result and not has_sysinfo_result:
            sse(_chunk({
                "role": "assistant",
                "tool_calls": [{
                    "index": 0, "id": "call_si", "type": "function",
                    "function": {"name": "sysinfo", "arguments": json.dumps({"query": "ram battery"})},
                }],
            }))
            sse(_chunk({}, finish="tool_calls"))
        else:
            # The honest echo: quote the sysinfo tool's own reading back.
            sysinfo_line = next(
                (
                    ln.strip()
                    for t in tool_results
                    for ln in t.splitlines()
                    if "RAM" in ln and "total" in ln
                ),
                "RAM reading not found",
            )
            sse(_chunk({"content": f"Here is what the system reports: {sysinfo_line}"}))
            sse(_chunk({}, finish="stop", usage={"prompt_tokens": 900, "completion_tokens": 20, "total_tokens": 920}))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


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
        return resp.read().decode("utf-8", errors="replace")


def sse_events(sse_text: str) -> list[dict]:
    out = []
    for line in sse_text.splitlines():
        line = line.strip()
        if line.startswith("data: ") and line != "data: [DONE]":
            try:
                obj = json.loads(line[6:])
                if isinstance(obj, dict):
                    out.append(obj)
            except Exception:
                pass
    return out


def final_text(events: list[dict]) -> str:
    return "".join(e.get("content") or e.get("token") or "" for e in events if e.get("type") == "token")


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
        sse_text = fire(
            "Check this machine's RAM total, and how much of it is available", SESSION
        )
        (OUT / "sse-turn1.sse").write_text(sse_text, encoding="utf-8")
        events = sse_events(sse_text)

        def todos(kind):
            return [e.get("todo") or {} for e in events if e.get("type") == kind]

        # ── RW1: the drawn plan seeds the panel — exactly one clear ──
        cleared = [e for e in events if e.get("type") == "todo_cleared"]
        if len(cleared) != 1:
            failures.append(f"RW1 expected exactly 1 todo_cleared, got {len(cleared)}")
        created = todos("todo_created")
        plan0 = [c for c in created if c.get("id") == "plan-0"]
        plan1 = [c for c in created if c.get("id") == "plan-1"]
        if not plan0 or "RAM" not in str(plan0[0].get("text", "")):
            failures.append(f"RW1 plan-0 (the RAM todo) missing: {created}")
        if not plan0 or not plan0[0].get("expected_outcome"):
            failures.append(f"RW1 plan-0 carries no outcome contract: {plan0}")
        if not plan1:
            failures.append(f"RW1 plan-1 (the filler row) missing: {created}")

        # ── RW2: the rewrite diffs — retire + append-with-outcome ──
        retired = [u for u in todos("todo_updated") if u.get("status") == "retired"]
        if [r.get("id") for r in retired] != ["plan-1"]:
            failures.append(f"RW2 expected plan-1 retired exactly once, got {retired}")
        if retired and not retired[0].get("result"):
            failures.append("RW2 the retirement carries no reason")
        plan2 = [c for c in created if c.get("id") == "plan-2"]
        if not plan2:
            failures.append(f"RW2 expected plan-2 (available memory) appended, got {created}")
        elif "available memory" not in str(plan2[0].get("text", "")).lower():
            failures.append(f"RW2 plan-2 is not the available-memory row: {plan2}")
        elif not plan2[0].get("expected_outcome"):
            failures.append(f"RW2 plan-2 carries no expected_outcome: {plan2}")
        if len(cleared) != 1:
            failures.append("RW2 the rewrite must never clear the panel")

        # ── RW3: the revision diff lands on the wire ──
        def _revised(events):
            out = []
            for e in events:
                if e.get("type") == "todo_revised":
                    out.append(e)
                oe = e.get("obs_event") or {}
                if oe.get("type") == "todo_revised":
                    out.append(oe.get("data") or {})
            return out

        revised = [r.get("added", 0) for r in _revised(events)]
        if not revised or revised[0] != 1:
            failures.append(f"RW3 todo_revised added expected 1, got {revised}")
        retired_counts = [r.get("retired", 0) for r in _revised(events)]
        if not retired_counts or retired_counts[0] != 1:
            failures.append(f"RW3 todo_revised retired expected 1, got {retired_counts}")

        # ── RW4: the revised contract gates the close on work evidence ──
        text = final_text(events)
        if "RAM" not in text or "GB" not in text:
            failures.append(f"RW4 the answer lacks the sysinfo evidence: {text[:200]!r}")
        if "✓" not in text:
            failures.append(f"RW4 the gate summary is not a pass: {text[-200:]!r}")
        if "available memory" not in text.lower() or "criteria met" not in text:
            failures.append(
                f"RW4 the revised criterion is not in the gate summary: {text[-200:]!r}"
            )
        if "[ACCEPTANCE GATE]" in text:
            failures.append("RW4 the turn replanned — the revised contract should have closed it")

        # ── RW5: a retired row takes no more lifecycle ──
        completed_ids = [c.get("id") for c in todos("todo_completed")]
        if "plan-1" in completed_ids:
            failures.append("RW5 the retired row was ticked completed at close")

        print(f"todo events on the wire: {len([e for e in events if str(e.get('type', '')).startswith('todo')])}")
        print(f"final text tail: {text[-160:]!r}")
    finally:
        try:
            if server is not None:
                kill_process_tree(server.pid)
        except Exception:
            pass
        try:
            fake.shutdown()
        except Exception:
            pass

    if failures:
        print("FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: RW1..RW5 — the model's own rewrite diffs, carries outcomes, and gates the close")  # noqa: E501
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
