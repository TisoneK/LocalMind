#!/usr/bin/env python3
"""Fast-path gate + parent-only catalog live traces.

Probes (baseline vs fix-N on the SAME prompts, isolated port 8765 + scratch
LOCALMIND_HOME, per memory/system/live-testing.md):

- hi_hint      "Hi" sent WITH the UI's X-LocalMind-Intent: chat header —
               the regression probe. Before the fix the header DISABLES the
               trivial fast-path (full init+Thinker+iteration pipeline);
               after the fix it must take the zero-provider-call canned
               reply (<2s, no thinker/init events, no provider usage).
- hello_plain  "Hello" with no header — control; already fast-paths on main.
- ram          "How much RAM do I have?" — tool-SELECTION probe (sysinfo)
               for the ADR-40 guardrail when the catalog changes.
- find_cv      "Find my CV file on this computer" — tool-SELECTION probe
               (system_search).

Usage:
  cd backend && ../scripts/live_test_s426_fastpath.py --label baseline \
      --prompts hi_hint,ram,find_cv
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
SCRATCH = REPO / "scratch" / "s426"
TRACEHOME = SCRATCH / "tracehome"

# (name, message, headers) — headers mimic what the Electron UI sends
# (client.ts streamChat: X-LocalMind-Intent + X-Intent-Confidence).
PROMPTS = [
    ("hi_hint", "Hi", {"X-LocalMind-Intent": "chat", "X-Intent-Confidence": "1.0"}),
    ("hello_plain", "Hello", None),
    ("ram", "How much RAM do I have?", None),
    ("find_cv", "Find my CV file on this computer", None),
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


def fire_chat(port: int, message: str, session_id: str, headers=None, timeout: int = 240) -> tuple[str, float]:
    """POST /api/chat, return (raw SSE text, wall seconds)."""
    body = urllib.parse.urlencode(
        {"message": message, "session_id": session_id, "is_first": "true"}
    ).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/chat",
        data=body,
        headers=dict(UI_HEADERS | (headers or {})),
        method="POST",
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return raw, time.monotonic() - t0


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

    text_parts, thinking_parts, tool_calls, errors = [], [], [], []
    stage_timings, usage, thinker_events = [], None, []
    for ev in events:
        etype = ev.get("type")
        if etype == "token":
            text_parts.append(ev.get("content", ""))
        elif etype == "thinking_token":
            thinking_parts.append(ev.get("thinking", ""))
        elif etype == "tool_call":
            tool_calls.append(ev.get("tool_call", {}))
        elif etype == "obs_event":
            d = ev.get("obs", {}) or {}
            if d.get("type") in ("agent_thinker_start", "agent_thinker_done"):
                thinker_events.append(d.get("type"))
            if d.get("type") == "stage_timing":
                stage_timings.append(
                    f"{d.get('stage')}={d.get('latency_ms')}ms({d.get('status')})"
                )
        elif etype == "error":
            errors.append(str(ev.get("error", {}))[:200])
        if etype == "done":
            usage = ev.get("provider_usage") or ev.get("usage")

    return {
        "final_text_head": "".join(text_parts)[:160],
        "tool_calls": [
            {"name": tc.get("name"), "latency_ms": tc.get("latency_ms")}
            for tc in tool_calls
        ],
        "thinker_events": thinker_events,
        "stage_timings": stage_timings,
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--prompts", default="hi_hint,ram,find_cv",
                    help="comma list: hi_hint,hello_plain,ram,find_cv")
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--port", type=int, default=8766,
                    help="isolated port — S426 uses 8766; 8765 belongs to the "
                         "S425 peer (shared-port kill_port collisions logged "
                         "as S426 inefficiency)")
    args = ap.parse_args()

    SCRATCH.mkdir(parents=True, exist_ok=True)
    TRACEHOME.mkdir(parents=True, exist_ok=True)

    port = args.port
    log_file = SCRATCH / f"server-{args.label}.log"
    kill_port(port)
    time.sleep(1)

    print(f"[boot] port {port}, log → {log_file}")
    proc = None
    results = []
    try:
        proc = boot_server(port, log_file)
        print(f"[boot] ready (pid={proc.pid})")
        for name in args.prompts.split(","):
            name = name.strip()
            entry = next((p for p in PROMPTS if p[0] == name), None)
            if entry is None:
                print(f"[skip] unknown prompt {name}")
                continue
            _, message, headers = entry
            sid = f"s426-{args.label}-{name}-{int(time.time())}"
            print(f"[run] {name}: {message!r} headers={headers or '-'}")
            raw, wall = fire_chat(port, message, sid, headers=headers,
                                  timeout=args.timeout)
            (SCRATCH / f"sse-{args.label}-{name}.sse").write_text(
                raw, encoding="utf-8", errors="replace")
            parsed = parse_sse(raw)
            parsed.update({"name": name, "wall_s": round(wall, 1),
                           "session_id": sid})
            results.append(parsed)
            print(f"  → {wall:.1f}s | tools={parsed['tool_calls']} | "
                  f"thinker={len(parsed['thinker_events'])} | "
                  f"usage={parsed['usage']}")
            print(f"  text: {parsed['final_text_head'][:100]}")
            time.sleep(3)  # free-tier cooldown
    finally:
        if proc is not None:
            kill_process_tree(proc.pid)
        kill_port(port)

    out = SCRATCH / f"results-{args.label}.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"[done] {len(results)} traces → {out}")


if __name__ == "__main__":
    main()
