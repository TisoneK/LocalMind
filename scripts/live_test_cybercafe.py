#!/usr/bin/env python3
"""
Session 332-A: Live-trace reproduction of the cyber-café duplicate-answer bug.

Boots LocalMind on isolated port 8765 + scratch LOCALMIND_HOME,
fires the cyber-café prompt, captures SSE, parses for duplicate-answer markers.

Usage:
  cd backend && ../scripts/live_test_cybercafe.py [--label baseline|fix-N]
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path("/home/z/my-project/localmind")
BACKEND = REPO / "backend"
VENV_PY = str(BACKEND / ".venv" / "bin" / "python")
SCRATCH = REPO / "scratch"
TRACEHOME = SCRATCH / "tracehome"
SETTINGS = TRACEHOME / "settings.json"

PROMPTS = [
    ("cybercafe", "Give me three ideas for improving a cyber café business."),
    ("hello", "Hello"),
    ("weather_simple", "What is the capital of France?"),
]


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
        preexec_fn=os.setsid,
    )
    # Wait for /api/health
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


def fire_chat(port: int, message: str, session_id: str, timeout: int = 240) -> str:
    """POST /api/chat, return raw SSE text."""
    import urllib.parse
    import urllib.request

    body = urllib.parse.urlencode(
        {"message": message, "session_id": session_id, "is_first": "true"}
    ).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/chat",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_sse(raw: str) -> dict:
    """Bucket SSE events by type."""
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        try:
            events.append(json.loads(payload))
        except json.JSONDecodeError:
            continue

    final_text_parts = []
    thinking_parts = []
    tool_calls = []
    turn_complete = None
    errors = []
    usage = None

    for ev in events:
        etype = ev.get("type")
        if etype == "token":
            final_text_parts.append(ev.get("content", ""))
        elif etype == "thinking_token":
            thinking_parts.append(ev.get("thinking", ""))
        elif etype == "tool_call":
            tool_calls.append(ev.get("tool_call", {}))
        elif etype == "done":
            turn_complete = ev
            usage = ev.get("provider_usage") or ev.get("usage")
        elif etype == "error":
            errors.append(ev.get("error", {}))

    return {
        "events": events,
        "final_text": "".join(final_text_parts),
        "thinking": "".join(thinking_parts),
        "tool_calls": tool_calls,
        "turn_complete": turn_complete,
        "errors": errors,
        "usage": usage,
        "event_type_counts": _count_types(events),
    }


def _count_types(events: list) -> dict:
    counts: dict[str, int] = {}
    for ev in events:
        t = ev.get("type", "?")
        counts[t] = counts.get(t, 0) + 1
    return counts


def analyze(label: str, prompt_name: str, prompt: str, parsed: dict, latency_s: float):
    """Return analysis dict + print summary."""
    text = parsed["final_text"]
    thinking = parsed["thinking"]
    n_tools = len(parsed["tool_calls"])

    # Detect duplicate-answer patterns
    # Heuristic 1: same opening line repeated ("Here are three" / "Great question")
    openers = re.findall(
        r"^(?:Here are three|Great question|Here's three|Sure,? here|Certainly,? here).*$",
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    # Heuristic 2: total word count > 250 for a "three ideas" prompt suggests duplication
    word_count = len(text.split())
    # Heuristic 3: distinct numbered/idea sections counted
    idea_markers = re.findall(r"^\s*(?:\d+\.|Idea\s*\d|^\s*-)\s", text, flags=re.MULTILINE)

    dup_suspected = len(openers) >= 2 or (word_count > 350 and len(idea_markers) > 6)

    print(f"\n{'='*72}")
    print(f"  LABEL      : {label}")
    print(f"  PROMPT     : {prompt_name!r} — {prompt[:60]!r}")
    print(f"  LATENCY    : {latency_s:.1f}s")
    print(f"  TOOLS      : {n_tools}")
    print(f"  EVENT TYPES: {parsed['event_type_counts']}")
    print(f"  USAGE      : {parsed['usage']}")
    if parsed["errors"]:
        print(f"  ERRORS     : {parsed['errors']}")
    print(f"  ANSWER LEN : {len(text)} chars, {word_count} words")
    print(f"  THINKING LEN: {len(thinking)} chars")
    print(f"  OPENERS FOUND: {openers}")
    print(f"  IDEA MARKERS : {len(idea_markers)} (e.g. {idea_markers[:3]})")
    print(f"  DUPLICATE SUSPECTED: {dup_suspected}")
    print(f"{'='*72}\n")

    return {
        "label": label,
        "prompt_name": prompt_name,
        "prompt": prompt,
        "latency_s": round(latency_s, 1),
        "n_tools": n_tools,
        "answer_chars": len(text),
        "answer_words": word_count,
        "thinking_chars": len(thinking),
        "openers_found": openers,
        "idea_markers_count": len(idea_markers),
        "duplicate_suspected": dup_suspected,
        "event_type_counts": parsed["event_type_counts"],
        "usage": parsed["usage"],
        "errors": parsed["errors"],
        "final_text_excerpt": text[:500] + ("…" if len(text) > 500 else ""),
        "thinking_excerpt": thinking[:300] + ("…" if len(thinking) > 300 else ""),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--prompts", default="cybercafe", help="comma list: cybercafe,hello,weather_simple")
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args()

    SCRATCH.mkdir(parents=True, exist_ok=True)
    TRACEHOME.mkdir(parents=True, exist_ok=True)

    port = 8765
    log_file = SCRATCH / f"server-{args.label}.log"

    # Kill any leftover
    subprocess.run(["pkill", "-f", f"LOCALMIND_PORT={port}"], check=False)
    time.sleep(1)

    print(f"[boot] starting server on port {port}, log → {log_file}")
    proc = None
    try:
        proc = boot_server(port, log_file)
        print(f"[boot] server ready (pid={proc.pid})")

        results = []
        for name in args.prompts.split(","):
            name = name.strip()
            prompt = dict(PROMPTS).get(name)
            if prompt is None:
                print(f"[skip] unknown prompt {name!r}")
                continue
            sid = f"s332-{name}-{int(time.time())}"
            sse_file = SCRATCH / f"sse-{args.label}-{name}.sse"
            print(f"\n[trace] {name}: {prompt!r}")
            t0 = time.time()
            raw = fire_chat(port, prompt, sid, timeout=args.timeout)
            latency = time.time() - t0
            sse_file.write_text(raw, encoding="utf-8")
            print(f"[trace] saved {sse_file} ({len(raw)} bytes, {latency:.1f}s)")

            parsed = parse_sse(raw)
            summary = analyze(args.label, name, prompt, parsed, latency)
            results.append(summary)

            # Cooldown for bankofai rate limit
            time.sleep(8)

        out = SCRATCH / f"results-{args.label}.json"
        out.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\n[done] results → {out}")

    finally:
        if proc is not None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                time.sleep(1)
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass
        subprocess.run(["pkill", "-f", f"LOCALMIND_PORT={port}"], check=False)


if __name__ == "__main__":
    main()
