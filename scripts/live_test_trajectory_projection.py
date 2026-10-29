#!/usr/bin/env python3
"""Live verification: the trajectory view is a PROJECTION of the record.

docs/reference-harness-gap-inventory.md rows B + G — "the trajectory view is a
pure projection of the durable log, so the UI can neither show what was never
recorded nor hide what was." This proves it end to end in the running app.

The invariant under test: the trajectory the UI builds LIVE from the streamed
obs events must equal the trajectory the backend PERSISTS and returns on a
reload — both are the same projection of the same record.

How the proof closes without a real provider credential (none exists in this
sandbox — same constraint the provenance harness documents): a local fake
OpenAI-compatible provider drives the REAL server on isolated port 8765 +
scratch LOCALMIND_HOME through a real agent turn (plan → two real sysinfo tool
calls across iterations → answer). Then:

  1. Capture the SSE `obs_event` stream — exactly what the frontend's live
     projection (turnProjection.ts) consumes.
  2. Project that captured stream with the BACKEND projection
     (agent_workspace.build_run_tree / build_agent_phases). The cross-language
     contract test (turnProjection.contract.test.ts + the backend twin) proves
     this projection is byte-identical to the frontend's, so projecting it here
     stands in for the live frontend view.
  3. Reload: GET /api/sessions/<id>/history → the PERSISTED agentRuns /
     agentPhases (what the UI renders after a restart).
  4. Assert projection(live stream) == persisted (structural, volatile
     timestamps aside). Live view == reload == record.
  5. Reload AGAIN and assert the persisted projection is unchanged — a replay
     is stable.

Usage:
  ./scripts/live_test_trajectory_projection.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness_common import (
    kill_port,
    kill_process_tree,
    server_popen_kwargs,
    venv_python,
)

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
VENV_PY = venv_python(BACKEND)
SCRATCH = REPO / "scratch"
HOME = SCRATCH / "trajectoryhome"
PORT = 8765
FAKE_PORT = 18795
PROVIDER_NAME = "Projection Proof Provider"
INIT_MARKER = "initialization stage of LocalMind's parent agent"

sys.path.insert(0, str(BACKEND / "src"))


class FakeProvider(BaseHTTPRequestHandler):
    """Drives one real agent turn: classify → sysinfo (iter 1) → sysinfo
    (iter 2) → answer. The exact tool sequence is irrelevant to the proof —
    what matters is that the REAL loop emits real tool_call / phase / lifecycle
    obs events that both stream to the UI and persist."""

    request_count: ClassVar[int] = 0

    log_message = lambda self, *a, **k: None

    def _json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream(self, chunks: list[dict]):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for c in chunks:
            self.wfile.write(("data: " + json.dumps(c) + "\n\n").encode())
        self.wfile.write(b"data: [DONE]\n\n")

    def _text(self, reply: str) -> list[dict]:
        return [
            {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "proj-flash",
             "choices": [{"index": 0, "delta": {"role": "assistant", "content": reply}, "finish_reason": None}]},
            {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "proj-flash",
             "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ]

    def _tool(self, name: str, args: str) -> list[dict]:
        return [
            {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "proj-flash",
             "choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
                 {"index": 0, "id": f"call_{name}", "type": "function",
                  "function": {"name": name, "arguments": args}}]}, "finish_reason": None}]},
            {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "proj-flash",
             "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        ]

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._json({"object": "list", "data": [{"id": "proj-flash"}]})
        else:
            self._json({"ok": True})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        if "/chat/completions" not in self.path:
            self._json({"error": {"message": "not found"}}, 404)
            return
        FakeProvider.request_count += 1
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {}
        text = json.dumps(body)

        if INIT_MARKER in text:
            self._stream(self._text(json.dumps({
                "mode": "execute",
                "acknowledgement": "On it — checking the system.",
                "response": "",
                "objective": "Report the system clock and platform",
                "title": "System check",
                "plan": ["Check the system clock", "Report the platform"],
                "clarifying_question": "",
                "confidence": 0.9,
            })))
            return

        # Loop calls: two real sysinfo tool calls across iterations, then answer.
        n = FakeProvider.request_count
        if n == 1:
            self._stream(self._tool("sysinfo", '{"query": "clock"}'))
        elif n == 2:
            self._stream(self._tool("sysinfo", '{"query": "platform"}'))
        else:
            self._stream(self._text("Here is what the system reports."))


def boot_fake() -> ThreadingHTTPServer:
    FakeProvider.request_count = 0
    srv = ThreadingHTTPServer(("127.0.0.1", FAKE_PORT), FakeProvider)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def write_settings(real_provider: str | None) -> None:
    """Fake provider by default (deterministic, CI-safe). With --real <name>,
    point the isolated server at a genuinely configured provider so the turn
    is driven by a real model — the projection invariant must hold either way."""
    HOME.mkdir(parents=True, exist_ok=True)
    if real_provider:
        from harness_common import provider_key
        key = provider_key(real_provider)
        if not key:
            raise SystemExit(f"--real {real_provider}: no API key configured (set {real_provider.upper()}_API_KEY or ~/LocalMind/settings.json)")
        (HOME / "settings.json").write_text(json.dumps({
            "adapter": real_provider,
            "api_keys": {real_provider: key},
            "connections": [],
        }, indent=2))
        return
    (HOME / "settings.json").write_text(json.dumps({
        "adapter": "fakeprov",
        "api_keys": {"fakeprov": "sk-local-fake-not-a-real-key"},
        "connections": [{
            "id": "fakeprov",
            "name": PROVIDER_NAME,
            "kind": "openai-compat",
            "base_url": f"http://127.0.0.1:{FAKE_PORT}/v1",
            "model": "proj-flash",
            "enabled": True,
        }],
    }, indent=2))


def boot_server(log_file: Path, adapter: str) -> subprocess.Popen:
    env = os.environ.copy()
    env.update({
        "LOCALMIND_PORT": str(PORT),
        "LOCALMIND_HOME": str(HOME),
        "LOCALMIND_ADAPTER": adapter,
        "PYTHONPATH": str(BACKEND / "src"),
    })
    proc = subprocess.Popen(
        [VENV_PY, "server.py"], cwd=str(BACKEND), env=env,
        stdout=open(log_file, "wb"), stderr=subprocess.STDOUT, **server_popen_kwargs(),  # noqa: SIM115
    )
    for _ in range(45):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2).read()
            return proc
        except Exception:  # noqa: BLE001 — poll until the server's health endpoint answers
            time.sleep(1)
    proc.kill()
    raise RuntimeError("server failed to start within 45s")


def fire_chat(message: str, session_id: str, timeout: int = 240) -> str:
    body = urllib.parse.urlencode({"message": message, "session_id": session_id, "is_first": "true"}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/chat", data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "X-LocalMind-Intent": "tool"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def api_get(path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=15) as resp:
        return json.loads(resp.read().decode())


def parse_obs_stream(raw: str) -> list:
    """Extract the recorded obs events — exactly what the frontend's live
    projection consumes — from the SSE stream."""
    from core.obs import ObsEvent
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):]
        if payload == "[DONE]":
            continue
        try:
            frame = json.loads(payload)
        except json.JSONDecodeError:
            continue
        obs = frame.get("obs_event")
        if obs and obs.get("type"):
            out.append(ObsEvent(type=obs["type"], data=obs.get("data") or {}))
    return out


class _Shim:
    """Feeds captured obs events to the backend projection as a collector would."""

    def __init__(self, events):
        self._events = events

    def history(self):
        return self._events


_VOLATILE = {"timestamp", "startedAt", "completedAt"}


def _norm(value):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in _VOLATILE:
                continue
            nv = _norm(v)
            if nv is None or nv == "":
                continue
            out[k] = nv
        return out
    if isinstance(value, list):
        return [_norm(v) for v in value]
    return value


def main() -> int:
    from core.agent_workspace import build_agent_phases, build_run_tree

    # --real <provider> drives the turn with a genuinely configured model
    # (e.g. --real deepseek); default is the deterministic fake provider.
    real_provider = None
    if "--real" in sys.argv:
        i = sys.argv.index("--real")
        real_provider = sys.argv[i + 1] if i + 1 < len(sys.argv) else "deepseek"

    problems: list[str] = []
    # A real model needs a prompt that reliably wants a tool; the fake path
    # ignores the text (its loop is scripted). Either way a tool is expected,
    # but the invariant holds even for a no-tool turn.
    message = (
        "List the files in the current working directory, then tell me what platform I'm on."
        if real_provider
        else "What time is it and what platform am I on? Check the system."
    )
    # A unique session + a clean isolated HOME each run, so a prior run's
    # persisted turn can never leak in and make `assistant[-1]` shift between
    # the two reloads (that is a test artifact, not a projection instability).
    session_id = f"trajectory-projection-proof-{int(time.time())}"
    import shutil
    shutil.rmtree(HOME, ignore_errors=True)
    kill_port(PORT)
    kill_port(FAKE_PORT)
    fake = boot_fake() if not real_provider else None
    write_settings(real_provider)
    log = SCRATCH / "trajectoryhome-server.log"
    proc = None
    try:
        proc = boot_server(log, real_provider or "fakeprov")

        raw = fire_chat(message, session_id=session_id)
        stream_events = parse_obs_stream(raw)
        tool_calls = [e for e in stream_events if e.type == "tool_call"]
        if not tool_calls and not real_provider:
            problems.append("no tool_call obs events reached the SSE stream (the frontend record is empty)")

        # The LIVE view: project the captured stream the same way the frontend
        # does (contract-proven identical projection).
        shim = _Shim(stream_events)
        tree = build_run_tree(shim, task=message, root_id="parent")
        live_phases = build_agent_phases(shim)
        live_root = tree[0]
        live_tools = live_root.get("tools") or []
        # Apply the SAME has_content guard build_workspace_artifacts uses on
        # persist (and the frontend's settled projection applies), so a bare
        # parent-only tree for a trivial turn compares equal to the dropped one.
        has_content = bool(
            live_root.get("tools") or live_root.get("evidence")
            or live_phases or len(tree) > 1
        )
        live_runs = tree if has_content else []
        if not live_tools and not real_provider:
            problems.append("the projected run tree has no tools — live view would show an empty trajectory")

        # The RELOAD view: what the backend persisted and returns on restart.
        # Poll until the assistant message is on disk — persistence can trail the
        # stream close, and racing it is a test artifact, not an instability.
        def reload_assistant() -> dict | None:
            msgs = (api_get(f"/api/sessions/{session_id}/history").get("history") or [])
            asst = [m for m in msgs if m.get("role") == "assistant" and (m.get("content") or m.get("error"))]
            return asst[-1] if asst else None

        last = None
        for _ in range(20):
            last = reload_assistant()
            if last is not None:
                break
            time.sleep(0.25)
        if last is None:
            problems.append("reload: no assistant message persisted")
            persisted_runs, persisted_phases = [], []
        else:
            persisted_runs = last.get("agentRuns") or []
            persisted_phases = last.get("agentPhases") or []
        if not persisted_runs and not real_provider:
            problems.append("reload: the persisted message carries no agentRuns (nothing to render on restart)")

        # THE INVARIANT: live projection of the streamed record == persisted.
        if _norm(live_runs) != _norm(persisted_runs):
            problems.append(
                "run tree MISMATCH: the live projection of the streamed record differs from the "
                "persisted/reloaded tree — the UI is not a faithful projection.\n"
                f"    live:      {json.dumps(_norm(live_runs))[:600]}\n"
                f"    persisted: {json.dumps(_norm(persisted_runs))[:600]}"
            )
        if _norm(live_phases) != _norm(persisted_phases):
            problems.append(
                "phase strip MISMATCH between the live projection and the persisted record:\n"
                f"    live:      {json.dumps(_norm(live_phases))[:400]}\n"
                f"    persisted: {json.dumps(_norm(persisted_phases))[:400]}"
            )

        # Replay stability: a second reload returns the same projection.
        last2 = reload_assistant()
        runs2 = (last2.get("agentRuns") or []) if last2 else []
        if _norm(runs2) != _norm(persisted_runs):
            problems.append(
                "replay: a second reload returned a DIFFERENT tree — the projection is not stable\n"
                f"    first:  {json.dumps(_norm(persisted_runs))[:300]}\n"
                f"    second: {json.dumps(_norm(runs2))[:300]}"
            )

        print(
            f"--- turn fired: {len([e for e in stream_events])} obs events streamed, "
            f"{len(tool_calls)} tool_call event(s)\n"
            f"--- live projection: parent '{live_root.get('title')}' with {len(live_tools)} tool(s), "
            f"{len(live_root.get('phases') or [])} lifecycle phase(s), {len(live_phases)} strip phase(s)\n"
            f"--- persisted (reload): {len(persisted_runs)} run(s), {len(persisted_phases)} strip phase(s)"
        )
        print()
        if problems:
            print("FAIL")
            for p in problems:
                print(f"  - {p}")
            return 1
        print(
            "PASS — the trajectory the UI builds live from the streamed obs record is the SAME "
            "trajectory the backend persisted and returns on reload: run tree and phase strip match "
            "structurally, and a replay is stable. The view is a projection of the record, verified "
            "in the running app."
        )
        return 0
    finally:
        kill_process_tree(proc, use_sigkill=True)
        if fake is not None:
            fake.shutdown()
        kill_port(PORT)
        kill_port(FAKE_PORT)


if __name__ == "__main__":
    sys.exit(main())
