"""Background runtime for user-started autonomous objectives."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import suppress

from core.agent.tool_dispatch import reset_allowed_tool_names, set_allowed_tool_names
from core.engine import Engine
from core.obs import ObsCollector
from storage.objectives import Objective, ObjectiveStore

logger = logging.getLogger(__name__)


class ObjectiveRuntime:
    """Single-worker supervisor for queued objectives."""

    # The first autonomy slice is deliberately read-only. Browser interaction
    # is excluded because click/fill/eval can mutate remote state.
    READ_ONLY_TOOLS = frozenset(
        {
            "web_search",
            "web_fetch",
            "file_task",
            "sysinfo",
            "diagnostics",
        }
    )

    POLL_SECONDS = 0.5
    LEASE_SECONDS = 900.0
    MAX_OBJECTIVE_SECONDS = 600.0

    # The specific-task workflow is a LOOP, not a
    # single engine pass. Each round is one `engine.process()` call on the
    # SAME execution session (history accumulates). The engine's
    # `agent_loop_done` obs event with hit_limit=True means the model ran out
    # of iterations before finishing — continue to the next round. A natural
    # loop end (agent_loop_done without hit_limit) means the model decided it
    # was done — mark completed. Cap rounds so a spinning objective can't run
    # forever; the wall-clock caps above still bound each round.
    MAX_OBJECTIVE_ROUNDS = 5
    ROUND_CONTINUATION = (
        "Continue the autonomous objective. Review what you have done so far "
        "in this conversation, decide what remains, and complete it. When the "
        "objective is fully satisfied, give a final summary and stop."
    )

    def __init__(self, engine: Engine, db_path: str):
        self._engine = engine
        self._store = ObjectiveStore(db_path)
        self._stop = asyncio.Event()
        self._worker: asyncio.Task | None = None
        self._active_task: asyncio.Task | None = None
        self._active_id: str | None = None
        self._lease_owner = f"runtime-{uuid.uuid4()}"

    @property
    def store(self) -> ObjectiveStore:
        return self._store

    async def start(self) -> None:
        if self._worker and not self._worker.done():
            return
        self._stop.clear()
        self._worker = asyncio.create_task(self._run(), name="localmind-objective-supervisor")
        logger.info("[objectives] supervisor started")

    async def stop(self) -> None:
        """Stop accepting work and leave active work recoverable on restart."""
        self._stop.set()
        if self._active_id:
            current = self._store.get(self._active_id)
            if current and current.status == "running":
                self._store.update_owned(
                    self._active_id,
                    self._lease_owner,
                    status="queued",
                    lease_until=None,
                )
        for task in (self._active_task, self._worker):
            if task and not task.done():
                task.cancel()
        for task in (self._active_task, self._worker):
            if task:
                with suppress(asyncio.CancelledError):
                    await task
        self._active_task = None
        self._worker = None
        self._active_id = None
        logger.info("[objectives] supervisor stopped")

    def interrupt(self, objective_id: str) -> None:
        """Interrupt only the current objective, not the supervisor."""
        if self._active_id == objective_id and self._active_task and not self._active_task.done():
            self._active_task.cancel()

    async def _run(self) -> None:
        while not self._stop.is_set():
            objective = self._store.claim_next(self.LEASE_SECONDS, lease_owner=self._lease_owner)
            if objective is None:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.POLL_SECONDS)
                except asyncio.TimeoutError:
                    pass
                continue

            self._active_id = objective.id
            self._active_task = asyncio.create_task(
                self._execute(objective),
                name=f"localmind-objective-{objective.id}",
            )
            try:
                await self._active_task
            except asyncio.CancelledError:
                # A user pause/cancel interrupts only this objective. During
                # shutdown, leave the loop through the stop event.
                if self._stop.is_set():
                    break
            finally:
                self._active_task = None
                self._active_id = None

    async def _execute(self, objective: Objective) -> None:
        """Run the specific-task loop: plan → execute → observe → decide.

        Each round is one `engine.process()` call on the SAME execution
        session (so history — and thus "observe what I did" — accumulates).
        After a round, the engine's `agent_loop_done` obs event tells us
        whether the model finished naturally (no hit_limit → completed) or
        ran out of iterations (hit_limit=True → continue to the next round
        with a continuation nudge). Stops early on a pending write
        (blocked for approval), on an empty round, or when the user pauses/
        cancels between rounds. Capped at MAX_OBJECTIVE_ROUNDS.
        """
        self._store.update_owned(objective.id, self._lease_owner, last_event="objective_started")
        obs = ObsCollector()
        response: list[str] = []
        pending_write: dict | None = None
        started = time.monotonic()
        prompt = objective.prompt
        execution_session_id = objective.execution_session_id or f"objective-{objective.id}"
        if objective.resume_message:
            prompt = f"{objective.resume_message}\n\nContinue the autonomous objective: {objective.prompt}"

        async def run_round(round_prompt: str) -> bool:
            """Run one engine pass. Returns True if the model finished
            naturally (agent_loop_done WITHOUT hit_limit)."""
            nonlocal pending_write
            natural_end = False
            fence_token = set_allowed_tool_names(self.READ_ONLY_TOOLS)

            def absorb() -> None:
                """Drain pending obs events into the store + natural_end."""
                nonlocal natural_end
                for event in obs.drain():
                    self._store.update_owned(
                        objective.id,
                        self._lease_owner,
                        last_event=event.type,
                    )
                    if event.type == "agent_loop_done" and not event.data.get("hit_limit"):
                        # Model finished the turn on its own — the
                        # objective's current phase is complete.
                        natural_end = True

            try:
                async for chunk in self._engine.process(
                    message=round_prompt,
                    session_id=execution_session_id,
                    obs=obs,
                    allowed_tool_names=set(self.READ_ONLY_TOOLS),
                ):
                    if chunk.text:
                        response.append(chunk.text)
                    if chunk.metadata:
                        pending = chunk.metadata.get("pending_write")
                        if pending:
                            pending_write = pending
                    absorb()
                    if chunk.status:
                        self._store.update_owned(
                            objective.id,
                            self._lease_owner,
                            last_event=chunk.status[:200],
                        )
                # The engine may emit agent_loop_done AFTER the final chunk
                # (clarification / web-search paths yield no following chunk)
                # or without any chunk after the emit. Drain once more so
                # those events aren't missed.
                absorb()
            finally:
                reset_allowed_tool_names(fence_token)
            return natural_end

        try:
            for round_index in range(1, self.MAX_OBJECTIVE_ROUNDS + 1):
                # Between rounds, respect a user pause/cancel without waiting
                # for the next claim cycle.
                current = self._store.get(objective.id)
                if current is None or current.cancel_requested or current.status != "running":
                    break

                round_prompt = prompt if round_index == 1 else self.ROUND_CONTINUATION
                try:
                    natural_end = await asyncio.wait_for(
                        run_round(round_prompt), timeout=self.MAX_OBJECTIVE_SECONDS
                    )
                except asyncio.TimeoutError:
                    self._store.update_owned(
                        objective.id,
                        self._lease_owner,
                        status="failed",
                        error=(
                            f"Objective exceeded the {int(self.MAX_OBJECTIVE_SECONDS)} "
                            "second runtime limit."
                        ),
                        last_event="objective_timeout",
                        lease_until=None,
                    )
                    return

                self._store.update_owned(
                    objective.id,
                    self._lease_owner,
                    last_event=f"objective_round_{round_index}",
                )

                # Stop when the model says the phase is done or we need
                # approval — no more rounds needed.
                if natural_end or pending_write or round_index == self.MAX_OBJECTIVE_ROUNDS:
                    break
                logger.info(
                    "[objectives] objective %s round %d hit iteration limit — continuing",
                    objective.id[:8],
                    round_index,
                )

            # If the user paused/canceled while we were mid-loop, leave the
            # store's status alone — don't overwrite canceled with failed.
            current = self._store.get(objective.id)
            if current is not None and (
                current.cancel_requested or current.status != "running"
            ):
                return

            text = "".join(response).strip()
            if not text and not pending_write:
                self._store.update_owned(
                    objective.id,
                    self._lease_owner,
                    status="failed",
                    error="Objective produced no usable response.",
                    last_event="objective_empty",
                    lease_until=None,
                )
                return

            if pending_write:
                self._store.update_owned(
                    objective.id,
                    self._lease_owner,
                    status="blocked",
                    result=text,
                    approval=json.dumps(pending_write, ensure_ascii=False),
                    last_event="approval_required",
                    lease_until=None,
                )
            else:
                self._store.update_owned(
                    objective.id,
                    self._lease_owner,
                    status="completed",
                    result=text,
                    completed_at=time.time(),
                    last_event="objective_completed",
                    lease_until=None,
                )
            logger.info(
                "[objectives] objective %s finished in %.1fs",
                objective.id[:8],
                time.monotonic() - started,
            )
        except asyncio.CancelledError:
            current = self._store.get(objective.id)
            if current and current.status == "running":
                self._store.update_owned(
                    objective.id,
                    self._lease_owner,
                    status="queued",
                    lease_until=None,
                )
            raise
        except Exception as exc:
            logger.exception("[objectives] objective %s failed", objective.id[:8])
            self._store.update_owned(
                objective.id,
                self._lease_owner,
                status="failed",
                error=str(exc)[:1000],
                last_event="objective_failed",
                lease_until=None,
            )
