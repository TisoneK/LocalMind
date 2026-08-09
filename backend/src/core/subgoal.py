"""
Per-run subgoal scratchpad — B-2026-08-02-8 (B3, subgoal tools).

Lets an agent decompose a multi-step task ("build a hello world repo")
into trackable subgoals ("create dir → write hello.py → git init →
git add → git commit") and update their status across iterations.
The planning-phase plan is injected as text but can't be changed
mid-run — this registry is the mutable, per-run working memory.

Isolation model (same as tools/proposals.py from B-2026-08-02-7):
- A contextvars.ContextVar holds the registry, so every asyncio task
  gets its own copy — a delegated child agent's scratchpad never bleeds
  into the parent and vice versa.
- AgentLoop.run() calls reset_subgoals() at the start of every run, so
  a previous run's scratchpad is discarded at the next run start.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Optional

# Valid lifecycle statuses for a subgoal.
SUBGOAL_STATUSES: tuple[str, ...] = ("pending", "in_progress", "completed", "blocked")

_STATUS_MARKERS: dict[str, str] = {
    "pending": "⬜",
    "in_progress": "🔄",
    "completed": "✅",
    "blocked": "⛔",
}


@dataclass
class Subgoal:
    """A single tracked subgoal in the current run's scratchpad."""

    id: str
    description: str
    status: str = "pending"
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status,
            "notes": self.notes,
        }


class SubgoalRegistry:
    """Ordered per-run subgoal registry with stable sequential ids."""

    def __init__(self) -> None:
        self._subgoals: dict[str, Subgoal] = {}
        self._order: list[str] = []
        self._counter = 0

    def add(self, description: str, status: str = "pending") -> Subgoal:
        """Add a subgoal and return it. Ids are stable within the run (sg-1, sg-2...)."""
        self._counter += 1
        subgoal = Subgoal(id=f"sg-{self._counter}", description=description.strip(), status=status)
        self._subgoals[subgoal.id] = subgoal
        self._order.append(subgoal.id)
        return subgoal

    def update(
        self,
        subgoal_id: str,
        *,
        status: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[Subgoal]:
        """Update a subgoal's status/notes. Returns None if the id is unknown."""
        subgoal = self._subgoals.get(subgoal_id)
        if subgoal is None:
            return None
        if status is not None:
            subgoal.status = status
        if notes is not None:
            subgoal.notes = notes
        return subgoal

    def get(self, subgoal_id: str) -> Optional[Subgoal]:
        return self._subgoals.get(subgoal_id)

    def all(self) -> list[Subgoal]:
        """Subgoals in insertion order."""
        return [self._subgoals[i] for i in self._order]

    def list_dicts(self) -> list[dict]:
        return [s.to_dict() for s in self.all()]

    def as_markdown(self) -> str:
        """Render the scratchpad so the model can see its own state."""
        if not self._subgoals:
            return "(no subgoals yet)"
        lines = []
        for subgoal in self.all():
            marker = _STATUS_MARKERS.get(subgoal.status, "⬜")
            line = f"- [{marker}] `{subgoal.id}` {subgoal.description} ({subgoal.status})"
            if subgoal.notes:
                line += f" — {subgoal.notes}"
            lines.append(line)
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._subgoals)


# ── Contextvar access ──────────────────────────────────────────────────────

_registry: contextvars.ContextVar[Optional[SubgoalRegistry]] = contextvars.ContextVar(
    "_subgoal_registry", default=None
)


def get_registry() -> SubgoalRegistry:
    """Return the current run's registry (creating it lazily)."""
    current = _registry.get()
    if current is None:
        current = SubgoalRegistry()
        _registry.set(current)
    return current


def reset_subgoals() -> None:
    """Start a fresh scratchpad. Called at the top of every agent run."""
    _registry.set(SubgoalRegistry())


__all__ = [
    "SUBGOAL_STATUSES",
    "Subgoal",
    "SubgoalRegistry",
    "get_registry",
    "reset_subgoals",
]
