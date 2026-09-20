"""The turn bus: how the processes working on ONE goal talk to each other.

A turn is not one caller waiting on one callee. The act loop, the Thinker, the
verifiers and the read-only grounding checks all work on the same goal at the
same time, and each of them knows something the others can use. This module is
the shared surface they publish to, so none of them has to call or await another:

  * **Facts are appended, never edited.** A fact records who said it (`source`),
    what kind of thing it is (`kind`), which loop `step` and which `goal_version`
    (plan generation) it answers, what it is grounded in, and when. A correction
    is a new fact.
  * **Freshness is decided at read time.** A replan bumps `goal_version`; a fact
    that answers an older version is stale and is never returned as current, so a
    slow verdict about the plan that was just replaced cannot be applied to its
    replacement (a stale answer that arrives late looks as authoritative as a
    fresh one, which is worse than none).
  * **Lanes are the processes in flight** for the goal. `track()` registers a
    background task; a lane that fails publishes an `error` fact instead of
    raising into the loop.
  * **`gate()` is the only place anything blocks**, and it is bounded: the loop
    waits for named lanes only where an irreversible step demands their verdict,
    and gives up (reporting which lanes timed out) rather than waiting forever.

Single-loop, in-process, no locks: every method runs on the event loop thread.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Fact:
    """One thing a process knows, with where it came from and what it answers."""

    seq: int
    source: str  # who published it: "thinker", "verifier", "system_tool", ...
    kind: str  # what it is: "analysis", "state", "verdict", "error", ...
    step: int  # the loop step it answers
    goal_version: int  # the plan generation it answers
    value: Any
    grounded_in: tuple = ()  # evidence it rests on (step ids, paths, ...)
    ts: float = 0.0


@dataclass
class GateResult:
    """Outcome of a bounded wait on lanes."""

    finished: list = field(default_factory=list)
    timed_out: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.timed_out


class TurnBus:
    """The shared, append-only record of one turn. See the module docstring."""

    def __init__(self, on_fact: Optional[Callable[[Fact, bool], None]] = None) -> None:
        self._log: list[Fact] = []
        self._lanes: dict[str, asyncio.Task] = {}
        self._waiters: list[asyncio.Future] = []
        self._on_fact = on_fact
        self.goal_version = 0

    # ── publish / read ───────────────────────────────────────────────────

    def publish(
        self,
        source: str,
        kind: str,
        value: Any,
        *,
        step: int,
        goal_version: Optional[int] = None,
        grounded_in: Iterable = (),
    ) -> Fact:
        """Append a fact. ``goal_version`` is the plan generation the publisher
        was working on when it STARTED (defaults to the current one); a process
        that began before a replan passes its own, so its late fact is stale."""
        fact = Fact(
            seq=len(self._log) + 1,
            source=source,
            kind=kind,
            step=step,
            goal_version=self.goal_version if goal_version is None else goal_version,
            value=value,
            grounded_in=tuple(grounded_in),
            ts=time.monotonic(),
        )
        self._log.append(fact)
        if self._on_fact is not None:
            try:
                self._on_fact(fact, self.is_stale(fact))
            except Exception:  # observability must never break a turn
                logger.debug("[turn-bus] on_fact hook failed", exc_info=True)
        for fut in [w for w in self._waiters if not w.done()]:
            fut.set_result(None)
        self._waiters = [w for w in self._waiters if not w.done()]
        return fact

    def replan(self) -> int:
        """The goal was re-planned: every fact about the old plan is now stale."""
        self.goal_version += 1
        return self.goal_version

    def is_stale(self, fact: Fact) -> bool:
        return fact.goal_version < self.goal_version

    def cursor(self) -> int:
        """Position to pass as ``since`` to read only what arrives after now."""
        return len(self._log)

    def facts(
        self,
        *,
        kind: Optional[str] = None,
        source: Optional[str] = None,
        since: int = 0,
        include_stale: bool = False,
    ) -> list[Fact]:
        return [
            f
            for f in self._log[since:]
            if (kind is None or f.kind == kind)
            and (source is None or f.source == source)
            and (include_stale or not self.is_stale(f))
        ]

    def latest(self, kind: str, *, source: Optional[str] = None, step: Optional[int] = None) -> Optional[Fact]:
        """The newest FRESH fact of this kind (optionally for one source/step)."""
        for f in reversed(self._log):
            if f.kind != kind or self.is_stale(f):
                continue
            if source is not None and f.source != source:
                continue
            if step is not None and f.step != step:
                continue
            return f
        return None

    def log(self) -> list[Fact]:
        """The whole append-only record, stale facts included (for debugging)."""
        return list(self._log)

    async def wait_for(
        self,
        kind: str,
        *,
        source: Optional[str] = None,
        step: Optional[int] = None,
        timeout: float,
    ) -> Optional[Fact]:
        """Wait (bounded) for a fresh fact of this kind; None on timeout."""
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            hit = self.latest(kind, source=source, step=step)
            if hit is not None:
                return hit
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return None
            fut = asyncio.get_running_loop().create_future()
            self._waiters.append(fut)
            try:
                await asyncio.wait_for(fut, timeout=remaining)
            except asyncio.TimeoutError:
                return self.latest(kind, source=source, step=step)

    # ── lanes: the processes in flight for this goal ─────────────────────

    def track(self, lane: str, task: asyncio.Task, *, step: int) -> asyncio.Task:
        """Register a background task as a lane. A lane that raises publishes an
        ``error`` fact (never an exception into the loop); a finished lane is
        removed. A second task under the same name replaces the first."""
        self._lanes[lane] = task

        def _done(t: asyncio.Task, _lane: str = lane, _step: int = step) -> None:
            if self._lanes.get(_lane) is t:
                del self._lanes[_lane]
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                self.publish(_lane, "error", repr(exc), step=_step)

        task.add_done_callback(_done)
        return task

    def in_flight(self) -> list[str]:
        return sorted(name for name, t in self._lanes.items() if not t.done())

    async def gate(self, lanes: Iterable[str], *, timeout: float) -> GateResult:
        """The one blocking point: wait, bounded, for the NAMED lanes.

        Use it only where an irreversible step needs a lane's verdict. A lane
        that is not running counts as finished; one that outlasts ``timeout`` is
        reported in ``timed_out`` and left running (the caller decides what a
        missing verdict means; nothing is cancelled here)."""
        names = list(lanes)
        pending = {n: self._lanes[n] for n in names if n in self._lanes and not self._lanes[n].done()}
        result = GateResult(finished=[n for n in names if n not in pending])
        if pending:
            done, _ = await asyncio.wait(pending.values(), timeout=timeout)
            for n, t in pending.items():
                (result.finished if t in done else result.timed_out).append(n)
        return result

    def cancel_all(self) -> None:
        for t in list(self._lanes.values()):
            if not t.done():
                t.cancel()
        self._lanes.clear()
