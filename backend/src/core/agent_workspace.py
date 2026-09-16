"""Server-side reconstruction of the Agent Workspace run tree + phase strip.

The Agents tab (AgentWorkspace) and the message phase strip are built live in
the frontend from SSE obs events (useLocalMind.ts). They are frontend-only
state, cleared on every session switch, so re-entering a chat showed the empty
"parent agent workspace will appear when a turn starts" placeholder.

To make them survive a reload, the runtime rebuilds the same structures from
the request-local ObsCollector at persist time and stores them with the
assistant message (``agent_runs`` / ``agent_phases`` columns). This module
mirrors the frontend logic — attachToolToAgentRun, delegation_started/
completed handling, evidence_to_parent entries, and buildAgentPhase — so the
restored tree matches what the user saw live.

The shapes are intentionally the frontend's AgentRun / AgentPhase / ToolCall
shapes (camelCase) so the history endpoint can return them verbatim.
"""

from __future__ import annotations

import ast
import hashlib
import time
from typing import Optional

from core.obs import ObsCollector

# Tool names whose output must never surface to the user (delegated child
# output is intermediate model context, not user-facing content). Mirrors
# agent_runtime._INTERNAL_DELEGATION_TOOLS.
_INTERNAL_DELEGATION_TOOLS = frozenset({"delegate", "delegate_parallel", "delegate_inline"})

# The obs event types that narrate the ACTIVE AGENT's lifecycle — attached
# to the parent run's `phases` in build_run_tree so the Agents tab shows the
# whole turn inside the running agent node ("getting started → understood →
# working → turn complete"). These belong on the workspace run node, NOT the
# chat phase strip: the strip (build_agent_phases) keeps the
# plan/gate/orchestrator/failure decision history only.
RUN_LIFECYCLE_TYPES = frozenset(
    {
        "agent_initialization_start",
        "agent_initialization_understanding",
        "agent_initialization_ack",
        "agent_initialization_done",
        "agent_planning_done",
        "agent_thinker_start",
        "agent_thinker_done",
        "agent_loop_start",
        "agent_loop_done",
    }
)


# Canonical narrative order for the run's lifecycle phases. The loop emits
# some events out of story order (agent_loop_start fires BEFORE the init
# events), so phases are stable-sorted by this rank when attached — the
# Agents tab always reads "getting started → understood → working → done".
_LIFECYCLE_PHASE_RANK = {
    "initializing": 0,
    "understanding": 1,
    "acknowledged": 2,
    "initialized": 3,
    "planned": 4,
    "thinking": 5,
    "thinking_done": 6,
    "working": 7,
    "turn_done": 8,
}


def _now_ms() -> int:
    """Wall-clock ms since epoch — the frontend's Date.now() equivalent."""
    return int(time.time() * 1000)


def _as_list(value) -> list:
    """Recover list payloads from obs events.

    ``ObsCollector.emit`` stringifies every non-numeric value, so a list
    payload (node_ids, unmet criteria) arrives here as its repr
    (``"['a', 'b']"") rather than an actual list. Recover it when possible
    (the live frontend loses these — its ``Array.isArray`` check is always
    false — so persisting the recovered list is strictly better); otherwise
    return [].
    """
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.startswith("["):
        try:
            parsed = ast.literal_eval(value)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, SyntaxError):
            return []
    return []


def _visible_tool_output(tool_name: str, agent_name: Optional[str], output: str) -> str:
    """Mirror of the SSE bridge's output filter for the run-tree tool rows."""
    if agent_name or tool_name in _INTERNAL_DELEGATION_TOOLS:
        return ""
    return output


