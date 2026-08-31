#!/usr/bin/env python3
"""Session 313 — thorough end-to-end system audit (real-user walkthrough).

Boots the real app on isolated 8765 + z.ai/glm-4.5-flash and walks through
a realistic user session. Captures SSE + log + latency for every interaction.
Per system/live-testing.md: isolated LOCALMIND_HOME, port 8765 (never 8000),
no API-key values printed, cleanup afterwards.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path
from collections import Counter

# ── Hard rules ──────────────────────────────────────────────────────────────
PORT = "8765"
REPO = Path(__file__).resolve().parent.parent
SC = REPO / "scratch" / "lm-audit-313"
TH = SC / "tracehome"
BACKEND = REPO / "backend"
from harness_common import venv_python

VENV_PY = venv_python(BACKEND)
ZAI_KEY = "a9fa08105a9a4127805da89d23da59f0.j51uE0L0dw2H1rV6"

# Results store
RESULTS: list[dict] = []


def setup():
    if SC.exists():
        shutil.rmtree(SC)
    SC.mkdir(parents=True)
    TH.mkdir(parents=True)
    (TH / "settings.json").write_text(json.dumps({
        "adapter": "zai",
        "model": "glm-4.5-flash",
        "thinking": "enabled",
        "reasoning_effort": "low",
        "shell_enabled": True,
        "api_keys": {"zai": ZAI_KEY},
    }))


def boot():
    env = os.environ.copy()
    env.update({
        "LOCALMIND_PORT": PORT, "LOCALMIND_HOME": str(TH),
        "LOCALMIND_ADAPTER": "zai", "LOCALMIND_SHELL_ENABLED": "true",
        "PYTHONPATH": str(BACKEND / "src"),
    })
    log = open(SC / "trace.log", "w")
    proc = subprocess.Popen(
        [VENV_PY, "server.py"], cwd=str(BACKEND), env=env,
        stdout=log, stderr=subprocess.STDOUT,
    )
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://localhost:{PORT}/api/health", timeout=2)
            return proc
        except Exception:
            time.sleep(0.5)
    return None


def curl_json(url, method="GET", data=None, timeout=10):
    req = urllib.request.Request(url, method=method)
    if data is not None:
        req.data = json.dumps(data).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"_error": str(e)}


def send_turn(sid, msg, is_first="false", timeout=180):
    """Send a chat message, return (sse_text, elapsed_s)."""
    data = urllib.parse.urlencode({
        "message": msg, "session_id": sid, "is_first": is_first,
    }).encode()
    req = urllib.request.Request(f"http://localhost:{PORT}/api/chat", data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            sse = r.read().decode("utf-8", errors="replace")
        elapsed = time.monotonic() - t0
        return sse, elapsed
    except Exception as e:
        return f"<EXCEPTION: {e}>", time.monotonic() - t0


def parse_sse(sse):
    """Extract event types + final text + key metrics from SSE."""
    events = []
    final_text = ""
    thinking_text = ""
    tool_calls = []
    usage = {}
    errors = []
    for line in sse.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            p = json.loads(line[6:])
        except Exception:
            continue
        t = p.get("type", "")
        if t == "obs_event":
            ot = p.get("data", {}).get("type", "")
            if ot == "tool_call":
                tool_calls.append({
                    "tool": p["data"].get("tool"),
                    "status": p["data"].get("status"),
                })
            elif ot == "turn_complete":
                usage = p.get("data", {}).get("provider_usage", {}) or {}
            elif ot in ("attachment_failed", "agent_loop_error", "agent_loop_failure"):
                errors.append(p["data"])
        elif t == "token":
            final_text += p.get("data", {}).get("content", "") or ""
        elif t == "thinking_token":
            thinking_text += p.get("thinking", "") or ""
        elif t == "error":
            errors.append({"type": "sse_error", "data": p})
    return {
        "events": events,
        "final_text": final_text.strip(),
        "thinking_text": thinking_text.strip()[:500],
        "tool_calls": tool_calls,
        "usage": usage,
        "errors": errors,
    }


def record(phase, sid, msg, sse, elapsed, notes=""):
    parsed = parse_sse(sse)
    result = {
        "phase": phase,
        "session_id": sid,
        "message": msg,
        "elapsed_s": round(elapsed, 2),
        "final_text_len": len(parsed["final_text"]),
        "final_text_preview": parsed["final_text"][:300],
        "thinking_preview": parsed["thinking_text"][:200],
        "tool_calls": parsed["tool_calls"],
        "usage": parsed["usage"],
        "errors": parsed["errors"],
        "notes": notes,
    }
    RESULTS.append(result)
    print(f"\n[{phase}] {msg[:60]!r}")
    print(f"  elapsed: {elapsed:.2f}s | text: {len(parsed['final_text'])} chars | tools: {len(parsed['tool_calls'])} | errors: {len(parsed['errors'])}")
    if parsed["final_text"]:
        print(f"  answer: {parsed['final_text'][:200]!r}")
    if parsed["tool_calls"]:
        print(f"  tools: {parsed['tool_calls'][:3]}")
    if parsed["errors"]:
        print(f"  errors: {parsed['errors'][:2]}")
    if parsed["usage"]:
        print(f"  usage: prompt={parsed['usage'].get('prompt_tokens')} completion={parsed['usage'].get('completion_tokens')}")
    # Save the raw SSE for debugging
    (SC / f"{phase}.sse").write_text(sse)
    return result


def main():
    setup()
    proc = boot()
    if proc is None:
        print("BOOT FAILED")
        return 1
    print(f"[boot] server alive on {PORT}")
    time.sleep(2)

    # Read boot log
    boot_log = (SC / "trace.log").read_text()
    ready_lines = [l for l in boot_log.splitlines() if "[parent-kernel]" in l]
    for l in ready_lines:
        print(f"  {l.strip()}")

    sid = f"audit-{int(time.time())}"

    try:
        # ── Phase A: bootup + health ────────────────────────────────────
        print("\n" + "="*60)
        print("PHASE A: bootup + health")
        print("="*60)
        health = curl_json(f"http://localhost:{PORT}/api/health")
        print(f"  /api/health: status={health.get('status')} parent_ready={health.get('parent_ready')} engine_ready={health.get('engine_ready')}")
        print(f"  parent_degraded_reason={health.get('parent_degraded_reason', '')!r}")
        print(f"  model={health.get('model')} adapter={health.get('adapter')}")

        models = curl_json(f"http://localhost:{PORT}/api/models")
        print(f"  /api/models: {len(models.get('models', []))} models, current={models.get('current', '')[:40]}")

        caps = curl_json(f"http://localhost:{PORT}/api/capabilities")
        fam_count = len(caps.get("families", []))
        print(f"  /api/capabilities: {fam_count} families")

        # ── Phase B: greeting + capability ──────────────────────────────
        print("\n" + "="*60)
        print("PHASE B: greeting + capability")
        print("="*60)
        sse, t = send_turn(sid, "Hi", is_first="true", timeout=90)
        record("B1-hi", sid, "Hi", sse, t)

        sse, t = send_turn(sid, "What can you do?", timeout=90)
        record("B2-capability", sid, "What can you do?", sse, t)

        sse, t = send_turn(sid, "Like what?", timeout=90)
        record("B3-followup", sid, "Like what?", sse, t)

        # ── Phase C: simple tool task ───────────────────────────────────
        print("\n" + "="*60)
        print("PHASE C: simple tool task")
        print("="*60)
        sse, t = send_turn(sid, "What is the hostname of this machine?", timeout=180)
        record("C1-hostname", sid, "What is the hostname of this machine?", sse, t)

        sse, t = send_turn(sid, "List the files in /tmp", timeout=180)
        record("C2-list-tmp", sid, "List the files in /tmp", sse, t)

        # ── Phase D: file create + read back ────────────────────────────
        print("\n" + "="*60)
        print("PHASE D: file create + read back")
        print("="*60)
        sse, t = send_turn(sid, "Create a file at /tmp/audit-test.txt with the content 'Hello from LocalMind audit'", timeout=180)
        record("D1-create", sid, "Create a file at /tmp/audit-test.txt...", sse, t)

        sse, t = send_turn(sid, "What did I just ask you to create?", timeout=90)
        record("D2-recall", sid, "What did I just ask you to create?", sse, t)

        # ── Phase E: multi-turn conversation ────────────────────────────
        print("\n" + "="*60)
        print("PHASE E: multi-turn conversation")
        print("="*60)
        sse, t = send_turn(sid, "I'm planning a small vegetable garden. What should I grow?", timeout=120)
        record("E1-garden", sid, "I'm planning a small vegetable garden...", sse, t)

        sse, t = send_turn(sid, "How much sun do tomatoes need?", timeout=120)
        record("E2-followup", sid, "How much sun do tomatoes need?", sse, t)

        sse, t = send_turn(sid, "What was the first thing I asked you about in this conversation?", timeout=120)
        record("E3-recall-early", sid, "What was the first thing I asked you about?", sse, t)

        # ── Phase F: web search ─────────────────────────────────────────
        print("\n" + "="*60)
        print("PHASE F: web search")
        print("="*60)
        sse, t = send_turn(sid, "Search the web for the current version of Python and tell me", timeout=180)
        record("F1-websearch", sid, "Search the web for the current version of Python...", sse, t)

        # ── Phase G: error handling ─────────────────────────────────────
        print("\n" + "="*60)
        print("PHASE G: error handling")
        print("="*60)
        sse, t = send_turn(sid, "Read the file at /nonexistent/path/to/file.txt", timeout=120)
        record("G1-missing-file", sid, "Read the file at /nonexistent/path/to/file.txt", sse, t)

        sse, t = send_turn(sid, "Run the command: ls /this/does/not/exist", timeout=120)
        record("G2-bad-command", sid, "Run the command: ls /this/does/not/exist", sse, t)

        # ── Phase H: observability check ────────────────────────────────
        print("\n" + "="*60)
        print("PHASE H: observability")
        print("="*60)
        obs = curl_json(f"http://localhost:{PORT}/api/observability/{sid}")
        print(f"  /api/observability: turn_count={obs.get('parent_session_turn_count')}")
        print(f"  summary present: {bool(obs.get('parent_session_summary'))}")
        if obs.get("parent_session_summary"):
            print(f"  summary preview: {obs['parent_session_summary'][:200]!r}")

        # ── Phase I: persistence (restart + reload) ─────────────────────
        print("\n" + "="*60)
        print("PHASE I: persistence (restart backend)")
        print("="*60)
        proc.terminate()
        proc.wait(timeout=10)
        time.sleep(1)
        proc = boot()
        if proc is None:
            print("  REBOOT FAILED")
            return 1
        time.sleep(2)
        # Check the session still exists + has history
        sessions = curl_json(f"http://localhost:{PORT}/api/sessions")
        session_exists = any(s.get("id") == sid for s in (sessions if isinstance(sessions, list) else []))
        print(f"  session {sid[:12]} exists after restart: {session_exists}")

        obs_after = curl_json(f"http://localhost:{PORT}/api/observability/{sid}")
        print(f"  turn_count after restart: {obs_after.get('parent_session_turn_count')}")

        # Send a follow-up that references pre-restart context
        sse, t = send_turn(sid, "What was the first thing I asked you about?", timeout=120)
        record("I1-recall-after-restart", sid, "What was the first thing I asked you about? (post-restart)", sse, t)

        # ── Final: dump all results ─────────────────────────────────────
        print("\n" + "="*60)
        print("AUDIT COMPLETE — summary")
        print("="*60)
        (SC / "results.json").write_text(json.dumps(RESULTS, indent=2, default=str))
        # Final log tail
        final_log = (SC / "trace.log").read_text()
        (SC / "final_trace.log").write_text(final_log)
        errors_in_log = [l for l in final_log.splitlines() if "ERROR" in l or "Traceback" in l]
        print(f"  total interactions: {len(RESULTS)}")
        print(f"  errors in log: {len(errors_in_log)}")
        for e in errors_in_log[-5:]:
            print(f"    {e.strip()[:150]}")
        return 0
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
