"""Tests for durable autonomous objective state."""

from __future__ import annotations

import time

from storage.objectives import ObjectiveStore


def test_objective_lifecycle_and_claim(tmp_db):
    store = ObjectiveStore(tmp_db)
    created = store.create("objective-1", "session-1", "Research FastAPI lifespan")

    assert created.status == "queued"
    claimed = store.claim_next(lease_seconds=60)
    assert claimed is not None
    assert claimed.id == created.id
    assert claimed.status == "running"
    assert claimed.attempts == 1

    paused = store.pause(created.id)
    assert paused is not None
    assert paused.status == "paused"
    assert store.claim_next() is None

    resumed = store.resume(created.id, "Continue with official docs")
    assert resumed is not None
    assert resumed.status == "queued"
    assert resumed.resume_message == "Continue with official docs"

    canceled = store.request_cancel(created.id)
    assert canceled is not None
    assert canceled.status == "canceled"
    assert store.claim_next() is None


def test_expired_running_objective_is_recoverable(tmp_db):
    store = ObjectiveStore(tmp_db)
    store.create("objective-2", "session-2", "Inspect the project")
    claimed = store.claim_next(lease_seconds=-1)
    assert claimed is not None

    recovered = store.claim_next(lease_seconds=60)
    assert recovered is not None
    assert recovered.id == "objective-2"
    assert recovered.attempts == 2


def test_stale_worker_cannot_finalize_canceled_objective(tmp_db):
    """A cancellation wins over a stale worker completion attempt."""
    store = ObjectiveStore(tmp_db)
    store.create("objective-race", "session-race", "Long-running research")
    claimed = store.claim_next(lease_seconds=60, lease_owner="worker-a")
    assert claimed is not None

    canceled = store.request_cancel(claimed.id)
    assert canceled is not None
    assert canceled.status == "canceled"

    stale = store.update_owned(
        claimed.id,
        "worker-a",
        status="completed",
        result="stale completion",
        completed_at=time.time(),
        lease_until=None,
    )
    assert stale is not None
    assert stale.status == "canceled"
    assert stale.result is None


def test_objective_result_and_approval_state(tmp_db):
    store = ObjectiveStore(tmp_db)
    store.create("objective-3", "session-3", "Prepare a change")

    blocked = store.update(
        "objective-3",
        status="blocked",
        approval='{"path":"example.txt"}',
        last_event="approval_required",
    )
    assert blocked is not None
    assert blocked.status == "blocked"
    assert blocked.approval == '{"path":"example.txt"}'

    completed = store.update(
        "objective-3",
        status="completed",
        result="Finished",
        completed_at=time.time(),
        lease_until=None,
    )
    assert completed is not None
    assert completed.result == "Finished"
    assert completed.completed_at is not None
