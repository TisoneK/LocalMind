#!/usr/bin/env python3
"""
Session 400: Live-test harness for the system_search tool (feature
system-search-tool — Local Search Intelligence Phase 1).

Boots LocalMind on isolated port 8765 + scratch LOCALMIND_HOME, fires the
USER-PITCH prompts ("Where is my LocalMind project?", "Find the largest
files…", "Do I have Python installed?", …), captures SSE, and scores:
  - did the model SELECT system_search (vs find_path/sysinfo/shell)?
  - which operations did it use?
  - did the final answer present real paths/data (grounded)?
  - tool-call counts, latency, token usage, errors

Provider comes from the ENVIRONMENT (LOCALMIND_ADAPTER + <PROV>_API_KEY) —
this script never contains or prints a key. Usage:

  cd backend && ZEN_API_KEY=... LOCALMIND_ADAPTER=zen \
      ../scripts/live_test_system_search.py --label baseline

Artifacts land in scratch/: server-syssearch-<label>.log,
sse-syssearch-<label>-<name>.sse, results-syssearch-<label>.json.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Derive the repo root from this script's location (scripts/ is at the repo
# root) so the harness runs on any machine — not a hardcoded sandbox path.
# Override with LOCALMIND_REPO if the layout ever differs.
_repo_env = os.environ.get("LOCALMIND_REPO", "").strip()
REPO = Path(_repo_env).expanduser() if _repo_env else Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
# Prefer the platform-correct venv python; fall back to the current interpreter.
_VENV_PY = BACKEND / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
VENV_PY = str(_VENV_PY) if _VENV_PY.exists() else sys.executable
SCRATCH = REPO / "scratch"
TRACEHOME = SCRATCH / "syssearch-home"

# The user-pitch questions (chat, 2026-08-25) — one per operation family.
PROMPTS = [
    ("find_project", "Where is my LocalMind project?"),
    ("largest_files", "Find the largest files on my computer."),
    ("apps_python", "Do I have Python installed, and where is it?"),
    ("recent_cv", "Show me the files I worked on most recently."),
    ("duplicates", "Do I have multiple copies of any files?"),
    ("open_psd", "What program can I use to open a .psd file?"),
]


def boot_server(port: int, log_file: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env.update(
        {
            "LOCALMIND_PORT": str(port),
            "LOCALMIND_HOME": str(TRACEHOME),
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
        preexec_fn=os.setsid,
    )
    for _ in range(45):
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/health", timeout=2
            ).read()
            return proc
        except Exception:
            time.sleep(1)
    proc.kill()
    raise RuntimeError("server failed to start within 45s")


def fire_chat(port: int, message: str, session_id: str, timeout: int = 240) -> str:
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


def parse_sse(raw: str) -> dict:
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data: "):
            continue
        try:
            events.append(json.loads(line[6:]))
        except json.JSONDecodeError:
            continue

    out = {
        "final_text": [],
        "thinking": [],
        "tool_calls": [],
        "errors": [],
        "usage": None,
        "event_counts": {},
        "degraded": False,
    }
    for ev in events:
        etype = ev.get("type")
        out["event_counts"][etype] = out["event_counts"].get(etype, 0) + 1
        if etype == "token":
            out["final_text"].append(ev.get("content", ""))
        elif etype == "thinking_token":
            out["thinking"].append(ev.get("thinking", ""))
        elif etype == "tool_call":
            out["tool_calls"].append(ev.get("tool_call", {}))
        elif etype == "error":
            out["errors"].append(str(ev.get("error", ev))[:300])
        elif etype == "agent_loop_degraded":
            out["degraded"] = True
        elif etype == "turn_complete":
            out["usage"] = ev.get("provider_usage")
    out["final_text"] = "".join(out["final_text"])
    return out


def score(name: str, prompt: str, parsed: dict) -> dict:
    tools = [tc.get("name") or tc.get("tool") or "?" for tc in parsed["tool_calls"]]
    syssearch_calls = [tc for tc in parsed["tool_calls"] if (tc.get("name") or tc.get("tool")) == "system_search"]
    ops = []
    for tc in syssearch_calls:
        raw = tc.get("arguments") or tc.get("input") or ""
        m = re.search(r'"operation"\s*:\s*"(\w+)"', str(raw))
        ops.append(m.group(1) if m else "?")

    final = parsed["final_text"]
    # Grounded: the answer contains real filesystem evidence (absolute paths
    # or sizes), not a generic "I found files" hedge.
    grounded = bool(re.search(r"/home/|/Users/|C:\\|KB|MB|GB", final))

    return {
        "name": name,
        "prompt": prompt,
        "tools_used": tools,
        "system_search_ops": ops,
        "selected_system_search": "system_search" in tools,
        "avoided_shell_for_search": "shell" not in tools or "system_search" in tools,
        "grounded_answer": grounded,
        "n_tool_calls": len(tools),
        "n_errors": len(parsed["errors"]),
        "degraded": parsed["degraded"],
        "errors": parsed["errors"][:2],
        "final_chars": len(final),
        "final_head": final[:280],
        "usage": parsed["usage"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument(
        "--prompts",
        default=",".join(n for n, _ in PROMPTS),
        help="comma-separated prompt names",
    )
    ap.add_argument("--cooldown", type=float, default=12.0)
    args = ap.parse_args()

    adapter = os.environ.get("LOCALMIND_ADAPTER", "")
    if not adapter:
        print(
            "ERROR: LOCALMIND_ADAPTER not set in env — server would boot the "
            "pydantic default (ollama). Set LOCALMIND_ADAPTER (and its API key) "
            "before running this script."
        )
        return 2
    print(f"provider adapter: {adapter} (from env; key never printed)")

    SCRATCH.mkdir(exist_ok=True)
    TRACEHOME.mkdir(parents=True, exist_ok=True)
    log_file = SCRATCH / f"server-syssearch-{args.label}.log"

    subprocess.run(["pkill", "-f", f"LOCALMIND_PORT={args.port}"], capture_output=True)
    time.sleep(1)

    srv = boot_server(args.port, log_file)
    results = []
    try:
        wanted = set(args.prompts.split(","))
        for name, prompt in PROMPTS:
            if name not in wanted:
                continue
            t0 = time.time()
            sse_file = SCRATCH / f"sse-syssearch-{args.label}-{name}.sse"
            try:
                raw = fire_chat(args.port, prompt, f"syssearch-{args.label}-{name}")
                sse_file.write_text(raw, encoding="utf-8")
                parsed = parse_sse(raw)
                row = score(name, prompt, parsed)
            except Exception as exc:  # noqa: BLE001 — record, keep going
                row = {
                    "name": name,
                    "prompt": prompt,
                    "tools_used": [],
                    "system_search_ops": [],
                    "selected_system_search": False,
                    "avoided_shell_for_search": False,
                    "grounded_answer": False,
                    "n_tool_calls": 0,
                    "n_errors": 1,
                    "degraded": True,
                    "errors": [f"harness: {exc}"],
                    "final_chars": 0,
                    "final_head": "",
                    "usage": None,
                }
            row["latency_s"] = round(time.time() - t0, 1)
            results.append(row)
            print(
                f"  {name:14s} {row['latency_s']:6.1f}s "
                f"tools={','.join(row['tools_used']) or '-'} "
                f"ops={','.join(row['system_search_ops']) or '-'} "
                f"grounded={row['grounded_answer']} "
                f"err={row['n_errors']}"
            )
            time.sleep(args.cooldown)
    finally:
        try:
            os.killpg(os.getpgid(srv.pid), 15)
        except Exception:
            srv.kill()

    out_file = SCRATCH / f"results-syssearch-{args.label}.json"
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")

    n = len(results)
    sel = sum(1 for r in results if r["selected_system_search"])
    gr = sum(1 for r in results if r["grounded_answer"])
    err = sum(1 for r in results if r["n_errors"] or r["degraded"])
    print(f"\n== system_search live-test [{args.label}] ==")
    print(f"selected system_search: {sel}/{n} · grounded: {gr}/{n} · errors/degraded: {err}/{n}")
    print(f"artifacts: {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
