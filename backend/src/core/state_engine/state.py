"""The canonical state. Immutable: a transition returns a NEW state.

The model never owns this — it is rebuilt from observations, rendered compactly
for the model, and fingerprinted so a failed move is never proposed twice.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any

_FACT_CHARS = 320
_UI_FACTS = 12  # how many facts a state carries to the UI (the model sees the last 8)


@dataclass(frozen=True)
class Goal:
    text: str
    constraints: tuple[str, ...] = ()


@dataclass(frozen=True)
class Move:
    """Something the agent could do. ``tool == "finish"`` ends with an answer."""

    tool: str
    args: dict = field(default_factory=dict)
    why: str = ""

    def fingerprint(self) -> str:
        blob = json.dumps({"t": self.tool, "a": self.args}, sort_keys=True, default=str)
        return hashlib.sha1(blob.encode()).hexdigest()[:12]

    def label(self) -> str:
        arg = ", ".join(f"{k}={str(v)[:60]}" for k, v in self.args.items())
        return f"{self.tool}({arg})"


@dataclass(frozen=True)
class Observation:
    """What a move actually produced. ``predicted`` marks a simulated (not real) outcome."""

    move: Move
    ok: bool
    text: str
    predicted: bool = False

    def fact(self) -> str:
        head = " ".join(self.text.split())[:_FACT_CHARS]
        return f"{self.move.label()} -> {'ok' if self.ok else 'FAILED'}: {head}"


@dataclass(frozen=True)
class Evaluation:
    """How good a state is relative to the goal. ``done`` needs an ``answer``."""

    progress: float = 0.0  # 0..1
    done: bool = False
    answer: str = ""
    reason: str = ""


@dataclass(frozen=True)
class AgentState:
    goal: Goal
    facts: tuple[str, ...] = ()  # what real observations established
    failed: tuple[str, ...] = ()  # move fingerprints that failed or led nowhere
    tried: tuple[str, ...] = ()  # every move fingerprint applied on this path
    progress: float = 0.0
    depth: int = 0
    trail: tuple[str, ...] = ()  # human-readable path of applied moves

    def apply(self, obs: Observation, evaluation: Evaluation) -> "AgentState":
        """State[n] + Move + Result -> State[n+1]."""
        fp = obs.move.fingerprint()
        return replace(
            self,
            facts=self.facts + ((obs.fact(),) if obs.ok else ()),
            failed=self.failed + ((fp,) if not obs.ok else ()),
            tried=self.tried + (fp,),
            progress=max(self.progress, evaluation.progress) if obs.ok else self.progress,
            depth=self.depth + 1,
            trail=self.trail + (obs.move.label(),),
        )

    def learn(self, obs: Observation) -> "AgentState":
        """A real observation from a probe that was NOT selected is still a fact."""
        if not obs.ok or obs.predicted:
            return self
        return replace(self, facts=self.facts + (obs.fact(),))

    def retreat_to(self, parent: "AgentState") -> "AgentState":
        """Back up to ``parent`` from a dead end: keep every real fact learned, remember every failed
        move, and prune the move that led INTO this dead end so the branch is not re-taken."""
        restored = replace(parent, facts=self.facts, failed=tuple(dict.fromkeys(parent.failed + self.failed)))
        return restored.with_failed(self.tried[-1]) if self.tried else restored

    def with_failed(self, fingerprint: str) -> "AgentState":
        """A move that led nowhere is remembered so it is not proposed again."""
        return self if fingerprint in self.failed else replace(self, failed=self.failed + (fingerprint,))

    def render(self, max_facts: int = 8) -> str:
        """Compact canonical view for the model (bounded, no chat history)."""
        lines = [f"GOAL: {self.goal.text}"]
        if self.goal.constraints:
            lines.append("CONSTRAINTS: " + "; ".join(self.goal.constraints))
        lines.append(f"PROGRESS: {self.progress:.2f}   DEPTH: {self.depth}")
        lines.append("KNOWN FACTS:" + ("" if self.facts else " (none yet)"))
        lines += [f"  - {f}" for f in self.facts[-max_facts:]]
        if self.trail:
            lines.append("MOVES SO FAR: " + " | ".join(self.trail[-6:]))
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "facts": len(self.facts),
            "failed": len(self.failed),
            "progress": self.progress,
            "depth": self.depth,
            # What the state actually holds, for the UI: the real observations (the same bounded text the
            # model is shown — never reasoning), the fingerprints of the moves this state has ruled out,
            # and the path of applied moves that reached it. All bounded; a UI can read the search.
            "fact_list": [f[:_FACT_CHARS] for f in self.facts[-_UI_FACTS:]],
            "failed_fps": list(self.failed),
            "trail": list(self.trail),
        }
