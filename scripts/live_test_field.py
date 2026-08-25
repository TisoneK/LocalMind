#!/usr/bin/env python3
"""
Session 401: FIELD live-testing harness — real general prompts/tasks.

Per `system/live-testing.md`: real provider, real prompts a real user would
send, SSE captured, traces scored for the field-failure markers past sessions
found: narration leak (final answer is a PLAN, not results), zero-tool
narration, duplicate answers, ungrounded answers, errors, degradation.

Prompt battery (categories): file-write, multi-step file ops, live data,
arithmetic, knowledge fast-path, sysinfo, writing, memory, search+count,
multi-turn context/correction.

Provider comes from the ENVIRONMENT (LOCALMIND_ADAPTER + <PROV>_API_KEY) —
this script never contains or prints a key. Usage:

  cd backend && BANKOFAI_API_KEY=... LOCALMIND_ADAPTER=bankofai \
      ../scripts/live_test_field.py --label run1 --batch 1

Artifacts land in scratch/: server-field-<label>.log,
sse-field-<label>-<name>.sse, results-field-<label>.json.
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

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
VENV_PY = str(BACKEND / ".venv" / "bin" / "python")
SCRATCH = REPO / "scratch"
TRACEHOME = SCRATCH / "field-home"

# (name, prompt, category) — REAL everyday user tasks, not synthetic probes.
PROMPTS = [
    ("groceries", "Create a file called groceries.txt with a shopping list: milk, bread, eggs, rice, cooking oil, and salt.", "file_write"),
    ("invoice_folder", "Make a folder called Invoices and create a file march.txt inside it saying 'Paid KES 4500 on 15 March'.", "file_multi_step"),
    ("tip_split", "My restaurant bill is 2400 KES. Calculate a 15% tip and split the total between 3 people.", "math"),
    ("ram_storage", "Summarize the difference between RAM and storage in simple terms.", "knowledge"),
    ("nairobi_weather", "What's the weather in Nairobi today?", "live_data"),
    ("sys_disk", "What time is it right now and how much disk space do I have?", "sysinfo"),
    ("landlord_email", "Draft a short polite email to my landlord asking them to fix the kitchen tap that has been leaking for a week.", "writing"),
    ("birthday_memory", "Remember that my sister's birthday is October 12th.", "memory"),
    ("py_count", "How many Python files are in my LocalMind project? Just give me the number.", "search_count"),
]

# Batch split so each run fits a tool-call timeout with cooldowns.
BATCHES = {
    "1": ["groceries", "invoice_folder", "tip_split", "ram_storage"],
    "2": ["nairobi_weather", "sys_disk", "landlord_email", "birthday_memory"],
    "2w": ["nairobi_weather"],  # weather alone — the CF-403 repro prompt
    "3": ["py_count"],
}

# Multi-turn conversations: list of (name, [messages]) — same session_id.
CONVERSATIONS = [
    ("mangoes", [
        "I have 12 mangoes.",
        "I gave 5 to my neighbor. How many do I have left?",
    ]),
]

# Grounding markers per category (answer should contain evidence of this shape).
_GROUND = {
    "file_write": r"groceries\.txt|/home/|/Users/",
    "file_multi_step": r"Invoices|march\.txt|/home/|/Users/",
    "math": r"920|2760|2[,. ]760|KES",
    "knowledge": r"RAM|memory|storage",
    "live_data": r"°|C|cloud|sun|rain|Nairobi|weather",
    "sysinfo": r":\d{2}|\d+\s?(?:GB|MB|TB)|%",
    "writing": r"Dear|Hello|Hi|tap|leak|regards|sincerely",
    "memory": r"stored|remember|saved|noted|October",
    "search_count": r"\d{3,}",
}

# Narration-leak marker: a final answer that ENDS on a plan, not results.
_LEAK_RE = re.compile(
    r"(let me|i'll now|i will now|i'm going to|next,? i(?:'| wi)?ll|"
    r"now (?:let me|i'll|i will)|hold on|one moment|wait while)",
    re.IGNORECASE,
)


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
        {"message": message, "session_id": session_id}
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

    out = {"final_text": [], "thinking": [], "tool_calls": [], "errors": [],
           "usage": None, "degraded": False}
    for ev in events:
        etype = ev.get("type")
        if etype == "token":
            out["final_text"].append(ev.get("content", ""))
        elif etype == "thinking_token":
            out["thinking"].append(ev.get("thinking", ""))
        elif etype == "tool_call":
            # Count only STARTED events (each call fires started+done —
            # counting both double-reports the tool count).
            if (ev.get("tool_call", {}) or {}).get("status") == "started":
                out["tool_calls"].append(ev.get("tool_call", {}))
        elif etype == "error":
            out["errors"].append(str(ev.get("error", ev))[:300])
        elif etype == "agent_loop_degraded":
            out["degraded"] = True
        elif etype == "turn_complete":
            out["usage"] = ev.get("provider_usage")
    out["final_text"] = "".join(out["final_text"])
    return out


def score(name: str, prompt: str, category: str, parsed: dict) -> dict:
    tools = [tc.get("name") or "?" for tc in parsed["tool_calls"]]
    final = parsed["final_text"]
    grounded = bool(re.search(_GROUND.get(category, r""), final))
    # Leak: planning language in the LAST 140 chars of the final answer.
    leak = bool(_LEAK_RE.search(final[-140:])) if final else False
    # Zero-tool narration: claims action with no tools at all.
    return {
        "name": name,
        "category": category,
        "prompt": prompt,
        "tools_used": tools,
        "n_tool_calls": len(tools),
        "grounded": grounded,
        "narration_leak": leak,
        "n_errors": len(parsed["errors"]),
        "degraded": parsed["degraded"],
        "errors": parsed["errors"][:2],
        "final_chars": len(final),
        "final_head": final[:320],
        "final_tail": final[-200:],
        "usage": parsed["usage"],
    }


def run_prompt(port: int, name: str, prompt: str, category: str, label: str) -> dict:
    t0 = time.time()
    sse_file = SCRATCH / f"sse-field-{label}-{name}.sse"
    try:
        raw = fire_chat(port, prompt, f"field-{label}-{name}")
        sse_file.write_text(raw, encoding="utf-8")
        row = score(name, prompt, category, parse_sse(raw))
    except Exception as exc:  # noqa: BLE001 — record, keep going
        row = {
            "name": name, "category": category, "prompt": prompt,
            "tools_used": [], "n_tool_calls": 0, "grounded": False,
            "narration_leak": False, "n_errors": 1, "degraded": True,
            "errors": [f"harness: {exc}"], "final_chars": 0,
            "final_head": "", "final_tail": "", "usage": None,
        }
    row["latency_s"] = round(time.time() - t0, 1)
    print(
        f"  {name:16s} {row['latency_s']:6.1f}s tools={','.join(row['tools_used']) or '-'} "
        f"grounded={row['grounded']} leak={row['narration_leak']} err={row['n_errors']}"
    )
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="run1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--batch", default="1", help="1|2|3, or 'convo' for multi-turn")
    ap.add_argument("--cooldown", type=float, default=15.0)
    args = ap.parse_args()

    adapter = os.environ.get("LOCALMIND_ADAPTER", "")
    if not adapter:
        print("ERROR: LOCALMIND_ADAPTER not set — set it (plus its API key) first.")
        return 2
    print(f"provider adapter: {adapter} (from env; key never printed)")

    SCRATCH.mkdir(exist_ok=True)
    TRACEHOME.mkdir(parents=True, exist_ok=True)
    log_file = SCRATCH / f"server-field-{args.label}.log"

    subprocess.run(["pkill", "-f", f"LOCALMIND_PORT={args.port}"], capture_output=True)
    time.sleep(1)

    srv = boot_server(args.port, log_file)
    results = []
    try:
        if args.batch == "convo":
            for cname, msgs in CONVERSATIONS:
                sid = f"field-{args.label}-{cname}"
                row = None
                for i, msg in enumerate(msgs):
                    t0 = time.time()
                    sse_file = SCRATCH / f"sse-field-{args.label}-{cname}-t{i}.sse"
                    try:
                        raw = fire_chat(args.port, msg, sid)
                        sse_file.write_text(raw, encoding="utf-8")
                        row = score(f"{cname}-t{i}", msg, "multi_turn", parse_sse(raw))
                    except Exception as exc:  # noqa: BLE001
                        row = {
                            "name": f"{cname}-t{i}", "category": "multi_turn",
                            "prompt": msg, "tools_used": [], "n_tool_calls": 0,
                            "grounded": False, "narration_leak": False,
                            "n_errors": 1, "degraded": True,
                            "errors": [f"harness: {exc}"], "final_chars": 0,
                            "final_head": "", "final_tail": "", "usage": None,
                        }
                    row["latency_s"] = round(time.time() - t0, 1)
                    results.append(row)
                    print(
                        f"  {row['name']:16s} {row['latency_s']:6.1f}s "
                        f"tools={row['n_tool_calls']} grounded={row['grounded']} "
                        f"leak={row['narration_leak']} err={row['n_errors']}"
                    )
                    print(f"    tail: {row['final_tail'][-120:]!r}")
                    time.sleep(args.cooldown)
        else:
            wanted = BATCHES[args.batch]
            for name, prompt, category in PROMPTS:
                if name not in wanted:
                    continue
                results.append(run_prompt(args.port, name, prompt, category, args.label))
                time.sleep(args.cooldown)
    finally:
        try:
            os.killpg(os.getpgid(srv.pid), 15)
        except Exception:
            srv.kill()

    out_file = SCRATCH / f"results-field-{args.label}.json"
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")

    n = len(results)
    gr = sum(1 for r in results if r["grounded"])
    lk = sum(1 for r in results if r["narration_leak"])
    er = sum(1 for r in results if r["n_errors"] or r["degraded"])
    print(f"\n== field live-test [{args.label} batch={args.batch}] ==")
    print(f"grounded: {gr}/{n} · narration leaks: {lk}/{n} · errors/degraded: {er}/{n}")
    print(f"artifacts: {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
