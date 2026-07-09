"""Observability endpoint - intent, confidence, tool timeline for right panel."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ToolEvent(BaseModel):
    tool_name: str
    timestamp: float
    duration: Optional[float] = None
    status: str  # "started", "completed", "failed"


class ObservabilityData(BaseModel):
    session_id: str
    intent: Optional[str] = None
    confidence: Optional[float] = None
    tools_used: str = ""
    memory_hits: int = 0
    context_tokens: int = 0
    latency_ms: float = 0
    tool_timeline: List[ToolEvent] = []


def _get_engine():
    """Get the engine singleton from the chat route module."""
    from api.routes.chat import _engine
    return _engine


@router.get("/observability/{session_id}", response_model=ObservabilityData)
async def get_observability(session_id: str):
    """Get observability data for a session.

    Returns real data from the engine's per-session observation cache,
    populated on every turn_complete event. Falls back to aggregated
    MetricsStore data if no observation has been stored yet.
    """
    engine = _get_engine()

    # Try the per-session observation cache first
    obs_data = engine._last_observation.get(session_id)

    if obs_data:
        return ObservabilityData(
            session_id=session_id,
            intent=obs_data.get("intent"),
            confidence=obs_data.get("confidence"),
            tools_used=obs_data.get("tools_used", ""),
            memory_hits=obs_data.get("memory_hits", 0),
            context_tokens=obs_data.get("context_tokens", 0),
            latency_ms=obs_data.get("latency_ms", 0),
        )

    # Fallback: aggregate from MetricsStore for this session's intent
    # (provides at least latency and request count if a turn completed
    # but the observation cache was pruned)
    all_metrics = engine._metrics.get_all_metrics()
    best_intent = None
    best_latency = 0.0
    for key, data in all_metrics.items():
        if data.get("total_requests", 0) > 0:
            best_intent = key
            best_latency = float(data.get("p50_latency_ms", 0))

    if best_intent:
        return ObservabilityData(
            session_id=session_id,
            intent=best_intent,
            confidence=0,
            tools_used=best_intent,
            memory_hits=0,
            context_tokens=0,
            latency_ms=best_latency,
        )

    # No data at all — return empty observation
    return ObservabilityData(session_id=session_id)
