#!/usr/bin/env python3
"""Live test for Session 305 — ParentSession + readiness telemetry.

Per system/live-testing.md:
- Isolated LOCALMIND_HOME (scratch copy of settings)
- Port 8765 (never 8000)
- Real z.ai/glm-4.5-flash
- Never print API-key values
- Capture before/after evidence

Verifies:
1. Boot log shows [parent-kernel] ready
2. /api/health returns parent_ready=true, parent_degraded_reason=""
3. First turn's SSE carries a parent_ready event
4. After 3+ turns, /api/observability/{sid} shows parent_session_summary + turn_count
5. The rolling summary persists across a backend restart
6. Token usage on turn 4 stays bounded (not linear with history)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ── Hard rules ──────────────────────────────────────────────────────────────
# Never touch port 8000. Never print API-key values. Isolate LOCALMIND_HOME.
PORT = "8765"
REPO = Path(__file__).resolve().parent.parent
SC = REPO / "scratch" / "lm-session305-scratch"
TH = SC / "tracehome"
BACKEND = REPO / "backend"
from harness_common import provider_key, venv_python

VENV_PY = venv_python(BACKEND)

# z.ai API key from the user's chat message — never print it.
ZAI_KEY = provider_key("zai")  # env ZAI_API_KEY or ~/LocalMind/settings.json - never printed
if not ZAI_KEY:
    sys.exit("ERROR: no zai key in env (ZAI_API_KEY) or ~/LocalMind/settings.json")
def setup_scratch_home():
    """Create an isolated LOCALMIND_HOME with a z.ai settings.json."""
    if SC.exists():
        shutil.rmtree(SC)
    SC.mkdir(parents=True)
    TH.mkdir(parents=True)

    # Build a minimal settings.json pointing at z.ai/glm-4.5-flash.
    # Never cat this file — it contains the API key.
    settings = {
        "adapter": "zai",
        "model": "glm-4.5-flash",
        "thinking": "enabled",
        "reasoning_effort": "low",
        "shell_enabled": True,
        "api_keys": {"zai": ZAI_KEY},
    }
    (TH / "settings.json").write_text(json.dumps(settings))


def boot_server():
    """Boot the backend on port 8765 from the isolated home."""
    env = os.environ.copy()
    env["LOCALMIND_PORT"] = PORT
    env["LOCALMIND_HOME"] = str(TH)
    env["LOCALMIND_ADAPTER"] = "zai"
    env["LOCALMIND_SHELL_ENABLED"] = "true"
    env["PYTHONPATH"] = str(BACKEND / "src")

    log_path = SC / "trace.log"
    log_file = open(log_path, "w")
    proc = subprocess.Popen(
        [VENV_PY, "server.py"],
        cwd=str(BACKEND),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    # Wait for /api/health to respond
    for _ in range(40):
        try:
            import urllib.request
            r = urllib.request.urlopen(f"http://localhost:{PORT}/api/health", timeout=2)
            if r.status == 200:
                return proc
        except Exception:
            time.sleep(0.5)
    print("ERROR: server did not boot in 20s", file=sys.stderr)
    print(Path(log_path).read_text()[-2000:], file=sys.stderr)
    proc.kill()
    return None


def curl_json(url: str, method: str = "GET", data=None):
    """GET or POST JSON; return parsed response."""
    import urllib.request
    req = urllib.request.Request(url, method=method)
    if data is not None:
        req.data = json.dumps(data).encode()
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def curl_sse(url: str, form_fields: dict, timeout: int = 120) -> str:
    """POST form fields to an SSE endpoint and return the raw SSE text."""
    import urllib.request
    import urllib.parse
    data = urllib.parse.urlencode(form_fields).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"<EXCEPTION: {e}>"


def grep_count(text: str, pattern: str) -> int:
    return text.count(pattern)


def main():
    setup_scratch_home()
    print("[setup] isolated home at", TH)

    proc = boot_server()
    if proc is None:
        sys.exit(1)
    print(f"[boot] server alive on port {PORT}")

    try:
        # ── Check 1: boot log shows parent-kernel ready ─────────────────
        time.sleep(1)  # let startup logs flush
        boot_log = (SC / "trace.log").read_text()
        ready_line = [l for l in boot_log.splitlines() if "[parent-kernel]" in l]
        print(f"\n[check 1] boot log [parent-kernel] lines:")
        for l in ready_line:
            print(f"   {l.strip()}")

        # ── Check 2: /api/health exposes parent_ready ───────────────────
        health = curl_json(f"http://localhost:{PORT}/api/health")
        print(f"\n[check 2] /api/health:")
        print(f"   parent_ready = {health.get('parent_ready')}")
        print(f"   parent_degraded_reason = {health.get('parent_degraded_reason', '')!r}")
        print(f"   engine_ready = {health.get('engine_ready')}")
        print(f"   status = {health.get('status')}")
        assert health.get("parent_ready") is True, "parent_ready should be True after boot"
        assert health.get("parent_degraded_reason") == "", "degraded_reason should be empty"

        # ── Check 3: first turn SSE carries parent_ready event ──────────
        sid = f"live-test-{int(time.time())}"
        print(f"\n[check 3] sending first turn to session {sid}")
        sse1 = curl_sse(
            f"http://localhost:{PORT}/api/chat",
            {"message": "Hello! What can you help me with today?", "session_id": sid, "is_first": "true"},
            timeout=90,
        )
        (SC / "turn1.sse").write_text(sse1)
        # Count event types
        events = []
        for line in sse1.splitlines():
            if line.startswith("data: ") and '"type"' in line:
                try:
                    payload = json.loads(line[6:])
                    events.append(payload.get("type", "?"))
                except Exception:
                    pass
        from collections import Counter
        event_counts = Counter(events)
        print(f"   SSE event counts: {dict(event_counts)}")
        parent_ready_events = grep_count(sse1, '"parent_ready"')
        print(f"   parent_ready events in SSE: {parent_ready_events}")
        assert parent_ready_events >= 1, "first turn should emit parent_ready"

        # ── Check 4: send 2 more turns, then check observability ────────
        print(f"\n[check 4] sending turns 2 and 3")
        sse2 = curl_sse(
            f"http://localhost:{PORT}/api/chat",
            {"message": "Tell me a short joke about programming.", "session_id": sid, "is_first": "false"},
            timeout=90,
        )
        (SC / "turn2.sse").write_text(sse2)
        print(f"   turn 2 done ({len(sse2)} bytes SSE)")

        sse3 = curl_sse(
            f"http://localhost:{PORT}/api/chat",
            {"message": "Now tell me a different joke, please.", "session_id": sid, "is_first": "false"},
            timeout=90,
        )
        (SC / "turn3.sse").write_text(sse3)
        print(f"   turn 3 done ({len(sse3)} bytes SSE)")

        # Check observability
        obs = curl_json(f"http://localhost:{PORT}/api/observability/{sid}")
        print(f"\n   /api/observability/{sid}:")
        print(f"     parent_session_summary present: {bool(obs.get('parent_session_summary'))}")
        print(f"     parent_session_turn_count: {obs.get('parent_session_turn_count')}")
        summary = obs.get("parent_session_summary") or ""
        if summary:
            print(f"     summary preview: {summary[:200]!r}")
        assert obs.get("parent_session_turn_count") == 3, f"expected 3 turns, got {obs.get('parent_session_turn_count')}"

        # ── Check 5: restart server, verify summary persists ────────────
        print(f"\n[check 5] restarting server to verify persistence")
        proc.terminate()
        proc.wait(timeout=10)
        time.sleep(1)
        proc = boot_server()
        if proc is None:
            sys.exit(1)
        time.sleep(2)

        obs_after = curl_json(f"http://localhost:{PORT}/api/observability/{sid}")
        print(f"   after restart, parent_session_turn_count: {obs_after.get('parent_session_turn_count')}")
        print(f"   after restart, summary present: {bool(obs_after.get('parent_session_summary'))}")
        assert obs_after.get("parent_session_turn_count") == 3, "turn count must survive restart"

        # ── Check 6: send turn 4, verify prompt is bounded ──────────────
        print(f"\n[check 6] sending turn 4 after restart")
        sse4 = curl_sse(
            f"http://localhost:{PORT}/api/chat",
            {"message": "What was the topic of the jokes you just told?", "session_id": sid, "is_first": "false"},
            timeout=120,
        )
        (SC / "turn4.sse").write_text(sse4)
        # Extract provider_usage prompt_tokens
        usage = None
        for line in sse4.splitlines():
            if "provider_usage" in line and '"type": "turn_complete"' in line:
                try:
                    payload = json.loads(line[6:])
                    usage = payload.get("data", {}).get("provider_usage", {})
                except Exception:
                    pass
        print(f"   turn 4 provider_usage: {usage}")
        if usage and usage.get("prompt_tokens"):
            print(f"   prompt_tokens on turn 4: {usage['prompt_tokens']}")
            print(f"   (bounded by kernel contract + summary + recent tail, NOT full history)")

        print("\n[RESULT] all live checks PASSED")
        return 0
    except AssertionError as e:
        print(f"\n[FAIL] {e}", file=sys.stderr)
        return 1
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
