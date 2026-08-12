"""
TaskState — first-class task state for one agent turn (ADR-18 P0).

B-2026-08-12-1 (P0 acceptance gate): the model should not have to
reconstruct task state from conversation history. TaskState is the
engine-side record the acceptance gate judges — objective, constraints,
success criteria, phase, progress, evidence, and budget, consolidated
into one serializable object the orchestrator drives.

Lifecycle:
    - Created once per turn in AgentLoop.run().
    - Updated after every tool execution (record_tool, record_step).
    - to_prompt() renders a compact TASK STATE block injected into the
      system prompt each iteration (sibling of the workspace feedback
      bar). The criteria are the "done" contract: the model must not
      report done until every criterion has evidence.
    - The gate (core.agent.verify) evaluates criteria against the trace
      evidence + the workspace; results flow back into context on the
      next iteration.

Relationship to the subgoal scratchpad (create_plan/subgoals): the
scratchpad stays the model's own planning artifact; TaskState is the
engine-side record the gate judges. Complementary, not duplicative.

Phases mirror AgentStep.phase (core/agent/models.py): plan / execute /
verify / final.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

PHASE_PLAN = "plan"
PHASE_EXECUTE = "execute"
PHASE_VERIFY = "verify"
PHASE_FINAL = "final"


@dataclass
class TaskState:
    """Engine-side objective truth for one agent turn (ADR-18 P0)."""

    objective: str = ""
    constraints: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    phase: str = PHASE_EXECUTE
    completed: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (step, error)
    evidence: list[dict] = field(default_factory=list)
    iteration: int = 0
    budget: dict = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)

    # ── Mutators ─────────────────────────────────────────────────────────

    def set_budget(
        self,
        iter_used: int,
        iter_max: int,
        wall_used: float,
        wall_max: float,
    ) -> None:
        """Record the iteration/wall-clock budget the loop enforces."""
        self.budget = {
            "iter_used": iter_used,
            "iter_max": iter_max,
            "wall_used": round(wall_used, 1),
            "wall_max": round(wall_max, 1),
        }

    def record_tool(
        self,
        tool_name: str,
        tool_input: str,
        observation: str,
        succeeded: bool = True,
        iteration: Optional[int] = None,
    ) -> None:
        """Append one tool execution to the evidence ledger."""
        self.evidence.append(
            {
                "tool": tool_name,
                "input": (tool_input or "")[:500],
                "observation": (observation or "")[:500],
                "succeeded": succeeded,
                "iteration": iteration if iteration is not None else self.iteration,
            }
        )

    def record_step(self, step: str, succeeded: bool, error: str = "") -> None:
        """Move a plan step into completed/failed and out of pending."""
        if step in self.pending:
            self.pending.remove(step)
        if succeeded:
            if step not in self.completed:
                self.completed.append(step)
        else:
            self.failed.append((step, error or "unknown error"))

    def advance_phase(self, phase: str) -> None:
        self.phase = phase

    # ── Serialization ────────────────────────────────────────────────────

    def to_prompt(self) -> str:
        """Compact TASK STATE block for system-prompt injection.

        Kept concise: the evidence itself is already visible via the
        tool messages in context — duplicating it here would bloat the
        prompt (the workspace feedback bar makes the same trade-off).
        The criteria render as an unchecked checklist so the model sees
        the "done" contract every iteration.
        """
        if (
            not self.objective
            and not self.success_criteria
            and not (self.completed or self.pending or self.failed)
        ):
            return ""
        lines = ["# Task State"]
        if self.objective:
            lines.append(f"Objective: {self.objective}")
        if self.constraints:
            lines.append(f"Constraints: {'; '.join(self.constraints)}")
        if self.success_criteria:
            lines.append("Success criteria — do NOT report done until ALL are met:")
            for criterion in self.success_criteria:
                lines.append(f"  - [ ] {criterion}")
        if self.completed or self.pending or self.failed:
            lines.append("Progress:")
            for step in self.completed:
                lines.append(f"  - [x] {step}")
            for step in self.pending:
                lines.append(f"  - [ ] {step}")
            for step, error in self.failed:
                lines.append(f"  - [!] {step} — failed: {error[:120]}")
        if self.budget:
            lines.append(
                f"Phase: {self.phase} · Iteration "
                f"{self.budget.get('iter_used', self.iteration)}/"
                f"{self.budget.get('iter_max', '?')}"
            )
        else:
            lines.append(f"Phase: {self.phase} · Iteration {self.iteration}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """JSON-safe serialization for obs/session persistence."""
        return {
            "objective": self.objective,
            "constraints": list(self.constraints),
            "success_criteria": list(self.success_criteria),
            "phase": self.phase,
            "completed": list(self.completed),
            "pending": list(self.pending),
            "failed": [{"step": step, "error": error} for step, error in self.failed],
            "evidence": list(self.evidence),
            "iteration": self.iteration,
            "budget": dict(self.budget),
        }