def _tool_call_dict(d: dict) -> dict:
    """Convert a tool_call obs event payload into the frontend ToolCall shape.

    Uses the same stable id scheme as the live pills (agent_runtime
    ``_collect_tool_calls`` and chat.py's bridge) so the restored run tree and
    the persisted tool timeline agree.
    """
    tool = str(d.get("tool", "unknown"))
    label = d.get("label", tool)
    status = d.get("status", "running")
    iteration = d.get("iteration", "")
    args_str = str(d.get("tool_args", ""))
    args_hash = "-" + hashlib.md5(args_str.encode()).hexdigest()[:6] if args_str else ""
    tc_id = f"tc-{tool}-iter{iteration}{args_hash}"
    agent = d.get("agent") or None
    latency_ms = d.get("latency_ms", "")
    try:
        duration = int(latency_ms) if latency_ms not in (None, "") else None
    except (TypeError, ValueError):
        duration = None
    return {
        "id": tc_id,
        "name": tool,
        "label": label if label else tool,
        "status": status,
        "input": args_str,
        "output": _visible_tool_output(tool, agent, str(d.get("output", ""))),
        "duration": duration,
        "iteration": iteration,
        "todoId": d.get("todo_id") or None,
        "reasoning": d.get("reasoning") or d.get("thought"),
        "agent": agent,
        "provider": d.get("provider") or None,
    }


def _lifecycle_phase(evt_type: str, d: dict, next_id) -> Optional[dict]:
    """Build an AgentPhase entry for a RUN-lifecycle obs event.

    Attached to the parent run's ``phases`` (Agents tab, inside the active
    agent node) — mirrors the frontend's buildAgentPhase cases for the same
    event types. ``next_id(prefix)`` is a per-build counter (deterministic ids
    like build_agent_phases). Returns None for events with nothing useful.
    """
    ts = _now_ms()
    iteration = d.get("iteration") if d.get("iteration") not in (None, "") else None
    if evt_type == "agent_initialization_start":
        return {
            "id": next_id("init-start"),
            "type": "initializing",
            "label": "Getting started — understanding your request",
            "timestamp": ts,
        }
    if evt_type == "agent_initialization_understanding":
        text = str(d.get("understanding", "")).strip() or None
        if not text:
            return None
        return {
            "id": next_id("understanding"),
            "type": "understanding",
            "label": "Understanding your request",
            "detail": text[:160],
            "timestamp": ts,
        }
    if evt_type == "agent_initialization_ack":
        text = str(d.get("acknowledgement", "")).strip() or None
        if not text:
            return None
        return {
            "id": next_id("ack"),
            "type": "acknowledged",
            "label": "Acknowledged",
            "detail": text[:160],
            "timestamp": ts,
        }
    if evt_type == "agent_initialization_done":
        mode = str(d.get("mode", ""))
        return {
            "id": next_id("init-done"),
            "type": "initialized",
            "label": (
                f"Understood — {mode} mode" if mode else "Understood the request"
            ),
            "detail": str(d.get("objective", ""))[:160] or None,
            "timestamp": ts,
        }
    if evt_type == "agent_planning_done":
        return {
            "id": next_id("planned"),
            "type": "planned",
            "label": "Plan ready — proceeding step by step",
            "timestamp": ts,
            "iteration": iteration,
        }
    if evt_type == "agent_thinker_start":
        return {
            "id": next_id("thinking"),
            "type": "thinking",
            "label": "Working out the approach",
            "timestamp": ts,
            "iteration": iteration,
        }
    if evt_type == "agent_thinker_done":
        return {
            "id": next_id("think-done"),
            "type": "thinking_done",
            "label": "Approach ready",
            "timestamp": ts,
            "iteration": iteration,
        }
    if evt_type == "agent_loop_start":
        return {
            "id": next_id("working"),
            "type": "working",
            "label": "Working — executing the plan",
            "timestamp": ts,
            "iteration": iteration,
        }
    if evt_type == "agent_loop_done":
        direct = bool(d.get("direct"))
        clarification = bool(d.get("clarification"))
        hit_limit = bool(d.get("hit_limit"))
        detail_parts = []
        if direct:
            detail_parts.append("answered directly")
        if clarification:
            detail_parts.append("asked for clarification")
        if hit_limit:
            detail_parts.append("iteration limit reached")
        try:
            iterations = int(d.get("iterations", 0) or 0)
        except (TypeError, ValueError):
            iterations = 0
        if iterations:
            detail_parts.append(f"{iterations} iterations")
        return {
            "id": next_id("turn-done"),
            "type": "turn_done",
            "label": "Turn complete",
            "detail": "; ".join(detail_parts) if detail_parts else None,
            "timestamp": ts,
            "iteration": iteration,
        }
    return None


