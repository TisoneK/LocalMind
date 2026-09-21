"""Run the state engine on a goal:  python -m core.state_engine "<goal>" [--provider deepseek --model deepseek-chat]"""
import argparse
import asyncio
import json

from adapters import get_adapter
from core.state_engine import Goal, StateEngine


async def _main(goal: str, provider: str, model: str, as_json: bool) -> None:
    engine = StateEngine(get_adapter(provider, model))
    async for ev in engine.run(Goal(goal)):
        print(json.dumps(ev.to_dict(), ensure_ascii=False) if as_json else f"[{ev.kind}] {ev.data}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("goal")
    ap.add_argument("--provider", default="deepseek")
    ap.add_argument("--model", default="deepseek-chat")
    ap.add_argument("--json", action="store_true", help="one JSON event per line (the UI contract)")
    a = ap.parse_args()
    asyncio.run(_main(a.goal, a.provider, a.model, a.json))
