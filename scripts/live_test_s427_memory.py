#!/usr/bin/env python3
"""S427: memory-evidence live trace — replays the user's EPL transcript.

Three turns on ONE session (multi-turn), isolated port 8766 + scratch
LOCALMIND_HOME, per memory/system/live-testing.md:

1. "Show me epl table"            → parent loop, web_search + web_fetch.
2. "Remember the source for EPL table"
     BEFORE S427: stored the literal phrase "source for EPL table"
     (confirmed "Remembered: source for EPL table") — the URL in turn 1's
     context was never consulted.
     AFTER: one bounded resolution call over the conversation evidence →
     stores the RESOLVED fact (contains the URL) and the confirmation
     echoes the resolved content.
3. "What's it?"                   → conversational fast path with recent
     memories injected → the answer should name the Sky Sports source.

Verification targets (grep the SSE + the scratch home's vector_facts):
  - turn2 text contains "skysports.com" (resolved echo, not bare phrase)
  - vector_facts content for this session contains "skysports.com"
  - turn3 text mentions the source

Usage:
  cd backend && .venv/Scripts/python.exe ../scripts/live_test_s427_memory.py \
      --label after [--turns 1,2,3]
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_common import kill_port, kill_process_tree, server_popen_kwargs, venv_python

VENV_PY = venv_python(BACKEND)
SCRATCH = REPO / "scratch" / "s427"
TRACEHOME = SCRATCH / "tracehome"

TURNS = [
    ("turn1_search", "Show me epl table"),
    ("turn2_remember", "Remember the source for EPL table"),
    ("turn3_whatsit", "What's it?"),
]

UI_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}


def boot_server(port: int, log_file: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env.update(
        {
            "LOCALMIND_PORT": str(port),
            "LOCALMIND_HOME": str(TRACEHOME),
            "LOCALMIND_ADAPTER": "bankofai",
            "LOCALMIND_SHELL_ENABLED": "true",
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
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/health", timeout=2
            ).read()
            return proc
        except Exception:
            time.sleep(1)
    proc.kill()
    raise RuntimeError("server failed to start within 45s")


def fire_chat(port: int, message: str, session_id: str, timeout: int = 240) -> tuple[str, float]:
    body = urllib.parse.urlencode(
        {"message": message, "session_id": session_id, "is_first": "true"}
    ).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/chat",
        data=body,
        headers=dict(UI_HEADERS),
        method="POST",
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return raw, time.monotonic() - t0


def final_text(raw: str) -> str:
    parts = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data: "):
            continue
        try:
            ev = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "token":
            parts.append(ev.get("content", ""))
    return "".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="after")
    ap.add_argument("--turns", default="1,2,3",
                    help="comma list of turn numbers 1..3")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args()

    SCRATCH.mkdir(parents=True, exist_ok=True)
    TRACEHOME.mkdir(parents=True, exist_ok=True)

    port = args.port
    log_file = SCRATCH / f"server-{args.label}.log"
    kill_port(port)
    time.sleep(1)

    session_id = f"s427-{args.label}-{int(time.time())}"
    print(f"[boot] port {port}, session {session_id}, log → {log_file}")
    proc = None
    results = []
    try:
        proc = boot_server(port, log_file)
        print(f"[boot] ready (pid={proc.pid})")
        for num in args.turns.split(","):
            name, message = TURNS[int(num) - 1]
            print(f"[run] {name}: {message!r}")
            raw, wall = fire_chat(port, message, session_id, timeout=args.timeout)
            (SCRATCH / f"sse-{args.label}-{name}.sse").write_text(
                raw, encoding="utf-8", errors="replace"
            )
            text = final_text(raw)
            results.append(
                {"turn": name, "wall_s": round(wall, 1), "text_head": text[:200]}
            )
            print(f"  → {wall:.1f}s | text: {text[:140]}")
            time.sleep(4)  # free-tier cooldown
    finally:
        if proc is not None:
            kill_process_tree(proc.pid)
        kill_port(port)

    out = SCRATCH / f"results-{args.label}.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"[done] {len(results)} turns → {out}")
    print(f"[next] check stored fact: {TRACEHOME}/memory_store (grep skysports)")


if __name__ == "__main__":
    main()
