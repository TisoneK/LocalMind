"""Regression: fire-and-forget title tasks must be retained (B-2026-08-24-4).

Agent-mode turns skip the classifier, so they never get a classify-derived
title and rely entirely on the async `refine_title_async` fallback. That
fallback was spawned with a bare `asyncio.create_task(...)` whose return
value was discarded — asyncio only holds a weak reference, so the task could
be garbage-collected before it ran, leaving agent-turn sessions stuck on
"New Chat". `_spawn_background` keeps a strong reference until the task
finishes, then drops it. These tests pin that contract.
"""

from __future__ import annotations

import asyncio
import gc

import pytest

from api.routes.chat import _BACKGROUND_TASKS, _spawn_background


@pytest.mark.asyncio
async def test_spawn_background_retains_task_until_done() -> None:
    ran = asyncio.Event()

    async def _work() -> None:
        await asyncio.sleep(0.02)
        ran.set()

    task = _spawn_background(_work())
    # Strong reference is held by the module set, even if we drop our local.
    assert task in _BACKGROUND_TASKS
    del task
    gc.collect()  # a bare create_task would let the task die here

    await asyncio.wait_for(ran.wait(), timeout=1.0)
    assert ran.is_set()


@pytest.mark.asyncio
async def test_spawn_background_discards_task_after_completion() -> None:
    async def _work() -> None:
        return None

    task = _spawn_background(_work())
    await task
    # done_callback runs on the next loop tick; yield once so it fires.
    await asyncio.sleep(0)
    assert task not in _BACKGROUND_TASKS
