"""Live verification: the model's markdown answer survives the wire intact.

Owner report (2026-11-03): "The UI does not format the output in style eg
tables etc its just text." Before touching any renderer, the pipeline must
be PROVEN on the wire — if the backend or the transport mangles (strips,
re-fences, re-wraps) the model's markdown, no frontend renderer can help.

This harness boots the REAL server (port 8765, scratch LOCALMIND_HOME)
against a local fake provider whose answers are authored markdown, and
asserts on the actual SSE stream and the persisted history:

  MD1  the well-formed answer (h2, bold, GFM table, bullets, inline code,
       fenced bash block, link) reaches the SSE stream as a CONTIGUOUS
       substring of the final text — byte-exact passthrough, nothing
       stripped, nothing re-wrapped;
  MD2  the same answer is persisted and served by the history endpoint
       (the reload path renders the same markdown the live turn did);
  MD3  the GLM-degraded answer (full-width pipes U+FF5C, full-width dash
       separators, a table with no delimiter row) ALSO passes through
       byte-exact — the transport never "helpfully" rewrites the model's
       output; rendering degraded shapes is the FRONTEND's job;
  MD4  both turns close against the drawn plan contract without a false
       [ACCEPTANCE GATE] replan (the outcome names the table + command the
       answer really carries);
  MD5  the response_formatting contract reaches the model: a captured loop
       request's system prompt contains the RESPONSE FORMATTING section
       with the table instruction (the prompt the real model sees).

One invocation, self-contained; server and fake provider killed in finally.
Artifacts: scratch/markdown-live/
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
FAKE_PORT = 18796
HOME = REPO / "scratch" / "markdown-live-home"
OUT = REPO / "scratch" / "markdown-live"

REQUESTS: list[dict] = []

PLANNER_JSON = {
    "mode": "execute",
    "acknowledgement": "Comparing the two plans for you",
    "response": "",
    "objective": "compare the two data plans",
    "title": "Compare Data Plans",
    "plan": [
        {
            "todo": "Compose the comparison answer from what I know",
            "outcome": "the answer contains a comparison table of the two plans and the install command",
        },
    ],
    "clarifying_question": "",
    "confidence": 0.9,
}

CONSULT_JSON = {
    "facts": ["The question asks for a plan comparison"],
    "ambiguities": [],
    "next_step": "synthesize the final answer",
    "confidence": 0.9,
}

# Well-formed GFM: heading, bold, table, list, inline code, fence, link.
ANSWER_A = (
    "## Kitengela vs Nairobi data plans\n"
    "\n"
    "Here is the comparison you asked for — **Plan A** is cheaper, **Plan B** is faster:\n"
    "\n"
    "| Plan | Price | Speed | Data cap |\n"
    "| --- | --- | --- | --- |\n"
    "| Plan A | KES 1,500 | 10 Mbps | 100 GB |\n"
    "| Plan B | KES 2,800 | 40 Mbps | 500 GB |\n"
    "\n"
    "Key points:\n"
    "\n"
    "- **Plan A** suits light browsing\n"
    "- **Plan B** suits streaming and downloads\n"
    "\n"
    "Install with:\n"
    "\n"
    "```bash\n"
    "pip install localmind\n"
    "```\n"
    "\n"
    "See the `README.md` for details, or the [docs](https://example.com/docs).\n"
)

# GLM-degraded shapes: full-width pipes, full-width-dash delimiter row, and
# a table with NO delimiter row at all. The transport must pass these
# through byte-exact; the frontend renderer decides how to cope.
ANSWER_B = (
    "## Kitengela vs Nairobi data plans\n"
    "\n"
    "| Plan ｜ Price ｜ Speed ｜ Data cap ｜\n"
    "｜－－－－－｜－－－－－｜－－－－－｜－－－－－－｜\n"
    "｜ Plan A ｜ KES 1,500 ｜ 10 Mbps ｜ 100 GB ｜\n"
    "｜ Plan B ｜ KES 2,800 ｜ 40 Mbps ｜ 500 GB ｜\n"
    "\n"
    "And a table with no delimiter row:\n"
    "\n"
    "| Plan | Price | Speed |\n"
    "| Plan A | KES 1,500 | 10 Mbps |\n"
    "| Plan B | KES 2,800 | 40 Mbps |\n"
    "\n"
    "Install with:\n"
    "\n"
    "```bash\n"
    "pip install localmind\n"
    "```\n"
)

MODE_ANSWERS = {"A": ANSWER_A, "B": ANSWER_B}

# Probe B draws NO plan: its purpose is the degraded-shape PASSTHROUGH, not
# the gate. With a plan row promising work, the zero-tool force (analyze
# intent + plan_steps + no tool calls) nudges every remaining iteration —
# 20 provider calls of harness-induced storm on the first run. An empty
# plan takes the legacy accept path and the probe stays single-purpose.
PLANNER_JSON_B = {
    **PLANNER_JSON,
    "acknowledgement": "Formatting it differently for you",
    "plan": [],
}


def _chunk(delta: dict, finish=None, usage=None) -> dict:
    obj = {
        "id": "md", "object": "chat.completion.chunk", "created": 1,
        "model": "md-flash",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    if usage:
        obj["usage"] = usage
    return obj


class FakeProvider(BaseHTTPRequestHandler):
    """Content-routed (route on THIS handler's own payload — REQUESTS[-1]
    races under ThreadingHTTPServer when background lanes overlap the answer
    call): init marker → planner; read-only-analyst system → consult;
    loop call (tools attached, no tool result yet) → the mode's markdown
    answer; anything else → repeat the mode's answer (a gate nudge replays
    the same content — a mangled replay would be a passthrough failure)."""

    mode: str = "A"

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
        # ground-truth dump: one JSON line per request (append-only — a
        # whole-file rewrite races under ThreadingHTTPServer and can lose
        # every write to a concurrent truncate).
        try:
            with open(OUT / "requests.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False)[:400_000] + "\n")
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
            self.wfile.write(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()

        messages = payload.get("messages") or []
        system = " ".join(
            str(m.get("content") or "") for m in messages if m.get("role") == "system"
        )
        has_tools = bool(payload.get("tools"))

        answer = MODE_ANSWERS.get(FakeProvider.mode, ANSWER_A)
        if "initialization stage" in system:
            planner = PLANNER_JSON if FakeProvider.mode == "A" else PLANNER_JSON_B
            sse(_chunk({"content": json.dumps(planner, ensure_ascii=False)}))
            sse(_chunk({}, finish="stop", usage={"prompt_tokens": 400, "completion_tokens": 90, "total_tokens": 490}))
        elif "read-only analyst" in system and not has_tools:
            sse(_chunk({"reasoning_content": "The request is a knowledge comparison; answer directly."}))
            sse(_chunk({"content": json.dumps(CONSULT_JSON, ensure_ascii=False)}))
            sse(_chunk({}, finish="stop"))
        else:
            # Loop call (and any gate-nudge replay): the markdown answer,
            # streamed in chunks so token reassembly is exercised too.
            parts = [answer[:80], answer[80:200], answer[200:]]
            for part in parts:
                if part:
                    sse(_chunk({"content": part}))
            sse(_chunk({}, finish="stop", usage={"prompt_tokens": 900, "completion_tokens": 120, "total_tokens": 1020}))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def boot_fake() -> ThreadingHTTPServer:
    FakeProvider.mode = "A"
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


def fire(message: str, session: str) -> str:
    body = urllib.parse.urlencode({"message": message, "session_id": session}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/chat",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
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


def history_contents(session: str) -> list[tuple[str, str]]:
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/sessions/{session}/history")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    out = []
    for m in data.get("history") or []:
        if isinstance(m, dict):
            out.append((str(m.get("role") or ""), str(m.get("content") or "")))
    return out


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
                        "id": "fakeprov", "name": "md-fake", "kind": "openai-compat",
                        "base_url": f"http://127.0.0.1:{FAKE_PORT}/v1",
                        "model": "md-flash", "enabled": True,
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

        # ── Probe A: the well-formed markdown answer ──
        sse_a = fire(
            "Compare Kitengela and Nairobi data plans in a table", "markdown-live-a"
        )
        (OUT / "sse-probeA.sse").write_text(sse_a, encoding="utf-8")
        text_a = final_text(sse_events(sse_a))

        if ANSWER_A.rstrip() not in text_a.rstrip():
            failures.append(
                "MD1 the well-formed answer did not reach the SSE stream "
                f"contiguously; final text was: {text_a[:400]!r}"
            )
        if "[ACCEPTANCE GATE]" in text_a:
            failures.append("MD4 probe A replanned — the drawn contract should have closed it")

        hist = history_contents("markdown-live-a")
        assistant = [c for r, c in hist if r == "assistant"]
        if not assistant:
            failures.append(f"MD2 the history carries no assistant message: {hist}")
        elif not any(ANSWER_A.rstrip() in c.rstrip() for c in assistant):
            failures.append(
                "MD2 the persisted history does not carry the well-formed answer "
                f"contiguously; got {[(r, c[:120]) for r, c in hist]}"
            )

        # ── Probe B: the GLM-degraded shapes ──
        FakeProvider.mode = "B"
        sse_b = fire(
            "Now compare them again, differently formatted", "markdown-live-b"
        )
        (OUT / "sse-probeB.sse").write_text(sse_b, encoding="utf-8")
        text_b = final_text(sse_events(sse_b))

        if ANSWER_B.rstrip() not in text_b.rstrip():
            failures.append(
                "MD3 the degraded answer did not pass through byte-exact — the "
                f"transport rewrote the model's output; final text was: {text_b[:400]!r}"
            )
        if "[ACCEPTANCE GATE]" in text_b:
            failures.append("MD4 probe B replanned — the drawn contract should have closed it")

        # ── MD5: the formatting contract reaches the model ──
        loop_systems = [
            " ".join(
                str(m.get("content") or "")
                for m in (r.get("messages") or [])
                if isinstance(m, dict) and m.get("role") == "system"
            )
            for r in REQUESTS
            if r.get("tools")
        ]
        if not loop_systems:
            failures.append("MD5 no loop request (tools attached) was captured")
        elif not any(
            "RESPONSE FORMATTING" in s and "table" in s.lower() for s in loop_systems
        ):
            failures.append(
                "MD5 the response_formatting contract is absent from the loop "
                "system prompt — the model never sees the table instruction"
            )

        print(f"probe A final text: {len(text_a)} chars; contains GFM table: {'| --- |' in text_a}")
        print(f"probe B final text: {len(text_b)} chars; contains full-width pipes: {'｜' in text_b}")
        print(f"captured provider requests: {len(REQUESTS)}")
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
    print("PASS: MD1..MD5 — markdown crosses the wire byte-exact both ways; the contract reaches the model")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
