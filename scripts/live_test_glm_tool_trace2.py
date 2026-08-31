#!/usr/bin/env python3
"""Session 306 retry — more direct task + provider fallback.
The first trace showed the model produce a prose 'I'll describe the shell tool'
preamble but never emit the actual tool_call. Try:
1. A more direct task: 'Run `uname -a` and tell me the output.'
2. If still no tool call, try Zen/hy3-free and DeepSeek as fallbacks.
"""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time, urllib.request, urllib.parse
from pathlib import Path
from collections import Counter

PORT = "8765"
REPO = Path(__file__).resolve().parent.parent
SC = REPO / "scratch" / "lm-glm-tool-trace2"
TH = SC / "tracehome"
BACKEND = REPO / "backend"
from harness_common import provider_key, venv_python

VENV_PY = venv_python(BACKEND)
# Keys resolved at runtime via provider_key() (env or settings.json) -
# never hardcoded, never printed.
MODELS = {"zai": "glm-4.5-flash", "zen": "hy3-free", "deepseek": "deepseek-chat"}


class _Keys:
    def __getitem__(self, provider: str):
        return (provider_key(provider), MODELS[provider])


KEYS = _Keys()

def setup(provider, model):
    if SC.exists(): shutil.rmtree(SC)
    SC.mkdir(parents=True); TH.mkdir(parents=True)
    (TH / "settings.json").write_text(json.dumps({
        "adapter": provider, "model": model, "thinking": "enabled",
        "reasoning_effort": "low", "shell_enabled": True,
        "api_keys": {provider: KEYS[provider][0]},
    }))

def boot(provider):
    env = os.environ.copy()
    env.update({"LOCALMIND_PORT": PORT, "LOCALMIND_HOME": str(TH),
                "LOCALMIND_ADAPTER": provider, "LOCALMIND_SHELL_ENABLED": "true",
                "PYTHONPATH": str(BACKEND / "src")})
    log = open(SC / "trace.log", "w")
    proc = subprocess.Popen([VENV_PY, "server.py"], cwd=str(BACKEND), env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://localhost:{PORT}/api/health", timeout=2); return proc
        except Exception: time.sleep(0.5)
    return None

def send_turn(sid, msg, timeout=180):
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

def run_one(provider, model, task):
    print(f"\n=== {provider}/{model} ===")
    print(f"   task: {task!r}")
    setup(provider, model)
    proc = boot(provider)
    if proc is None:
        print("   boot failed"); return None
    try:
        time.sleep(2)
        log_text = (SC / "trace.log").read_text()
        ready = [l for l in log_text.splitlines() if "[parent-kernel]" in l]
        for l in ready: print(f"   {l.strip()}")
        sid = f"tool-{provider}-{int(time.time())}"
        sse = send_turn(sid, task, timeout=180)
        (SC / f"{provider}_turn.sse").write_text(sse)
        log_after = (SC / "trace.log").read_text()
        if "429" in sse or "429" in log_after:
            print("   HIT 429 — skipping"); return {"hit_429": True}
        events = parse_events(sse)
        counts = Counter(e.get("type", "?") for e in events)
        # Strip thinking_token spam
        counts_no_think = {k: v for k, v in counts.items() if k != "thinking_token"}
        print(f"   events (excl thinking_token): {counts_no_think}")
        # Did a tool_call fire?
        tool_calls = [e for e in events if e.get("type") == "tool_call"]
        print(f"   tool_call events: {len(tool_calls)}")
        for tc in tool_calls[:3]:
            d = tc.get("data", {})
            print(f"     tool={d.get('tool')} status={d.get('status')}")
        # describe_tool?
        has_describe = any("describe_tool" in str(e) for e in events) or "describe_tool" in log_after
        print(f"   describe_tool loaded: {has_describe}")
        # Final text
        final = ""
        for e in events:
            if e.get("type") == "token" and e.get("data", {}).get("content"):
                final += e["data"]["content"]
        print(f"   final text: {final[:300]!r}")
        # Log key lines
        key_log = [l for l in log_after.splitlines() if any(k in l for k in ["iter=", "finished", "MiniMax", "gate", "empty", "replan", "ERROR"])]
        for l in key_log[-8:]:
            print(f"   log: {l.strip()[:150]}")
        return {
            "provider": provider, "has_tool_call": len(tool_calls) > 0,
            "has_describe": has_describe, "final_text": final,
            "tool_calls": [{"tool": tc.get("data", {}).get("tool"), "status": tc.get("data", {}).get("status")} for tc in tool_calls[:3]],
        }
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except: proc.kill()

def main():
    tasks = [
        "Run the shell command `uname -a` and tell me the output.",
        "What files are in the /tmp directory? Use the shell tool to find out.",
    ]
    results = []
    for provider in ["zai", "zen", "deepseek"]:
        if not provider_key(provider):
            print(f"[skip] {provider}: no key in env/settings")
            continue
        model = KEYS[provider][1]
        for task in tasks:
            r = run_one(provider, model, task)
            if r is None: continue
            if r.get("hit_429"): continue
            results.append(r)
            if r.get("has_tool_call"):
                print(f"\n[SUCCESS] {provider} emitted a real tool_call")
                return 0
            # If no tool call, try the other task on this provider before moving on
        # Move to next provider
    print("\n[SUMMARY]")
    for r in results:
        print(f"  {r['provider']}: tool_call={r.get('has_tool_call')} describe={r.get('has_describe')} final={r.get('final_text','')[:80]!r}")
    if any(r.get("has_tool_call") for r in results):
        return 0
    print("\n[FAIL] no provider emitted a tool_call on either task")
    return 1

if __name__ == "__main__": sys.exit(main())
