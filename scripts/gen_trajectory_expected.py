#!/usr/bin/env python3
"""Generate the cross-language trajectory-projection contract's expected output.

Reads the shared event fixtures (tests/fixtures/trajectory_projection.json),
feeds each case through the REAL backend projection (the source of truth that
persists the record and the UI renders on reload) and writes the normalized
result to tests/fixtures/trajectory_projection.expected.json.

Both sides of the contract pin to that expected file:
  * backend  — tests/core/test_trajectory_projection_contract.py
  * frontend — frontend/src/lib/localmind/turnProjection.contract.test.ts
so the frontend's live projection (turnProjection.ts) and the backend's
persist-time projection (agent_workspace.py + agent_runtime._collect_tool_calls)
can never silently drift apart again.

Run from the repo root:  python scripts/gen_trajectory_expected.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend" / "src"))

from core.agent_workspace import (
    build_workspace_artifacts,
    collect_injected_items,
)
from core.obs import ObsCollector

FIXTURE = REPO / "tests" / "fixtures" / "trajectory_projection.json"
EXPECTED = REPO / "tests" / "fixtures" / "trajectory_projection.expected.json"

# Wall-clock fields the projection stamps with the current time — not part of
# the structural contract (the frontend uses Date.now(), the backend time.time()).
_VOLATILE = {"timestamp", "startedAt", "completedAt"}


def _norm(value):
    """Normalize for cross-language comparison: drop volatile wall-clock keys and
    absent-ish scalars (None / ""). This makes a Python ``None`` equal to an
    omitted TS key and ``""`` equal to ``undefined``, so the contract checks the
    real structure (ids, labels, statuses, nesting, recovered lists) without
    tripping over representational differences between the two ports. Lists are
    kept as-is — both ports emit the same empty-vs-present lists."""
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


def _collector_for(events: list[dict]) -> ObsCollector:
    c = ObsCollector()
    for evt in events:
        c.emit(evt["type"], **(evt.get("data") or {}))
    return c


def project_case(case: dict) -> dict:
    events = case["events"]
    task = case.get("task", "")
    root_error = case.get("rootError")
    collector = _collector_for(events)
    # Use the REAL persist-time projection so the expected artifact is exactly
    # what the backend writes (never a reimplementation that can drift).
    agent_runs, agent_phases = build_workspace_artifacts(
        collector, task=task, root_error=root_error
    )
    injected = collect_injected_items(collector)
    return {
        "agentRuns": agent_runs or [],
        "agentPhases": agent_phases or [],
        "injectedItems": injected if injected else None,
    }


def main() -> None:
    fixture = json.loads(FIXTURE.read_text())
    out = {}
    for case in fixture["cases"]:
        out[case["name"]] = _norm(project_case(case))
    EXPECTED.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {EXPECTED.relative_to(REPO)} ({len(out)} cases)")


if __name__ == "__main__":
    main()
