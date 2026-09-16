"""
Per-request pipeline stage timing (extracted from the agent loop).

Shared lifecycle service — ``_StageClock`` records REAL wall-clock latency
per runtime stage and emits ``stage_timing`` obs events so the Observe panel
renders truthful statuses (done / skipped) with real timings.
"""

from __future__ import annotations

import time

from core.obs import ObsCollector


class _StageClock:
    """Per-request pipeline stage timing for the Observe panel.

    The frontend's "Agent Pipeline" section previously derived stage status
    from a heuristic (intent present / tool call seen / latency > 0), which
    left "Tool Select" orange forever on completed no-tool turns and showed
    "Execute" as done with no tools. This clock records REAL wall-clock
    latency per stage and emits ``stage_timing`` obs events so the panel can
    render truthful statuses (done / skipped) with real timings.

    Stages: intent_classify, context_build, agent_initialize, tool_select,
    generate, execute. Stages that never ran are emitted as "skipped" so the
    UI never shows a stuck "running" state for work that didn't happen.
    """

    def __init__(self, obs: ObsCollector):
        self._obs = obs
        self._marks: dict[str, float] = {}
        self.timings: dict[str, dict] = {}

    def start(self, stage: str) -> None:
        self._marks[stage] = time.monotonic()

    def end(self, stage: str, status: str = "done") -> None:
        t0 = self._marks.pop(stage, None)
        if t0 is None:
            return
        latency_ms = round((time.monotonic() - t0) * 1000)
        self._timing(stage, latency_ms, status)

    def mark(self, stage: str, latency_ms: int, status: str = "done") -> None:
        """Record a stage that completed outside start()/end() (e.g. skipped
        or folded into another stage) with an explicit latency."""
        self._timing(stage, latency_ms, status)

    def skip(self, stage: str) -> None:
        self._timing(stage, 0, "skipped")

    def snapshot(self) -> dict:
        return dict(self.timings)

    def _timing(self, stage: str, latency_ms: int, status: str) -> None:
        self.timings[stage] = {"latency_ms": latency_ms, "status": status}
        self._obs.emit("stage_timing", stage=stage, latency_ms=latency_ms, status=status)
