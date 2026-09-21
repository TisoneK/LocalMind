# State Agent — a state-driven agent engine

An agent engine that treats a goal as a **search over states**, not as a growing conversation. The engine
owns the state; the model has exactly two jobs — propose candidate actions, and score outcomes. It works
against any environment that can describe its actions and perform them, so the same engine can drive a
desktop app, a shell, a repo, a browser or a game.

**LocalMind is adapter #1**, not the engine's subject. Nothing in this package imports LocalMind;
`tests/state_agent/test_boundary.py` fails the build if that ever changes.

## The loop

```
Goal ─► State ─► Proposer ─► candidate Actions ─► Environment.probe   (or Simulator.predict)
                                                        │
                                        Evaluator ◄─────┘   one call scores every outcome
                                            │
                              the search (beam of one + backtracking) ─► Transition ─► new State
                                            │
                                  TerminalCondition decides when it is over
```

- **The state is the engine's.** `AgentState` is immutable (goal, the facts real observations established,
  the actions that failed, the path taken, progress, depth), rendered compactly for the model with no chat
  history, and fingerprinted so an action that failed is never proposed twice.
- **Probing is real.** A read-only action is performed and its actual output recorded. Nothing is invented.
- **Scoring is one call per fan**, with deterministic guards: a failed probe never counts as progress, and
  `done` requires an answer grounded in facts (a predicted outcome can never settle a goal).
- **Backtracking keeps what was learned.** When nothing beats where the state stands, the engine retreats
  to the parent state with every real fact intact and the action that led into the dead end pruned.
- **Every step is an event.** `EngineEvent`s (state, candidates, probe, evaluation, selected, backtrack,
  needs_confirmation, done, stopped) are the whole record — states, actions and outcomes, never hidden
  reasoning. A UI (the State Explorer) is built entirely on them.

## Writing an adapter

Two objects and a budget:

```python
from state_agent import ActionSpec, EngineBudget, Goal, Observation, StateEngine
from state_agent.model import LLMEvaluator, LLMMoveProposer

class MyEnvironment:                     # where actions happen
    name = "my-env"
    def tools(self) -> dict[str, ActionSpec]: ...          # what can be done, and what is read-only
    def is_read_only(self, action) -> bool | None: ...      # None = this environment has no such action
    async def probe(self, action) -> Observation: ...       # perform it; never raise

engine = StateEngine(
    MyEnvironment(),
    proposer=LLMMoveProposer(my_model_port, environment.tools()),
    evaluator=LLMEvaluator(my_model_port),
    simulator=None,                      # optional: predict actions that must not be performed
    budget=EngineBudget(max_model_calls=16),
)
async for event in engine.run(Goal("…")):
    ...
```

A model port is anything that answers a prompt: `async def complete(prompt, *, max_chars=4000) -> str`.
LocalMind's port wraps its provider adapters (`state_agent/adapters/localmind.py`), and its CLI is
`python -m state_agent.adapters.localmind_cli "<goal>"`.

## Extension points

| Point | Protocol | Today |
|---|---|---|
| where actions happen | `Environment` | LocalMind's read-only tools (`dir_explorer`, `file_task`, `web_search`, `web_fetch`, `sysinfo`, `calculate`) |
| what the model is asked | `Proposer`, `Evaluator` | JSON-in/JSON-out prompts against a `ModelPort` |
| acting without performing | `Simulator` | seam wired (a predicted outcome is labelled and never learned as fact); no implementation yet |
| when a run ends | `TerminalCondition` | `BudgetExhausted`, `NoRunnableActions`, `NothingImproves` — each declares the decision point it applies at (`before_propose`, `no_actions`, `no_improvement`) |

Not built yet, deliberately: a `SearchStrategy` protocol (the loop *is* the search until a second strategy
exists — a beam wider than one — to earn the interface), persistent state/resume, and parallel probes.
Those are backlog rows in the host, not promises here.
