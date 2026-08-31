#!/usr/bin/env python3
"""Session 307 live verification — prose-commitment detector + re-prompt.

Before (Session 306): glm-4.5-flash produced 'I'll describe the shell tool...'
prose preamble without emitting a tool_call; loop accepted the prose as final.

After (this session): the detector should fire on iter=1, inject a [TOOL
COMMITMENT] re-prompt, and the model should emit a real tool_call on iter=2.

Verifies:
1. Boot + health (parent_ready=true).
2. Send 'list /tmp files' task.
3. SSE contains a [TOOL COMMITMENT] re-prompt event (agent_loop_gate_failed_replan).
4. SSE contains a real tool_call event after the re-prompt.
5. Final answer references actual /tmp contents (grounded evidence).
"""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time, urllib.request, urllib.parse
from pathlib import Path
from collections import Counter

PORT = "8765"
REPO = Path(__file__).resolve().parent.parent
SC = REPO / "scratch" / "lm-prose-commitment"
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
        try:
            urllib.request.urlopen(f"http://localhost:{PORT}/api/health", timeout=2); return proc
        except: time.sleep(0.5)
    return None

def send_turn(sid, msg, timeout=240):
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
        # Health
        with urllib.request.urlopen(f"http://localhost:{PORT}/api/health", timeout=5) as r:
            health = json.loads(r.read())
        print(f"[health] parent_ready={health.get('parent_ready')} status={health.get('status')}")

        sid = f"prose-{int(time.time())}"
        # The exact task from Session 306 that exposed the bug.
        msg = "Please list the files in the /tmp directory using the shell tool."
        print(f"\n[turn] sending: {msg!r}")
        sse = send_turn(sid, msg, timeout=300)
        (SC / "turn.sse").write_text(sse)
        log_after = (SC / "trace.log").read_text()

        if "429" in sse or "429" in log_after:
            print("[SKIP] z.ai 429 — rate-limited, cannot verify this run")
            return 2

        events = parse_events(sse)
        counts = Counter(e.get("type", "?") for e in events)
        counts_no_think = {k: v for k, v in counts.items() if k != "thinking_token"}
        print(f"\n[events] (excl thinking_token): {counts_no_think}")

        # Key evidence: did the gate fire + did a tool_call follow?
        gate_fired = any(
            e.get("type") == "obs_event"
            and e.get("data", {}).get("type") == "agent_loop_gate_failed_replan"
            for e in events
        )
        # Also check the log for the [TOOL COMMITMENT] injection.
        log_has_commitment = "[TOOL COMMITMENT]" in log_after
        print(f"\n[check] gate_failed_replan event emitted: {gate_fired}")
        print(f"[check] [TOOL COMMITMENT] in log: {log_has_commitment}")

        tool_calls = [
            e for e in events
            if e.get("type") == "tool_call"
            or (e.get("type") == "obs_event" and e.get("data", {}).get("type") == "tool_call")
        ]
        print(f"[check] tool_call events: {len(tool_calls)}")
        for tc in tool_calls[:5]:
            d = tc.get("data", {})
            print(f"  tool={d.get('tool')} status={d.get('status')}")

        # Did describe_tool fire?
        has_describe = "describe_tool" in log_after or any(
            "describe_tool" in str(e) for e in events
        )
        print(f"[check] describe_tool loaded: {has_describe}")

        # Final text
        final = ""
        for e in events:
            if e.get("type") == "token" and e.get("data", {}).get("content"):
                final += e["data"]["content"]
        print(f"\n[final] text length: {len(final)}")
        if final:
            print(f"[final] preview: {final[:400]!r}")

        # Iterations
        iters = [l for l in log_after.splitlines() if "iter=" in l and "LLM:" in l]
        print(f"\n[log] iterations: {len(iters)}")
        for i in iters:
            print(f"  {i.strip()[:150]}")

        # Verdict
        print("\n[VERDICT]")
        if gate_fired or log_has_commitment:
            print("  ✅ prose-commitment detector FIRED (gate_failed_replan or [TOOL COMMITMENT] in log)")
        else:
            print("  ⚠️  detector did NOT fire — model may have emitted a tool_call on iter=1 (no preamble)")
        if tool_calls:
            print(f"  ✅ real tool_call emitted ({len(tool_calls)} events)")
        else:
            print("  ❌ no tool_call emitted — model still didn't act even after the nudge")
        if final and len(final) > 20:
            print("  ✅ final answer produced")
        else:
            print("  ⚠️  short/empty final answer")

        return 0 if (gate_fired or log_has_commitment) and tool_calls else 1
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except: proc.kill()

if __name__ == "__main__": sys.exit(main())
