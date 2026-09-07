#!/usr/bin/env python3
"""
Session 438 — live-trace the post-evidence over-thinking gap.

The reported failure shape: after web_fetch returned the weather JSON, the
loop kept "thinking" (~88s of reasoning for a one-line answer) instead of
synthesizing promptly. This harness boots the isolated server, fires the
weather prompts, and measures the ADR-57 metrics that item is about:

  - wall latency
  - time-to-first-visible-token (TTFT)
  - POST-EVIDENCE TTFT: time from the last tool_call "done" event to the
    first visible token event — the "evidence in hand, now answer" gap
  - LLM calls per turn + their serial cost (from the server log)
  - thinking volume streamed while the user waits

Usage:
  cd backend && ../scripts/live_test_s438_overthink.py --label baseline --port 8766
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_common import kill_port, server_popen_kwargs, venv_python

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"

VENV_PY = venv_python(BACKEND)
SCRATCH = REPO / "scratch"
TRACEHOME = SCRATCH / "s438" / "tracehome"

# The B-2026-08-30-8 shape: a tool puts the answer-bearing evidence in the
# transcript, and the turn should synthesize promptly. Both prompts force a
# web fetch (realtime keywords route them out of the fast paths).
PROMPTS = [
    (
        "weather",
        "What's the weather in Nairobi today? Find the current temperature.",
    ),
    (
        "wttr_fetch",
        "Fetch https://wttr.in/Nairobi?format=j1 and tell me the current temperature in Nairobi.",
    ),
]


def boot_server(port: int, log_file: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env.update(
        {
            "LOCALMIND_PORT": str(port),
            "LOCALMIND_HOME": str(TRACEHOME),
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


def fire_chat_streamed(port: int, message: str, session_id: str, timeout: int = 300):
    """POST /api/chat, return (raw_sse, timeline) where timeline is [(t, type)]."""
    body = urllib.parse.urlencode(
        {"message": message, "session_id": session_id, "is_first": "true"}
    ).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/chat",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    t0 = time.monotonic()
    raw_parts: list[str] = []
    timeline: list[tuple[float, str]] = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for line in resp:
            text = line.decode("utf-8", errors="replace")
            raw_parts.append(text)
            s = text.strip()
            if s.startswith("data: "):
                try:
                    ev = json.loads(s[6:])
                    timeline.append((time.monotonic() - t0, ev.get("type", "?")))
                except json.JSONDecodeError:
                    pass
    return "".join(raw_parts), timeline


def parse_sse(raw: str) -> dict:
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data: "):
            continue
        try:
            events.append(json.loads(line[6:]))
        except json.JSONDecodeError:
            continue
    final_text, thinking, tool_events, turn_complete, errors = [], [], [], None, []
    for ev in events:
        etype = ev.get("type")
        if etype == "token":
            final_text.append(ev.get("content", ""))
        elif etype == "thinking_token":
            thinking.append(ev.get("thinking", ""))
        elif etype == "tool_call":
            tool_events.append(ev)
        elif etype == "done":
            turn_complete = ev
        elif etype == "error":
            errors.append(ev.get("error", {}))
    return {
        "final_text": "".join(final_text),
        "thinking": "".join(thinking),
        "tool_events": tool_events,
        "turn_complete": turn_complete,
        "errors": errors,
        "event_type_counts": _count_types(events),
    }


def _count_types(events: list) -> dict:
    counts: dict[str, int] = {}
    for ev in events:
        t = ev.get("type", "?")
        counts[t] = counts.get(t, 0) + 1
    return counts


def timeline_metrics(timeline: list[tuple[float, str]]) -> dict:
    """TTFT + post-evidence gap from the timestamped event stream."""
    ttft = None
    for t, etype in timeline:
        if etype == "token" and ttft is None:
            ttft = t
            break
    last_tool_done = None
    for t, etype in timeline:
        if etype == "tool_call":
            last_tool_done = t
    post_tool_ttft = None
    if last_tool_done is not None:
        for t, etype in timeline:
            if etype == "token" and t > last_tool_done:
                post_tool_ttft = round(t - last_tool_done, 2)
                break
    return {
        "ttft_s": round(ttft, 2) if ttft is not None else None,
        "last_tool_done_s": round(last_tool_done, 2) if last_tool_done else None,
        "post_tool_ttft_s": post_tool_ttft,
    }


def parse_llm_calls(log_file: Path) -> list[dict]:
    """Per-iteration LLM call costs from the server log."""
    calls = []
    try:
        text = log_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return calls
    for m in re.finditer(r"iter=(\d+) LLM: (\d+)ms", text):
        calls.append({"iter": int(m.group(1)), "ms": int(m.group(2))})
    return calls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--prompts", default="weather,wttr_fetch")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    TRACEHOME.mkdir(parents=True, exist_ok=True)
    if not (TRACEHOME / "settings.json").exists():
        raise SystemExit(
            f"no settings.json at {TRACEHOME / 'settings.json'} — stage it from "
            "the real app home first (never print its contents)"
        )

    out_dir = SCRATCH / "s438"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_file = out_dir / f"server-{args.label}-{args.port}.log"

    kill_port(args.port)
    time.sleep(1)

    print(f"[boot] port {args.port}, log → {log_file}")
    proc = None
    try:
        proc = boot_server(args.port, log_file)
        print(f"[boot] server ready (pid={proc.pid})")
        log_text = log_file.read_text(encoding="utf-8", errors="replace")
        if "already in use" in log_text:
            raise RuntimeError("PORT COLLISION: server log says 'already in use' — trace would be invalid")
        if "ready" not in log_text:
            raise RuntimeError("no 'ready' line in server log — boot unverified")

        results = []
        for name, prompt in PROMPTS:
            if name not in args.prompts.split(","):
                continue
            sid = f"s438-{args.label}-{name}-{int(time.time())}"
            sse_file = out_dir / f"sse-{args.label}-{name}.sse"
            print(f"\n[trace] {name}: {prompt[:60]!r}")
            raw, timeline = fire_chat_streamed(args.port, prompt, sid, timeout=args.timeout)
            sse_file.write_text(raw, encoding="utf-8")
            parsed = parse_sse(raw)
            tmet = timeline_metrics(timeline)
            llm_calls = parse_llm_calls(log_file)
            wall = timeline[-1][0] if timeline else None
            summary = {
                "label": args.label,
                "prompt_name": name,
                "wall_s": round(wall, 2) if wall is not None else None,
                **tmet,
                "tools": [
                    {"tool": ev.get("tool_call", {}).get("tool") or ev.get("tool"),
                     "status": ev.get("status"),
                     "latency_ms": ev.get("tool_call", {}).get("latency_ms")}
                    for ev in parsed["tool_events"]
                ],
                "llm_calls_this_log": llm_calls,
                "llm_total_s": round(sum(c["ms"] for c in llm_calls) / 1000, 2),
                "thinking_chars": len(parsed["thinking"]),
                "answer_chars": len(parsed["final_text"]),
                "answer_excerpt": parsed["final_text"][:400],
                "event_type_counts": parsed["event_type_counts"],
                "usage": (parsed["turn_complete"] or {}).get("provider_usage"),
                "errors": parsed["errors"],
            }
            results.append(summary)
            print(json.dumps(summary, indent=2)[:2000])
            time.sleep(8)

        out = out_dir / f"results-{args.label}.json"
        out.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\n[done] results → {out}")
    finally:
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
        kill_port(args.port)


if __name__ == "__main__":
    main()
