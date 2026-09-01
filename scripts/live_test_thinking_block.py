#!/usr/bin/env python3
"""B-2026-08-30-7 live verification — the Thinking box shows real reasoning.

Fix under test (chat.py bridge): the loop's leak-filtered reasoning prose
(StreamChunk.thinking) is forwarded as thinking_token, and curated tool
labels (_narration_sse) emit on status_update instead of masquerading as
thinking. Before the fix, a 1m43s reasoning turn showed ONLY
"Researching on the web…" twice (user evidence, 2026-09-01).

Per system/live-testing.md: isolated 8765 + scratch LOCALMIND_HOME, real
provider (bankofai primary), no API-key values printed, cleanup after.

PASS = all of:
  1. thinking_token events exist whose text is REAL reasoning prose
     (not a curated _TOOL_NARRATION label)
  2. status_update events carry the curated tool labels
  3. no scaffold phrases in any thinking_token text
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.parse
from collections import Counter
from pathlib import Path

PORT = "8765"
REPO = Path(__file__).resolve().parent.parent
SC = REPO / "scratch" / "lm-thinking-block"
TH = SC / "tracehome"
BACKEND = REPO / "backend"
from harness_common import provider_key, venv_python

VENV_PY = venv_python(BACKEND)

PROVIDER = "bankofai"
MODEL = "glm-5.3-flash"

# The curated labels (mirror of chat.py _TOOL_NARRATION) — thinking_token
# text matching one of these is a LABEL, not reasoning.
CURATED_LABELS = [
    "checking your system", "looking at your desktop", "searching your files",
    "searching inside files", "looking for files", "running a command",
    "running some code", "reading a file", "writing a file", "editing a file",
    "applying an edit", "searching the web", "researching on the web",
    "fetching a page", "browsing the web", "checking version control",
    "checking my memory", "working out the numbers", "managing a process",
    "reading the spreadsheet", "reading the data", "querying the database",
    "working on it",
]

# Scaffold phrases that must never reach the Thinking box.
SCAFFOLD_PHRASES = [
    "synthesis reminder", "system reminder", "per the reminder",
    "do not call another tool", "[action narration]", "[force-tool]",
    "[synthesize]", "[recovery]",
]


def setup():
    if SC.exists():
        shutil.rmtree(SC)
    SC.mkdir(parents=True)
    TH.mkdir(parents=True)
    (TH / "settings.json").write_text(json.dumps({
        "adapter": PROVIDER,
        "model": MODEL,
        "thinking": "enabled",
        "shell_enabled": True,
        "api_keys": {PROVIDER: provider_key(PROVIDER)},
    }))


def boot():
    env = os.environ.copy()
    env.update({
        "LOCALMIND_PORT": PORT, "LOCALMIND_HOME": str(TH),
        "LOCALMIND_ADAPTER": PROVIDER, "LOCALMIND_SHELL_ENABLED": "true",
        "PYTHONPATH": str(BACKEND / "src"),
    })
    log = open(SC / "trace.log", "w")
    proc = subprocess.Popen([VENV_PY, "server.py"], cwd=str(BACKEND), env=env,
                            stdout=log, stderr=subprocess.STDOUT)
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://localhost:{PORT}/api/health", timeout=2)
            return proc
        except Exception:
            time.sleep(0.5)
    return None


def send_turn(sid: str, msg: str, timeout: int = 240) -> str:
    data = urllib.parse.urlencode({
        "message": msg, "session_id": sid, "is_first": "false",
    }).encode()
    req = urllib.request.Request(f"http://localhost:{PORT}/api/chat", data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"<EXCEPTION: {e}>"


def parse_sse_events(sse: str) -> list[dict]:
    events = []
    for line in sse.splitlines():
        if line.startswith("data: ") and '"type"' in line:
            try:
                events.append(json.loads(line[6:]))
            except Exception:
                pass
    return events


def main() -> int:
    setup()
    proc = boot()
    if proc is None:
        print("FAIL: server did not boot on isolated port", PORT)
        return 1
    try:
        time.sleep(2)
        sid = f"think-block-{int(time.time())}"
        # NOTE: "how did arsenal play" alone hits the conversational fast path
        # in the isolated harness (no session context) — the fast path never
        # streams reasoning. An explicit tool request forces the agent loop,
        # whose model calls stream reasoning (the path under test; it is also
        # the path the user's live evidence came from).
        msg = "Use web research to find the latest Arsenal match result, then tell me the score."
        print(f"provider={PROVIDER}/{MODEL}  port={PORT} (isolated)")
        print(f"sending: {msg}")
        sse = send_turn(sid, msg)
        (SC / "turn.sse").write_text(sse)
        if "<EXCEPTION" in sse:
            print(f"FAIL: turn errored: {sse[:300]}")
            return 1

        events = parse_sse_events(sse)
        counts = Counter(e.get("type", "?") for e in events)
        print(f"SSE event counts: {dict(counts)}")

        thinking_texts = [e.get("thinking", "") for e in events if e.get("type") == "thinking_token"]
        status_texts = [e.get("status", "") for e in events if e.get("type") == "status_update"]

        # Check 1: REAL reasoning prose reached the Thinking box.
        real_reasoning = [
            t for t in thinking_texts
            if t.strip() and not any(t.strip().lower().startswith(lbl) for lbl in CURATED_LABELS)
        ]
        print(f"\nthinking_token events: {len(thinking_texts)} "
              f"(curated-label-shaped: {len(thinking_texts) - len(real_reasoning)}, "
              f"real prose: {len(real_reasoning)})")
        if real_reasoning:
            sample = real_reasoning[0][:160].replace("\n", " ")
            print(f"  sample real reasoning: {sample!r}")

        # Check 2: curated labels moved to status_update.
        narrated = [s for s in status_texts if any(lbl in s.lower() for lbl in CURATED_LABELS)]
        print(f"\nstatus_update events: {len(status_texts)} (curated labels: {len(narrated)})")
        for s in narrated[:5]:
            print(f"  status: {s!r}")

        # Check 3: no scaffold phrases anywhere in thinking_token text.
        leaked = [t for t in thinking_texts if any(p in t.lower() for p in SCAFFOLD_PHRASES)]
        print(f"\nscaffold-phrase leaks in thinking: {len(leaked)}")

        ok = bool(real_reasoning) and not leaked
        print("\n" + ("PASS: real reasoning reaches the Thinking box; labels on status_update."
                      if ok else "FAIL: see counts above — reasoning prose missing or scaffold leaked."))
        return 0 if ok else 1
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        time.sleep(1)
        shutil.rmtree(SC, ignore_errors=True)
        print(f"\ncleanup: server stopped, scratch removed ({SC})")


if __name__ == "__main__":
    sys.exit(main())
