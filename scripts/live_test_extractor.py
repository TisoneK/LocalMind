#!/usr/bin/env python3
"""Live-test the evidence extractor on the weather task.

Per system/live-testing.md: real z.ai/glm-4.5-flash, isolated 8765.
Verify: when synthesis fails, does the deterministic extractor fire
and give the user a real answer from the reasoning/observations?
"""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time, urllib.request, urllib.parse
from pathlib import Path

PORT = "8765"
REPO = Path(__file__).resolve().parent.parent
SC = REPO / "scratch" / "lm-extractor-live"
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
    proc = subprocess.Popen([VENV_PY, "server.py"], cwd=str(BACKEND), env=env,
                            stdout=log, stderr=subprocess.STDOUT)
    for _ in range(40):
        try: urllib.request.urlopen(f"http://localhost:{PORT}/api/health", timeout=2); return proc
        except: time.sleep(0.5)
    return None

def send(sid, msg, timeout=240):
    data = urllib.parse.urlencode({"message": msg, "session_id": sid, "is_first": "true"}).encode()
    req = urllib.request.Request(f"http://localhost:{PORT}/api/chat", data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            sse = r.read().decode("utf-8", errors="replace")
        return sse, time.monotonic() - t0
    except Exception as e:
        return f"<EXC: {e}>", time.monotonic() - t0

def main():
    setup()
    proc = boot()
    if not proc: print("BOOT FAILED"); return 1
    print(f"[boot] server alive on {PORT}")
    time.sleep(2)
    try:
        sid = f"extractor-{int(time.time())}"
        msg = "Hey, what's the weather like in Kitengela rn"
        print(f"\n[turn] {msg!r}")
        sse, elapsed = send(sid, msg, timeout=300)
        (SC / "turn.sse").write_text(sse)
        log = (SC / "trace.log").read_text()

        # Parse the final answer
        final = ""
        for line in sse.splitlines():
            if line.startswith("data: ") and '"type": "token"' in line:
                try:
                    p = json.loads(line[6:])
                    final += p.get("content", "") or ""
                except: pass

        print(f"\n[result] elapsed: {elapsed:.1f}s")
        print(f"[result] final answer ({len(final.strip())} chars): {final.strip()[:500]!r}")

        # Check what path fired
        print(f"\n[log checks]")
        print(f"  evidence_extracted fired: {'evidence_extracted' in log}")
        print(f"  answer extracted from reasoning: {'answer extracted from reasoning' in log}")
        print(f"  answer extracted from tool observations: {'answer extracted from tool observations' in log}")
        print(f"  empty-response rescued by evidence extraction: {'evidence extraction' in log}")
        print(f"  empty-response rescued by synthesis: {'rescued by synthesis' in log}")
        print(f"  post-loop evidence synthesis: {'post-loop' in log}")
        print(f"  clean fallback: {'Actions panel' in final}")
        print(f"  429 rate-limited: {'429' in log}")

        # Key log lines
        print(f"\n[key log lines]")
        for l in log.splitlines():
            if any(k in l for k in ["iter=", "tool_call=", "finished", "extracted", "rescued", "synthesis", "HEDGE", "empty", "ERROR"]):
                print(f"  {l.strip()[:180]}")

        # Verdict
        print(f"\n[VERDICT]")
        if final.strip() and not any(h in final.lower() for h in ["would you like", "actions panel", "couldn't"]):
            print(f"  ✅ REAL ANSWER produced ({len(final)} chars)")
            if "evidence_extracted" in log or "extracted" in log:
                print(f"  ✅ deterministic extractor FIRED (zero-LLM)")
            return 0
        elif "evidence_extracted" in log or "answer extracted" in log:
            print(f"  ⚠️  extractor fired but answer looks like a fallback")
            return 1
        elif "429" in log:
            print(f"  ⚠️  z.ai 429 — rate-limited, cannot verify")
            return 2
        else:
            print(f"  ❌ no real answer + extractor didn't fire")
            return 1
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except: proc.kill()

if __name__ == "__main__": sys.exit(main())
