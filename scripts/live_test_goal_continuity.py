"""LIVE verification — cross-turn continuity: the open-question record and
the carried objective (the Continuous Goal Pursuit build, S016).

Boots the REAL LocalMind server (port 8765, scratch LOCALMIND_HOME) against
the local deterministic OpenAI-compat fake provider (established harness
pattern, no external key), replays the owner's location-conversation shape
plus a fresh-question / social-gesture / short-answer sequence, and asserts
the continuity contract END TO END:

  turn 1  "Where am i now?"   → the reply ends on a question → the durable
                                open-question record lands (trace event +
                                SQLite row), whichever lane served the turn.
  turn 2  "yes"               → consumed: the reroute is on the record
                                (path_selected lane=open_question_reply), the
                                loop's outgoing payload carries the open-
                                question section, the pre-init classify is
                                DRIVEN to clarify — and the stand-down holds
                                (no canned clarification ends the turn), the
                                row is consumed.
  turn 3  "What city is that?"→ a substantive message supersedes any record;
                                the fresh question-ending reply records again.
  turn 4  "lol"               → a pure social gesture takes the light lane and
                                LEAVES the record outstanding; the fast-path
                                prompt carries the active-objective line.
  turn 5  "sure"              → consumed again: loop payload carries the
                                section, row cleared.

A durable session goal is seeded before the run so the carried-objective
surface is asserted on both the loop payload and the fast-path prompt.

One invocation, self-contained; server and fake provider killed in finally.
Artifacts: scratch/goal-continuity-live/
"""

from __future__ import annotations

import json
import os
import sqlite3
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
HOME = REPO / "scratch" / "goal-continuity-home"
OUT = REPO / "scratch" / "goal-continuity-live"
SESSION = "goal-continuity-live"

QUESTION_1 = (
    "Based on your machine settings, you're in Kenya (KE), in the E. Africa "
    "Standard Time zone. Do you need more specific location information?"
)
ANSWER_YES = (
    "Checked again — the machine facts expose the country and timezone, but no "
    "city is available locally."
)
QUESTION_2 = (
    "I can see the country and timezone, but the machine facts expose no city — "
    "do you want me to try a web lookup?"
)
SOCIAL_REPLY = "Glad it landed!"
ANSWER_SURE = "On it — trying a web lookup for the nearest city now."

OBJECTIVE = "Determine the user's current location as precisely as the machine allows"

REPLIES = {
    "Where am i now?": QUESTION_1,
    "yes": ANSWER_YES,
    "What city is that?": QUESTION_2,
    "lol": SOCIAL_REPLY,
    "sure": ANSWER_SURE,
}

REQUESTS: list[dict] = []


def _last_user_text(req: dict) -> str:
    msgs = (req or {}).get("messages") or []
    for m in reversed(msgs):
        if m.get("role") == "user":
            return str(m.get("content") or "")
    return ""


def _is_classify(req: dict) -> bool:
    """The pre-init/parent classify call carries the three-mode contract."""
    blob = json.dumps((req or {}).get("messages") or [])
    return "direct|clarify|execute" in blob


class FakeProvider(BaseHTTPRequestHandler):
    """Replies keyed by the conversation's last user message; the classify
    call is answered with an explicit clarify JSON on the "yes" turn so the
    stand-down is verified against a REAL clarification decision."""

    def log_message(self, *a):  # silence request logging
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length)
        try:
            req = json.loads(raw)
        except Exception:
            req = {}
        REQUESTS.append(req)
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

        user_text = _last_user_text(req)
        if _is_classify(req):
            mode = "clarify" if user_text.strip() == "yes" else "execute"
            body = {"mode": mode, "objective": "Resolve the user's request"}
            if mode == "clarify":
                body["clarifying_question"] = (
                    "What specific location information are you looking for?"
                )
            sse({
                "id": "gc", "object": "chat.completion.chunk", "created": 1,
                "model": "gc-flash",
                "choices": [{"index": 0, "delta": {"content": json.dumps(body)}, "finish_reason": None}],
            })
            sse({
                "id": "gc", "object": "chat.completion.chunk", "created": 1,
                "model": "gc-flash",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 300, "completion_tokens": 20, "total_tokens": 320},
            })
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        reply = None
        for msg, text in REPLIES.items():
            if msg in user_text:
                reply = text
                break
        if reply is None:
            reply = "Noted."
        sse({
            "id": "gc", "object": "chat.completion.chunk", "created": 1,
            "model": "gc-flash",
            "choices": [{"index": 0, "delta": {"content": reply}, "finish_reason": None}],
        })
        sse({
            "id": "gc", "object": "chat.completion.chunk", "created": 1,
            "model": "gc-flash",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 25, "total_tokens": 525},
        })
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def boot_fake() -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", FAKE_PORT), FakeProvider)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def find_db() -> Path:
    dbs = [p for p in HOME.rglob("*.db")]
    if not dbs:
        raise RuntimeError("no sqlite db found under the scratch home")
    return dbs[0]


