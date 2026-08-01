"""User-controlled autonomous objective endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from storage.objectives import Objective

router = APIRouter()


class ObjectiveCreateRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=20_000)
    priority: int = Field(default=0, ge=-100, le=100)


class ObjectiveResumeRequest(BaseModel):
    message: str | None = Field(default=None, max_length=20_000)


def _serialize(objective: Objective) -> dict:
    return {
        "id": objective.id,
        "session_id": objective.session_id,
        "prompt": objective.prompt,
        "status": objective.status,
        "priority": objective.priority,
        "result": objective.result,
        "error": objective.error,
        "approval": objective.approval,
        "resume_message": objective.resume_message,
        "last_event": objective.last_event,
        "attempts": objective.attempts,
        "cancel_requested": objective.cancel_requested,
        "created_at": objective.created_at,
        "updated_at": objective.updated_at,
        "started_at": objective.started_at,
        "completed_at": objective.completed_at,
    }


def _runtime(request: Request):
    runtime = getattr(request.app.state, "objective_runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="Objective runtime is not ready")
    return runtime


@router.get("/objectives")
async def list_objectives(request: Request, session_id: str | None = Query(default=None)):
    return {"objectives": [_serialize(item) for item in _runtime(request).store.list(session_id)]}


@router.post("/objectives", status_code=202)
async def create_objective(request: Request, body: ObjectiveCreateRequest):
    runtime = _runtime(request)
    objective = runtime.store.create(
        objective_id=str(uuid.uuid4()),
        session_id=body.session_id,
        prompt=body.prompt.strip(),
        priority=body.priority,
    )
    return _serialize(objective)


@router.get("/objectives/{objective_id}")
async def get_objective(objective_id: str, request: Request):
    objective = _runtime(request).store.get(objective_id)
    if objective is None:
        raise HTTPException(status_code=404, detail="Objective not found")
    return _serialize(objective)


@router.post("/objectives/{objective_id}/pause")
async def pause_objective(objective_id: str, request: Request):
    runtime = _runtime(request)
    objective = runtime.store.pause(objective_id)
    if objective is None:
        raise HTTPException(status_code=404, detail="Objective not found")
    runtime.interrupt(objective_id)
    return _serialize(objective)


@router.post("/objectives/{objective_id}/resume")
async def resume_objective(objective_id: str, request: Request, body: ObjectiveResumeRequest | None = None):
    runtime = _runtime(request)
    current = runtime.store.get(objective_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Objective not found")
    if current.status not in {"paused", "blocked", "failed"}:
        raise HTTPException(status_code=409, detail=f"Objective is {current.status}, not resumable")
    objective = runtime.store.resume(objective_id, body.message if body else None)
    return _serialize(objective)


@router.post("/objectives/{objective_id}/cancel")
async def cancel_objective(objective_id: str, request: Request):
    runtime = _runtime(request)
    objective = runtime.store.request_cancel(objective_id)
    if objective is None:
        raise HTTPException(status_code=404, detail="Objective not found")
    runtime.interrupt(objective_id)
    return _serialize(objective)
