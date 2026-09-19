#!/usr/bin/env python3
"""
B-2026-09-15-8 live-trace repro: does the criteria-unmet replan gate
(classify_turn_outcome's is_pending_action_narration flag,
`_acceptance_gate_at_final_answer` in core/agent/loop.py) misfire on a
zero-tool discussion turn? Fires one prompt through the real server and
saves the SSE — grep it for `agent_loop_gate_failed_replan`.

Note (Session S022 live-testing): a discussion-shaped prompt free of
message_implies_tool_action's blocked keywords tends to short-circuit to
the direct/chat tier upstream (never reaching this gate at all) — that is
the SYSTEM working as intended, not a test failure. The gate is only
reachable once the model has been classified into the "execute" tier;
forcing that live is model/prompt-dependent. The gate's suppression logic
itself is pinned deterministically in
tests/core/test_acceptance_gate.py (test_gate_suppresses_pending_action_
narration_on_conversational_zero_tool_turn and its siblings), which call
`_acceptance_gate_at_final_answer` directly with is_parent=True — the same
call shape production uses.

Usage:
  cd backend && ../scripts/live_test_replan_gate.py --label after
  cd backend && ../scripts/live_test_replan_gate.py --adapter zai --model glm-4.5-flash --prompt "..."
"""
import argparse
import time
from pathlib import Path

from harness_common import kill_port, kill_process_tree, server_popen_kwargs, venv_python
import os
import subprocess
import urllib.request

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
VENV_PY = venv_python(BACKEND)
SCRATCH = REPO / "scratch"
TRACEHOME = SCRATCH / "tracehome"

DEFAULT_PROMPT = (
    "Give me your top three suggestions to make this project more "
    "maintainable, in one or two sentences starting with \"I'll\"."
)


def boot_server(port: int, log_file: Path, adapter: str) -> subprocess.Popen:
    env = os.environ.copy()
    env.update(
        {
            "LOCALMIND_PORT": str(port),
            "LOCALMIND_HOME": str(TRACEHOME),
            "LOCALMIND_ADAPTER": adapter,
            "LOCALMIND_SHELL_ENABLED": "true",
            "PYTHONPATH": str(BACKEND / "src"),
        }
    )
    proc = subprocess.Popen(
        [VENV_PY, "server.py"],
        cwd=str(BACKEND),
        env=env,
        stdout=open(log_file, "wb"),
        stderr=subprocess.STDOUT,
        **server_popen_kwargs(),
    )
    for _ in range(45):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2).read()
            return proc
        except Exception:
            time.sleep(1)
    proc.kill()
    raise RuntimeError("server failed to start within 45s")


def fire_chat(port: int, message: str, session_id: str, timeout: int = 240) -> str:
    import urllib.parse

    body = urllib.parse.urlencode(
        {"message": message, "session_id": session_id, "is_first": "true"}
    ).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/chat",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def setup_scratch_settings(adapter: str, model: str) -> None:
    """Copy the app's real settings.json (api_keys included, never printed)
    into the scratch home, then force adapter/model there — settings.json
    BEATS LOCALMIND_ADAPTER (see system/live-testing.md), so the env var
    alone isn't enough."""
    import json
    import shutil

    real_settings = Path.home() / "LocalMind" / "settings.json"
    scratch_settings = TRACEHOME / "settings.json"
    if not scratch_settings.exists() and real_settings.exists():
        shutil.copy(real_settings, scratch_settings)
    if scratch_settings.exists():
        data = json.loads(scratch_settings.read_text(encoding="utf-8"))
        data["adapter"] = adapter
        data["model"] = model
        scratch_settings.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="after")
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--adapter", default="gemini", help="adapter id, e.g. gemini/zai/bankofai")
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    args = ap.parse_args()

    SCRATCH.mkdir(parents=True, exist_ok=True)
    TRACEHOME.mkdir(parents=True, exist_ok=True)
    setup_scratch_settings(args.adapter, args.model)

    port = 8765
    log_file = SCRATCH / f"server-replan-{args.label}.log"
    kill_port(port)
    time.sleep(1)

    proc = None
    try:
        proc = boot_server(port, log_file, args.adapter)
        print(f"[boot] server ready (pid={proc.pid})")

        sid = f"replan-{int(time.time())}"
        sse_file = SCRATCH / f"sse-replan-{args.label}.sse"
        print(f"\n[trace] {args.prompt!r}")
        t0 = time.time()
        raw = fire_chat(port, args.prompt, sid, timeout=args.timeout)
        latency = time.time() - t0
        sse_file.write_text(raw, encoding="utf-8")
        print(f"[trace] saved {sse_file} ({len(raw)} bytes, {latency:.1f}s)")
    finally:
        if proc is not None:
            kill_process_tree(proc)
        kill_port(port)


if __name__ == "__main__":
    main()
