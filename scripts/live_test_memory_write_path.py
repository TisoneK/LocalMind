#!/usr/bin/env python3
"""Live trace: what the memory write path accepts, keeps, and removes.

Run the SAME turns twice — once from a checkout of the previous revision
(`--label before`) and once from the working tree (`--label after`) — so the
claim is a measured difference rather than an assertion:

  turn 1  a live value (public IP + provider) the user asked to remember
  turn 2  a durable preference
  turn 3  the SAME preference again — one row, or a duplicate?
  turn 4  the memory list, asked for by name — does it print fact ids?
  turn 5  "forget #<id>" — is the removal verified?

Reads and deletes are not on the deterministic path the way writes are, so
turns 4-5 NAME the tool; whether the model actually calls it is part of what
the trace records. The REST memory surface is exercised inline afterwards
(list + delete by short id) so the store-side behavior is measured either way.

Evidence lands in scratch/live-memory-write-path/: SSE per turn, the isolated
home's vector_facts rows (id / memory_key / memory_kind / content), the server
log, and a results JSON.

Usage:
  cd backend && .venv/Scripts/python.exe ../scripts/live_test_memory_write_path.py --label after
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
SC = REPO / "scratch" / "live-memory-write-path"
TH = SC / "tracehome"
VENV_PY = venv_python(BACKEND)

TURNS: list[tuple[str, str | None]] = [
    (
        "turn1_live_value",
        "Remember that my public IP is 41.90.11.7 and my ISP is Safaricom. Just acknowledge.",
    ),
    ("turn2_preference", "Remember that I prefer concise answers. Just acknowledge."),
    ("turn3_restate", "Remember this: I prefer concise answers."),
    (
        "turn4_list",
        "Call the memory_op tool with operation list, then repeat its raw output exactly, "
        "including each fact id.",
    ),
    ("turn5_forget", None),  # filled with an id the list printed
]


def _prepare_home(keep: bool = False) -> None:
    """Fresh scratch home with the provider key bridged in (never printed).

    `keep` continues a previous run's home — how a follow-up pass (a turn the
    provider rate-limited) sees the rows the earlier turns stored.
    """
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


def _final_text(sse: str) -> str:
    parts = []
    for line in sse.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            ev = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "token":
            parts.append(ev.get("content", "") or "")
    return "".join(parts)


def _rows() -> list[dict]:
    db = TH / "localmind.db"
    if not db.exists():
        return []
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        raw = conn.execute("SELECT id, content, metadata FROM vector_facts").fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    rows = []
    for fact_id, content, metadata in raw:
        try:
            meta = json.loads(metadata or "{}")
        except ValueError:
            meta = {}
        rows.append(
            {
                "id": fact_id,
                "content": content,
                "memory_key": meta.get("memory_key", ""),
                "memory_kind": meta.get("memory_kind", ""),
                "memory_freshness": meta.get("memory_freshness", ""),
                "memory_type": meta.get("memory_type", ""),
            }
        )
    return rows


def _rest_json(port: int, path: str, method: str = "GET") -> dict:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace") or "{}")


def _rest_roundtrip(port: int, rows: list[dict]) -> dict:
    """Exercise the stored-memory surface the app itself uses: list, then delete
    by the SHORT id the screen shows. The short id has to resolve, or the id a
    user can read is an id the user cannot act on."""
    out: dict = {"listed": 0, "deleted": False, "rows_after": None}
    try:
        facts = _rest_json(port, "/api/memory").get("facts", [])
        out["listed"] = len(facts)
        for fact in rows:
            if fact.get("memory_kind") == "preference":
                resp = _rest_json(port, f"/api/memory/{fact['id'][:8]}", method="DELETE")
                out["deleted"] = bool(resp.get("deleted"))
                break
        out["rows_after"] = len(_rest_json(port, "/api/memory").get("facts", []))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="after")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--turns", default="1,2,3,4", help="comma list; empty runs only the REST checks")
    ap.add_argument("--pause", type=int, default=8, help="seconds between turns (free-tier pacing)")
    ap.add_argument("--keep-home", action="store_true", help="continue the previous run's store")
    args = ap.parse_args()

    try:
        # A Windows console is cp1252: model text can carry characters it cannot
        # encode, and a print must never abort a trace.
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    _prepare_home(keep=args.keep_home)
    log_path = SC / f"server-{args.label}.log"
    session_id = f"memory-write-{args.label}-{int(time.time())}"
    print(f"[boot] port {args.port} home {TH} (keys never printed)")

    proc = None
    results = []
    try:
        proc = _boot(args.port, log_path)
        print(f"[boot] healthy (pid={proc.pid})")
        for num in [n for n in args.turns.split(",") if n.strip()]:
            name, message = TURNS[int(num) - 1]
            if name == "turn5_forget":
                ids = re.findall(r"#([0-9a-f]{8})", "\n".join(r["text"] for r in results))
                if not ids:
                    print("[skip] forget turn - no id was surfaced by the list")
                    continue
                message = (
                    f"Call the memory_op tool with operation=forget and content='#{ids[0]}', "
                    "then repeat its raw output exactly."
                )
            print(f"[run] {name}: {message!r}")
            try:
                sse, wall = _fire(args.port, message, session_id, args.timeout)
            except Exception as exc:
                sse, wall = f"<EXC {exc}>", 0.0
            (SC / f"sse-{args.label}-{name}.sse").write_text(sse, encoding="utf-8", errors="replace")
            text = _final_text(sse)
            results.append({"turn": name, "message": message, "wall_s": round(wall, 1), "text": text})
            print(f"  -> {wall:.1f}s | {text.strip()[:220]!r}")
            time.sleep(args.pause)
        # Runs while the server is up: the write/delete surface the app itself
        # uses is the second half of the evidence when the model is throttled.
        rest = _rest_roundtrip(args.port, _rows())
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
        "volatile_value_refused": ("volatile_fact" in log_text) or ("rather not keep" in text_all),
        "volatile_rows_in_store": len([r for r in rows if "41.90.11.7" in r["content"]]),
        "rows_for_preference": len([r for r in rows if "concise" in r["content"].lower()]),
        "rows_total": len(rows),
        "keyed_rows": len([r for r in rows if r["memory_key"]]),
        "listed_ids_in_chat": len(re.findall(r"#([0-9a-f]{8})", text_all)),
        "forget_confirmed_in_chat": "Removed from memory" in text_all,
        "rest_listed": rest["listed"],
        "rest_delete_by_short_id": rest["deleted"],
        "rest_rows_after_delete": rest["rows_after"],
        "rest_error": rest.get("error", ""),
    }
    payload = {
        "label": args.label,
        "session": session_id,
        "turns": results,
        "rows": rows,
        "rest": rest,
        "checks": checks,
    }
    (SC / f"results-{args.label}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("\n[rows in the isolated store]")
    for row in rows:
        print(f"  {row['id'][:8]} key={row['memory_key'] or '-'} kind={row['memory_kind'] or '-'} "
              f"fresh={row['memory_freshness'] or '-'} :: {row['content'][:90]}")
    print("\n[checks]")
    for key, value in checks.items():
        print(f"  {key}: {value}")
    print(f"\n[done] evidence in {SC}")


if __name__ == "__main__":
    main()
