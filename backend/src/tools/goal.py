"""Goal tools — ``get_goal`` and ``update_goal``.

The model reads the session's durable goal and mutates it through these
tools. Authority is enforced at execution time:

- create / edit / pause / resume / clear require a DIRECT human turn. During
  an autonomous goal round only completion and blocking are allowed, so a
  round cannot quietly rewrite or stop the work it is supposed to continue.
- blocked needs the same condition to have persisted for at least
  ``BLOCKED_AFTER_ROUNDS`` admitted rounds, and a concrete reason.
- every mutation except create carries the exact ``goal_id`` + ``revision``
  returned by a prior read (compare-and-set; stale refs are rejected).
"""

from __future__ import annotations

import ast
import json
import uuid

from core import goal_rounds
from core.config import settings
from core.models import Intent, RiskLevel, ToolResult
from core.session_workspace import current_session_id
from storage.goals import (
    DEFAULT_MAX_GOAL_ROUNDS,
    Goal,
    GoalConflictError,
    get_goal_store,
)
from tools import register_tool

_ACTIONS = ("create", "edit", "pause", "resume", "complete", "blocked", "clear")
_HUMAN_ONLY = frozenset({"create", "edit", "pause", "resume", "clear"})


def _store():
    return get_goal_store(settings.localmind_db_path)


def _failure(message: str, error_type: str = "validation_error") -> ToolResult:
    return ToolResult(
        content=message,
        risk=RiskLevel.LOW,
        source="goal",
        success=False,
        error_type=error_type,
        error_message=message,
    )


def _payload(goal: Goal | None, session_id: str) -> dict:
    return {
        "goal": goal_rounds.goal_view(goal, session_id),
        "activation": "armed" if goal_rounds.is_armed(session_id) else "disarmed",
    }


