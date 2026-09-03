#!/usr/bin/env python3
"""
B-2026-09-02 / ADR-57 slice 1: live-verify gated live-streaming of the final
answer on a post-tool (web_research) turn.

Before (validate-then-show): the answer text is buffered for the guards and
arrives as ONE burst after the model stops generating (~51s dead air on the
ADR-57 timeline trace).
After (gated live streaming): the head flushes after a ~150-char marker-free
lookahead, then chunks stream as they arrive. TTFT should drop from
~turn-length to ~turn-start + first-chunk; the final answer must stay clean
(no tool-mechanics leaks, no duplicate text).

Usage:
  backend/.venv/bin/python scripts/live_test_stream_gating.py --label baseline|fix-N
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
TRACEHOME = SCRATCH / "tracehome-stream"
SETTINGS = TRACEHOME / "settings.json"
PORT = 8765

# Post-tool turn: forces web_research, so the final answer lands on the
# iteration>=1 path that the gated live-streaming covers (WEB-1, Session 336).
PROMPT = "Find the official description of Python and summarize it briefly."

# Session 336's web-acquisition quality bar (final text must not leak mechanics).
FORBIDDEN_TOKENS = [
    "which tool", "what tool", "web_search", "web_fetch", "browser_agent",
    "i used the web_search tool", "i called the browser", "specify the tool",
]


# The app settings.json ADAPTER wins over the LOCALMIND_ADAPTER env var, so the
# harness must WRITE the requested adapter (+ a matching model) into the scratch
# settings to actually switch providers. Keys are copied from the app settings.
_ADAPTER_MODEL = {
    "bankofai": "deepseek-v4-flash",
    "zai": "glm-4.5-flash",
    "chutes": "deepseek-ai/DeepSeek-V4-Flash-0731-TEE",
    "gemini": "gemini-2.5-flash",
}


def prepare_tracehome(adapter: str = "bankofai", model: str = "") -> None:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    TRACEHOME.mkdir(parents=True, exist_ok=True)
    # Copy the APP's settings so the trace sees the user's real api_keys.
    # Never print any api_keys value.
    src = Path.home() / "LocalMind" / "settings.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    data["adapter"] = adapter
    # Explicit --model wins; else the per-adapter default. (Some free models
    # live on the same provider as a now-paid one, e.g. bankofai/hy3.)
    if model:
        data["model"] = model
    elif adapter in _ADAPTER_MODEL:
        data["model"] = _ADAPTER_MODEL[adapter]
    data["shell_enabled"] = True
    SETTINGS.write_text(json.dumps(data), encoding="utf-8")


def boot_server(log_file: Path, adapter: str = "bankofai"):
    env = os.environ.copy()
    env.update(
        {
            "LOCALMIND_PORT": str(PORT),
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
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2).read()
            return proc
        except Exception:
            time.sleep(1)
    proc.kill()
    raise RuntimeError("server failed to start within 60s")


def fire_chat_timed(message: str, session_id: str, timeout: int = 270):
    """POST /api/chat, reading the SSE stream line by line with arrival times.

    Returns (raw_sse, timed) where timed is [(t_rel_s, line)] for every SSE
    data line — true wall-clock offsets, so TTFT is real, not inferred.
    """
    body = urllib.parse.urlencode({"message": message, "session_id": session_id}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/chat",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    t0 = time.time()
    timed = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw_parts = []
        for raw_line in resp:
            t_rel = round(time.time() - t0, 2)
            line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
            raw_parts.append(line)
            if line.startswith("data: "):
                timed.append((t_rel, line[6:]))
    return "\n".join(raw_parts), timed


def analyze(raw: str, timed, label: str) -> dict:
    events = []
    for t_rel, payload in timed:
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        # Obs events are wrapped: {"obs_event": {"type": ..., "data": {...}}}.
        # Token/error frames are top-level. Unwrap so `type` is always found.
        if isinstance(obj.get("obs_event"), dict):
            obj = obj["obs_event"]
        events.append((t_rel, obj))

    first_token_t = None
    last_token_t = None
    done_t = None
    tool_events = []
    token_payloads = []
    errors = []
    thinker_iters = []  # ADR-57 slice 2: which iterations the Thinker fired on
    thinker_starts = {}  # iteration -> start t_rel
    thinker_spans = []  # (iteration, duration_s) — consult wall time
    intent_seen = None
    for t_rel, obj in events:
        typ = obj.get("type") or ""
        if typ == "agent_thinker_start":
            data = obj.get("data") or obj
            it = data.get("iteration")
            thinker_iters.append(it)
            thinker_starts[it] = t_rel
        elif typ == "agent_thinker_done":
            data = obj.get("data") or obj
            it = data.get("iteration")
            if it in thinker_starts:
                thinker_spans.append((it, round(t_rel - thinker_starts[it], 2)))
        if intent_seen is None:
            intent_seen = obj.get("intent") or (obj.get("data") or {}).get("intent")
        if typ == "token":
            token_payloads.append(obj.get("content", "") or "")
            if first_token_t is None:
                first_token_t = t_rel
            last_token_t = t_rel
        elif typ == "tool_call":
            tool_events.append((obj.get("tool"), obj.get("status"), t_rel))
        elif typ in ("turn_complete", "done"):
            done_t = t_rel
        elif typ in ("error", "agent_loop_error"):
            # The error payload may be a dict (normalized provider error) or a
            # string — coerce before slicing so the analyzer never crashes.
            errors.append(str(obj.get("error", "") or "")[:160])

    answer = "".join(token_payloads)
    return {
        "label": label,
        "intent": intent_seen,
        "thinker_calls": len(thinker_iters),
        "thinker_iters": thinker_iters,
        "thinker_spans_s": thinker_spans,
        "ttft_s": first_token_t,
        "last_token_s": last_token_t,
        "turn_complete_s": done_t,
        "token_events": len(token_payloads),
        "answer_chars": len(answer),
        # Burst signature: ONE token event carrying (nearly) the whole answer.
        "burst_single_token": len(token_payloads) == 1 and len(answer) > 1000,
        "streamed": len(token_payloads) > 3,
        "tools": tool_events,
        "forbidden_leaks": [w for w in FORBIDDEN_TOKENS if w in answer.lower()],
        "duplicate_500": (
            len(answer) > 500 and answer[:250].strip() in answer[250:].strip()
        ),
        "empty_answer": len(answer) == 0,
        "errors": errors,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="fix-N", help="baseline | fix-N")
    ap.add_argument("--adapter", default="bankofai", help="bankofai | zai (weak-model check)")
    ap.add_argument("--prompt", default=PROMPT, help="override the turn prompt")
    ap.add_argument("--model", default="", help="override the model (e.g. hy3 on bankofai)")
    args = ap.parse_args()

    prepare_tracehome(adapter=args.adapter, model=args.model)
    kill_port(PORT)
    time.sleep(1)
    log_file = SCRATCH / f"server-stream-{args.label}.log"
    proc = boot_server(log_file, adapter=args.adapter)
    try:
        raw, timed = fire_chat_timed(
            args.prompt, session_id=f"stream-{args.label}-{int(time.time())}"
        )
        sse_file = SCRATCH / f"sse-stream-{args.label}.sse"
        sse_file.write_text(raw, encoding="utf-8")
        res = analyze(raw, timed, args.label)
        sse_file.with_name(f"results-stream-{args.label}.json").write_text(
            json.dumps(res, indent=2), encoding="utf-8"
        )
        print(json.dumps(res, indent=2))
        print(f"\nSSE saved: {sse_file}")
        print(f"Server log: {log_file}")
    finally:
        kill_process_tree(proc, use_sigkill=True)
        kill_port(PORT)


if __name__ == "__main__":
    main()