def build_run_tree(
    collector: ObsCollector,
    *,
    task: str,
    root_id: str = "parent",
    started_at: Optional[int] = None,
    completed_at: Optional[int] = None,
    root_error: Optional[str] = None,
) -> list[dict]:
    """Rebuild the Agent Workspace run tree from the request's obs events.

    Mirrors the frontend: the parent root is created with the user's task,
    child runs are created on ``delegation_started`` (keyed by run_id),
    child statuses settle on ``delegation_completed``, tool_call events attach
    to the owning run (a child by its ``agent`` tag, else the parent),
    ``evidence_to_parent`` entries land on the parent run, and RUN-lifecycle
    obs events (initialization/planning/thinker/loop) append phase entries to
    the parent run's ``phases`` so the active agent node narrates the turn.
    """
    runs: list[dict] = [
        {
            "id": root_id,
            "name": "parent",
            "role": "parent",
            "task": task,
            "status": "failed" if root_error else "completed",
            "depth": 0,
            "startedAt": started_at if started_at is not None else _now_ms(),
            "completedAt": completed_at if completed_at is not None else _now_ms(),
            "error": root_error,
            "tools": [],
            "phases": [],
        }
    ]
    by_id: dict[str, dict] = {root_id: runs[0]}
    # agent name -> most recent run id for that agent (child tool_call events
    # carry `agent` but not run_id; the frontend matches by name + running).
    child_by_agent: dict[str, str] = {}
    # Deterministic phase ids within one build (same pattern as
    # build_agent_phases) so the persisted run tree survives reload.
    _phase_counter = {"n": 0}

    def _next_id(prefix: str) -> str:
        _phase_counter["n"] += 1
        return f"phase-{prefix}-{_phase_counter['n']}"

    def _attach_tool(tc: dict) -> None:
        run_id = tc.get("runId")
        if not run_id and tc.get("agent"):
            agent = tc["agent"]
            if agent in child_by_agent and child_by_agent[agent] in by_id:
                run_id = child_by_agent[agent]
            else:
                for run in reversed(runs):
                    if run.get("role") != "parent" and run.get("name") == agent and run.get("status") == "running":
                        run_id = run["id"]
                        break
        target = by_id.get(run_id or root_id) or runs[0]
        tools: list[dict] = target.setdefault("tools", [])
        for i, existing in enumerate(tools):
            if existing.get("id") == tc.get("id"):
                # Merge but never clobber a present value with a missing one
                # (e.g. the started event carries the reasoning, the done
                # event may omit it) — only non-empty fields win.
                tools[i] = {
                    **existing,
                    **{k: v for k, v in tc.items() if v not in (None, "")},
                }
                return
        tools.append(tc)

    for evt in collector.history():
        d = evt.data
        if evt.type == "tool_call":
            _attach_tool(_tool_call_dict(d))
        elif evt.type == "delegation_started":
            agent = str(d.get("target_agent", "sub-agent"))
            run_id = str(d.get("run_id") or f"child-{agent}")
            if run_id not in by_id:
                runs.append(
                    {
                        "id": run_id,
                        "name": agent,
                        "role": "child",
                        "parentId": root_id,
                        "task": str(d.get("task", "")),
                        "status": "running",
                        "depth": int(d.get("depth", 1)),
                        "startedAt": _now_ms(),
                        "tools": [],
                    }
                )
                by_id[run_id] = runs[-1]
            child_by_agent[agent] = run_id
        elif evt.type == "delegation_completed":
            run_id = str(d.get("run_id") or "")
            target = by_id.get(run_id)
            if target is None:
                # Fallback: match by agent name like the frontend does.
                agent = str(d.get("target_agent", ""))
                for run in reversed(runs):
                    if run.get("name") == agent:
                        target = run
                        break
            if target is None:
                continue
            raw_status = str(d.get("status", ""))
            status = (
                "completed" if raw_status == "completed"
                else "timed_out" if raw_status == "timed_out"
                else "failed"
            )
            target["status"] = status
            target["completedAt"] = _now_ms()
            if d.get("error_type"):
                target["error"] = str(d["error_type"])
        elif evt.type == "evidence_to_parent":
            parent = runs[0]
            evidence = parent.setdefault("evidence", [])
            evidence.append(
                {
                    "tool": str(d.get("tool", "unknown")),
                    "iteration": int(d.get("iteration", 0) or 0),
                    "evidenceChars": int(d.get("evidence_chars", 0) or 0),
                    "failed": bool(d.get("failed")),
                    "timestamp": _now_ms(),
                }
            )
        elif evt.type in RUN_LIFECYCLE_TYPES:
            # The classify call names the turn ("Fetch Weather"); carry it onto
            # the parent node so the reloaded run tree heads the turn the same
            # way the live UI does (no extra model call — rides this event).
            if evt.type == "agent_initialization_done":
                _title = str(d.get("title", "")).strip()
                if _title:
                    runs[0]["title"] = _title[:40]
            phase = _lifecycle_phase(evt.type, d, _next_id)
            if phase:
                # Child lifecycle events carry an `agent` tag (forwarded by
                # ChildObsProxy) — attach to that child run; untagged events
                # belong to the parent.
                agent = str(d.get("agent") or "")
                target = runs[0]
                if agent:
                    for run in reversed(runs):
                        if run.get("role") != "parent" and run.get("name") == agent:
                            target = run
                            break
                target.setdefault("phases", []).append(phase)
    # Canonical narrative order per run (the loop emits some events out of
    # story order — stable sort by rank).
    for run in runs:
        phases = run.get("phases")
        if phases:
            run["phases"] = sorted(
                phases, key=lambda p: _LIFECYCLE_PHASE_RANK.get(p.get("type"), 99)
            )
    return runs


