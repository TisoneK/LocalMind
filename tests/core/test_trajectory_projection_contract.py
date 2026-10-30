"""Backend side of the cross-language trajectory-projection contract.

The trajectory (agent run tree + phase strip + injected-item ledger) is
projected from the recorded obs stream on BOTH sides: the backend at persist
time (agent_workspace), the frontend live (turnProjection.ts). This test pins
the backend projection to the shared expected artifact
(tests/fixtures/trajectory_projection.expected.json); the frontend pins to the
same file in turnProjection.contract.test.ts. Change one projection and one of
the two goes red until they agree again — so the two reconstructions can never
silently drift apart (which is exactly the divergence this whole change
removed: random phase ids, lost list payloads, a hand-mirrored live path).

Regenerate expected with:  python scripts/gen_trajectory_expected.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.obs import ObsCollector
from core.agent_workspace import (
    build_workspace_artifacts,
    collect_injected_items,
)

_REPO = Path(__file__).resolve().parents[2]
_FIXTURE = _REPO / "tests" / "fixtures" / "trajectory_projection.json"
_EXPECTED = _REPO / "tests" / "fixtures" / "trajectory_projection.expected.json"

_VOLATILE = {"timestamp", "startedAt", "completedAt"}


def _norm(value):
    """Drop volatile wall-clock keys + absent-ish scalars (None/"") — identical
    to scripts/gen_trajectory_expected.py and the frontend contract test."""
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


def _collector_for(events):
    c = ObsCollector()
    for evt in events:
        c.emit(evt["type"], **(evt.get("data") or {}))
    return c


def _project(case):
    collector = _collector_for(case["events"])
    agent_runs, agent_phases = build_workspace_artifacts(
        collector, task=case.get("task", ""), root_error=case.get("rootError")
    )
    injected = collect_injected_items(collector)
    return _norm(
        {
            "agentRuns": agent_runs or [],
            "agentPhases": agent_phases or [],
            "injectedItems": injected if injected else None,
        }
    )


_FIXTURE_CASES = json.loads(_FIXTURE.read_text())["cases"]
_EXPECTED_DATA = json.loads(_EXPECTED.read_text())


@pytest.mark.parametrize("case", _FIXTURE_CASES, ids=[c["name"] for c in _FIXTURE_CASES])
def test_backend_projection_matches_expected(case):
    assert _project(case) == _norm(_EXPECTED_DATA[case["name"]])
