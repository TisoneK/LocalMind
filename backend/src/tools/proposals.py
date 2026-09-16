"""
Per-run proposal registry — Propose-stage tools.

Stores staged file edits/writes (path → proposed content) so the
propose/select/apply pattern can work across multiple tool calls WITHIN
one agent run:

    propose_str_replace(...)   → stages candidate edit (no disk write)
    propose_write_file(...)    → stages candidate full-file write (no write)
    apply_proposed_edit(...)   → writes the staged winner to disk

Isolation rules (per the B2 spec's "Risk" note):
- A contextvars.ContextVar holds the registry, so every asyncio task gets
  its own copy — a delegated child agent's proposals never bleed into the
  parent and vice versa.
- AgentLoop.run() calls reset_proposals() at the start of every run, so a
  run that ends without applying its staged edits simply discards them at
  the next run start (matching the fresh-per-turn steering queue / abort
  event pattern from A5/A2).
"""

from __future__ import annotations

import contextvars
from typing import Optional

_proposals: contextvars.ContextVar[Optional[dict[str, str]]] = contextvars.ContextVar(
    "_proposed_edits", default=None
)


def reset_proposals() -> None:
    """Start a fresh proposal scope. Called at the top of every agent run."""
    _proposals.set({})


def get_proposals() -> dict[str, str]:
    """Return the current run's proposal registry (creating it lazily)."""
    current = _proposals.get()
    if current is None:
        current = {}
        _proposals.set(current)
    return current


def stage_proposal(path: str, content: str) -> None:
    """Stage proposed content for `path` (a resolved absolute path)."""
    get_proposals()[path] = content


def get_proposal(path: str) -> Optional[str]:
    """Return staged content for `path`, or None if nothing is staged."""
    return get_proposals().get(path)


def discard_proposal(path: str) -> None:
    """Remove the staged proposal for `path` after it has been applied."""
    get_proposals().pop(path, None)
