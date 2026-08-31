#!/usr/bin/env python3
"""Live-test: web_fetch redirect fix + tool-failure recovery fix.
Task: 'Hey, whats the weather like in Cheptais rn' — the exact task
from the user's transcript that exposed both bugs."""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time, urllib.request, urllib.parse
from pathlib import Path

PORT = "8765"; SC = Path(__file__).resolve().parent.parent / "scratch" / "lm-cheptais"; TH = SC / "tracehome"
BACKEND = Path(__file__).resolve().parent.parent / "backend"
from harness_common import venv_python

VENV_PY = venv_python(BACKEND)
ZAI_KEY = "a9fa08105a9a4127805da89d23da59f0.j51uE0L0dw2H1rV6"

if SC.exists(): shutil.rmtree(SC)
SC.mkdir(parents=True); TH.mkdir(parents=True)
(TH / "settings.json").write_text(json.dumps({
    "adapter": "zai", "model": "glm-4.5-flash", "thinking": "enabled",
    "reasoning_effort": "low", "shell_enabled": True, "api_keys": {"zai": ZAI_KEY},
}))

env = os.environ.copy()
env.update({"LOCALMIND_PORT": PORT, "LOCALMIND_HOME": str(TH),
            "LOCALMIND_ADAPTER": "zai", "LOCALMIND_SHELL_ENABLED": "true",
            "PYTHONPATH": str(BACKEND / "src")})
log = open(SC / "trace.log", "w")
proc = subprocess.Popen([VENV_PY, "server.py"], cwd=str(BACKEND), env=env, stdout=log, stderr=subprocess.STDOUT)
for _ in range(40):
    try: urllib.request.urlopen(f"http://localhost:{PORT}/api/health", timeout=2); break
    except: time.sleep(0.5)

time.sleep(2)
sid = f"cheptais-{int(time.time())}"
msg = "Hey, whats the weather like in Cheptais rn"
print(f"[turn] {msg!r}")
data = urllib.parse.urlencode({"message": msg, "session_id": sid, "is_first": "true"}).encode()
req = urllib.request.Request(f"http://localhost:{PORT}/api/chat", data=data, method="POST")
req.add_header("Content-Type", "application/x-www-form-urlencoded")
t0 = time.monotonic()
try:
    with urllib.request.urlopen(req, timeout=300) as r: sse = r.read().decode("utf-8", errors="replace")
except Exception as e: sse = f"<EXC: {e}>"
elapsed = time.monotonic() - t0
(SC / "turn.sse").write_text(sse)
log_text = (SC / "trace.log").read_text()

# Parse
final = ""
for line in sse.splitlines():
    if line.startswith("data: ") and '"type": "token"' in line:
        try:
            p = json.loads(line[6:])
            final += p.get("content", "") or ""
        except: pass

print(f"\n[result] elapsed: {elapsed:.1f}s")
print(f"[result] final answer ({len(final.strip())} chars): {final.strip()[:400]!r}")
print(f"\n[checks]")
print(f"  429 rate-limited: {'429' in log_text}")
print(f"  web_fetch succeeded: {'web_fetch' in log_text and 'ventusky' in log_text}")
print(f"  web_fetch error (sync close): {'sync close on an async' in log_text}")
print(f"  agent_loop_failure emitted: {'agent_loop_failure' in log_text or 'Agent loop terminated' in sse}")
print(f"  tool_failure classified: {'tool_failure' in log_text}")

# Key log lines
print(f"\n[key log lines]")
for l in log_text.splitlines():
    if any(k in l for k in ["iter=", "tool_call=", "tool=web_fetch", "finished", "ERROR", "extracted", "rescued", "failure", "recovery"]):
        print(f"  {l.strip()[:180]}")

proc.terminate()
try: proc.wait(timeout=5)
except: proc.kill()
