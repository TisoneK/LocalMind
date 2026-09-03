#!/usr/bin/env python3
"""
B-2026-09-03 — Prompt Assembly Audit runner (P0 Context Engineering milestone).

Replays the diagnostic scenario from the 19.4K-prompt-tokens screenshot:
  turn 1 "Hi" / turn 2 "How are you" / turn 3 "Good to know that"
in ONE session (history accumulates), then a real research turn for contrast.
The adapter's env-gated audit hook (LOCALMIND_PROMPT_AUDIT) records every
outgoing model request; this script boots the server, fires the turns, and
prints the per-call section breakdown from the audit JSONL.

Usage:
  backend/.venv/bin/python scripts/live_test_prompt_audit.py \
      [--adapter bankofai] [--model qwen3.8-flash]
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_common import kill_port, kill_process_tree, server_popen_kwargs, venv_python

VENV_PY = venv_python(BACKEND)
SCRATCH = REPO / "scratch"
TRACEHOME = SCRATCH / "tracehome-audit"
AUDIT_FILE = SCRATCH / "prompt-audit.jsonl"
PORT = 8765

TRIVIAL_TURNS = ["Hi", "How are you", "Good to know that"]
RESEARCH_TURN = (
    "Find the official descriptions of Python, Rust, and Go, and summarize "
    "each language briefly."
)

_ADAPTER_MODEL = {
    "bankofai": "qwen3.8-flash",
    "gemini": "gemini-2.5-flash",
    "zai": "glm-4.5-flash",
}


def prepare_tracehome(adapter: str, model: str) -> None:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    TRACEHOME.mkdir(parents=True, exist_ok=True)
    # Copy the APP's settings so the trace sees the user's real api_keys.
    # Never print any api_keys value.
    src = Path.home() / "LocalMind" / "settings.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    data["adapter"] = adapter
    data["model"] = model or _ADAPTER_MODEL.get(adapter, "")
    data["shell_enabled"] = True
    (TRACEHOME / "settings.json").write_text(json.dumps(data), encoding="utf-8")


def boot_server(log_file: Path, adapter: str):
    env = os.environ.copy()
    env.update(
        {
            "LOCALMIND_PORT": str(PORT),
            "LOCALMIND_HOME": str(TRACEHOME),
            "LOCALMIND_ADAPTER": adapter,
            "LOCALMIND_SHELL_ENABLED": "true",
            "LOCALMIND_PROMPT_AUDIT": str(AUDIT_FILE),
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
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2).read()
            return proc
        except Exception:
            time.sleep(1)
    proc.kill()
    raise RuntimeError("server failed to start within 60s")


def fire_chat(message: str, session_id: str, timeout: int = 240) -> tuple[str, float]:
    body = urllib.parse.urlencode({"message": message, "session_id": session_id}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/chat",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    t0 = time.time()
    parts = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            parts.append(raw.decode("utf-8", errors="replace").rstrip("\n"))
    return "\n".join(parts), round(time.time() - t0, 2)


def read_audit() -> list[dict]:
    if not AUDIT_FILE.exists():
        return []
    out = []
    for line in AUDIT_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default="bankofai")
    ap.add_argument("--model", default="")
    ap.add_argument("--skip-research", action="store_true")
    args = ap.parse_args()

    if AUDIT_FILE.exists():
        AUDIT_FILE.unlink()
    prepare_tracehome(args.adapter, args.model)
    kill_port(PORT)
    time.sleep(1)
    log_file = SCRATCH / "server-prompt-audit.log"
    proc = boot_server(log_file, args.adapter)
    sid = f"audit-{int(time.time())}"
    try:
        for i, msg in enumerate(TRIVIAL_TURNS, 1):
            _, dt = fire_chat(msg, sid)
            print(f"[turn {i}] {msg!r:22s} -> {dt}s")
        if not args.skip_research:
            _, dt = fire_chat(RESEARCH_TURN, sid)
            print(f"[turn 4] research turn -> {dt}s")
    finally:
        kill_process_tree(proc, use_sigkill=True)
        kill_port(PORT)

    # ── Report ──────────────────────────────────────────────────────────
    recs = read_audit()
    print(f"\n{'='*72}\nPROMPT ASSEMBLY AUDIT — {len(recs)} model calls "
          f"({args.adapter}/{args.model or _ADAPTER_MODEL[args.adapter]})\n{'='*72}")
    grand = 0
    for r in recs:
        total = r["system"] + r["tools"] + r["history"] + r["current"]
        grand += total
        print(
            f"[{r['ts']}] {r['call']:5s} total~{total:5d} = system {r['system']:5d}"
            f" | tools {r['tools']:5d} ({r['n_tools']:2d} defs)"
            f" | history {r['history']:5d} ({r['n_history_msgs']:2d} msgs)"
            f" | current {r['current']:4d}"
            f"  [msgs={r['n_messages']}]"
        )
    print(f"{'-'*72}\nTOTAL prompt tokens across all calls: ~{grand}")
    last = AUDIT_FILE.with_suffix(AUDIT_FILE.suffix + ".last-payload.json")
    if last.exists():
        p = json.loads(last.read_text(encoding="utf-8"))
        msgs = p["payload"].get("messages") or []
        sys_msgs = [m for m in msgs if m.get("role") == "system"]
        if sys_msgs:
            s = sys_msgs[0].get("content")
            if isinstance(s, list):
                s = " ".join(x.get("text", "") for x in s if isinstance(x, dict))
            print(f"\nLast call system prompt: {len(s)} chars — first 600:\n{s[:600]}")
        tools = p["payload"].get("tools") or []
        print(f"\nLast call tool defs: {len(tools)} — names:")
        for t in tools[:40]:
            fn = (t.get("function") or {})
            print(f"  - {fn.get('name', '?')}: {(fn.get('description') or '')[:60]}")


if __name__ == "__main__":
    main()
