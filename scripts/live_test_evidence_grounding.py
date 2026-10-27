#!/usr/bin/env python3
"""Live-trace verification for the evidence-grounding acceptance criterion.

Boots LocalMind on isolated port 8765 + scratch LOCALMIND_HOME, fires the
weather prompt that produced the fabrication trace (a forecast asserted
from a JavaScript-shell page whose readable extract was navigation chrome),
captures SSE, and scores the turn for:

  - `agent_loop_gate_failed_replan` events whose unmet list names
    "figures in the answer appear in no tool result" (the new criterion);
  - whether the FINAL delivered answer still asserts measured figures
    (the fabrication signature) — after the criterion, a turn that
    invented figures must end with either a grounded answer or an honest
    gap report, never a bare invented forecast;
  - a control prompt (no figures) that must never trip the criterion.

Requires a provider credential in the scratch home's settings.json
(copy the app's settings file — never print its contents). Primary
provider: bankofai/deepseek-v4-flash (LOCALMIND_ADAPTER=bankofai).

Usage:
  cd backend && ../scripts/live_test_evidence_grounding.py [--label baseline|fix]
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_common import kill_port, kill_process_tree, server_popen_kwargs, venv_python  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
VENV_PY = venv_python(BACKEND)
SCRATCH = REPO / "scratch"
TRACEHOME = SCRATCH / "tracehome"
SETTINGS = TRACEHOME / "settings.json"

PROMPTS = [
    # The fabrication repro: a place whose best-known sources are
    # JavaScript-rendered, so the static fetch returns chrome.
    ("weather_kitengela", "whats the weather like in Kitengela"),
    # Control: no measured figures, must never trip the criterion.
    ("capital_france", "What is the capital of France?"),
]

# The unmet note the new criterion emits through the gate-replan event.
_GROUNDING_UNMET = re.compile(r"figures in the answer appear in no tool result", re.IGNORECASE)
# The fabrication signature in a delivered answer: measured quantities.
_FIGURE_SIGNATURE = re.compile(
    r"\b\d+(?:\.\d+)?\s*°\s*[CF]"
    r"|\b\d+(?:\.\d+)?\s*(?:km/h|kph|mph)\b"
    r"|\b\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?\s*mm\b"
    r"|\b\d+(?:\.\d+)?\s*%\s*(?:humidity|chance)",
    re.IGNORECASE,
)
# Honest-gap wording: the acceptable alternative to a grounded forecast.
_HONEST_GAP = re.compile(
    r"(couldn't|could not|did not|didn't|no|not)\s+(find|contain|available|"
    r"able|access|retrieve|get)|no forecast|insufficient|not contained",
    re.IGNORECASE,
)


def boot_server(port: int, log_file: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env.update(
        {
            "LOCALMIND_PORT": str(port),
            "LOCALMIND_HOME": str(TRACEHOME),
            # Default to the primary live-test provider; a caller-exported
            # LOCALMIND_ADAPTER (plus its key env) wins — the evidence-grounding
            # repro runs on the exact model from the failure trace, cerebras.
            "LOCALMIND_ADAPTER": os.environ.get("LOCALMIND_ADAPTER", "bankofai"),
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
    text_parts, replans, errors, tool_calls = [], [], [], []
    for ev in events:
        etype = ev.get("type")
        if etype == "token":
            text_parts.append(ev.get("content", ""))
        elif etype in ("agent_loop_gate_failed_replan", "gate_failed_replan"):
            unmet = " ".join(str(u) for u in ev.get("unmet", []))
            replans.append(unmet)
        elif etype == "tool_call":
            tool_calls.append(ev.get("tool", ""))
        elif etype == "error":
            errors.append(ev.get("error", {}))
    # The workspace relays gate replans under a nested event too.
    if not replans:
        for ev in events:
            blob = json.dumps(ev)
            if _GROUNDING_UNMET.search(blob):
                replans.append("(relayed gate_replan payload matches)")
                break
    return {
        "events": events,
        "final_text": "".join(text_parts),
        "replans": replans,
        "tool_calls": tool_calls,
        "errors": errors,
    }


def score(label: str, name: str, prompt: str, parsed: dict, latency_s: float) -> dict:
    text = parsed["final_text"]
    grounding_fired = any(_GROUNDING_UNMET.search(r) for r in parsed["replans"])
    figures_in_final = sorted({m.group(0) for m in _FIGURE_SIGNATURE.finditer(text)})
    honest_gap = bool(_HONEST_GAP.search(text))
    # The failure this criterion closes: invented figures delivered as the
    # final answer with no grounding replan on the way.
    fabrication_delivered = bool(figures_in_final) and not grounding_fired and not honest_gap
    verdict = (
        "PASS: grounding replan fired" if grounding_fired
        else ("PASS: honest gap report" if honest_gap and figures_in_final
              else ("PASS: no figures asserted" if not figures_in_final
                    else "FAIL: figures delivered with no grounding replan"))
    )
    if name == "capital_france" and grounding_fired:
        verdict = "FAIL: criterion fired on a figure-free control"
    print(f"\n{'=' * 72}")
    print(f"  LABEL       : {label}")
    print(f"  PROMPT      : {name!r} — {prompt[:60]!r}")
    print(f"  LATENCY     : {latency_s:.1f}s   TOOLS: {len(parsed['tool_calls'])}")
    print(f"  GATE REPLANS: {parsed['replans'] or 'none'}")
    print(f"  FIGURES     : {figures_in_final or 'none'}")
    print(f"  HONEST GAP  : {honest_gap}")
    print(f"  VERDICT     : {verdict}")
    if parsed["errors"]:
        print(f"  ERRORS      : {parsed['errors'][:2]}")
    print(f"  ANSWER      : {text[:220]!r}")
    print(f"{'=' * 72}\n")
    return {
        "label": label,
        "prompt_name": name,
        "latency_s": round(latency_s, 1),
        "tools": parsed["tool_calls"],
        "gate_replans": parsed["replans"],
        "grounding_criterion_fired": grounding_fired,
        "figures_in_final": figures_in_final,
        "honest_gap": honest_gap,
        "fabrication_delivered": fabrication_delivered,
        "verdict": verdict,
        "errors": parsed["errors"],
        "final_text_excerpt": text[:600],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="fix")
    ap.add_argument("--prompts", default="weather_kitengela,capital_france")
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args()

    if not SETTINGS.exists():
        print(
            "[setup] no scratch settings yet — copy the app's settings file "
            "into scratch/tracehome/settings.json (never print its contents)."
        )
        sys.exit(2)

    SCRATCH.mkdir(parents=True, exist_ok=True)
    TRACEHOME.mkdir(parents=True, exist_ok=True)
    port = 8765
    log_file = SCRATCH / f"server-{args.label}.log"
    kill_port(port)
    time.sleep(1)
    print(f"[boot] starting server on port {port}, log -> {log_file}")
    proc = None
    try:
        proc = boot_server(port, log_file)
        print(f"[boot] server ready (pid={proc.pid})")
        results = []
        for name in args.prompts.split(","):
            name = name.strip()
            prompt = dict(PROMPTS).get(name)
            if prompt is None:
                print(f"[skip] unknown prompt {name!r}")
                continue
            sid = f"s006-grounding-{name}-{int(time.time())}"
            sse_file = SCRATCH / f"sse-{args.label}-{name}.sse"
            t0 = time.time()
            raw = fire_chat(port, prompt, sid, timeout=args.timeout)
            latency = time.time() - t0
            sse_file.write_text(raw, encoding="utf-8")
            print(f"[trace] {name}: saved {sse_file} ({len(raw)} bytes, {latency:.1f}s)")
            results.append(score(args.label, name, prompt, parse_sse(raw), latency))
            time.sleep(8)  # provider rate-limit cooldown
        out = SCRATCH / f"results-{args.label}.json"
        out.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"[done] results -> {out}")
    finally:
        if proc is not None:
            kill_process_tree(proc)
        kill_port(port)


if __name__ == "__main__":
    main()
