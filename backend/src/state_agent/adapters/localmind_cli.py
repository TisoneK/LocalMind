"""Run a goal through an adapter, on the command line.

    python -m state_agent.adapters.localmind_cli "<goal>" [--provider deepseek --model deepseek-chat]
                                                        [--json] [--budget-calls N]

This CLI belongs to the LocalMind ADAPTER, not to the engine: the engine has no environment of its own and
cannot boot without one. A standalone install ships its own CLI wired to its own environment.
"""
import argparse
import asyncio
import json

from adapters import get_adapter
from state_agent import EngineBudget, Goal
from state_agent.adapters.localmind import build_engine


async def _main(goal: str, provider: str, model: str, as_json: bool, max_calls: int) -> None:
    engine = build_engine(get_adapter(provider, model), EngineBudget(max_model_calls=max_calls))
    async for ev in engine.run(Goal(goal)):
        print(json.dumps(ev.to_dict(), ensure_ascii=False) if as_json else f"[{ev.kind}] {ev.data}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("goal")
    ap.add_argument("--provider", default="deepseek")
    ap.add_argument("--model", default="deepseek-chat")
    ap.add_argument("--json", action="store_true", help="one JSON event per line (the UI contract)")
    ap.add_argument("--budget-calls", type=int, default=16, help="model calls the run may spend")
    a = ap.parse_args()
    asyncio.run(_main(a.goal, a.provider, a.model, a.json, a.budget_calls))
