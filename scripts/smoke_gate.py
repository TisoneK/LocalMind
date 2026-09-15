#!/usr/bin/env python
"""ADR-18 P0 acceptance-gate live smoke.

Drives a real coding task through the RUNNING server's /api/chat SSE
stream and reports on the acceptance-gate artifacts:

  1. Did the dispatcher produce success_criteria? (plan JSON contains them)
  2. Did the loop reach a verified done with a gate summary ("✓ n/n")?
  3. Did a gate-failure replan fire? (honest unmet report)

Usage: backend/.venv/bin/python scripts/smoke_gate.py
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request

BASE = "http://localhost:8000/api/chat"


def stream_chat(message: str, session_id: str = "smoke-gate") -> list[dict]:
    body = urllib.parse.urlencode(
        {"message": message, "session_id": session_id}
    ).encode()
    req = urllib.request.Request(
        BASE,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    events: list[dict] = []
    with urllib.request.urlopen(req, timeout=300) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data: "):
                continue
            try:
                payload = json.loads(line[len("data: "):])
            except json.JSONDecodeError:
                continue
            events.append(payload)
    return events


def main() -> int:
    message = (
        "Create a small python project in /tmp/lm-gate-smoke: a hello.py that "
        "prints 'hello gate', plus a test file, and RUN pytest to prove it "
        "passes. Report what was actually verified."
    )
    print(f"posting: {message!r}")
    try:
        events = stream_chat(message)
    except Exception as exc:  # noqa: BLE001
        print(f"SMOKE FAIL — stream error: {exc}")
        return 2

    texts = [e.get("text", "") or "" for e in events if e.get("type") != "error"]
    full = "\n".join(texts)

    # Artifacts we look for
    plan_json = None
    for e in events:
        if isinstance(e.get("plan"), (dict, list, str)) or "execution_plan" in str(e.get("plan", "")):
            plan_json = e.get("plan")
            break
        # dispatcher reformulation sometimes carries the plan in 'plan' key
    # fallback: scan serialized events for success_criteria mention
    serialized = json.dumps(events)[:200000]
    has_criteria = '"success_criteria"' in serialized
    has_task_type = '"task_type"' in serialized  # ADR-19 task-aware context
    gate_summary = "✓" in full or "criteria met" in full
    honest_unmet = "not met" in full or "unmet" in full
    done_seen = any(e.get("type") == "done" for e in events)

    print("\n===== SMOKE RESULTS =====")
    print(f"done event seen:            {done_seen}")
    print(f"dispatcher emitted criteria:{has_criteria}")
    print(f"dispatcher emitted task_type:{has_task_type}")
    print(f"gate summary (✓ n/n) seen:  {gate_summary}")
    print(f"honest-unmet wording seen:  {honest_unmet}")
    print(f"plan object captured:       {plan_json is not None}")
    print("\n----- last 1200 chars of stream text -----")
    print(full[-1200:])
    print("\n----- tail event types -----")
    print([e.get("type") for e in events[-12:]])

    ok = done_seen and (has_criteria or gate_summary)
    print(f"\nSMOKE {'PASS' if ok else 'INCONCLUSIVE/FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
