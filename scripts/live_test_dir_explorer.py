#!/usr/bin/env python3
"""
Live-test harness for the dir_explorer tool (feature explorer-tool).

Boots LocalMind on an isolated port + scratch LOCALMIND_HOME, fires
selection prompts, captures SSE, and scores the QUESTIONS THE DESIGN DOC
§10 ASKS:
  1. Does the model SELECT dir_explorer (list / tree / stat) for
     look-around-a-folder phrasing?
  2. Does it PRESENT bounded output honestly (no invented entries)?
  3. Does it NOT regress system_search (find-by-name), grep_search
     (content search) or shell (real shell work) selection?

Provider comes from the environment (LOCALMIND_ADAPTER, one of zen / zai /
bankofai; this script never contains or prints a key). Primary per the
design: zen/deepseek-v4-flash-free; the mandatory weak-model check is
zai/glm-4.5-flash. Usage:

  cd backend && ../scripts/live_test_dir_explorer.py --label zen-primary
  cd backend && ../scripts/live_test_dir_explorer.py --label zai-weak \
      --adapter zai

Artifacts: scratch/server-direxplore-<label>.log,
scratch/sse-direxplore-<label>-<name>.sse,
scratch/results-direxplore-<label>.json.
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

from harness_common import (
    kill_port,
    kill_process_tree,
    provider_key,
    server_popen_kwargs,
    venv_python,
)

_repo_env = os.environ.get("LOCALMIND_REPO", "").strip()
REPO = Path(_repo_env).expanduser() if _repo_env else Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
VENV_PY = venv_python(BACKEND)
SCRATCH = REPO / "scratch"
TRACEHOME = SCRATCH / "direxplore-home"
REAL_SETTINGS = Path.home() / "LocalMind" / "settings.json"

# name -> (prompt, expected-first-tool, expected-operation or None)
PROMPTS = [
    # The two new-capability prompts (design §10).
    ("list_documents",
     "What's in my Documents folder? Just the contents with sizes, don't read any files.",
     "dir_explorer", "list"),
    ("tree_project",
     ("Sketch the structure of my LocalMind project folder — just the layout, "
      "a few levels deep, without reading file contents."),
     "dir_explorer", "tree"),
    # The pre-write check the safety workflow now names.
    ("pre_write_stat",
     ("Before I save a file into ~/Documents, tell me whether 'notes.txt' already "
      "exists there and when it was last modified."),
     "dir_explorer", "stat"),
    # Regressions: these must NOT collapse onto dir_explorer.
    ("find_by_name",
     "Find my CV file somewhere under Documents.",
     "system_search", None),
    ("content_search",
     "Search all text files in my Documents folder for the word 'invoice'.",
     "grep_search", None),
    ("real_shell",
     "Run 'git --version' in the shell and report the exact output.",
     "shell", None),
]


def prepare_home(adapter: str) -> None:
    """Scratch LOCALMIND_HOME with the real settings, provider-rewritten.

    The copied settings carry api keys — never cat, never print. The stale
    generic "model" key is dropped so the requested provider's default
    model applies (a leftover cloud model would otherwise be mapped onto
    the new provider).
    """
    TRACEHOME.mkdir(parents=True, exist_ok=True)
    dst = TRACEHOME / "settings.json"
    if REAL_SETTINGS.exists():
        data = json.loads(REAL_SETTINGS.read_text(encoding="utf-8"))
    else:
        data = {}
    data["adapter"] = adapter
    data.pop("model", None)
    keys = data.get("api_keys") or {}
    if adapter not in keys and not provider_key(adapter):
        print(f"ERROR: no API key configured for provider '{adapter}' "
              f"(env {adapter.upper()}_API_KEY or settings api_keys). "
              "This is a missing input — aborting, key never printed.")
        sys.exit(2)
    if adapter not in keys and provider_key(adapter):
        keys[adapter] = provider_key(adapter)  # env var → settings bridge
        data["api_keys"] = keys
    dst.write_text(json.dumps(data), encoding="utf-8")


def boot_server(port: int, adapter: str, log_file: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env.update({
        "LOCALMIND_PORT": str(port),
        "LOCALMIND_HOME": str(TRACEHOME),
        "LOCALMIND_ADAPTER": adapter,
        "LOCALMIND_SHELL_ENABLED": "true",
        "PYTHONPATH": str(BACKEND / "src"),
    })
    log_fh = open(log_file, "wb")  # noqa: SIM115 (lives for the server's lifetime)
    proc = subprocess.Popen(
        [VENV_PY, "server.py"],
        cwd=str(BACKEND),
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        **server_popen_kwargs(),
    )
    ready = False
    for _ in range(45):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2).read()
            ready = True
            break
        except OSError:
            time.sleep(1)
    if not ready:
        proc.kill()
        raise RuntimeError("server failed to start within 45s")
    # Port-hygiene trap: a STALE listener answers health checks while the
    # fresh server sits dead-on-the-port — verify the log proves this boot owns
    # the port before trusting any trace.
    try:
        blob = log_file.read_bytes()
        if b"already in use" in blob or b"[Errno 98]" in blob or b"10048" in blob:
            kill_process_tree(proc)
            raise RuntimeError("log says the port was already in use — stale listener, aborting")
    except FileNotFoundError:
        pass
    return proc


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
    out = {"final_text": [], "tool_calls": [], "errors": [], "usage": None, "degraded": False}
    for ev in events:
        etype = ev.get("type")
        if etype == "token":
            out["final_text"].append(ev.get("content", ""))
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


def _args_of(tc: dict) -> dict:
    raw = tc.get("arguments") or tc.get("input") or "{}"
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        m = re.search(r'"operation"\s*:\s*"(\w+)"', str(raw))
        return {"operation": m.group(1)} if m else {}


def score(name: str, prompt: str, expected_tool: str, expected_op: str | None, parsed: dict) -> dict:
    tools = [tc.get("name") or tc.get("tool") or "?" for tc in parsed["tool_calls"]]
    calls_by_name: dict[str, list[dict]] = {}
    for tc in parsed["tool_calls"]:
        calls_by_name.setdefault(tc.get("name") or tc.get("tool") or "?", []).append(_args_of(tc))
    explorer_ops = [a.get("operation", "?") for a in calls_by_name.get("dir_explorer", [])]
    selected = expected_tool in tools
    op_ok = (expected_op is None) or (expected_op in explorer_ops)
    # The non-regression half: the OTHER new surface must not swallow it.
    bleed = (expected_tool != "dir_explorer") and ("dir_explorer" in tools[:1])
    final = parsed["final_text"]
    return {
        "name": name,
        "prompt": prompt,
        "expected_tool": expected_tool,
        "expected_op": expected_op,
        "tools_used": tools,
        "dir_explorer_ops": explorer_ops,
        "selected_expected": selected and op_ok,
        "explorer_bled_into_regression": bleed,
        "n_errors": len(parsed["errors"]),
        "degraded": parsed["degraded"],
        "errors": parsed["errors"][:2],
        "final_chars": len(final),
        "final_head": final[:240],
        "usage": parsed["usage"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="run")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--adapter", default="", help="zen|zai|bankofai (default: LOCALMIND_ADAPTER env)")
    ap.add_argument("--prompts", default=",".join(n for n, _, _, _ in PROMPTS))
    ap.add_argument("--cooldown", type=float, default=12.0)
    args = ap.parse_args()

    adapter = (args.adapter or os.environ.get("LOCALMIND_ADAPTER", "")).strip()
    if not adapter:
        print("ERROR: no provider — pass --adapter (or set LOCALMIND_ADAPTER).")
        return 2
    print(f"provider adapter: {adapter} (key resolved from env/settings, never printed)")

    SCRATCH.mkdir(exist_ok=True)
    prepare_home(adapter)
    log_file = SCRATCH / f"server-direxplore-{args.label}.log"

    kill_port(args.port)
    time.sleep(1)
    srv = boot_server(args.port, adapter, log_file)
    results = []
    try:
        wanted = set(args.prompts.split(","))
        for name, prompt, exp_tool, exp_op in PROMPTS:
            if name not in wanted:
                continue
            t0 = time.time()
            try:
                raw = fire_chat(args.port, prompt, f"direxplore-{args.label}-{name}")
                (SCRATCH / f"sse-direxplore-{args.label}-{name}.sse").write_text(raw, encoding="utf-8")
                row = score(name, prompt, exp_tool, exp_op, parse_sse(raw))
            except Exception as exc:  # noqa: BLE001 — record, keep going
                row = {
                    "name": name, "prompt": prompt, "expected_tool": exp_tool,
                    "expected_op": exp_op, "tools_used": [], "dir_explorer_ops": [],
                    "selected_expected": False, "explorer_bled_into_regression": False,
                    "n_errors": 1, "degraded": True, "errors": [f"harness: {exc}"],
                    "final_chars": 0, "final_head": "", "usage": None,
                }
            row["latency_s"] = round(time.time() - t0, 1)
            results.append(row)
            verdict = "PASS" if row["selected_expected"] and not row["explorer_bled_into_regression"] else "FAIL"
            print(
                f"  {verdict} {name:16s} {row['latency_s']:6.1f}s "
                f"want={exp_tool}{'/' + exp_op if exp_op else ''} "
                f"got={','.join(row['tools_used']) or '-'} "
                f"ops={','.join(row['dir_explorer_ops']) or '-'}"
            )
            time.sleep(args.cooldown)
    finally:
        kill_process_tree(srv)

    out_file = SCRATCH / f"results-direxplore-{args.label}.json"
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    ok = sum(1 for r in results if r["selected_expected"] and not r["explorer_bled_into_regression"])
    newcap = sum(1 for r in results if r["expected_tool"] == "dir_explorer" and r["selected_expected"])
    print(f"\n== dir_explorer live-test [{adapter} / {args.label}] ==")
    print(f"selection PASS overall: {ok}/{len(results)} · new-capability picks: {newcap}/{sum(1 for r in results if r['expected_tool'] == 'dir_explorer')}")
    print(f"artifacts: {out_file}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
