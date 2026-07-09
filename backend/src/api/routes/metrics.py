"""Metrics endpoint - performance metrics for bottom bar."""
from __future__ import annotations

import time

from fastapi import APIRouter
from pydantic import BaseModel

from api.routes.health import _SERVER_START

router = APIRouter()


class MetricsResponse(BaseModel):
    tokensPerSecond: float
    latency: float
    totalTokens: int
    promptTokens: int = 0
    completionTokens: int = 0
    uptime: float


def _get_engine():
    """Get the engine singleton from the chat route module."""
    from api.routes.chat import _engine
    return _engine


@router.get("/metrics")
async def get_metrics():
    """Get performance metrics from the engine's MetricsStore."""
    engine = _get_engine()
    store = engine._metrics
    streaming = store.get_streaming_metrics()

    # Aggregate latency across all intents for a representative value
    all_metrics = store.get_all_metrics()
    agg_latency = 0.0
    agg_count = 0
    for key, data in all_metrics.items():
        if data.get("total_requests", 0) > 0:
            agg_latency += data.get("p50_latency_ms", 0) * data["total_requests"]
            agg_count += data["total_requests"]
    avg_latency = (agg_latency / agg_count) if agg_count > 0 else 0.0

    # Use streaming metrics (last request) when available, otherwise
    # fall back to the aggregated average latency across all intents.
    latency = streaming.get("latency", 0)
    if latency == 0 and avg_latency > 0:
        latency = avg_latency

    return {
        "tokensPerSecond": streaming.get("tokensPerSecond", 0),
        "latency": latency,
        "totalTokens": streaming.get("totalTokens", 0),
        "promptTokens": streaming.get("promptTokens", 0),
        "completionTokens": streaming.get("completionTokens", 0),
        "uptime": round(time.time() - _SERVER_START, 2),
    }
