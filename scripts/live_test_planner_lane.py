"""Live verification: the Planner lane on the wire (S023).

The owner's live export (session-1793620218681) showed ordinary lookup turns
rendering syn- tool-echo todos — S020's {todo, outcome} plan existed only in
the parent-init branch the production runtime skips. This harness boots the
REAL server (port 8765, scratch LOCALMIND_HOME) against a local fake provider
and asserts, on the actual SSE stream and the actual outgoing payloads:

  PL1  the real plan — a task turn's FIRST provider call is the Planner
       lane (the init prompt with the {todo, outcome} contract), its
       scripted plan reaches the SSE as todo_cleared + todo_created rows
       with ids plan-0/plan-1, status pending and the expected_outcome
       carried — and NO syn- row ever appears.
  PL2  the per-todo contract gates the close — the drawn outcome becomes
       the acceptance gate's criterion; the answer satisfies the evidence
       check and the turn closes without an [ACCEPTANCE GATE] replan.
  PL3  consult thinking stays clean — the Thinker consult emits a fenced
       JSON rehearsal on the reasoning channel; the SSE thinking stream
       must NOT carry it (the fence suppressor on the wire).
  PL4  social turns skip the lane — "hi LM" reaches the model WITHOUT a
       planner call first (no "initialization stage" system prompt on the
       turn's first request), and no plan rows appear.

One invocation, self-contained; server and fake provider killed in finally.
Artifacts: scratch/planner-lane-live/
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
FAKE_PORT = 18772
HOME = REPO / "scratch" / "planner-lane-live-home"
OUT = REPO / "scratch" / "planner-lane-live"
SESSION = "planner-lane-live"

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
    "facts": ["The calculator ran and returned a numeric result"],
    "ambiguities": [],
    "next_step": "synthesize the final answer",
    "confidence": 0.9,
}


def _chunk(delta: dict, finish=None, usage=None) -> dict:
    obj = {
        "id": "pl", "object": "chat.completion.chunk", "created": 1,
        "model": "ps-flash",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    if usage:
        obj["usage"] = usage
    return obj


class FakeProvider(BaseHTTPRequestHandler):
    """Content-routed responses:

    - system says "initialization stage"  → the Planner lane → plan JSON
    - system says "read-only analyst"     → the Thinker consult → fenced
      rehearsal on reasoning_content + the decision JSON on content
    - the payload carries a tool result   → the final answer
    - otherwise                           → the calculator tool call
    """

    def log_message(self, *a):  # silence request logging
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length)
        try:
            REQUESTS.append(json.loads(raw))
        except Exception:
            REQUESTS.append({})
        if not self.path.endswith("/chat/completions"):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"{}")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        def sse(obj):
            self.wfile.write(f"data: {json.dumps(obj)}\n\n".encode())
            self.wfile.flush()

        payload = REQUESTS[-1]
        body = json.dumps(payload)
        system = " ".join(
            str(m.get("content") or "") for m in (payload.get("messages") or [])
            if m.get("role") == "system"
        )
        has_tool_result = any(m.get("role") == "tool" for m in (payload.get("messages") or []))
        last_user = ""
        for m in reversed(payload.get("messages") or []):
            if m.get("role") == "user":
                last_user = str(m.get("content") or "")
                break

        if "initialization stage" in system:
            # The Planner lane call (thinking off — never answered here).
            sse(_chunk({"content": json.dumps(PLANNER_JSON)}))
            sse(_chunk({}, finish="stop", usage={"prompt_tokens": 400, "completion_tokens": 90, "total_tokens": 490}))
        elif "read-only analyst" in system:
            # The Thinker consult: rehearse the decision JSON inside a
            # fenced block on the REASONING channel (the 2026-11-02 mess),
            # then the decision on the text channel.
            rehearsal = (
                "Let me structure this as a JSON response: ```json\n"
                '{"facts": ["guess"], "next_step": "rehearsed"}\n```'
            )
            sse(_chunk({"reasoning_content": rehearsal}))
            sse(_chunk({"content": json.dumps(CONSULT_JSON)}))
            sse(_chunk({}, finish="stop"))
        elif has_tool_result:
            # Echo the RAM line the tool actually reported (the honest
            # evidence-grounded answer the gate's criterion demands).
            ram = ""
            for m in payload.get("messages") or []:
                if m.get("role") == "tool":
                    text = str(m.get("content") or "")
                    for ln in text.splitlines():
                        if "RAM" in ln and "total" in ln:
                            ram = ln.strip()
            sse(_chunk({"content": f"Here is what the system reports: {ram or 'RAM total not found'}"}))
            sse(_chunk({}, finish="stop", usage={"prompt_tokens": 900, "completion_tokens": 14, "total_tokens": 914}))
        elif "hi lm" in last_user.lower() or "hello" in last_user.lower():
            sse(_chunk({"content": "Hello! How can I assist you today?"}))
            sse(_chunk({}, finish="stop", usage={"prompt_tokens": 300, "completion_tokens": 10, "total_tokens": 310}))
        else:
            sse(_chunk({
                "role": "assistant",
                "tool_calls": [{
                    "index": 0, "id": "call_1", "type": "function",
                    "function": {"name": "sysinfo", "arguments": json.dumps({"query": "ram"})},
                }],
            }))
            sse(_chunk({}, finish="tool_calls"))
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


def system_of(payload: dict) -> str:
    return " ".join(
        str(m.get("content") or "") for m in (payload.get("messages") or [])
        if m.get("role") == "system"
    )


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
        turn1 = fire("Search your system info and tell me how much RAM this machine has", SESSION)
        (OUT / "sse-turn1.sse").write_text(turn1, encoding="utf-8")
        events = sse_events(turn1)

        # ── PL1: the drawn plan reaches the panel, never a syn- row ──
        created = [e.get("todo") or {} for e in events if e.get("type") == "todo_created"]
        cleared = [e for e in events if e.get("type") == "todo_cleared"]
        ids = [c.get("id") for c in created]
        if not cleared:
            failures.append("PL1: no todo_cleared before the plan rows")
        if "plan-0" not in ids:
            failures.append(f"PL1: no plan-0 row in the todo events (ids: {ids})")
        else:
            print(f"PL1 OK: plan rows seeded ({ids}) after a todo_cleared")
        p0 = next((c for c in created if c.get("id") == "plan-0"), {})
        if p0.get("expected_outcome") != PLANNER_JSON["plan"][0]["outcome"]:
            failures.append(f"PL1: plan-0 missing the outcome contract: {p0}")
        elif p0.get("status") != "pending":
            failures.append(f"PL1: plan-0 not pending at draw-up: {p0.get('status')!r}")
        else:
            print("PL1 OK: plan-0 carries the Planner's outcome contract, pending")
        if any(str(i).startswith("syn-") for i in ids):
            failures.append(f"PL1: a syn- tool-echo row leaked onto a planned turn: {ids}")
        else:
            print("PL1 OK: no syn- tool-echo rows")

        # The first provider call of the turn is the Planner lane.
        if REQUESTS and "initialization stage" in system_of(REQUESTS[0]):
            print("PL1 OK: the turn's first provider call is the Planner lane")
        else:
            failures.append("PL1: the turn's first provider call is not the Planner lane")

        # ── PL2: the answer closed against the drawn contract ──
        answer = "".join(
            str(e.get("content") or "") for e in events if e.get("type") == "token"
        )
        if "RAM" in answer and ("total" in answer or "GB" in answer):
            print("PL2 OK: the turn answered from the sysinfo reading")
        else:
            failures.append(f"PL2: answer missing the RAM reading: {answer[:200]!r}")
        if "[ACCEPTANCE GATE]" in answer or "criteria met — unmet" in answer:
            failures.append(f"PL2: the gate replanned on a satisfiable contract: {answer[:300]!r}")
        else:
            print("PL2 OK: the per-todo contract closed without a false replan")

        # ── PL3: the consult's fenced rehearsal never reaches thinking ──
        thinking = "".join(
            str(e.get("thinking") or "") for e in events if e.get("type") == "thinking"
        )
        if "```" in thinking or '"next_step": "rehearsed"' in thinking:
            failures.append(
                f"PL3: the consult's JSON rehearsal leaked into thinking: {thinking[:200]!r}"
            )
        elif "calculator" in answer.lower() and "ran" in answer.lower():
            failures.append("PL3: the consult's decision JSON leaked into the answer text")
        else:
            print("PL3 OK: no fenced rehearsal in the thinking stream")

        # ── PL4: a social turn skips the lane entirely ──
        n_before = len(REQUESTS)
        turn2 = fire("hi LM", SESSION)
        (OUT / "sse-turn2.sse").write_text(turn2, encoding="utf-8")
        t2_first = REQUESTS[n_before] if len(REQUESTS) > n_before else {}
        if "initialization stage" in system_of(t2_first):
            failures.append("PL4: the social turn paid a Planner call")
        else:
            print("PL4 OK: the social turn's first provider call is not the Planner lane")
        t2_events = sse_events(turn2)
        t2_created = [e.get("todo") or {} for e in t2_events if e.get("type") == "todo_created"]
        if any(str(c.get("id")).startswith(("plan-", "syn-")) for c in t2_created):
            failures.append(f"PL4: a social turn grew todo rows: {[c.get('id') for c in t2_created]}")
        else:
            print("PL4 OK: no plan rows on the social turn")
        t2_answer = "".join(
            str(e.get("content") or "") for e in t2_events if e.get("type") == "token"
        )
        if "Hello" in t2_answer:
            print("PL4 OK: the greeting reached the model and came back as an answer")
        else:
            failures.append(f"PL4: greeting turn answer unexpected: {t2_answer[:120]!r}")

    finally:
        if server is not None:
            kill_process_tree(server)
        try:
            fake.shutdown()
        except Exception:
            pass

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
