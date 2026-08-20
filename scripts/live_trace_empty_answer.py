#!/usr/bin/env python3
"""Capture the exact empty-answer flow on glm-4.5-flash for B-2026-08-20-7."""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time, urllib.request, urllib.parse
from pathlib import Path
PORT = "8765"; SC = Path("/tmp/lm-empty-debug"); TH = SC / "tracehome"
BACKEND = Path("/home/z/my-project/LocalMind/backend")
VENV_PY = str(BACKEND / ".venv" / "bin" / "python")
ZAI_KEY = "a9fa08105a9a4127805da89d23da59f0.j51uE0L0dw2H1rV6"
if SC.exists(): shutil.rmtree(SC)
SC.mkdir(parents=True); TH.mkdir(parents=True)
(TH / "settings.json").write_text(json.dumps({"adapter":"zai","model":"glm-4.5-flash","thinking":"enabled","reasoning_effort":"low","shell_enabled":True,"api_keys":{"zai":ZAI_KEY}}))
env = os.environ.copy()
env.update({"LOCALMIND_PORT":PORT,"LOCALMIND_HOME":str(TH),"LOCALMIND_ADAPTER":"zai","LOCALMIND_SHELL_ENABLED":"true","PYTHONPATH":str(BACKEND/"src")})
log = open(SC/"trace.log","w")
proc = subprocess.Popen([VENV_PY,"server.py"],cwd=str(BACKEND),env=env,stdout=log,stderr=subprocess.STDOUT)
for _ in range(40):
    try: urllib.request.urlopen(f"http://localhost:{PORT}/api/health",timeout=2); break
    except: time.sleep(0.5)
time.sleep(2)
sid = f"debug-{int(time.time())}"
msg = "Please list the files in the /tmp directory using the shell tool."
print(f"[turn] {msg!r}")
data = urllib.parse.urlencode({"message":msg,"session_id":sid,"is_first":"false"}).encode()
req = urllib.request.Request(f"http://localhost:{PORT}/api/chat",data=data,method="POST")
req.add_header("Content-Type","application/x-www-form-urlencoded")
try:
    with urllib.request.urlopen(req,timeout=300) as r: sse = r.read().decode("utf-8",errors="replace")
except Exception as e: sse = f"<EXC: {e}>"
(SC/"turn.sse").write_text(sse)
log_text = (SC/"trace.log").read_text()
# Print the full agent.loop log lines
print("\n=== agent.loop log lines ===")
for line in log_text.splitlines():
    if "agent.loop" in line or "agent_runtime" in line or "ERROR" in line or "synthesis" in line.lower() or "rescue" in line.lower() or "empty" in line.lower():
        print(f"  {line.strip()[:200]}")
# Final text
final = ""
for line in sse.splitlines():
    if line.startswith("data: ") and '"type": "token"' in line:
        try:
            p = json.loads(line[6:])
            final += p.get("data",{}).get("content","") or ""
        except: pass
print(f"\n[final] {len(final)} chars: {final[:300]!r}")
proc.terminate()
try: proc.wait(timeout=5)
except: proc.kill()