def _parse(message: str) -> dict | None:
    text = (message or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return None
    return parsed if isinstance(parsed, dict) else None


def _int_field(data: dict, *names: str) -> int | None:
    for name in names:
        if data.get(name) is not None and str(data.get(name)).strip() != "":
            try:
                return int(data[name])
            except (TypeError, ValueError):
                return None
    return None


def _goal_ref(data: dict) -> tuple[str, int] | None:
    goal_id = str(data.get("goal_id") or data.get("goalId") or "").strip()
    revision = _int_field(data, "revision")
    if not goal_id or revision is None:
        return None
    return goal_id, revision


async def get_goal(message: str = "") -> ToolResult:
    """Read the session's current goal (empty input is a valid call)."""
    session_id = current_session_id()
    if not session_id:
        return _failure("No active chat session — get_goal runs inside a chat turn.")
    goal = _store().get(session_id)
    return ToolResult(
        content=json.dumps(_payload(goal, session_id), ensure_ascii=False),
        risk=RiskLevel.LOW,
        source="get_goal",
        success=True,
        metadata={"goal": goal_rounds.goal_view(goal, session_id)},
    )


async def update_goal(message: str) -> ToolResult:
    """Create or mutate the session's durable goal."""
    session_id = current_session_id()
    if not session_id:
        return _failure("No active chat session — update_goal runs inside a chat turn.")

    data = _parse(message)
    if data is None:
        return _failure(
            "update_goal expects a JSON object, e.g. "
            '{"action": "create", "objective": "...", "max_goal_rounds": 12} '
            'or {"action": "complete", "goal_id": "...", "revision": 3}.'
        )
    action = str(data.get("action") or "").strip().lower()
    if action not in _ACTIONS:
        return _failure(
            f"Unknown action '{action}'. Use one of: {', '.join(_ACTIONS)}."
        )

    in_round = goal_rounds.active_goal_round(session_id) is not None
    if in_round and action in _HUMAN_ONLY:
        return _failure(
            f"'{action}' requires a direct user turn; during an autonomous goal "
            "round only complete or blocked are allowed."
        )

    store = _store()
    try:
        if action == "create":
            objective = str(data.get("objective") or "").strip()
            if not objective:
                return _failure("create requires a non-empty objective.")
            max_rounds = _int_field(data, "max_goal_rounds", "maxGoalRounds")
            goal = store.create(
                goal_id=f"goal-{uuid.uuid4().hex[:12]}",
                session_id=session_id,
                objective=objective,
                max_rounds=max_rounds if max_rounds is not None else DEFAULT_MAX_GOAL_ROUNDS,
            )
            goal_rounds.arm(session_id)
            return ToolResult(
                content=json.dumps(_payload(goal, session_id), ensure_ascii=False),
                risk=RiskLevel.LOW,
                source="update_goal",
                success=True,
                metadata={"goal": goal_rounds.goal_view(goal, session_id)},
            )

        if action == "clear":
            store.clear(session_id)
            goal_rounds.disarm(session_id)
            return ToolResult(
                content=json.dumps({"goal": None, "activation": "disarmed"}),
                risk=RiskLevel.LOW,
                source="update_goal",
                success=True,
            )

        ref = _goal_ref(data)
        if ref is None:
            return _failure(
                "update_goal needs the exact goal_id and revision from a prior "
                "get_goal call."
            )
        goal_id, revision = ref

        if action == "edit":
            updated = store.edit(
                session_id,
                goal_id,
                revision,
                objective=str(data.get("objective") or "").strip() or None,
                max_rounds=_int_field(data, "max_goal_rounds", "maxGoalRounds"),
            )
        elif action == "pause":
            updated = store.set_phase(session_id, goal_id, revision, "paused")
        elif action == "resume":
            updated = store.resume(session_id, goal_id, revision)
        elif action == "complete":
            updated = store.set_phase(session_id, goal_id, revision, "complete")
        else:  # blocked
            reason = str(
                data.get("blocked_reason") or data.get("blockedReason") or ""
            ).strip()
            if not reason:
                return _failure("blocked requires a concrete blocked_reason.")
            current = store.get(session_id)
            if (
                in_round
                and current is not None
                and current.rounds_started < goal_rounds.BLOCKED_AFTER_ROUNDS
            ):
                return _failure(
                    "blocked is not allowed yet: report it only after the same "
                    f"condition persists for at least {goal_rounds.BLOCKED_AFTER_ROUNDS} "
                    "goal rounds. Keep working instead."
                )
            updated = store.set_phase(
                session_id, goal_id, revision, "blocked", blocked_reason=reason
            )

        if updated is None:
            return _failure(
                "Stale goal reference — call get_goal again and copy the current "
                "goal_id and revision.",
                error_type="stale_revision",
            )

        if action == "complete" or action == "pause" or action == "blocked":
            goal_rounds.disarm(session_id)
        elif action == "resume":
            goal_rounds.arm(session_id)

        return ToolResult(
            content=json.dumps(_payload(updated, session_id), ensure_ascii=False),
            risk=RiskLevel.LOW,
            source="update_goal",
            success=True,
            metadata={"goal": goal_rounds.goal_view(updated, session_id)},
        )
    except GoalConflictError as exc:
        return _failure(str(exc), error_type="goal_conflict")
    except Exception as exc:  # never crash a turn on a goal mutation
        return _failure(f"Could not update the goal: {exc}", error_type="internal_error")


register_tool(
    Intent.GET_GOAL,
    get_goal,
    description=(
        "Read this chat's durable goal: objective, phase (active/paused/"
        "blocked/complete), rounds started vs cap, blocker reason, and whether "
        "automatic continuation is armed. Returns {goal: null} when there is "
        "no goal. Call this before update_goal and copy the exact goal_id + "
        "revision."
    ),
    cost=0.0,
    latency_ms=5,
    parallelizable=True,
    input_optional=True,
)

register_tool(
    Intent.UPDATE_GOAL,
    update_goal,
    description=(
        "Create or mutate this chat's durable long-running goal. Actions: "
        "create (objective, optional max_goal_rounds), edit, pause, resume, "
        "complete, blocked (requires blocked_reason), clear. Use create when "
        "the user asks for a substantial multi-turn objective that should keep "
        "going on its own; do not create goals for routine single-turn work. "
        "Every action except create/clear needs the goal_id and revision from "
        "get_goal. During an automatic goal round only complete/blocked are "
        "allowed; blocked only after the same condition persisted for at "
        "least 3 rounds. Mark complete only when the objective is actually "
        "achieved."
    ),
    cost=0.0,
    latency_ms=10,
    parallelizable=False,
)
