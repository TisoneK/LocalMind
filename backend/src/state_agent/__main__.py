"""The engine has no environment of its own, so `python -m state_agent` cannot run a goal by itself.

Run it through an adapter instead — inside LocalMind that is:

    python -m state_agent.adapters.localmind_cli "<goal>"

A standalone install ships its own CLI wired to its own environment. This module deliberately imports
nothing from LocalMind: the engine's dependency rule is enforced by tests/state_agent/test_boundary.py.
"""
import sys

MESSAGE = (
    "state_agent is the engine, not a program: it needs an environment adapter to run.\n"
    "Inside LocalMind:  python -m state_agent.adapters.localmind_cli \"<goal>\"\n"
    "In your own host:  construct StateEngine(environment, proposer=..., evaluator=...).run(Goal(...))\n"
)


def main() -> int:
    print(MESSAGE)
    return 2


if __name__ == "__main__":
    sys.exit(main())
