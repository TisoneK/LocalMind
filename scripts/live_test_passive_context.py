#!/usr/bin/env python3
"""Live-test harness for passive context awareness (B-2026-09-15-15).

Boots LocalMind on an isolated port with a scratch LOCALMIND_HOME, runs the
same three turns under a --label, and verifies the passive path end-to-end:

  turn 1  a durable self-fact stated incidentally (no "remember" trigger)
  turn 2  a question that benefits from it (does the recall surface it?)
  turn 3  the deterministic memory read ("what do you know about me") —
          the store's own id-bearing listing, independent of any model

After the turns, the script reads the scratch home's SQLite `vector_facts`
table DIRECTLY (the S014 direct-insert route in reverse — a read-back that
does not depend on the embedder) and prints the rows.

Usage (one invocation = one self-contained trace):
  backend/.venv/Scripts/python.exe scripts/live_test_passive_context.py --label baseline
  backend/.venv/Scripts/python.exe scripts/live_test_passive_context.py --label fix-1

Artifacts land in scratch/passive-s020/: server-<label>.log, sse-<label>-<n>.sse,
facts-<label>.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(errors="replace")  # cp1252 console trap (S014)

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
VENV_PY = BACKEND / ".venv" / "Scripts" / "python.exe"
SCRATCH = REPO / "scratch" / "passive-s020"

# Per-session harness port (the 8765 base + this session's codename number,
# per the shared-port lesson in the office log).
PORT = 8769

# The scratch home is seeded from the app's real settings.json so the trace
# uses real provider credentials — but the ADAPTER/MODEL fields are pinned
# here (keys are never read, printed, or modified by this script).
# Z.ai/GLM: the shared Gemini key's per-minute bucket drains under concurrent
# local sessions (429s with ~20s retry windows killed two verification runs);
# GLM-4.5-Flash is the always-free model, so the harness is reproducible.
SEED_SETTINGS_ADAPTER = "zai"
SEED_SETTINGS_MODEL = "glm-4.5-flash"

TURNS = [
    ("statement", "By the way, my name is Tisone and I'm based in Nairobi."),
    ("question", "What's a good evening spot around here?"),
    ("readback", "What do you know about me?"),
]


def _seed_home(home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    settings_path = home / "settings.json"
    real = Path.home() / "LocalMind" / "settings.json"
    if real.exists():
        data = json.loads(real.read_text(encoding="utf-8"))
    else:
        data = {}
    data["adapter"] = SEED_SETTINGS_ADAPTER
    data["model"] = SEED_SETTINGS_MODEL
    settings_path.write_text(json.dumps(data), encoding="utf-8")


def boot_server(home: Path, log_file: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env.update(
        {
            "LOCALMIND_PORT": str(PORT),
            "LOCALMIND_HOME": str(home),
            "LOCALMIND_SHELL_ENABLED": "true",
            "PYTHONPATH": str(BACKEND / "src"),
            "PYTHONUTF8": "1",
        }
    )
    proc = subprocess.Popen(
        [str(VENV_PY), "server.py"],
        cwd=str(BACKEND),
        env=env,
        stdout=open(log_file, "wb"),
        stderr=subprocess.STDOUT,
    )
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2).read()
            return proc
        except Exception:
            time.sleep(1)
    proc.kill()
    raise RuntimeError("server failed to start within 60s")


def fire_chat(message: str, session_id: str, timeout: int = 240) -> str:
    body = urllib.parse.urlencode(
        {"message": message, "session_id": session_id, "is_first": "true"}
    ).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/chat",
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
    types: dict[str, int] = {}
    text_parts: list[str] = []
    passive_events: list[dict] = []
    for evt in events:
        t = evt.get("type", "?")
        types[t] = types.get(t, 0) + 1
        if t == "token" and evt.get("content"):
            text_parts.append(evt["content"])
        if t == "passive_memory":
            passive_events.append(evt.get("memory") or {})
    return {
        "types": types,
        "text": "".join(text_parts),
        "passive_events": passive_events,
    }


def read_facts(home: Path) -> list[dict]:
    """Direct SQLite read-back of the fact rows (no embedder needed)."""
    db = home / "localmind.db"
    if not db.exists():
        return []
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT id, content, metadata FROM vector_facts ORDER BY created_at"
        ).fetchall()
    finally:
        conn.close()
    out = []
    for rid, content, metadata in rows:
        try:
            meta = json.loads(metadata)
        except Exception:
            meta = {}
        out.append({"id": rid, "content": content, "memory_kind": meta.get("memory_kind", "")})
    return out


def kill_port(port: int) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | "
             "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }"],
            capture_output=True,
        )
    else:
        subprocess.run(["bash", "-c", f"fuser -k {port}/tcp 2>/dev/null || true"], capture_output=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="baseline")
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args()

    SCRATCH.mkdir(parents=True, exist_ok=True)
    home = SCRATCH / f"home-{args.label}"
    _seed_home(home)
    log_file = SCRATCH / f"server-{args.label}.log"

    kill_port(PORT)
    time.sleep(1)
    print(f"[boot] port {PORT}, home {home}, log -> {log_file}")
    proc = None
    results = []
    try:
        proc = boot_server(home, log_file)
        print(f"[boot] ready pid={proc.pid}")
        sid = f"s020-{args.label}-{int(time.time())}"
        for i, (name, prompt) in enumerate(TURNS, 1):
            t0 = time.time()
            raw = fire_chat(prompt, sid, timeout=args.timeout)
            latency = time.time() - t0
            (SCRATCH / f"sse-{args.label}-{i}-{name}.sse").write_text(raw, encoding="utf-8")
            parsed = parse_sse(raw)
            print(
                f"[turn {i} {name}] {latency:.1f}s | passive_memory events: "
                f"{len(parsed['passive_events'])} | types: {parsed['types']}"
            )
            for pe in parsed["passive_events"]:
                print(f"    passive_memory: {pe}")
            excerpt = parsed["text"][:220].replace("\n", " ")
            print(f"    answer: {excerpt}")
            results.append(
                {"turn": name, "prompt": prompt, "latency_s": round(latency, 1),
                 "passive_events": parsed["passive_events"], "answer_excerpt": excerpt}
            )
            time.sleep(2)
        facts = read_facts(home)
        (SCRATCH / f"facts-{args.label}.json").write_text(
            json.dumps({"facts": facts, "turns": results}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"[facts] {len(facts)} rows in the store:")
        for f in facts:
            print(f"    [{f['memory_kind']}] {f['content'][:100]}")
        return 0
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
        kill_port(PORT)


if __name__ == "__main__":
    raise SystemExit(main())
