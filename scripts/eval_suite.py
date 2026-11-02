"""The standing eval harness (B-2026-10-31-23) — the audit §1.7 scenario
suite run against the live app.

One invocation is self-contained, per `system/live-testing.md`: boot the
REAL LocalMind server on port 8765 with a scratch LOCALMIND_HOME, run the
scenarios from `eval_scenarios.py` turn by turn over the chat SSE, score
every turn structurally (tools, lanes, observability events, questions,
latency) and — in deterministic mode — against the pinned content
expectations, then write machine-readable results + a markdown report
into `scratch/eval-suite-<label>/`.

Providers:
  --provider fake (default)  a scripted local OpenAI-compat provider (no
                             key); content expectations are REQUIRED —
                             this mode verifies the PIPELINE end to end.
  --provider real            boot against the app's real settings file
                             (copied verbatim into the scratch home; keys
                             never read, printed, or logged). Content
                             expectations become ADVISORY; exclusions
                             (defect signatures) still gate. This is the
                             mode that scores the model.

Suite metrics (the audit's six): task completion, factual accuracy
(fixture-pinned in fake mode; advisory note on a real provider), tool
success, recovery rate (failure-injecting scenarios), unnecessary
questions, latency (wall + the provider timing pair from the wire).

Usage:
  python scripts/eval_suite.py --list
  python scripts/eval_suite.py                          # full suite, fake
  python scripts/eval_suite.py --scenario offer-then-approval,failed-tool
  python scripts/eval_suite.py --provider real --label weekly
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
sys.path.insert(0, str(REPO / "scripts"))
from eval_scenarios import ALL_SCENARIOS, Scenario, TurnSpec
from harness_common import kill_process_tree, server_popen_kwargs, venv_python

PORT = 8765
FAKE_PORT = 18776
CLASSIFY_MARKER = "direct|clarify|execute"

QUESTION_RE = re.compile(r"\?\s*$")

# Content-check kinds — used by the report to split authoritative
# structural results from fixture-pinned content results.
STRUCTURAL = "structural"
CONTENT = "content"


# ─── The scripted deterministic provider ───────────────────────────────

class ActiveScript:
    """The running scenario's provider script. Steps match per provider
    call, first match wins. `tool`/`after` steps are once-only, in
    declared order (the app's call sequence is deterministic given the
    scripted responses); `classify`/`user`/`any` are stateless."""

    def __init__(self, steps: tuple[tuple, ...], scratch: str):
        self.scratch = scratch
        self.once: list[tuple] = list(steps)
        self.stateless: list[tuple] = list(steps)

    def _subst(self, value):
        if isinstance(value, str):
            return value.replace("{scratch}", self.scratch)
        if isinstance(value, tuple):
            return tuple(self._subst(v) for v in value)
        if isinstance(value, list):
            return [self._subst(v) for v in value]
        return value

    def _last_user(self, messages: list[dict]) -> str:
        for m in reversed(messages or []):
            if m.get("role") == "user":
                return str(m.get("content") or "")
        return ""

    def _last_tool_msg(self, messages: list[dict]) -> tuple[str, str] | None:
        """(tool_call_id, content) of the last tool-role message."""
        for m in reversed(messages or []):
            if m.get("role") == "tool":
                return str(m.get("tool_call_id") or ""), str(m.get("content") or "")
        return None

    def match(self, body: dict) -> tuple | None:
        messages = body.get("messages") or []
        blob = json.dumps(messages)
        last_user = self._last_user(messages)
        has_tools = isinstance(body.get("tools"), list) and bool(body["tools"])

        # The app re-mints tool-call ids, so `after` steps match by ORDER:
        # the Nth `after` step answers the request that carries the Nth tool
        # result anywhere in the conversation (tool scenarios are
        # single-turn by contract — see eval_scenarios.py).
        tool_results = sum(1 for m in messages if m.get("role") == "tool")
        first_tool_pending = tool_results == 0

        # 1. once-only `after` steps, in order (the Nth tool result).
        for step in list(self.once):
            if step[0] == "after" and tool_results >= step[1]:
                self.once.remove(step)
                return self._subst(step)

        # 2. stateless matches — classify (model-driven classify turns only)
        # before user-text steps (the classify call re-sends the user text).
        # User steps come BEFORE the once-only `tool` steps: a turn that
        # should OPEN with prose (the offer) must not be answered by a tool
        # delta just because the loop attaches tool schemas to its first
        # call.
        for step in self.stateless:
            if step[0] == "classify" and CLASSIFY_MARKER in blob:
                return step
        for step in self.stateless:
            if step[0] == "user" and step[1] in last_user:
                return step

        # 3. once-only `tool` steps (the loop's first iteration).
        for step in list(self.once):
            if step[0] == "tool" and has_tools and first_tool_pending:
                self.once.remove(step)
                return self._subst(step)
        # 3. fallback.
        for step in self.stateless:
            if step[0] == "any":
                return step
        if CLASSIFY_MARKER in blob:
            return ("classify", "execute", "")
        return ("any", "Noted.")


def _sse_chunks(handler: BaseHTTPRequestHandler, chunks: list[dict]) -> None:
    for c in chunks:
        handler.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
        handler.wfile.flush()
    handler.wfile.write(b"data: [DONE]\n\n")
    handler.wfile.flush()


def _text_chunks(text: str, model: str) -> list[dict]:
    return [
        {"id": "ev", "object": "chat.completion.chunk", "created": 1, "model": model,
         "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]},
        {"id": "ev", "object": "chat.completion.chunk", "created": 1, "model": model,
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
         "usage": {"prompt_tokens": 640, "completion_tokens": 24, "total_tokens": 664}},
    ]


def _tool_chunks(name: str, args: str, call_id: str, model: str) -> list[dict]:
    return [
        {"id": "ev", "object": "chat.completion.chunk", "created": 1, "model": model,
         "choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
             {"index": 0, "id": call_id, "type": "function",
              "function": {"name": name, "arguments": args}}]},
             "finish_reason": None}]},
        {"id": "ev", "object": "chat.completion.chunk", "created": 1, "model": model,
         "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    ]


class FakeProvider(BaseHTTPRequestHandler):
    """Serves the ActiveScript set by the runner before each scenario."""

    active: ActiveScript | None = None
    model = "eval-flash"
    log: ClassVar[list[str]] = []  # per-request debug lines, dumped per scenario

    def log_message(self, *a):  # silence
        pass

    def _reply_classify(self, step: tuple) -> None:
        _, mode, question = step
        body = {
            "mode": mode,
            "acknowledgement": "Working from the context I already hold.",
            "response": "",
            "objective": "Resolve the user's request",
            "title": "Eval turn",
            "plan": [],
            "clarifying_question": question if mode == "clarify" else "",
            "confidence": 0.9,
        }
        _sse_chunks(self, _text_chunks(json.dumps(body), self.model))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            body = {}
        if not self.path.endswith("/chat/completions"):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"{}")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        script = FakeProvider.active
        step = script.match(body) if script else ("any", "Noted.")
        messages = body.get("messages") or []
        roles = "/".join(str(m.get("role")) for m in messages[-3:])
        FakeProvider.log.append(
            f"path={self.path} last3={roles} "
            f"tool_results={sum(1 for m in messages if m.get('role') == 'tool')} "
            f"has_tools={bool(body.get('tools'))} "
            f"marker={CLASSIFY_MARKER in json.dumps(messages)} "
            f"matched={step[0]}:{str(step[1])[:40]}"
        )
        kind = step[0]
        if kind == "classify":
            self._reply_classify(step)
        elif kind == "tool":
            _, name, args, call_id = step
            _sse_chunks(self, _tool_chunks(name, args, call_id, self.model))
        elif kind == "after":
            payload = step[2]
            if isinstance(payload, tuple) and payload and payload[0] == "tool":
                _sse_chunks(self, _tool_chunks(payload[1], payload[2], payload[3], self.model))
            else:
                _sse_chunks(self, _text_chunks(str(payload), self.model))
        else:  # user / any
            _sse_chunks(self, _text_chunks(str(step[-1]), self.model))


def boot_fake() -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", FAKE_PORT), FakeProvider)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ─── Server boot (house pattern) ────────────────────────────────────────

def boot_server(home: Path, out: Path, adapter_env: str) -> subprocess.Popen:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2).read()
        raise RuntimeError(
            f"a live server already answers on port {PORT} — kill the stale harness first"
        )
    except RuntimeError:
        raise
    except Exception:  # noqa: BLE001, S110 — any probe failure means the port is free
        pass
    env = os.environ.copy()
    env.update({
        "LOCALMIND_PORT": str(PORT),
        "LOCALMIND_HOME": str(home),
        "PYTHONPATH": str(BACKEND / "src"),
    })
    if adapter_env:
        env["LOCALMIND_ADAPTER"] = adapter_env
    log = out / "server.log"
    # The handle must outlive this function: the server writes for its whole
    # lifetime (SIM115 acknowledged — closing it would kill the server's IO).
    log_fh = open(log, "wb")  # noqa: SIM115
    proc = subprocess.Popen(
        [venv_python(BACKEND), "server.py"],
        cwd=str(BACKEND), env=env,
        stdout=log_fh, stderr=subprocess.STDOUT,
        **server_popen_kwargs(),
    )
    for _ in range(45):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2).read()
            return proc
        except Exception:  # noqa: BLE001 — not-up-yet is expected during boot
            time.sleep(1)
    proc.kill()
    raise RuntimeError("server failed to start within 45s (see server.log)")


# ─── Turn execution + SSE parsing ───────────────────────────────────────

def fire(message: str, session_id: str, timeout: int = 150) -> tuple[str, float]:
    body = urllib.parse.urlencode({"message": message, "session_id": session_id}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/chat",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return raw, (time.monotonic() - t0) * 1000.0


def parse_sse(raw: str) -> tuple[str, list[dict], list[dict], dict, dict]:
    """Returns (final_text, obs_events, top_events, metrics, usage)."""
    text_parts: list[str] = []
    obs: list[dict] = []
    top: list[dict] = []
    metrics: dict = {}
    usage: dict = {}
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            payload = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        top.append(payload)
        if payload.get("type") == "token":
            text_parts.append(str(payload.get("content") or ""))
        elif payload.get("type") == "metrics":
            metrics = payload.get("metrics") or {}
        elif payload.get("type") == "done":
            usage = payload.get("provider_usage") or {}
        oe = payload.get("obs_event")
        if isinstance(oe, dict) and oe.get("type"):
            obs.append(oe)
            if oe["type"] == "turn_complete":
                text = str(oe.get("data", {}).get("text") or "")
                if text:
                    text_parts.append(text)
    return "".join(text_parts), obs, top, metrics, usage


def obs_by_type(obs: list[dict], etype: str) -> list[dict]:
    return [o.get("data") or {} for o in obs if o.get("type") == etype]


def asked_question(text: str) -> bool:
    return bool(QUESTION_RE.search((text or "").strip()))


# ─── Scoring ────────────────────────────────────────────────────────────

def score_turn(spec: TurnSpec, tr: dict, deterministic: bool) -> list[dict]:
    checks: list[dict] = []

    def add(name: str, kind: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "kind": kind, "ok": bool(ok), "detail": detail})

    # Tools ran as expected.
    done_tools = [t["tool"] for t in tr["tools"] if t.get("status") == "done"]
    failed_tools = [t["tool"] for t in tr["tools"] if t.get("status") == "failed"]
    all_tools = [t["tool"] for t in tr["tools"]]

    if spec.expect_no_tools:
        add("no tools ran", STRUCTURAL, not all_tools,
            f"ran: {sorted(set(all_tools))}" if all_tools else "")
    else:
        for tool in spec.expect_tools:
            add(f"tool {tool} ran and finished done", STRUCTURAL,
                tool in done_tools,
                "" if tool in done_tools else f"ran={sorted(set(all_tools))}")
    for tool in spec.expect_tool_failure:
        add(f"tool {tool} ran and FAILED honestly", STRUCTURAL,
            tool in failed_tools,
            "" if tool in failed_tools else f"statuses={sorted(set(all_tools))}")
    for tool, minimum in sorted(spec.expect_tool_counts.items()):
        count = done_tools.count(tool)
        add(f"tool {tool} completed >= {minimum} call(s)", STRUCTURAL,
            count >= minimum, f"count={count}")
    for tool in spec.forbid_tools:
        add(f"tool {tool} did NOT run", STRUCTURAL, tool not in all_tools,
            "" if tool not in all_tools else "ran")

    # Lane + observability expectations.
    if spec.expect_lane:
        lanes = [d.get("lane") or d.get("path") or "" for d in tr["paths"]]
        add(f"lane is {spec.expect_lane}", STRUCTURAL, spec.expect_lane in lanes,
            f"lanes={lanes}")
    for etype in spec.expect_obs:
        add(f"obs event {etype} on the wire", STRUCTURAL,
            bool(obs_by_type(tr["obs"], etype)))
    for etype in spec.forbid_obs:
        add(f"obs event {etype} absent", STRUCTURAL,
            not obs_by_type(tr["obs"], etype))

    # Question expectations.
    has_q = asked_question(tr["text"])
    if spec.expect_question is True:
        add("reply asks a question", STRUCTURAL, has_q)
    elif spec.expect_question is False:
        add("reply does NOT ask a question", STRUCTURAL, not has_q)

    # Content: exclusions gate in BOTH modes (defect signatures);
    # inclusions are required in deterministic mode, advisory on a real
    # provider (a real model cannot be pinned to exact text).
    # Case-insensitive on purpose: the assertions key on WORDS, and the
    # reply's capitalization is not part of any contract being scored.
    lowered = tr["text"].lower()
    for sub in spec.reply_excludes:
        add(f"reply excludes '{sub}'", STRUCTURAL, sub.lower() not in lowered)
    for sub in spec.reply_contains:
        add(f"reply contains '{sub}'", CONTENT, sub.lower() in lowered,
            "" if sub.lower() in lowered else "advisory on a real provider")

    return checks


def verdict_of(checks: list[dict], deterministic: bool) -> str:
    structural = [c for c in checks if c["kind"] == STRUCTURAL]
    content = [c for c in checks if c["kind"] == CONTENT]
    if any(not c["ok"] for c in structural):
        return "FAIL"
    if deterministic and any(not c["ok"] for c in content):
        return "PARTIAL"
    return "PASS"


# ─── Runner ─────────────────────────────────────────────────────────────

def find_db(home: Path) -> Path:
    dbs = [p for p in home.rglob("*.db")]
    if not dbs:
        raise RuntimeError("no sqlite db found under the scratch home")
    return dbs[0]


def run_scenario(sc: Scenario, out: Path, home: Path, scratch: str) -> dict:
    session_id = f"eval-{sc.id}"
    # Seed workspace files for this scenario's session (session workspaces
    # live under <home>/sessions/<id>/) — unused by the current scenarios
    # (file tools resolve against the user's real folders), kept for the
    # workspace-bound tools future scenarios may use.
    ws = home / "sessions" / session_id
    ws.mkdir(parents=True, exist_ok=True)
    # Seed the scenario's files (paths are scratch-home-relative, e.g.
    # "files/notes.md") so file tools read REAL bytes.
    for rel, content in sc.seed_files.items():
        target = home / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    turn_results: list[dict] = []
    for i, spec in enumerate(sc.turns, 1):
        user = spec.user.replace("{scratch}", scratch)
        raw, wall_ms = fire(user, session_id)
        (out / f"{sc.id}-turn{i}.sse.txt").write_text(raw)
        time.sleep(1.0)  # let persist paths settle (house pattern)
        text, obs, _top, metrics, usage = parse_sse(raw)
        tr = {
            "text": text,
            "obs": obs,
            "tools": obs_by_type(obs, "tool_call"),
            "paths": obs_by_type(obs, "path_selected"),
            "metrics": metrics,
            "usage": usage,
            "wall_ms": wall_ms,
        }
        checks = score_turn(spec, tr, deterministic=True)
        turn_results.append({
            "n": i,
            "user": user,
            "reply_head": text[:220],
            "checks": checks,
            "tools": [
                {"tool": t.get("tool"), "status": t.get("status"),
                 "latency_ms": t.get("latency_ms")}
                for t in tr["tools"]
            ],
            "lanes": [d.get("lane") or d.get("path") or "" for d in tr["paths"]],
            "latency_ms": wall_ms,
            "first_token_ms": metrics.get("first_token_ms", 0),
            "decode_ms": metrics.get("decode_ms", 0),
            "llm_calls": metrics.get("llm_calls", 0),
            "total_latency_ms": metrics.get("total_latency_ms", 0),
        })

    all_checks = [c for t in turn_results for c in t["checks"]]
    verdict = verdict_of(all_checks, deterministic=True)

    # Recovery scoring for failure-injecting scenarios.
    recovery = None
    if sc.injects_failure:
        last_text = turn_results[-1]["reply_head"] if turn_results else ""
        tool_failed = any(
            t["status"] == "failed"
            for t in turn_results[-1]["tools"]
        ) if turn_results else False
        recovery = bool(
            last_text
            and sc.recovery_marker in last_text
            and tool_failed
        )

    return {
        "id": sc.id,
        "category": sc.category,
        "title": sc.title,
        "verdict": verdict,
        "recovered": recovery,
        "turns": turn_results,
    }


def real_mode_adjust(result: dict, sc: Scenario) -> dict:
    """On a real provider, content inclusions are advisory: downgrade
    their failures from the verdict (structural exclusions still gate)."""
    for t in result["turns"]:
        for c in t["checks"]:
            if c["kind"] == CONTENT and not c["ok"]:
                c["detail"] = (c["detail"] + " [advisory: not scored on a real "
                               "provider]").strip()
    structural = [c for t in result["turns"] for c in t["checks"]
                  if c["kind"] == STRUCTURAL]
    result["verdict"] = "FAIL" if any(not c["ok"] for c in structural) else (
        "PARTIAL" if any(
            not c["ok"] for t in result["turns"] for c in t["checks"]
        ) else "PASS"
    )
    return result


def compute_suite_metrics(results: list[dict]) -> dict:
    total = len(results)
    verdicts = {"PASS": 0, "PARTIAL": 0, "FAIL": 0}
    for r in results:
        verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1

    # Tool success: tool-expecting turns where every expected tool finished
    # done and no unexpected failure occurred.
    tool_turns = 0
    tool_ok = 0
    for r in results:
        for t in r["turns"]:
            expecting = any(
                c["name"].startswith("tool ") and "ran and finished done" in c["name"]
                for c in t["checks"]
            ) and not any(
                "ran and FAILED honestly" in c["name"] for c in t["checks"]
            )
            if expecting:
                tool_turns += 1
                tool_checks = [c for c in t["checks"]
                               if c["name"].startswith("tool ")]
                if all(c["ok"] for c in tool_checks):
                    tool_ok += 1

    # Recovery.
    failure_scenarios = [r for r in results if r["recovered"] is not None]
    recovered = [r for r in failure_scenarios if r["recovered"]]

    # Unnecessary questions: turns whose spec said no-question and a
    # question was asked (the check's detail names it).
    unnecessary = 0
    question_gated = 0
    for r in results:
        for t in r["turns"]:
            for c in t["checks"]:
                if c["name"] == "reply does NOT ask a question":
                    question_gated += 1
                    if not c["ok"]:
                        unnecessary += 1

    # Latency.
    latencies = [t["latency_ms"] for r in results for t in r["turns"]]
    first_tokens = [t["first_token_ms"] for r in results for t in r["turns"]
                    if t["first_token_ms"]]
    decodes = [t["decode_ms"] for r in results for t in r["turns"] if t["decode_ms"]]

    def pct(values, p):
        if not values:
            return 0
        return sorted(values)[min(len(values) - 1, int(len(values) * p / 100))]

    # Factual accuracy (fixture-pinned content assertions, fake mode).
    content_checks = [c for r in results for t in r["turns"] for c in t["checks"]
                      if c["kind"] == CONTENT]
    accuracy = {
        "basis": "fixture-pinned (deterministic provider — pipeline verification, not model accuracy)",
        "assertions": len(content_checks),
        "passed": sum(1 for c in content_checks if c["ok"]),
    }

    return {
        "task_completion": {
            "basis": "scenario verdicts (structural checks authoritative)",
            "total": total,
            **verdicts,
            "rate": round((verdicts["PASS"] + 0.5 * verdicts["PARTIAL"]) / total, 3)
            if total else 0.0,
        },
        "factual_accuracy": accuracy,
        "tool_success": {
            "tool_expecting_turns": tool_turns,
            "clean": tool_ok,
            "rate": round(tool_ok / tool_turns, 3) if tool_turns else None,
        },
        "recovery_rate": {
            "failure_scenarios": len(failure_scenarios),
            "recovered": len(recovered),
            "rate": round(len(recovered) / len(failure_scenarios), 3)
            if failure_scenarios else None,
        },
        "unnecessary_questions": {
            "question_gated_turns": question_gated,
            "violations": unnecessary,
            "rate": round(unnecessary / question_gated, 3) if question_gated else 0.0,
        },
        "latency": {
            "turn_wall_ms": {
                "min": round(min(latencies)) if latencies else 0,
                "median": round(statistics.median(latencies)) if latencies else 0,
                "p90": round(pct(latencies, 90)),
                "max": round(max(latencies)) if latencies else 0,
            },
            "first_token_ms_avg": round(statistics.mean(first_tokens)) if first_tokens else None,
            "decode_ms_avg": round(statistics.mean(decodes)) if decodes else None,
        },
    }


def render_report(meta: dict, results: list[dict], suite: dict) -> str:
    lines: list[str] = []
    lines.append(f"# Eval suite report — {meta['label']} ({meta['started']})")
    lines.append("")
    lines.append(f"- Provider mode: **{meta['provider']}**"
                 + (f" (adapter `{meta['adapter']}`, model `{meta['model']}`)"
                    if meta.get("model") else ""))
    lines.append(f"- Server: port {meta['port']}, scratch home `{meta['home']}`")
    lines.append(f"- Scenarios: {len(results)}")
    lines.append("")
    lines.append("| Scenario | Category | Verdict | Recovered | Max turn ms |")
    lines.append("|---|---|---|---|---|")
    for r in results:
        maxms = max((t["latency_ms"] for t in r["turns"]), default=0)
        lines.append(
            f"| {r['id']} | {r['category']} | {r['verdict']} "
            f"| {r['recovered'] if r['recovered'] is not None else '—'} "
            f"| {round(maxms)} |"
        )
    lines.append("")
    lines.append("## Suite metrics")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(suite, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## Findings (failed checks)")
    lines.append("")
    any_fail = False
    for r in results:
        for t in r["turns"]:
            for c in t["checks"]:
                if not c["ok"] and c["kind"] == STRUCTURAL:
                    any_fail = True
                    lines.append(
                        f"- `{r['id']}` turn {t['n']}: **{c['name']}** "
                        f"{('— ' + c['detail']) if c.get('detail') else ''}"
                    )
    if not any_fail:
        lines.append("- None. All structural checks green.")
    lines.append("")
    lines.append(
        "Honest scope: deterministic mode verifies the PIPELINE (routing, "
        "tools, continuity machinery, honest failure reporting) against "
        "scripted replies — content assertions are fixture-pinned, not "
        "model accuracy. Real-provider runs score the model structurally; "
        "content inclusions are advisory there."
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--provider", choices=("fake", "real"), default="fake")
    ap.add_argument("--scenario", default="", help="comma-separated scenario ids")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--label", default="run")
    ap.add_argument("--settings", default="", help="real mode: settings file to use")
    ap.add_argument("--keep", action="store_true", help="keep the scratch home")
    args = ap.parse_args()

    if args.list:
        for sc in ALL_SCENARIOS:
            print(f"{sc.id:28s} {sc.category:24s} {sc.title}")
        return 0

    selected = ALL_SCENARIOS
    if args.scenario:
        ids = {s.strip() for s in args.scenario.split(",") if s.strip()}
        selected = tuple(sc for sc in ALL_SCENARIOS if sc.id in ids)
        unknown = ids - {sc.id for sc in selected}
        if unknown:
            print(f"unknown scenario ids: {sorted(unknown)}")
            return 2
    if not selected:
        print("no scenarios selected")
        return 2

    out = REPO / "scratch" / f"eval-suite-{args.label}"
    home = REPO / "scratch" / f"eval-suite-{args.label}-home"
    if out.exists():
        shutil.rmtree(out)
    if home.exists():
        shutil.rmtree(home)
    out.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)
    scratch = str(home)

    fake = None
    server = None
    try:
        adapter_env = ""
        model_name = ""
        adapter_name = "fakeprov"
        if args.provider == "real":
            settings_src = Path(args.settings) if args.settings else (
                Path.home() / "LocalMind" / "settings.json")
            if not settings_src.exists():
                print(
                    "real mode needs the app's settings file (default "
                    f"{Path.home() / 'LocalMind' / 'settings.json'}) — none found. "
                    "A missing credential is a missing input; refusing to fake it."
                )
                return 2
            shutil.copy(settings_src, home / "settings.json")
            # Read ONLY the adapter/model names for the report (never keys).
            try:
                cfg = json.loads((home / "settings.json").read_text(encoding="utf-8"))
                adapter_name = str(cfg.get("adapter") or "unknown")
                conns = cfg.get("connections") or []
                if conns:
                    model_name = str(conns[0].get("model") or "")
            except (json.JSONDecodeError, OSError, ValueError):
                pass
            print(f"real mode: settings copied from {settings_src} (keys never read)")
        else:
            settings = {
                "adapter": "fakeprov",
                "api_keys": {"fakeprov": "sk-local-fake-not-a-real-key"},
                "connections": [{
                    "id": "fakeprov", "name": "eval-fake", "kind": "openai-compat",
                    "base_url": f"http://127.0.0.1:{FAKE_PORT}/v1",
                    "model": "eval-flash", "enabled": True,
                }],
            }
            (home / "settings.json").write_text(json.dumps(settings, indent=2))
            adapter_env = "fakeprov"
            fake = boot_fake()
            print(f"scripted provider on {FAKE_PORT}")

        server = boot_server(home, out, adapter_env)
        print(f"server up on {PORT}")

        results: list[dict] = []
        for sc in selected:
            print(f"  running {sc.id} …")
            if fake is not None:
                FakeProvider.active = ActiveScript(sc.script, scratch)
                FakeProvider.log = []
            result = run_scenario(sc, out, home, scratch)
            if fake is not None:
                (out / f"{sc.id}-provider-debug.log").write_text(
                    "\n".join(FakeProvider.log) + "\n")
            if args.provider == "real":
                result = real_mode_adjust(result, sc)
            results.append(result)
            print(f"    -> {result['verdict']}"
                  + (f" (recovered={result['recovered']})"
                     if result["recovered"] is not None else ""))

        suite = compute_suite_metrics(results)
        if args.provider == "real":
            suite["factual_accuracy"]["basis"] = (
                "advisory on a real provider — content inclusions recorded, "
                "not machine-scored (no judge wired)"
            )
        meta = {
            "label": args.label,
            "provider": args.provider,
            "adapter": adapter_name,
            "model": model_name,
            "port": PORT,
            "home": str(home),
            "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        (out / f"results-{args.label}.json").write_text(
            json.dumps({"meta": meta, "suite": suite, "scenarios": results},
                       indent=2))
        report = render_report(meta, results, suite)
        (out / f"report-{args.label}.md").write_text(report)

        print()
        print(f"task completion : {suite['task_completion']['PASS']} PASS / "
              f"{suite['task_completion']['PARTIAL']} PARTIAL / "
              f"{suite['task_completion']['FAIL']} FAIL "
              f"(rate {suite['task_completion']['rate']})")
        ts = suite["tool_success"]
        print(f"tool success    : {ts['clean']}/{ts['tool_expecting_turns']} "
              f"({ts['rate']})")
        rr = suite["recovery_rate"]
        if rr["failure_scenarios"]:
            print(f"recovery        : {rr['recovered']}/{rr['failure_scenarios']} "
                  f"({rr['rate']})")
        uq = suite["unnecessary_questions"]
        print(f"unnecessary ques: {uq['violations']} violations across "
              f"{uq['question_gated_turns']} gated turns")
        lat = suite["latency"]["turn_wall_ms"]
        print(f"latency (wall)  : median {lat['median']}ms, p90 {lat['p90']}ms, "
              f"max {lat['max']}ms")
        print()
        print(f"artifacts: {out}")
        failed = suite["task_completion"]["FAIL"]
        return 1 if failed else 0
    finally:
        if server:
            kill_process_tree(server.pid)
        if fake:
            fake.shutdown()
        if not args.keep and home.exists():
            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
