"""
AgentLoop — native tool/function calling via Ollama's API.

The main orchestration class for agent-mode responses.  Instead of forcing
the model to output fragile JSON like {"finish": {"answer": "..."}}, we use
Ollama's native tool calling API (chat_with_tools) which handles the
structured interaction for us.

v0.9 changes vs v0.8:
- Feature: Plan→Execute→Verify workflow — a planning LLM call runs before
  the main loop, producing a step-by-step plan that gets injected into the
  execution-phase system prompt. This eliminates trial-and-error iterations
  where the model fumbles with incomplete tool args.
- Feature: Post-execution verification — after file_write, the file is read
  back to confirm it was written correctly. After code_exec, the output is
  checked for common error indicators.
- Raised MAX_ITERATIONS to 8 (from 5) to accommodate the new phases.
- System prompt now includes plan context from the planning phase.
- Reduced wasted iterations: typical "Create X" tasks now complete in 2-3
  iterations instead of 5.

v0.8 changes vs v0.7:
- Fix: Duplicate tool entries — emit single tool_call obs event per iteration
  with a stable ID (tool_name + iteration), so frontend can match started/done
- Fix: Empty labels — build labels from structured tool_args (path, command,
  query) instead of raw concatenated tool_input string
- Fix: OS/shell awareness — inject _build_environment_context() into the
  agent system prompt so the model knows it's on Windows/Linux/macOS
- Feature: Tool arg validation — reject tool calls with missing required args
  before dispatching, giving the model a clear error message to self-correct

v0.7 changes vs v0.6:
- Bug A fix: file_write called without content now yields StreamChunk
  informing user about redirect to file_task (previously silent redirect)
- Bug B fix: Enhanced dedup cache works at tool_name level for file_write
- New tool: edit_file — in-place file editing

v0.6 changes vs v0.5 (JSON-parsing loop):
- Uses adapter.chat_with_tools() for native tool calling
- MAX_ITERATIONS raised to 5 (from 3)
- Deduplication and allowlist validation preserved
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from types import SimpleNamespace
from typing import AsyncIterator, Optional

from adapters.ollama import MultiToolCallResult, ToolCallResult
from core.agent.agent_filters import (
    _filter_code_output,
    _filter_system_leaks,
    _filter_tool_injection,
)
from core.agent.constants import (
    AGENT_ALLOWED_TOOLS,
    AGENT_INTENTS,
    CLARIFICATION_THRESHOLD,
    INTENT_TOOL_SCOPES,
    MAX_ITERATIONS,
    MAX_WALL_CLOCK_SECS,
    OBS_LOG_MAX_CHARS,
    PER_CALL_TIMEOUT_SECS,
    PLAN_ENABLED,
    PLAN_TIMEOUT_SECS,
    REASONING_MAX_WALL_CLOCK_SECS,
    REASONING_PER_CALL_TIMEOUT_SECS,
    REASONING_PLAN_TIMEOUT_SECS,
    SYNTHESIS_ENABLED,
    SYNTHESIS_TIMEOUT_SECS,
    VERIFY_CODE_EXEC,
    VERIFY_ENABLED,
    VERIFY_FILE_WRITE,
    WORKSPACE_STATE_ENABLED,
)

# Session 129 decomposition: the plan-parsing / MiniMax-DSML interception /
# tool-talk / tool-input helpers below moved to core.agent.text_tools and are
# re-imported here for backward compatibility (tests import them from
# core.agent.loop).
from core.agent.delegation import (
    InlineMutationScope,
    set_inline_mutation_scope,
    snapshot_messages,
    validate_rewritten_history,
)
from core.agent.init_stream import (
    InitializationPreview,
    extract_preview,
    render_understanding,
)
from core.agent.initialization import (
    InitializationDecision,
    build_initialization_prompt,
    parse_initialization,
)
from core.agent.models import AgentStep, AgentTrace
from core.agent.prompts import build_agent_system_prompt, build_planning_prompt
from core.agent.synthesizer import AnswerSynthesizer
from core.agent.task_state import TaskState
from core.agent.text_tools import (
    _MAX_TOOL_TALK_RECOVERIES,
    _MINIMAX_PARTIAL_RE,
    _STANDALONE_PARTIAL_RE,
    _extract_tool_input,
    _has_minimax_tool_call,
    _is_filler_step,  # noqa: F401 — re-exported for backward compat (Session 129)
    _is_tool_talk,
    _normalize_dsml,
    _normalize_system_tool_call,
    _parse_minimax_tool_call,
    _parse_plan_steps,
    _strip_minimax_tool_calls,
    _strip_minimax_tool_calls_stream,
    _truncate_observation,
)
from core.agent.tool_dispatch import dispatch_with_retry
from core.agent.tool_schemas import TOOL_DEFINITIONS, tool_defs_for_call
from core.context_builder import _build_environment_context
from core.context_compactor import simplify_tool_results
from core.models import AgentAbortedError, Intent, StreamChunk, ToolResult
from core.workspace_state import format_snapshot, mark_turn_start
from core.workspace_state import snapshot as workspace_snapshot

logger = logging.getLogger(__name__)


class TerminalProviderError(RuntimeError):
    """A provider error that must terminate the current turn immediately."""

    def __init__(self, raw: str):
        self.raw = str(raw)
        super().__init__(self.raw)


# Tool definitions live in core.agent.tool_schemas (ADR-40 lean schemas) — the
# single source of truth for the native `tools` param and the in-prompt list.


# ── Helpers ────────────────────────────────────────────────────────────────────


def _reasoning_setting(name: str, fallback: float) -> float:
    """Return a user-tunable reasoning timeout from Settings when set.

    ADR-41 (Session 254): the reasoning budgets are surfaced in the Settings
    UI (settings.json) and as env vars via the pydantic Settings fields. The
    constants below remain the module-level defaults (and the test surface);
    the Settings value wins when present, since load_runtime_settings applies
    settings.json AFTER pydantic folds the env in.
    """
    try:
        from core.config import settings

        value = getattr(settings, name, None)
        if value:
            return float(value)
    except Exception:
        pass
    return fallback


def _plan_timeout_for(active_adapter) -> float:
    """Return the plan/init stream timeout, scaled for thinking models and
    slow local providers.

    ADR-41 (Session 254): with thinking enabled the model reasons before
    emitting the plan JSON, so the 8s PLAN_TIMEOUT_SECS can fire mid-thought
    (observed live: "initialization timed out after 8s" with GLM-4.5-Flash
    thinking ON). Use the larger REASONING_PLAN_TIMEOUT_SECS budget for
    thinking models.

    Session 289 (slow local providers): the parent initialization is
    classify-only for a fast model, but for a slow local model (Ollama) the
    init call must GENERATE the whole `direct` decision — including the
    greeting `response` itself — before the stream ends. At CPU token rates
    (phi4-mini observed at ~0.17 tok/s) even a 30-token reply exceeds the 30s
    plan budget, so the init timed out, `parse_initialization("")` fell open to
    EXECUTE, and a plain "Hi" cascaded into the full tool loop (5K-token
    prompt) and burned the whole wall-clock. A slow provider therefore needs
    the same generous chat budget the per-call timeout already grants it — the
    init is effectively a full generation, not a quick plan. Floored at the
    reasoning plan budget so it never shrinks below the thinking-model window.
    The parent loop's wall-clock cap still bounds total turn time.
    """
    if getattr(active_adapter, "thinking_enabled", False):
        return _reasoning_setting("localmind_reasoning_plan_timeout_secs", REASONING_PLAN_TIMEOUT_SECS)
    if getattr(active_adapter, "slow_provider", False):
        plan_budget = _reasoning_setting("localmind_reasoning_plan_timeout_secs", REASONING_PLAN_TIMEOUT_SECS)
        try:
            from core.config import settings as _settings

            chat_budget = float(getattr(_settings, "ollama_timeout_chat", 0) or 0)
        except Exception:
            chat_budget = 0.0
        return max(plan_budget, chat_budget)
    return PLAN_TIMEOUT_SECS


def _per_call_timeout_for(active_adapter) -> float:
    """Return the per-iteration LLM-call timeout, scaled for thinking models
    and slow local providers.

    ADR-41 (Session 254): a reasoning model with thinking enabled streams
    many thinking tokens before its answer — a fixed 45s cap would truncate
    mid-thought on a slow free tier. Use the larger reasoning budget (tunable
    via Settings UI / env) when the adapter reports thinking_enabled.

    Session 288 (slow local providers): a local Ollama model has the same
    truncation problem for a different reason — its token rate is low (often
    <1-2 tok/s on CPU/small GPUs), so a legitimately short reply can exceed
    45s. The generic cap even preempted the operator-tuned ollama_timeout_chat
    HTTP timeout entirely (observed live: phi4-mini "Hi" timed out at 45s on
    a 55.8s / 37-token generation). Honor that chat budget for slow providers,
    floored at the generic cap so it never shrinks below a cloud call's window.
    """
    if getattr(active_adapter, "thinking_enabled", False):
        return _reasoning_setting("localmind_reasoning_timeout_secs", REASONING_PER_CALL_TIMEOUT_SECS)
    if getattr(active_adapter, "slow_provider", False):
        try:
            from core.config import settings as _settings

            _chat = float(getattr(_settings, "ollama_timeout_chat", 0) or 0)
        except Exception:
            _chat = 0.0
        if _chat > 0:
            return max(PER_CALL_TIMEOUT_SECS, _chat)
    return PER_CALL_TIMEOUT_SECS


def _user_message_text(messages: list[dict]) -> str:
    """Return the latest user-role message text (for the TaskState objective).

    Skips injected acceptance-gate blocks so repeated replans keep the
    ORIGINAL task framing instead of degrading to a previous gate message.
    """
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            content = str(msg.get("content", ""))
            if "[ACCEPTANCE GATE]" in content:
                continue
            return content[:200]
    return ""


def _thinker_context_block(analysis) -> str:
    """Render a Thinker analysis (ADR-42) into a compact block the loop injects
    so the model's NEXT action is shaped by the reasoning-on-evidence — facts
    to build on, ambiguities to resolve on their default (ADR-36: proceed, do
    not block), and the suggested next step."""
    parts = ["[Your analysis of the evidence so far — reason from this, do not repeat it to the user]"]
    if analysis.facts:
        parts.append("Known: " + "; ".join(analysis.facts))
    if analysis.ambiguities:
        parts.append(
            "Unresolved (proceed on the default unless it risks a wrong irreversible action): "
            + "; ".join(f"{a.text} → {a.default or 'pick the most reasonable option'}" for a in analysis.ambiguities)
        )
    if analysis.next_step:
        parts.append("Next step: " + analysis.next_step)
    return "\n".join(parts)


def _thinker_user_summary(analysis) -> str:
    """Render a Thinker analysis (ADR-42) as USER-facing text for the
    degraded-evidence fallback (B-2026-08-16-12).

    Distinct from `_thinker_context_block`, which addresses the MODEL's next
    action; this is the already-computed intermediate synthesis the user can
    read when the final model call fails after successful tool work. Facts
    first (the concrete findings), then the next step the Thinker planned.
    """
    # No self-header: the degraded fallback intro already announces the block
    # ("Here's what I'd already worked out from the evidence…"), so repeating
    # it here would read twice. The bullets + next-step stand on their own.
    parts = []
    if analysis.facts:
        parts.extend(f"  • {f}" for f in analysis.facts)
    if getattr(analysis, "next_step", "") and str(analysis.next_step).strip():
        parts.append(f"Next step I was taking: {analysis.next_step}")
    return "\n".join(parts)


def _filtered_tool_defs(allowed_tools: Optional[frozenset[str]] = None) -> list[dict]:
    """Return TOOL_DEFINITIONS filtered to the allowed tool set.

    Args:
        allowed_tools: optional scoped toolset (from an AgentConfig). When
            provided, only tools whose name is in this set are returned.
            When None (the default), filters to AGENT_ALLOWED_TOOLS (the
            global allowlist) — preserving the pre-ADR-6 behavior.
    """
    allowed_names = allowed_tools if allowed_tools is not None else AGENT_ALLOWED_TOOLS
    return [td for td in TOOL_DEFINITIONS if td["function"]["name"] in allowed_names]


def _note_described_tool(tool_name: str, tool_result, loaded_tools: set[str]) -> None:
    """Record a long-tail tool loaded via describe_tool (ADR-40 option C).

    Called right after ANY dispatch whose tool was describe_tool. The loaded
    name is carried in ``ToolResult.metadata`` (NOT a contextvar) because
    dispatch_with_retry runs tools inside asyncio.wait_for — a child task
    whose contextvar writes would be lost to the loop. The name then appears
    in the next iteration's native ``tools`` param (via tool_defs_for_call).
    """
    if tool_name != "describe_tool" or tool_result is None or not tool_result.success:
        return
    metadata = tool_result.metadata or {}
    loaded = metadata.get("loaded_tool")
    if not loaded and metadata.get("already_loaded"):
        # Core tools historically expose `already_loaded` + `tool_name`
        # without a `loaded_tool` field. Bootstrap mode still needs to add
        # that schema to the next native call, so infer it at the loop seam
        # rather than changing the public ToolResult shape.
        loaded = metadata.get("tool_name")
    if loaded:
        loaded_tools.add(loaded)
        logger.info("[agent.loop] describe_tool loaded %r for this run", loaded)


def _emit_todo_write_events(tool_name: str, tool_result, obs) -> None:
    """Turn a ``todo_write`` result into the todo_* obs events the UI renders.

    Tools can't reach the request's ObsCollector (they run inside
    ``asyncio.wait_for`` — the same boundary that makes ``_note_described_tool``
    use metadata, not a contextvar), so ``todo_write`` returns the normalized
    list in ``metadata["todos"]`` and the loop emits here. A full replace
    (clear + one create per item) mirrors the plan-todo emission, so the agent's
    checklist becomes the live Todos panel — create, update status, and mark
    complete, all under the agent's control (ADR-43).
    """
    if tool_name != "todo_write" or obs is None or tool_result is None or not tool_result.success:
        return
    todos = (tool_result.metadata or {}).get("todos")
    if todos is None:
        return
    obs.emit("todo_cleared")
    for t in todos:
        obs.emit(
            "todo_created",
            id=t.get("id", ""),
            text=t.get("text", ""),
            completed=bool(t.get("completed", False)),
            status=t.get("status", "pending"),
        )


def _tool_provider(tool_result) -> Optional[str]:
    """Surface which backend engine a tool used, for the Actions-card badge.

    Generic metadata hook: any tool that wants a provider badge sets
    ``metadata["provider"]`` on its ToolResult (e.g. web_search names the
    winning engine). Falls back to web_search's established
    ``successful_provider`` key so existing metadata needs no change.
    """
    if tool_result is None or not tool_result.metadata:
        return None
    return tool_result.metadata.get("provider") or tool_result.metadata.get("successful_provider")


# Session 238 (Thinker/Agent rebuild Step 0) — forced-tool reprompt bound.
# When a tool-required turn's FIRST model call returns empty or text-without-
# tool (gemini-2.5-flash via the OpenAI-compat endpoint, Session 237 trace),
# the loop reprompts once with a forced-tool nudge instead of failing the
# turn. The nudge is gated to iteration 0 (the first tool call), so this
# counter is a hard ceiling documenting the bound; if the gate is ever
# relaxed, the counter still caps the retries.
_MAX_TOOL_FORCE_RECOVERIES = 2

# ADR-41 follow-up (Session 256) — empty-but-reasoned retry bound.
# With thinking re-enabled (z.ai/GLM), a slow free tier sometimes streams a
# long reasoning burst and then returns NO content and NO tool call — the
# model "thought but didn't act" (live user bug: iter-1 ran shell
# Get-ChildItem, iter-2 streamed reasoning then went empty, and the whole
# turn failed with empty_response). The reasoning is real progress; one
# bounded retry with a nudge recovers the turn. Two consecutive empties
# still fail fast — the think-only protection from the original disable
# stays intact (this + the Phase-1 500-chunk reasoning cap bound it).
_MAX_EMPTY_REASONING_RECOVERIES = 2

# B-2026-08-20-7 / Session 310: parent turns get a higher recovery cap. Live
# traces on z.ai/glm-4.5-flash (Sessions 306-308) showed the model frequently
# hits empty-response-after-reasoning on multiple iterations of a single
# tool-bearing turn — the cap of 2 was exhausted before the model could
# complete the turn, leaving only the post-loop synthesis to produce an answer.
# Raising the parent cap to 3 gives weak models one more recovery attempt,
# which is often the difference between "model ran tools and synthesized a
# real answer itself" vs "harness had to synthesize from evidence." The
# non-parent cap stays at 2 (don't loosen legacy/child paths). The hard
# upper bound (3) + the iteration cap (MAX_ITERATIONS) + the post-loop
# synthesis together bound the turn — no infinite-loop risk.
_MAX_EMPTY_REASONING_RECOVERIES_PARENT = 3


# Session 192 — same-tool replan bound. After this many CONSECUTIVE
# failures on the SAME tool, the acceptance gate stops replanning and
# reports honestly instead of looping. Root of the Session 191 death
# spiral: "find my CV" replanned to the same failing shell tool 15+
# times (confidence 0.30) for 480s — a tool failing twice in a row
# means the APPROACH is wrong; retrying it a third time is not a plan
# change, it's a loop. A different tool (or a success) resets the
# streak, so legitimate strategy pivots are never blocked.
_SAME_TOOL_REPLAN_CAP = 2

# B-2026-08-18-3 — repetition nudge bound. A model can spin on a tool that keeps
# SUCCEEDING but isn't advancing (the "current weather Kitengela" transcript: 3
# web_searches all returned results, none useful, then an empty synthesis). The
# failure streak above never catches this because the tool didn't fail. After
# this many CONSECUTIVE calls to the same tool (pass OR fail), the loop nudges
# ONCE to reflect and change approach or answer with what it has — soft, not a
# forced stop, so a task that legitimately needs repeated same-tool calls (e.g.
# reading several files) is not blocked; the iteration/wall-clock caps remain the
# hard bound.
_SAME_TOOL_REPETITION_NUDGE_CAP = 3


def same_tool_failure_streak(trace) -> tuple[int, str]:
    """Count CONSECUTIVE same-tool failures at the end of a trace.

    Returns (streak, tool_name). The streak only counts the TRAILING
    run of failed steps that used the same tool — a success, or a
    different tool, breaks it (that is a strategy change, which the
    gate must keep allowing). Tool-less reasoning iterations do not
    break the streak: the model "thinking" between failures of the
    same tool is still the same failing approach.
    """
    steps = getattr(trace, "steps", []) or []
    streak = 0
    last_tool = ""
    for step in reversed(steps):
        tool = getattr(step, "tool_name", "") or ""
        failed = bool(getattr(step, "tool_failed", False))
        if not tool:
            continue
        if failed and (not last_tool or tool == last_tool):
            streak += 1
            last_tool = tool
        else:
            break
    return streak, last_tool


# ── Tool-error recovery (spec §17 self-correction, §28 error handling) ────────
# ROOT FIX (B-2026-08-18-9): when a tool FAILS, the loop used to surface only
# "[Tool 'X' returned error_type='...']" and leave recovery to the model — which
# a weak model can't reliably do, so the turn dead-ended (empty_response). Every
# tool error now carries a concrete, model-AGNOSTIC next step keyed on its error
# CLASS. This is the GENERAL recovery path the per-tool patches were approximating
# (code_exec→shell, etc.); the harness classifies + directs for every tool and
# every error, instead of hoping the model reads a raw error. The structural
# guards still bound it: dispatch_with_retry never retries permission errors, and
# `same_tool_failure_streak` (CAP=2) forces an honest stop on a repeated failure.

# error_type → recovery class (spec §28). Names cover every error_type emitted by
# the tools + contracts (grep error_type= across backend/src/tools + core/agent).
_ERR_PERMISSION = frozenset({
    "permission", "permission_denied", "invalid_action", "unknown_operation",
    "unknown_action", "ssrf_blocked", "inline_mutation_not_allowed",
    "registry_unavailable", "adapter_unavailable",
})
_ERR_INPUT = frozenset({
    "invalid_input", "validation_error", "missing_arg", "missing_ref",
    "missing_field", "parse_error", "binary_content", "construction_failed",
    "nl_command_rejected",
})
_ERR_NORESULT = frozenset({"not_found", "empty", "io_error", "http_error", "network", "challenge"})
_ERR_TRANSIENT = frozenset({"timeout", "rate_limit"})
_ERR_STOP = frozenset({"wall_clock_cap", "recursion_limit"})


def tool_error_recovery_directive(tool_name: str, error_type: str) -> str:
    """A concrete, model-agnostic recovery step for a failed tool, by error class.

    Never empty — every failure gets an actionable next step, so no tool error is
    a dead end the model just gives up on.
    """
    et = (error_type or "").strip().lower()
    if et in _ERR_PERMISSION:
        return (
            f"`{tool_name}` is not available or not permitted, so calling it again will fail the "
            "same way. Take a DIFFERENT approach (another tool or a different plan). If nothing "
            "available can do this, tell the user it can't be done here — do not claim success."
        )
    if et in _ERR_INPUT:
        return (
            f"The input to `{tool_name}` was rejected as invalid. Read the message above for what "
            f"it expects, then EITHER call `{tool_name}` again with corrected input, OR use the tool "
            "that actually fits this step. Do not repeat the identical call."
        )
    if et in _ERR_NORESULT:
        return (
            f"`{tool_name}` did not return a usable result. Try a different query, source, or tool. "
            "If the information genuinely isn't available, say so honestly — do not invent an answer."
        )
    if et in _ERR_TRANSIENT:
        return (
            f"`{tool_name}` hit a transient failure ({et}). Retry ONCE (smaller/simpler if possible); "
            "if it fails again, continue with what you have or try another approach."
        )
    if et in _ERR_STOP:
        return (
            "A hard limit was reached. Stop calling tools and give the best honest answer you can "
            "from the evidence gathered so far."
        )
    # git_error, internal_error, child_exception, parse-anything-else, unknown.
    return (
        f"`{tool_name}` failed ({et or 'error'}). Check the message above, then try a corrected call "
        "or a different tool/approach. If you cannot complete this step, report the actual state "
        "honestly — never claim success you didn't verify."
    )


def same_tool_repetition_streak(trace) -> tuple[int, str]:
    """Trailing run of consecutive calls to the SAME tool, regardless of
    pass/fail (B-2026-08-18-3).

    Returns (streak, tool_name). Unlike `same_tool_failure_streak`, a SUCCESS
    does not break the streak — this catches a model spinning on a tool that
    keeps succeeding but isn't advancing (e.g. repeated web_searches that return
    results but never the answer). A DIFFERENT tool breaks it (a real strategy
    change); tool-less reasoning steps don't.
    """
    steps = getattr(trace, "steps", []) or []
    streak = 0
    last_tool = ""
    for step in reversed(steps):
        tool = getattr(step, "tool_name", "") or ""
        if not tool:
            continue
        if not last_tool or tool == last_tool:
            streak += 1
            last_tool = tool
        else:
            break
    return streak, last_tool


def parent_completion_floor_note(trace) -> Optional[str]:
    """The parent's deterministic completion-verification FLOOR (B-2026-08-18-2,
    review-66): the missing VERIFY→DONE segment of the spec's wheel.

    On the user-facing parent path the turn carries no explicit success-criteria
    contract (the parent runs a generic ANALYZE intent, `GoalInterpreter` is not
    wired, and the F4 post-execution verifier is skipped for non-high-stakes
    intents), so `_acceptance_gate_at_final_answer` used to accept the model's
    "done" on its word alone — even when the parent's last real action FAILED
    (spec §29/§30: "action succeeded" ≠ "objective succeeded").

    This closes that hole. When the parent's LAST executed tool is high-stakes
    (file_write/file_edit/shell/code_exec — file_write also has its own read-back
    grounding), the action is judged failed if EITHER (a) the dispatcher set
    `tool_failed` (tool-level failure: permission, internal error), OR (b) the
    reused F4 checker `verify_last_tool_succeeded` finds error markers in its
    observation (command-level failure: a nonzero-exit shell command or a
    code_exec exception, which `shell.py` returns as content with success=True —
    so `tool_failed` alone would MISS it). Returns a note on failure so the gate
    rejects "done" and recovers; None otherwise → read/analysis/search turns and
    genuinely successful actions are unchanged.

    Tradeoff (identical to the already-shipped F4 verifier this reuses): the
    observation check keys on error markers, so a high-stakes action whose
    legitimate output contains "error"/"failed" could be false-rejected; the
    `_SUCCESS_RE` override in `verify_last_tool_succeeded` covers the common
    passing-build case, and the same-tool-streak + iteration caps bound any
    spurious replan to an honest stop.
    """
    from core.agent.post_execution_verifier import (
        is_high_stakes_intent,
        verify_last_tool_succeeded,
    )

    # Judge only the LAST tool the parent actually ran; a preceding failure the
    # model already recovered from must not block a later legitimate "done".
    last_step = None
    for step in reversed(getattr(trace, "steps", []) or []):
        if getattr(step, "tool_name", "") or "":
            last_step = step
            break
    if last_step is None:
        return None
    name = last_step.tool_name or ""
    if not is_high_stakes_intent(name):
        return None
    if bool(getattr(last_step, "tool_failed", False)):
        return f"the last action ({name}) reported a failure"
    # Judge THIS tool step's observation — not `verify_last_tool_succeeded(trace)`,
    # which re-reads steps[-1] and would miss the failure when a tool-less
    # final-answer/reasoning step trails the real action.
    passed, note = verify_last_tool_succeeded(SimpleNamespace(steps=[last_step]))
    if not passed:
        return f"the last action ({name}) did not succeed — {note}"
    return None


# B-2026-08-20-6 — prose tool-action commitment detector (Session 307).
# Phrases that indicate the model is *preamble-ing* a tool call rather than
# answering. Matched case-insensitively as substrings. Scoped to iterations
# where no tool_call was emitted, so a legitimate prose answer that happens
# to contain "tool" is NOT false-triggered (the no-tool_call guard is the
# real predicate; these phrases only refine "is this prose a commitment?").
_PROSE_COMMITMENT_PHRASES: tuple[str, ...] = (
    "let me describe",
    "let me use",
    "let me call",
    "let me run",
    "let me first",
    "let me start by",
    "i'll describe",
    "i'll use",
    "i'll call",
    "i'll run",
    "i'll first",
    "i'll help you",  # live-trace: "I'll help you list... using the shell tool"
    "i need to describe",
    "i need to use",
    "i need to call",
    "i need to run",
    "i should describe",
    "i should use",
    "i should call",
    "i should run",
    "first, i should",
    "first, i'll",
    "first, let me",
    "i'm going to describe",
    "i'm going to use",
    "i'm going to call",
    "i'm going to run",
    "i will use the",
    "i will call the",
    "i will run the",
)

# Tool-name mentions that, combined with a commitment phrase, make the
# preamble unambiguous. A phrase alone ("let me use") is suspicious but
# could be conversational; a phrase + tool name ("let me use the shell
# tool") is a clear commitment the model failed to act on.
_TOOL_NAME_HINTS: tuple[str, ...] = (
    "shell",
    "describe_tool",
    "file_read",
    "file_write",
    "file_task",
    "file_edit",
    "web_search",
    "web_fetch",
    "code_exec",
    "calculator",
    "git",
    "todo_write",
    "memory",
    "find_path",
    "browser",
    "tool",
)


def prose_commits_to_tool_action(text: str) -> bool:
    """Detect "model committed to a tool action in prose but didn't emit one".

    Returns True when ``text`` contains BOTH a commitment phrase (e.g.
    "let me describe", "I'll use") AND a tool-name mention (e.g. "shell",
    "describe_tool", "tool"). The conjunction is required — a phrase alone
    is too easy to false-trigger on legitimate prose ("let me use an
    analogy"), and a tool name alone is common in capability questions
    ("what tools do you have?").

    Called by ``_acceptance_gate_at_final_answer`` ONLY on iterations where
    no ``tool_call`` was emitted this run, so the detector never fires on a
    turn that actually executed a tool.
    """
    if not text:
        return False
    lower = text.lower()
    has_phrase = any(phrase in lower for phrase in _PROSE_COMMITMENT_PHRASES)
    if not has_phrase:
        return False
    has_tool = any(hint in lower for hint in _TOOL_NAME_HINTS)
    return has_tool


# B-2026-08-20-13 (Session 314): hedge detection. After tools ran and produced
# evidence, weak models sometimes produce a non-answer that asks the user to
# choose or confirm instead of synthesizing the answer from the evidence they
# already have. Live transcript: model had 8 search results with "16°,
# overcast" but answered "Would you like me to get the current weather from
# weather-atlas.com?" — a hedging non-answer.
_HEDGE_PHRASES: tuple[str, ...] = (
    "would you like me to",
    "would you prefer",
    "which source would",
    "which would you prefer",
    "shall i fetch",
    "shall i get",
    "do you want me to",
    "i would need to fetch",
    "i'd need to fetch",
    "i can fetch one of these",
    "i'd be happy to fetch",
    "let me know which",
    "please let me know if you'd like",
)


def answer_hedges_after_evidence(text: str) -> bool:
    """Detect a hedging non-answer after tools ran.

    Returns True when the text contains a hedge phrase ("Would you like me
    to...", "Which source would you prefer?") — indicating the model is
    asking the user to choose or confirm instead of synthesizing the answer
    from the evidence it already gathered.

    Called by ``_acceptance_gate_at_final_answer`` ONLY on iterations where
    at least one tool ran this run (evidence exists), so the detector never
    fires on a turn that didn't gather evidence.
    """
    if not text or len(text.strip()) < 10:
        return False
    lower = text.lower()
    return any(phrase in lower for phrase in _HEDGE_PHRASES)


class AgentLoop:
    """
    Runs the think → act → observe cycle for a single user turn using
    Ollama's native tool calling API.

    Usage (called by Engine.stream()):
        async for chunk in agent_loop.run(messages, intent, ...):
            yield chunk

    Note: CHAT intent should NOT be routed here — engine.py handles CHAT
    by streaming directly via adapter.chat().
    """

    def __init__(self, adapter):
        self._adapter = adapter
        self._synthesizer = AnswerSynthesizer(
            enabled=SYNTHESIS_ENABLED,
            timeout_secs=SYNTHESIS_TIMEOUT_SECS,
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(
        self,
        messages: list[dict],
        intent: Intent,
        initial_tool_result: Optional[ToolResult],
        available_tools: list[dict],
        confidence: float = 1.0,
        adapter=None,
        intent_history: Optional[list[str]] = None,
        obs=None,
        memory_facts: Optional[list[str]] = None,
        orchestrator_context: Optional[str] = None,
        skip_planning: bool = False,
        # Optional caller-provided plan labels. They seed the Todos panel
        # (same plan-{i} ids the planner would emit) and drive the plan
        # cursor, so the UI still shows a real plan + progress.
        plan_steps: Optional[list[str]] = None,
        # ADR-18 P0: typed success criteria from an explicit plan
        # (or the model's create_plan). The acceptance gate
        # evaluates these against tool evidence + workspace; "done" requires
        # receipts. None = no contract (legacy model-assertion path).
        success_criteria: Optional[list[str]] = None,
        # ADR-19: explicit task type from a caller-provided plan.
        # Selects the task-aware context policy (which tool results/history
        # stay verbatim vs. get stubbed). Empty = legacy positional behavior.
        task_type: str = "",
        # ADR-18 P0: the selected BaseAgent's is_done() implementation,
        # called at each iteration head so the loop stops when criteria are
        # VERIFIED (not merely asserted). None for the direct-loop path
        # (no agent instance) — hard caps still bound it.
        is_done_fn=None,
        agent_config=None,
        agent_context: Optional[str] = None,
        allowed_tool_names: Optional[frozenset[str]] = None,
        steering_queue: Optional[asyncio.Queue] = None,
        abort_signal: Optional[asyncio.Event] = None,
        # Session 178 — wire the dead AgentOrchestrator.replan() into the
        # verify-fail path. Before falling back to _replan_for_gate's
        # self-contained LLM call, notify the orchestrator so its confidence
        # drops, it can re-route to a different agent (e.g. coding→debugger),
        # and the orchestrator_replan_* obs events fire for real (consumed by
        # the frontend in Session 180). None = legacy behavior (no orchestrator
        # notification; _replan_for_gate runs alone).
        orchestrator=None,
        reformulated_message: str = "",
    ) -> AsyncIterator[StreamChunk]:
        """
        Run the agent loop with the Plan→Execute→Verify workflow.

        Flow:
        0. [Plan] If PLAN_ENABLED, run a planning LLM call (no tools) to
           produce a step-by-step plan. Inject it into the execution prompt.
        1. Build filtered tool definitions
        2. Loop up to MAX_ITERATIONS:
           a. Call adapter.chat_with_tools() with tool definitions
           b. If ToolCallResult → validate, dispatch, verify, add to context, continue
           c. If AsyncIterator[StreamChunk] → stream to user, return
        3. If max iterations hit, force a final answer

        Args:
            orchestrator_context: Optional caller-provided context or hint.
                The parent may evaluate, adapt, or reject it before acting;
                it is never a directive that bypasses parent planning.
            plan_steps: Optional list of caller-provided step labels. These
                seed the Todos panel (plan-{i} ids) and drive the plan cursor
                as the model narrates each step.
            agent_config: Optional AgentConfig from the selected BaseAgent
                subclass (ADR-6). When provided, its `max_iterations` and
                `max_wall_clock_secs` override the module-level defaults
                (ADR-8 Phase 2 — was dead code before; now honored).
            agent_context: Optional agent-specific context string from the
                selected BaseAgent's build_context() method (ADR-8 Phase 2).
                When the CodingAgent is selected for SHELL/FILE_*/CODE_EXEC
                intents, this contains the coding playbook loaded from
                agents/coding/playbook.md. Passed through to
                build_agent_system_prompt() and injected as the
                `agent_context_section` in the system prompt.
            steering_queue: Optional per-session asyncio.Queue of user
                messages injected mid-turn (B-2026-08-02-5/A5). Drained at
                each iteration boundary — the agent sees them as new user
                prompts and continues its turn without being aborted.
            abort_signal: Optional per-session asyncio.Event (B-2026-08-02-2/A2).
                When set (POST /api/chat/{session_id}/abort), the loop raises
                AgentAbortedError at the next check point so the engine can
                yield a clean "stopped" response instead of running to the
                wall-clock/iteration cap after the client closed the stream.
        """
        active_adapter = adapter or self._adapter
        trace = AgentTrace()
        # ADR-18 P0: seed the acceptance contract from the dispatcher's plan.
        if success_criteria:
            trace.success_criteria = [str(c).strip() for c in success_criteria if str(c).strip()]

        # ADR-19: resolve the context policy from the DISPATCHER-RESOLVED
        # task_type (parse_task_type_from_plan already applied the
        # primary_domain hint before storing it on the plan). The dispatcher
        # prompt contract says "when unset or ambiguous, omit it — the engine
        # falls back to the legacy positional behavior" — so the loop must
        # not additionally activate a policy via intent/phase fallbacks
        # (Session 163: a SHELL intent with no task_type must behave exactly
        # as before; see design.md §7 locked decision 2 note). Empty → the
        # legacy no-op default policy.
        from core.context_policy import policy_for, resolve_task_type

        # ADR-19 x ADR-22 re-key (Session 186): the passed-in task_type is a
        # dispatcher HINT — the agent re-settles it from its actual routing
        # during planning below. Seed with the hint so any read before the
        # settlement point sees the same value the engine used.
        self._settled_task_type = task_type
        self._context_policy = policy_for(task_type)
        # Provider usage is carried through every streamed chunk and tool-call
        # result so the Engine can report real prompt/completion counts.
        _provider_usage: dict[str, int] = {}
        _obs = obs  # may be None — all obs.emit() calls guarded below
        _loop_start_time = time.monotonic()  # ADR-5: wall-clock cap baseline

        # B-2026-08-02-7 (B2): fresh proposal scope per run — staged edits
        # from a previous run must never leak into this one (same
        # fresh-per-turn pattern as the A5 steering queue / A2 abort event).
        # Lazy import to avoid a circular import at registration time.
        from tools.proposals import reset_proposals
        reset_proposals()
        # B-2026-08-02-8 (B3): fresh subgoal scratchpad per run — a previous
        # run's subgoals must never leak into this one (same fresh-per-turn
        # pattern as the proposal registry / A5 steering queue / A2 abort).
        from core.subgoal import reset_subgoals
        reset_subgoals()

        # ADR-40 option C: per-run loaded long-tail tools (via describe_tool).
        # Fresh per run — a previous run's loads never leak into this one
        # (same fresh-per-turn pattern as proposals/subgoals above).
        loaded_tools: set[str] = set()

        # ADR-8 Phase 2 (Session 34): honor agent_config.max_iterations
        # and agent_config.max_wall_clock_secs when provided. Previously
        # these were dead code — the loop used module-level MAX_ITERATIONS
        # and MAX_WALL_CLOCK_SECS regardless of which agent was selected.
        # Now the CodingAgent can have more headroom (20 iterations / 10
        # minutes) than the generic loop (8 iterations / 3 minutes),
        # appropriate for coding tasks that need more steps. Fall back to
        # the module-level defaults if agent_config is None or its caps
        # are unset/invalid.
        if (
            agent_config is not None
            and getattr(agent_config, "max_iterations", None)
            and isinstance(agent_config.max_iterations, int)
            and agent_config.max_iterations >= 1
        ):
            _effective_max_iter = agent_config.max_iterations
        else:
            _effective_max_iter = MAX_ITERATIONS
        if (
            agent_config is not None
            and getattr(agent_config, "max_wall_clock_secs", None)
            and isinstance(agent_config.max_wall_clock_secs, (int, float))
            and agent_config.max_wall_clock_secs >= 1
        ):
            _effective_max_wall = agent_config.max_wall_clock_secs
        elif getattr(active_adapter, "thinking_enabled", False) or getattr(active_adapter, "slow_provider", False):
            # ADR-41 (Session 256): a thinking model on a slow free tier
            # spends 30-170s per call THINKING before acting — the 180s wall
            # clock fits only ~1-2 calls, so a multi-step turn (init + tool +
            # answer) hits the cap before finishing. Session 288: a slow
            # LOCAL provider (Ollama) has the same wall-clock problem for a
            # different reason — every call is slow (often 60-90s+), so a
            # multi-step turn can't fit in 180s either. Scale the cap for
            # both; the per-call timeout, iteration cap, and bounded recovery
            # retries are the real spin protections.
            _effective_max_wall = _reasoning_setting(
                "localmind_reasoning_max_wall_clock_secs",
                REASONING_MAX_WALL_CLOCK_SECS,
            )
        else:
            _effective_max_wall = MAX_WALL_CLOCK_SECS

        if _obs:
            _obs.emit("agent_loop_start", intent=intent.value)

        # ── Clarification gate ─────────────────────────────────────────
        if confidence < CLARIFICATION_THRESHOLD and intent in AGENT_INTENTS:
            clarification = (
                f"I want to make sure I understand — it looks like you want me to "
                f"use the **{intent.value.replace('_', ' ')}** tool, but I'm not very confident. "
                f"Could you confirm, or rephrase what you'd like me to do?"
            )
            trace.clarification_issued = True
            yield StreamChunk(text=clarification, done=False)
            yield StreamChunk(text="", done=True)
            if _obs:
                _obs.emit("agent_loop_done", intent=intent.value, clarification=True)
            return

        # ── Build tool definitions filtered by allowlist ───────────────
        # ADR-6: when an agent_config is provided, use its scoped
        # allowed_tools instead of the global AGENT_ALLOWED_TOOLS, then
        # (Session 124) further narrow to the intent's tool scope — a
        # coding agent's 19 tools become ~11 for a SHELL task. Smaller
        # surface = more reliable selection AND fewer tokens per step.
        scoped_tools = agent_config.allowed_tools if agent_config is not None else None
        effective_allowed = allowed_tool_names
        if effective_allowed is not None:
            scoped_tools = frozenset(scoped_tools or AGENT_ALLOWED_TOOLS).intersection(effective_allowed)
        # Session 124: per-intent tool scoping — intersect with the intent's
        # tool scope so a git-status request doesn't pay for web/browse/
        # proposal/subgoal tool definitions on every step (the 21.9K-prompt-
        # token driver). Unknown intents fall back to the full allowlist.
        #
        # Guard: when the CALLER explicitly scoped tools (allowed_tool_names
        # provided — e.g. the execution-graph/objective path passes a graph
        # policy), respect that scope fully and do NOT further narrow it by
        # intent. The graph policy is already the authoritative toolset for
        # that step; intersecting it with the intent scope could silently
        # drop a tool the graph expects.
        if effective_allowed is None:
            intent_scope = INTENT_TOOL_SCOPES.get(intent, AGENT_ALLOWED_TOOLS)
            scoped_tools = frozenset(scoped_tools or AGENT_ALLOWED_TOOLS).intersection(intent_scope)
        filtered_tools = _filtered_tool_defs(scoped_tools)

        # Phase 1 warm-kernel parent turns enter the native loop directly.
        # Resolve this before composing the first tool definitions because the
        # bootstrap surface is intentionally smaller than the normal surface.
        _parent_native_turn = (
            bool(skip_planning) and getattr(agent_config, "name", "") == "parent"
        )

        # ADR-40 option C: the native `tools` param is composed PER CALL —
        # scoped CORE tools + describe_tool + any long-tail tools loaded this
        # run via describe_tool (on-demand full-tool-context). Loaded tools
        # stay loaded for the rest of the run; nothing outside the scope is
        # ever added.
        def _current_tool_defs() -> list[dict]:
            _allowed = scoped_tools if scoped_tools is not None else AGENT_ALLOWED_TOOLS
            return tool_defs_for_call(
                filtered_tools,
                _allowed,
                loaded_tools,
                bootstrap_only=_parent_native_turn,
            )

        # Scope the metadata tool list the same way so the system-prompt
        # "Available tools" section and the planner see the same small
        # surface as the adapter tool defs. Metadata uses intent values;
        # most equal their tool names except FILE_EDIT (tool module
        # "edit_file").
        def _scope_name(t: dict) -> str:
            return "edit_file" if t.get("intent") == "file_edit" else t.get("intent")

        scoped_available = [t for t in available_tools if _scope_name(t) in scoped_tools]

        # Boot-path efficiency (bootup-telemetry session): the FULL
        # environment block (platform calls + available_tools + a VectorStore
        # construction) and the ADR-5 workspace snapshot (4-5 git
        # subprocesses, ~100ms macOS / more on Windows) are ONLY consumed by
        # the EXECUTE prompt (turn_context_parts below). They are NOT needed
        # by the parent initialization call — that uses the COMPACT env block
        # (init_env_context). Building them here, before the init model call,
        # made every DIRECT turn ("Hi") pay for work it never uses. Both are
        # now deferred to the execute path: env_context is built lazily where
        # the non-parent plan-stream needs it, and the workspace snapshot is
        # taken right before the execute prompt assembly. Direct/clarify
        # turns skip them entirely.

        # ── Phase 0: Parent initialization / planning ───────────────────
        # The user-facing parent does not inherit a prompt-shaped route. Its
        # first model call decides whether this is direct conversation,
        # clarification, or tool work. Tool work gets a bounded plan that is
        # then injected into the execution loop; direct/clarify decisions
        # finish here without a second model call.
        #
        # Non-parent callers retain the older plan-stream contract for child
        # agents and isolated loop tests. The request runtime always supplies
        # the ParentAgent config, so all user turns use initialization.
        plan_context = ""
        iteration_offset = 0  # how many initialization/planning calls consumed
        # Session 280 (B-2026-08-16-12): `initialization` is only assigned in
        # the parent-init branch below, but the Thinker consult reads it as
        # the Evidence objective. Initialize here so the consult never hits a
        # NameError on non-parent paths (child agents, isolated loop tests) —
        # before this, the NameError was swallowed by the consult's try/except
        # and the Thinker silently never ran outside the parent loop.
        initialization: Optional[InitializationDecision] = None
        _parent_initialization = (
            getattr(agent_config, "name", "") == "parent"
            and not initial_tool_result
            and not skip_planning
        )
        if _parent_initialization:
            if abort_signal is not None and abort_signal.is_set():
                raise AgentAbortedError("aborted by user before initialization")
            initialization_started = time.monotonic()
            if _obs:
                _obs.emit("agent_initialization_start", intent=intent.value)
            # ADR-34 B-7: consume the streaming initializer so the user sees
            # the model's acknowledgement within the 5s SLO.
            # Each ("ack", str) event becomes a StreamChunk(status=...) — a
            # model-owned transport acknowledgement, never raw chain-of-thought.
            # The ("understanding", str) event is INTERNAL: it feeds the Agent
            # Workspace lifecycle phase (agent_initialization_understanding obs)
            # only — it is NOT streamed into the chat ThinkingBlock (a shallow
            # one-line classify note doesn't belong in the user's chat thread).
            initialization: Optional[InitializationDecision] = None
            streaming_ack_emitted = False
            # Session 289: the classify/init call gets a COMPACT env (no tool
            # prose, no hardware lines) — ~half the tokens of the full block,
            # which matters most on the slow local models this app targets.
            init_env_context = _build_environment_context(compact=True)
            async for event_type, payload in self._initialize_parent_streaming(
                active_adapter=active_adapter,
                messages=messages,
                env_context=init_env_context,
                intent_history=intent_history,
            ):
                if event_type == "ack" and isinstance(payload, str):
                    streaming_ack_emitted = True
                    if _obs:
                        _obs.emit(
                            "agent_initialization_ack",
                            acknowledgement=payload[:180],
                            elapsed_ms=round((time.monotonic() - initialization_started) * 1000),
                        )
                    yield StreamChunk(text="", done=False, status=payload[:180])
                elif event_type == "understanding" and isinstance(payload, str):
                    # INTERNAL only — narrate it in the Agent Workspace via the
                    # obs event; do NOT yield a thinking StreamChunk (that would
                    # surface this shallow one-line classify note in the user's
                    # chat ThinkingBlock, where it doesn't belong).
                    if _obs:
                        _obs.emit(
                            "agent_initialization_understanding",
                            understanding=payload[:600],
                            elapsed_ms=round((time.monotonic() - initialization_started) * 1000),
                        )
                elif event_type == "decision" and isinstance(payload, InitializationDecision):
                    initialization = payload
            if initialization is None:
                # The streaming contract guarantees a final decision event;
                # if we somehow didn't get one, fall back safely.
                initialization = parse_initialization("")
            iteration_offset = 1
            if _obs:
                _obs.emit(
                    "stage_timing",
                    stage="agent_initialize",
                    latency_ms=round((time.monotonic() - initialization_started) * 1000),
                    status="done",
                )
                _obs.emit(
                    "agent_initialization_done",
                    mode=initialization.mode,
                    objective=initialization.objective,
                    # Action-oriented turn heading for the Agent Workspace
                    # (rides the existing event — no extra call). Empty when the
                    # model omitted it → the UI keeps "Turn N".
                    title=initialization.title,
                    confidence=initialization.confidence,
                    # ADR-34 B-12: record the init prompt budget so init vs
                    # execution sizes are measured independently.
                    init_prompt_chars=initialization.init_prompt_chars,
                )

            if initialization.is_direct:
                if _obs:
                    _obs.emit("agent_loop_done", intent=intent.value, direct=True)
                if getattr(initialization, "needs_history_answer", False):
                    # B-2026-08-18-5: the classify JSON flaked with nothing to
                    # salvage. Do NOT emit the canned context-free fallback —
                    # answer the user's latest message directly from the
                    # conversation history (fixes a follow-up like "why did you
                    # say X?" being met with a generic "tell me more").
                    _hist_msgs = [
                        {
                            "role": "system",
                            "content": (
                                "You are LocalMind, a helpful assistant. Answer the user's "
                                "LATEST message using the conversation above. If they are "
                                "questioning or correcting a previous answer, address it "
                                "directly and honestly using what was actually said earlier "
                                "— never reply with a generic 'tell me more'. Be concise."
                            ),
                        },
                        *messages,
                    ]
                    _direct_parts: list[str] = []

                    async def _collect_direct():
                        async for _c in active_adapter.chat(_hist_msgs, temperature=0.4, intent="chat"):
                            if getattr(_c, "error", None):
                                break
                            _t = _filter_system_leaks(_c.text or "")
                            if _t:
                                _direct_parts.append(_t)

                    try:
                        await asyncio.wait_for(
                            _collect_direct(), timeout=_per_call_timeout_for(active_adapter)
                        )
                    except Exception as _exc:  # pragma: no cover — defensive fallback
                        logger.warning("[agent.loop] direct-from-history fallback failed: %s", _exc)
                    _answer = "".join(_direct_parts).strip() or initialization.response
                    yield StreamChunk(text=_answer, done=False, usage=initialization.usage)
                    yield StreamChunk(text="", done=True)
                    return
                if initialization.acknowledgement:
                    yield StreamChunk(
                        text="",
                        done=False,
                        status=initialization.acknowledgement,
                    )
                # Session 290: carry the init call's provider usage — on a
                # direct turn the init IS the turn, so this is the real token
                # count (else the runtime falls back to an inflated estimate).
                yield StreamChunk(
                    text=initialization.response,
                    done=False,
                    usage=initialization.usage,
                )
                yield StreamChunk(text="", done=True)
                return

            if initialization.is_clarification:
                if _obs:
                    _obs.emit("agent_loop_done", intent=intent.value, clarification=True)
                clarification = "\n\n".join(
                    part
                    for part in (initialization.acknowledgement, initialization.clarifying_question)
                    if part
                ) or "Could you clarify what you would like me to do?"
                yield StreamChunk(text=clarification, done=False)
                yield StreamChunk(text="", done=True)
                return

            plan_context = initialization.objective_line()
            trace.plan_text = plan_context
            # ADR-49 (revises ADR-38 for the todo checklist): the init returns an
            # ordered step list for a multi-step task. Emit it UP FRONT as the
            # live Todos panel so the user sees the plan the agent will follow;
            # `_advance_plan_on_narration` (below) checks each step off as the
            # agent works, and the agent may reorder/skip as evidence changes.
            _plan_steps = list(initialization.plan_steps or [])
            if _plan_steps and _obs:
                _obs.emit("todo_cleared")
                for i, step in enumerate(_plan_steps):
                    _obs.emit(
                        "todo_created",
                        id=f"plan-{i}",
                        text=step,
                        completed=False,
                        status="pending",
                    )
            if _obs:
                _obs.emit(
                    "agent_planning_done",
                    intent=intent.value,
                    plan_len=len(plan_context),
                    iterations_cost=iteration_offset,
                )
            # The streaming ack already surfaced the model's acknowledgement
            # earlier in the turn; only emit a status line here if the
            # streaming path did NOT already show one (e.g. the model produced
            # no acknowledgement field but did produce an execute decision).
            if initialization.acknowledgement and not streaming_ack_emitted:
                yield StreamChunk(text="", done=False, status=initialization.acknowledgement)
        elif PLAN_ENABLED and intent in AGENT_INTENTS and not initial_tool_result and not skip_planning:
            # B-2026-08-02-2 (A2): check abort before the planning phase — it
            # can take a full model call.
            if abort_signal is not None and abort_signal.is_set():
                raise AgentAbortedError("aborted by user before planning")
            if _obs:
                _obs.emit("agent_planning_start", intent=intent.value)

            # The plan-stream path (non-parent callers) is the ONLY consumer
            # of the full environment block — the parent initialization call
            # uses the compact block instead. Build it here, lazily, so the
            # parent boot path never pays for it (bootup-telemetry session).
            # S295: drop the redundant "## Available Tools" prose (the native
            # tools param + in-prompt list already carry it) — saves ~279
            # tokens on every loop iteration; keeps the OS/shell hints.
            env_context = _build_environment_context(include_tool_list=False)

            # Collect the plan internally while it streams from the provider.
            plan_chunks: list[str] = []
            async for plan_chunk in self._plan_stream(
                active_adapter=active_adapter,
                intent=intent,
                loop_messages=messages,
                available_tools=scoped_available,
                env_context=env_context,
                intent_history=intent_history,
                tool_defs=_current_tool_defs(),
            ):
                if plan_chunk:
                    plan_chunks.append(plan_chunk)

            plan_context = "".join(plan_chunks).strip()

            # Truncate plan to prevent context bloat
            _PLAN_MAX_CHARS = 1500
            if len(plan_context) > _PLAN_MAX_CHARS:
                plan_context = plan_context[:_PLAN_MAX_CHARS] + "\n[... plan truncated]"

            iteration_offset = 1  # PLAN_ITERATION_COST
            trace.plan_text = plan_context
            if _obs:
                _obs.emit(
                    "agent_planning_done",
                    intent=intent.value,
                    plan_len=len(plan_context),
                    iterations_cost=iteration_offset,
                )

            # Parse plan steps and emit as todo items via obs
            # so the frontend's Todos panel shows the execution plan
            _plan_steps = _parse_plan_steps(plan_context)
            if _plan_steps and _obs:
                for i, step in enumerate(_plan_steps):
                    _obs.emit("todo_created", id=f"plan-{i}", text=step, completed=False)
            elif not _plan_steps:
                # Session 122: the engine's static fallback is suppressed for
                # plan-required intents (the LLM plan owns the todo list), so a
                # planner that produced nothing parseable must be loud — a
                # silent zero-todo turn would look exactly like the old dead UI.
                logger.warning(
                    f"[agent.loop] plan produced 0 steps for intent={intent.value} "
                    f"(plan_len={len(plan_context)}); no todos emitted"
                )
        elif plan_steps:
            # Session 134: planning was skipped because the dispatcher's
            # execution_plan is being reused (injected via
            # orchestrator_context). Seed the todo list from those steps so
            # the Todos panel shows the plan and the cursor can advance as
            # the model narrates each step.
            _plan_steps = list(plan_steps)
            if _obs:
                for i, step in enumerate(_plan_steps):
                    _obs.emit("todo_created", id=f"plan-{i}", text=step, completed=False)
        else:
            _plan_steps = []

        # ADR-18 P0: first-class task state — created once per turn when
        # there is a contract (criteria) or a plan. The full block (objective
        # + criteria checklist) is injected into the system prompt ONCE — the
        # criteria are the "done" contract. Progress/budget are refreshed
        # into the per-iteration context each iteration (cheaper than
        # re-injecting the criteria every turn). Objective prefers the short
        # user message; the plan text (already injected via plan_context) is
        # only a capped fallback so it is never duplicated.
        task_state = TaskState(
            objective=_user_message_text(messages)
            or (plan_context or "").strip()[:160]
            or "",
            success_criteria=list(trace.success_criteria),
        )
        # Session 180 — F3 Structured Planner DAG. Parse the free-text
        # plan into typed PlanNode objects so the loop can advance them
        # through pending → in_progress → completed | failed. Falls back
        # to the GoalInterpreter's turn-level criteria for per-node
        # criteria when the plan text doesn't carry its own.
        if plan_context:
            try:
                from core.agent.plan_parser import parse_plan_to_nodes

                task_state.nodes = parse_plan_to_nodes(
                    plan_context,
                    fallback_criteria=list(trace.success_criteria) if trace.success_criteria else None,
                )
                if task_state.nodes and _obs:
                    _obs.emit(
                        "plan_nodes_created",
                        intent=intent.value,
                        node_count=len(task_state.nodes),
                        node_ids=[n.id for n in task_state.nodes],
                    )
            except Exception as _plan_parse_exc:  # pragma: no cover — defensive
                logger.warning(
                    "[agent.loop] plan_parser failed (non-fatal): %s",
                    _plan_parse_exc,
                )

        # ADR-19 x ADR-22 re-key (Session 186): settle the task type the
        # agent committed to during planning. The dispatcher task_type is a
        # HINT (free-tier misclassifies); the loop only plans for
        # AGENT_INTENTS with an intent-driven planner, so the intent is the
        # settled routing. Explicit canonical hints still win (except 'chat'
        # on a non-CHAT routing); the intent fallback corrects a
        # misclassified/empty hint. Re-keys the loop's own context policy
        # (tool-result compaction) + the trace, keeping them consistent with
        # the engine's level-aware memory retrieval.
        self._settled_task_type = resolve_task_type(
            task_type,
            intent=intent.value,
        )
        self._context_policy = policy_for(self._settled_task_type)
        trace.task_type = self._settled_task_type
        if _obs:
            _obs.emit(
                "task_type_settled",
                task_type=self._settled_task_type,
                source="planning" if plan_context else "routing",
                plan_len=len(plan_context),
            )

        task_state.set_budget(
            iter_used=0,
            iter_max=_effective_max_iter,
            wall_used=0.0,
            wall_max=_effective_max_wall,
        )

        # Track which plan step we're currently executing so we can mark
        # todos as complete when their corresponding tool finishes.
        _plan_step_cursor = 0

        # Session 121: the plan cursor advances ONLY when the model narrates
        # a step transition (non-empty text before its tool call). Silent tool
        # continuations keep the current todo — so ONE todo owns MANY actions
        # (e.g. todo "Review backend code" → read/grep/read… all under it).
        # The previous per-tool advance split one logical step's actions
        # across consecutive todos. Remaining todos are finalized as done
        # when the turn ends (see the SSE bridge's _finalize_plan_todos).
        def _advance_plan_on_narration() -> None:
            nonlocal _plan_step_cursor
            if (
                _plan_steps
                and _plan_step_cursor < len(_plan_steps)
                and (result.raw_content or "").strip()
                and _obs
            ):
                _obs.emit("todo_completed", id=f"plan-{_plan_step_cursor}", completed=True)
                _plan_step_cursor += 1

        # Session 142: the 'why' for any tool call under the active plan
        # step. The frontend renders `why: {action.reasoning}` in the
        # Actions/tool-step cards — previously only the model's pre-tool
        # narration (thought=) was attached, so a silent tool run (no
        # narration, the common free-tier case) rendered a blank 'why:'.
        # The plan-step label IS the rationale for the action; attach it.
        def _step_reasoning() -> str:
            if _plan_steps and 0 <= _plan_step_cursor < len(_plan_steps):
                return _plan_steps[_plan_step_cursor]
            return ""

        # Session 142: mark the CURRENT plan step's todo complete when the
        # loop is about to end. `_advance_plan_on_narration` only completes
        # on model narration; a silent tool run (the common free-tier case)
        # never advances, so the executed step's todo stayed 'pending' until
        # the SSE bridge's end-of-turn finalize — which the user's real run
        # showed NOT landing in the UI. Emit from the loop itself so the
        # bridge's todo_completed handler (chat.py) forwards it regardless.
        # Does NOT advance the cursor — one todo may own many actions.
        def _complete_current_plan_step() -> None:
            if not _plan_steps or not _obs:
                return
            if 0 <= _plan_step_cursor < len(_plan_steps):
                _obs.emit(
                    "todo_completed",
                    id=f"plan-{_plan_step_cursor}",
                    completed=True,
                )

        # ── Inject agent system prompt (with plan context) ──────────────
        loop_messages = list(messages)

        # Build the parent execution prompt with plan context, memory facts,
        # and any caller-provided routing hint
        system_prompt = build_agent_system_prompt(
            intent=intent,
            available_tools=scoped_available,
            intent_history=intent_history,
            plan_context=plan_context if plan_context else None,
            memory_facts=memory_facts,
            orchestrator_context=orchestrator_context,
            agent_context=agent_context,
            # ADR-40: render the in-prompt "Available tools" list from the SAME
            # scoped defs as the native tools param (single source of truth).
            tool_defs=filtered_tools,
            native_bootstrap=_parent_native_turn,
        )

        # Session 245 (agent-loop token efficiency, Lever 1): the environment
        # (OS/cwd and the CURRENT TIME), the ADR-5 workspace state (git status,
        # diff, last build) and the ADR-18 task-state block are all PER-TURN
        # DYNAMIC. They are deliberately kept OUT of the cacheable system prompt
        # and carried in a SEPARATE trailing turn-context message, so the
        # system+tools prefix stays byte-stable across calls and turns and the
        # provider can cache it (see the cache_control marker in the adapter).
        #
        # ── ADR-5: Workspace state feedback (DEFERRED to the execute path) ──
        # Mark the turn start (records current HEAD for diff tracking), then
        # take a snapshot of git status/diff/build result. The snapshot is
        # injected into the execute prompt below — this is the "observations
        # flow back into context every turn" loop from the CODING HARNESS
        # diagram, the literal difference between a harness and a bare API.
        #
        # Boot-path efficiency (bootup-telemetry session): this block runs 4-5
        # git subprocesses (~100ms on macOS, more on Windows). It is ONLY
        # consumed by the execute prompt — the parent initialization call
        # never sees it. Deferred here (after init/plan decided mode=execute)
        # so DIRECT and CLARIFY turns skip the subprocesses entirely.
        workspace_context = ""
        if WORKSPACE_STATE_ENABLED:
            try:
                mark_turn_start()
                ws_snap = workspace_snapshot()
                workspace_context = format_snapshot(ws_snap)
                if workspace_context:
                    logger.debug(
                        "[agent_loop] workspace_state injected (%d chars)",
                        len(workspace_context),
                    )
            except Exception as ws_exc:
                # Workspace state must never break the agent loop —
                # log and continue with empty context.
                logger.warning("[agent_loop] workspace_state failed: %s", ws_exc)
                workspace_context = ""

        # S295: the trailing turn-context is re-sent on EVERY loop iteration —
        # drop the redundant tool-list prose (kept in the native param + the
        # in-prompt list) to save ~279 tokens/iteration.
        turn_context_parts = [_build_environment_context(include_tool_list=False)]
        if workspace_context:
            turn_context_parts.append(workspace_context)
        _task_state_prompt = task_state.to_prompt()
        if _task_state_prompt:
            turn_context_parts.append(_task_state_prompt)
        turn_context = "\n\n".join(p for p in turn_context_parts if p)

        # Replace or prepend the (stable) system message
        if loop_messages and loop_messages[0]["role"] == "system":
            loop_messages[0] = {
                "role": "system",
                "content": loop_messages[0]["content"] + "\n\n" + system_prompt,
            }
        else:
            loop_messages.insert(0, {"role": "system", "content": system_prompt})

        # Trailing turn-context (dynamic) — placed AFTER the stable prefix so it
        # never mutates the cached region.
        if turn_context:
            loop_messages.insert(1, {"role": "system", "content": turn_context})

        # ── Seed observation log with initial tool result ──────────────
        observation_log = ""
        last_tool_failed = False
        consecutive_failures = 0
        fabrication_risk = 0  # Incremented on tool errors and fabrication-prone patterns
        # ADR-42: the Thinker consults ONCE, on the first real evidence.
        _thinker_consulted = False

        if initial_tool_result:
            safe_initial = _filter_tool_injection(initial_tool_result.content)
            # Inject as tool messages (proper OpenAI format — the model sees this in context).
            # Do NOT also add to observation_log: the tool messages ARE the observation.
            # Adding to observation_log AND injecting as tool messages triples the context cost.
            tool_call_id = str(uuid.uuid4())
            loop_messages.append(
                {
                    "role": "assistant",
                    "content": "I've already performed an initial action. Let me analyze the result.",
                    "tool_calls": [
                        {
                            "id": tool_call_id,
                            "type": "function",
                            "function": {
                                "name": initial_tool_result.source,
                                "arguments": "{}",
                            },
                        }
                    ],
                }
            )
            loop_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": _truncate_observation(safe_initial),
                }
            )
            # ADR-18 P1 (Session 174): the SINGLE_TOOL fast path (dir
            # listing, git status, URL fetch, browse) pre-dispatches the
            # tool in the engine and passes the result as
            # initial_tool_result — but the result never became a
            # trace.step, so the run-scoped evidence guard in both gates
            # (iteration-head is_done_fn and _acceptance_gate_at_final_answer)
            # saw ZERO tool evidence and criteria on fast-path plans could
            # never verify. Record it as a step: the tool DID run this
            # turn, its output IS evidence, and the criteria checkers
            # (tests/file/git/http/no-errors/fallback) can now evaluate it.
            trace.steps.append(
                AgentStep(
                    iteration=0,
                    thought="initial tool dispatch (engine pre-dispatch)",
                    tool_name=initial_tool_result.source or "tool",
                    tool_input="",
                    observation=safe_initial,
                    tool_failed=not initial_tool_result.success,
                    phase="execute",
                )
            )

        # Per-turn tool call cache: (tool_name, normalised_input) → observation text.
        _call_cache: dict[tuple[str, str], str] = {}

        # ── Collected tool results for post-loop synthesis ──────────────
        # Track all ToolResults from this turn so the AnswerSynthesizer
        # can extract and synthesize them into a user-facing answer after
        # the loop completes. Without this, raw search links and HTML
        # content leak directly to the user.
        collected_results: list[ToolResult] = []

        # ── Bug B fix: name-level dedup for file_write ────────────────────
        # Track which file paths have been written to in this turn. If the
        # agent calls file_write on the same path twice (even with different
        # content), the second call is almost always redundant or a mistake.
        # The fingerprint-level dedup above only catches identical inputs,
        # but the model may produce slightly different content strings on
        # retry, defeating the exact-match dedup.
        _file_write_paths: set[str] = set()

        # ── B-2026-08-02-9 (B4): inline-delegation scope ──────────────
        # Publish this loop's live message list (BY REFERENCE) plus a
        # validated in-place mutate callback into a contextvar. The
        # delegate_inline tool reads this scope and hands it to an
        # inline-capable child (ContextPrunerAgent), which can rewrite the
        # parent's history in place. Fail-safe: the callback structurally
        # validates the rewritten history (roles, tool_call_id pairing,
        # size bounds, no trailing tool role) and refuses invalid rewrites;
        # the pre-mutation history is snapshotted to disk; the mutation is
        # emitted via obs. Each nested agent loop republishes its own scope
        # and the delegation tools restore the parent's scope around child
        # runs, so a child can never leave its scope in the parent's place.
        _inline_run_id = f"inline_{uuid.uuid4().hex[:12]}"
        _inline_original_len = len(loop_messages)
        _inline_system_msg = (
            loop_messages[0]
            if (loop_messages and loop_messages[0].get("role") == "system")
            else None
        )
        _inline_scope = InlineMutationScope(
            run_id=_inline_run_id,
            messages=loop_messages,
            mutate=lambda _m: False,  # placeholder, replaced below
        )

        def _mutate_inline(new_messages: list[dict]) -> bool:
            """Validate, snapshot, and apply an inline rewrite in place."""
            # The child model never rewrites the system prompt — always
            # restore the original system message (if one was present).
            # Note: if the child dropped it, this +1 can push a rewrite that
            # was exactly at the size bound to "grew" — rejected fail-safe
            # (no mutation); the child sees the reason in the tool result.
            if _inline_system_msg is not None:
                _filtered = [m for m in new_messages if m.get("role") != "system"]
                new_messages = [_inline_system_msg] + _filtered
            ok, reason = validate_rewritten_history(new_messages, _inline_original_len)
            if not ok:
                logger.warning("[agent_loop] inline mutation rejected: %s", reason)
                return False
            _snap = snapshot_messages(loop_messages, _inline_run_id)
            _before = len(loop_messages)
            loop_messages[:] = new_messages
            _inline_scope.applied = True
            logger.info(
                "[agent_loop] inline mutation applied: %d → %d messages (snapshot %s)",
                _before, len(loop_messages), _snap or "none",
            )
            if _obs:
                _obs.emit(
                    "inline_mutation",
                    run_id=_inline_run_id,
                    before=_before,
                    after=len(loop_messages),
                    snapshot=_snap or "",
                )
            return True

        _inline_scope.mutate = _mutate_inline
        set_inline_mutation_scope(_inline_scope)

        # ── Main loop ──────────────────────────────────────────────────
        # Phase 1 warm-kernel parent turns enter this loop directly. Their
        # first native response may be ordinary prose, so they must not be
        # treated as a skipped tool call or forced into a tool recovery.
        # ADR-8 Phase 2: use _effective_max_iter / _effective_max_wall
        # (agent_config overrides when provided; module-level defaults
        # otherwise) instead of the raw MAX_ITERATIONS / MAX_WALL_CLOCK_SECS.
        _repetition_nudged = False  # B-2026-08-18-3: fire the progress nudge once per turn
        for iteration in range(_effective_max_iter):
            trace.iterations_used = iteration + 1

            # ADR-5: hard wall-clock cap. The loop terminates on "done,
            # blocked, OR limit" — this is the time-based limit. Prevents
            # a small model from spinning forever on a task it can't solve.
            _elapsed = time.monotonic() - _loop_start_time
            if _elapsed > _effective_max_wall:
                logger.warning(
                    "[agent_loop] wall-clock cap hit after %.1fs (iter %d/%d) — forcing final answer",
                    _elapsed,
                    iteration + 1,
                    _effective_max_iter,
                )
                if _obs:
                    _obs.emit(
                        "agent_loop_wall_clock_cap",
                        intent=intent.value,
                        elapsed_secs=_elapsed,
                        iteration=iteration + 1,
                    )
                break

            # ── ADR-18 P0 acceptance gate (iteration head) ──────────────
            # Sync model-declared success criteria (create_plan tool) into
            # the trace, update the task-state block, then ask the selected
            # agent's is_done(): the loop stops only when the criteria are
            # VERIFIED against evidence (not merely asserted). Stub
            # is_done() implementations return (False, "") — the legacy
            # model-assertion + hard-caps path is unchanged for them. The
            # wall-clock/iteration caps below still bound everything.
            from core.subgoal import get_registry as _get_subgoal_registry

            _sub_registry = _get_subgoal_registry()
            if not trace.success_criteria and _sub_registry.success_criteria:
                trace.success_criteria = list(_sub_registry.success_criteria)
                task_state.success_criteria = list(trace.success_criteria)
            task_state.iteration = iteration + 1
            task_state.set_budget(
                iter_used=iteration + 1,
                iter_max=_effective_max_iter,
                wall_used=_elapsed,
                wall_max=_effective_max_wall,
            )
            _subgoals = _sub_registry.all()
            task_state.completed = [s.description for s in _subgoals if s.status == "completed"]
            task_state.pending = [s.description for s in _subgoals if s.status in ("pending", "in_progress")]
            task_state.failed = [(s.description, s.notes or "") for s in _subgoals if s.status == "blocked"]

            # B-2026-08-18-3 — progress nudge. If the model has called the SAME
            # tool N+ times in a row (succeeding but not advancing — the "current
            # weather Kitengela" spin: 3 web_searches, all ok, none useful, then
            # empty synthesis), nudge ONCE to change approach or answer with what
            # it has. Soft: legitimately-repeated tools aren't blocked, and the
            # iteration/wall-clock caps remain the hard bound.
            if not _repetition_nudged:
                _rep_streak, _rep_tool = same_tool_repetition_streak(trace)
                if _rep_streak >= _SAME_TOOL_REPETITION_NUDGE_CAP:
                    _repetition_nudged = True
                    loop_messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"[PROGRESS CHECK] You have called `{_rep_tool}` "
                                f"{_rep_streak} times in a row and are not converging. "
                                "STOP repeating it: either take a genuinely DIFFERENT "
                                "approach (a different tool, or a materially different "
                                "input), or give the best answer you can from the evidence "
                                f"you already have. Do not call `{_rep_tool}` again with a "
                                "similar input."
                            ),
                        }
                    )
                    if _obs:
                        _obs.emit(
                            "agent_loop_repetition_nudge",
                            tool=_rep_tool,
                            streak=_rep_streak,
                            iteration=iteration + 1,
                        )

            # Session 180 — F3 Structured Planner DAG. Advance the plan
            # nodes based on the latest tool execution. Heuristic: the
            # node whose subgoal tokens appear in the latest tool's
            # input/observation transitions to completed (or failed).
            if task_state.nodes and trace.steps:
                try:
                    from core.agent.plan_parser import advance_node_for_step

                    _last = trace.steps[-1]
                    _advanced_id = advance_node_for_step(
                        task_state.nodes,
                        tool_name=_last.tool_name or "",
                        tool_input=_last.tool_input or "",
                        observation=_last.observation or "",
                        succeeded=not _last.tool_failed,
                    )
                    if _advanced_id and _obs:
                        _adv_node = next(
                            (n for n in task_state.nodes if n.id == _advanced_id), None
                        )
                        if _adv_node:
                            _obs.emit(
                                "plan_node_advanced",
                                node_id=_advanced_id,
                                new_status=_adv_node.status,
                                subgoal=_adv_node.subgoal[:120],
                                iteration=iteration + 1,
                            )
                except Exception as _advance_exc:  # pragma: no cover
                    logger.debug(
                        "[agent.loop] plan node advance failed (non-fatal): %s",
                        _advance_exc,
                    )
            # Fresh progress/budget for the per-iteration context (the
            # criteria checklist stays in the system prompt — no duplication).
            task_state_refresh = task_state.to_prompt(include_criteria=False)
            if task_state_refresh:
                task_state_refresh = "\n\n" + task_state_refresh

            if is_done_fn is not None:
                _done, _done_reason = is_done_fn(
                    iteration + 1,
                    _elapsed,
                    None,  # last tool result — the gate evaluates trace evidence
                    trace,
                )
                if _done:
                    logger.info(
                        "[agent.loop] acceptance gate passed — %s (iter %d/%d)",
                        _done_reason,
                        iteration + 1,
                        _effective_max_iter,
                    )
                    if _obs:
                        _obs.emit(
                            "agent_loop_gate_passed",
                            intent=intent.value,
                            iterations=iteration + 1,
                            reason=str(_done_reason)[:200],
                        )
                    # Gate-passed is a CLEAN termination: the criteria are
                    # verified (not asserted), so the verified summary IS the
                    # final answer. A plain `break` would fall into the
                    # hit-limit path (forced answer + hit_limit=True) — wrong.
                    # Same todo bookkeeping as the other clean exits.
                    _complete_current_plan_step()
                    _done_text = str(_done_reason or "").strip()
                    if not _done_text:
                        # ADR-36 B-7: a gate that passes without an explicit
                        # reason must still produce a non-empty final reply —
                        # never end a turn with zero output. Fall back to the
                        # trace evidence, then to a generic acknowledgement.
                        _done_text = self._summarize_trace_for_user(trace, observation_log) or (
                            "I completed the task and verified it against the "
                            "acceptance criteria."
                        )
                    trace.final_response = _done_text
                    if _obs:
                        _obs.emit("agent_loop_done", intent=intent.value, iterations=iteration + 1)
                    yield StreamChunk(text=_done_text, done=False)
                    yield StreamChunk(text="", done=True, usage=dict(_provider_usage))
                    return

            # B-2026-08-02-5 (A5): steering without aborting. Drain any
            # user messages queued via POST /api/chat/{session_id}/steer
            # at the NEXT iteration boundary — never mid-tool. The agent
            # sees the steering message as a new user prompt and continues
            # its turn instead of being aborted and re-run. Messages are
            # tagged "steering": True so compaction passes can identify
            # them; they are user-role, so the A4 compactor
            # (simplify_tool_results — tool-role only) never stubs them.
            if steering_queue is not None:
                while not steering_queue.empty():
                    _steer_msg = await steering_queue.get()
                    _steer_msg.setdefault("steering", True)
                    loop_messages.append(_steer_msg)

            # B-2026-08-02-2 (A2): abort check at each iteration boundary.
            # Set via POST /api/chat/{session_id}/abort (or client
            # disconnect) — the loop raises and the engine yields a clean
            # "stopped" response. Granularity is one step boundary, matching
            # the steering design: a mid-tool abort lands here after the
            # current tool finishes.
            if abort_signal is not None and abort_signal.is_set():
                raise AgentAbortedError("aborted by user")

            # Build iteration-specific context hint
            failure_hint = ""
            if last_tool_failed and consecutive_failures >= 2:
                failure_hint = (
                    "\nWARNING: Multiple tool failures. Consider providing your "
                    "best answer from existing context instead of retrying."
                )

            # Add an observation summary as the latest user context if we have one
            iteration_messages = list(loop_messages)
            if observation_log:
                # Cap observation log to prevent context overflow on later iterations.
                # Keep the tail (most recent observations) — they're most relevant.
                _OBS_LOG_TOTAL_CAP = OBS_LOG_MAX_CHARS * 2  # 1600 chars
                trimmed_log = observation_log
                if len(observation_log) > _OBS_LOG_TOTAL_CAP:
                    trimmed_log = "…[earlier observations truncated]\n" + observation_log[-_OBS_LOG_TOTAL_CAP:]
                context_content = f"{trimmed_log}{failure_hint}\nIteration {iteration + 1}/{_effective_max_iter}. "
                # ADR-18 P0: refresh the task-state progress/budget lines
                # into the per-iteration context (criteria stay in the
                # system prompt; only progress changes per iteration).
                if task_state_refresh:
                    context_content += task_state_refresh
                iteration_messages.append({"role": "user", "content": context_content})

            # B-2026-08-02-4 (A4): deterministic tool-result simplification.
            # When the accumulated conversation has more than the newest few
            # tool results, stub the older oversized ones (head + omission
            # marker + tail) to keep the window in budget WITHOUT an LLM
            # call. Preserves tool_call_id (protocol validity) and never
            # touches the newest results the model still needs. Idempotent.
            # Deliberately unconditional — the keep_last window preserves
            # what the model still needs; old results it already acted on
            # are exactly what frees the most context (see
            # context_compactor.simplify_tool_results docstring).
            iteration_messages = simplify_tool_results(
                iteration_messages,
                policy=getattr(self, "_context_policy", None),
            )

            # B-2026-08-02-8 (B3): surface the subgoal scratchpad directly in
            # the system message each iteration — tool results alone aren't
            # reliable working memory (the A4 compactor stubs older tool
            # results, so a plan created early could vanish mid-run). The
            # registry is small (3-7 subgoals); empty → skip. iteration_messages
            # is a fresh copy per iteration, so the append never accumulates.
            from core.subgoal import get_registry
            _scratchpad = get_registry().as_markdown()
            if iteration_messages and _scratchpad != "(no subgoals yet)":
                iteration_messages[0]["content"] = (
                    iteration_messages[0]["content"]
                    + "\n\n## Current subgoal scratchpad\n"
                    + _scratchpad
                )

            # ── LLM call with tools ───────────────────────────────────
            # Session 25/31: wrap with a hard timeout to prevent "thinking
            # forever" when the model hangs. Uses PER_CALL_TIMEOUT_SECS
            # (45s) — SHORTER than the adapter's 120s HTTP timeout so the
            # user sees a result before the adapter itself times out.
            # The wall-clock cap is checked between iterations.
            # ADR-41 (Session 254): a reasoning model with thinking enabled
            # (z.ai/GLM) legitimately streams many thinking tokens before
            # its answer — a fixed 45s cap would truncate mid-thought on a
            # slow free tier. When the adapter reports thinking_enabled,
            # use the larger reasoning budget instead (Settings UI / env).
            _per_call_timeout = _per_call_timeout_for(active_adapter)
            t_llm = time.monotonic()
            # Session 238 (Thinker/Agent rebuild Step 0): on the FIRST
            # iteration of a tool-required intent (no tool has run yet),
            # force the model to emit a tool call. Some providers
            # (gemini-2.5-flash via the OpenAI-compat endpoint) otherwise
            # return an empty or text-only response on the first tool call,
            # which failed the turn with the "empty response" message
            # (Session 237 trace). tool_choice="required" is applied ONLY
            # here — later iterations keep the default so the model can
            # synthesize its final answer without further tool calls.
            _force_tool_choice = (
                iteration == 0
                and intent in AGENT_INTENTS
                and not trace.steps
                and bool(filtered_tools)
                and not _parent_native_turn
            )
            try:
                result = await asyncio.wait_for(
                    active_adapter.chat_with_tools(
                        messages=iteration_messages,
                        tools=_current_tool_defs(),
                        temperature=0.3,
                        intent=intent.value,
                        tool_choice="required" if _force_tool_choice else None,
                    ),
                    timeout=_per_call_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "[agent_loop] model call timed out after %.0fs (iter %d) — breaking with error",
                    _per_call_timeout,
                    iteration + 1,
                )
                if _obs:
                    _obs.emit(
                        "agent_loop_model_timeout",
                        intent=intent.value,
                        timeout_secs=_per_call_timeout,
                        iteration=iteration + 1,
                    )
                yield StreamChunk(
                    text=(
                        f"The model is taking too long to respond "
                        f"(timed out after {int(_per_call_timeout)}s). "
                        f"The free-tier model may be overloaded. "
                        f"Please try again or switch to a faster model."
                    ),
                    done=False,
                )
                yield StreamChunk(text="", done=True)
                return
            llm_ms = round((time.monotonic() - t_llm) * 1000)
            logger.info(f"[agent.loop] iter={iteration + 1} LLM: {llm_ms}ms")

            # ── Handle MultiToolCallResult (model invoked multiple tools) ──
            result_usage = getattr(result, "usage", None)
            if result_usage:
                _provider_usage.update(result_usage)
                yield StreamChunk(text="", done=False, usage=dict(_provider_usage))
            # When the model returns multiple tool calls in a single response,
            # dispatch independent ones concurrently via asyncio.gather().
            # This is safe because independent tool calls (e.g., file_task + sysinfo)
            # have no side-effect dependencies between them.
            if isinstance(result, MultiToolCallResult):
                # The model's content alongside a tool call is user-facing
                # NARRATION (its chain-of-thought arrives separately on the
                # thinking channel and is filtered). Stream that one-line progress
                # update to the user's chat — not into the ThinkingBlock.
                _narration = _filter_system_leaks((result.raw_content or "").strip())
                if _narration:
                    yield StreamChunk(text=_narration[:400] + "\n\n", done=False)

                logger.info(
                    f"[agent.loop] iter={iteration + 1} multi_tool_call: "
                    f"{len(result.calls)} tools — {[c.tool_name for c in result.calls]}"
                )

                # Validate and filter: separate valid from rejected calls
                valid_calls: list[tuple[ToolCallResult, str]] = []  # (call, tool_input)
                _system_question = _user_message_text(messages)
                for call in result.calls:
                    _name, _args, _corrected = _normalize_system_tool_call(
                        _system_question,
                        call.tool_name,
                        call.tool_args,
                    )
                    if _corrected:
                        logger.info(
                            "[agent.loop] corrected shell clock call to sysinfo for %r",
                            _system_question[:80],
                        )
                        call.tool_name = _name
                        call.tool_args = _args
                    _inp = _extract_tool_input(_name, _args)

                    # Apply same validations as single-tool path
                    if effective_allowed is not None and _name not in effective_allowed:
                        logger.warning(f"[agent.loop] parallel: rejected tool {_name!r} by explicit policy")
                        continue
                    if _name not in AGENT_ALLOWED_TOOLS:
                        logger.warning(f"[agent.loop] parallel: rejected tool {_name!r}")
                        continue
                    if not _inp or len(_inp.strip("?. \t")) < 3:
                        logger.warning(f"[agent.loop] parallel: rejected degenerate input for {_name!r}")
                        continue
                    if _name == "file_write":
                        _p = _args.get("path", "").strip()
                        _c = _args.get("content", "").strip()
                        if not _p or not _c:
                            logger.warning("[agent.loop] parallel: file_write missing args, skipping")
                            continue

                    valid_calls.append((call, _inp))

                if not valid_calls:
                    # All calls were rejected — fall through to next iteration
                    last_tool_failed = True
                    consecutive_failures += 1
                    observation_log += "\n[All parallel tool calls rejected]\n"
                    continue

                # Dispatch all valid calls concurrently
                async def _dispatch_single(tc_name: str, tc_input: str, tc_args: dict):
                    """Dispatch a single tool and return (name, observation, failed, latency_ms, provider)."""
                    t_start = time.monotonic()
                    tc_result = None
                    try:
                        tc_intent = Intent(tc_name)
                        tc_result, tc_failed, _ = await dispatch_with_retry(
                            tc_intent,
                            tc_input,
                            obs=_obs,  # ADR-18 P3: delegation streams into the UI
                            allowed_tool_names=effective_allowed,
                        )
                        # ADR-40 option C: a describe_tool call in a batch loads
                        # the named tool for the rest of this run (metadata
                        # survives the wait_for task boundary).
                        _note_described_tool(tc_name, tc_result, loaded_tools)
                        _emit_todo_write_events(tc_name, tc_result, _obs)
                        tc_obs = tc_result.content if tc_result else f"[Tool {tc_name} returned no result]"
                        tc_obs = _filter_tool_injection(tc_obs)
                        # Collect result for post-loop synthesis
                        if tc_result:
                            collected_results.append(tc_result)
                        # Bridge diff metadata from edit_file tool results.
                        # When edit_file produces structured diff hunks, emit a
                        # file_diff obs event so the frontend DiffBlock can render
                        # green/red highlighted diffs — like Cursor/Claude.
                        if tc_result and tc_result.metadata and tc_result.source == "edit_file":
                            diff_hunks = tc_result.metadata.get("diff_hunks", [])
                            if diff_hunks and _obs:
                                _obs.emit(
                                    "file_diff",
                                    diff_hunks=diff_hunks,
                                    diff_language=tc_result.metadata.get("diff_language", ""),
                                    path=tc_result.metadata.get("path", ""),
                                    diff_additions=tc_result.metadata.get("diff_additions", 0),
                                    diff_deletions=tc_result.metadata.get("diff_deletions", 0),
                                )
                    except Exception as e:
                        tc_obs = f"[Tool {tc_name} error: {e}]"
                        tc_failed = True
                    tc_lat = round((time.monotonic() - t_start) * 1000)
                    tc_provider = _tool_provider(tc_result)
                    return tc_name, tc_obs, tc_failed, tc_lat, tc_provider

                # Build labels for each tool call
                # Session 142: capture the batch's 'why' ONCE — the started
                # emits below run BEFORE _advance_plan_on_narration and the
                # done emits AFTER it, so calling _step_reasoning() at each
                # emit would stamp the same tool call with two different step
                # labels on a narrated transition. All calls in a batch share
                # the same cursor, so one capture serves the whole batch.
                _batch_reasoning = _step_reasoning()
                for call, _inp in valid_calls:
                    _path = call.tool_args.get("path", "")
                    _command = call.tool_args.get("command", "")
                    _query = call.tool_args.get("query", "")
                    _code_preview = call.tool_args.get("code", "")[:40]
                    _label_map = {
                        "file_write": f"Creating file: {_path[:80]}" if _path else "Creating file",
                        "edit_file": f"Editing file: {_path[:80]}" if _path else "Editing file",
                        "code_exec": f"Executing: {_code_preview}..." if _code_preview else "Executing code",
                        "web_search": f"Searching: {_query[:80]}" if _query else "Searching the web",
                        "web_fetch": f"Fetching: {call.tool_args.get('url', '')[:80]}"
                        if call.tool_args.get("url")
                        else "Fetching web page",
                        "file_task": f"Reading: {_path[:80]}" if _path else "Reading file",
                        "shell": f"Running: {_command[:80]}" if _command else "Running command",
                        "memory_op": f"Memory: {call.tool_args.get('operation', '')} {call.tool_args.get('content', '')[:40]}".strip(),  # noqa: E501
                        "sysinfo": f"System info: {_query[:60]}" if _query else "Getting system info",
                        "observe": f"Observing: {_query[:60]}" if _query else "Observing the desktop",
                        "calculator": f"Calculating: {_query[:60]}" if _query else "Calculating",
                        "csv": f"Reading CSV: {_query[:60]}" if _query else "Reading CSV",
                        "json": f"Querying JSON: {_query[:60]}" if _query else "Querying JSON",
                        "sql": f"Querying DB: {_query[:60]}" if _query else "Querying database",
                        "git": f"Git: {call.tool_args.get('operation', '')}" if call.tool_args.get('operation') else "Git operation",  # noqa: E501
                        "process": f"Process: {call.tool_args.get('operation', '')} {call.tool_args.get('name', '')}" if call.tool_args.get('operation') else "Process operation",  # noqa: E501
                        "diagnostics": f"Diagnostics: {call.tool_args.get('operation', '')}" if call.tool_args.get('operation') else "Analyzing failure",  # noqa: E501
                        "browse": f"Browser: {call.tool_args.get('action', '')}" if call.tool_args.get('action') else "Using browser",  # noqa: E501
                        "delegate": f"Delegating to {call.tool_args.get('target_agent', '')}" if call.tool_args.get('target_agent') else "Delegating sub-task",  # noqa: E501
                        "delegate_parallel": f"Delegating {len(call.tool_args.get('targets') or [])} sub-agents in parallel" if call.tool_args.get('targets') else "Delegating sub-agents in parallel",  # noqa: E501
                        "delegate_inline": f"Inline: {call.tool_args.get('target_agent', '')}" if call.tool_args.get('target_agent') else "Inline delegation",  # noqa: E501
                        "propose_str_replace": f"Staging edit: {call.tool_args.get('path', '')[:80]}" if call.tool_args.get('path') else "Staging edit proposal",  # noqa: E501
                        "propose_write_file": f"Staging write: {call.tool_args.get('path', '')[:80]}" if call.tool_args.get('path') else "Staging write proposal",  # noqa: E501
                        "apply_proposed_edit": f"Applying edit: {call.tool_args.get('path', '')[:80]}" if call.tool_args.get('path') else "Applying staged edit",  # noqa: E501
                        "add_subgoal": "Adding subgoal",
                        "update_subgoal": (f"Updating subgoal: {call.tool_args.get('id', '')[:40]}"
                                            if call.tool_args.get('id') else "Updating subgoal"),
                        "create_plan": (f"Creating plan ({len(call.tool_args.get('steps') or [])} steps)"
                                         if call.tool_args.get('steps') else "Creating plan"),
                        "skill": (f"Loading skill: {call.tool_args.get('skill_name', '')[:40]}"
                                  if call.tool_args.get('skill_name') else "Loading skill"),
                        "best_of_n_edit": (f"Best-of-N edit: {call.tool_args.get('file_path', '')[:60]}"
                                            if call.tool_args.get('file_path')
                                            else "Best-of-N edit (N candidates)"),
                    }
                    _label = _label_map.get(call.tool_name, f"Running {call.tool_name}")
                    yield StreamChunk(text="", done=False, status=_label)
                    if _obs:
                        _obs.emit(
                            "tool_call",
                            tool=call.tool_name,
                            label=_label,
                            status="started",
                            tool_args=_inp,
                            iteration=iteration + 1,
                            todo_id=f"plan-{_plan_step_cursor}" if _plan_steps else None,
                            thought=result.raw_content or "", reasoning=_batch_reasoning,
                        )

                # Session 121: a narrated iteration is a step transition —
                # advance the plan before dispatching this batch so all its
                # (parallel) actions land under the new todo.
                _advance_plan_on_narration()

                # Dispatch all valid calls concurrently, but surface each tool's
                # completion AS IT FINISHES (B-10) instead of blocking on the whole
                # batch — a fast tool's card no longer waits for a slow sibling.
                # Model-context assembly below stays in INPUT order (deterministic).
                async def _dispatch_and_emit(idx: int, call, inp: str):
                    res = await _dispatch_single(call.tool_name, inp, call.tool_args)
                    tc_name, tc_obs, tc_failed, tc_lat, tc_provider = res
                    if _obs:
                        _obs.emit(
                            "tool_call",
                            tool=tc_name,
                            label="",
                            status="failed" if tc_failed else "done",
                            output=_truncate_observation(tc_obs),
                            latency_ms=tc_lat,
                            tool_args=inp,  # this call's input (the batch loop's _inp was stale)
                            iteration=iteration + 1,
                            todo_id=f"plan-{_plan_step_cursor}" if _plan_steps else None,
                            thought=result.raw_content or "",
                            reasoning=_batch_reasoning,
                            provider=tc_provider,
                        )
                    return idx, res

                _batch_tasks = [
                    asyncio.ensure_future(_dispatch_and_emit(i, call, inp))
                    for i, (call, inp) in enumerate(valid_calls)
                ]
                _results_by_idx: dict[int, tuple] = {}
                for _fut in asyncio.as_completed(_batch_tasks):
                    _idx, _res = await _fut
                    _results_by_idx[_idx] = _res
                    # Yield so the SSE bridge flushes the just-emitted tool_call
                    # event to the user now (as-completed streaming).
                    yield StreamChunk(text="", done=False, status=f"Done — {_res[0]} ({_res[3]}ms)")
                dispatch_results = [_results_by_idx[i] for i in range(len(valid_calls))]

                # Process all results and add to conversation context
                any_failed = False
                tool_messages: list[dict] = []
                for tc_name, tc_obs, tc_failed, tc_lat, tc_provider in dispatch_results:
                    observation_log += (
                        f"\n[Tool: {tc_name} | Status: {'FAILED' if tc_failed else 'OK'} | Latency: {tc_lat}ms]\n"
                        f"{_truncate_observation(tc_obs)}\n"
                    )
                    trace.steps.append(
                        AgentStep(
                            iteration=iteration + 1,
                            thought=result.raw_content or "",
                            tool_name=tc_name,
                            tool_input="",  # individual inputs not tracked in parallel
                            observation=_truncate_observation(tc_obs),
                            tool_failed=tc_failed,
                            retry_count=0,
                            latency_ms=tc_lat,
                        )
                    )
                    # The tool_call done/failed event is emitted per-tool as it
                    # completes (see _dispatch_and_emit above), not here.
                    if tc_failed:
                        any_failed = True

                    # Add tool result to context as proper tool messages
                    call_id = str(uuid.uuid4())
                    tool_messages.append(
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": tc_name,
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        }
                    )
                    tool_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": _truncate_observation(tc_obs),
                        }
                    )

                loop_messages.extend(tool_messages)

                if any_failed:
                    last_tool_failed = True
                    consecutive_failures += 1
                    fabrication_risk += 1  # Parallel tool failures increase fabrication risk
                    if _obs:
                        _obs.emit(
                            "fabrication_risk",
                            risk=fabrication_risk,
                            tool="multi",
                            iteration=iteration + 1,
                        )
                else:
                    last_tool_failed = False
                    consecutive_failures = 0

                continue

            # ── Handle ToolCallResult (model chose to use a tool) ─────
            if isinstance(result, ToolCallResult):
                result_usage = getattr(result, "usage", None)
                if result_usage:
                    _provider_usage.update(result_usage)
                    yield StreamChunk(text="", done=False, usage=dict(_provider_usage))
                tool_name = result.tool_name
                tool_args = result.tool_args
                tool_name, tool_args, corrected_system_call = _normalize_system_tool_call(
                    _user_message_text(messages),
                    tool_name,
                    tool_args,
                )
                if corrected_system_call:
                    logger.info(
                        "[agent.loop] corrected shell clock call to sysinfo for current system query"
                    )
                    if _obs:
                        _obs.emit(
                            "tool_call_corrected",
                            from_tool="shell",
                            to_tool="sysinfo",
                            reason="current time/date/day queries use the authoritative local clock",
                            iteration=iteration + 1,
                        )
                tool_input = _extract_tool_input(tool_name, tool_args)

                # Debug: log description from LLM
                logger.info(f"[agent.loop] tool_args description: {tool_args.get('description', 'NONE')}")

                # The model's content alongside a tool call is user-facing
                # NARRATION (chain-of-thought comes separately on the thinking
                # channel). Stream it to the user's chat as a brief progress line.
                _narration = _filter_system_leaks((result.raw_content or "").strip())
                if _narration:
                    yield StreamChunk(text=_narration[:400] + "\n\n", done=False)

                logger.info(
                    f"[agent.loop] iter={iteration + 1} tool_call={tool_name} args={json.dumps(tool_args)[:120]}"
                )

                # Guard: reject tool names outside the explicit objective policy.
                if effective_allowed is not None and tool_name not in effective_allowed:
                    allowed_list = ", ".join(sorted(effective_allowed))
                    observation = f"[Tool '{tool_name}' is not available in this objective policy. Allowed tools: {allowed_list}]"  # noqa: E501
                    logger.warning(f"[agent.loop] rejected tool name by explicit policy: {tool_name!r}")
                    last_tool_failed = True
                    consecutive_failures += 1
                    observation_log += f"\n[Tool: {tool_name} | Status: BLOCKED (policy)]\n{observation}\n"
                    continue

                if tool_name not in AGENT_ALLOWED_TOOLS:
                    allowed_list = ", ".join(sorted(AGENT_ALLOWED_TOOLS))
                    observation = f"[Tool '{tool_name}' is not available. Available tools: {allowed_list}]"
                    logger.warning(f"[agent.loop] rejected tool name: {tool_name!r}")
                    last_tool_failed = True
                    consecutive_failures += 1
                    observation_log += f"\n[Tool: {tool_name} | Status: BLOCKED (not in allowlist)]\n{observation}\n"
                    trace.steps.append(
                        AgentStep(
                            iteration=iteration + 1,
                            thought=result.raw_content or "",
                            tool_name=tool_name,
                            tool_input=tool_input,
                            observation=observation,
                            tool_failed=True,
                            retry_count=0,
                            latency_ms=llm_ms,
                        )
                    )
                    # Add the failed tool call + result to conversation context
                    # so the model can see its mistake and correct itself.
                    call_id = str(uuid.uuid4())
                    loop_messages.append(
                        {
                            "role": "assistant",
                            "content": result.raw_content or "",
                            "tool_calls": [
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": json.dumps(tool_args),
                                    },
                                }
                            ],
                        }
                    )
                    loop_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": observation,
                        }
                    )
                    continue

                # ── Validate required args before dispatch ──────────────────
                # Reject tool calls missing required parameters (e.g. file_write
                # without 'path' or 'content'). This gives the model a clear
                # error message so it can self-correct instead of dispatching
                # a doomed tool call that wastes an iteration.
                if tool_name == "file_write":
                    _fw_path = tool_args.get("path", "").strip()
                    _fw_content = tool_args.get("content", "").strip()
                    if not _fw_path or not _fw_content:
                        observation = (
                            f"[file_write REJECTED: missing required args. "
                            f"You MUST provide both 'path' (got: {_fw_path!r}) and "
                            f"'content' (got: {_fw_content[:50]!r}...). "
                            f"Call file_write again with BOTH arguments filled in.]"
                        )
                        logger.warning(
                            f"[agent.loop] file_write missing required args: "
                            f"path={_fw_path!r}, content_len={len(_fw_content)}"
                        )
                        last_tool_failed = True
                        consecutive_failures += 1
                        observation_log += (
                            f"\n[Tool: {tool_name} | Status: REJECTED (missing required args)]\n{observation}\n"
                        )
                        trace.steps.append(
                            AgentStep(
                                iteration=iteration + 1,
                                thought=result.raw_content or "",
                                tool_name=tool_name,
                                tool_input=tool_input,
                                observation=observation,
                                tool_failed=True,
                                retry_count=0,
                                latency_ms=llm_ms,
                            )
                        )
                        call_id = str(uuid.uuid4())
                        loop_messages.append(
                            {
                                "role": "assistant",
                                "content": result.raw_content or "",
                                "tool_calls": [
                                    {
                                        "id": call_id,
                                        "type": "function",
                                        "function": {
                                            "name": tool_name,
                                            "arguments": json.dumps(tool_args),
                                        },
                                    }
                                ],
                            }
                        )
                        loop_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call_id,
                                "content": observation,
                            }
                        )
                        continue

                # Semantic validation: reject empty or degenerate inputs
                if not tool_input or len(tool_input.strip("?. \t")) < 3:
                    observation = (
                        f"[Action rejected: input for '{tool_name}' is empty or too short. "
                        f"Provide a specific, meaningful input and try again.]"
                    )
                    logger.warning(f"[agent.loop] rejected degenerate input for tool={tool_name!r}: {tool_input!r}")
                    last_tool_failed = True
                    consecutive_failures += 1
                    observation_log += f"\n[Tool: {tool_name} | Status: REJECTED (bad input)]\n{observation}\n"
                    trace.steps.append(
                        AgentStep(
                            iteration=iteration + 1,
                            thought=result.raw_content or "",
                            tool_name=tool_name,
                            tool_input=tool_input,
                            observation=observation,
                            tool_failed=True,
                            retry_count=0,
                            latency_ms=llm_ms,
                        )
                    )
                    call_id = str(uuid.uuid4())
                    loop_messages.append(
                        {
                            "role": "assistant",
                            "content": result.raw_content or "",
                            "tool_calls": [
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": json.dumps(tool_args),
                                    },
                                }
                            ],
                        }
                    )
                    loop_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": observation,
                        }
                    )
                    continue

                # Deduplication: skip a tool call we've already made this turn
                call_fingerprint = (tool_name, tool_input.lower().strip())
                if call_fingerprint in _call_cache:
                    cached_obs = _call_cache[call_fingerprint]
                    logger.info(f"[agent.loop] dedup hit for tool={tool_name!r} — returning cached result")
                    observation_log += (
                        f"\n[Tool: {tool_name} | Input: {tool_input[:60]} | Status: CACHED]\n"
                        f"{_truncate_observation(cached_obs)}\n"
                    )
                    trace.steps.append(
                        AgentStep(
                            iteration=iteration + 1,
                            thought=result.raw_content or "",
                            tool_name=tool_name,
                            tool_input=tool_input,
                            observation=f"[cached] {cached_obs[:200]}",
                            tool_failed=False,
                            retry_count=0,
                            latency_ms=llm_ms,
                        )
                    )
                    # Add cached result as tool message
                    call_id = str(uuid.uuid4())
                    loop_messages.append(
                        {
                            "role": "assistant",
                            "content": result.raw_content or "",
                            "tool_calls": [
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": json.dumps(tool_args),
                                    },
                                }
                            ],
                        }
                    )
                    loop_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": cached_obs,
                        }
                    )
                    continue

                # ── Bug B fix: name-level dedup for file_write ──────────
                # If the agent already called file_write for a given path
                # in this turn, reject the duplicate. This prevents double
                # writes where the model calls file_write, sees the result,
                # then calls file_write again on the same path with slightly
                # different content (often due to retrying or re-planning).
                if tool_name == "file_write":
                    _write_path = tool_args.get("path", "").strip().lower()
                    if _write_path and _write_path in _file_write_paths:
                        logger.info(
                            f"[agent.loop] name-level dedup: file_write already "
                            f"called for path={_write_path!r} — returning cached result"
                        )
                        # Use the cached observation if available, otherwise
                        # tell the model it already wrote this file
                        _path_key = (tool_name, tool_input.lower().strip())
                        cached_write_obs = _call_cache.get(
                            _path_key,
                            f"[file_write already executed for '{tool_args.get('path', '')}' "
                            f"in this turn. Do not write the same file again.]",
                        )
                        observation_log += (
                            f"\n[Tool: {tool_name} | Path: {_write_path} | Status: CACHED (name-level dedup)]\n"
                            f"{_truncate_observation(cached_write_obs)}\n"
                        )
                        trace.steps.append(
                            AgentStep(
                                iteration=iteration + 1,
                                thought=result.raw_content or "",
                                tool_name=tool_name,
                                tool_input=tool_input,
                                observation=f"[name-dedup] {cached_write_obs[:200]}",
                                tool_failed=False,
                                retry_count=0,
                                latency_ms=llm_ms,
                            )
                        )
                        call_id = str(uuid.uuid4())
                        loop_messages.append(
                            {
                                "role": "assistant",
                                "content": result.raw_content or "",
                                "tool_calls": [
                                    {
                                        "id": call_id,
                                        "type": "function",
                                        "function": {
                                            "name": tool_name,
                                            "arguments": json.dumps(tool_args),
                                        },
                                    }
                                ],
                            }
                        )
                        loop_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call_id,
                                "content": cached_write_obs,
                            }
                        )
                        continue

                # ── Dispatch the tool ──────────────────────────────────
                # Use LLM-provided description from tool_args, fallback to
                # structured label built from tool_args fields (path, command,
                # query) — NOT from raw concatenated tool_input which may be
                # empty or malformed when the model sends incomplete args.
                logger.info(f"[agent.loop] full tool_args: {tool_args}")
                action_label = tool_args.get("description")
                logger.info(f"[agent.loop] description from LLM: {action_label}")
                if not action_label:
                    # Build label from structured tool_args, not raw tool_input.
                    # This prevents empty labels like "Creating file: :" when
                    # the model sends empty args — we extract the actual path,
                    # command, or query from the args dict instead.
                    _path = tool_args.get("path", "")
                    _command = tool_args.get("command", "")
                    _query = tool_args.get("query", "")
                    _code_preview = tool_args.get("code", "")[:40]
                    action_labels = {
                        "file_write": f"Creating file: {_path[:80]}" if _path else "Creating file",
                        "edit_file": f"Editing file: {_path[:80]}" if _path else "Editing file",
                        "code_exec": f"Executing: {_code_preview}..." if _code_preview else "Executing code",
                        "web_search": f"Searching: {_query[:80]}" if _query else "Searching the web",
                        "web_fetch": f"Fetching: {tool_args.get('url', '')[:80]}" if tool_args.get("url") else "Fetching page",  # noqa: E501
                        "file_task": f"Reading: {_path[:80]}" if _path else "Reading file",
                        "shell": f"Running: {_command[:80]}" if _command else "Running command",
                        "memory_op": f"Memory: {tool_args.get('operation', '')} {tool_args.get('content', '')[:40]}".strip(),  # noqa: E501
                        "sysinfo": f"System info: {_query[:60]}" if _query else "Getting system info",
                        "observe": f"Observing: {_query[:60]}" if _query else "Observing the desktop",
                        "calculator": f"Calculating: {_query[:60]}" if _query else "Calculating",
                        "csv": f"Reading CSV: {_query[:60]}" if _query else "Reading CSV",
                        "json": f"Querying JSON: {_query[:60]}" if _query else "Querying JSON",
                        "sql": f"Querying DB: {_query[:60]}" if _query else "Querying database",
                        "git": f"Git: {tool_args.get('operation', '')}" if tool_args.get('operation') else "Git operation",  # noqa: E501
                        "process": f"Process: {tool_args.get('operation', '')} {tool_args.get('name', '')}" if tool_args.get('operation') else "Process operation",  # noqa: E501
                        "diagnostics": f"Diagnostics: {tool_args.get('operation', '')}" if tool_args.get('operation') else "Analyzing failure",  # noqa: E501
                        "browse": f"Browser: {tool_args.get('action', '')}" if tool_args.get('action') else "Using browser",  # noqa: E501
                        "describe_tool": f"Loading tool docs: {tool_args.get('tool_name', '')}" if tool_args.get('tool_name') else "Loading tool docs",  # noqa: E501
                    }
                    action_label = action_labels.get(tool_name, f"Running {tool_name}")
                # Session 121: narrated iteration → step transition; the new
                # tool call belongs to the next plan todo.
                _advance_plan_on_narration()
                logger.info(
                    f"[agent.loop] iter={iteration + 1} tool={tool_name} input={tool_input[:80]} — {action_label}"
                )
                if _obs:
                    _obs.emit(
                        "tool_call",
                        tool=tool_name,
                        label=action_label,
                        status="started",
                        tool_args=tool_input,
                        iteration=iteration + 1,
                        todo_id=f"plan-{_plan_step_cursor}" if _plan_steps else None,
                        thought=result.raw_content or "", reasoning=_step_reasoning(),
                    )

                # ── Yield intermediate status to the user so they see real-time ──
                # feedback during tool execution. Without this, the user sees only
                # "Generating response..." until the entire tool call cycle completes.
                # v0.10: Use status field for the thinking area, text field for
                # minimal inline feedback. The status shows in the ThinkingBlock
                # component, while the text appears briefly before the final answer.
                yield StreamChunk(text="", done=False, status=action_label)

                t_tool = time.monotonic()
                tool_failed = False
                retry_count = 0
                observation = ""

                try:
                    tool_intent = Intent(tool_name)

                    # ── file_write: validate and use typed contract ──────────
                    # Guard: if the model calls file_write without a meaningful
                    # content arg (e.g. placeholder like "read", "code", "yes"),
                    # REJECT the call so the model can self-correct.
                    # Previously this redirected to file_task (read), but that
                    # caused "not_found" errors when the file didn't exist yet
                    # (the user wanted to CREATE it, not READ it).
                    if tool_name == "file_write":
                        _content = tool_args.get("content", "")
                        _path = tool_args.get("path", "")
                        if not _content or len(_content.strip()) < 5:
                            logger.info(
                                f"[agent.loop] file_write called without meaningful content "
                                f"(path={_path!r}, content={_content.strip()[:20]!r}) — rejecting"
                            )
                            observation = (
                                f"[file_write REJECTED: content is too short "
                                f"({len(_content.strip())} chars: {_content.strip()[:30]!r}). "
                                f"You MUST provide the actual file content, not a placeholder. "
                                f"Call file_write again with meaningful content in the 'content' field.]"
                            )
                            last_tool_failed = True
                            consecutive_failures += 1
                            observation_log += (
                                f"\n[Tool: {tool_name} | Status: REJECTED (content too short)]\n{observation}\n"
                            )
                            trace.steps.append(
                                AgentStep(
                                    iteration=iteration + 1,
                                    thought=result.raw_content or "",
                                    tool_name=tool_name,
                                    tool_input=tool_input,
                                    observation=observation,
                                    tool_failed=True,
                                    retry_count=0,
                                    latency_ms=llm_ms,
                                )
                            )
                            call_id = str(uuid.uuid4())
                            loop_messages.append(
                                {
                                    "role": "assistant",
                                    "content": result.raw_content or "",
                                    "tool_calls": [
                                        {
                                            "id": call_id,
                                            "type": "function",
                                            "function": {
                                                "name": tool_name,
                                                "arguments": json.dumps(tool_args),
                                            },
                                        }
                                    ],
                                }
                            )
                            loop_messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": call_id,
                                    "content": observation,
                                }
                            )
                            continue

                    if tool_name == "file_write":
                        try:
                            from tools.contracts.base import ToolRegistry

                            contract_cls = ToolRegistry.get("file_write")
                            file_payload = {
                                "path": tool_args.get("path", ""),
                                "content": tool_args.get("content", ""),
                            }
                            tool_result = await contract_cls().execute(file_payload)
                            tool_failed = not tool_result.success if tool_result else True
                            retry_count = 0
                        except KeyError:
                            # Contract not registered — fall back to legacy dispatch
                            logger.warning("[agent.loop] FileWriteContract not in registry, using legacy dispatch")
                            tool_result, tool_failed, retry_count = await dispatch_with_retry(
                                tool_intent,
                                tool_input,
                                allowed_tool_names=effective_allowed,
                            )

                    elif tool_name == "edit_file":
                        # edit_file: use typed contract path (like file_write)
                        try:
                            from tools.contracts.base import ToolRegistry

                            contract_cls = ToolRegistry.get("edit_file")
                            edit_payload = dict(tool_args)  # pass all args as payload
                            tool_result = await contract_cls().execute(edit_payload)
                            tool_failed = not tool_result.success if tool_result else True
                            retry_count = 0
                        except KeyError:
                            # Contract not registered — fall back to legacy dispatch
                            logger.warning("[agent.loop] EditFileContract not in registry, using legacy dispatch")
                            tool_result, tool_failed, retry_count = await dispatch_with_retry(
                                tool_intent,
                                tool_input,
                                allowed_tool_names=effective_allowed,
                            )

                        # Bridge diff metadata from edit_file tool results.
                        # Emit a file_diff obs event so the frontend DiffBlock can
                        # render green/red highlighted diffs — like Cursor/Claude.
                        if tool_result and tool_result.metadata and tool_result.source == "edit_file":
                            diff_hunks = tool_result.metadata.get("diff_hunks", [])
                            if diff_hunks and _obs:
                                _obs.emit(
                                    "file_diff",
                                    diff_hunks=diff_hunks,
                                    diff_language=tool_result.metadata.get("diff_language", ""),
                                    path=tool_result.metadata.get("path", ""),
                                    diff_additions=tool_result.metadata.get("diff_additions", 0),
                                    diff_deletions=tool_result.metadata.get("diff_deletions", 0),
                                )

                    else:
                        tool_result, tool_failed, retry_count = await dispatch_with_retry(
                            tool_intent,
                            tool_input,
                            adapter=active_adapter,
                            allowed_tool_names=effective_allowed,
                        )

                    # ADR-40 option C: a describe_tool call loads the named
                    # long-tail tool into this run's native tools param.
                    _note_described_tool(tool_name, tool_result, loaded_tools)
                    _emit_todo_write_events(tool_name, tool_result, _obs)

                    latency_ms = round((time.monotonic() - t_tool) * 1000)

                    if tool_result:
                        if tool_intent == Intent.CODE_EXEC:
                            safe_obs = _filter_code_output(tool_result.content)
                        else:
                            safe_obs = _filter_tool_injection(tool_result.content)

                        # Structured error context + a concrete recovery step
                        # (B-2026-08-18-9) so a tool error is never a dead end.
                        if not tool_result.success and tool_result.error_type:
                            safe_obs = (
                                f"[Tool '{tool_name}' returned error_type={tool_result.error_type!r}]\n"
                                + safe_obs
                                + "\n[RECOVERY]: "
                                + tool_error_recovery_directive(tool_name, tool_result.error_type)
                            )

                        # Search results are an intermediate observation, not
                        # the answer. The parent must receive them as a tool
                        # message and decide whether to fetch, replan, verify,
                        # or synthesize a final response on the next iteration.
                        # The old web-search shortcut called the synthesizer
                        # here and emitted `done`, which detached the agent
                        # from its own evidence loop.
                        observation = safe_obs
                        _call_cache[call_fingerprint] = safe_obs

                        # Bug B fix: track file_write paths for name-level dedup
                        if tool_name == "file_write":
                            _written_path = tool_args.get("path", "").strip().lower()
                            if _written_path:
                                _file_write_paths.add(_written_path)

                        # ── Post-execution verification ───────────────────────
                        # After certain tool executions, verify the result to catch
                        # silent failures and give the model feedback for self-correction.
                        if VERIFY_ENABLED and not tool_failed:
                            verify_obs = await self._verify_tool_result(
                                tool_name=tool_name,
                                tool_args=tool_args,
                                observation=safe_obs,
                                allowed_tool_names=effective_allowed,
                                result_path=(tool_result.metadata or {}).get("path"),
                            )
                            if verify_obs:
                                observation += f"\n[VERIFICATION]: {verify_obs}"
                                trace.verification_results.append(verify_obs)

                        # ── Grounding verification ───────────────────────────────
                        # After successful file_write, emit a grounding_check obs event
                        # with the result of reading the file back. This makes the
                        # verification observable to the frontend and creates an
                        # explicit audit trail for the grounding check.
                        if tool_name == "file_write" and not tool_failed:
                            # S293: verify WHERE THE WRITE ACTUALLY LANDED
                            # (tool_result.metadata["path"]), not the model's
                            # requested arg. They diverge whenever file_write
                            # re-anchors a path or timestamp-renames a document —
                            # verifying the raw arg then read-back-failed a
                            # perfectly good write and injected a false
                            # [GROUNDING CHECK FAILED] (B-2026-08-17-6).
                            _grounding_path = (tool_result.metadata or {}).get("path") or tool_args.get("path", "")
                            if _grounding_path and _obs:
                                try:
                                    # NOTE: dispatch_with_retry is imported at module level (line 177).
                                    # Do NOT re-import it here — that would shadow the module-level
                                    # binding and cause UnboundLocalError in closures like
                                    # _dispatch_single() and _write_files().
                                    (
                                        _grounding_result,
                                        _grounding_failed,
                                        _,
                                    ) = await dispatch_with_retry(
                                        Intent.FILE_TASK,
                                        _grounding_path,
                                        max_retries=0,
                                        allowed_tool_names=effective_allowed,
                                    )
                                    _grounding_ok = (
                                        not _grounding_failed and _grounding_result and _grounding_result.success
                                    )
                                    _grounding_content_len = (
                                        len(_grounding_result.content)
                                        if _grounding_result and _grounding_result.content
                                        else 0
                                    )
                                    _obs.emit(
                                        "grounding_check",
                                        tool="file_write",
                                        path=_grounding_path,
                                        verified=_grounding_ok,
                                        content_length=_grounding_content_len,
                                        iteration=iteration + 1,
                                    )
                                    if not _grounding_ok:
                                        observation += (
                                            f"\n[GROUNDING CHECK FAILED]: file_write for '{_grounding_path}' "
                                            f"could not be verified — the file may not exist or may be empty. "
                                            f"Do NOT claim the file was created successfully."
                                        )
                                        fabrication_risk += 1
                                        logger.warning(
                                            f"[agent.loop] grounding check FAILED for file_write: "
                                            f"path={_grounding_path!r}"
                                        )
                                except Exception as _ge:
                                    logger.warning(f"[agent.loop] grounding check error (non-fatal): {_ge}")

                        # ── Terminal bridge: emit tool output to the terminal panel ──
                        # Forward ALL tool executions to the terminal panel so the user
                        # sees what the AI is doing in real-time. Shell/code_exec show
                        # as command+output. Other tools (file_task, file_write, etc.)
                        # show as labeled operations with their results.
                        if _obs:
                            _term_command = tool_input
                            _term_output = safe_obs
                            _term_success = not tool_failed
                            # Generate a descriptive label for non-shell tools
                            _term_label = action_label
                            _obs.emit(
                                "terminal_output",
                                tool=tool_name,
                                command=_term_command,
                                output=_term_output[:5000],
                                success=str(_term_success),
                                latency_ms=str(latency_ms),
                                label=str(_term_label),
                                tool_args=json.dumps(tool_args)[:500] if tool_args else "",
                            )

                        last_tool_failed = False
                        consecutive_failures = 0

                        # Yield completion status so user sees the tool finished
                        if not tool_failed:
                            yield StreamChunk(
                                text="",
                                done=False,
                                status=f"Done — {action_label} ({latency_ms}ms)",
                            )

                        if retry_count > 0:
                            yield StreamChunk(
                                text=f"*(succeeded after {retry_count} retr{'y' if retry_count == 1 else 'ies'})*\n",
                                done=False,
                            )
                    else:
                        observation = f"[Tool '{tool_name}' returned no result after {retry_count} retries]"
                        tool_failed = True
                        latency_ms = round((time.monotonic() - t_tool) * 1000)

                except (ValueError, Exception) as exc:
                    observation = f"[Tool '{tool_name}' failed: {exc}]"
                    tool_failed = True
                    retry_count = 0
                    latency_ms = round((time.monotonic() - t_tool) * 1000)

                if tool_failed:
                    last_tool_failed = True
                    consecutive_failures += 1
                    fabrication_risk += 1  # Tool errors increase fabrication risk
                    if _obs:
                        _obs.emit(
                            "tool_call",
                            tool=tool_name,
                            label=action_label,
                            status="failed",
                            output=_truncate_observation(observation),
                            latency_ms=latency_ms,                                            tool_args=tool_input,
                                            iteration=iteration + 1,
                                            todo_id=f"plan-{_plan_step_cursor}" if _plan_steps else None,
                                            thought=result.raw_content or "", reasoning=_step_reasoning(),
                                            provider=_tool_provider(tool_result),
                                        )
                        _obs.emit(
                            "fabrication_risk",
                            risk=fabrication_risk,
                            tool=tool_name,
                            iteration=iteration + 1,
                        )
                else:
                    if _obs:
                        _obs.emit(
                            "tool_call",
                            tool=tool_name,
                            label=action_label,
                            status="done",
                            output=_truncate_observation(observation),
                            latency_ms=latency_ms,                                            tool_args=tool_input,
                                            iteration=iteration + 1,
                                            todo_id=f"plan-{_plan_step_cursor}" if _plan_steps else None,
                                            thought=result.raw_content or "", reasoning=_step_reasoning(),
                                            provider=_tool_provider(tool_result),

                                        )

                trace.steps.append(
                    AgentStep(
                        iteration=iteration + 1,
                        thought=result.raw_content or "",
                        tool_name=tool_name,
                        tool_input=tool_input,
                        observation=observation[:500],
                        tool_failed=tool_failed,
                        retry_count=retry_count,
                        latency_ms=latency_ms,
                    )
                )
                # ANTI-FABRICATION: Only append to observation_log for FAILED
                # tool calls. For successful calls, the tool messages below
                # ARE the observation — adding to observation_log too causes
                # dual injection (the same data appears in both a "user" role
                # message via observation_log AND as a "tool" role message),
                # which wastes context tokens and can cause the model to
                # truncate earlier critical context, leading to fabrication.
                if tool_failed:
                    observation_log += (
                        f"\n[Tool: {tool_name} | Input: {tool_input[:60]} | "
                        f"Status: FAILED | {latency_ms}ms]\n"
                        f"{_truncate_observation(observation)}\n"
                    )

                # Add the tool call + result to conversation context
                # so the model can reason about what happened and decide next.
                # ANTI-FABRICATION: Prepend a strong instruction to the tool
                # result telling the model to use ONLY the actual output.
                call_id = str(uuid.uuid4())
                loop_messages.append(
                    {
                        "role": "assistant",
                        "content": result.raw_content or "",
                        "tool_calls": [
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(tool_args),
                                },
                            }
                        ],
                    }
                )
                # Anti-fabrication wrapper: the model MUST base its response
                # on the actual tool output. Without this, models (especially
                # smaller ones like MiniMax M2.5) sometimes ignore the tool
                # result and fabricate plausible-looking but false data.
                if not tool_failed and observation:
                    safe_observation = (
                        f"[ACTUAL TOOL OUTPUT — use ONLY this data in your response]\n"
                        f"{observation}\n"
                        f"[END TOOL OUTPUT — do NOT invent or add items not shown above]"
                    )
                else:
                    safe_observation = observation
                loop_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": safe_observation,
                    }
                )

                # ── ADR-42: Thinker consult on the first real evidence ──────
                # A silent, read-only reasoning pass on what was just GATHERED
                # (not the raw request) — streams genuine reasoning to the
                # ThinkingBlock and feeds a next-step/facts/ambiguities analysis
                # forward to shape the next action. Gated: once per turn, only
                # tool-capable intents, only when the model actually reasons
                # (thinking enabled), only on a real successful observation. Any
                # failure/timeout is swallowed — the Thinker never blocks a turn.
                if (
                    not _thinker_consulted
                    and not tool_failed
                    and observation
                    and intent in AGENT_INTENTS
                    and getattr(active_adapter, "thinking_enabled", False)
                ):
                    _thinker_consulted = True
                    try:
                        from core.agent.thinker import Evidence, Thinker

                        _ev = Evidence(
                            objective=(initialization.objective if initialization else ""),
                            user_message=_user_message_text(loop_messages),
                            observations="\n".join(
                                f"[{s.tool_name}] {s.observation}" for s in trace.steps if s.observation
                            ),
                            last_action=tool_name,
                            iteration=iteration + 1,
                        )
                        if _ev.has_evidence:
                            if _obs:
                                _obs.emit("agent_thinker_start", iteration=iteration + 1)
                            _thinker = Thinker(
                                timeout_secs=_reasoning_setting(
                                    "localmind_reasoning_plan_timeout_secs", REASONING_PLAN_TIMEOUT_SECS
                                )
                            )
                            async for _tc in _thinker.consult(_ev, active_adapter):
                                if _tc.thinking:
                                    yield StreamChunk(text="", thinking=_tc.thinking, done=False)
                            _analysis = _thinker.last_analysis
                            if _analysis and not _analysis.is_empty:
                                loop_messages.append(
                                    {"role": "user", "content": _thinker_context_block(_analysis)}
                                )
                                # B-2026-08-16-12: preserve a user-facing
                                # rendering of the analysis on the trace so the
                                # degraded-evidence fallback can surface the
                                # already-computed synthesis instead of
                                # discarding it when the final model call fails
                                # (e.g. a provider 429 on the synthesis turn).
                                trace.thinker_analysis = _thinker_user_summary(_analysis)
                                if _obs:
                                    _obs.emit(
                                        "agent_thinker_done",
                                        iteration=iteration + 1,
                                        next_step=_analysis.next_step[:200],
                                        facts=len(_analysis.facts),
                                        ambiguities=len(_analysis.ambiguities),
                                    )
                    except Exception as _thx:  # never let the Thinker break a turn
                        logger.warning("[agent.loop] Thinker consult skipped: %s", _thx)

                # ADR-34 B-8: tool output must NOT become the final assistant
                # answer. The parent model receives the evidence as a tool
                # message and synthesizes its own response on the next
                # iteration. The previous "authoritative sysinfo" shortcut
                # extracted the raw "Current date/time: ..." line and yielded
                # it directly — that violated the evidence/synthesis boundary
                # (tool output was the final chat content, not parent
                # synthesis). The model may still choose to report the
                # date/time verbatim, but that is the model's decision, not
                # a code shortcut.
                if _obs:
                    _obs.emit(
                        "evidence_to_parent",
                        tool=tool_name,
                        iteration=iteration + 1,
                        evidence_chars=len(safe_observation),
                        failed=tool_failed,
                    )

                # Continue the loop — the model will see the tool result
                # and decide whether to use another tool or synthesize a
                # final answer from the evidence.
                continue

            # ── Handle streaming text (model chose NOT to use tools) ───
            # This is the final answer — OR the model emitted tool-call XML
            # as text content instead of using the structured tool_calls API.
            # We stream it incrementally for real-time feedback, with:
            # 1. Early MiniMax tool-call XML interception (execute the tool!)
            # 2. Tool-talk detection (model narrating intent instead of calling)
            # 3. Fabrication detection (text answer without any tool calls)
            else:
                # ── Phase 0: Buffer enough text for MiniMax tool-call detection ──
                # MiniMax M2.5 outputs <invoke name="web_search">...</invoke> as
                # TEXT content, not structured tool_calls. We need to buffer enough
                # text to detect this pattern before streaming to the user.
                # If we detect a tool call in the text, we intercept it, execute
                # the tool, and feed the result back into the loop.
                #
                # v0.10: Increased buffer from 800 to 2000 chars. MiniMax M2.5
                # sometimes outputs a long text prefix (e.g. "Let me search for
                # the weather in Cheptais. I'll use the web search tool.") BEFORE
                # the <invoke> XML, which can be 200-500+ chars. The old 800-char
                # limit meant the buffer could fill up with prefix text before the
                # XML arrived, causing us to miss the tool call entirely. Now we
                # also check incrementally — if we see "minimax:tool_call" or
                # "<invoke" appearing mid-buffer, we keep reading.
                _MINIMAX_CHECK_CHARS = 2000
                _MINIMAX_MAX_BUFFER = 4000  # hard cap to prevent infinite buffering
                _minimax_buffer = ""
                _minimax_chunks: list[StreamChunk] = []
                _minimax_stream_ended = False
                _minimax_error = False
                _streamed_reasoning = False  # Session 256: did this call stream thinking?
                _reasoning_buffer = ""  # B-2026-08-18-11: capture the reasoning TEXT
                # (not just the flag). On GLM/thinking the model sometimes puts its
                # real answer/analysis in the reasoning channel and leaves content
                # empty; the endgame salvages this instead of failing the turn.
                _minimax_error_msg = ""  # Session 187: keep the adapter's error
                # message (e.g. "zen returned 429: …") — previously dropped, so
                # the frontend got error="" and rendered nothing.
                _minimax_partial_seen = False  # track if we've seen start of XML

                async for chunk in result:
                    # B-2026-08-02-2 (A2): abort check during stream buffering.
                    if abort_signal is not None and abort_signal.is_set():
                        raise AgentAbortedError("aborted during streaming")
                    filtered_text = _filter_system_leaks(chunk.text)
                    _minimax_buffer += filtered_text
                    if chunk.usage:
                        _provider_usage.update(chunk.usage)
                    _minimax_chunks.append(
                        StreamChunk(text=filtered_text, done=chunk.done, usage=dict(_provider_usage))
                    )
                    # ADR-41 (Session 254): forward the model's reasoning live
                    # as it streams (GLM thinking → ThinkingBlock). Reasoning is
                    # user-visible progress and never affects MiniMax/DSML
                    # tool-call detection (that only looks at TEXT), so it can
                    # be yielded immediately instead of buffered. Filtered for
                    # system-leak XML like the text path. (isinstance guard:
                    # test stubs may carry a truthy non-str .thinking.)
                    if isinstance(chunk.thinking, str) and chunk.thinking:
                        _streamed_reasoning = True
                        _reasoning_buffer += chunk.thinking
                        yield StreamChunk(
                            text="",
                            thinking=_filter_system_leaks(chunk.thinking),
                            done=False,
                            usage=dict(_provider_usage),
                        )
                    if chunk.error:
                        _minimax_error = True
                        if not _minimax_error_msg:
                            _minimax_error_msg = chunk.error
                    if chunk.done:
                        _minimax_stream_ended = True
                        break
                    # Check if we're seeing the START of a tool call XML.
                    # If so, keep reading even past the normal limit.
                    if _has_minimax_tool_call(_minimax_buffer):
                        # Complete tool call found — stop buffering
                        break
                    if _MINIMAX_PARTIAL_RE.search(_minimax_buffer) or _STANDALONE_PARTIAL_RE.search(
                        _normalize_dsml(_minimax_buffer)
                    ):
                        _minimax_partial_seen = True
                    if len(_minimax_buffer) >= _MINIMAX_CHECK_CHARS:
                        if _minimax_partial_seen:
                            # We're mid-tool-call — keep reading up to max buffer
                            if len(_minimax_buffer) >= _MINIMAX_MAX_BUFFER:
                                break
                            continue
                        # No sign of tool call — check one more time then break
                        break

                # ── Check for MiniMax tool-call XML in the buffered text ──
                _minimax_calls = _parse_minimax_tool_call(_minimax_buffer)

                if _minimax_calls and not _minimax_error:
                    # INTERCEPT: The model output a tool call as text!
                    # Parse it, execute the tool, and feed results back.
                    logger.info(
                        f"[agent.loop] iter={iteration + 1} MINIMAX TOOL CALL INTERCEPTED: "
                        f"{len(_minimax_calls)} call(s) — {[c[0] for c in _minimax_calls]}"
                    )
                    if _obs:
                        _obs.emit(
                            "minimax_tool_call_intercepted",
                            tools=[c[0] for c in _minimax_calls],
                            iteration=iteration + 1,
                        )

                    # Drain remaining chunks from the stream
                    if not _minimax_stream_ended:
                        async for _ in result:
                            pass

                    # Process each intercepted tool call
                    for tc_name, tc_args, tc_raw_xml in _minimax_calls:
                        # Normalize MiniMax parameter names to match our tool definitions
                        # MiniMax uses <parameter name="text"> for the query argument
                        _normalized_args = dict(tc_args)
                        if tc_name == "web_search" and "text" in _normalized_args and "query" not in _normalized_args:
                            _normalized_args["query"] = _normalized_args.pop("text")
                        if tc_name == "web_fetch" and "text" in _normalized_args and "url" not in _normalized_args:
                            _normalized_args["url"] = _normalized_args.pop("text")

                        # Check allowlist
                        if tc_name not in AGENT_ALLOWED_TOOLS:
                            logger.warning(f"[agent.loop] minimax intercept: rejected tool {tc_name!r}")
                            allowed_list = ", ".join(sorted(AGENT_ALLOWED_TOOLS))
                            observation = f"[Tool '{tc_name}' is not available. Available tools: {allowed_list}]"
                            call_id = str(uuid.uuid4())
                            loop_messages.append(
                                {
                                    "role": "assistant",
                                    "content": _strip_minimax_tool_calls(_minimax_buffer),
                                }
                            )
                            loop_messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        f"You tried to call tool '{tc_name}' but it's not available. "
                                        f"Available tools: {allowed_list}. Try a different approach."
                                    ),
                                }
                            )
                            continue

                        # Extract tool input from normalized args
                        tool_input = _extract_tool_input(tc_name, _normalized_args)

                        if not tool_input or len(tool_input.strip("?. \t")) < 3:
                            logger.warning(
                                f"[agent.loop] minimax intercept: degenerate input for {tc_name!r}: {tool_input!r}"
                            )
                            loop_messages.append(
                                {
                                    "role": "assistant",
                                    "content": _strip_minimax_tool_calls(_minimax_buffer),
                                }
                            )
                            loop_messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        f"Your tool call for '{tc_name}' had empty or too-short input. "
                                        f"Call it again with a specific, meaningful input."
                                    ),
                                }
                            )
                            continue

                        # Build action label for user feedback
                        _path = _normalized_args.get("path", "")
                        _command = _normalized_args.get("command", "")
                        _query = _normalized_args.get("query", "")
                        _url = _normalized_args.get("url", "")
                        _label_map = {
                            "web_search": f"Searching: {_query[:80]}" if _query else "Searching the web",
                            "web_fetch": f"Fetching: {_url[:80]}" if _url else "Fetching web page",
                            "shell": f"Running: {_command[:80]}" if _command else "Running command",
                            "file_task": f"Reading: {_path[:80]}" if _path else "Reading file",
                            "code_exec": "Executing code",
                            "memory_op": f"Memory: {_normalized_args.get('operation', '')} {_normalized_args.get('content', '')[:40]}".strip(),  # noqa: E501
                            "sysinfo": f"System info: {_query[:60]}" if _query else "Getting system info",
                        "observe": f"Observing: {_query[:60]}" if _query else "Observing the desktop",
                        "calculator": f"Calculating: {_query[:60]}" if _query else "Calculating",
                        "csv": f"Reading CSV: {_query[:60]}" if _query else "Reading CSV",
                        "json": f"Querying JSON: {_query[:60]}" if _query else "Querying JSON",
                        "sql": f"Querying DB: {_query[:60]}" if _query else "Querying database",
                        "describe_tool": f"Loading tool docs: {_normalized_args.get('tool_name', '')}" if _normalized_args.get('tool_name') else "Loading tool docs",  # noqa: E501
                        }
                        action_label = _label_map.get(tc_name, f"Running {tc_name}")

                        # Emit status to user — v0.10: use status field
                        yield StreamChunk(text="", done=False, status=action_label)
                        if _obs:
                            _obs.emit(
                                "tool_call",
                                tool=tc_name,
                                label=action_label,
                                status="started",
                                iteration=iteration + 1,
                                todo_id=f"plan-{_plan_step_cursor}" if _plan_steps else None,
                                thought=result.raw_content or "", reasoning=_step_reasoning(),
                            )

                        # Dispatch the tool
                        t_tool = time.monotonic()
                        tool_failed = False
                        try:
                            tool_intent = Intent(tc_name)
                            tool_result, tool_failed, retry_count = await dispatch_with_retry(
                                tool_intent,
                                tool_input,
                                adapter=active_adapter,
                                obs=_obs,  # ADR-18 P3: delegation streams into the UI
                                allowed_tool_names=effective_allowed,
                            )
                            _note_described_tool(tc_name, tool_result, loaded_tools)
                            _emit_todo_write_events(tc_name, tool_result, _obs)
                            latency_ms = round((time.monotonic() - t_tool) * 1000)

                            if tool_result:
                                if tool_intent == Intent.CODE_EXEC:
                                    safe_obs = _filter_code_output(tool_result.content)
                                else:
                                    safe_obs = _filter_tool_injection(tool_result.content)

                                # Structured error context + a concrete recovery
                                # step (B-2026-08-18-9) — never a dead end.
                                if not tool_result.success and tool_result.error_type:
                                    safe_obs = (
                                        f"[Tool '{tc_name}' returned error_type={tool_result.error_type!r}]\n"
                                        + safe_obs
                                        + "\n[RECOVERY]: "
                                        + tool_error_recovery_directive(tc_name, tool_result.error_type)
                                    )

                                # A text-encoded search call follows the same
                                # intermediate-observation contract as a native
                                # tool call. Do not synthesize or finish here.
                                observation = safe_obs

                                # Yield completion status
                                if not tool_failed:
                                    yield StreamChunk(
                                        text="",
                                        done=False,
                                        status=f"Done — {action_label} ({latency_ms}ms)",
                                    )

                                # Anti-fabrication wrapper
                                if not tool_failed and observation:
                                    safe_observation = (
                                        f"[ACTUAL TOOL OUTPUT — use ONLY this data in your response]\n"
                                        f"{observation}\n"
                                        f"[END TOOL OUTPUT — do NOT invent or add items not shown above]"
                                    )
                                else:
                                    safe_observation = observation

                                # Add tool call + result to conversation context
                                call_id = str(uuid.uuid4())
                                loop_messages.append(
                                    {
                                        "role": "assistant",
                                        "content": _strip_minimax_tool_calls(_minimax_buffer),
                                        "tool_calls": [
                                            {
                                                "id": call_id,
                                                "type": "function",
                                                "function": {
                                                    "name": tc_name,
                                                    "arguments": json.dumps(_normalized_args),
                                                },
                                            }
                                        ],
                                    }
                                )
                                loop_messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": call_id,
                                        "content": safe_observation,
                                    }
                                )
                                last_tool_failed = False
                                consecutive_failures = 0
                            else:
                                observation = f"[Tool '{tc_name}' returned no result]"
                                tool_failed = True
                                loop_messages.append(
                                    {
                                        "role": "assistant",
                                        "content": _strip_minimax_tool_calls(_minimax_buffer),
                                    }
                                )
                                loop_messages.append(
                                    {
                                        "role": "user",
                                        "content": f"Tool '{tc_name}' returned no result. Try a different approach.",
                                    }
                                )
                                last_tool_failed = True
                                consecutive_failures += 1
                        except (ValueError, Exception) as exc:
                            logger.warning(f"[agent.loop] minimax intercept: tool dispatch failed: {exc}")
                            loop_messages.append(
                                {
                                    "role": "assistant",
                                    "content": _strip_minimax_tool_calls(_minimax_buffer),
                                }
                            )
                            loop_messages.append(
                                {
                                    "role": "user",
                                    "content": f"Tool '{tc_name}' failed: {exc}. Try a different approach.",
                                }
                            )
                            last_tool_failed = True
                            consecutive_failures += 1

                        if _obs:
                            _obs.emit(
                                "tool_call",
                                tool=tc_name,
                                label=action_label,
                                status="done" if not tool_failed else "failed",
                                latency_ms=latency_ms if "latency_ms" in dir() else 0,
                                iteration=iteration + 1,
                                todo_id=f"plan-{_plan_step_cursor}" if _plan_steps else None,
                                thought=result.raw_content or "", reasoning=_step_reasoning(),
                            )

                        trace.steps.append(
                            AgentStep(
                                iteration=iteration + 1,
                                thought=_strip_minimax_tool_calls(_minimax_buffer),
                                tool_name=tc_name,
                                tool_input=tool_input[:200],
                                observation=observation[:500] if "observation" in dir() else "",
                                tool_failed=tool_failed if "tool_failed" in dir() else True,
                                retry_count=0,
                                latency_ms=latency_ms if "latency_ms" in dir() else 0,
                            )
                        )

                    # After processing all intercepted tool calls, continue the loop
                    # so the model can reason about the results and produce a final answer
                    continue

                # ── No MiniMax tool calls found — proceed with normal text handling ──
                # Re-use the buffered chunks as the initial_buffer for tool-talk detection
                initial_buffer = _minimax_buffer
                has_error = _minimax_error
                stream_ended_early = _minimax_stream_ended

                # ── Fabrication detection: text response without tool calls ──
                # If the model was supposed to use tools (agent intent, iteration 0)
                # but produced a text response instead, this is a potential fabrication.
                # The model may be describing what it would do instead of actually
                # calling tools. Emit a warning so the observability pipeline can
                # track this pattern.
                if (
                    iteration == 0
                    and intent in AGENT_INTENTS
                    and not trace.steps
                    and not _parent_native_turn
                ):
                    fabrication_risk += 1
                    if _obs:
                        _obs.emit(
                            "fabrication_warning",
                            risk=fabrication_risk,
                            reason="model produced text response without tool calls on first iteration",
                            intent=intent.value,
                            iteration=iteration + 1,
                        )
                    logger.warning(
                        f"[agent.loop] fabrication warning: model produced text without "
                        f"tool calls for intent={intent.value} on iter={iteration + 1} "
                        f"(fabrication_risk={fabrication_risk})"
                    )
                    # Session 238 (Thinker/Agent rebuild Step 0): on the
                    # FIRST tool iteration, text without a tool call is
                    # usually model fragility, not a real answer — the
                    # model skipped the tool API (gemini-2.5-flash via
                    # OpenAI-compat returned text/empty on the first tool
                    # call — Session 237 trace). Reprompt with a
                    # forced-tool nudge (bounded) instead of streaming the
                    # text as the final answer. The model's text stays in
                    # history, so if it insists on text again on the next
                    # pass (iteration != 0 now), the text IS accepted and
                    # streamed — never an unbounded retry.
                    if (
                        filtered_tools
                        and not has_error
                        and trace.tool_forced_recoveries < _MAX_TOOL_FORCE_RECOVERIES
                    ):
                        trace.tool_forced_recoveries += 1
                        if _obs:
                            _obs.emit(
                                "tool_force_recovery",
                                recovery_num=trace.tool_forced_recoveries,
                                reason="text-without-tool on first tool iteration",
                                intent=intent.value,
                                iteration=iteration + 1,
                            )
                        if not stream_ended_early:
                            async for _drain_chunk in result:
                                pass
                        loop_messages.append({"role": "assistant", "content": initial_buffer})
                        loop_messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "This request requires a tool call, but you did not call one. "
                                    "You MUST invoke a tool now via the function-calling API "
                                    "(e.g. shell, file_task, web_search) before answering. "
                                    "Do NOT narrate what you would do — call the tool directly."
                                ),
                            }
                        )
                        continue  # retry this iteration with the forced-tool nudge
                # (initial_buffer and initial_chunks already populated by the
                #  MiniMax detection phase above — no need to re-buffer here)

                # Detect errors in the initial buffer
                if has_error or (
                    initial_buffer
                    and any(
                        marker in initial_buffer
                        for marker in [
                            "Ollama returned 5",
                            "Ollama timed out",
                            "Cannot connect to Ollama",
                            "returned 5",
                            "timed out after",
                        ]
                    )
                ):
                    # A provider error after a successful tool call is a
                    # degraded synthesis, not a failed tool execution. This
                    # is common with per-minute provider limits: the first
                    # model call succeeds, the tool succeeds, and the next
                    # model call that should summarize the evidence gets a
                    # 429. Returning the error here discards the evidence and
                    # makes the whole turn look like the tool failed.
                    _stream_err = _minimax_error_msg or initial_buffer
                    from core.error_normalizer import normalize_error

                    _normalized_stream_error = normalize_error(_stream_err)
                    _has_successful_evidence = any(
                        step.tool_name and not step.tool_failed
                        for step in trace.steps
                    )
                    _can_preserve_evidence = (
                        _has_successful_evidence
                        and _normalized_stream_error.get("source") == "model_provider"
                        and bool(_normalized_stream_error.get("retryable"))
                    )
                    if _can_preserve_evidence:
                        logger.warning(
                            "[agent.loop] iter=%d — provider synthesis failed after "
                            "successful tool work; preserving evidence (%s)",
                            iteration + 1,
                            _normalized_stream_error.get("code", "provider_error"),
                        )
                        if _obs:
                            _obs.emit(
                                "agent_loop_degraded",
                                iteration=iteration + 1,
                                provider_error_code=_normalized_stream_error.get("code", "error"),
                                evidence_preserved=True,
                            )
                        # B-2026-08-20-15 (Session 317): FIRST try deterministic
                        # extraction from the evidence already in hand — zero
                        # LLM calls. The provider rate-limited the synthesis,
                        # but the tool observations (search results, shell
                        # output) already contain the answer. Extract it
                        # directly instead of dumping raw harness internals.
                        _user_msg = _user_message_text(loop_messages) or ""
                        _extracted = self._extract_answer_from_evidence(
                            reasoning_buffer=_reasoning_buffer,
                            observation_log=observation_log,
                            trace=trace,
                            user_message=_user_msg,
                        )
                        if _extracted:
                            logger.info(
                                "[agent.loop] provider-failure rescued by evidence "
                                "extraction (zero-LLM, %d chars)", len(_extracted),
                            )
                            if _obs:
                                _obs.emit(
                                    "evidence_extracted",
                                    intent=intent.value,
                                    chars=len(_extracted),
                                    source="provider_failure_recovery",
                                )
                            yield StreamChunk(
                                text=_extracted,
                                done=False,
                                usage=dict(_provider_usage),
                            )
                            yield StreamChunk(text="", done=True, usage=dict(_provider_usage))
                            return
                        # Extraction failed — yield a CLEAN user-facing message
                        # (B-2026-08-20-14), NOT the raw _summarize_trace_for_user
                        # dump. The tool evidence is in the Actions panel.
                        _tool_count = sum(1 for s in (trace.steps if trace else []) if getattr(s, "tool_name", ""))
                        if _tool_count > 0:
                            yield StreamChunk(
                                text=(
                                    "I found the information you asked for, but the "
                                    "model provider rate-limited my final synthesis "
                                    "call. The search results and tool outputs are in "
                                    "the Actions panel above — take a look, or ask me "
                                    "again and I'll retry."
                                ),
                                done=False,
                                usage=dict(_provider_usage),
                            )
                        else:
                            yield StreamChunk(
                                text=(
                                    "The model provider rate-limited my request. "
                                    "Please try again in a moment."
                                ),
                                done=False,
                                usage=dict(_provider_usage),
                            )
                        yield StreamChunk(text="", done=True, usage=dict(_provider_usage))
                    else:
                        logger.warning(
                            f"[agent.loop] iter={iteration + 1} — error in stream, aborting"
                        )
                        if _obs:
                            _obs.emit(
                                "agent_loop_error",
                                error=_stream_err[:120],
                                iteration=iteration + 1,
                            )
                        yield StreamChunk(
                            text=(
                                "⚠️ The model ran into an issue. Please try again, "
                                "or switch to a larger model for this task."
                            ),
                            done=True,
                            error=_stream_err[:200],
                        )
                    # Drain remaining chunks from the stream
                    if not stream_ended_early:
                        async for _ in result:
                            pass
                    return

                # Detect tool-talk in the initial buffer
                if _is_tool_talk(initial_buffer) and trace.tool_talk_recoveries < _MAX_TOOL_TALK_RECOVERIES:
                    trace.tool_talk_recoveries += 1
                    logger.warning(
                        f"[agent.loop] iter={iteration + 1} — tool-talk detected "
                        f"(recovery {trace.tool_talk_recoveries}/{_MAX_TOOL_TALK_RECOVERIES}): "
                        f"{initial_buffer[:120]!r}"
                    )
                    if _obs:
                        _obs.emit(
                            "tool_talk_recovery",
                            iteration=iteration + 1,
                            recovery_num=trace.tool_talk_recoveries,
                            preview=initial_buffer[:80],
                        )
                    # Drain remaining chunks from the stream
                    if not stream_ended_early:
                        async for _ in result:
                            pass
                    # Inject corrective hint and continue without streaming the bad text
                    loop_messages.append(
                        {
                            "role": "assistant",
                            "content": initial_buffer,
                        }
                    )
                    loop_messages.append(
                        {
                            "role": "user",
                            "content": (
                                "You described wanting to use a tool but did not call it. "
                                "You MUST use the tool-calling API directly — do NOT narrate or describe "
                                "your intent. Call the tool now using the function-calling format."
                            ),
                        }
                    )
                    continue  # retry this iteration with the corrective hint

                # ── v0.7: Fabricated data detection (no tool call, no narration) ──
                # The model produced text that looks like real data (scores, weather,
                # prices) but NEVER called a tool. This means it fabricated from
                # training data. For WEB_SEARCH intent, this is the most critical
                # failure mode — the model "knows" the answer from training and
                # outputs it directly, skipping the actual tool call entirely.
                #
                # Pattern: "The current temperature in Cheptais is 22°C..." — no
                # tool was called, this is fabricated.
                _FABRICATED_DATA_PATTERNS = [
                    re.compile(r"\b(temperature|temp)\b.{0,20}\d+°(C|F)", re.IGNORECASE),
                    re.compile(r"\bweather\b.{0,30}\d+°(C|F)", re.IGNORECASE),
                    re.compile(r"\b(score|result)\b.{0,15}\d+\s*[-–]\s*\d+", re.IGNORECASE),
                    re.compile(
                        r"\b(played|vs|versus|against)\b.{0,30}\b(won|lost|drew|beat)\b",
                        re.IGNORECASE,
                    ),
                    re.compile(r"\b(standings|table|rankings?)\b.{0,10}\b(1\.|1st|2nd|3rd)", re.IGNORECASE),
                    re.compile(r"\b(fixture|match|game)\b.{0,20}\b(vs|versus|against)\b", re.IGNORECASE),
                    re.compile(r"\b(price|value|rate)\b.{0,20}[\$€£₹]\d+", re.IGNORECASE),
                    re.compile(r"\b(exchange rate|stock price|crypto|bitcoin|ethereum)\b", re.IGNORECASE),
                ]
                _fabricated_data_detected = any(p.search(initial_buffer) for p in _FABRICATED_DATA_PATTERNS)

                if (
                    _fabricated_data_detected
                    and intent in (Intent.WEB_SEARCH, Intent.WEB_FETCH)
                    and trace.tool_talk_recoveries < _MAX_TOOL_TALK_RECOVERIES + 1
                ):
                    # The model fabricated time-sensitive data from training — this is
                    # the most dangerous hallucination because it looks plausible.
                    # CRITICAL: Drain the stream and force a tool call instead.
                    logger.warning(
                        f"[agent.loop] iter={iteration + 1} — FABRICATED DATA DETECTED "
                        f"for intent={intent.value}: model produced time-sensitive data "
                        f"from training without calling any tool. "
                        f"Preview: {initial_buffer[:120]!r}"
                    )
                    if _obs:
                        _obs.emit(
                            "fabricated_data_intercepted",
                            intent=intent.value,
                            iteration=iteration + 1,
                            preview=initial_buffer[:80],
                        )
                    # Drain remaining chunks from the stream
                    if not stream_ended_early:
                        async for _ in result:
                            pass
                    # Inject corrective hint forcing the model to use the actual tool
                    loop_messages.append(
                        {
                            "role": "assistant",
                            "content": initial_buffer,
                        }
                    )
                    loop_messages.append(
                        {
                            "role": "user",
                            "content": (
                                "CRITICAL: You just output time-sensitive data (weather, scores, prices, etc.) "
                                "from your training knowledge — this data is STALE and likely WRONG. "
                                "You MUST call the web_search tool NOW to get real, current data. "
                                "Do NOT answer from your training data for time-sensitive queries. "
                                "Call web_search with a specific query for the user's request."
                            ),
                        }
                    )
                    fabrication_risk += 2  # Heavy penalty for fabricated data
                    continue  # retry with forced tool call

                # ── Empty-response guard (Session 115) ────────────────────
                # The model produced NO usable text AND no tool call (e.g.
                # the free-tier model returns an empty stream, or every chunk
                # was filtered out as a system-leak). Previously this fell
                # through to "stream the answer" with an empty buffer — the
                # user saw a spinner for 60-120s, then a blank/near-empty
                # reply and no explanation (the silent-stall failure mode).
                # Honest fast-fail instead: say what happened and STOP, so we
                # never burn another PER_CALL_TIMEOUT_SECS call on the same
                # empty output.
                if not (initial_buffer or "").strip():
                    # Session 238 (Thinker/Agent rebuild Step 0): an EMPTY
                    # response on the FIRST tool iteration is model
                    # fragility (gemini-2.5-flash returned empty/no-tool in
                    # 788ms — Session 237 trace), not evidence that the
                    # model is overloaded. Reprompt once with a forced-tool
                    # nudge before the Session 115 honest fast-fail, so the
                    # turn can still succeed. Later iterations (or a second
                    # empty response) take the honest fail unchanged — the
                    # nudge is bounded and never spins.
                    if (
                        iteration == 0
                        and intent in AGENT_INTENTS
                        and not trace.steps
                        and filtered_tools
                        and trace.tool_forced_recoveries < _MAX_TOOL_FORCE_RECOVERIES
                    ):
                        trace.tool_forced_recoveries += 1
                        if _obs:
                            _obs.emit(
                                "tool_force_recovery",
                                recovery_num=trace.tool_forced_recoveries,
                                reason="empty response on first tool iteration",
                                intent=intent.value,
                                iteration=iteration + 1,
                            )
                        if not stream_ended_early:
                            async for _drain_chunk in result:
                                pass
                        # Keep message-role alternation for strict providers:
                        # an empty assistant frame, then the corrective nudge.
                        loop_messages.append({"role": "assistant", "content": ""})
                        loop_messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "You returned an empty response. This request requires "
                                    "tool use — call the appropriate tool NOW via the "
                                    "function-calling API (do not answer from memory)."
                                ),
                            }
                        )
                        continue  # retry this iteration with the forced-tool nudge

                    # ADR-41 follow-up (Session 256): the model streamed
                    # reasoning but returned no text and no tool call — on a
                    # slow free tier with thinking ON, GLM sometimes "thinks
                    # but doesn't act" (live user bug: iter-1 ran shell
                    # Get-ChildItem, iter-2 streamed reasoning then went
                    # empty, failing the whole turn). The reasoning is real
                    # progress, so do ONE bounded retry with a nudge before
                    # the honest fail. Two consecutive empties still fail
                    # fast — the think-only protection stays intact.
                    #
                    # B-2026-08-20-7 / Session 310: parent turns get a higher
                    # cap (3 vs 2) — weak models on the parent path frequently
                    # need the extra recovery attempt to complete a tool-bearing
                    # turn. The post-loop synthesis remains the final safety net.
                    _empty_reasoning_cap = (
                        _MAX_EMPTY_REASONING_RECOVERIES_PARENT
                        if _parent_native_turn
                        else _MAX_EMPTY_REASONING_RECOVERIES
                    )
                    if _streamed_reasoning and trace.empty_reasoning_recoveries < _empty_reasoning_cap:  # noqa: E501
                        trace.empty_reasoning_recoveries += 1
                        logger.warning(
                            "[agent.loop] iter=%d — empty response after reasoning "
                            "streamed (recovery %d/%d) — nudging to continue",
                            iteration + 1,
                            trace.empty_reasoning_recoveries,
                            _empty_reasoning_cap,
                        )
                        if _obs:
                            _obs.emit(
                                "empty_reasoning_recovery",
                                recovery_num=trace.empty_reasoning_recoveries,
                                intent=intent.value,
                                iteration=iteration + 1,
                            )
                        if not stream_ended_early:
                            async for _drain_chunk in result:
                                pass
                        # Session 260: ground truth showed the model streams
                        # reasoning then 0 content ("thinks but doesn't act").
                        # Force thinking OFF on the retry so it emits the
                        # answer/tool-call directly — it has already reasoned
                        # (streamed live); more thinking just repeats the empty.
                        try:
                            active_adapter._one_shot_thinking_off = True
                        except Exception:
                            pass
                        # Keep message-role alternation for strict providers:
                        # an empty assistant frame, then the corrective nudge.
                        loop_messages.append({"role": "assistant", "content": ""})
                        # B-2026-08-20-13 (Session 314): include the user's
                        # ORIGINAL question in the nudge so the model can
                        # re-anchor. The generic "You reasoned about this task"
                        # caused the model to lose context on weak models
                        # (live transcript: "I don't have any information about
                        # what the original task was" — even though the user's
                        # message was in loop_messages). Restating the question
                        # explicitly gives the model a concrete anchor.
                        _original_question = _user_message_text(loop_messages) or "the user's request"
                        loop_messages.append(
                            {
                                "role": "user",
                                "content": (
                                    f"You reasoned about this task but returned no answer "
                                    f"and no tool call. The user's request was: "
                                    f"\"{_original_question[:500]}\". "
                                    f"Do NOT reason further — act now: "
                                    f"call the next tool you need, or give the final answer "
                                    f"directly in plain text."
                                ),
                            }
                        )
                        continue  # retry with thinking OFF so the model acts

                    trace.empty_response = True  # ADR-18 P2: remember this failure
                    if _obs:
                        _obs.emit(
                            "agent_loop_empty_response",
                            intent=intent.value,
                            iteration=iteration + 1,
                        )
                    if not stream_ended_early:
                        async for _drain in result:
                            pass

                    # B-2026-08-20-15 (Session 316): FIRST try deterministic
                    # extraction from the reasoning buffer — ZERO LLM calls.
                    # The user's insight: "the thinking text already has all
                    # the answers." The model's reasoning often contains a
                    # direct answer sentence ("the temperature is 16°C and
                    # overcast"). Extract it before making another LLM call.
                    _user_msg = _user_message_text(loop_messages) or ""
                    _extracted = self._extract_answer_from_evidence(
                        reasoning_buffer=_reasoning_buffer,
                        observation_log=observation_log,
                        trace=trace,
                        user_message=_user_msg,
                    )
                    if _extracted:
                        logger.info(
                            "[agent.loop] empty-response rescued by evidence extraction "
                            "(zero-LLM, %d chars)", len(_extracted),
                        )
                        if _obs:
                            _obs.emit(
                                "evidence_extracted",
                                intent=intent.value,
                                chars=len(_extracted),
                                source="reasoning_or_observations",
                            )
                        yield StreamChunk(text=_extracted, done=False)
                        yield StreamChunk(text="", done=True, usage=dict(_provider_usage))
                        return

                    # B-2026-08-18-11: SYNTHESIZE a real answer before giving up.
                    # The model streamed reasoning but no content — on GLM/thinking
                    # the substance often lands in the REASONING channel (it "thinks
                    # but doesn't act"). Hand the model its OWN reasoning + the tool
                    # evidence back and ask for the final answer with thinking OFF
                    # (a plain synthesis call, not the tool loop), so a real answer
                    # is produced from what was already worked out — instead of a
                    # raw "couldn't summarize" tool dump. Falls through to the dump
                    # only if this also yields nothing.
                    try:
                        active_adapter._one_shot_thinking_off = True
                    except Exception:
                        pass
                    _synth_obs = observation_log
                    if _reasoning_buffer.strip():
                        _synth_obs = (
                            (observation_log + "\n\n" if observation_log.strip() else "")
                            + "Your own analysis so far (from your reasoning):\n"
                            + _reasoning_buffer.strip()[-4000:]
                        )
                    _synth_answer = ""
                    if _synth_obs.strip():
                        try:
                            async for _sc in self._force_final_answer(
                                loop_messages=loop_messages,
                                observation_log=_synth_obs,
                                active_adapter=active_adapter,
                                trace=trace,
                                provider_usage=_provider_usage,
                                framing="final",
                                suppress_report=True,
                                suppress_empty_fallback=True,
                            ):
                                if _sc.text:
                                    _synth_answer += _sc.text
                        except Exception as _exc:  # pragma: no cover — defensive
                            logger.warning("[agent.loop] empty-response synthesis failed: %s", _exc)
                    _synth_answer = _synth_answer.strip()
                    if _synth_answer:
                        logger.info(
                            "[agent.loop] empty-response rescued by synthesis from "
                            "reasoning+evidence (%d chars)",
                            len(_synth_answer),
                        )
                        if _obs:
                            _obs.emit(
                                "empty_response_synthesized",
                                intent=intent.value,
                                chars=len(_synth_answer),
                            )
                        yield StreamChunk(text=_synth_answer, done=False)
                        yield StreamChunk(text="", done=True, usage=dict(_provider_usage))
                        return

                    _empty_summary = self._summarize_trace_for_user(trace, observation_log)
                    # B-2026-08-20-7: LAST safety net. The B-2026-08-18-11
                    # synthesis-from-reasoning rescue above (line ~3819) failed
                    # or didn't fire (no reasoning buffer). But if tools ran
                    # this turn, there IS evidence to synthesize from — the
                    # model just couldn't produce the final answer itself.
                    # Try ONE deterministic post-loop synthesis from the tool
                    # evidence before falling back to the empty message.
                    # This does NOT count against the recovery budget.
                    async for _post_synth_chunk in self._post_loop_synthesis_from_evidence(
                        loop_messages=loop_messages,
                        observation_log=observation_log,
                        active_adapter=active_adapter,
                        trace=trace,
                        provider_usage=_provider_usage,
                        intent=intent,
                        obs=_obs,
                    ):
                        if _post_synth_chunk.text:
                            yield _post_synth_chunk
                            yield StreamChunk(text="", done=True, usage=dict(_provider_usage))
                            return
                    # B-2026-08-20-14: post-loop synthesis also failed. Produce
                    # a CLEAN user-facing message — not the raw trace dump.
                    # The old path yielded _empty_summary (raw harness internals
                    # "Here is what actually ran: web_search(...) → output: ...")
                    # which reads as developer debug output. The Actions panel
                    # already has the tool evidence; the chat bubble stays clean.
                    _tool_count = sum(1 for s in (trace.steps if trace else []) if getattr(s, "tool_name", ""))
                    if _tool_count > 0:
                        _empty_msg = (
                            "I found the information you asked for, but I'm having "
                            "trouble putting it into a clean final answer right now. "
                            "The search results and tool outputs are in the Actions "
                            "panel above — take a look, or ask me again and I'll retry."
                        )
                    else:
                        _empty_msg = (
                            "I couldn't generate a response for that request. "
                            "Please try again, or rephrase your question."
                        )
                    # Session 142: do NOT complete the plan todo here — the
                    # model produced nothing and NO tool ran, so marking the
                    # step done would be a lie. The SSE bridge's end-of-turn
                    # _finalize_plan_todos still closes it (the plan covers
                    # the whole turn), but we don't pretend the work happened.
                    self._emit_failure_memory(trace, intent, _obs)  # ADR-18 P2
                    yield StreamChunk(text=_empty_msg, done=False)
                    yield StreamChunk(text="", done=True, usage=dict(_provider_usage))
                    return

                # Phase 2: No tool-talk detected — stream the answer
                # incrementally. First yield the initial buffer, then
                # stream remaining chunks directly from the adapter.
                #
                # v0.10: Mid-stream MiniMax detection. Sometimes MiniMax outputs
                # the tool-call XML AFTER the initial buffer check (e.g., it emits
                # 2 sentences of text, then the <invoke> XML in a later chunk).
                # We now check for this pattern during streaming and intercept it.
                full_text = initial_buffer

                # Yield the initial buffer — but filter any MiniMax XML that might
                # have appeared after the initial check
                _stripped_buffer = _strip_minimax_tool_calls(initial_buffer)
                if _stripped_buffer != initial_buffer:
                    # MiniMax XML appeared in the initial buffer but wasn't caught
                    # by the earlier _parse_minimax_tool_call check (e.g., partial XML
                    # that completed during buffering). Re-check now.
                    logger.info("[agent.loop] MiniMax XML detected in initial buffer during Phase 2 — re-checking")
                    _late_calls = _parse_minimax_tool_call(initial_buffer)
                    if _late_calls and not has_error:
                        # Drain remaining chunks and process the intercepted calls
                        if not stream_ended_early:
                            async for _drain_chunk in result:
                                _drain_text = _filter_system_leaks(_drain_chunk.text)
                                _minimax_buffer += _drain_text
                        # Re-process with the complete buffer
                        _minimax_buffer = initial_buffer
                        _minimax_calls = _late_calls
                        # Jump to the MiniMax interception handler above by
                        # re-running the buffer through _parse_minimax_tool_call
                        # and continuing the loop. Since we already consumed the
                        # stream, we process inline here.
                        for _tc_name, _tc_args, _tc_raw_xml in _minimax_calls:
                            _norm_args = dict(_tc_args)
                            if _tc_name == "web_search" and "text" in _norm_args and "query" not in _norm_args:
                                _norm_args["query"] = _norm_args.pop("text")
                            if _tc_name == "web_fetch" and "text" in _norm_args and "url" not in _norm_args:
                                _norm_args["url"] = _norm_args.pop("text")
                            if _tc_name not in AGENT_ALLOWED_TOOLS:
                                continue
                            _tc_input = _extract_tool_input(_tc_name, _norm_args)
                            if not _tc_input or len(_tc_input.strip("?. \t")) < 3:
                                continue
                            _tc_label_parts = {
                                "web_search": f"Searching: {_norm_args.get('query', '')[:80]}",
                                "web_fetch": f"Fetching: {_norm_args.get('url', '')[:80]}",
                                "shell": f"Running: {_norm_args.get('command', '')[:80]}",
                                "describe_tool": f"Loading tool docs: {_norm_args.get('tool_name', '')[:80]}",
                            }
                            _tc_label = _tc_label_parts.get(_tc_name, f"Running {_tc_name}")
                            yield StreamChunk(text="", done=False, status=_tc_label)
                            if _obs:
                                _obs.emit(
                                    "tool_call",
                                    tool=_tc_name,
                                    label=_tc_label,
                                    status="started",
                                    iteration=iteration + 1,
                                    todo_id=f"plan-{_plan_step_cursor}" if _plan_steps else None,
                                    thought=result.raw_content or "", reasoning=_step_reasoning(),
                                )
                            t_late = time.monotonic()
                            try:
                                _late_result, _late_failed, _ = await dispatch_with_retry(
                                    Intent(_tc_name),
                                    _tc_input,
                                    obs=_obs,  # ADR-18 P3: delegation streams into the UI
                                    allowed_tool_names=effective_allowed,
                                )
                                _note_described_tool(_tc_name, _late_result, loaded_tools)
                                _emit_todo_write_events(_tc_name, _late_result, _obs)
                                _late_lat = round((time.monotonic() - t_late) * 1000)
                                _late_obs = (
                                    _filter_tool_injection(_late_result.content)
                                    if _late_result
                                    else f"[Tool {_tc_name} returned no result]"
                                )
                                # Late/intercepted search calls are also
                                # observations for the parent, never terminal
                                # user output. Feed the result back through the
                                # normal tool-message continuation below.
                                trace.steps.append(
                                    AgentStep(
                                        iteration=iteration + 1,
                                        thought=_strip_minimax_tool_calls(_minimax_buffer),
                                        tool_name=_tc_name,
                                        tool_input=_tc_input,
                                        observation=_late_obs[:500],
                                        tool_failed=_late_failed,
                                        latency_ms=_late_lat,
                                    )
                                )
                                if not _late_failed:
                                    yield StreamChunk(
                                        text="",
                                        done=False,
                                        status=f"Done — {_tc_label} ({_late_lat}ms)",
                                    )
                                call_id = str(uuid.uuid4())
                                safe_late_obs = (
                                    (
                                        f"[ACTUAL TOOL OUTPUT — use ONLY this data in your response]\n"
                                        f"{_late_obs}\n"
                                        f"[END TOOL OUTPUT — do NOT invent or add items not shown above]"
                                    )
                                    if not _late_failed and _late_obs
                                    else _late_obs
                                )
                                loop_messages.append(
                                    {
                                        "role": "assistant",
                                        "content": _strip_minimax_tool_calls(_minimax_buffer),
                                        "tool_calls": [
                                            {
                                                "id": call_id,
                                                "type": "function",
                                                "function": {
                                                    "name": _tc_name,
                                                    "arguments": json.dumps(_norm_args),
                                                },
                                            }
                                        ],
                                    }
                                )
                                loop_messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": call_id,
                                        "content": safe_late_obs,
                                    }
                                )
                            except Exception as _late_exc:
                                logger.warning(f"[agent.loop] late MiniMax intercept failed: {_late_exc}")
                            if _obs:
                                _obs.emit(
                                    "tool_call",
                                    tool=_tc_name,
                                    label=_tc_label,
                                    status="done",
                                    output=_truncate_observation(safe_late_obs),
                                    latency_ms=_late_lat if "_late_lat" in dir() else 0,
                                    iteration=iteration + 1,
                                    todo_id=f"plan-{_plan_step_cursor}" if _plan_steps else None,
                                    thought=result.raw_content or "", reasoning=_step_reasoning(),
                                    provider=_tool_provider(_late_result),
                                )
                        continue  # continue the loop so the model can produce a final answer

                # Yield the clean initial buffer
                if _stripped_buffer.strip():
                    yield StreamChunk(text=_stripped_buffer, done=False)

                # If the stream already ended (short response), we're done
                if stream_ended_early:
                    trace.final_response = full_text
                    trace.steps.append(
                        AgentStep(
                            iteration=iteration + 1,
                            thought=full_text[:500],
                            tool_name=None,
                            tool_input=None,
                            observation=None,
                        )
                    )
                    # ADR-18 P0: the model saying "done" is not enough — gate
                    # the claim against the success criteria (replan or honest
                    # report). Only finish when the gate is satisfied or capped.
                    _gate_suffix, _gate_final = await self._acceptance_gate_at_final_answer(
                        trace=trace,
                        iteration=iteration,
                        effective_max_iter=_effective_max_iter,
                        loop_messages=loop_messages,
                        observation_log=observation_log,
                        active_adapter=active_adapter,
                        intent=intent,
                        obs=_obs,
                        orchestrator=orchestrator,
                        reformulated_message=reformulated_message,
                        memory_facts=memory_facts,
                        intent_history=intent_history,
                        is_parent=(getattr(agent_config, "name", "") == "parent"),
                    )
                    if not _gate_final:
                        continue
                    # Session 237: the gate passed but the model may have run
                    # the tool without writing an answer — synthesize the real
                    # content from evidence so the reply isn't just "✓ n/n".
                    if not full_text.strip():
                        _synth = await self._synthesize_final_from_trace(
                            trace, intent,
                            reformulated_message or _user_message_text(loop_messages),
                            active_adapter,
                        )
                        if _synth:
                            full_text = _synth
                            trace.final_response = full_text
                            yield StreamChunk(text=_synth, done=False)
                    if _gate_suffix:
                        full_text += _gate_suffix
                        trace.final_response = full_text
                        yield StreamChunk(text=_gate_suffix, done=False)
                    logger.info(f"[agent.loop] finished iter={iteration + 1} — {trace.summary()}")
                    # Session 142: turn-end — close out the current plan step's
                    # todo (covers the stream-ended-early silent path).
                    _complete_current_plan_step()
                    self._emit_failure_memory(trace, intent, _obs)
                    if _obs:
                        _obs.emit("agent_loop_done", intent=intent.value, iterations=iteration + 1)
                    _worker_report = trace.work_report()
                    if _worker_report.needs_report(full_text):
                        # Session 147: try one focused synthesis call before
                        # the deterministic report — the free-tier model often
                        # ends a tool-bearing turn with a bare heading.
                        async for _rescue_chunk in self._rescue_final_answer(
                            loop_messages=loop_messages,
                            observation_log=observation_log,
                            active_adapter=active_adapter,
                            trace=trace,
                            provider_usage=_provider_usage,
                        ):
                            yield _rescue_chunk
                    yield StreamChunk(text="", done=True, usage=dict(_provider_usage))
                    return

                # Stream remaining chunks — with mid-stream MiniMax detection
                _mid_stream_minimax_buffer = ""
                _mid_stream_text = ""
                async for chunk in result:
                    # B-2026-08-02-2 (A2): respond to abort DURING streaming —
                    # the longest phase (up to PER_CALL_TIMEOUT_SECS). is_set()
                    # is a flag read; checked per chunk.
                    if abort_signal is not None and abort_signal.is_set():
                        raise AgentAbortedError("aborted during streaming")
                    if chunk.usage:
                        _provider_usage.update(chunk.usage)
                    filtered_text = _filter_system_leaks(chunk.text)
                    full_text += filtered_text
                    _mid_stream_text += filtered_text
                    _mid_stream_minimax_buffer += filtered_text
                    if chunk.error:
                        has_error = True
                    # v0.10: Mid-stream MiniMax tool call detection.
                    # If we see a complete <invoke> pattern in the streaming
                    # text, strip it from the output and execute the tool.
                    if _has_minimax_tool_call(_mid_stream_minimax_buffer):
                        logger.info(
                            "[agent.loop] mid-stream MiniMax tool call detected: %s",
                            _mid_stream_minimax_buffer[:200],
                        )
                        # Strip the XML from what we've already yielded
                        _clean = _strip_minimax_tool_calls(_mid_stream_text)
                        # The tool call will be handled on the next iteration
                        # For now, just suppress the XML and let the model see it
                        filtered_text = ""
                        _mid_stream_minimax_buffer = ""
                    # ADR-41 (Session 254): forward the model's reasoning live
                    # as it streams (GLM thinking → ThinkingBlock). Reasoning
                    # is independent of the text path — it never affects
                    # MiniMax/DSML detection and is filtered for system leaks
                    # like the text below. (isinstance guard: test stubs may
                    # carry a truthy non-str .thinking.)
                    if isinstance(chunk.thinking, str) and chunk.thinking:
                        yield StreamChunk(
                            text="",
                            thinking=_filter_system_leaks(chunk.thinking),
                            done=False,
                            usage=dict(_provider_usage),
                        )
                    # Also strip any partial MiniMax XML from individual chunks.
                    # Use the STREAM variant: the plain _strip_minimax_tool_calls
                    # ends with .strip(), which on a per-chunk basis eats the
                    # leading/trailing space at every chunk boundary and welds
                    # words together ("assistantrunning", "thisdevice"). The
                    # stream variant removes the XML without touching boundary
                    # whitespace; the final answer is assembled from full_text.
                    _chunk_clean = _strip_minimax_tool_calls_stream(filtered_text)
                    if _chunk_clean:
                        # Keep the terminal marker until report enforcement has
                        # completed below; otherwise the client can finalize
                        # before the worker report is delivered.
                        yield StreamChunk(text=_chunk_clean, done=False, usage=dict(_provider_usage))

                trace.final_response = full_text
                trace.steps.append(
                    AgentStep(
                        iteration=iteration + 1,
                        thought=full_text[:500],
                        tool_name=None,
                        tool_input=None,
                        observation=None,
                    )
                )
                # ADR-18 P0: gate the model's "done" claim (replan or honest
                # report) BEFORE the turn-end events — the loop is only done
                # when the gate is satisfied or the caps force an honest close.
                _gate_suffix, _gate_final = await self._acceptance_gate_at_final_answer(
                    trace=trace,
                    iteration=iteration,
                    effective_max_iter=_effective_max_iter,
                    loop_messages=loop_messages,
                    observation_log=observation_log,
                    active_adapter=active_adapter,
                    intent=intent,
                    obs=_obs,
                    orchestrator=orchestrator,
                    reformulated_message=reformulated_message,
                    memory_facts=memory_facts,
                    intent_history=intent_history,
                    is_parent=(getattr(agent_config, "name", "") == "parent"),
                )
                if not _gate_final:
                    continue
                # Session 237: gate passed but no model answer — synthesize the
                # real content from tool evidence (not just "✓ n/n criteria met").
                if not full_text.strip():
                    _synth = await self._synthesize_final_from_trace(
                        trace, intent,
                        reformulated_message or _user_message_text(loop_messages),
                        active_adapter,
                    )
                    if _synth:
                        full_text = _synth
                        trace.final_response = full_text
                        yield StreamChunk(text=_synth, done=False)
                if _gate_suffix:
                    full_text += _gate_suffix
                    trace.final_response = full_text
                    yield StreamChunk(text=_gate_suffix, done=False)
                logger.info(f"[agent.loop] finished iter={iteration + 1} — {trace.summary()}")
                self._emit_failure_memory(trace, intent, _obs)
                if _obs:
                    _obs.emit("agent_loop_done", intent=intent.value, iterations=iteration + 1)

                # Explicit worker → report boundary: a tool-bearing turn is
                # not complete merely because the model emitted some text.
                # If that text contains no evidence from successful tool work,
                # append the deterministic report derived from the trace.
                _worker_report = trace.work_report()
                if _worker_report.needs_report(full_text):
                    # Session 147: try one focused synthesis call before
                    # the deterministic report — the free-tier model often
                    # ends a tool-bearing turn with a bare heading.
                    async for _rescue_chunk in self._rescue_final_answer(
                        loop_messages=loop_messages,
                        observation_log=observation_log,
                        active_adapter=active_adapter,
                        trace=trace,
                        provider_usage=_provider_usage,
                    ):
                        yield _rescue_chunk
                elif not full_text.strip():
                    # B-2026-08-20-14: model stream produced no text after
                    # filtering. Produce a CLEAN user-facing message, not the
                    # raw trace dump. The Actions panel has the tool evidence.
                    _tc = sum(1 for s in (trace.steps if trace else []) if getattr(s, "tool_name", ""))
                    if _tc > 0:
                        logger.warning(
                            "[agent.loop] iter=%d — model stream produced no text "
                            "after filtering; yielding clean fallback",
                            iteration + 1,
                        )
                        yield StreamChunk(
                            text=(
                                "I found the information you asked for, but I'm having "
                                "trouble putting it into a clean final answer right now. "
                                "The search results and tool outputs are in the Actions "
                                "panel above — take a look, or ask me again and I'll retry."
                            ),
                            done=False,
                        )
                # Session 142: close out the current plan step's todo — a
                # silent tool run never advanced the cursor, so without this
                # the executed step stays 'pending' in the Todos panel.
                _complete_current_plan_step()
                yield StreamChunk(text="", done=True, usage=dict(_provider_usage))
                return

        # ── MAX_ITERATIONS hit (or wall-clock cap broke the loop) ──────
        trace.hit_limit = True
        logger.warning(f"[agent.loop] loop ended — {trace.summary()}")
        # Session 142: close out the current plan step's todo on the
        # hit-limit path too — the work for the current step may have
        # completed even though the loop was capped.
        _complete_current_plan_step()
        self._emit_failure_memory(trace, intent, _obs)
        if _obs:
            _obs.emit("agent_loop_done", intent=intent.value, iterations=trace.iterations_used, hit_limit=True)

        # Session 31: ALWAYS try to synthesize a final answer from what
        # we gathered. Wrap with a timeout so this doesn't hang too.
        # If it times out, yield the observation log directly — the user
        # sees what happened instead of nothing.
        try:
            async for chunk in self._force_final_answer(
                loop_messages=loop_messages,
                observation_log=observation_log,
                active_adapter=active_adapter,
                trace=trace,  # Session 31: pass trace so empty-stream fallback can surface tool outputs
                provider_usage=_provider_usage,
            ):
                yield chunk
        except asyncio.TimeoutError:
            logger.warning("[agent.loop] final synthesis timed out — yielding evidence fallback")
            yield StreamChunk(
                text=self._synthesis_failure_fallback(trace, observation_log, timed_out=True),
                done=True,
            )
        except Exception as e:
            logger.warning(f"[agent.loop] final synthesis failed: {e}")
            yield StreamChunk(
                text=self._synthesis_failure_fallback(trace, observation_log, timed_out=False),
                done=True,
            )

    # ------------------------------------------------------------------
    # ADR-18 P0 — acceptance gate at the final-answer point
    # ------------------------------------------------------------------

    # ──────────────────────────────────────────────────────────────────────
    # ADR-18 P2 — failure memory emit (Session 175)
    # ──────────────────────────────────────────────────────────────────────
    def _emit_failure_memory(self, trace, intent, obs):
        """Emit an `agent_loop_failure` obs event when this run FAILED
        (iteration cap, unmet acceptance criteria, or a tool failure).
        The engine persists it to failure memory (the Remember stage).
        Successful runs emit nothing — remembering success would flood
        the table with noise."""
        try:
            from core.failure_memory import build_failure_summary, classify_failure

            failure_type = classify_failure(trace)
            if failure_type and obs:
                obs.emit(
                    "agent_loop_failure",
                    intent=intent.value,
                    failure_type=failure_type,
                    summary=build_failure_summary(trace),
                )
        except Exception:  # pragma: no cover — memory must never break the loop
            pass

    async def _synthesize_final_from_trace(
        self, trace, intent: Intent, user_question: str, adapter
    ) -> str:
        """Build a real content answer from tool evidence when the model
        finished the loop without emitting one.

        Session 237: execute turns like "list my dev folder" ran the tool and
        the acceptance gate passed, but the model produced NO final text — so
        the reply was only the criteria suffix ("✓ 1/1 criteria met"), never
        the actual listing. Synthesize an answer from the trace's tool
        observations instead. This only fires on the empty-answer path, so it
        strictly improves a currently-broken case (no regression to turns
        where the model already answered).
        """
        if not self._synthesizer.enabled:
            return ""
        try:
            from core.models import RiskLevel, ToolResult

            results = [
                ToolResult(
                    content=str(step.observation),
                    risk=RiskLevel.LOW,
                    source=step.tool_name or "tool",
                )
                for step in (getattr(trace, "steps", []) or [])
                if step.tool_name and step.observation
            ]
            if not results:
                return ""
            synthesis = await self._synthesizer.synthesize(
                tool_results=results,
                intent=intent,
                user_question=user_question or "",
                adapter=adapter or self._adapter,
            )
            return (synthesis.answer or "").strip()
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning(
                "[agent.loop] final-answer synthesis from trace failed (non-fatal): %s",
                exc,
            )
            return ""

    async def _acceptance_gate_at_final_answer(
        self,
        *,
        trace,
        iteration: int,
        effective_max_iter: int,
        loop_messages: list[dict],
        observation_log: str,
        active_adapter,
        intent: Intent,
        obs,
        # Session 178 — pass-through from run() so the orchestrator's
        # dead replan() method can finally be called. None = legacy.
        orchestrator=None,
        reformulated_message: str = "",
        memory_facts: Optional[list[str]] = None,
        intent_history: Optional[list[str]] = None,
        is_parent: bool = False,
    ) -> tuple[str, bool]:
        """Gate the model's "done" claim against the success criteria.

        Runs when the model produces a final answer (no more tool calls).
        "An agent saying done should not mean the task is done":
          - All criteria met → suffix = the verified summary (✓ n/n).
          - Some unmet + iterations remain → EXPLICIT replan LLM call
            (locked decision 3, Session 154); the revised plan is injected
            as a user block and the loop continues (returns is_final=False).
            Session 178: when `orchestrator` is provided, it is notified
            FIRST — its replan() produces a structured OrchestrationResult
            (re-route, confidence drop, clarification question) which is
            prepended to the revised plan block. The orchestrator's obs
            events (orchestrator_replan_start/_done/_timeout/_failed) now
            fire for real (consumed by the frontend in Session 180).
          - Some unmet + cap → suffix = the honest unmet report.
        No criteria → ("", True) — the legacy path is unchanged.
        """
        criteria = getattr(trace, "success_criteria", None) or []
        if not criteria:
            # B-2026-08-18-2 / review-66 — the parent's missing VERIFY→DONE
            # floor. With no explicit criteria contract, don't accept the
            # parent's "done" when its last real action FAILED (spec §29/§30).
            # Deterministic, keyed on the dispatcher's tool_failed verdict, and
            # scoped to the parent — read/analysis/successful turns are
            # unchanged (return the legacy model-assertion path below).
            _floor_note = parent_completion_floor_note(trace) if is_parent else None
            if _floor_note is None:
                # B-2026-08-20-6 (Session 307) — the prose-tool-commitment
                # detector. Distinct from the completion floor (which fires
                # when a tool RAN and failed): this fires when NO tool ran
                # this run AND the model's prose *commits* to a tool action
                # ("I'll use the shell tool", "let me describe..."). The
                # model intended to act but didn't emit the tool_call — a
                # known weak-model pattern (glm-4.5-flash live trace,
                # Session 306). Inject ONE bounded re-prompt; if the model
                # still doesn't emit a tool_call on the next iteration, the
                # one-shot guard below prevents an infinite nudge loop and
                # the turn falls through to the honest-stop path.
                if is_parent and not any(
                    getattr(s, "tool_name", "") for s in getattr(trace, "steps", []) or []
                ):
                    _final_text = getattr(trace, "final_response", "") or ""
                    if prose_commits_to_tool_action(_final_text):
                        # One-shot: if we already nudged on this run, don't
                        # nudge again — fall through to accept (the model
                        # had its chance and still didn't emit a tool_call).
                        _already_nudged = any(
                            getattr(m, "content", "").find("[TOOL COMMITMENT]") >= 0
                            if isinstance(getattr(m, "content", ""), str)
                            else False
                            for m in (loop_messages or [])
                        ) or any(
                            isinstance(m, dict)
                            and isinstance(m.get("content", ""), str)
                            and "[TOOL COMMITMENT]" in m.get("content", "")
                            for m in (loop_messages or [])
                        )
                        if not _already_nudged and iteration + 1 < effective_max_iter:
                            if obs:
                                obs.emit(
                                    "agent_loop_gate_failed_replan",
                                    intent=intent.value,
                                    iteration=iteration + 1,
                                    unmet=["model committed to a tool action in prose but emitted no tool_call"],
                                )
                            loop_messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        "\n[TOOL COMMITMENT] You wrote that you would use a "
                                        "tool (e.g. describe_tool, shell), but you did not "
                                        "actually emit the tool_call — you only described "
                                        "what you intend to do. Emit the tool_call now with "
                                        "the correct arguments, or proceed with the action. "
                                        "Do not describe the call; make it.\n"
                                    ),
                                }
                            )
                            return "", False
                # B-2026-08-20-13 (Session 314): the hedge detector. Distinct
                # from the prose-commitment detector (which fires when NO tool
                # ran): this fires when tools DID run (evidence exists) but the
                # model's answer hedges — "Would you like me to fetch...?",
                # "Which source would you prefer?" — instead of synthesizing
                # from the evidence it already gathered. Live transcript: model
                # had 8 search results with "16°, overcast" but answered
                # "Would you like me to get the current weather from
                # weather-atlas.com?" — a non-answer after real work was done.
                # Inject ONE bounded re-prompt; one-shot guard prevents loops.
                if is_parent and any(
                    getattr(s, "tool_name", "") for s in getattr(trace, "steps", []) or []
                ):
                    _final_text = getattr(trace, "final_response", "") or ""
                    if answer_hedges_after_evidence(_final_text):
                        _already_hedge_nudged = any(
                            isinstance(m, dict)
                            and isinstance(m.get("content", ""), str)
                            and "[HEDGE]" in m.get("content", "")
                            for m in (loop_messages or [])
                        )
                        if not _already_hedge_nudged and iteration + 1 < effective_max_iter:
                            if obs:
                                obs.emit(
                                    "agent_loop_gate_failed_replan",
                                    intent=intent.value,
                                    iteration=iteration + 1,
                                    unmet=["model hedged after evidence — asked user to choose"],
                                )
                            loop_messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        "\n[HEDGE] You gathered evidence (tools ran) but then asked "
                                        "the user to choose or confirm instead of synthesizing the "
                                        "answer. Do NOT ask 'Would you like me to...' or 'Which "
                                        "source would you prefer?'. You already have the evidence — "
                                        "synthesize a direct answer from it NOW, or fetch ONE specific "
                                        "page if the snippets lack the detail you need. Do not ask the "
                                        "user to decide; act.\n"
                                    ),
                                }
                            )
                            return "", False
                return "", True
            _streak, _streak_tool = same_tool_failure_streak(trace)
            if iteration + 1 >= effective_max_iter or _streak >= _SAME_TOOL_REPLAN_CAP:
                # Out of iterations / same-tool spiral — stop honestly rather
                # than loop the same failure (spec §18 loop protection).
                trace.gate_summary = f"✗ completion floor: {_floor_note}"
                return f"\n\n{trace.gate_summary}", True
            revised = await self._replan_for_gate(
                trace=trace,
                unmet=[("(parent completion floor)", _floor_note)],
                loop_messages=loop_messages,
                observation_log=observation_log,
                active_adapter=active_adapter,
            )
            if obs:
                obs.emit(
                    "agent_loop_gate_failed_replan",
                    intent=intent.value,
                    iteration=iteration + 1,
                    unmet=[_floor_note],
                )
            loop_messages.append(
                {
                    "role": "user",
                    "content": (
                        "\n[COMPLETION FLOOR] You reported done, but your last "
                        f"action failed:\n- {_floor_note}\n\nRevised plan:\n{revised}\n"
                        "\nDo NOT report done until that action succeeds. Continue working."
                    ),
                }
            )
            return "", False
        # Run-scoped evidence guard (same as is_coding_done): never gate on
        # pre-existing workspace state before this run executed a tool.
        if not any(step.tool_name for step in getattr(trace, "steps", [])):
            return "", True

        from core.agent.verify import evaluate_criteria, format_gate_results, gate_passed

        results = evaluate_criteria(criteria, trace)
        trace.criteria_results = results
        trace.gate_passed = gate_passed(results)
        # Session 192 — same-tool replan bound. Consecutive failures on the
        # same tool means the APPROACH is wrong: stop replanning and report
        # honestly instead of looping the same failure (the 480s spiral).
        #
        # Tradeoff (Session 192 review): CAP=2 gives the model exactly ONE
        # replan cycle after the first same-tool failure — the gate only fires
        # at the model's "done" claim, so a model that heeds the revised plan
        # (e.g. pivots to find_path) breaks the streak on the next step and is
        # never blocked. Only a model that repeats the same tool after the
        # corrective replan gets stopped. That is precisely the transcript
        # pattern (17 same-tool retries, never pivoting).
        _streak, _streak_tool = same_tool_failure_streak(trace)
        _block_replan = _streak >= _SAME_TOOL_REPLAN_CAP
        if trace.gate_passed:
            trace.gate_summary = format_gate_results(results)
            # Session 179 — F4 Mandatory post-execution verifier for
            # high-stakes intents. Even when criteria pass, run ONE
            # additional deterministic check that the LAST tool's output
            # has no error markers. If the last tool failed (e.g. the
            # model said "done" but the file_write returned an error
            # string), reject "done" and force a replan — same path as
            # criteria-fail below. Closes the gap where the GoalInterpreter's
            # derived criteria check the FIRST tool's outcome but miss a
            # subsequent tool's failure.
            from core.agent.post_execution_verifier import post_execution_verify

            _pe_passed, _pe_note = post_execution_verify(trace, intent)
            if not _pe_passed:
                # Treat as criteria-fail: replan if iterations remain AND the
                # same-tool failure streak hasn't hit its bound (Session 192).
                unmet = [("(post-execution verifier)", _pe_note)]
                if iteration + 1 < effective_max_iter and not _block_replan:
                    # Session 178 — notify the orchestrator (same path as
                    # criteria-fail above).
                    _orchestrator_hint = ""
                    if orchestrator is not None:
                        if obs:
                            obs.emit(
                                "orchestrator_replan_start",
                                intent=intent.value,
                                iteration=iteration + 1,
                                unmet=[c for c, _ in unmet][:3],
                            )
                        try:
                            from core.agent.orchestrator import OrchestrationStep

                            _last_step = None
                            for _s in reversed(getattr(trace, "steps", []) or []):
                                if _s.tool_name:
                                    _last_step = _s
                                    break
                            _failed_step = OrchestrationStep(
                                tool=_last_step.tool_name if _last_step else "(unknown)",
                                args=(
                                    {"input": (_last_step.tool_input or "")[:200]}
                                    if _last_step
                                    else {}
                                ),
                                reason=_pe_note[:300],
                            )
                            _replan_result = await orchestrator.replan(
                                reformulated_message=reformulated_message
                                or _user_message_text(loop_messages),
                                intent=intent,
                                failed_step=_failed_step,
                                failure_reason=_pe_note[:200],
                                adapter=active_adapter,
                                memory_facts=memory_facts,
                                intent_history=intent_history,
                                obs=obs,
                            )
                            if _replan_result and _replan_result.orchestrator_context:
                                _orchestrator_hint = (
                                    f"\n[ORCHESTRATOR — confidence dropped to "
                                    f"{round(_replan_result.confidence, 2)}]\n"
                                    f"{_replan_result.orchestrator_context}\n"
                                )
                            if obs:
                                obs.emit(
                                    "orchestrator_replan_done",
                                    confidence=round(_replan_result.confidence, 2)
                                    if _replan_result
                                    else 0.0,
                                    intent=intent.value,
                                )
                        except Exception as _orch_exc:  # pragma: no cover — defensive
                            logger.warning(
                                "[agent.loop] orchestrator.replan (post-exec) failed "
                                "(non-fatal): %s",
                                _orch_exc,
                            )
                            if obs:
                                obs.emit(
                                    "orchestrator_replan_failed",
                                    error=str(_orch_exc)[:120],
                                    intent=intent.value,
                                )

                    revised = await self._replan_for_gate(
                        trace=trace,
                        unmet=unmet,
                        loop_messages=loop_messages,
                        observation_log=observation_log,
                        active_adapter=active_adapter,
                    )
                    if obs:
                        obs.emit(
                            "agent_loop_gate_failed_replan",
                            intent=intent.value,
                            iteration=iteration + 1,
                            unmet=[c for c, _ in unmet][:5],
                        )
                    block = (
                        "\n[POST-EXECUTION VERIFIER] Your last tool reported an error:\n"
                        f"- {_pe_note}\n"
                        + (_orchestrator_hint + "\n" if _orchestrator_hint else "")
                        + f"\nRevised plan:\n{revised}\n"
                        + "\nDo NOT report done until the error is fixed. Continue working."
                    )
                    loop_messages.append({"role": "user", "content": block})
                    return "", False
                # Cap hit — honest report (iteration cap or same-tool streak).
                trace.gate_summary = f"✗ post-execution verifier: {_pe_note}"
                if _block_replan:
                    if obs:
                        obs.emit(
                            "agent_loop_repeated_tool_stop",
                            tool=_streak_tool,
                            streak=_streak,
                            iteration=iteration + 1,
                        )
                    trace.gate_summary += (
                        f" Stopped after {_streak} consecutive failures on "
                        f"'{_streak_tool}' — retrying the same tool won't fix it."
                    )
                return f"\n\n{trace.gate_summary}", True
            return f"\n\n{trace.gate_summary}", True

        unmet = [(c, n) for c, passed, n in results if not passed]
        if iteration + 1 < effective_max_iter and not _block_replan:
            # Session 178 — Notify the orchestrator FIRST so its dead
            # replan() method finally runs, its confidence drops, and
            # the orchestrator_replan_* obs events fire for real (to be
            # consumed by the frontend in Session 180). The orchestrator
            # may also return a clarification_question or a re-route hint.
            _orchestrator_hint = ""
            if orchestrator is not None:
                # Session 178 — emit the obs events HERE (in the loop) so
                # they fire even when the orchestrator is mocked in tests
                # (the real AgentOrchestrator.replan also emits them, but
                # the loop is the authoritative source — it owns the call).
                if obs:
                    obs.emit(
                        "orchestrator_replan_start",
                        intent=intent.value,
                        iteration=iteration + 1,
                        unmet=[c for c, _ in unmet][:3],
                    )
                try:
                    # Build an OrchestrationStep describing the failed work.
                    # The trace's last failed step (or last tool) is the
                    # closest proxy we have without a richer TaskState.
                    from core.agent.orchestrator import OrchestrationStep

                    _last_step = None
                    for _s in reversed(getattr(trace, "steps", []) or []):
                        if _s.tool_name:
                            _last_step = _s
                            break
                    _failed_step = OrchestrationStep(
                        tool=_last_step.tool_name if _last_step else "(unknown)",
                        args=(
                            {"input": (_last_step.tool_input or "")[:200]}
                            if _last_step
                            else {}
                        ),
                        reason="; ".join(f"{c}: {n}" for c, n in unmet)[:300],
                    )
                    _replan_result = await orchestrator.replan(
                        reformulated_message=reformulated_message
                        or _user_message_text(loop_messages),
                        intent=intent,
                        failed_step=_failed_step,
                        failure_reason="; ".join(f"{c}: {n}" for c, n in unmet)[:200],
                        adapter=active_adapter,
                        memory_facts=memory_facts,
                        intent_history=intent_history,
                        obs=obs,
                    )
                    if _replan_result and _replan_result.orchestrator_context:
                        _orchestrator_hint = (
                            f"\n[ORCHESTRATOR — confidence dropped to "
                            f"{round(_replan_result.confidence, 2)}]\n"
                            f"{_replan_result.orchestrator_context}\n"
                        )
                        if _replan_result.clarification_question:
                            _orchestrator_hint += (
                                f"Clarification needed: "
                                f"{_replan_result.clarification_question}\n"
                            )
                    if obs:
                        obs.emit(
                            "orchestrator_replan_done",
                            confidence=round(_replan_result.confidence, 2)
                            if _replan_result
                            else 0.0,
                            intent=intent.value,
                        )
                except Exception as _orch_exc:  # pragma: no cover — defensive
                    logger.warning(
                        "[agent.loop] orchestrator.replan failed (non-fatal, "
                        "falling back to _replan_for_gate): %s",
                        _orch_exc,
                    )
                    if obs:
                        obs.emit(
                            "orchestrator_replan_failed",
                            error=str(_orch_exc)[:120],
                            intent=intent.value,
                        )

            revised = await self._replan_for_gate(
                trace=trace,
                unmet=unmet,
                loop_messages=loop_messages,
                observation_log=observation_log,
                active_adapter=active_adapter,
            )
            if obs:
                obs.emit(
                    "agent_loop_gate_failed_replan",
                    intent=intent.value,
                    iteration=iteration + 1,
                    unmet=[c for c, _ in unmet][:5],
                )
            block = (
                "\n[ACCEPTANCE GATE] Your success criteria are NOT yet met:\n"
                + "\n".join(f"- {c} — {n}" for c, n in unmet)
                + (_orchestrator_hint + "\n" if _orchestrator_hint else "")
                + f"\nRevised plan from the gate:\n{revised}\n"
                + "\nDo NOT report done until every criterion is met. Continue working."
            )
            loop_messages.append({"role": "user", "content": block})
            return "", False

        # Cap hit: strict + honest report — the answer must state what's
        # unmet (iteration cap or same-tool streak).
        trace.gate_summary = format_gate_results(results)
        if _block_replan:
            if obs:
                obs.emit(
                    "agent_loop_repeated_tool_stop",
                    tool=_streak_tool,
                    streak=_streak,
                    iteration=iteration + 1,
                )
            trace.gate_summary += (
                f" Stopped replanning after {_streak} consecutive failures on "
                f"'{_streak_tool}' — the current approach is not converging."
            )
        return f"\n\n{trace.gate_summary}", True

    async def _replan_for_gate(
        self,
        *,
        trace,
        unmet: list[tuple[str, str]],
        loop_messages: list[dict],
        observation_log: str,
        active_adapter,
    ) -> str:
        """Explicit LLM replan call (planning-prompt shape) for gate failure.

        Returns the revised plan text (capped); on any failure returns a
        directive to re-attempt so the loop always continues with a plan.
        """
        user_text = _user_message_text(loop_messages)
        unmet_text = "\n".join(f"- {c}: {n}" for c, n in unmet)
        evidence_tail = observation_log[-1200:] if observation_log else "(no tool observations recorded)"
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the replanning step of an acceptance-gate loop. "
                    "A previous plan did not meet its success criteria. Produce "
                    "a REVISED, concrete, step-by-step plan to meet the unmet "
                    "criteria. Number each step."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Task: {user_text}\n"
                    f"Success criteria: {'; '.join(trace.success_criteria)}\n"
                    f"Unmet criteria:\n{unmet_text}\n"
                    f"Evidence so far (tail):\n{evidence_tail}\n"
                    "Revised plan:"
                ),
            },
        ]
        plan_chunks: list[str] = []

        async def _collect_replan():
            async for chunk in active_adapter.chat(messages, temperature=0.1, intent="chat"):
                if chunk.error:
                    break
                text = _filter_system_leaks(chunk.text)
                if text:
                    plan_chunks.append(text)

        try:
            await asyncio.wait_for(
                _collect_replan(),
                timeout=_plan_timeout_for(active_adapter),
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[agent.loop] gate replan stream timed out (%ss)",
                _plan_timeout_for(active_adapter),
            )
        except Exception as exc:
            logger.warning("[agent.loop] gate replan call failed: %s", exc)
        plan_text = "".join(plan_chunks).strip()
        if not plan_text:
            plan_text = "Re-attempt the failed steps, then verify each criterion against the evidence."
        return plan_text[:1500]

    # ------------------------------------------------------------------
    # Web-search result handler
    # ------------------------------------------------------------------

    async def _handle_web_search_result(
        self,
        safe_obs: str,
        query: str,
        thought: str,
        iteration: int,
        trace: AgentTrace,
        user_question: str = "",
        reasoning: str = "",
        adapter=None,
        allowed_tool_names: Optional[frozenset[str]] = None,
    ) -> AsyncIterator[StreamChunk]:
        """
        Synthesize search results into a user-facing answer, with follow-up
        fetching when snippets are insufficient.

        Pipeline:
        1. Run synthesizer on search snippets
        2. If snippets are sufficient -> LLM synthesizes answer directly
        3. If snippets need followup -> fetch top URL(s), then use
           synthesize_combined() with a dedicated prompt that prioritizes
           the fetched page content over the snippets

        NEVER dumps raw web content to the user. All output goes through
        the LLM synthesizer or smart regex extraction as a last resort.
        """
        filename = f"search_results_{int(time.time())}.md"

        file_content = (
            f"# Web Search Results: {query}\n\n*Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}*\n\n{safe_obs}"
        )

        # Fire-and-forget: write the raw results file in the background.
        async def _write_file() -> None:
            try:
                await dispatch_with_retry(
                    Intent.FILE_WRITE,
                    f"{filename}:\n\n{file_content}",
                    allowed_tool_names=allowed_tool_names,
                )
                logger.info(f"[agent.loop] web search results written to {filename}")
            except Exception as exc:
                logger.warning(f"[agent.loop] search result file write failed: {exc}")

        asyncio.create_task(_write_file())

        # ── Synthesis pipeline ──────────────────────────────────────────
        synthesis_answer = None

        if self._synthesizer.enabled:
            try:
                # Create a ToolResult from the search output for the synthesizer
                from core.models import RiskLevel, ToolResult

                search_result = ToolResult(
                    content=safe_obs,
                    risk=RiskLevel.LOW,
                    source="web_search",
                )

                # Step 1: Check sufficiency of search snippets
                synthesis = await self._synthesizer.synthesize(
                    tool_results=[search_result],
                    intent=Intent.WEB_SEARCH,
                    user_question=user_question or query,
                    adapter=adapter or self._adapter,
                )

                if synthesis.needs_followup and synthesis.followup_tool == "web_fetch":
                    # Snippets are insufficient — fetch the top URL for actual data
                    followup_url = (synthesis.followup_args or {}).get("url", "")
                    if followup_url:
                        logger.info(f"[agent.loop] synthesis requests web_fetch for: {followup_url[:80]}")
                        # Emit a status chunk so the user knows we're fetching
                        yield StreamChunk(text="", done=False, status=f"Reading page: {followup_url[:60]}")
                        fetch_result, fetch_failed, _ = await dispatch_with_retry(
                            Intent.WEB_FETCH,
                            followup_url,
                            allowed_tool_names=allowed_tool_names,
                        )
                        if fetch_result and not fetch_failed:
                            # Step 2: Use synthesize_combined() — this is the PRIMARY
                            # synthesis path for web queries. It uses a dedicated prompt
                            # that prioritizes fetched page content over search snippets,
                            # and pre-processes the content to remove ads/noise.
                            fetch_synthesis = await self._synthesizer.synthesize_combined(
                                search_result=search_result,
                                fetch_result=fetch_result,
                                user_question=user_question or query,
                                adapter=adapter or self._adapter,
                            )
                            synthesis_answer = fetch_synthesis.answer
                        else:
                            # Fetch failed — use the search-only synthesis
                            synthesis_answer = synthesis.answer or (
                                "I found some relevant results but couldn't read the "
                                "full page content. The search snippets didn't contain "
                                "enough detail to fully answer your question."
                            )
                    else:
                        synthesis_answer = synthesis.answer or (
                            "I found search results but need more detail. "
                            "The search snippets didn't contain enough specific data."
                        )
                elif synthesis.answer:
                    # Search snippets were sufficient — use the synthesized answer
                    synthesis_answer = synthesis.answer
                elif synthesis.is_gap_report:
                    # Honest gap report
                    synthesis_answer = synthesis.answer

            except Exception as e:
                logger.warning(f"[agent.loop] synthesis failed: {e}")
                # Use smart extraction instead of dumping raw content
                from core.agent.synthesizer import _smart_extract_key_data

                synthesis_answer = _smart_extract_key_data(safe_obs, user_question or query)

        # Fallback: if synthesis didn't produce an answer, use smart extraction
        if not synthesis_answer:
            from core.agent.synthesizer import _smart_extract_key_data

            synthesis_answer = _smart_extract_key_data(safe_obs, user_question or query)

        trace.final_response = synthesis_answer
        trace.steps.append(
            AgentStep(
                iteration=iteration + 1,
                thought=thought,
                tool_name="web_search",
                tool_input=query,
                observation=f"Results → {filename}, synthesized answer provided",
            )
        )

        yield StreamChunk(text=synthesis_answer, done=False)
        yield StreamChunk(text="", done=True)

    # ------------------------------------------------------------------
    # Parent initialization phase
    # ------------------------------------------------------------------

    async def _initialize_parent_streaming(
        self,
        active_adapter,
        messages: list[dict],
        env_context: str,
        intent_history: Optional[list[str]] = None,
    ):
        """Stream the parent initializer with progressive public events.

        ADR-34 B-7: the user must see a model-owned acknowledgement and a
        bounded understanding line as soon as the provider emits them —
        not a single parsed blob 7+ seconds in.  This generator yields
        ``(event_type, payload)`` tuples that the parent runtime forwards
        to the SSE boundary as bounded ``StreamChunk`` events.

        Yielded events (in order):
        - ``("ack", str)`` — the model's acknowledgement, ≤600 chars.
        - ``("understanding", str)`` — a bounded thinker line combining
          objective + clarifying question + mode.  Emitted at most once
          per turn, after ack.
        - ``("decision", InitializationDecision)`` — the final parsed
          decision.  Always yielded exactly once, last.

        Raw chain-of-thought, full JSON envelope, and tool-schema prose
        are NEVER yielded.  Only bounded public fields surface to the user.
        """
        user_message = _user_message_text(messages)
        conversation_history = [
            message
            for message in messages
            if message.get("role") in {"user", "assistant"}
        ]
        prompt = build_initialization_prompt(
            user_message=user_message,
            env_context=env_context,
            history=conversation_history,
        )
        init_messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_message},
        ]
        from core.error_normalizer import is_terminal_pre_generation_error

        chunks: list[str] = []
        # Event queue: the producer task pushes ("ack", str) / ("understanding", str)
        # / ("decision", InitializationDecision) / ("error", Exception) tuples.
        # The consumer generator pulls them in order.  This decouples streaming
        # from yielding and propagates exceptions cleanly.
        event_queue: asyncio.Queue = asyncio.Queue()
        last_preview = InitializationPreview()
        # Session 290: accumulate the init call's provider usage. On a DIRECT
        # turn the init call is the whole turn, so this is the real token usage
        # (previously dropped, forcing an inflated estimate).
        usage_acc: dict = {}

        async def _stream_producer() -> None:
            ack_sent = False
            understanding_sent = False
            decision_sent = False
            try:
                async for chunk in active_adapter.chat(
                    init_messages,
                    temperature=0.1,
                    intent="chat",
                ):
                    if getattr(chunk, "usage", None):
                        usage_acc.update(chunk.usage)
                    if chunk.error:
                        if is_terminal_pre_generation_error(chunk.error):
                            await event_queue.put(("error", TerminalProviderError(chunk.error)))
                            return
                        logger.warning(
                            "[agent.loop] initialization adapter error: %s",
                            chunk.error[:120],
                        )
                        # Non-terminal error (e.g. transient 503) — fall open
                        # to execute mode so the parent loop can retry or
                        # surface a clean error.  Do NOT hang the consumer.
                        decision = parse_initialization("".join(chunks))
                        await event_queue.put(("decision", decision))
                        decision_sent = True
                        return
                    # Whitespace-safe per-chunk filtering: the stream variant
                    # removes tool-call markup WITHOUT trimming edges, so the
                    # spaces between streamed JSON deltas survive the join
                    # (Session 231: the trimming variant collapsed the init
                    # objective + response into spaceless text).
                    text = _strip_minimax_tool_calls_stream(_filter_system_leaks(chunk.text))
                    if not text:
                        continue
                    chunks.append(text)
                    # Progressive extraction: surface new public fields as soon
                    # as the partial JSON contains them.  We never yield raw
                    # JSON or chain-of-thought — only the bounded values of
                    # acknowledgement / objective / response / clarifying_question.
                    preview = extract_preview("".join(chunks))
                    diff = last_preview.diff(preview)
                    # Update last_preview in place so the next diff only fires
                    # for genuinely new content.
                    for field, new_value in diff.items():
                        setattr(last_preview, field, new_value)
                    # Session 237: for DIRECT (trivial / needs-thought-no-tools)
                    # turns, suppress the acknowledgement AND the understanding.
                    # The reply itself streams immediately, so an ack like
                    # "Hello there!" before "Hi! How can I help you today?" is
                    # a redundant second greeting, and a "respond to a greeting"
                    # thought is pure theater (ADR-37: trivial → just reply, no
                    # narration). `mode` is the first JSON field, so it is known
                    # by the time ack/objective appear. Ack + understanding stay
                    # for execute/clarify turns, where there is real work to
                    # acknowledge and real reasoning to show.
                    _direct = last_preview.mode == "direct"
                    if not ack_sent and last_preview.acknowledgement and not _direct:
                        ack_sent = True
                        await event_queue.put(("ack", last_preview.acknowledgement[:600]))
                    # Emit understanding at most once — when the model's
                    # OBJECTIVE (its reasoning about what the user wants) or a
                    # clarifying_question first appears. The `response` (the
                    # answer itself) is deliberately NOT a trigger: surfacing
                    # it here would make the "thought process" identical to the
                    # final answer (rendered in the ThinkingBlock AND the
                    # workspace card) and would expose the answer as
                    # chain-of-thought, which ADR-34 forbids.
                    if not understanding_sent and not _direct and (
                        last_preview.objective
                        or last_preview.clarifying_question
                    ):
                        understanding_sent = True
                        line = render_understanding(last_preview)
                        if line:
                            await event_queue.put(("understanding", line))
                # Stream ended — parse the full JSON and emit the final decision.
                _raw_joined = "".join(chunks)
                decision = parse_initialization(_raw_joined)
                # ADR-34 B-12: record the init prompt size for budget measurement.
                decision.init_prompt_chars = len(prompt)
                decision.usage = dict(usage_acc)
                # Observability (Session 290): log the mode AND a snippet of the
                # model's raw output so an operator can confirm WHY a turn went
                # direct vs execute — e.g. "execute" on a plain 'Hi' means the
                # model explicitly chose it, while a direct-from-unparseable
                # shows the raw prose we recovered. Answers "what is happening?".
                logger.info(
                    "[agent.loop] parent initialization mode=%s conf=%.2f prompt_chars=%d raw=%r",
                    decision.mode,
                    decision.confidence,
                    decision.init_prompt_chars,
                    _raw_joined[:200],
                )
                await event_queue.put(("decision", decision))
                decision_sent = True
            except Exception as exc:
                if is_terminal_pre_generation_error(exc):
                    await event_queue.put(("error", TerminalProviderError(str(exc))))
                    return
                logger.warning("[agent.loop] initialization producer failed: %s", exc)
                # Still produce a final decision so the consumer doesn't hang.
                if not decision_sent:
                    decision = parse_initialization("".join(chunks))
                    await event_queue.put(("decision", decision))
                    decision_sent = True
            finally:
                # Safety net: if the producer exited without putting any event
                # (e.g. adapter returned immediately with no chunks and no
                # error), put a fail-open decision so the consumer unblocks.
                if not decision_sent:
                    try:
                        decision = parse_initialization("".join(chunks))
                    except Exception:
                        decision = parse_initialization("")
                    await event_queue.put(("decision", decision))

        producer_task = asyncio.create_task(_stream_producer())

        try:
            while True:
                # Wait for the next event with a timeout so we can also check
                # whether the producer has finished without blocking forever.
                try:
                    event_type, payload = await asyncio.wait_for(
                        event_queue.get(), timeout=_plan_timeout_for(active_adapter)
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "[agent.loop] initialization timed out after %.0fs",
                        _plan_timeout_for(active_adapter),
                    )
                    # Salvage whatever the model streamed before the cap — a
                    # slow model that produced partial prose still answers
                    # (bounded direct), instead of being discarded into the
                    # tool loop. parse_initialization keeps execute opt-in.
                    yield ("decision", parse_initialization("".join(chunks)))
                    return
                if event_type == "error":
                    if isinstance(payload, TerminalProviderError):
                        raise payload
                    # Non-terminal error → bounded direct answer from whatever
                    # arrived, never an unrequested tool loop.
                    yield ("decision", parse_initialization("".join(chunks)))
                    return
                if event_type == "decision":
                    yield (event_type, payload)
                    return
                yield (event_type, payload)
        finally:
            if not producer_task.done():
                producer_task.cancel()
                try:
                    await producer_task
                except (asyncio.CancelledError, Exception):
                    pass

    # ------------------------------------------------------------------
    # Planning phase (child-agent compatibility)
    # ------------------------------------------------------------------

    async def _plan_stream(
        self,
        active_adapter,
        intent: Intent,
        loop_messages: list[dict],
        available_tools: list[dict],
        env_context: str,
        intent_history: Optional[list[str]] = None,
        tool_defs: Optional[list[dict]] = None,
    ):
        """
        Streaming version of _plan — yields plan tokens as they arrive.

        This lets the user see the model's planning reasoning (UNDERSTANDING,
        STEPS, ARGS_PRECHECK) in real-time in the thinking block, instead of
        waiting 5-15s for the full plan to be generated before showing anything.
        """
        # Find the user message
        user_message = ""
        for msg in reversed(loop_messages):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break
        if not user_message:
            return

        planning_prompt = build_planning_prompt(
            intent=intent,
            user_message=user_message,
            available_tools=available_tools,
            env_context=env_context,
            intent_history=intent_history,
            tool_defs=tool_defs,
        )

        planning_messages = [
            {"role": "system", "content": planning_prompt},
            {"role": "user", "content": user_message},
        ]

        try:
            _plan_timeout = _plan_timeout_for(active_adapter)
            from core.error_normalizer import is_terminal_pre_generation_error

            # Use a queue for real-time streaming with timeout
            _plan_queue: asyncio.Queue = asyncio.Queue()
            _SENTINEL = object()
            _terminal_error: list[TerminalProviderError] = []

            async def _stream_plan():
                try:
                    async for chunk in active_adapter.chat(
                        planning_messages,
                        temperature=0.1,
                        intent="chat",
                    ):
                        if chunk.error:
                            if is_terminal_pre_generation_error(chunk.error):
                                _terminal_error.append(TerminalProviderError(chunk.error))
                            logger.warning("[agent.loop] plan stream adapter error: %s", chunk.error[:120])
                            break
                        text = _filter_system_leaks(chunk.text)
                        # Session 148: strip DSML/MiniMax tool-call markup from
                        # planning text too — a model that emits a stray tool
                        # call block here would otherwise leak it into the plan
                        # context and the thinking stream.
                        # Session 231: use the whitespace-SAFE stream variant —
                        # the trimming one removed the spaces between streamed
                        # deltas, so the plan/thinking text rendered spaceless.
                        text = _strip_minimax_tool_calls_stream(text)
                        if text:
                            await _plan_queue.put(text)
                finally:
                    await _plan_queue.put(_SENTINEL)

            _task = asyncio.create_task(_stream_plan())
            try:
                while True:
                    try:
                        item = await asyncio.wait_for(_plan_queue.get(), timeout=_plan_timeout)
                    except asyncio.TimeoutError:
                        _task.cancel()
                        logger.warning(f"[agent.loop] planning stream timed out ({_plan_timeout}s)")
                        break
                    if item is _SENTINEL:
                        break
                    yield item
                # Ensure the task completes — but don't hang if it already
                # finished or errored. Use a short timeout.
                # NOTE: same BaseException trap as the dispatcher (Session 127):
                # awaiting a task cancelled by the timeout path above raises
                # CancelledError, which `except (TimeoutError, Exception)` does
                # NOT catch in py3.8+ — it would escape and kill the whole
                # request. gather(return_exceptions=True) absorbs it.
                try:
                    _task_results = await asyncio.wait_for(
                        asyncio.gather(_task, return_exceptions=True),
                        timeout=5,
                    )
                except Exception:
                    _task.cancel()
                    _task_results = []
                if _terminal_error:
                    raise _terminal_error[0]
                for _task_result in _task_results:
                    if isinstance(_task_result, TerminalProviderError):
                        raise _task_result
                    if isinstance(_task_result, Exception) and is_terminal_pre_generation_error(_task_result):
                        raise TerminalProviderError(str(_task_result))
            except asyncio.CancelledError:
                # External cancellation of the generator itself (client abort):
                # cancel the child task, then propagate cleanly.
                _task.cancel()
                raise
            except Exception:
                _task.cancel()
                raise

        except TerminalProviderError:
            raise
        except Exception as exc:
            from core.error_normalizer import is_terminal_pre_generation_error

            if is_terminal_pre_generation_error(exc):
                raise TerminalProviderError(str(exc)) from exc
            logger.warning(f"[agent.loop] planning stream failed (non-fatal): {exc}")

    # ------------------------------------------------------------------
    # Post-execution verification
    # ------------------------------------------------------------------

    async def _verify_tool_result(
        self,
        tool_name: str,
        tool_args: dict,
        observation: str,
        allowed_tool_names: Optional[frozenset[str]] = None,
        result_path: Optional[str] = None,
    ) -> Optional[str]:
        """
        Verify a tool result after successful execution.

        Returns:
            A verification message to append to the observation, or None
            if no verification was needed or it passed silently.

        Verification checks:
        - file_write: Read the file back to confirm it exists and has content
        - code_exec: Check for Python error indicators in the output
        - shell: Check for common error patterns in the output
        """
        try:
            # ── file_write verification ──────────────────────────────────
            if tool_name == "file_write" and VERIFY_FILE_WRITE:
                # S293: read back WHERE THE WRITE LANDED (result_path from the
                # tool's metadata) not the model's raw arg — they diverge on a
                # re-anchored path or a timestamp-renamed document, which used
                # to fail verification for a perfectly good write (B-2026-08-17-6).
                path = result_path or tool_args.get("path", "")
                expected_len = len(tool_args.get("content", ""))
                if not path:
                    return None

                # Dispatch a file_task to read the file back
                # NOTE: dispatch_with_retry is imported at module level (line 177).
                # Do NOT re-import it here — that would shadow the module-level
                # binding and cause UnboundLocalError in other parts of run().
                verify_result, verify_failed, _ = await dispatch_with_retry(
                    Intent.FILE_TASK,
                    path,
                    max_retries=0,  # no retry for verification
                    allowed_tool_names=allowed_tool_names,
                )
                if verify_failed or not verify_result or not verify_result.success:
                    return (
                        f"File verification FAILED — could not read back '{path}'. "
                        f"The file may not have been written correctly."
                    )

                actual_content = verify_result.content or ""
                actual_len = len(actual_content)

                # Check if the file was written with reasonable content
                if actual_len == 0:
                    return (
                        f"File verification FAILED — '{path}' exists but is empty. "
                        f"Expected {expected_len} chars of content."
                    )

                # Check for significant truncation (>50% content loss)
                if expected_len > 100 and actual_len < expected_len * 0.5:
                    return (
                        f"File verification WARNING — '{path}' may be truncated. "
                        f"Written {actual_len} chars but expected ~{expected_len} chars. "
                        f"Consider rewriting the file with complete content."
                    )

                logger.info(
                    f"[agent.loop] file_write verification passed: "
                    f"path={path} expected={expected_len} actual={actual_len}"
                )
                # Surface the loop's OWN read-back result as evidence: a factual
                # statement of what the runtime found on disk. It deliberately does
                # NOT tell the agent whether to read the file back itself — that
                # phantom "do NOT read it back" / "read it back" instruction is a
                # bug (it fought legitimate user requests and second-guessed the
                # agent); the agent decides based on the actual task (B-2026-08-18-7).
                return f"file_write confirmed — {actual_len} chars verified on disk at {path}."

            # ── code_exec verification ───────────────────────────────────
            if tool_name == "code_exec" and VERIFY_CODE_EXEC:
                # Check for common Python error patterns in the output
                error_indicators = [
                    "Traceback (most recent call last)",
                    "SyntaxError:",
                    "IndentationError:",
                    "NameError:",
                    "TypeError:",
                    "ValueError:",
                    "ImportError:",
                    "ModuleNotFoundError:",
                    "KeyboardInterrupt",
                ]
                found_errors = [e for e in error_indicators if e in observation]
                if found_errors:
                    return f"Code execution produced errors: {', '.join(found_errors[:3])}. Fix the code and try again."
                return None

        except Exception as exc:
            logger.warning(f"[agent.loop] verification failed (non-fatal): {exc}")
            return None

        return None

    # ------------------------------------------------------------------
    # Trace summarization — for silent-failure fallbacks (Session 31)
    # ------------------------------------------------------------------

    @staticmethod
    def _summarize_trace_for_user(
        trace, observation_log: str, synthesis_failure_reason: Optional[str] = None
    ) -> str:
        """
        Build a user-facing summary of what tools actually ran, for the
        silent-failure fallback path. Returns an empty string if no tools
        ran (so the caller knows there's nothing to summarize).

        Session 31 (revised per user feedback): the previous version guessed
        "free-tier model overload" — a plausible-sounding but unverified
        self-diagnosis. The user correctly pushed back: for a 4-step task
        (mkdir, git init, write a small file, commit), context overflow is
        not plausible. The real cause is more likely a tool returning
        broken/unexpected data that the synthesizer chokes on.

        The honest fix: surface the ACTUAL tool inputs and outputs (truncated)
        so the user can see for themselves what happened. Don't guess at the
        cause — let the evidence speak. If a tool returned malformed data,
        the user will spot it immediately in the output.

        Args:
            trace: AgentTrace with .steps (list of AgentStep).
            observation_log: the failed-tool log (may be empty if all
                tools succeeded).

        Returns:
            A user-facing string with tool call details, or "" if no tool
            calls ran.
        """
        # Collect tool calls from the trace (skip pure-thinking steps
        # where tool_name is None).
        tool_calls = [s for s in trace.steps if s.tool_name]
        if not tool_calls:
            # No tools ran — return empty so caller falls back to the
            # model-overload suggestion in _force_final_answer.
            return ""

        # B-2026-08-16-12: the Thinker's analysis (if any) was preserved on
        # the trace by the loop — surface it instead of discarding the
        # already-computed synthesis when the final model call fails.
        thinker_block = ""
        if trace is not None:
            thinker_block = (getattr(trace, "thinker_analysis", "") or "").strip()

        if synthesis_failure_reason:
            if thinker_block:
                intro = (
                    f"I ran the requested tools but couldn't synthesize a final "
                    f"answer ({synthesis_failure_reason}). Here's what I'd "
                    f"already worked out from the evidence, plus the raw tool "
                    f"calls:"
                )
            else:
                intro = (
                    f"I ran the requested tools but couldn't synthesize a final "
                    f"answer ({synthesis_failure_reason}). Instead of guessing "
                    f"why, here's the raw evidence — each tool I called, what I "
                    f"sent it, and what it returned:"
                )
        else:
            if thinker_block:
                intro = (
                    "I ran the requested tools but the model couldn't summarize "
                    "what happened (it returned an empty response). Here's what "
                    "I'd already worked out from the evidence, plus the raw tool "
                    "calls:"
                )
            else:
                intro = (
                    "I ran the requested tools but the model couldn't summarize "
                    "what happened (it returned an empty response). Instead of "
                    "guessing why, here's the raw evidence — each tool I called, "
                    "what I sent it, and what it returned:"
                )
        lines = [intro, ""]
        if thinker_block:
            lines.append(thinker_block)
            lines.append("")
        # Session 32: if the iteration limit was hit, say so explicitly.
        # The previous fallback guessed "overload" — that was a wrong
        # diagnosis. The real cause was almost always the iteration cap
        # being too low (now fixed — raised from 3 to 8). When hit_limit
        # is True, the user needs to know: the model didn't fail, it just
        # ran out of iterations before finishing the task.
        if getattr(trace, "hit_limit", False):
            lines.insert(0, (
                f"I hit my iteration limit ({trace.iterations_used} iterations) "
                f"before completing the task. This is NOT a model overload or "
                f"context-overflow issue — I simply ran out of steps. Here's "
                f"what I managed to do before the cap:"
            ))
            # Remove the generic "couldn't summarize" line we just added —
            # it's misleading when the real cause is the iteration cap. Keep
            # the Thinker block (index >= 3) if present — it's real evidence.
            lines = [lines[0], ""] + lines[3:]
        for i, step in enumerate(tool_calls, 1):
            status = "FAILED" if step.tool_failed else "ok"
            _input = (step.tool_input or "").strip()
            if len(_input) > 120:
                _input = _input[:117] + "..."
            lines.append(f"  {i}. {step.tool_name}({_input}) — {status}")

            # ALWAYS surface the observation (tool output), not just for
            # failed tools. The user's point is that a SUCCEEDED tool might
            # be returning malformed data that chokes the synthesizer —
            # we need to show success outputs too, not just error outputs.
            if step.observation:
                _obs_text = step.observation.strip()
                if len(_obs_text) > 300:
                    _obs_text = _obs_text[:297] + "..."
                # First non-empty line, or the whole thing if single-line
                _first_line = _obs_text.splitlines()[0] if _obs_text.splitlines() else _obs_text
                if step.tool_failed:
                    lines.append(f"     → error: {_first_line}")
                else:
                    lines.append(f"     → output: {_first_line}")

        # Surface the observation log too if it has content (failed tools
        # are logged here with their full error context — more detail than
        # the per-step snippet above).
        if observation_log.strip():
            lines.append("")
            lines.append("Full error details:")
            lines.append(observation_log[:1500])

        lines.append("")
        # Session 32: tailor the "what to try" advice to the actual cause.
        # If hit_limit is True, the advice is "tell me to continue" or
        # "raise the iteration limit" — NOT "switch to a larger model"
        # (the model didn't fail, it just ran out of steps).
        if getattr(trace, "hit_limit", False):
            lines.append(
                "What to try next:\n"
                "  • Tell me to \"continue\" — I'll pick up where I left off\n"
                "    and finish the remaining steps.\n"
                "  • Or ask me to do one step at a time so each step gets\n"
                "    its own iteration budget.\n"
                "  • The iteration limit is configurable via the\n"
                "    LOCALMIND_MAX_ITERATIONS env var (default: 8)."
            )
        else:
            lines.append(
                "What to try next:\n"
                "  • Check the outputs above — if a tool returned something\n"
                "    unexpected, that's likely the real cause (not 'overload').\n"
                "  • Try one step at a time to isolate which step breaks.\n"
                "  • Or switch to a larger model if you want me to retry the\n"
                "    synthesis with more reasoning capacity."
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Deterministic evidence extraction (ZERO LLM calls — B-2026-08-20-15)
    # ------------------------------------------------------------------

    def _extract_answer_from_evidence(
        self,
        *,
        reasoning_buffer: str,
        observation_log: str,
        trace,
        user_message: str,
    ) -> str:
        """Extract the answer directly from evidence already in hand — no LLM call.

        B-2026-08-20-15 (Session 316): the user's insight — "the thinking text
        and other evidence already has all the answers." When the model's
        synthesis call fails (empty/timeout), the answer often already exists in:
        1. The reasoning buffer (the model's own analysis — "the temperature is
           16°C and overcast").
        2. The tool observations (search result snippets, shell output).

        This method extracts the answer DETERMINISTICALLY — no retry, no extra
        LLM call, zero latency. It's the first thing tried when synthesis fails;
        the retry-then-clean-message path is only the last resort.

        Extraction strategy (in priority order):
        - If the reasoning buffer contains a direct answer statement (mentions
          the user's key entity + a value/fact), extract the relevant sentence(s).
        - If tool observations contain the answer (e.g. search snippets with
          temperature, a shell output with the hostname), extract the relevant
          snippet.
        - Otherwise return "" (caller falls through to retry/clean-message).
        """
        # Strategy 1: extract from the reasoning buffer.
        # The model's reasoning often contains a sentence like "the current
        # temperature is 16°C" or "the hostname is xyz". Find sentences that
        # mention the user's key entity and look like answers.
        if reasoning_buffer and reasoning_buffer.strip():
            extracted = self._extract_answer_sentence(reasoning_buffer, user_message)
            if extracted:
                logger.info(
                    "[agent.loop] answer extracted from reasoning buffer (%d chars, zero-LLM)",
                    len(extracted),
                )
                return extracted

        # Strategy 2: extract from tool observations.
        # Search results often contain the answer in the snippet itself
        # (e.g. "Current Time: 7 июн 2026 г. 02:45:08.12 °C").
        if observation_log and observation_log.strip():
            extracted = self._extract_answer_from_observations(observation_log, user_message)
            if extracted:
                logger.info(
                    "[agent.loop] answer extracted from tool observations (%d chars, zero-LLM)",
                    len(extracted),
                )
                return extracted

        return ""

    def _extract_answer_sentence(self, reasoning: str, user_message: str) -> str:
        """Extract a direct-answer sentence from the model's reasoning buffer.

        Looks for sentences that contain factual answer markers (numbers with
        units, "is X", "temperature", "hostname", etc.) and the user's key
        entity. Returns the best candidate, or "" if none found.
        """
        import re

        if not reasoning or not reasoning.strip():
            return ""
        # Extract key entities from the user's message (lowercased, >3 chars).
        # e.g. "weather in Kitengela" → ["weather", "kitengela"]
        user_lower = (user_message or "").lower()
        entities = [
            w for w in re.findall(r"[a-z]{4,}", user_lower)
            if w not in {"what", "where", "when", "how", "tell", "give", "show",
                         "find", "list", "check", "please", "could", "would",
                         "should", "current", "about"}
        ]
        # Split reasoning into sentences.
        sentences = re.split(r'(?<=[.!?])\s+', reasoning.strip())
        # Score each sentence: does it mention an entity + a factual marker?
        factual_markers = (
            r'\d+\s*°?',  # temperature / numbers
            r'\d+\s*(?:km|kg|mb|gb|hz|ghz|mhz|fps|rpm|mph|kph) ?',  # units
            r'is\s+[\w-]+',  # "is X"
            r'are\s+[\w-]+',  # "are X"
            r'temperature',
            r'hostname',
            r'overcast|sunny|rainy|cloudy|clear',  # weather
            r'located|found|returned',
        )
        best = ""
        best_score = 0
        for sent in sentences:
            sent_lower = sent.lower()
            if len(sent) < 15 or len(sent) > 400:
                continue
            score = 0
            # Entity match
            for ent in entities:
                if ent in sent_lower:
                    score += 2
            # Factual marker match — REQUIRED. A sentence without a factual
            # marker is not an answer, even if it mentions the entity.
            # ("Let me try a different approach" mentions nothing factual.)
            has_factual = False
            for marker in factual_markers:
                if re.search(marker, sent_lower):
                    score += 1
                    has_factual = True
            if not has_factual:
                continue  # skip sentences with no factual content
            # Penalize meta-reasoning ("I should", "I need to", "let me")
            if any(p in sent_lower for p in (
                "i should", "i need to", "let me", "i'll ",
                "i will ", "try a different",
            )):
                score -= 5
            if score > best_score and score >= 2:
                best_score = score
                best = sent.strip()
        return best

    def _extract_answer_from_observations(self, obs_log: str, user_message: str) -> str:
        """Extract a direct answer from tool observations (search snippets, etc.).

        Search results often contain the answer in the snippet. e.g.:
        "Current Time: 7 июн 2026 г. 02:45:08.12 °C"
        This extracts the most relevant snippet line.
        """
        import re

        if not obs_log or not obs_log.strip():
            return ""
        user_lower = (user_message or "").lower()
        entities = [
            w for w in re.findall(r"[a-z]{4,}", user_lower)
            if w not in {"what", "where", "when", "how", "tell", "give", "show",
                         "find", "list", "check", "please", "could", "would",
                         "should", "current", "about"}
        ]
        # Look for lines in the observation log that contain a factual value
        # (number, temperature, etc.). Entity match is a bonus but the factual
        # marker is the primary signal — a line with "12 °C" is an answer even
        # if it doesn't repeat the user's entity word.
        lines = obs_log.splitlines()
        best = ""
        best_score = 0
        for line in lines:
            line = line.strip()
            if len(line) < 10 or len(line) > 300:
                continue
            line_lower = line.lower()
            score = 0
            # Entity match (bonus)
            for ent in entities:
                if ent in line_lower:
                    score += 1
            # Factual value markers (PRIMARY signal — weighted higher)
            if re.search(r'\d+\s*°', line_lower):  # temperature
                score += 5
            if re.search(r'\d{4}', line):  # year / time
                score += 2
            if re.search(r'(?:is|are|was|were)\s+\S', line_lower):
                score += 1
            # Penalize URLs / headers / result-count lines
            if line_lower.startswith("http"):
                score -= 10
            if line_lower.startswith("search results"):
                score -= 10
            if re.match(r'^\d+\.\s', line):  # numbered result header
                score -= 2
            if score > best_score and score >= 3:
                best_score = score
                best = line
        return best

    # ------------------------------------------------------------------
    # Forced final answer after iteration limit
    # ------------------------------------------------------------------

    def _synthesis_failure_fallback(
        self, trace, observation_log: str, timed_out: bool
    ) -> str:
        """Build a CLEAN user-facing message when final synthesis times out or crashes.

        B-2026-08-20-14 (Session 315): the old fallback dumped raw harness
        internals (``_summarize_trace_for_user`` with "I ran the requested
        tools but couldn't synthesize... What to try next: Check the outputs
        above") which reads as developer debug output, not a user answer. The
        new fallback is honest + concise: it says what was attempted and
        points the user at the Actions panel (where the tool evidence already
        lives). The raw tool-call trace is still in the Actions panel for
        users who want the detail; the chat bubble stays clean.
        """
        _tool_count = sum(1 for s in (trace.steps if trace else []) if getattr(s, "tool_name", ""))
        if _tool_count > 0:
            return (
                "I found the information you asked for, but I'm having trouble "
                "putting it into a clean final answer right now. The search "
                "results and tool outputs are in the Actions panel above — "
                "take a look, or ask me again and I'll retry."
            )
        if observation_log.strip():
            return (
                "I ran some tools but couldn't produce a final answer. "
                "The tool outputs are in the Actions panel — take a look, "
                "or ask me again and I'll retry."
            )
        if timed_out:
            return (
                "I ran out of time generating a response. Please try again, "
                "or rephrase your question."
            )
        return (
            "I couldn't generate a response for that request. "
            "Please try again, or rephrase your question."
        )

    async def _post_loop_synthesis_from_evidence(
        self,
        *,
        loop_messages: list[dict],
        observation_log: str,
        active_adapter,
        trace,
        provider_usage: dict[str, int],
        intent,
        obs,
    ) -> AsyncIterator[StreamChunk]:
        """B-2026-08-20-7: deterministic post-loop synthesis when tools ran
        but the model produced no usable final text.

        This is the LAST safety net before the empty-response fallback. It
        fires when:
        - at least one tool ran this turn (``trace.steps`` has a tool_name), AND
        - the final text is empty or trivially short.

        Unlike the B-2026-08-18-11 synthesis-from-reasoning rescue (which
        fires on empty-WITH-reasoning and counts against the recovery budget),
        this fires AFTER the loop has terminated and does NOT count against
        any recovery budget — it's a single final attempt to synthesize a
        real answer from the gathered tool evidence.

        Yields the synthesized text if non-empty; otherwise yields nothing
        (the caller falls through to the existing empty-message path).
        """
        # Guard: only fire when tools actually ran. A no-tool empty turn has
        # no evidence to synthesize from — the empty-message fallback is the
        # honest answer there.
        has_tool_evidence = any(
            getattr(s, "tool_name", "") for s in getattr(trace, "steps", []) or []
        )
        if not has_tool_evidence:
            return
        # Guard: only fire when there's observation log content to synthesize.
        if not (observation_log or "").strip():
            return
        _synth = ""
        try:
            active_adapter._one_shot_thinking_off = True  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            async for _chunk in self._force_final_answer(
                loop_messages=loop_messages,
                observation_log=observation_log,
                active_adapter=active_adapter,
                trace=trace,
                provider_usage=provider_usage,
                framing="final",
                suppress_report=True,
                suppress_empty_fallback=True,
            ):
                if _chunk.text:
                    _synth += _chunk.text
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("[agent.loop] post-loop evidence synthesis failed: %s", exc)
        _synth = _synth.strip()
        if _synth and len(_synth) >= 20:
            logger.info(
                "[agent.loop] empty-final-answer rescued by post-loop evidence "
                "synthesis (%d chars)", len(_synth),
            )
            if obs:
                obs.emit(
                    "post_loop_synthesis",
                    intent=getattr(intent, "value", ""),
                    chars=len(_synth),
                )
            yield StreamChunk(text=_synth, done=False)

    async def _rescue_final_answer(
        self,
        loop_messages: list[dict],
        observation_log: str,
        active_adapter,
        trace: Optional[AgentTrace],
        provider_usage: dict[str, int],
    ) -> AsyncIterator[StreamChunk]:
        """Session 147: rescue a heading-only final answer on NORMAL completion.

        The free-tier model frequently ends a tool-bearing turn with a bare
        heading ("**Git status**") instead of a synthesized answer. Before
        dumping the deterministic worker report, run ONE focused synthesis
        call (plain chat, user's request + tool observations) and stream its
        answer. Only fall back to the report when synthesis fails, times
        out, or itself produces a non-substantive reply.
        """
        _report_text = trace.work_report().render() if trace is not None else ""
        _synth = ""
        try:
            async for _chunk in self._force_final_answer(
                loop_messages=loop_messages,
                observation_log=observation_log,
                active_adapter=active_adapter,
                trace=trace,
                provider_usage=provider_usage,
                framing="final",
                suppress_report=True,
                suppress_empty_fallback=True,
            ):
                if _chunk.text:
                    _synth += _chunk.text
        except Exception as exc:
            logger.warning(f"[agent.loop] clean synthesis failed: {exc}")
        _synth = _synth.strip()
        if _synth and (trace is None or not trace.work_report().needs_report(_synth)):
            logger.info(
                "[agent.loop] heading-only final answer rescued by synthesis (%d chars)",
                len(_synth),
            )
            yield StreamChunk(text=_synth, done=False)
            return
        if _report_text:
            logger.info(
                "[agent.loop] final response did not report tool evidence; "
                "emitting worker report"
            )
            yield StreamChunk(text="\n\n" + _report_text, done=False)

    async def _force_final_answer(
        self,
        loop_messages: list[dict],
        observation_log: str,
        active_adapter,
        trace=None,
        provider_usage: Optional[dict[str, int]] = None,
        framing: str = "limit",
        suppress_report: bool = False,
        suppress_empty_fallback: bool = False,
    ) -> AsyncIterator[StreamChunk]:
        """
        After hitting MAX_ITERATIONS, ask the LLM to synthesize a final
        answer from everything gathered so far.  Uses plain chat() without
        tools — the model should just summarize what it knows.

        Session 31: now accepts an optional `trace` parameter so the
        empty-stream fallback can surface ACTUAL tool inputs/outputs
        instead of guessing "overload" (per user feedback — the overload
        diagnosis was unverified and likely wrong for small tasks).

        Session 147: `framing` selects the directive text — "limit" for the
        iteration-limit path (default, preserves prior behavior) or "final"
        for rescuing a heading-only answer on normal completion. When
        `suppress_report` is True, the internal needs_report append is
        skipped (the caller owns the report fallback decision).
        """
        # Strip tool_calls from messages for the plain chat call.
        # Convert tool results to user-readable context with generous truncation
        # (1500 chars — the 500-char limit was too aggressive and lost key info).
        clean_messages = []
        for msg in loop_messages:
            if msg.get("role") == "tool":
                # Tool results become user context — use generous truncation
                content = msg.get("content", "")
                if len(content) > 1500:
                    half = 750
                    content = content[:half] + f"\n…[{len(content) - 1500} chars omitted]…\n" + content[-half:]
                clean_messages.append(
                    {
                        "role": "user",
                        "content": f"[Tool result]: {content}",
                    }
                )
            elif msg.get("role") == "assistant" and msg.get("tool_calls"):
                # Keep text content, drop tool_calls — model sees it as its own prior turn
                clean_messages.append(
                    {
                        "role": "assistant",
                        "content": msg.get("content", "") or "I was gathering information.",
                    }
                )
            else:
                clean_messages.append(msg)

        if framing == "final":
            _directive = (
                "Your earlier reply was too short to answer the user. Provide a "
                "complete, direct final answer to the user's ORIGINAL request now, "
                "based EXACTLY on the tool results shown above. Do not call any "
                "tools — just answer directly.\n\n"
                "ANTI-FABRICATION: Your answer MUST be based EXACTLY on the tool "
                "results shown above. Do NOT invent file names, folder contents, "
                "or any data that was not in the tool output. If a tool showed "
                "3 items, report 3 items — never add items that 'seem typical'.\n\n"
                "SYNTHESIS: Do NOT copy the tool output verbatim. Synthesize a "
                "natural-language answer that addresses the user's question using "
                "the evidence. Report exact values (dates, numbers, names) from "
                "the tool output, but frame them in your own words."
            )
        else:
            _directive = (
                "Maximum iterations reached. Provide your best answer now "
                "based on everything gathered so far. Do not call any tools — "
                "just answer directly.\n\n"
                "ANTI-FABRICATION: Your answer MUST be based EXACTLY on the tool "
                "results shown above. Do NOT invent file names, folder contents, "
                "or any data that was not in the tool output. If a tool showed "
                "3 items, report 3 items — never add items that 'seem typical'.\n\n"
                "SYNTHESIS: Do NOT copy the tool output verbatim. Synthesize a "
                "natural-language answer that addresses the user's question using "
                "the evidence. Report exact values (dates, numbers, names) from "
                "the tool output, but frame them in your own words."
            )

        force_msg = clean_messages + [
            {
                "role": "user",
                "content": f"{observation_log}\n{_directive}",
            }
        ]
        # Session 31: track whether the model produced ANY non-empty text.
        # Free-tier models sometimes return an empty stream (zero chunks, or
        # chunks whose text is entirely filtered out as system-leak XML).
        # Without this check, _force_final_answer returns silently, the
        # engine sees an empty full_response_chunks, and the user gets the
        # uselessly generic "I wasn't able to complete that request. The
        # tool may have failed or returned no useful output." fallback —
        # with zero indication of what actually happened. This is the
        # "Tools execution failure" symptom the user reported.
        _provider_usage = provider_usage if provider_usage is not None else {}
        _any_text_yielded = False
        _final_chunks: list[StreamChunk] = []
        _final_text_parts: list[str] = []
        try:
            t_final = time.monotonic()
            async for chunk in active_adapter.chat(force_msg, temperature=0.4):
                if chunk.usage:
                    _provider_usage.update(chunk.usage)
                if chunk.error:
                    _error_report = trace.work_report().render() if trace is not None else ""
                    yield StreamChunk(
                        text=_error_report,
                        done=True,
                        error=chunk.error,
                        usage=dict(_provider_usage),
                    )
                    return
                filtered_text = _filter_system_leaks(chunk.text)
                # Session 148: strip DSML/MiniMax tool-call markup from the
                # final synthesis too — the browser-validated run leaked a raw
                # <｜DSML｜tool_calls> block into the answer because the rescue
                # path (framing='final') only ran the system-leak filter. The
                # model sometimes emits a tool call as plain text here even
                # though plain chat has no tools.
                # Session 246: use the STREAM variant — the trimming variant
                # ends with .strip(), which on a per-chunk basis eats the
                # boundary space between every delta and welds the synthesis
                # into spaceless text ("HereHere arethe", "storiesIfound").
                filtered_text = _strip_minimax_tool_calls_stream(filtered_text)
                if filtered_text:
                    _any_text_yielded = True
                    _final_text_parts.append(filtered_text)
                # ADR-41 (Session 254): forward the model's reasoning in the
                # final synthesis too — a thinking model (GLM) streams
                # reasoning before this answer as well. Held with the text
                # so the ThinkingBlock renders it before the answer.
                # (isinstance guard: test stubs may carry a truthy non-str
                # .thinking.)
                _thinking = (
                    _filter_system_leaks(chunk.thinking)
                    if isinstance(chunk.thinking, str) and chunk.thinking
                    else ""
                )
                # Hold the terminal marker until the worker report contract
                # has been enforced below.
                _final_chunks.append(
                    StreamChunk(text=filtered_text, thinking=_thinking, done=False, usage=dict(_provider_usage))
                )
            logger.info(f"[agent.loop] final synthesis: {round((time.monotonic() - t_final) * 1000)}ms")
        except Exception as exc:
            logger.warning(f"[agent.loop] final synthesis failed: {exc}")
            _error_report = trace.work_report().render() if trace is not None else ""
            if framing == "final":
                _exception_text = (
                    "I couldn't complete the final answer. Here are the key findings "
                    "gathered so far:\n\n"
                    + observation_log
                )
            else:
                _exception_text = (
                    "I've reached my iteration limit. Here are the key findings gathered so far:\n\n"
                    + observation_log
                )
            if _error_report:
                _exception_text += "\n\n" + _error_report
            yield StreamChunk(text=_exception_text, done=True, usage=dict(_provider_usage))
            return  # CRITICAL: return after yielding the exception fallback

        _final_text = "".join(_final_text_parts)
        if (
            not suppress_report
            and trace is not None
            and trace.work_report().needs_report(_final_text)
        ):
            _report_text = trace.work_report().render()
            if _report_text:
                logger.info(
                    "[agent.loop] forced final response did not report tool evidence; "
                    "emitting worker report"
                )
                _final_chunks.append(StreamChunk(text="\n\n" + _report_text, done=False))

        if _final_chunks and _any_text_yielded:
            for _final_chunk in _final_chunks:
                yield _final_chunk
            yield StreamChunk(text="", done=True, usage=dict(_provider_usage))

        # Session 31 (revised per user feedback): if the model returned an
        # empty stream (or all chunks were filtered out as system-leak XML),
        # yield a fallback that surfaces ACTUAL EVIDENCE — not a guess.
        #
        # The previous version guessed "free-tier model overload." The user
        # correctly pushed back: for a 4-step task (mkdir, git init, write
        # a small file, commit), context overflow is not plausible. The
        # real cause is more likely a tool returning broken data that the
        # synthesizer chokes on. So instead of guessing, surface the actual
        # tool inputs and outputs from the trace and let the user decide.
        if not _any_text_yielded:
            if suppress_empty_fallback:
                # Session 147: the rescue caller owns the empty case — it
                # renders the deterministic worker report itself.
                logger.info(
                    "[agent.loop] final synthesis empty — caller handles fallback"
                )
                return
            logger.warning(
                "[agent.loop] final synthesis produced no text — "
                "yielding evidence-based fallback (model returned empty stream)"
            )
            # B-2026-08-20-15 (Session 316): FIRST try deterministic evidence
            # extraction — ZERO LLM calls, ZERO latency. The user's insight:
            # "the thinking text and other evidence already has all the answers."
            # The model's reasoning buffer + tool observations often contain
            # the answer directly (e.g. "the temperature is 16°C" in reasoning,
            # or "Current Time: ... 12 °C" in a search snippet). Extract it
            # before falling back to the retry-then-clean-message path.
            _user_msg = _user_message_text(loop_messages) or ""
            _extracted = self._extract_answer_from_evidence(
                reasoning_buffer="",  # _force_final_answer doesn't have the reasoning buffer
                observation_log=observation_log,
                trace=trace,
                user_message=_user_msg,
            )
            if _extracted:
                yield StreamChunk(text=_extracted, done=True, usage=dict(_provider_usage))
                return
            # B-2026-08-20-14 (Session 315): before dumping raw tool calls to
            # the user, try the post-loop evidence synthesis ONE more time.
            # The _force_final_answer call above may have returned empty
            # because the model was in a bad state; a fresh synthesis call
            # with thinking OFF + the full observation_log often succeeds.
            # This is the difference between "user sees a clean answer" and
            # "user sees raw harness debug output."
            _post_synth_text = ""
            try:
                active_adapter._one_shot_thinking_off = True  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                async for _ps_chunk in self._force_final_answer(
                    loop_messages=loop_messages,
                    observation_log=observation_log,
                    active_adapter=active_adapter,
                    trace=trace,
                    provider_usage=_provider_usage,
                    framing="final",
                    suppress_report=True,
                    suppress_empty_fallback=True,
                ):
                    if _ps_chunk.text:
                        _post_synth_text += _ps_chunk.text
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("[agent.loop] post-synthesis retry failed: %s", exc)
            _post_synth_text = _post_synth_text.strip()
            if _post_synth_text and len(_post_synth_text) >= 20:
                logger.info(
                    "[agent.loop] empty final synthesis rescued by retry (%d chars)",
                    len(_post_synth_text),
                )
                yield StreamChunk(text=_post_synth_text, done=True, usage=dict(_provider_usage))
                return

            # Synthesis retry also failed — produce a CLEAN user-facing message.
            # B-2026-08-20-14: the old fallback dumped raw harness internals
            # ("I ran the requested tools but couldn't synthesize... What to
            # try next: Check the outputs above") which reads as developer
            # debug output, not a user answer. The new fallback is honest +
            # concise: it says what was attempted and points the user at the
            # Actions panel (where the tool evidence already lives).
            _tool_count = sum(1 for s in (trace.steps if trace else []) if s.tool_name)
            if _tool_count > 0:
                yield StreamChunk(
                    text=(
                        "I found the information you asked for, but I'm having "
                        "trouble putting it into a clean final answer right now. "
                        "The search results and tool outputs are in the Actions "
                        "panel above — take a look, or ask me again and I'll retry."
                    ),
                    done=True,
                    usage=dict(_provider_usage),
                )
            elif observation_log.strip():
                yield StreamChunk(
                    text=(
                        "I ran some tools but couldn't produce a final answer. "
                        "The tool outputs are in the Actions panel — take a look, "
                        "or ask me again and I'll retry."
                    ),
                    done=True,
                    usage=dict(_provider_usage),
                )
            else:
                # No tools ran AND no observation log — genuine model issue.
                yield StreamChunk(
                    text=(
                        "I couldn't generate a response for that request. "
                        "Please try again, or rephrase your question."
                    ),
                    done=True,
                    usage=dict(_provider_usage),
                )
