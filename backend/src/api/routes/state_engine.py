"""The State Explorer: a page served by the backend, and a live SSE stream of a state-engine run.

  GET  /state-explorer          the self-contained page (no build step, no npm — it works on any machine
                                that can run the backend, Windows included)
  GET  /api/state-engine/info   which provider/model the engine will use and which tools it may probe
  POST /api/state-engine/run    stream one run as SSE: a `meta` event, then every EngineEvent

The engine is experimental and READ-ONLY (ADR-71): it only ever probes with look-and-read tools. The route
uses the same provider/model the classic agent uses; nothing new is configured.
"""
from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

page_router = APIRouter()
router = APIRouter()

_PAGE = Path(__file__).resolve().parent.parent / "static" / "state-explorer" / "index.html"

# The search bounds an engine run will accept. Kept here (not inline in the model) so /info can publish
# exactly what the UI is allowed to offer — the explorer lets the user widen or narrow the search.
_MAX_DEPTH = 10
_MAX_BRANCHES = 5
_MAX_MODEL_CALLS = 40
_MAX_BACKTRACKS = 5
_DEFAULT_BUDGET = {"max_depth": 6, "max_branches": 3, "max_model_calls": 16, "max_backtracks": 2}


class RunRequest(BaseModel):
    goal: str = Field(min_length=3, max_length=2000)
    max_depth: int = Field(default=6, ge=1, le=_MAX_DEPTH)
    max_branches: int = Field(default=3, ge=1, le=_MAX_BRANCHES)
    max_model_calls: int = Field(default=16, ge=2, le=_MAX_MODEL_CALLS)
    max_backtracks: int = Field(default=2, ge=0, le=_MAX_BACKTRACKS)


def _provider_and_model() -> tuple[str, str]:
    from core.config import settings
    from core.parent_kernel import active_parent_model

    return settings.localmind_adapter, active_parent_model() or ""


def _make_engine(budget):
    """Build the engine on the active provider, through LocalMind's adapter. A seam so tests can
    substitute a scripted engine."""
    from adapters import get_adapter
    from state_agent.adapters.localmind import build_engine

    provider, model = _provider_and_model()
    return build_engine(get_adapter(provider, model), budget)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@page_router.get("/state-explorer", response_class=HTMLResponse)
async def state_explorer_page():
    try:
        return HTMLResponse(_PAGE.read_text(encoding="utf-8"))
    except OSError:
        raise HTTPException(
            status_code=404, detail="State Explorer page is not built (run docs/prototypes/state-explorer/build.py)"
        )


@router.get("/state-engine/info")
async def state_engine_info():
    from state_agent.adapters.localmind import LOCALMIND_ACTIONS

    provider, model = _provider_and_model()
    return {
        "experimental": True,
        "read_only": True,
        "provider": provider,
        "model": model,
        "tools": [{"name": t.name, "description": t.description} for t in LOCALMIND_ACTIONS.values()],
        # What a run costs and what it may be told to spend: the UI's search controls come from here.
        "budget": dict(_DEFAULT_BUDGET),
        "budget_limits": {
            "max_depth": [1, _MAX_DEPTH],
            "max_branches": [1, _MAX_BRANCHES],
            "max_model_calls": [2, _MAX_MODEL_CALLS],
            "max_backtracks": [0, _MAX_BACKTRACKS],
        },
    }


@router.post("/state-engine/run")
async def state_engine_run(req: RunRequest, request: Request):
    from state_agent import EngineBudget, Goal

    budget = EngineBudget(
        max_depth=req.max_depth, max_branches=req.max_branches,
        max_model_calls=req.max_model_calls, max_backtracks=req.max_backtracks,
    )
    provider, model = _provider_and_model()

    async def stream():
        yield _sse({"kind": "meta", "provider": provider, "model": model, "budget": dataclasses.asdict(budget)})
        try:
            engine = _make_engine(budget)
            async for ev in engine.run(Goal(req.goal.strip())):
                if await request.is_disconnected():  # the user pressed Stop / closed the tab
                    return
                yield _sse(ev.to_dict())
        except Exception as exc:  # noqa: BLE001 — a failed run is reported, never a dropped stream
            logger.warning("[state-engine] run failed: %s", exc)
            yield _sse({
                "seq": 0, "t_ms": 0, "kind": "stopped",
                "reason": f"error: {type(exc).__name__}: {exc}"[:300], "settled": False,
                "facts": [], "trail": [], "model_calls": 0,
            })

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
