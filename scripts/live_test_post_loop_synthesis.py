#!/usr/bin/env python3
"""Session 308 live verification — post-loop evidence synthesis.

Before (Session 307): glm-4.5-flash executed real tools (describe_tool → shell)
but ended with a 0-char final answer (recovery cap hit, no synthesis fired).

After (this session): the post-loop synthesis should fire and produce a real
answer from the gathered tool evidence.
"""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time, urllib.request, urllib.parse
from pathlib import Path
from collections import Counter

PORT = "8765"
REPO = Path(__file__).resolve().parent.parent
SC = REPO / "scratch" / "lm-post-loop"
TH = SC / "tracehome"
BACKEND = REPO / "backend"
from harness_common import provider_key, venv_python

VENV_PY = venv_python(BACKEND)
ZAI_KEY = provider_key("zai")  # env ZAI_API_KEY or ~/LocalMind/settings.json - never printed
if not ZAI_KEY:
    sys.exit("ERROR: no zai key in env (ZAI_API_KEY) or ~/LocalMind/settings.json")
def setup():
    if SC.exists(): shutil.rmtree(SC)
    SC.mkdir(parents=True); TH.mkdir(parents=True)
    (TH / "settings.json").write_text(json.dumps({
        "adapter": "zai", "model": "glm-4.5-flash", "thinking": "enabled",
        "reasoning_effort": "low", "shell_enabled": True, "api_keys": {"zai": ZAI_KEY},
    }))

def boot():
    env = os.environ.copy()
    env.update({"LOCALMIND_PORT": PORT, "LOCALMIND_HOME": str(TH),
                "LOCALMIND_ADAPTER": "zai", "LOCALMIND_SHELL_ENABLED": "true",
                "PYTHONPATH": str(BACKEND / "src")})
    log = open(SC / "trace.log", "w")
    proc = subprocess.Popen([VENV_PY, "server.py"], cwd=str(BACKEND), env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(40):
        try: urllib.request.urlopen(f"http://localhost:{PORT}/api/health", timeout=2); return proc
        except: time.sleep(0.5)
    return None

def send_turn(sid, msg, timeout=300):
    data = urllib.parse.urlencode({"message": msg, "session_id": sid, "is_first": "false"}).encode()
    req = urllib.request.Request(f"http://localhost:{PORT}/api/chat", data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.read().decode("utf-8", errors="replace")
    except Exception as e: return f"<EXCEPTION: {e}>"

def parse_events(sse):
    events = []
    for line in sse.splitlines():
        if line.startswith("data: ") and '"type"' in line:
            try: events.append(json.loads(line[6:]))
            except: pass
    return events

def main():
    setup(); proc = boot()
    if not proc: print("boot failed"); return 1
    print(f"[boot] server alive on {PORT}")
    try:
        time.sleep(2)
        log = (SC / "trace.log").read_text()
        ready = [l for l in log.splitlines() if "[parent-kernel]" in l]
        for l in ready: print(f"  {l.strip()}")

        sid = f"postloop-{int(time.time())}"
        # The exact task from Session 307 that ended 0-char.
        msg = "Please list the files in the /tmp directory using the shell tool."
        print(f"\n[turn] {msg!r}")
        sse = send_turn(sid, msg, timeout=300)
        (SC / "turn.sse").write_text(sse)
        log_after = (SC / "trace.log").read_text()

        if "429" in sse or "429" in log_after:
            print("[SKIP] z.ai 429 — rate-limited")
            return 2

        events = parse_events(sse)
        # Extract final text
        final = ""
        for e in events:
            if e.get("type") == "token" and e.get("data", {}).get("content"):
                final += e["data"]["content"]
        print(f"\n[final] {len(final)} chars")
        if final:
            print(f"[final] preview: {final[:400]!r}")

        # Check for the post_loop_synthesis event
        has_post_loop = any(
            "post_loop_synthesis" in str(e) for e in events
        ) or "post-loop evidence synthesis" in log_after
        print(f"\n[check] post_loop_synthesis fired: {has_post_loop}")

        # Check tool execution
        has_shell = "tool_call=shell" in log_after or "tool=shell" in log_after
        has_describe = "describe_tool" in log_after
        print(f"[check] describe_tool loaded: {has_describe}")
        print(f"[check] shell tool_call executed: {has_shell}")

        # Iterations
        iters = [l for l in log_after.splitlines() if "iter=" in l and "LLM:" in l]
        print(f"[check] iterations: {len(iters)}")

        # Key log lines
        key = [l for l in log_after.splitlines() if any(k in l.lower() for k in ["synthesis", "rescue", "empty", "finished", "post-loop"])]
        for l in key[-8:]:
            print(f"  log: {l.strip()[:180]}")

        print("\n[VERDICT]")
        if final and len(final) >= 20:
            print(f"  ✅ NON-EMPTY final answer ({len(final)} chars) — B-2026-08-20-7 FIXED")
            if has_post_loop:
                print("  ✅ post_loop_synthesis event confirmed in log")
            return 0
        elif has_post_loop:
            print("  ⚠️  post_loop_synthesis fired but final text still short — synthesis may have returned trivial")
            return 1
        else:
            print("  ❌ empty final answer — post_loop_synthesis did NOT fire (model may not have hit the empty-response fallthrough)")
            return 1
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except: proc.kill()

if __name__ == "__main__": sys.exit(main())