def build_workspace_artifacts(
    collector: ObsCollector,
    *,
    task: str,
    root_error: Optional[str] = None,
) -> tuple[Optional[list], Optional[list]]:
    """Build the run tree + phase strip for persistence with a message.

    Returns (agent_runs, agent_phases); both are None when there is nothing
    worth restoring. The run tree is only persisted when it has actual content
    (tools, evidence, children, or an error) — a bare parent-only node for a
    trivial chat turn would override the last interesting turn's tree on the
    Agents tab after reload.
    """
    runs = build_run_tree(collector, task=task, root_error=root_error)
    root = runs[0]
    has_content = bool(
        root_error
        or root.get("tools")
        or root.get("evidence")
        or root.get("phases")
        or len(runs) > 1
    )
    agent_runs = runs if has_content else None
    agent_phases = build_agent_phases(collector) or None
    return agent_runs, agent_phases


def build_agent_phases(collector: ObsCollector) -> list[dict]:
    """Rebuild the phase-strip entries from the request's obs events.

    Mirrors the frontend's buildAgentPhase: each of the 8 phase
    event types becomes one AgentPhase entry; events missing required fields
    are skipped. Ids are deterministic (``phase-<type>-<n>``) so the persisted
    strip survives reload without re-randomization.
    """
    phases: list[dict] = []
    counter = 0

    def _next_id(prefix: str) -> str:
        nonlocal counter
        counter += 1
        return f"phase-{prefix}-{counter}"

    for evt in collector.history():
        d = evt.data
        ts = _now_ms()
        iteration = (
            d.get("iteration")
            if d.get("iteration") not in (None, "")
            else None
        )
        # Lifecycle narration (initialization/planning/thinker/loop) lives on
        # the RUN tree (build_run_tree phases), not the chat strip — the strip
        # keeps the plan/gate/orchestrator/failure decision
        # history only.
        if evt.type == "plan_nodes_created":
            try:
                count = int(d.get("node_count", 0) or 0)
            except (TypeError, ValueError):
                count = 0
            if not count:
                continue
            ids = _as_list(d.get("node_ids"))
            phases.append(
                {
                    "id": _next_id("plan"),
                    "type": "plan_created",
                    "label": f"Plan built — {count} step{'' if count == 1 else 's'}",
                    "detail": " → ".join(str(i) for i in ids) if ids else None,
                    "timestamp": ts,
                }
            )
        elif evt.type == "plan_node_advanced":
            node_id = str(d.get("node_id", ""))
            if not node_id:
                continue
            new_status = str(d.get("new_status", ""))
            subgoal = str(d.get("subgoal", ""))[:100]
            status_icon = (
                "✓" if new_status == "completed"
                else "✗" if new_status == "failed"
                else "~"
            )
            phases.append(
                {
                    "id": _next_id("adv"),
                    "type": "node_advanced",
                    "label": f"{node_id} {status_icon} {subgoal}",
                    "detail": f"status: {new_status}" if new_status else None,
                    "timestamp": ts,
                    "iteration": iteration,
                }
            )
        elif evt.type == "agent_loop_gate_passed":
            intent = str(d.get("intent", ""))
            phases.append(
                {
                    "id": _next_id("gate-pass"),
                    "type": "gate_passed",
                    "label": (
                        f"Verified — {intent} acceptance gate passed"
                        if intent
                        else "Verified — acceptance gate passed"
                    ),
                    "timestamp": ts,
                    "iteration": iteration,
                }
            )
        elif evt.type == "agent_loop_gate_failed_replan":
            intent = str(d.get("intent", ""))
            unmet = [str(u) for u in _as_list(d.get("unmet"))]
            phases.append(
                {
                    "id": _next_id("gate-fail"),
                    "type": "gate_failed_replan",
                    "label": (
                        f"Replanning — {intent} criteria unmet"
                        if intent
                        else "Replanning — acceptance criteria unmet"
                    ),
                    "detail": f"Unmet: {'; '.join(unmet[:3])}" if unmet else None,
                    "timestamp": ts,
                    "iteration": iteration,
                }
            )
        elif evt.type == "orchestrator_replan_start":
            intent = str(d.get("intent", ""))
            phases.append(
                {
                    "id": _next_id("orch-start"),
                    "type": "orchestrator_replan_start",
                    "label": (
                        f"Orchestrator notified — {intent} failure"
                        if intent
                        else "Orchestrator notified of failure"
                    ),
                    "timestamp": ts,
                    "iteration": iteration,
                }
            )
        elif evt.type == "orchestrator_replan_done":
            try:
                confidence = float(d.get("confidence", 0) or 0)
            except (TypeError, ValueError):
                confidence = 0.0
            intent = str(d.get("intent", ""))
            phases.append(
                {
                    "id": _next_id("orch-done"),
                    "type": "orchestrator_replan_done",
                    "label": (
                        f"Orchestrator replanned — {intent}, confidence {confidence:.2f}"
                        if intent
                        else f"Orchestrator replanned — confidence {confidence:.2f}"
                    ),
                    "timestamp": ts,
                }
            )
        elif evt.type == "orchestrator_replan_failed":
            error = str(d.get("error", ""))
            phases.append(
                {
                    "id": _next_id("orch-fail"),
                    "type": "orchestrator_replan_failed",
                    "label": "Orchestrator replan failed (non-fatal — using fallback)",
                    "detail": f"Error: {error[:120]}" if error else None,
                    "timestamp": ts,
                }
            )
        elif evt.type == "agent_loop_failure":
            reason = str(d.get("reason") or d.get("failure_type") or "")
            phases.append(
                {
                    "id": _next_id("fail"),
                    "type": "agent_loop_failure",
                    "label": "Agent loop terminated",
                    "detail": f"Reason: {reason[:120]}" if reason else None,
                    "timestamp": ts,
                }
            )
    return phases
