#!/usr/bin/env python3
"""Live trace: are memory READS and DELETES deterministic, like writes?

Run the SAME turns twice — once from a checkout of the previous revision
(`--label before`) and once from the working tree (`--label after`) — so the
claim is a measured difference rather than an assertion:

  setup (REST, no model)  seed the store: a durable preference + a live value
  turn 1  "What do you know about me?"  → is the answer the STORE's listing
          (ids included), or the model improvising over injected context?
  turn 2  "list my memories"            → id-bearing listing, zero model calls?
  turn 3  "forget that I prefer dark mode" → applied and confirmed from a
          read-back, without the model choosing whether to act?

The previous revision routed these turns through the model — the read reached
the tool only when the model happened to choose it — so its replies vary. The
current revision answers from the store directly; the discriminators are the
server log's "deterministic memory-read/delete" lines, the id-bearing listing,
the read-back confirmation, and the done event's provider usage (a
deterministic turn makes no provider call, so usage is empty/absent).

Evidence lands in scratch/live-memory-routing/: SSE per turn, the isolated
home's vector_facts rows, the server log, and a results JSON.

Usage:
  cd backend && .venv/Scripts/python.exe ../scripts/live_test_memory_routing.py --label before
  cd backend && .venv/Scripts/python.exe ../scripts/live_test_memory_routing.py --label after
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from harness_common import provider_key, venv_python

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
SC = REPO / "scratch" / "live-memory-routing"
TH = SC / "tracehome"
VENV_PY = venv_python(BACKEND)

PREFERENCE = "The user prefers dark mode in their editor."
LIVE_VALUE = "The user's public IP is 41.90.44.19."

TURNS: list[tuple[str, str]] = [
    ("turn1_what_do_you_know", "What do you know about me?"),
    ("turn2_list", "list my memories"),
    ("turn3_forget", "forget that I prefer dark mode"),
]


def _prepare_home(keep: bool = False) -> None:
    """Fresh scratch home with the provider key bridged in (never printed)."""
    key = provider_key("zai")
    if not key:
        sys.exit("ERROR: no zai key in env (ZAI_API_KEY) or ~/LocalMind/settings.json")
    if SC.exists() and not keep:
        shutil.rmtree(SC)
    TH.mkdir(parents=True, exist_ok=True)
    (TH / "settings.json").write_text(
        json.dumps(
            {
                "adapter": "zai",
                "model": "glm-4.5-flash",
                "thinking": "enabled",
                "reasoning_effort": "low",
                "shell_enabled": True,
                "api_keys": {"zai": key},
            }
        )
    )


def _boot(port: int, log_path: Path) -> subprocess.Popen:
    env = {
        **os.environ,
        "LOCALMIND_PORT": str(port),
        "LOCALMIND_HOME": str(TH),
        "LOCALMIND_ADAPTER": "zai",
        "LOCALMIND_SHELL_ENABLED": "true",
        "PYTHONPATH": str(BACKEND / "src"),
    }
    log = open(log_path, "wb")
    proc = subprocess.Popen(
        [VENV_PY, "server.py"],
        cwd=str(BACKEND),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2).read()
            return proc
        except Exception:
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError("server did not become healthy in 30s")


def _rest_json(port: int, path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace") or "{}")


def _seed(port: int) -> int:
    """Seed the store so the turns have something deterministic to answer from.

    The app's own POST /api/memory route embeds every write, and this box has
    no embedder (Ollama down, no cloud key) — a REST seed 503s. The store
    itself re-reads vector_facts on every call, so a direct insert is what
    store() would have written: (id, content, metadata JSON).
    """
    import uuid

    conn = sqlite3.connect(TH / "localmind.db")
    try:
        rows = [
            (uuid.uuid4().hex, PREFERENCE, {"memory_type": "user_preference", "importance": "0.8", "access_count": "0"}),
            (uuid.uuid4().hex, LIVE_VALUE, {"memory_type": "general", "importance": "0.5", "access_count": "0"}),
        ]
        for fact_id, content, meta in rows:
            conn.execute(
                "INSERT INTO vector_facts(id, content, metadata) VALUES (?, ?, ?)",
                (fact_id, content, json.dumps(meta)),
            )
        conn.commit()
        return conn.execute("SELECT COUNT(*) FROM vector_facts").fetchone()[0]
    finally:
        conn.close()


def _fire(port: int, message: str, session_id: str, timeout: int) -> tuple[str, float]:
    body = urllib.parse.urlencode(
        {"message": message, "session_id": session_id, "is_first": "true"}
    ).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/chat",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace"), time.monotonic() - t0


def _sse_events(sse: str) -> list[dict]:
    evs = []
    for line in sse.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            evs.append(json.loads(line[6:]))
        except json.JSONDecodeError:
            continue
    return evs


def _final_text(sse: str) -> str:
    return "".join(
        ev.get("content", "") or "" for ev in _sse_events(sse) if ev.get("type") == "token"
    )


def _done_usage(sse: str) -> dict:
    """Provider usage on the LAST done event ({} when none was attached)."""
    usage: dict = {}
    for ev in _sse_events(sse):
        if ev.get("type") == "done":
            usage = ev.get("provider_usage") or {}
    return usage


def _rows() -> list[dict]:
    db = TH / "localmind.db"
    if not db.exists():
        return []
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        raw = conn.execute("SELECT id, content FROM vector_facts").fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return [{"id": fid, "content": content} for fid, content in raw]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="after")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--pause", type=int, default=8, help="seconds between turns (free-tier pacing)")
    ap.add_argument("--skip-setup", action="store_true", help="continue the previous run's store")
    args = ap.parse_args()

    try:
        # A Windows console is cp1252: model text can carry characters it cannot
        # encode, and a print must never abort a trace.
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    _prepare_home(keep=args.skip_setup)
    log_path = SC / f"server-{args.label}.log"
    session_id = f"memory-routing-{args.label}-{int(time.time())}"
    print(f"[boot] port {args.port} home {TH} (keys never printed)")

    proc = None
    results = []
    seeded_count = None
    try:
        proc = _boot(args.port, log_path)
        print(f"[boot] healthy (pid={proc.pid})")
        if not args.skip_setup:
            seeded_count = _seed(args.port)
            listed = len(_rest_json(args.port, "/api/memory").get("facts", []))
            print(f"[setup] seeded store ({seeded_count} rows); /api/memory lists {listed}")
        time.sleep(2)
        for name, message in TURNS:
            print(f"[run] {name}: {message!r}")
            try:
                sse, wall = _fire(args.port, message, session_id, args.timeout)
            except Exception as exc:
                sse, wall = f"<EXC {exc}>", 0.0
            (SC / f"sse-{args.label}-{name}.sse").write_text(
                sse, encoding="utf-8", errors="replace"
            )
            text = _final_text(sse)
            results.append(
                {
                    "turn": name,
                    "message": message,
                    "wall_s": round(wall, 1),
                    "text": text,
                    "done_provider_usage": _done_usage(sse),
                }
            )
            print(f"  -> {wall:.1f}s | usage={bool(results[-1]['done_provider_usage'])} "
                  f"| {text.strip()[:160]!r}")
            time.sleep(args.pause)
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()

    rows = _rows()
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    text_all = "\n".join(r["text"] for r in results)
    checks = {
        "seeded_facts": seeded_count,
        "deterministic_read_logged": "deterministic memory-read" in log_text,
        "deterministic_delete_logged": "deterministic memory-delete" in log_text,
        "listing_has_ids": bool(re.search(r"#[0-9a-f]{8}", text_all)),
        "listing_names_seeded_fact": "dark mode" in text_all,
        "delete_confirmed_in_chat": "Removed from memory" in text_all,
        "preference_row_gone_after_forget": len(
            [r for r in rows if "dark mode" in r["content"].lower()]
        ),
        "rows_total": len(rows),
        "any_turn_with_provider_usage": any(r["done_provider_usage"] for r in results),
    }
    payload = {
        "label": args.label,
        "session": session_id,
        "turns": results,
        "rows": rows,
        "checks": checks,
    }
    (SC / f"results-{args.label}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

    print("\n[rows in the isolated store]")
    for row in rows:
        print(f"  {row['id'][:8]} :: {row['content'][:90]}")
    print("\n[checks]")
    for key, value in checks.items():
        print(f"  {key}: {value}")
    print(f"\n[done] evidence in {SC}")


if __name__ == "__main__":
    main()
