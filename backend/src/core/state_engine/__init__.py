"""State-driven engine (experimental) — built BESIDE the parent agent, not inside it.

The agent is a state-transition system that uses a model to propose and judge
moves; the ENGINE owns the state, not the model. Goal -> state -> candidate
moves -> probe -> evaluate -> select -> apply -> new state, under a hard budget.

It depends only on stable capabilities (model adapters, the tool dispatcher) and
never imports the parent loop, so it can be proven on its own and, if it earns
it, replace the parent later. Slice 1 is read-only: irreversible moves are never
executed here (ADR-70).
"""
from core.state_engine.search import EngineBudget, EngineEvent, StateEngine
from core.state_engine.state import AgentState, Evaluation, Goal, Move, Observation

__all__ = [
    "AgentState", "EngineBudget", "EngineEvent", "Evaluation", "Goal", "Move", "Observation", "StateEngine",
]
