"""Observability endpoint - intent, confidence, tool timeline for right panel.

B-2026-08-09-5: the per-session observation cache is the ONLY source of
intent/latency data. The old session-agnostic MetricsStore aggregate fallback
was removed because it leaked another session's data.
"""

from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()


class ToolEvent(BaseModel):
    tool_name: str
    timestamp: float
    duration: Optional[float] = None
    status: str  # "started", "completed", "failed"


class ObservationEventSummary(BaseModel):
    type: str
    data: dict[str, Any] = Field(default_factory=dict)


class ObservationWorkspaceSummary(BaseModel):
    git_available: bool = False
    git_branch: str = ""
    git_head: str = ""
    git_status: str = ""
    git_diff_stat: str = ""
    last_build_result: Optional[dict[str, Any]] = None
    open_files: list[str] = Field(default_factory=list)


class ObservationSummary(BaseModel):
    timestamp: float
    workspace: ObservationWorkspaceSummary
    recent_events: list[ObservationEventSummary] = Field(default_factory=list)


class ObservabilityData(BaseModel):
    session_id: str
    intent: Optional[str] = None
    confidence: Optional[float] = None
    tools_used: str = ""
    memory_hits: int = 0
    context_tokens: int = 0
    latency_ms: float = 0
    tool_timeline: List[ToolEvent] = Field(default_factory=list)
    observation: Optional[ObservationSummary] = None
    # ADR-12 (B-2026-08-09-2): real per-stage timings from the engine's
    # _StageClock, folded into the stored observation on turn_complete.
    # Shape: {stage: {"latency_ms": int, "status": "done"|"skipped"|...}}
    stage_timings: Optional[dict] = None
    # B-2026-08-09-16 (ADR-15 §4): per-tool latency summary folded from
    # the agent loop's tool_call obs events. Shape:
    # {tool_name: {"calls", "total_ms", "avg_ms", "max_ms", "last_status"}}.
    # Answers the tool-vs-subagent question: is a tool's OWN execution
    # slow, or is the model round-trip around it the real cost?
    tool_timings: Optional[dict] = None
    # Session 123: anomalies detected on the last completed turn (stall /
    # token leak). Shape: [{kind, severity, title, detail, metrics}]. The
    # Observe panel renders these as alert cards instead of silently
    # displaying the bad numbers.
    anomalies: Optional[list] = None


def _get_engine():
    """Get the engine singleton from the chat route module."""
    from api.routes.chat import _engine

    return _engine


@router.get(
    "/observability/{session_id}",
    response_model=ObservabilityData,
)
async def get_observability(session_id: str):
    """Get observability data for a session.

    Returns real data from the engine's per-session observation cache,
    populated on every turn_complete event (including trivial/conversational
    short-circuits since B-2026-08-09-5). Sessions without a stored
    observation return the empty response — no cross-session aggregate.
    """
    engine = _get_engine()

    # Try the per-session observation cache first
    obs_data = engine._last_observation.get(session_id)

    # Session 267: the in-memory cache dies on backend restart (capped at 200
    # sessions and process-scoped). Fall back to the persisted observation
    # (one row per session, written at turn end) so the Observe panel survives
    # a backend restart. The snapshot dict is stored as the already-serialized
    # public summary, so re-wrap it in the pydantic model directly.
    if obs_data is None:
        try:
            persisted = engine._store.get_observation(session_id)
        except Exception:
            persisted = None
        if persisted:
            obs_data = persisted.get("data")
            snapshot = persisted.get("snapshot")
            if obs_data:
                return ObservabilityData(
                    session_id=session_id,
                    intent=obs_data.get("intent"),
                    confidence=obs_data.get("confidence"),
                    tools_used=obs_data.get("tools_used", ""),
                    memory_hits=obs_data.get("memory_hits", 0),
                    context_tokens=obs_data.get("context_tokens", 0),
                    latency_ms=obs_data.get("latency_ms", 0),
                    observation=(
                        ObservationSummary.model_validate(snapshot)
                        if snapshot is not None
                        else None
                    ),
                    stage_timings=obs_data.get("stage_timings"),
                    tool_timings=obs_data.get("tool_timings"),
                    anomalies=obs_data.get("anomalies"),
                )

    if obs_data:
        snapshot = getattr(engine, "_last_observation_snapshots", {}).get(session_id)
        return ObservabilityData(
            session_id=session_id,
            intent=obs_data.get("intent"),
            confidence=obs_data.get("confidence"),
            tools_used=obs_data.get("tools_used", ""),
            memory_hits=obs_data.get("memory_hits", 0),
            context_tokens=obs_data.get("context_tokens", 0),
            latency_ms=obs_data.get("latency_ms", 0),
            observation=(
                ObservationSummary.model_validate(snapshot.to_public_summary())
                if snapshot is not None
                else None
            ),
            stage_timings=obs_data.get("stage_timings"),
            tool_timings=obs_data.get("tool_timings"),
            anomalies=obs_data.get("anomalies"),
        )

    # B-2026-08-09-5: no per-session observation → return the honest empty
    # response. The previous fallback aggregated MetricsStore by INTENT and
    # returned the first intent with any requests — which could show ANOTHER
    # session's intent/latency in this session's Observe panel. MetricsStore is
    # intent-keyed (no session scope), so a truthful per-session fallback is
    # impossible. With every turn (incl. trivial "Hi") now storing an
    # observation, this branch only fires for pruned sessions (>200).
    return ObservabilityData(session_id=session_id)
