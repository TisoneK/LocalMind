"""State Agent — a state-driven agent engine, environment-agnostic by construction.

The agent is a state-transition system that uses a model to propose and judge actions; the ENGINE owns the
state, not the model:

    Goal -> State -> Proposer -> candidate Actions -> Environment.probe (or Simulator.predict)
                                                              |
                                              Evaluator <-----+   (one call scores every outcome)
                                                  |
                                    the search (beam of one + backtracking) -> Transition -> new State
                                                  |
                                         TerminalCondition decides when it is over

Nothing in this package knows what an environment is. Adapters supply one:

    from state_agent import Goal, StateEngine, EngineBudget
    from state_agent.adapters.localmind import build_engine   # LocalMind is adapter #1

    engine = build_engine(adapter, EngineBudget(max_model_calls=16))
    async for event in engine.run(Goal("find the README and say which framework it uses")):
        print(event.to_dict())

The public surface is the contracts (``protocols``), the state (``state``), the loop (``search``), and the
model's two jobs (``model``). If you are writing an adapter, you need ``Environment``, a ``ModelPort``, and
``build_engine`` (or the ``StateEngine`` constructor directly).
"""
from state_agent.model import LLMEvaluator, LLMMoveProposer, ModelPort, parse_json
from state_agent.protocols import (
    Action,
    ActionSpec,
    Environment,
    Evaluation,
    Evaluator,
    Goal,
    Move,
    Observation,
    Proposer,
    Simulator,
    TerminalCondition,
    TerminalContext,
    render_action_specs,
)
from state_agent.search import (
    DEFAULT_TERMINAL_CONDITIONS,
    BudgetExhausted,
    EngineBudget,
    EngineEvent,
    NoRunnableActions,
    NothingImproves,
    StateEngine,
)
from state_agent.state import AgentState

__all__ = [
    # contracts
    "Action", "ActionSpec", "Environment", "Evaluation", "Evaluator", "Goal", "Move", "Observation",
    "Proposer", "Simulator", "TerminalCondition", "TerminalContext", "render_action_specs",
    # state
    "AgentState",
    # engine
    "StateEngine", "EngineBudget", "EngineEvent",
    # terminal conditions
    "DEFAULT_TERMINAL_CONDITIONS", "BudgetExhausted", "NoRunnableActions", "NothingImproves",
    # model layer
    "ModelPort", "LLMMoveProposer", "LLMEvaluator", "parse_json",
]
