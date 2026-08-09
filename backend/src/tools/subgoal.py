"""
Subgoal scratchpad tools — B-2026-08-02-8 (B3, per Codebuff's
add-subgoal / update-subgoal / create-plan).

Three tools that operate on a per-run SubgoalRegistry (core/subgoal.py):

  - add_subgoal(description)      — record a single new subgoal
  - update_subgoal(id, status?,   — change a subgoal's status ("pending" /
    notes?)                          "in_progress" / "completed" / "blocked")
                                     and/or attach notes
  - create_plan(steps | plan)     — create many subgoals at once from a
                                     markdown list or JSON array

Every tool returns the full current scratchpad so the model always sees
its own state (the registry itself lives in a contextvar — it is NOT
injected into the prompt automatically; the tool results carry it).
"""

from __future__ import annotations

import json
import re

from core.models import Intent, RiskLevel, ToolResult
from core.subgoal import SUBGOAL_STATUSES, get_registry
from tools import register_tool

# Matches "1. step", "1) step", "- step", "* step" list items.
_PLAN_LINE_RE = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+(.+?)\s*$")


def _parse_plan_text(text: str) -> list[str]:
    """Turn a pasted plan (markdown list or plain lines) into steps."""
    """Turn a pasted plan into steps.

    Only list items ("1. step", "- step", "* step") count as steps — bare
    lines like a "Plan:" heading are intentionally skipped so they never
    become bogus steps. For plans that aren't a clean list, pass the JSON
    steps array instead (the schema-documented input).
    """
    steps: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = _PLAN_LINE_RE.match(line)
        if match:
            steps.append(match.group(1).strip())
    return steps


def _render(registry) -> str:
    return f"Current subgoals:\n{registry.as_markdown()}"


async def add_subgoal(message: str) -> ToolResult:
    """Record a single new subgoal in the current run's scratchpad."""
    description = message.strip()
    if not description:
        return ToolResult(
            content="'description' is required for add_subgoal",
            risk=RiskLevel.LOW,
            source="add_subgoal",
            success=False,
            error_type="validation_error",
            error_message="Missing required field 'description'",
        )

    registry = get_registry()
    subgoal = registry.add(description)
    return ToolResult(
        content=f"Added `{subgoal.id}`: {subgoal.description}\n\n{_render(registry)}",
        risk=RiskLevel.LOW,
        source="add_subgoal",
        success=True,
        metadata={
            "subgoal": subgoal.to_dict(),
            "subgoals": registry.list_dicts(),
        },
    )


async def update_subgoal(message: str) -> ToolResult:
    """Update a subgoal's status and/or notes."""
    try:
        payload = json.loads(message) if message.strip().startswith("{") else {}
        if not isinstance(payload, dict):
            payload = {}
    except (json.JSONDecodeError, TypeError):
        payload = {}

    subgoal_id = str(payload.get("id", "")).strip()
    status = payload.get("status")
    notes = payload.get("notes")

    if not subgoal_id:
        return ToolResult(
            content="'id' is required for update_subgoal (e.g. \"sg-1\")",
            risk=RiskLevel.LOW,
            source="update_subgoal",
            success=False,
            error_type="validation_error",
            error_message="Missing required field 'id'",
        )

    if status is not None and status not in SUBGOAL_STATUSES:
        return ToolResult(
            content=(
                f"Invalid status {status!r}. Valid statuses: "
                f"{', '.join(SUBGOAL_STATUSES)}."
            ),
            risk=RiskLevel.LOW,
            source="update_subgoal",
            success=False,
            error_type="validation_error",
            error_message=f"Invalid status '{status}'",
        )

    registry = get_registry()
    subgoal = registry.update(subgoal_id, status=status, notes=notes)
    if subgoal is None:
        return ToolResult(
            content=f"Subgoal {subgoal_id!r} not found in the current run's scratchpad.",
            risk=RiskLevel.LOW,
            source="update_subgoal",
            success=False,
            error_type="not_found",
        )

    return ToolResult(
        content=(
            f"Updated `{subgoal.id}` ({subgoal.status}"
            f"{' — ' + subgoal.notes if subgoal.notes else ''})\n\n{_render(registry)}"
        ),
        risk=RiskLevel.LOW,
        source="update_subgoal",
        success=True,
        metadata={
            "subgoal": subgoal.to_dict(),
            "subgoals": registry.list_dicts(),
        },
    )


async def create_plan(message: str) -> ToolResult:
    """Create many subgoals at once from a markdown list or JSON steps array."""
    steps: list[str] = []
    if message.strip().startswith("{"):
        try:
            payload = json.loads(message)
            if isinstance(payload, dict):
                raw = payload.get("steps") or payload.get("plan") or ""
                if isinstance(raw, list):
                    steps = [str(s).strip() for s in raw if str(s).strip()]
                else:
                    steps = _parse_plan_text(str(raw))
        except (json.JSONDecodeError, TypeError, ValueError):
            steps = _parse_plan_text(message)
    else:
        steps = _parse_plan_text(message)

    if not steps:
        return ToolResult(
            content=(
                "'steps' is required for create_plan — a JSON array "
                '({"steps": ["create dir", "write hello.py"]}) or a markdown '
                "list ('1. create dir\\n2. write hello.py')."
            ),
            risk=RiskLevel.LOW,
            source="create_plan",
            success=False,
            error_type="validation_error",
            error_message="No steps found",
        )

    registry = get_registry()
    created = [registry.add(step) for step in steps]
    ids = ", ".join(s.id for s in created)
    return ToolResult(
        content=(
            f"Created plan with {len(created)} subgoals (`{ids}`):\n\n"
            f"{_render(registry)}"
        ),
        risk=RiskLevel.LOW,
        source="create_plan",
        success=True,
        metadata={
            "created": [s.to_dict() for s in created],
            "subgoals": registry.list_dicts(),
        },
    )


# ── Register the tools ─────────────────────────────────────────────────────

register_tool(
    Intent.ADD_SUBGOAL,
    add_subgoal,
    description=(
        "Record a single subgoal in the current run's subgoal scratchpad. "
        "Use for multi-step tasks to track progress across iterations: add a "
        "step, mark it in_progress/completed as you work, and keep notes. "
        "Prefer create_plan when you know several steps up front. Returns the "
        "full current scratchpad."
    ),
    cost=0.0,
    latency_ms=5,
    parallelizable=True,  # pure in-memory registry write
)

register_tool(
    Intent.UPDATE_SUBGOAL,
    update_subgoal,
    description=(
        "Update a subgoal's status ('pending' | 'in_progress' | 'completed' | "
        "'blocked') and/or attach notes. Ids come from add_subgoal / "
        "create_plan (e.g. 'sg-1'). Returns the full current scratchpad."
    ),
    cost=0.0,
    latency_ms=5,
    parallelizable=True,  # pure in-memory registry write
)

register_tool(
    Intent.CREATE_PLAN,
    create_plan,
    description=(
        "Create multiple subgoals at once for a multi-step task. Pass a JSON "
        "array of steps ({\"steps\": [\"create dir\", \"write hello.py\", ...]}) "
        "or a markdown list ('1. create dir\\n2. write hello.py'). The plan is "
        "tracked in the current run's scratchpad so you can check off each step "
        "as you complete it. Returns the full current scratchpad."
    ),
    cost=0.0,
    latency_ms=5,
    parallelizable=True,  # pure in-memory registry write
)
