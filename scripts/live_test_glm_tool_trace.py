#!/usr/bin/env python3
"""Session 306 — clean GLM native tool trace after provider recovery.

Live-verify on z.ai/glm-4.5-flash that the warm kernel + describe_tool
bootstrap executes a real tool task end-to-end:
  describe_tool → real shell tool call → grounded evidence → final answer.

Per system/live-testing.md: isolated 8765 + LOCALMIND_HOME, real provider,
no API-key values printed, cleanup. Falls back to Zen/hy3-free or DeepSeek
if z.ai returns 429.
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

PORT = "8765"
REPO = Path(__file__).resolve().parent.parent
SC = REPO / "scratch" / "lm-glm-tool-trace"
TH = SC / "tracehome"
BACKEND = REPO / "backend"
from harness_common import venv_python

VENV_PY = venv_python(BACKEND)

# API keys from the user's chat message — never print these.
KEYS = {
    "zai": ("a9fa08105a9a4127805da89d23da59f0.j51uE0L0dw2H1rV6", "glm-4.5-flash"),
    "zen": ("sk-nm1fjrywWtjADgniEcddUZlZ1Ol3pQBiEzdFikO8wZ4bCKyijRrWahPCqMQQgv3G", "hy3-free"),
    "deepseek": ("sk-2beef2a502f0469b95807d346187dda8", "deepseek-chat"),
}

# Try providers in order; first that succeeds wins.
PROVIDER_ORDER = ["zai", "zen", "deepseek"]


def setup(provider: str, model: str):
    if SC.exists():
        shutil.rmtree(SC)
    SC.mkdir(parents=True)
    TH.mkdir(parents=True)
    (TH / "settings.json").write_text(json.dumps({
        "adapter": provider,
        "model": model,
        "thinking": "enabled",
        "reasoning_effort": "low",
        "shell_enabled": True,
        "api_keys": {provider: KEYS[provider][0]},
    }))


def boot(provider: str):
    env = os.environ.copy()
    env.update({
        "LOCALMIND_PORT": PORT, "LOCALMIND_HOME": str(TH),
        "LOCALMIND_ADAPTER": provider, "LOCALMIND_SHELL_ENABLED": "true",
        "PYTHONPATH": str(BACKEND / "src"),
    })
    log = open(SC / "trace.log", "w")
    proc = subprocess.Popen([VENV_PY, "server.py"], cwd=str(BACKEND), env=env,
                            stdout=log, stderr=subprocess.STDOUT)
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://localhost:{PORT}/api/health", timeout=2)
            return proc
        except Exception:
            time.sleep(0.5)
    return None


def send_turn(sid: str, msg: str, timeout: int = 120) -> str:
    data = urllib.parse.urlencode({
        "message": msg, "session_id": sid, "is_first": "false",
    }).encode()
    req = urllib.request.Request(f"http://localhost:{PORT}/api/chat", data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"<EXCEPTION: {e}>"


def parse_sse_events(sse: str) -> list[dict]:
    events = []
    for line in sse.splitlines():
        if line.startswith("data: ") and '"type"' in line:
            try:
                events.append(json.loads(line[6:]))
            except Exception:
                pass
    return events


def check_for_429(sse: str, log: str) -> bool:
    """Return True if the trace hit a z.ai 429 (rate-limit)."""
    indicators = ["429", "rate_limit", "Rate limit", "Too Many Requests"]
    return any(ind in sse or ind in log for ind in indicators)


def run_trace(provider: str, model: str) -> dict:
    """Run a single tool-requiring trace. Returns a result dict."""
    print(f"\n=== Attempting trace on {provider}/{model} ===")
    setup(provider, model)
    proc = boot(provider)
    if proc is None:
        return {"ok": False, "reason": "boot failed"}
    try:
        time.sleep(2)  # let boot logs flush
        boot_log = (SC / "trace.log").read_text()
        ready_lines = [l for l in boot_log.splitlines() if "[parent-kernel]" in l]
        for l in ready_lines:
            print(f"   {l.strip()}")
        if "degraded" in (ready_lines[-1] if ready_lines else ""):
            return {"ok": False, "reason": "boot degraded", "log": boot_log[-2000:]}

        sid = f"glm-tool-{int(time.time())}"
        # A simple tool-requiring task: list /tmp files (shell).
        msg = "Please list the files in the /tmp directory using the shell tool."
        print(f"   sending: {msg}")
        sse = send_turn(sid, msg, timeout=180)
        (SC / "tool_turn.sse").write_text(sse)
        log = (SC / "trace.log").read_text()

        if check_for_429(sse, log):
            return {"ok": False, "reason": "429 rate-limit", "log": log[-2000:]}

        events = parse_sse_events(sse)
        event_counts = Counter(e.get("type", "?") for e in events)
        print(f"   SSE event counts: {dict(event_counts)}")

        # Look for the key evidence: describe_tool, tool_call(shell), final text
        has_describe = any("describe_tool" in str(e) for e in events)
        has_shell_call = any(
            e.get("type") == "tool_call" and "shell" in str(e.get("data", {}).get("tool", ""))
            for e in events
        )
        # Also check the log for these (some events only show in logs)
        log_has_describe = "describe_tool" in log
        log_has_shell = "tool_call=shell" in log or "shell(" in log
        log_has_iter = "finished iter" in log
        # Final answer text
        final_text = ""
        for e in events:
            if e.get("type") == "token" and e.get("data", {}).get("text"):
                final_text += e["data"]["text"]
        if not final_text:
            # Try done event
            for e in events:
                if e.get("type") == "done":
                    final_text = e.get("data", {}).get("text", "") or ""

        print(f"   has describe_tool: {has_describe or log_has_describe}")
        print(f"   has shell tool_call: {has_shell_call or log_has_shell}")
        print(f"   has 'finished iter' in log: {log_has_iter}")
        print(f"   final text length: {len(final_text)}")
        if final_text:
            print(f"   final text preview: {final_text[:300]!r}")

        # Check for errors
        errors = [l for l in log.splitlines() if "ERROR" in l or "Traceback" in l]
        if errors:
            print(f"   errors in log: {len(errors)}")
            for e in errors[:3]:
                print(f"     {e.strip()[:150]}")

        return {
            "ok": True,
            "provider": provider,
            "model": model,
            "has_describe_tool": has_describe or log_has_describe,
            "has_shell_call": has_shell_call or log_has_shell,
            "has_finished_iter": log_has_iter,
            "final_text": final_text,
            "event_counts": dict(event_counts),
            "errors": errors[:5],
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def main():
    for provider in PROVIDER_ORDER:
        model = KEYS[provider][1]
        result = run_trace(provider, model)
        if result.get("ok"):
            # Even if ok=True, check if it was a 429 in disguise
            if result.get("reason") == "429 rate-limit":
                print(f"\n[skip] {provider} hit 429, trying next provider")
                continue
            # Check the success criteria
            if result.get("has_shell_call") and result.get("final_text"):
                print(f"\n[SUCCESS] clean tool trace on {provider}/{model}")
                print(f"  describe_tool loaded: {result['has_describe_tool']}")
                print(f"  shell tool_call emitted: {result['has_shell_call']}")
                print(f"  final answer length: {len(result['final_text'])} chars")
                return 0
            else:
                print(f"\n[PARTIAL] {provider} trace completed but missing evidence")
                print(f"  has_describe_tool: {result.get('has_describe_tool')}")
                print(f"  has_shell_call: {result.get('has_shell_call')}")
                print(f"  final_text: {result.get('final_text', '')[:200]!r}")
                # Save the trace for analysis
                shutil.copy(SC / "trace.log", REPO / "scripts" / f"trace-{provider}.log")
                return 1
        else:
            reason = result.get("reason", "unknown")
            print(f"\n[skip] {provider} failed: {reason}")
            if "429" in reason:
                continue  # try next provider
            # Save log for debugging
            try:
                shutil.copy(SC / "trace.log", REPO / "scripts" / f"boot-fail-{provider}.log")
            except Exception:
                pass
    print("\n[FAIL] no provider produced a clean tool trace")
    return 1


if __name__ == "__main__":
    sys.exit(main())