def open_question_row(conn: sqlite3.Connection) -> tuple | None:
    try:
        return conn.execute(
            "SELECT question FROM session_open_questions WHERE session_id = ?", (SESSION,)
        ).fetchone()
    except sqlite3.OperationalError:
        return None


def seed_goal(db: Path) -> None:
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            """INSERT INTO session_goals
               (id, session_id, objective, phase, revision, max_rounds,
                rounds_started, created_at, updated_at)
               VALUES ('goal-live', ?, ?, 'active', 1, 256, 0, ?, ?)""",
            (SESSION, OBJECTIVE, time.time(), time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def boot_server() -> subprocess.Popen:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2).read()
        raise RuntimeError(
            f"a live server already answers on port {PORT} — kill the stale harness first"
        )
    except RuntimeError:
        raise
    except Exception:
        pass
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


def fire(message: str) -> str:
    body = urllib.parse.urlencode({"message": message, "session_id": SESSION}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/chat",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read().decode("utf-8", errors="replace")


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


def obs_types(events: list[dict]) -> list[tuple[str, dict]]:
    out = []
    for e in events:
        oe = e.get("obs_event") or {}
        if isinstance(oe, dict) and oe.get("type"):
            out.append((oe["type"], oe.get("data") or {}))
    return out


def wire_event(events: list[dict], etype: str) -> dict | None:
    for t, data in obs_types(events):
        if t == etype:
            return data
    return None


def check(condition: bool, label: str, failures: list[str]) -> None:
    print(f"    [{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        failures.append(label)


def main() -> int:
    import shutil

    if OUT.exists():
        shutil.rmtree(OUT)
    if HOME.exists():
        shutil.rmtree(HOME)
    OUT.mkdir(parents=True, exist_ok=True)
    HOME.mkdir(parents=True, exist_ok=True)
    settings = {
        "adapter": "fakeprov",
        "api_keys": {"fakeprov": "sk-local-fake-not-a-real-key"},
        "connections": [
            {
                "id": "fakeprov", "name": "gc-fake", "kind": "openai-compat",
                "base_url": f"http://127.0.0.1:{FAKE_PORT}/v1",
                "model": "gc-flash", "enabled": True,
            }
        ],
    }
    (HOME / "settings.json").write_text(json.dumps(settings, indent=2))

    fake = boot_fake()
    server: subprocess.Popen | None = None
    failures: list[str] = []
    try:
        server = boot_server()
        print(f"server up on {PORT} (fake provider on {FAKE_PORT})")
        db = find_db()
        seed_goal(db)
        print(f"seeded the durable session goal in {db.name}")

        conn = sqlite3.connect(str(db))

        # ── turn 1: the question-ending reply records the open question ──
        raw1 = fire("Where am i now?")
        (OUT / "turn1.sse.txt").write_text(raw1)
        time.sleep(1.0)
        ev1 = parse_events(raw1)
        rec1 = wire_event(ev1, "open_question_recorded")
        check(rec1 is not None, "turn 1 records the open question (trace event)", failures)
        row = open_question_row(conn)
        check(
            row is not None and "more specific location" in (row[0] or ""),
            "turn 1 lands the durable row with the asked question",
            failures,
        )

        # ── turn 2: "yes" is consumed → reroute + section + stand-down ──
        raw2 = fire("yes")
        (OUT / "turn2.sse.txt").write_text(raw2)
        time.sleep(1.0)
        ev2 = parse_events(raw2)
        ps2 = wire_event(ev2, "path_selected")
        check(
            ps2 is not None and ps2.get("lane") == "open_question_reply",
            "turn 2 reroutes on the record (path_selected lane=open_question_reply)",
            failures,
        )
        check(
            wire_event(ev2, "open_question_consumed") is not None,
            "turn 2 consumes the record (trace event)",
            failures,
        )
        # The loop payload carries the open-question section: find the LAST
        # request whose messages include a system message with the section.
        oq_payloads = [
            req for req in REQUESTS
            if any("Open question you asked" in str(m.get("content") or "")
                   for m in (req.get("messages") or []) if m.get("role") == "system")
        ]
        check(bool(oq_payloads), "turn 2's loop payload carries the open-question section", failures)
        if oq_payloads:
            sys_texts = [
                str(m.get("content") or "")
                for m in oq_payloads[-1].get("messages", [])
                if m.get("role") == "system"
            ]
            tail = sys_texts[-1] if sys_texts else ""
            check("more specific location" in tail or "Do you need more" in json.dumps(oq_payloads[-1]),
                  "the section names the agent's OWN question", failures)
            check(
                any("Active objective for this session" in t for t in sys_texts),
                "the loop payload carries the carried-objective section",
                failures,
            )
        final2 = "".join(
            e.get("obs_event", {}).get("data", {}).get("text", "")
            for e in ev2
        ) or raw2
        check(
            "want to make sure I understand" not in raw2,
            "the driven clarify decision did NOT end the turn (stand-down held)",
            failures,
        )
        row2 = open_question_row(conn)
        check(row2 is None, "turn 2 consumed the row (cleared after resolution)", failures)

        # ── turn 3: a substantive message supersedes; the new question records ──
        raw3 = fire("What city is that?")
        (OUT / "turn3.sse.txt").write_text(raw3)
        time.sleep(1.0)
        ev3 = parse_events(raw3)
        rec3 = wire_event(ev3, "open_question_recorded")
        check(rec3 is not None, "turn 3's question-ending reply records again", failures)
        row3 = open_question_row(conn)
        check(
            row3 is not None and "web lookup" in (row3[0] or ""),
            "turn 3 leaves the fresh question outstanding",
            failures,
        )

        # ── turn 4: a pure social gesture leaves the record outstanding ──
        n_req_before = len(REQUESTS)
        raw4 = fire("lol")
        (OUT / "turn4.sse.txt").write_text(raw4)
        time.sleep(1.0)
        ev4 = parse_events(raw4)
        ps4 = wire_event(ev4, "path_selected")
        check(
            ps4 is None or ps4.get("lane") != "open_question_reply",
            "turn 4 is not an open-question resolution (social gesture)",
            failures,
        )
        row4 = open_question_row(conn)
        check(
            row4 is not None and "web lookup" in (row4[0] or ""),
            "turn 4 LEAVES the question outstanding (social gesture)",
            failures,
        )
        turn4_reqs = REQUESTS[n_req_before:]
        check(
            any(
                "Active objective for this session" in json.dumps(req.get("messages") or [])
                for req in turn4_reqs
            ),
            "turn 4's prompt carries the active-objective surface",
            failures,
        )
        check(
            wire_event(ev4, "open_question_consumed") is None
            and wire_event(ev4, "open_question_superseded") is None,
            "turn 4 fires no record mutation",
            failures,
        )

        # ── turn 5: "sure" is consumed again ──
        raw5 = fire("sure")
        (OUT / "turn5.sse.txt").write_text(raw5)
        time.sleep(1.0)
        ev5 = parse_events(raw5)
        ps5 = wire_event(ev5, "path_selected")
        check(
            ps5 is not None and ps5.get("lane") == "open_question_reply",
            "turn 5 reroutes on the record again",
            failures,
        )
        check(
            wire_event(ev5, "open_question_consumed") is not None,
            "turn 5 consumes the record",
            failures,
        )
        check(
            any(
                "Open question you asked" in str(m.get("content") or "")
                for req in REQUESTS
                for m in (req.get("messages") or [])
                if m.get("role") == "system"
            ),
            "turn 5's loop payload carries the section again",
            failures,
        )
        row5 = open_question_row(conn)
        check(row5 is None, "turn 5 cleared the row", failures)
        conn.close()

    finally:
        if server:
            kill_process_tree(server.pid)
        fake.shutdown()

    if failures:
        print("FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("PASS — cross-turn continuity verified live (record lifecycle, reroute, sections, stand-down, carried objective)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
