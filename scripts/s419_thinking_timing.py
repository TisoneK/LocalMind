#!/usr/bin/env python3
"""Session 419 live check: thinking_token STREAMING on the forced-final path.

Boots the isolated 8765 server (scratch LOCALMIND_HOME), fires a prompt that
exhausts the iteration budget on a thinking model, and timestamps every SSE
event. PASS requires: >1 thinking_token AND the first-to-last thinking_token
span >> flush-burst (~1ms) AND no error. Artifacts in scratch/.
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
sys.path.insert(0, str(REPO / "scripts"))
from harness_common import kill_port, kill_process_tree, server_popen_kwargs, venv_python

VENV_PY = venv_python(BACKEND)
SCRATCH = REPO / "scratch"
TRACEHOME = SCRATCH / "tracehome"

PROMPT = (
    "Read the file C:/Users/tison/Documents/localmind-s419-evidence.txt and then "
    "list every file on my Desktop, summarise each one, and write a full "
    "report to s419-report.md with a ten-point research plan"
)


def boot_server(port: int, log_file: Path):
    import os
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
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2).read()
            return proc
        except Exception:
            time.sleep(1)
    proc.kill()
    raise RuntimeError("server failed to start within 45s")


import subprocess  # noqa: E402


def fire_chat(port: int, message: str, session_id: str, timeout: int = 240):
    """POST /api/chat, stream line-by-line with ARRIVAL timestamps.

    Returns (stamped_lines, wall_seconds). The stamp is taken per line as the
    socket delivers it — stamping after resp.read() would measure parse time,
    not arrival time (that artifact produced a fake 0.4ms span once already).
    """
    t0 = time.monotonic()
    body = urllib.parse.urlencode(
        {"message": message, "session_id": session_id, "is_first": "true"}
    ).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/chat",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    stamped: list[tuple[float, str]] = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw_line in resp:
            stamped.append((time.monotonic(), raw_line.decode("utf-8", errors="replace")))
    return stamped, time.monotonic() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--label", default="fix-1")
    args = ap.parse_args()

    evidence = TRACEHOME / "localmind-s419-evidence.txt"
    TRACEHOME.mkdir(parents=True, exist_ok=True)
    evidence.write_text("LocalMind s419 live-test evidence file. Contains the word banana three times: banana banana banana.", encoding="utf-8")

    log = SCRATCH / f"s419-server-{args.label}.log"
    raw_path = SCRATCH / f"s419-sse-{args.label}.sse"
    proc = None
    try:
        kill_port(args.port)
        proc = boot_server(args.port, log)
        stamped_lines, elapsed = fire_chat(args.port, PROMPT, f"s419-thinking-{args.label}")
        raw_path.write_text("".join(l for _, l in stamped_lines), encoding="utf-8")

        stamps = []
        for ts, line in stamped_lines:
            line = line.strip()
            if not line.startswith("data: "):
                continue
            try:
                ev = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            stamps.append((ts, ev))
        think_stamps = [s for s, ev in stamps if ev.get("type") == "thinking_token"]
        think_texts = [
            ev.get("thinking", "") for _, ev in stamps if ev.get("type") == "thinking_token"
        ]
        errors = [ev for _, ev in stamps if ev.get("type") == "error"]
        done = [ev for _, ev in stamps if ev.get("type") == "done"]

        print(f"turn wall: {elapsed:.1f}s | events: {len(stamps)}")
        print(f"thinking_token events: {len(think_stamps)}")
        print(f"error events: {len(errors)} | done: {bool(done)}")
        if len(think_stamps) >= 2:
            span_ms = (think_stamps[-1] - think_stamps[0]) * 1000
            print(f"first→last thinking_token span: {span_ms:.1f}ms")
            print(f"thinking chars: {sum(len(t) for t in think_texts)}")
            verdict = "PASS" if span_ms > 200 and not errors else "FAIL"
        else:
            print("too few thinking_token events to measure a span")
            verdict = "INCONCLUSIVE" if errors else "FAIL"
        if errors:
            print("error payloads (first 2):", json.dumps(errors[:2])[:400])
        print(f"VERDICT: {verdict}")
        return 0 if verdict == "PASS" else 1
    finally:
        if proc:
            kill_process_tree(proc.pid)


if __name__ == "__main__":
    sys.exit(main())
