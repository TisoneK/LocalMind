#!/usr/bin/env python3
"""Quick live test: trigger ParentSession compaction with 8 turns.
Verifies the rolling summary appears in /api/observability after >6 turns.
"""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time, urllib.request, urllib.parse
from pathlib import Path
from collections import Counter

PORT = "8765"
REPO = Path(__file__).resolve().parent.parent
SC = REPO / "scratch" / "lm-compaction-scratch"
TH = SC / "tracehome"
BACKEND = REPO / "backend"
from harness_common import venv_python

VENV_PY = venv_python(BACKEND)
ZAI_KEY = "a9fa08105a9a4127805da89d23da59f0.j51uE0L0dw2H1rV6"

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
        except Exception: time.sleep(0.5)
    return None

def send_turn(sid, msg):
    data = urllib.parse.urlencode({"message": msg, "session_id": sid, "is_first": "false"}).encode()
    req = urllib.request.Request(f"http://localhost:{PORT}/api/chat", data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=90) as r: return r.read().decode("utf-8", errors="replace")
    except Exception as e: return f"<EXCEPTION: {e}>"

def main():
    setup(); proc = boot()
    if not proc: print("boot failed"); return 1
    print("[boot] ok")
    try:
        sid = f"compact-{int(time.time())}"
        msgs = [
            "Hi, I'm planning a small vegetable garden.",
            "What vegetables grow well together?",
            "How much sun does tomato need?",
            "What about carrots — are they good companions?",
            "Tell me about soil preparation.",
            "When should I water the garden?",
            "What pests should I watch for?",
            "Summarize what we've discussed so far.",
        ]
        for i, m in enumerate(msgs, 1):
            sse = send_turn(sid, m)
            print(f"  turn {i} done ({len(sse)} bytes)")
            time.sleep(0.5)
        # Check observability
        with urllib.request.urlopen(f"http://localhost:{PORT}/api/observability/{sid}", timeout=10) as r:
            obs = json.loads(r.read())
        print(f"\n[observability] turn_count = {obs.get('parent_session_turn_count')}")
        summary = obs.get('parent_session_summary') or ''
        print(f"[observability] summary present: {bool(summary)}")
        print(f"[observability] summary chars: {len(summary)}")
        if summary:
            print(f"[observability] summary preview: {summary[:300]!r}")
            assert obs.get('parent_session_turn_count') == 8, f"expected 8, got {obs.get('parent_session_turn_count')}"
            assert "tomato" in summary.lower() or "carrots" in summary.lower() or "garden" in summary.lower(), \
                "summary should mention earlier topics"
            print("\n[RESULT] compaction verified — rolling summary present after 8 turns")
            return 0
        else:
            print("\n[WARN] no summary yet (turn_count should be 8 > RECENT_TAIL_MAX=6)")
            return 1
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except: proc.kill()

if __name__ == "__main__": sys.exit(main())
