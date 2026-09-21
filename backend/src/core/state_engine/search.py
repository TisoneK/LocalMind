"""The engine loop: goal -> state -> candidate moves -> probe -> evaluate -> select -> apply.

Slice 1 is a beam of ONE with backtracking, over READ-ONLY moves only:
  * every candidate is really probed (read-only, so probing is safe and the result
    is a true observation, not a guess) — this is the "simulation";
  * one model call scores all outcomes; the best becomes the next state, the rest
    still teach facts (they are real);
  * nothing better than where we stand -> backtrack: the moves are remembered as
    failed and the previous state is restored, up to a budget;
  * a move that is not read-only is never executed here: it is surfaced as
    `needs_confirmation` (ADR-67/70).
Every step is an EngineEvent — states, moves and outcomes, never hidden reasoning —
so the tree of what was explored can be shown.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from core.state_engine.catalog import DEFAULT_CATALOG, ToolSpec
from core.state_engine.executor import Executor, RegistryExecutor
from core.state_engine.llm import LLMEvaluator, LLMMoveProposer
from core.state_engine.state import AgentState, Goal, Move, Observation

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EngineBudget:
    max_depth: int = 6
    max_branches: int = 3
    max_model_calls: int = 16
    max_backtracks: int = 2


@dataclass
class EngineEvent:
    """One step, as a plain record. This is the UI contract: states, moves, outcomes — never reasoning.

    kinds: state | candidates | probe | evaluation | selected | backtrack | needs_confirmation | done | stopped
    Tree ids: `state` carries `node` and `parent`; `selected`/`backtrack` name the node they move to.
    """

    kind: str
    data: dict[str, Any] = field(default_factory=dict)
    seq: int = 0  # position in the run
    t_ms: int = 0  # ms since the run started

    def to_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "t_ms": self.t_ms, "kind": self.kind, **self.data}


class StateEngine:
    def __init__(
        self,
        adapter,
        *,
        catalog: Optional[dict[str, ToolSpec]] = None,
        executor: Optional[Executor] = None,
        proposer=None,
        evaluator=None,
        budget: Optional[EngineBudget] = None,
    ) -> None:
        self.catalog = catalog or DEFAULT_CATALOG
        self.executor = executor or RegistryExecutor(adapter)
        self.proposer = proposer or LLMMoveProposer(adapter, self.catalog)
        self.evaluator = evaluator or LLMEvaluator(adapter)
        self.budget = budget or EngineBudget()

    async def run(self, goal: Goal) -> AsyncIterator[EngineEvent]:
        """`_steps` stamped with the run clock, a sequence number and the tree ids a UI needs."""
        t0 = time.monotonic()
        seq = 0
        counter = 0
        cur: Optional[str] = None
        stack: list[str] = []
        pending_parent: Optional[str] = None
        async for ev in self._steps(goal):
            if ev.kind == "state":
                node = f"n{counter}"
                counter += 1
                ev.data.update(node=node, parent=pending_parent)
                if pending_parent is not None:
                    stack.append(pending_parent)
                cur, pending_parent = node, None
            elif ev.kind == "selected":
                pending_parent = cur
            elif ev.kind == "backtrack":
                cur = stack.pop() if stack else cur
                ev.data["node"] = cur
            if ev.kind not in ("state", "backtrack"):
                ev.data["at"] = cur
            seq += 1
            ev.seq, ev.t_ms = seq, int((time.monotonic() - t0) * 1000)
            yield ev

    async def _timed(self, move: Move) -> tuple[Observation, int]:
        t = time.monotonic()
        obs = await self.executor.run(move)
        return obs, int((time.monotonic() - t) * 1000)

    async def _steps(self, goal: Goal) -> AsyncIterator[EngineEvent]:
        b = self.budget
        state = AgentState(goal)
        history: list[AgentState] = []  # ancestors, for backtracking
        calls = backtracks = 0
        yield EngineEvent("state", {"depth": 0, "goal": goal.text, **state.to_dict()})

        while True:
            if state.depth >= b.max_depth or calls + 2 > b.max_model_calls:
                yield self._stopped("budget", state, calls)
                return

            avoid = set(state.failed) | set(state.tried)
            try:
                moves = await self.proposer.propose(state, b.max_branches, avoid)
            except Exception as exc:  # noqa: BLE001
                yield self._stopped(f"proposer_error: {exc}", state, calls)
                return
            calls += 1
            yield EngineEvent(
                "candidates",
                {"moves": [{"fp": m.fingerprint(), "label": m.label(), "tool": m.tool, "why": m.why} for m in moves]},
            )

            runnable: list[Move] = []
            for m in moves:
                spec = self.catalog.get(m.tool)
                if spec is None:
                    state = state.with_failed(m.fingerprint())  # not a real tool: never again
                elif not spec.read_only:
                    yield EngineEvent("needs_confirmation", {"fp": m.fingerprint(), "move": m.label(), "why": m.why})
                else:
                    runnable.append(m)

            if not runnable:
                state, history, backtracks, ev = self._backtrack(state, history, backtracks, [])
                if ev is None:
                    yield self._stopped("no_moves", state, calls)
                    return
                yield ev
                continue

            timed = await asyncio.gather(*(self._timed(m) for m in runnable))
            outcomes: list[Observation] = [o for o, _ in timed]
            for o, ms in timed:
                yield EngineEvent(
                    "probe",
                    {
                        "fp": o.move.fingerprint(), "move": o.move.label(), "ok": o.ok, "chars": len(o.text),
                        "ms": ms, "excerpt": " ".join(o.text.split())[:320],
                    },
                )

            try:
                evals = await self.evaluator.evaluate(state, outcomes)
            except Exception as exc:  # noqa: BLE001
                yield self._stopped(f"evaluator_error: {exc}", state, calls)
                return
            calls += 1
            for o, e in zip(outcomes, evals):
                yield EngineEvent(
                    "evaluation",
                    {"fp": o.move.fingerprint(), "move": o.move.label(), "progress": e.progress, "done": e.done,
                     "reason": e.reason},
                )

            ranked = sorted(
                (p for p in zip(outcomes, evals) if p[0].ok),
                key=lambda p: (p[1].done, p[1].progress),
                reverse=True,
            )
            if not ranked or (not ranked[0][1].done and ranked[0][1].progress <= state.progress):
                # Nothing beats where we stand: keep what the real probes taught, then back up.
                for o in outcomes:
                    state = state.learn(o).with_failed(o.move.fingerprint())
                state, history, backtracks, ev = self._backtrack(state, history, backtracks, outcomes)
                if ev is None:
                    yield self._stopped("no_progress", state, calls)
                    return
                yield ev
                continue

            best_obs, best_eval = ranked[0]
            history.append(state)
            for o in outcomes:
                if o is not best_obs:
                    state = state.learn(o)
                if not o.ok:
                    # A probe that really failed is remembered as failed HERE too, not only on a backtrack:
                    # the same move would fail again at the next state, and the point of fingerprinting is
                    # that it is not proposed twice.
                    state = state.with_failed(o.move.fingerprint())
            state = state.apply(best_obs, best_eval)
            yield EngineEvent(
                "selected",
                {"fp": best_obs.move.fingerprint(), "move": best_obs.move.label(), "progress": best_eval.progress},
            )
            yield EngineEvent("state", {"depth": state.depth, **state.to_dict()})
            if best_eval.done:
                yield EngineEvent(
                    "done", {"answer": best_eval.answer, "trail": list(state.trail), "model_calls": calls}
                )
                return

    def _backtrack(self, state, history, backtracks, outcomes):
        """Restore the previous state, carrying the failed-move memory (and learned facts) back."""
        if backtracks >= self.budget.max_backtracks or not history:
            return state, history, backtracks, None
        parent = state.retreat_to(history[-1])
        return parent, history[:-1], backtracks + 1, EngineEvent("backtrack", {"to_depth": parent.depth})

    @staticmethod
    def _stopped(reason: str, state: AgentState, calls: int) -> EngineEvent:
        """An honest stop: what is known, and that the goal is NOT settled."""
        return EngineEvent(
            "stopped",
            {
                "reason": reason, "settled": False, "facts": list(state.facts),
                "trail": list(state.trail), "model_calls": calls,
            },
        )
