"""
Memory API routes — F4

GET    /api/memory              — list all stored facts with metadata
POST   /api/memory              — manually store a new fact
PATCH  /api/memory/{fact_id}   — correct an existing fact's content
DELETE /api/memory/{fact_id}   — delete a specific fact by ID
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from storage.vector import VectorStore

router = APIRouter()
logger = logging.getLogger(__name__)

_store = VectorStore()


# ── GET /api/memory ───────────────────────────────────────────────────────


@router.get("/memory")
async def list_memory():
    """Return all stored facts in frontend-compatible format."""
    facts = await _store.list_all_with_metadata()

    # Convert to frontend MemoryFact format
    memory_facts = []
    for fact in facts:
        # FIX: VectorStore.list_all_with_metadata() returns {"id", "fact", ...}
        # (the field is named "fact", not "text"). The previous code used
        # fact.get("text", "") which always returned empty string.
        # Now we try "fact" first, then "content" as fallback.
        content = fact.get("fact") or fact.get("content") or fact.get("text") or ""

        # FIX: Relevance score guard — prevent NaN from reaching the frontend.
        # When there are no facts in the store, or the score is missing/None,
        # default to 0.8 (arbitrary "moderate relevance" default) so the
        # MemoryTab doesn't show NaN%.
        raw_score = fact.get("score", None)
        if raw_score is not None:
            try:
                relevance = float(raw_score)
            except (ValueError, TypeError):
                relevance = 0.8
        else:
            relevance = 0.8  # default when no score available

        # FIX: Timestamp guard — ensure valid numeric timestamp for formatDate().
        # The metadata written by _persist carries the fact's "timestamp" field
        # (the vector_facts.created_at COLUMN is a DB-side row timestamp, not in
        # the metadata dict — reading "created_at" here always yielded 0).
        raw_ts = fact.get("timestamp", 0) or fact.get("created_at", 0)
        try:
            timestamp = float(raw_ts) if raw_ts else 0
        except (ValueError, TypeError):
            timestamp = 0

        memory_facts.append(
            {
                "id": fact.get("id", ""),
                "content": content,
                "source": fact.get("source", "unknown"),
                "relevance": relevance,
                "timestamp": timestamp,
            }
        )

    return {"facts": memory_facts}


# ── PATCH /api/memory/{fact_id} ─────────────────────────────────────────────


class UpdateMemoryRequest(BaseModel):
    content: str


class UpdateMemoryResponse(BaseModel):
    updated: bool
    fact_id: str
    content: str


@router.patch("/memory/{fact_id}", response_model=UpdateMemoryResponse)
async def update_memory(fact_id: str, req: UpdateMemoryRequest):
    """Correct an existing fact's content (B-2026-08-23-14 follow-up).

    Re-embeds the corrected text and preserves the fact's original metadata.
    The fact id is derived from the content hash, so it changes — the response
    carries the NEW id and the UI must refresh its list.
    """
    new_id = await _store.update_content(fact_id, req.content)
    if not new_id:
        raise HTTPException(status_code=404, detail=f"Fact '{fact_id}' not found or could not be updated.")
    return UpdateMemoryResponse(updated=True, fact_id=new_id, content=req.content)


# ── DELETE /api/memory/{fact_id} ──────────────────────────────────────────


class DeleteResponse(BaseModel):
    deleted: bool
    fact_id: str


@router.delete("/memory/{fact_id}", response_model=DeleteResponse)
async def delete_memory(fact_id: str):
    """Delete a specific fact by its ID."""
    ok = await _store.forget_by_id(fact_id)
    if not ok:
        raise HTTPException(
            status_code=404, detail=f"Fact '{fact_id}' not found or could not be deleted."
        )
    return DeleteResponse(deleted=True, fact_id=fact_id)


# ── POST /api/memory ──────────────────────────────────────────────────────


class StoreMemoryRequest(BaseModel):
    fact: str
    session_id: str = "manual"
    memory_type: str = "semantic"
    importance: float = 0.5
    source: str = "manual"


class StoreMemoryResponse(BaseModel):
    stored: bool
    fact: str


@router.post("/memory", response_model=StoreMemoryResponse)
async def store_memory(req: StoreMemoryRequest):
    """Manually store a fact in the vector memory store."""
    ok = await _store.store(
        fact=req.fact,
        session_id=req.session_id,
        source=req.source,
        extra_metadata={
            "memory_type": req.memory_type,
            "importance": str(req.importance),
            "access_count": "0",
        },
    )
    if not ok:
        raise HTTPException(status_code=503, detail="Memory store unavailable.")
    return StoreMemoryResponse(stored=True, fact=req.fact)
