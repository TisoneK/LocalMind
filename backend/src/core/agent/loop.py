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
    DIRECT_RETRIEVAL_INTENTS,
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

# Decomposition: the plan-parsing / MiniMax-DSML interception /
# tool-talk / tool-input helpers below moved to core.agent.text_tools and are
# re-imported here for backward compatibility (tests import them from
# core.agent.loop).
from core.agent.context_breakdown import compute_breakdown, scale_breakdown
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
    ensure_upfront_plan,
    parse_initialization,
)
from core.agent.lookup_plan import LOOKUP_STEPS, lookup_step_for_tool, lookup_step_label
from core.agent.models import AgentStep, AgentTrace, strip_worker_reports, strip_worker_reports_from_history
from core.agent.prompts import build_agent_intent_tail, build_agent_system_prompt, build_planning_prompt
from core.agent.synthesizer import AnswerSynthesizer
from core.agent.task_state import TaskState
from core.agent.text_tools import (
    _MAX_TOOL_TALK_RECOVERIES,
    _MINIMAX_PARTIAL_RE,
    _STANDALONE_PARTIAL_RE,
    _extract_tool_input,
    _has_minimax_tool_call,
    _inspection_can_be_rerun,
    _inspection_fingerprint,
    _is_filler_step,  # noqa: F401 — re-exported for backward compat
    _is_readonly_inspection,
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
from core.agent.turn_outcome import Recovery, TurnOutcome, classify_turn_outcome
from core.context_builder import _build_environment_context
from core.context_compactor import simplify_tool_results
from core.models import AgentAbortedError, Intent, StreamChunk, ToolResult
from core.workspace_state import format_snapshot, mark_turn_start
from core.workspace_state import snapshot as workspace_snapshot
from storage.tool_result_index import INDEX_THRESHOLD_BYTES, get_tool_result_index

logger = logging.getLogger(__name__)


# Lazy wrapper to avoid circular import:
# core.agent.loop → core.trivial_input → core.engine._helpers →
# core.engine.__init__ → core.agent_runtime → core.agent.loop.
# The trivial_input helpers are stable; importing once per process is cheap,
# so we cache the function reference on first call.
_message_implies_tool_action_fn = None


def _message_implies_tool_action(message: str) -> bool:
    """Return True if the user's message implies a tool/file/code action.

    Wraps core.trivial_input.message_implies_tool_action via lazy import.
    Used by the action-narration detector to scope its replan trigger:
    only fire when the user actually expected a tool action.
    """
    global _message_implies_tool_action_fn
    if _message_implies_tool_action_fn is None:
        from core.trivial_input import message_implies_tool_action as _fn
        _message_implies_tool_action_fn = _fn
    return _message_implies_tool_action_fn(message)


# Lazy wrapper for message_is_action_approval (same import-cycle reason as
# _message_implies_tool_action above).
_message_is_action_approval_fn = None


def _message_is_action_approval(message: str) -> bool:
    """Return True if the message approves a previously narrated pending action.

    Wraps core.trivial_input.message_is_action_approval via lazy import.
    Used by the replan gate (B-2026-09-15-8) to escalate on approval tokens
    ("go ahead", "do it") that message_implies_tool_action() alone would
    miss, since an approval doesn't itself mention any tool/file keyword.
    """
    global _message_is_action_approval_fn
    if _message_is_action_approval_fn is None:
        from core.trivial_input import message_is_action_approval as _fn
        _message_is_action_approval_fn = _fn
    return _message_is_action_approval_fn(message)


# Lazy wrapper for should_skip_workspace_state.
# Avoids circular import: pre_init_classifier imports nothing heavy.
_should_skip_workspace_state_fn = None


def _should_skip_workspace_state(message: str) -> bool:
    """Return True if the user's message is 'analyze-only' (do not
    implement yet / first analyze). Wraps the pre_init_classifier helper
    via lazy import + caches the function reference."""
    global _should_skip_workspace_state_fn
    if _should_skip_workspace_state_fn is None:
        from core.agent.pre_init_classifier import should_skip_workspace_state as _fn
        _should_skip_workspace_state_fn = _fn
    return _should_skip_workspace_state_fn(message)


class TerminalProviderError(RuntimeError):
    """A provider error that must terminate the current turn immediately."""

    def __init__(self, raw: str):
        self.raw = str(raw)
        super().__init__(self.raw)


# Tool definitions live in core.agent.tool_schemas (lean schemas) — the
# single source of truth for the native `tools` param and the in-prompt list.


# ── Helpers ────────────────────────────────────────────────────────────────────


def _reasoning_setting(name: str, fallback: float) -> float:
    """Return a user-tunable reasoning timeout from Settings when set.

    The reasoning budgets are surfaced in the Settings
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

    With thinking enabled the model reasons before
    emitting the plan JSON, so the 8s PLAN_TIMEOUT_SECS can fire mid-thought
    (observed live: "initialization timed out after 8s" with GLM-4.5-Flash
    thinking ON). Use the larger REASONING_PLAN_TIMEOUT_SECS budget for
    thinking models.

    On slow local providers: the parent initialization is
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

    A reasoning model with thinking enabled streams
    many thinking tokens before its answer — a fixed 45s cap would truncate
    mid-thought on a slow free tier. Use the larger reasoning budget (tunable
    via Settings UI / env) when the adapter reports thinking_enabled.

    A local Ollama model has the same
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


# Sentences the loop writes into user-role messages itself (nudges, recovery,
# replan prompts). Bracket-tagged blocks ("\n[ACTION NARRATION] ...") are
# recognised by shape instead — see `_is_harness_injected`.
_HARNESS_USER_PREFIXES = (
    "SYNTHESIS REMINDER",
    "You reasoned about this task but returned no answer",
    "You described wanting to use a tool but did not call it",
    "This request requires a tool call, but you did not call one",
    "You returned an empty response. This request requires",
    "You tried to call tool",
    "Your tool call for",
    "CRITICAL: You just output time-sensitive data",
    "[PROGRESS CHECK]",
    "[DIVERGENT STOP]",
    "[Tool result]:",
)


def _is_harness_injected(content: str) -> bool:
    """True for a user-role message the LOOP wrote (a nudge, a recovery, a gate
    or replan block), not something the user typed.

    Every bracket-tagged harness block opens with a newline then ``[TAG]``; a
    real user message that happens to start with ``[URGENT]`` has no leading
    newline, so it is never mistaken for one."""
    if content.startswith("\n["):
        return True
    text = content.lstrip()
    return text.startswith(_HARNESS_USER_PREFIXES)


def _user_message_text(messages: list[dict], limit: Optional[int] = 200) -> str:
    """Return the latest message the USER wrote (for the TaskState objective and
    every consumer that needs "the original request").

    Skips everything the loop itself injected as a user-role message — the
    acceptance-gate/Thinker blocks and also the recovery nudges — so repeated
    recoveries keep the ORIGINAL task framing instead of degrading to the last
    nudge. A live trace showed the Thinker being handed "[ACTION NARRATION] You
    described what you would do…" as the user's request, and then a nudge
    quoting a nudge, so its reasoning and next step were about the recovery
    text and not the task.
    """
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            content = str(msg.get("content", ""))
            if "[ACCEPTANCE GATE]" in content or "[THINKER ANALYSIS]" in content:
                continue
            if _is_harness_injected(content):
                continue
            return content if limit is None else content[:limit]
    return ""


def _content_requested_by_user(content: str, request: str) -> bool:
    """True when `content` is a literal the user themselves asked to be written.

    The file_write guard refuses very short bodies because a model sometimes
    passes a placeholder ("read", "code", "yes") when it means a different tool.
    A body the user spelled out — `containing "eta"` — is the opposite of a
    placeholder, and refusing it makes the model pad it with invented text.
    Only an explicit literal counts: the exact text in quotes, or introduced by
    an unmistakable cue ("containing eta"). A word that merely appears somewhere
    in the sentence ("then read it back") does not.
    """
    literal = (content or "").strip()
    if not literal or not request:
        return False
    esc = re.escape(literal)
    if re.search(rf"[\"'`\u201c\u2018]\s*{esc}\s*[\"'`\u201d\u2019]", request, re.IGNORECASE):
        return True
    cue = r"(?:containing|contains|with (?:the )?(?:text|content|line|word|value)|that says|saying)"
    return bool(re.search(rf"\b{cue}\s+{esc}(?=[\s.,;:!?]|$)", request, re.IGNORECASE))


# Decisions the loop hands the model at each stage. One positive instruction per
# stage, in a fixed structure — the goal, what has been done, what to do next —
# instead of a paragraph of "do NOT" rules appended to the full prompt. Live
# capture: the negative reminder was re-sent on every call and glm still
# narrated; one recovery even named a tool (`file_read`) that does not exist.
_DECISION_CONTINUE = (
    "Decision: compare the tool results above with every part of the goal. If every "
    "part is answered, write the final answer now from those results. If a part is "
    "still missing, your next message is the tool call that gets it."
)
_DECISION_ACT = (
    "Decision: your next message is the tool call itself, with its arguments, and "
    "nothing written before it."
)
_DECISION_ACT_ZERO = (
    "Decision: this goal needs a tool result and none has been produced, so your next "
    "message is a tool call. If the tool you need is on-demand, load it first with "
    "describe_tool."
)
_DECISION_FORCE_TOOL = (
    "Decision: you said you would act, but no tool was called, so nothing has happened "
    "yet. Your next message is the tool call (after a failed fetch, the next source). "
    "If the work is already complete, report its concrete result instead."
)
_DECISION_ANSWER = (
    "Decision: write the final answer now, presenting the actual results above. If one "
    "specific detail is truly missing, call one tool for it; otherwise answer from what "
    "you have."
)


def _stage_card(tag: str, stage: str, decision: str, loop_messages: list, trace) -> str:
    """A structured stage instruction: goal, what ran so far, one decision.

    Keeps the leading ``\n[TAG]`` shape every loop-injected block has, so
    `_is_harness_injected` and the already-nudged checks recognise it."""
    goal = _user_message_text(loop_messages)
    ran = [
        f"{getattr(st, 'tool_name', '')} ({'failed' if getattr(st, 'tool_failed', False) else 'ok'})"
        for st in (getattr(trace, "steps", None) or [])
        if getattr(st, "tool_name", "")
    ]
    lines = [f"\n[{tag}] Stage: {stage}."]
    if goal:
        lines.append(f"Goal: {goal}")
    lines.append("Done so far: " + (", ".join(ran) if ran else "nothing yet") + ".")
    lines.append(decision)
    return "\n".join(lines) + "\n"


def _merge_call_usage(accum: dict[str, int], call: dict) -> None:
    """Fold one LLM call's usage into the turn accumulator.

    Occupancy fields (prompt_tokens/completion_tokens/cached_tokens/...)
    keep LAST-CALL semantics — the context-window meter must show what the
    next call will carry, not a sum across calls. The ``total_*`` fields
    accumulate across every call in the turn, and ``llm_calls`` counts the
    calls that reported usage, so the UI can show real per-turn cost:
    fresh vs cached input and output (P0 Context Engineering Step 1 —
    surface cache data to the UI).
    """
    for key in ("prompt_tokens", "completion_tokens", "cached_tokens", "cache_miss_tokens"):
        value = call.get(key)
        if isinstance(value, (int, float)) and value > 0:
            accum[f"total_{key}"] = int(accum.get(f"total_{key}", 0)) + int(value)
    if call.get("prompt_tokens"):
        accum["llm_calls"] = int(accum.get("llm_calls", 0)) + 1
    accum.update(call)


def _thinker_context_block(analysis) -> str:
    """Render a Thinker analysis into a compact block the loop injects
    so the model's NEXT action is shaped by the reasoning-on-evidence — facts
    to build on, ambiguities to resolve on their default (proceed, do
    not block), and the suggested next step."""
    # The standalone [THINKER ANALYSIS] line keeps this block out of
    # `_user_message_text`: recovery nudges and fallbacks read
    # "the user's ORIGINAL request" from the latest user message — without
    # the marker, a pre-tool Thinker block (appended BEFORE any tool runs)
    # would be misread as the user's request on every later nudge in the
    # turn. Same pattern as the [ACCEPTANCE GATE] skip. The marker must be
    # an exact standalone token ("[THINKER ANALYSIS]") so the skip check
    # matches.
    parts = [
        "[THINKER ANALYSIS]",
        "Your analysis of the evidence so far — reason from this, do not repeat it to the user",
    ]
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


# Junk lines to drop from raw evidence when synthesis fails and we must show the
# tool output directly (rate-limit fallback). These are page chrome — nav items,
# login/subscription prompts, loading placeholders — that made the fallback look
# like a wall of "Subscribe now / LOGOUT / Loading…" instead of the actual
# headlines.
_EVIDENCE_JUNK_RE = re.compile(
    r"^(?:loading[.…\s]*|logout|log\s?in|sign\s?in|sign\s?up|subscribe.*|"
    r"subscribed.*|menu|home|register|follow(?:\s+this\s+topic)?|share|more|"
    r"skip to (?:content|main).*|advertisement|sponsored|you are logged in|"
    r"newsletter|show more.*|see more.*|read more.*|view all.*|privacy policy|"
    r"terms.*|all rights reserved|©.*|cookie.*|account settings|go to my account|"
    r"bookmarks|manage subscriptions?|need help.*|loading)$",
    re.IGNORECASE,
)


def _clean_evidence_text(text: str) -> str:
    """Strip obvious page chrome from a tool observation for the raw-evidence
    fallback, keeping substantive lines (headlines, sentences, the Source line).

    Conservative: keeps anything that isn't clearly nav/subscription junk, so a
    real headline is never dropped. Returns the cleaned text (may be empty).
    """
    kept: list[str] = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        if _EVIDENCE_JUNK_RE.match(s):
            continue
        # Drop bare one-word menu tokens (no space, no sentence punctuation),
        # but keep markdown headers (**Source:** …) and anything with real length.
        if len(s) < 14 and " " not in s and not s.startswith("**") and not s[0].isdigit():
            continue
        kept.append(s)
    return "\n".join(kept).strip()


def _thinker_user_summary(analysis) -> str:
    """Render a Thinker analysis as USER-facing text for the
    degraded-evidence fallback.

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


# ── Concurrent post-tool consults ────────────────────────────────────────────
# A consult that runs while the NEXT model call is already in flight costs the
# turn zero wall-clock (it overlaps model work instead of stacking on it) —
# which is what lets it fire after every tool without re-creating the
# earlier "2-minute turn" serial latency. The data-dependency map:
# the analysis of observation N BLOCKS the next action only when
# the tool FAILED (recovery advice must shape the very next call — that
# consult stays inline/blocking); after a success the model already sees the
# raw observation, so the consult overlaps the next call and its analysis is
# injected at the first iteration head after it completes.
_THINKER_CONSULT_CAP = 5  # per turn — bounds token spend and provider pressure
_THINKER_TOOL_SKIP = frozenset(
    {"todo_write", "describe_tool", "create_plan", "add_subgoal", "update_subgoal"}
)


class _BackgroundConsult:
    """A post-tool Thinker consult running as a background task.

    Prose chunks queue while nobody drains; the loop drains at iteration
    heads and tool boundaries (near-live: the consult usually finishes during
    the model call it overlaps). When the task completes, `analysis` carries
    the parsed ThinkerAnalysis. The task never raises — a failed consult
    simply completes with an empty analysis (same contract as the inline
    consult). A task still running at turn end finishes on its own, bounded
    by the consult timeout; nothing consumes it and it is garbage-collected.
    """

    def __init__(self, evidence, adapter, timeout_secs: float) -> None:
        from core.agent.thinker import Thinker

        self._thinker = Thinker(timeout_secs=timeout_secs)
        self._evidence = evidence
        self._adapter = adapter
        self.queue: asyncio.Queue = asyncio.Queue()
        self.task: Optional[asyncio.Task] = None
        self.iteration = evidence.iteration

    def start(self) -> None:
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            async for chunk in self._thinker.consult(self._evidence, self._adapter):
                await self.queue.put(chunk)
        except Exception as exc:  # never let a consult crash the turn
            logger.warning("[agent.loop] background consult failed: %s", exc)
        finally:
            await self.queue.put(None)  # completion sentinel

    @property
    def analysis(self):
        return self._thinker.last_analysis

    def drain_nowait(self) -> tuple:
        """Pull all queued chunks without blocking.

        Returns (thinking_chunks, finished) — finished is True once the
        consult completed (sentinel seen), in which case `analysis` is final.
        """
        chunks = []
        finished = False
        while True:
            try:
                chunk = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if chunk is None:
                finished = True
                continue
            if isinstance(getattr(chunk, "thinking", None), str) and chunk.thinking:
                chunks.append(chunk)
        return chunks, finished


def _absorb_thinker_analysis(loop_messages, trace, obs, analysis, iteration: int) -> None:
    """Inject a completed Thinker analysis into the model context (shared by
    the blocking and background consult paths). Mirrors the inline-consult contract:
    context block for the model, user-facing summary on the trace for the
    degraded fallback, lifecycle event for observability."""
    if analysis and not analysis.is_empty:
        loop_messages.append({"role": "user", "content": _thinker_context_block(analysis)})
        # Preserve a user-facing rendering on the trace so the
        # degraded-evidence fallback can surface the already-computed synthesis
        # when the final model call fails (e.g. a provider 429).
        trace.thinker_analysis = _thinker_user_summary(analysis)
        if obs:
            obs.emit(
                "agent_thinker_done",
                iteration=iteration,
                next_step=analysis.next_step[:200],
                facts=len(analysis.facts),
                ambiguities=len(analysis.ambiguities),
            )


def _shell_tool_enabled() -> bool:
    """Whether the shell tool is currently enabled.

    Reads the live settings each call — the user can toggle it in the
    Settings UI mid-session and the very next turn must respect it. Defaults
    to enabled (shell on by default) on any config error so the
    tool surface is never silently shrunk by a misread."""
    try:
        from core.config import settings as _s

        return bool(getattr(_s, "localmind_shell_enabled", True))
    except Exception:
        return True


def _filtered_tool_defs(allowed_tools: Optional[frozenset[str]] = None) -> list[dict]:
    """Return TOOL_DEFINITIONS filtered to the allowed tool set.

    Args:
        allowed_tools: optional scoped toolset (from an AgentConfig). When
            provided, only tools whose name is in this set are returned.
            When None (the default), filters to AGENT_ALLOWED_TOOLS (the
            global allowlist) — preserving the earlier global-allowlist behavior.
    """
    allowed_names = allowed_tools if allowed_tools is not None else AGENT_ALLOWED_TOOLS
    return [td for td in TOOL_DEFINITIONS if td["function"]["name"] in allowed_names]


async def _carry_observation(
    full_obs: str,
    tool_name: str,
    session_id: str | None,
    loaded_tools: set[str],
    *,
    fallback: str,
) -> str:
    """The carried form of a tool observation.

    For a LARGE result (> ~5 KB) this stores the FULL output in the hybrid
    Tool-Result Index and returns a bounded head PLUS a one-line pointer
    (``id=<result_id>``) so the model can pull the otherwise-discarded
    remainder back on demand via ``search_tool_results`` — instead of
    re-running the tool or working from the head alone. A large tool result
    is otherwise either truncated (its tail lost) or carried whole (context
    bloat); the pointer path is bounded AND lossless.

    For a result at/under the threshold, returns ``fallback`` unchanged — the
    call site's existing carried form — so slice 2 changes behaviour ONLY for
    large results. Never raises: any indexing failure also returns
    ``fallback`` (correctness over savings). Records ``search_tool_results``
    in ``loaded_tools`` when a pointer is added so its schema loads this run.
    """
    # Never index a retrieval result — search_tool_results output is ALREADY a
    # read-back of stored content; re-indexing it makes the model chase nested
    # pointers into its own searches (seen live: 4 chained searches).
    if tool_name == "search_tool_results":
        return fallback
    if len(full_obs.encode("utf-8")) < INDEX_THRESHOLD_BYTES:
        return fallback
    try:
        result_id, n_chunks = await get_tool_result_index().index_result(
            full_obs, session_id=session_id or "", tool_name=tool_name
        )
    except Exception as exc:  # noqa: BLE001 — never fail a turn on indexing
        logger.debug("[agent.loop] tool-result indexing failed (non-critical): %s", exc)
        return fallback
    if not result_id or n_chunks == 0:
        return fallback
    loaded_tools.add("search_tool_results")
    return (
        f"{_truncate_observation(full_obs)}\n"
        f"…[truncated for context — full {tool_name or 'tool'} output "
        f"({len(full_obs):,} chars) stored — id={result_id}; call "
        f"search_tool_results with this result_id to read the rest]…"
    )


def _note_described_tool(tool_name: str, tool_result, loaded_tools: set[str]) -> None:
    """Record a long-tail tool loaded via describe_tool.

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
    complete, all under the agent's control.
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


# Terse harness-owned step verbs for the synthesized
# user-facing checklist. The Todos panel is a rendered artifact of what the
# agent actually DID — it must never depend on the model choosing to plan,
# narrate, or call todo_write (free-tier models do none of these reliably;
# live-fail evidence showed glm ignoring todo_write entirely).
_SYNTH_TODO_PREFIX = {
    "shell": "Run",
    "file_write": "Write",
    "edit_file": "Edit",
    "file_task": "Read",
    "find_path": "Find",
    "git": "Git",
    "web_search": "Search",
    "web_fetch": "Fetch",
    "code_exec": "Run code",
    "memory_op": "Memory op",
    "process": "Process op",
    "browse": "Browser",
    "diagnostics": "Diagnostics",
    "csv": "Read CSV",
    "json": "Query JSON",
    "sql": "Query DB",
    "calculator": "Calculate",
    "observe": "Observe",
    "sysinfo": "System info",
    "todo_write": "Update todos",
    "delegate": "Delegate",
    # Follow-up: the agent learning a tool's docs is part of "what
    # happened" — surfacing it shows the how/why of the tool choice (the
    # model consulted the schema before using the tool). The AGENT's actual
    # tool knowledge still comes from the returned schema (recorded via
    # _note_described_tool → next call's native tools param), not the panel.
    "describe_tool": "Load tool docs",
}


# ── Diff emission for ANY file-writing path ──────────────────────────────────
# The edit_file path emits `file_diff` from structured hunks in its ToolResult
# metadata (edit_file.py._diff_hunks). file_write and shell writes carry no
# hunks, so the loop computes them itself: snapshot the file's pre-write
# content, then after the successful write produce hunks from the unified diff
# and emit the SAME file_diff obs event the frontend DiffBlock renders — so
# diff mode works even when the file was written by any other means, not just
# edit_file.

_PREWRITE_SNAPSHOTS: dict[str, str] = {}


def _diff_hunks_module(original: str, modified: str, path: str) -> list[dict]:
    """Structural hunks for the frontend DiffBlock — mirrors
    edit_file._diff_hunks (kept independent to avoid a cross-tool import)."""
    import difflib
    import re as _re

    orig_lines = original.splitlines(keepends=True)
    mod_lines = modified.splitlines(keepends=True)
    diff = difflib.unified_diff(
        orig_lines, mod_lines, fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="", n=3
    )
    diff_lines = list(diff)
    if not diff_lines:
        return []
    hunks: list[dict] = []
    current: dict | None = None
    old_line = 0
    new_line = 0
    for line in diff_lines:
        m = _re.match(r"^@@@? -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if m:
            if current:
                hunks.append(current)
            old_start = int(m.group(1))
            old_count = int(m.group(2) or "1")
            new_start = int(m.group(3))
            new_count = int(m.group(4) or "1")
            current = {
                "filePath": path,
                "oldStart": old_start,
                "oldLines": old_count,
                "newStart": new_start,
                "newLines": new_count,
                "lines": [{"type": "hunk_header", "content": line, "oldLine": old_start, "newLine": new_start}],
            }
            old_line = old_start
            new_line = new_start
            continue
        if current is None:
            continue
        if line.startswith("+"):
            current["lines"].append({"type": "added", "content": line[1:], "newLine": new_line})
            new_line += 1
        elif line.startswith("-"):
            current["lines"].append({"type": "removed", "content": line[1:], "oldLine": old_line})
            old_line += 1
        else:
            current["lines"].append(
                {"type": "context", "content": line[1:], "oldLine": old_line, "newLine": new_line}
            )
            old_line += 1
            new_line += 1
    if current:
        hunks.append(current)
    return hunks


def _emit_file_diff(
    obs,
    *,
    path: str,
    content_before: str = "",
    content_after: str = "",
    diff_hunks: list[dict] | None = None,
    diff_language: str = "",
    diff_additions: int = 0,
    diff_deletions: int = 0,
) -> None:
    """Emit the ``file_diff`` obs event once for a file-changing tool.

    Called either with explicit ``diff_hunks`` (edit_file path) or with
    ``content_before`` / ``content_after`` (file_write / shell writes), in
    which case the hunks are computed here. No-ops when there is no diff.
    """
    if obs is None or not path:
        return
    if diff_hunks is None:
        if content_before == content_after:
            return
        diff_hunks = _diff_hunks_module(content_before, content_after, path)
        if not diff_hunks:
            return
        before_lines = content_before.splitlines() or []
        after_lines = content_after.splitlines() or []
        diff_additions = sum(1 for line in after_lines if line not in before_lines)
        diff_deletions = sum(1 for line in before_lines if line not in after_lines)
    obs.emit(
        "file_diff",
        diff_hunks=diff_hunks,
        diff_language=diff_language,
        path=path,
        diff_additions=diff_additions,
        diff_deletions=diff_deletions,
    )


def _record_prewrite_snapshot(path: str) -> None:
    """Store the pre-write content of a file for a later diff emission.

    file_write/scripts overwrite the file IN PLACE inside the tool, so the
    loop cannot read the old content afterward. Snapshot before dispatch
    (from the on-disk file if it exists) and stash it in a module-level
    dict keyed by absolute path; the post-run hook consumes and clears it.
    """
    if not path:
        return
    import os

    abs_path = os.path.abspath(os.path.expanduser(path))
    try:
        if os.path.isfile(abs_path):
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                _PREWRITE_SNAPSHOTS[abs_path] = f.read()
        else:
            _PREWRITE_SNAPSHOTS[abs_path] = ""  # new file → empty before
    except Exception:
        _PREWRITE_SNAPSHOTS[abs_path] = ""


def _consume_prewrite_snapshot(path: str) -> str | None:
    """Return + clear the pre-write snapshot for a path (None when unknown)."""
    import os

    abs_path = os.path.abspath(os.path.expanduser(path))
    return _PREWRITE_SNAPSHOTS.pop(abs_path, None)


# ── Durable write-stats logging ─────────────────────────────────────────────

_WRITE_TOOLS = frozenset({"file_write", "edit_file", "apply_proposed_edit"})


def _log_session_write(
    session_id: str | None,
    *,
    path: str,
    tool: str,
    bytes: int = 0,
    lines: int = 0,
    kind: str = "created",
) -> None:
    """Best-effort write-stats logging — must never break the turn."""
    if not session_id or not path:
        return
    try:
        from core.config import settings
        from storage.db import get_shared_store

        get_shared_store(settings.localmind_db_path).log_write(
            session_id, path=path, tool=tool,
            bytes=bytes, lines=lines, kind=kind,
        )
    except Exception:
        pass


def _write_kind_from_snapshot(pre: str | None) -> str:
    """Return 'created' when the pre-write snapshot is empty (new file),
    'overwritten' otherwise."""
    if pre is None:
        return "created"
    return "created" if pre == "" else "overwritten"


def _synthetic_todo_text(tool_name: str, tool_input: str) -> str:
    """One terse imperative step label per real tool execution.

    Distilled from the tool call itself (name + first line of input), not
    from any model narration — the panel shows what happened, the model's
    thinking stays its own business.
    """
    verb = _SYNTH_TODO_PREFIX.get(tool_name, tool_name.replace("_", " "))
    first_line = (tool_input or "").strip().splitlines()[0].strip() if (tool_input or "").strip() else ""
    arg = first_line[:90]
    label = f"{verb}: {arg}" if arg else verb
    return label[:120]


def _render_todo_state(todo_state: Optional[list[dict]]) -> str:
    """Render the session's persisted todo list as a context block.

    The agent must be aware of its own environment — a follow-up
    like "mark the task as complete" needs to know WHICH todos exist and their
    status. The todos table rows carry id/content/completed/status; render
    them with the same markers the UI uses so the model can act on them.
    Returns "" when there is nothing to show.
    """
    if not todo_state:
        return ""
    lines = ["# Current todos"]
    for t in todo_state:
        text = str(t.get("content") or t.get("text") or "").strip()
        if not text:
            continue
        status = str(t.get("status") or "").lower()
        if status not in ("pending", "in_progress", "completed", "blocked", "done"):
            status = "completed" if t.get("completed") else "pending"
        marker = {
            "completed": "[x]",
            "done": "[x]",
            "in_progress": "[~]",
            "blocked": "[!]",
            "pending": "[ ]",
        }.get(status, "[ ]")
        lines.append(f"- {marker} {text}")
    if len(lines) == 1:
        return ""
    done = sum(
        1 for t in todo_state if t.get("completed") or str(t.get("status") or "").lower() == "done"
    )
    lines.append(
        f"({done}/{len(todo_state)} completed — update a todo by calling "
        "todo_write with the full list.)"
    )
    return "\n".join(lines)


def _render_goal_route(goal_tree: Optional[list[dict]]) -> str:
    """Render the derived goal tree as an ordered route for the model.

    Each top-level goal item plus its sub-goals phrased
    check → prep → write → verify, so the agent follows the fastest+safest
    ordered path (each step feeds the next). Rendered once per turn — the
    same immutable denominator the Todos panel shows. Returns "" when
    nothing was derived.
    """
    if not goal_tree:
        return ""
    # "follow in order" made a regex-derived route a cage — the model obeyed
    # mechanical steps that tool results had already contradicted. The route
    # is a PRIOR, not an order: evidence wins.
    lines = [
        "# Goal route (a default order, each step feeding the next — when tool"
        " results contradict a step, adapt; the goal is the outcome, not the"
        " literal route)"
    ]
    for i, entry in enumerate(goal_tree):
        if not isinstance(entry, dict):
            continue
        goal = str(entry.get("goal") or "").strip()
        if not goal:
            continue
        lines.append(f"Goal {i + 1}: {goal}")
        sub_goals = entry.get("sub_goals") or []
        for j, sub in enumerate(sub_goals):
            sub_text = str(sub).strip()
            if sub_text:
                lines.append(f"   {j + 1}. {sub_text}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def _intent_for_tool(tool_name: str) -> Intent:
    """Map a tool name to its Intent.

    Most tools share their intent value, but a few differ: the tool module is
    ``edit_file`` while its Intent value is ``file_edit``. Seen live:
    `Intent(tool_name)` with "edit_file" raises ValueError, the outer
    dispatch except marks the tool failed, and the failed-branch emit then
    crashed on the unbound `tool_result` — every native edit_file call died.
    """
    _TOOL_NAME_TO_INTENT = {"edit_file": Intent.FILE_EDIT}
    try:
        return _TOOL_NAME_TO_INTENT.get(tool_name) or Intent(tool_name)
    except ValueError:
        # Unknown tool name — fall back to a neutral intent rather than crash.
        return Intent.SHELL


# A shell command can be one to three letters (ls, df, ps, id, cd, w, du).
_SHORT_COMMAND_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{0,2}")


def _input_is_degenerate(tool_name: str, tool_input: str) -> bool:
    """True when a tool call's input is too empty/short to mean anything.

    The guard exists to stop blank or punctuation-only inputs ("?", ".") — a search with no
    query, a path with no name. Under three characters is a fair cut for those, but not for a
    shell command: `ls`, `df` and `ps` are complete commands. Refusing `ls` sent a live turn
    into thirteen replans, because the model can never make `ls` longer.
    """
    if _tool_allows_empty_input(tool_name):
        return False
    stripped = (tool_input or "").strip("?. \t")
    if len(stripped) >= 3:
        return False
    if tool_name == "shell" and _SHORT_COMMAND_RE.fullmatch(stripped):
        return False
    return True


def _tool_allows_empty_input(tool_name: str) -> bool:
    """True if the tool declares empty input as a valid, meaningful call.

    Tools like sysinfo/observe default to a full overview when called with no
    query, so a bare call must NOT be rejected by the degenerate-input guard.
    The tool declares this via ``register_tool(..., input_optional=True)``.
    """
    try:
        from tools import input_is_optional

        return input_is_optional(_intent_for_tool(tool_name))
    except Exception:
        return False


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


# Forced-tool reprompt bound.
# When a tool-required turn's FIRST model call returns empty or text-without-
# tool (gemini-2.5-flash via the OpenAI-compat endpoint, seen live),
# the loop reprompts once with a forced-tool nudge instead of failing the
# turn. The nudge is gated to iteration 0 (the first tool call), so this
# counter is a hard ceiling documenting the bound; if the gate is ever
# relaxed, the counter still caps the retries.
_MAX_TOOL_FORCE_RECOVERIES = 2

# Empty-but-reasoned retry bound (follow-up to the thinking re-enable).
# With thinking re-enabled (z.ai/GLM), a slow free tier sometimes streams a
# long reasoning burst and then returns NO content and NO tool call — the
# model "thought but didn't act" (live user bug: iter-1 ran shell
# Get-ChildItem, iter-2 streamed reasoning then went empty, and the whole
# turn failed with empty_response). The reasoning is real progress; one
# bounded retry with a nudge recovers the turn. Two consecutive empties
# still fail fast — the think-only protection from the original disable
# stays intact (this + the Phase-1 500-chunk reasoning cap bound it).
_MAX_EMPTY_REASONING_RECOVERIES = 2

# Parent turns get a higher recovery cap. Live
# traces on z.ai/glm-4.5-flash showed the model frequently
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


# Same-tool replan bound. After this many CONSECUTIVE
# failures on the SAME tool, the acceptance gate stops replanning and
# reports honestly instead of looping. Root cause, seen live: the
# "find my CV" task replanned to the same failing shell tool 15+
# times (confidence 0.30) for 480s — a tool failing twice in a row
# means the APPROACH is wrong; retrying it a third time is not a plan
# change, it's a loop. A different tool (or a success) resets the
# streak, so legitimate strategy pivots are never blocked.
_SAME_TOOL_REPLAN_CAP = 2

# Total replan cap. The acceptance gate can replan on every
# "done" claim, burning iterations on re-planning instead of executing.
# Weak models hit 8 replan cycles with zero progress. Cap total gate
# replans per run so the model is forced to produce a real answer.
_MAX_TOTAL_GATE_REPLANS = 2

# Repetition nudge bound. A model can spin on a tool that keeps
# SUCCEEDING but isn't advancing (the "current weather Kitengela" transcript: 3
# web_searches all returned results, none useful, then an empty synthesis). The
# failure streak above never catches this because the tool didn't fail. After
# this many CONSECUTIVE calls to the same tool (pass OR fail), the loop nudges
# ONCE to reflect and change approach or answer with what it has — soft, not a
# forced stop, so a task that legitimately needs repeated same-tool calls (e.g.
# reading several files) is not blocked; the iteration/wall-clock caps remain the
# hard bound.
_SAME_TOOL_REPETITION_NUDGE_CAP = 3

# Divergent-tool budget. If the model calls N different tools
# (or same tool with materially different inputs) but never sets criteria and
# never completes a subgoal, the task is a goose chase (e.g. "fix it" with no
# context → random filesystem exploration). Force an honest stop.
_DIVERGENT_TOOL_BUDGET = 5


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


# The iteration cap is a failsafe for a FAILING loop, not a
# penalty on a legitimately long task whose tools keep succeeding. Past the base
# cap the loop continues as long as it keeps making successful progress — so a
# genuinely long, succeeding task is bounded by the WALL-CLOCK cap and by
# failure detection, NOT by an iteration count (the user's rule: cap failure,
# never success). This absolute ceiling is a pure runaway guard for the
# pathological case where progress somehow never stops and wall-clock never
# fires; set high enough that wall-clock always binds first in practice.
_ITER_ABSOLUTE_CEILING = 100

# Max iterations "refunded" for on-demand tool loading.
# describe_tool costs a whole iteration purely to pull ONE
# tool's schema into context before the tool can be called — pure overhead, not
# task progress. We credit one iteration per DISTINCT tool loaded on-demand this
# run so schema-loading does not eat the failsafe budget (a weather lookup that
# had to load `browse` + `web_fetch` docs was burning ~half its iterations on
# describe_tool alone and hitting the cap). Bounded so a describe_tool spam loop
# still terminates; the wall-clock cap and _ITER_ABSOLUTE_CEILING also bind.
_DESCRIBE_TOOL_CREDIT_CAP = 8


def _base_cap_reached(iteration: int, loaded_tool_count: int, effective_max_iter: int) -> bool:
    """True when the failsafe base iteration cap is reached, AFTER refunding the
    iterations spent purely on describe_tool schema-loading.

    ``loaded_tool_count`` is the number of DISTINCT tools loaded on-demand this
    run (``len(loaded_tools)``); each cost an iteration to fetch a schema, which
    is overhead, not task progress. Credit is bounded by _DESCRIBE_TOOL_CREDIT_CAP.
    This only governs the base failsafe — the caller still applies the
    progress-extension and wall-clock checks on top.
    """
    credits = min(max(loaded_tool_count, 0), _DESCRIBE_TOOL_CREDIT_CAP)
    return (iteration - credits) >= effective_max_iter


def _iteration_budget_extendable(trace) -> bool:
    """True if the run may continue past the base iteration cap.

    Extend only when the most recent tool-executing step SUCCEEDED — that is
    "success tool execution" the user asked us not to punish. A failed last
    tool (or no tool ever run) does not earn an extension.
    """
    for step in reversed(getattr(trace, "steps", []) or []):
        if getattr(step, "tool_name", ""):
            return not bool(getattr(step, "tool_failed", False))
    return False


# ── Tool-error recovery (spec §17 self-correction, §28 error handling) ────────
# ROOT FIX: when a tool FAILS, the loop used to surface only
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
# A OneDrive/cloud placeholder that could not be hydrated (file bytes are
# in the cloud, provider not serving them). NOT a plain io_error — every OS-
# level read (zipfile/code_exec/shell included) fails identically, so the
# directive must stop the model from improvising alternate readers.
_ERR_CLOUDFILE = frozenset({"cloud_file_unavailable"})
# A format that has NO parser (OLE2 .pub/.doc, ambiguous zip container). The
# generic "try a different tool/approach" directive is actively harmful here —
# the model obeyed it and burned 10 code_exec calls improvising OLE2 parsing
# on the live trace. The only correct move: stop, ask for a converted file.
_ERR_UNSUPPORTED = frozenset({"unsupported_format"})
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
    if et in _ERR_UNSUPPORTED:
        # Live evidence: under the generic directive a weak model spent
        # 10 code_exec calls trying to hand-parse the OLE2 container. There is
        # NO parser for this format — alternate tools cannot succeed.
        return (
            f"`{tool_name}` does not support this file format and NO other tool can parse it either — "
            "do NOT attempt zipfile/code_exec/shell/manual byte parsing. Stop working on this file and "
            "tell the user the format is unsupported, with the conversion suggestion from the result "
            "above (e.g. re-save as .docx or .pdf). You may still answer from any metadata the result "
            "provided. Never fabricate the file's contents."
        )
    if et in _ERR_CLOUDFILE:
        # The tool already started OneDrive and/or waited for hydration where
        # possible; the message above carries the precise state and remedy.
        return (
            f"`{tool_name}` could not read a cloud (OneDrive) placeholder file whose content is not "
            "downloaded. EVERY read of it fails at the OS level until OneDrive hydrates it — do NOT "
            "retry with zipfile, code_exec, shell, or any other reader. Either re-ask for the same "
            "file shortly (hydration may have finished after the tool's wait), or report the actual "
            "state to the user with the remedy named above. Never fabricate the file's contents."
        )
    if et in _ERR_NORESULT:
        # For web_fetch, the model usually has search results
        # with multiple URLs already. Point it at the next URL instead of a
        # generic "try a different source." The model was stopping after one
        # 404 instead of trying the other results.
        if tool_name == "web_fetch":
            return (
                f"`{tool_name}` did not return a usable result for that URL. "
                "You already have search results with other URLs — try fetching "
                "the NEXT URL from the list. If none of the URLs work, synthesize "
                "the answer from the search snippets you already have, or say so "
                "honestly. Do not invent an answer."
            )
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
    # OS-aware shell recovery hint. When shell fails with
    # "not recognized" or similar, the model almost always used the
    # wrong OS syntax. Give an explicit OS-specific correction.
    # Keep the "honestly" contract — the test
    # test_unknown_errors_still_get_an_actionable_directive requires it for
    # every unknown error type, and the wording protects against false
    # success claims (the model says "done" without verifying).
    if tool_name == "shell":
        import platform as _plat

        _os_name = _plat.system()
        if _os_name == "Windows":
            return (
                f"`shell` command failed ({et or 'error'}) -- you are on WINDOWS. "
                "Common fixes: mkdir -p -> New-Item -ItemType Directory -Force; "
                "ls -> Get-ChildItem; cat -> Get-Content; grep -> Select-String; "
                "find -> Get-ChildItem -Recurse -Filter; rm -> Remove-Item; "
                "cp -> Copy-Item; mv -> Move-Item. "
                "Fix the command and retry with the CORRECT PowerShell syntax. "
                "If you cannot complete this step, report the actual state "
                "honestly -- never claim success you didn't verify."
            )
        return (
            f"`shell` command failed ({et or 'error'}). "
            "Check the error message, fix the command, and retry. "
            "On Unix: use mkdir -p, ls, cat, grep, find. "
            "If the command doesn't exist, try a different approach. "
            "If you cannot complete this step, report the actual state "
            "honestly -- never claim success you didn't verify."
        )
    return (
        f"`{tool_name}` failed ({et or 'error'}). Check the message above, then try a corrected call "
        "or a different tool/approach. If you cannot complete this step, report the actual state "
        "honestly -- never claim success you didn't verify."
    )


def same_tool_repetition_streak(trace) -> tuple[int, str]:
    """Trailing run of consecutive calls to the SAME tool, regardless of
    pass/fail.

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


# Identical-call no-progress bound. The repetition nudge
# above counts same-TOOL repetitions; a weak model can satisfy the letter of the
# nudge by tweaking one character and still spin. This counts the trailing
# run of calls with the SAME tool AND normalized-identical arguments — the
# true "same command over and over" signature the user called out (the CV
# transcript: three malformed system_search queries with materially the same
# input, then a shell fallback that search itself should have handled).
_IDENTICAL_CALL_STOP_CAP = 3
_ARGS_NORMALIZE_MAX = 2000  # bound the signature string


def _normalize_call_signature(tool_name: str, tool_input: str) -> str:
    """A whitespace/case-insensitive signature of one tool call."""
    return re.sub(r"\s+", " ", f"{tool_name}::{tool_input}".strip().lower())[:_ARGS_NORMALIZE_MAX]


def identical_call_streak(trace) -> tuple[int, str]:
    """Trailing run of consecutive same-tool, same-normalized-argument calls.

    Returns (streak, signature). Unlike `same_tool_repetition_streak`, this
    compares WHAT was called, not just which tool — a materially different
    input breaks the streak (that is a strategy change and is allowed).
    """
    steps = getattr(trace, "steps", []) or []
    streak = 0
    last_sig = ""
    for step in reversed(steps):
        tool = getattr(step, "tool_name", "") or ""
        if not tool:
            continue
        sig = _normalize_call_signature(tool, getattr(step, "tool_input", "") or "")
        if not last_sig or sig == last_sig:
            streak += 1
            last_sig = sig
        else:
            break
    return streak, last_sig


def parent_completion_floor_note(trace) -> Optional[str]:
    """The parent's deterministic completion-verification FLOOR:
    the missing VERIFY→DONE segment.

    On the user-facing parent path the turn carries no explicit success-criteria
    contract (the parent runs a generic ANALYZE intent, `GoalInterpreter` is not
    wired, and the post-execution verifier is skipped for non-high-stakes
    intents), so `_acceptance_gate_at_final_answer` used to accept the model's
    "done" on its word alone — even when the parent's last real action FAILED
    (spec §29/§30: "action succeeded" ≠ "objective succeeded").

    This closes that hole. When the parent's LAST executed tool is high-stakes
    (file_write/file_edit/shell/code_exec — file_write also has its own read-back
    grounding), the action is judged failed if EITHER (a) the dispatcher set
    `tool_failed` (tool-level failure: permission, internal error), OR (b) the
    reused post-execution checker `verify_last_tool_succeeded` finds error markers in its
    observation (command-level failure: a nonzero-exit shell command or a
    code_exec exception, which `shell.py` returns as content with success=True —
    so `tool_failed` alone would MISS it). Returns a note on failure so the gate
    rejects "done" and recovers; None otherwise → read/analysis/search turns and
    genuinely successful actions are unchanged.

    Tradeoff (identical to the already-shipped post-execution verifier this reuses): the
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


def _flush_after_live_stream(streamed_text: str, clean_text: str) -> str:
    """Return the not-yet-seen remainder of `clean_text` after live streaming.

    When the head of an iteration's answer was
    streamed live, the post-gate flush must emit only what the user has NOT
    already seen — otherwise a cleaned/intercepted buffer re-yields the whole
    answer (the duplicate-answer class, reintroduced by streaming).

    Prefix-aware: the live path never yields a detected tool-call marker (the
    pending-marker hold flips the turn back to the buffered path first), so
    the cleaned full text should start with the streamed prefix. If it does,
    return the tail; if it doesn't (unexpected guard rewrite), return "" —
    losing a few unseen chars beats duplicating the answer in the bubble.
    """
    shown = (streamed_text or "").strip()
    clean = (clean_text or "").strip()
    if not clean:
        return ""
    if not shown:
        return clean
    # The buffered text is whitespace-stripped by _strip_minimax_tool_calls,
    # so compare against the stripped shown prefix (the head was yielded raw).
    if clean.startswith(shown):
        return clean[len(shown):]
    return ""


# Prose tool-action commitment detector.
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
    "let me check",
    "let me look",
    "let me find",
    "let me search",
    "let me fetch",
    "let me create",
    "let me write",
    "let me get",
    "i'll describe",
    "i'll use",
    "i'll call",
    "i'll run",
    "i'll first",
    "i'll help you",  # live-trace: "I'll help you list... using the shell tool"
    "i'll start by",
    "i'll check",
    "i'll look",
    "i'll create",
    "i'll write",
    "i'll get",
    "i need to describe",
    "i need to use",
    "i need to call",
    "i need to run",
    "i need to check",
    "i need to look",
    "i should describe",
    "i should use",
    "i should call",
    "i should run",
    "i should check",
    "first, i should",
    "first, i'll",
    "first, let me",
    "i'm going to describe",
    "i'm going to use",
    "i'm going to call",
    "i'm going to run",
    "i'm going to check",
    "i'm going to create",
    "i will use the",
    "i will call the",
    "i will run the",
    # Filler-word variants: subject + filler + verb
    # ("I'll probably use shell" — "probably" breaks the substring)
    "i'll probably use",
    "i'll probably call",
    "i'll probably run",
    # Casual/slang variants that weak models produce:
    "lemme use",
    "lemme call",
    "lemme run",
    "lemme check",
    "lemme look",
    "lemme start",
    "lemme get",
    "lemme create",
    "lemme write",
    "gonna use",
    "gonna call",
    "gonna run",
    "gonna check",
    "gonna create",
    "ima use",
    "ima call",
    "ima run",
    "ima check",
    "ima create",
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


# Hedge detection. After tools ran and produced
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

# Follow-through failure phrases — the model says "let me try"
# after a failed tool but doesn't actually call a tool on this iteration.
# These phrases indicate the model INTENDS to continue but is stopping
# prematurely — the acceptance gate should reject and force a real tool call.
_FOLLOW_THROUGH_PHRASES: tuple[str, ...] = (
    "let me try the next",
    "let me try another",
    "let me try a different",
    "i'll try the next",
    "i'll try another",
    "i'll try a different",
    "let me fetch the next",
    "let me fetch another",
    "i'll fetch the next",
    "let me try the other",
    "i'll try the other",
    "let me check the next",
    "let me check another",
    "let me attempt",
    "let me pull up",
    "i'll pull up",
)

# Post-evidence narration detection.
# After tools have run successfully (iteration >= 1), weak models
# sometimes narrate their NEXT intended action instead of synthesizing
# the evidence they already gathered. E.g. "Let me call sysinfo to get
# your system details" after describe_tool already ran.
# Unlike _PROSE_COMMITMENT_PHRASES (which requires a tool-name mention
# and fires when NO tools ran), this fires when tools DID run but the
# model is still narrating instead of presenting results.
_POST_EVIDENCE_NARRATION_PHRASES: tuple[str, ...] = (
    "let me call that",
    "let me call sysinfo",
    "let me run the",
    "let me use the",
    "let me check the",
    "let me get the",
    "let me look at the",
    "let me fetch the",
    "let me search for",
    "i'll call that",
    "i'll call sysinfo",
    "i'll run the",
    "i'll use the",
    "i'll check the",
    "i'll get the",
    "i'll look at the",
    "i'll fetch the",
    "i'll search for",
    "i'm going to call",
    "i'm going to run",
    "i'm going to use",
    "i'm going to check",
    "i'm going to get",
    "now let me call",
    "now let me run",
    "now let me use",
    "now i'll call",
    "now i'll run",
    "now i'll use",
)

# Evidence-sufficient → answer-only call.
# Live baseline (bankofai/qwen3.8-flash, weather turn): after the page fetch
# landed, the loop still spent a full tool-schema-bearing reasoning call
# (38s) deciding to answer, plus two more acquisition iterations the evidence
# already covered. When a fetch tool has put substantive page content in the
# transcript, the NEXT model call is made answer-only: no tool schemas (the
# adapter omits the tools key entirely, so a native tool call is impossible)
# plus a one-shot user directive. The normal buffered final-answer path and
# the acceptance gate run unchanged on that reply; if the model instead
# narrates a further action, the turn-outcome seam maps that to FORCE_TOOL
# (tools_withheld=True) so a genuinely multi-step request gets its tools back.
_EVIDENCE_COMPLETE_TOOLS: frozenset[str] = frozenset(
    {"web_fetch", "web_research", "browse"}
)
# NOTE: the trigger is deliberately TOOL-based, not intent-based — the parent
# path enters the loop with a fixed generic intent, so the declared intent
# carries no signal. What matters is what the trace shows: the last successful
# real tool put substantive page content in the transcript.
# A fetch returning less than this is an error page / redirect stub, not
# evidence — the model should stay free to retry another source.
_EVIDENCE_MIN_CHARS = 200
# Requests that continue past the answer (save/write/export the fetched
# data somewhere) must NOT be short-circuited — the fetch is a mid-task step.
_EVIDENCE_EXCLUDE_ACTION_RE = re.compile(
    r"\b(?:save|write|store|create|update|delete|remove|append|insert|download"
    r"|upload|export|convert|send|email|post|tweet|commit|push)\b",
    re.IGNORECASE,
)
_EVIDENCE_ANSWER_DIRECTIVE = (
    "\n[EVIDENCE SUFFICIENT] The tool results above already contain the "
    "information this request needs. Give your final answer to the user NOW, "
    "using that data — do not announce or plan further tool calls. If a "
    "specific required detail is genuinely missing from the results, say "
    "exactly what is missing instead of guessing.\n"
)

# Pending-ACTION narration. Distinct from
# post-evidence narration (which wants the model to SYNTHESIZE): here the
# model narrates a concrete STATE-CHANGING action it is ABOUT to take
# (delete, create, run, move, install…) but emits no tool call, and the loop
# ends — so the action never happens. The remedy is the OPPOSITE of the
# post-evidence one: FORCE THE TOOL CALL, never "the action phase is over,
# synthesize" (that would suppress the very deletion/creation the user asked
# for). User live-report ("delete huge files"): the agent said "Got it —
# time to act. Let me verify the exact paths and then delete them." and the
# loop ended with nothing deleted.
_ACTION_INTENT_LEADINS: tuple[str, ...] = (
    "let me ", "let me now", "i'll ", "i will ", "i'm going to",
    "i am going to", "i'm about to", "i am about to", "i should now",
    "now i'll", "now i will", "now let me", "time to ", "next, i", "next i'll",
)
# State-changing verbs whose narration WITHOUT a tool call is the bug. Kept to
# unambiguous mutations (destructive / creative / execution); substrings that
# collide with common words ("clear"→"clearly", "apply"→"applying") are
# excluded to avoid false positives. Each is matched only after an intent
# lead-in and an offer-marker exclusion (below), so the co-occurrence is a
# strong signal even as a bare substring.
_STATE_CHANGING_VERBS: tuple[str, ...] = (
    "delete", "remove", "erase", "wipe", "uninstall", "purge", "trash",
    "create", "write ", "overwrite", "save ", "move ", "rename", "install",
    "download", "kill ", "terminate", "execute", "mkdir", "chmod",
    " rm ", "`rm", "rm -",
    # "run" only in unambiguous multiword forms — bare "run" collides with the
    # read-only idiom "run through the results".
    "run the ", "run this ", "run that ", "run a ", "run our ", "run it",
)
# Offers / hedges: the model is DEFERRING to the user, not committing to act.
# "Let me know if you want me to delete them" must NEVER force a delete — that
# would perform a destructive action the user has not confirmed. When any of
# these are present the text is treated as an offer, not a pending action.
_OFFER_MARKERS: tuple[str, ...] = (
    "let me know", "would you like", "if you'd like", "if you would like",
    "if you want", "want me to", "should i ", "shall i ", "do you want",
    "would you prefer", "if you'd prefer", "just say", "let me know if",
)
# Gerund / present-continuous action verbs. Live-test (
# bankofai/deepseek-v4-flash): the model ended its answer with "…which I will
# leave untouched. Deleting the two .bin files now:" and stopped — no rm. That
# phrasing has NO "let me/I'll" lead-in (it's a gerund) so trigger 1 missed it.
# Trigger 2 catches an answer that ENDS by announcing the action as imminent
# ("… now:", "… now.") — output was promised but never produced. Synthesis
# gerunds ("summarizing", "checking") are deliberately excluded so the
# post-evidence path still owns those.
_GERUND_ACTION_VERBS: tuple[str, ...] = (
    "deleting", "removing", "erasing", "wiping", "purging", "trashing",
    "creating", "writing", "overwriting", "moving ", "renaming",
    "installing", "uninstalling", "downloading", "executing",
    "running the", "running this", "running that",
)


def narrates_pending_action(text: str) -> bool:
    """Detect a committed-but-unexecuted state-changing action.

    Two triggers, both on a SHORT final answer (the narration IS the response)
    that is NOT an offer/hedge ("let me know if you want me to…"):
      1. a first-person future-intent lead-in ("let me…", "I'll…", "time to…")
         AND a state-changing verb (delete/create/run/move…);
      2. the answer ENDS by announcing the action as imminent/in-progress —
         a gerund action verb ("deleting…", "removing…") followed by a "now:"
         / "now." / bare-colon tail (output promised, never produced).
    The caller uses this to FORCE a tool call rather than end the turn — the
    opposite remedy from `narrates_after_evidence` (which wants synthesis).
    """
    if not text or len(text.strip()) < 10:
        return False
    lower = text.lower().strip()
    # Long responses likely contain real content (e.g. a report that mentions
    # deleting) — only flag short responses that ARE the narration.
    if len(lower) > 500:
        return False
    # Offers defer to the user — never coerce a destructive action from them.
    if any(marker in lower for marker in _OFFER_MARKERS):
        return False
    # Trigger 1 — explicit future-intent lead-in + a state-changing verb.
    if any(lead in lower for lead in _ACTION_INTENT_LEADINS) and any(
        verb in lower for verb in _STATE_CHANGING_VERBS
    ):
        return True
    # Trigger 2 — the answer ends by announcing an imminent action and stops.
    tail = lower[-120:]
    if any(g in tail for g in _GERUND_ACTION_VERBS) and (
        lower.endswith(":")
        or lower.endswith("now")
        or lower.endswith("now.")
        or lower.endswith("now:")
        or lower.endswith("shortly.")
        or lower.endswith("shortly:")
    ):
        return True
    return False


def narrates_after_evidence(text: str) -> bool:
    """Detect post-evidence narration: model describes next action instead
    of synthesizing gathered evidence.

    Fires when text CONTAINS a narration phrase ("let me call X", "I'll run the...")
    and the text is short enough that the narration IS the response (not a
    long answer with narration buried in it). Only meaningful when tools
    have already run — calling it on iteration 0 would false-positive on
    legitimate first-action text.
    """
    if not text or len(text.strip()) < 10:
        return False
    lower = text.lower().strip()
    # Long responses (>500 chars) likely contain real content alongside
    # a narration fragment — only flag short responses that ARE narration.
    if len(lower) > 500:
        return False
    return any(phrase in lower for phrase in _POST_EVIDENCE_NARRATION_PHRASES)


def answer_fails_follow_through(text: str, had_tool_failure: bool) -> bool:
    """Detect a follow-through failure: the model says 'let me try...' after
    a tool failed, but doesn't actually call a tool on this iteration.

    Seen live: the model fetched AccuWeather, got 403, saw the [RECOVERY]
    directive to 'try the NEXT URL', then produced a short text response:
    'AccuWeather blocked the request. Let me try the next sources.'
    The acceptance gate accepted this as a final answer — ending the turn
    prematurely. The user saw no weather data.

    This detector fires when:
    1. A tool failed this run (had_tool_failure=True)
    2. The model's text contains a follow-through phrase ('let me try')
    3. No tool call was emitted this iteration (checked by the caller)

    Returns True when the gate should REJECT and force a real tool call.
    """
    if not text or not had_tool_failure:
        return False
    lower = text.lower()
    return any(phrase in lower for phrase in _FOLLOW_THROUGH_PHRASES)


# Handoff agent-followthrough-persistence (live, bankofai/glm-5.3-flash,
# "Arsenal livescore and news"): the model answered sub-goal 1 well, then
# ENDED the turn with "I couldn't pull additional news headlines in this
# pass — the Sofascore match page is tracking it live." — conceding an
# explicitly requested part while tools that could get it were available.
# Unlike answer_fails_follow_through (mid-turn retry talk after a tool
# FAILURE), this fires on the FINAL ANSWER confessing an unmet part —
# no tool failure required. Phrase classes:
#   admission — explicit non-acquisition confession ("couldn't pull X")
#   deferral  — pushing the missing part to "the next pass" or onto the user
# Bounded at the call site: one [FORCE-TOOL] nudge per turn (the _already
# tag check) + the iteration budget.
_PUNT_ADMISSION_PHRASES: tuple[str, ...] = (
    "couldn't pull", "could not pull",
    "couldn't get", "could not get",
    "couldn't fetch", "could not fetch",
    "couldn't retrieve", "could not retrieve",
    "couldn't grab", "could not grab",
    "wasn't able to pull", "was not able to pull",
    "wasn't able to get", "was not able to get",
    "wasn't able to fetch", "was not able to fetch",
    "unable to pull", "unable to fetch", "unable to retrieve",
    "unable to get the", "unable to find the",
)

_PUNT_DEFERRAL_PHRASES: tuple[str, ...] = (
    "in this pass",
    "this time around",
    "on a future pass",
    "next pass",
    "look it up yourself",
    "look it up on",
    "check it yourself",
    "check it on",
    "check yourself",
    "track it live",
    "tracking it live",
    "follow it live",
    "following it live",
)


def answer_punts_requested_part(text: str) -> bool:
    """Detect the final-answer PUNT: the answer concedes an explicitly
    requested part is still unmet and defers it (to a later pass or to the
    user themselves) instead of calling a tool that could get it.

    Deliberately does NOT require had_tool_failure — the punt usually
    follows a SUCCESSFUL partial answer (part 1 answered, part 2 conceded).
    """
    if not text:
        return False
    lower = text.lower()
    if any(phrase in lower for phrase in _PUNT_ADMISSION_PHRASES):
        return True
    return any(phrase in lower for phrase in _PUNT_DEFERRAL_PHRASES)


# Same live trace family: the "final answer" can be internal-scaffolding
# prose that leaked into content — e.g. "The synthesis reminder says do NOT
# call another tool and present results now." (handoff-before baseline,
# bankofai/glm-5.3-flash: 77 chars, classified ANSWER, turn over, zero
# sub-goals covered). _filter_system_leaks strips XML-tagged system leaks;
# these are plain-prose scaffold references and get through. They are NEVER
# a legitimate final answer — route to SYNTHESIZE (evidence exists) or
# FORCE_TOOL (nothing ran yet).
_SCAFFOLD_LEAK_PHRASES: tuple[str, ...] = (
    "the synthesis reminder",
    "synthesis reminder says",
    "do not call another tool",
    "[action narration]",
    "[force-tool]",
    "[synthesize]",
    "[recovery]",
    "the system reminder",
    "per the reminder",
)


def answer_is_internal_scaffold(text: str) -> bool:
    """True when the final text is internal-scaffolding prose (references to
    reminders, directives, or injected instruction blocks) rather than an
    answer for the user."""
    if not text:
        return False
    lower = text.lower()
    return any(phrase in lower for phrase in _SCAFFOLD_LEAK_PHRASES)


def _recovery_nudge_tail(loop_messages: list[dict], trace=None) -> str:
    """Task-anchor a recovery nudge: the user's ORIGINAL request, plus an
    advancement hint when tools already ran this turn.

    Seen live in the user's "create a new project" trace:
    the tool-talk / forced-tool / empty-response nudges were task-blind —
    "Call the tool now using the function-calling format", with no reference
    to the actual request. A weak model reads that as "prove you can call a
    tool" and re-runs reconnaissance (ls / Get-ChildItem) instead of taking
    the next real step, burning iterations until the turn ends with zero
    progress. An earlier fix already anchored the empty-reasoning nudge (include
    the original question); this gives the remaining nudges the same anchor
    plus a "do not repeat tools you already ran" advancement hint.
    """
    parts: list[str] = []
    question = _user_message_text(loop_messages)
    if question:
        parts.append(f'The user\'s request was: "{question[:300]}"')
    ran: list[str] = []
    if trace is not None:
        for step in getattr(trace, "steps", []) or []:
            name = getattr(step, "tool_name", "") or ""
            if name and name not in ran:
                ran.append(name)
    if ran:
        parts.append(
            "You have already run these tools this turn: "
            + ", ".join(ran)
            + ". Do NOT repeat them — call the tool that takes the NEXT step "
            "toward the request above (e.g. creating or writing files, not "
            "re-listing directories)."
        )
    return ("\n" + "\n".join(parts)) if parts else ""


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
        # Typed success criteria from an explicit plan
        # (or the model's create_plan). The acceptance gate
        # evaluates these against tool evidence + workspace; "done" requires
        # receipts. None = no contract (legacy model-assertion path).
        success_criteria: Optional[list[str]] = None,
        # Explicit task type from a caller-provided plan.
        # Selects the task-aware context policy (which tool results/history
        # stay verbatim vs. get stubbed). Empty = legacy positional behavior.
        task_type: str = "",
        # The selected BaseAgent's is_done() implementation,
        # called at each iteration head so the loop stops when criteria are
        # VERIFIED (not merely asserted). None for the direct-loop path
        # (no agent instance) — hard caps still bound it.
        is_done_fn=None,
        agent_config=None,
        agent_context: Optional[str] = None,
        allowed_tool_names: Optional[frozenset[str]] = None,
        steering_queue: Optional[asyncio.Queue] = None,
        abort_signal: Optional[asyncio.Event] = None,
        # Wire the dead AgentOrchestrator.replan() into the
        # verify-fail path. Before falling back to _replan_for_gate's
        # self-contained LLM call, notify the orchestrator so its confidence
        # drops, it can re-route to a different agent (e.g. coding→debugger),
        # and the orchestrator_replan_* obs events fire for real (consumed by
        # the frontend). None = legacy behavior (no orchestrator
        # notification; _replan_for_gate runs alone).
        orchestrator=None,
        reformulated_message: str = "",
        # When the caller supplies a harness-derived goal
        # checklist, the criteria must gate at the FINAL-ANSWER point
        # (_acceptance_gate_at_final_answer), never at the iteration head
        # is_done_fn — an early criteria-verified stop would end the turn
        # with a bare "✓ n/n" summary before the model writes its answer.
        skip_head_gate: bool = False,
        # The session's CURRENT persisted todo list (from the
        # todos table, via the SSE bridge). Injected into the turn context so
        # a follow-up like "mark the task as complete" is actionable — the
        # model sees what todos exist and their status instead of hunting in
        # chat history. None = no persisted todos (first turn / no checklist).
        todo_state: Optional[list[dict]] = None,
        # The derived goal tree — each plan step plus its
        # ordered sub-goals (check → prep → write → verify), as plain dicts
        # [{goal, sub_goals}]. When present alongside plan_steps, the loop
        # seeds the sub-goals as nested Todos rows (plan-{i}-sub-{j}) and
        # injects the ordered route into the model context. None = flat plan
        # (legacy behavior). Never mutated — the same fixed denominator as the
        # flat plan items.
        goal_tree: Optional[list[dict]] = None,
        # Session id → the env context injects the session's
        # workspace folder so the agent writes artifacts where they belong.
        session_id: str | None = None,
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
                subclass. When provided, its `max_iterations` and
                `max_wall_clock_secs` override the module-level defaults
                (were dead code before; now honored).
            agent_context: Optional agent-specific context string from the
                selected BaseAgent's build_context() method.
                When the CodingAgent is selected for SHELL/FILE_*/CODE_EXEC
                intents, this contains the coding playbook loaded from
                agents/coding/playbook.md. Passed through to
                build_agent_system_prompt() and injected as the
                `agent_context_section` in the system prompt.
            steering_queue: Optional per-session asyncio.Queue of user
                messages injected mid-turn (the user-steering path). Drained at
                each iteration boundary — the agent sees them as new user
                prompts and continues its turn without being aborted.
            abort_signal: Optional per-session asyncio.Event (the abort path).
                When set (POST /api/chat/{session_id}/abort), the loop raises
                AgentAbortedError at the next check point so the engine can
                yield a clean "stopped" response instead of running to the
                wall-clock/iteration cap after the client closed the stream.
        """
        active_adapter = adapter or self._adapter
        trace = AgentTrace()
        # Seed the acceptance contract from the dispatcher's plan.
        if success_criteria:
            trace.success_criteria = [str(c).strip() for c in success_criteria if str(c).strip()]

        # Resolve the context policy from the DISPATCHER-RESOLVED
        # task_type (parse_task_type_from_plan already applied the
        # primary_domain hint before storing it on the plan). The dispatcher
        # prompt contract says "when unset or ambiguous, omit it — the engine
        # falls back to the legacy positional behavior" — so the loop must
        # not additionally activate a policy via intent/phase fallbacks
        # (a SHELL intent with no task_type must behave exactly
        # as before). Empty → the
        # legacy no-op default policy.
        from core.context_policy import policy_for, resolve_task_type

        # The passed-in task_type is a
        # dispatcher HINT — the agent re-settles it from its actual routing
        # during planning below. Seed with the hint so any read before the
        # settlement point sees the same value the engine used.
        self._settled_task_type = task_type
        self._context_policy = policy_for(task_type)
        # Provider usage is carried through every streamed chunk and tool-call
        # result so the Engine can report real prompt/completion counts.
        _provider_usage: dict[str, int] = {}
        _obs = obs  # may be None — all obs.emit() calls guarded below
        _loop_start_time = time.monotonic()  # wall-clock cap baseline

        # Fresh proposal scope per run — staged edits
        # from a previous run must never leak into this one (same
        # fresh-per-turn pattern as the steering queue / abort event).
        # Lazy import to avoid a circular import at registration time.
        from tools.proposals import reset_proposals
        reset_proposals()
        # Fresh subgoal scratchpad per run — a previous
        # run's subgoals must never leak into this one (same fresh-per-turn
        # pattern as the proposal registry / steering queue / abort).
        from core.subgoal import reset_subgoals
        reset_subgoals()

        # Per-run loaded long-tail tools (via describe_tool).
        # Fresh per run — a previous run's loads never leak into this one
        # (same fresh-per-turn pattern as proposals/subgoals above).
        loaded_tools: set[str] = set()

        # Honor agent_config.max_iterations
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
        # Absolute iteration ceiling. The base cap
        # (_effective_max_iter) is the failsafe for a stuck/failing loop; a run
        # that keeps succeeding continues past it, bounded by the WALL-CLOCK cap
        # and failure detection rather than an iteration count. This ceiling is a
        # fixed runaway guard (never hit in practice — wall-clock binds first).
        _iter_hard_cap = max(_effective_max_iter, _ITER_ABSOLUTE_CEILING)
        if (
            agent_config is not None
            and getattr(agent_config, "max_wall_clock_secs", None)
            and isinstance(agent_config.max_wall_clock_secs, (int, float))
            and agent_config.max_wall_clock_secs >= 1
        ):
            _effective_max_wall = agent_config.max_wall_clock_secs
        elif getattr(active_adapter, "thinking_enabled", False) or getattr(active_adapter, "slow_provider", False):
            # A thinking model on a slow free tier
            # spends 30-170s per call THINKING before acting — the 180s wall
            # clock fits only ~1-2 calls, so a multi-step turn (init + tool +
            # answer) hits the cap before finishing. A slow
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
        # When an agent_config is provided, use its scoped
        # allowed_tools instead of the global AGENT_ALLOWED_TOOLS, then
        # further narrow to the intent's tool scope — a
        # coding agent's 19 tools become ~11 for a SHELL task. Smaller
        # surface = more reliable selection AND fewer tokens per step.
        scoped_tools = agent_config.allowed_tools if agent_config is not None else None
        effective_allowed = allowed_tool_names
        if effective_allowed is not None:
            scoped_tools = frozenset(scoped_tools or AGENT_ALLOWED_TOOLS).intersection(effective_allowed)
        # Per-intent tool scoping — intersect with the intent's
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
        # When the shell tool is DISABLED (Settings UI toggle /
        # LOCALMIND_SHELL_ENABLED=false), remove it from the model's tool
        # surface entirely. The model must not see a callable shell schema —
        # it should route through code_exec (python), file_task, file_write
        # instead. The environment context (context_builder) already tells it
        # shell is off + the fallback guidance; this makes the schema vanish
        # so a disabled shell call is impossible (the shell tool's own guard
        # remains as a second line of defense).
        if scoped_tools is not None and not _shell_tool_enabled():
            scoped_tools = frozenset(scoped_tools - {"shell"})
        filtered_tools = _filtered_tool_defs(scoped_tools)

        # Phase 1 warm-kernel parent turns enter the native loop directly.
        # Resolve this before composing the first tool definitions because the
        # bootstrap surface is intentionally smaller than the normal surface.
        _parent_native_turn = (
            bool(skip_planning) and getattr(agent_config, "name", "") == "parent"
        )

        # The native `tools` param is composed PER CALL —
        # scoped CORE tools + describe_tool + any long-tail tools loaded this
        # run via describe_tool (on-demand full-tool-context). Loaded tools
        # stay loaded for the rest of the run; nothing outside the scope is
        # ever added.
        def _current_tool_defs() -> list[dict]:
            _allowed = scoped_tools if scoped_tools is not None else AGENT_ALLOWED_TOOLS
            # search_tool_results is a meta-retrieval tool
            # (like describe_tool) — permit its composition regardless of the
            # per-intent scope so a stub/pointer is always actionable. It is
            # kept OUT of the in-prompt "Available tools" list (scoped_available
            # is unchanged) and only enters the native param when the loop adds
            # it to loaded_tools — i.e. only on a turn that stored a large result.
            if "search_tool_results" in loaded_tools:
                _allowed = frozenset(_allowed) | {"search_tool_results"}
            # The call-1 tool param ALWAYS includes core tools.
            # Bootstrap used to send ONLY describe_tool, which forced a handshake
            # round-trip — and for a CORE tool it caused an INFINITE describe_tool
            # loop (live: the model wanted web_search, but with only describe_tool
            # in the param it called describe_tool("web_search") 5x → iteration
            # cap). Core tools are now present from turn 1 so the model calls them
            # directly. The lighter bootstrap PROMPT (compact tool summary) is
            # kept via `native_bootstrap`, independent of the tool surface.
            return tool_defs_for_call(
                filtered_tools,
                _allowed,
                loaded_tools,
                bootstrap_only=False,
            )

        # Scope the metadata tool list the same way so the system-prompt
        # "Available tools" section and the planner see the same small
        # surface as the adapter tool defs. Metadata uses intent values;
        # most equal their tool names except FILE_EDIT (tool module
        # "edit_file").
        def _scope_name(t: dict) -> str:
            return "edit_file" if t.get("intent") == "file_edit" else t.get("intent")

        scoped_available = [t for t in available_tools if _scope_name(t) in scoped_tools]

        # Boot-path efficiency: the FULL
        # environment block (platform calls + available_tools + a VectorStore
        # construction) and the workspace snapshot (4-5 git
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
        # `initialization` is only assigned in
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

        # Chat mode — read from settings singleton.
        # "auto" = current behavior (classifier decides).
        # "agent" = skip classifier, force full execute path.
        # "direct" = skip classifier, answer with no tools.
        from core.config import settings as _cfg
        _chat_mode = getattr(_cfg, 'localmind_chat_mode', 'auto')

        if _chat_mode == 'direct' and getattr(agent_config, "name", "") == "parent":
            # Chat mode answers with no tools — but if the
            # request clearly needs an ACTION (run a command, edit files, search
            # the machine), don't silently answer without doing it. Offer to
            # switch to Agent mode (the frontend renders an Accept/Decline gate).
            from core.trivial_input import CAPABILITY_NOTE
            _dm_user_msg = reformulated_message or _user_message_text(messages) or ""
            if _message_implies_tool_action(_dm_user_msg):
                if _obs:
                    _obs.emit("agent_loop_done", intent=intent.value, direct=True)
                yield StreamChunk(
                    text=(
                        "This looks like it needs an action — running a command, "
                        "editing files, or searching your computer — which Chat "
                        "mode can't do. Switch to Agent mode and I'll handle it, "
                        "or stay in Chat and I'll answer as best I can without tools."
                    ),
                    done=False,
                )
                yield StreamChunk(
                    text="", done=True,
                    metadata={"switch_to_agent": {"message": _dm_user_msg}},
                )
                return

            # Direct mode: lightweight chat, no tools, no init, no planning.
            if _obs:
                _obs.emit("agent_loop_done", intent=intent.value, direct=True)
            _direct_msgs = [
                {
                    "role": "system",
                    "content": (
                        CAPABILITY_NOTE
                        + "Answer the user's question directly and concisely."
                    ),
                },
                *messages,
            ]
            try:
                async for _c in active_adapter.chat(
                    _direct_msgs, temperature=0.4, intent="chat"
                ):
                    if getattr(_c, "error", None):
                        break
                    _t = _filter_system_leaks(_c.text or "")
                    if _t:
                        yield StreamChunk(text=_t, done=False)
            except Exception as _exc:
                logger.warning("[agent.loop] direct mode chat failed: %s", _exc)
                yield StreamChunk(
                    text=f"Direct mode error: {_exc}", done=False, error=True
                )
            yield StreamChunk(text="", done=True)
            return

        # Pre-init deterministic guards (4 root-cause clusters):
        #   A. hallucination-class prompts → direct refusal (no tools)
        #   B. analyze-only prompts → skip workspace_state + skip action-narration
        #   C. pressure-induced fabrication → refusal-strengthening reminder
        #   D. impossible constraints → clarify the conflict
        # When the classifier returns a mode, the LLM init call is skipped
        # and the deterministic decision is used directly. This runs BEFORE
        # the _parent_initialization block so it fires even when
        # skip_planning=True (the production code path).
        from core.agent.pre_init_classifier import classify_pre_init

        _user_msg_for_pre = reformulated_message or _user_message_text(messages) or ""
        # Pass the recent prior turns (EXCLUDING the current
        # message, which is the tail of `messages`) so the pressured-reask
        # guard can see that the agent already refused an unanswerable —
        # "just guess" / "check your memory" follow-ups then get the same
        # deterministic refusal instead of a fresh model pass to cave in.
        _pre_history = [
            {"role": m.get("role"), "content": str(m.get("content", ""))}
            for m in messages[-7:-1]
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]
        _pre_init_override = classify_pre_init(_user_msg_for_pre, history=_pre_history)
        logger.info(
            "[agent.loop] pre_init_classifier for %r → mode=%s skip_ws=%s reminder=%s",
            _user_msg_for_pre[:80],
            _pre_init_override.mode,
            _pre_init_override.skip_workspace_state,
            bool(_pre_init_override.extra_system_reminder),
        )

        if _pre_init_override.mode and _chat_mode != 'agent' and getattr(agent_config, "name", "") == "parent":
            # Deterministic decision — skip the LLM init call entirely.
            initialization = InitializationDecision(
                mode=_pre_init_override.mode,
                response=_pre_init_override.response or "",
                acknowledgement=_pre_init_override.acknowledgement or "",
                objective=_pre_init_override.objective or "",
                title=_pre_init_override.title or "",
                clarifying_question=_pre_init_override.clarifying_question or "",
                confidence=1.0,
            )
            if _obs:
                _obs.emit(
                    "agent_initialization_done",
                    mode=initialization.mode,
                    objective=initialization.objective,
                    title=initialization.title,
                    confidence=initialization.confidence,
                    init_prompt_chars=0,
                    pre_init_override=True,
                )
                _obs.emit(
                    "stage_timing",
                    stage="agent_initialize",
                    latency_ms=0,
                    status="pre_init_override",
                )

            # Emit the direct/clarify response + done chunk
            # and return immediately. Do NOT fall through to the execute
            # phase — that would run tools despite the deterministic
            # refusal/clarify decision.
            if initialization.is_direct:
                if _obs:
                    _obs.emit("agent_loop_done", intent=intent.value, direct=True)
                if initialization.acknowledgement:
                    yield StreamChunk(text="", done=False, status=initialization.acknowledgement)
                yield StreamChunk(text=initialization.response, done=False)
                yield StreamChunk(text="", done=True)
                return
            elif initialization.is_clarification:
                if _obs:
                    _obs.emit("agent_loop_done", intent=intent.value, clarified=True)
                if initialization.acknowledgement:
                    yield StreamChunk(text="", done=False, status=initialization.acknowledgement)
                yield StreamChunk(text=initialization.clarifying_question, done=False)
                yield StreamChunk(text="", done=True)
                return

        if _parent_initialization:
            if abort_signal is not None and abort_signal.is_set():
                raise AgentAbortedError("aborted by user before initialization")
            initialization_started = time.monotonic()
            if _obs:
                _obs.emit("agent_initialization_start", intent=intent.value)
            # Consume the streaming initializer so the user sees
            # the model's acknowledgement within the 5s SLO.
            # Each ("ack", str) event becomes a StreamChunk(status=...) — a
            # model-owned transport acknowledgement, never raw chain-of-thought.
            # The ("understanding", str) event is INTERNAL: it feeds the Agent
            # Workspace lifecycle phase (agent_initialization_understanding obs)
            # only — it is NOT streamed into the chat ThinkingBlock (a shallow
            # one-line classify note doesn't belong in the user's chat thread).
            initialization: Optional[InitializationDecision] = None
            streaming_ack_emitted = False

            # The classify/init call gets a COMPACT env (no tool
            # prose, no hardware lines) — ~half the tokens of the full block,
            # which matters most on the slow local models this app targets.
            init_env_context = _build_environment_context(compact=True, session_id=session_id)
            # Inject the refusal-strengthening reminder
            # into the init prompt (prepended to the env_context) when the
            # pre-init classifier detected pressure on a sensitive topic.
            if _pre_init_override.extra_system_reminder:
                init_env_context = (
                    _pre_init_override.extra_system_reminder + "\n\n" + init_env_context
                )
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
                    # Record the init prompt budget so init vs
                    # execution sizes are measured independently.
                    init_prompt_chars=initialization.init_prompt_chars,
                )

            if initialization.is_direct:
                if _obs:
                    _obs.emit("agent_loop_done", intent=intent.value, direct=True)
                if getattr(initialization, "needs_history_answer", False):
                    # When the classify JSON flakes with nothing to
                    # salvage. Do NOT emit the canned context-free fallback —
                    # answer the user's latest message directly from the
                    # conversation history (fixes a follow-up like "why did you
                    # say X?" being met with a generic "tell me more").
                    from core.trivial_input import CAPABILITY_NOTE
                    _hist_msgs = [
                        {
                            "role": "system",
                            "content": (
                                CAPABILITY_NOTE
                                + "Answer the user's "
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
                # Carry the init call's provider usage — on a
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
            # The init returns an ordered step list for a multi-step task
            # (the todo-checklist contract, superseding the earlier plan-only shape).
            # Emit it UP FRONT as the
            # live Todos panel so the user sees the plan the agent will follow;
            # `_advance_plan_on_narration` (below) checks each step off as the
            # agent works, and the agent may reorder/skip as evidence changes.
            _plan_steps = ensure_upfront_plan(list(initialization.plan_steps or []), intent)
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
                # Seed the sub-goal rows
                # (plan-{i}-sub-{j}) right after their parent goal. They
                # are part of the SAME immutable denominator — informational, never advanced by the plan
                # cursor, finalized with the parent at turn end. The UI
                # shows the short title; `content` keeps the full route
                # text (paths/commands) for the agent context.
                for i, tree_entry in enumerate(goal_tree or []):
                    if not isinstance(tree_entry, dict):
                        continue
                    sub_goals = tree_entry.get("sub_goals") or []
                    sub_titles = tree_entry.get("sub_goal_titles") or []
                    for j, sub in enumerate(sub_goals):
                        if not str(sub).strip():
                            continue
                        ttl = ""
                        if isinstance(sub_titles, list) and j < len(sub_titles):
                            _st = sub_titles[j]
                            if isinstance(_st, dict):
                                ttl = str(_st.get("title") or "").strip()
                        _obs.emit(
                            "todo_created",
                            id=f"plan-{i}-sub-{j}",
                            text=ttl or str(sub).strip()[:60],
                            content=str(sub).strip(),
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
            # Check abort before the planning phase — it
            # can take a full model call.
            if abort_signal is not None and abort_signal.is_set():
                raise AgentAbortedError("aborted by user before planning")
            if _obs:
                _obs.emit("agent_planning_start", intent=intent.value)

            # The plan-stream path (non-parent callers) is the ONLY consumer
            # of the full environment block — the parent initialization call
            # uses the compact block instead. Build it here, lazily, so the
            # parent boot path never pays for it.
            # Drop the redundant "## Available Tools" prose (the native
            # tools param + in-prompt list already carry it) — saves ~279
            # tokens on every loop iteration; keeps the OS/shell hints.
            env_context = _build_environment_context(
                include_tool_list=False, session_id=session_id
            )

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
                # The engine's static fallback is suppressed for
                # plan-required intents (the LLM plan owns the todo list), so a
                # planner that produced nothing parseable must be loud — a
                # silent zero-todo turn would look exactly like the old dead UI.
                logger.warning(
                    f"[agent.loop] plan produced 0 steps for intent={intent.value} "
                    f"(plan_len={len(plan_context)}); no todos emitted"
                )
        elif plan_steps:
            # Planning was skipped because the dispatcher's
            # execution_plan is being reused (injected via
            # orchestrator_context). Seed the todo list from those steps so
            # the Todos panel shows the plan and the cursor can advance as
            # the model narrates each step. The UI text is
            # the goal's short title (when the goal tree supplied one);
            # `content` keeps the full checkable goal string.
            _plan_steps = list(plan_steps)
            if _obs:
                for i, step in enumerate(_plan_steps):
                    _ttl = ""
                    if isinstance(goal_tree, list) and i < len(goal_tree):
                        _te = goal_tree[i]
                        if isinstance(_te, dict):
                            _ttl = str(_te.get("title") or "").strip()
                    _obs.emit(
                        "todo_created",
                        id=f"plan-{i}",
                        text=_ttl or str(step)[:120],
                        content=str(step),
                        completed=False,
                    )
                # Seed the sub-goal rows
                # (plan-{i}-sub-{j}) right after their parent goal — the
                # warm-kernel parent path (runtime passes skip_planning +
                # goal_tree) rides this branch. Same fixed denominator as
                # the flat items; informational rows, never advanced by
                # the plan cursor. UI shows the short title; `content`
                # carries the full route text.
                for i, tree_entry in enumerate(goal_tree or []):
                    if not isinstance(tree_entry, dict):
                        continue
                    sub_goals = tree_entry.get("sub_goals") or []
                    sub_titles = tree_entry.get("sub_goal_titles") or []
                    for j, sub in enumerate(sub_goals):
                        if not str(sub).strip():
                            continue
                        ttl = ""
                        if isinstance(sub_titles, list) and j < len(sub_titles):
                            _st = sub_titles[j]
                            if isinstance(_st, dict):
                                ttl = str(_st.get("title") or "").strip()
                        _obs.emit(
                            "todo_created",
                            id=f"plan-{i}-sub-{j}",
                            text=ttl or str(sub).strip()[:60],
                            content=str(sub).strip(),
                            completed=False,
                            status="pending",
                        )
        else:
            _plan_steps = []

        # First-class task state — created once per turn when
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
        # Structured Planner DAG. Parse the free-text
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

        # Settle the task type the
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

        # The plan cursor advances ONLY when the model narrates
        # a step transition (non-empty text before its tool call). Silent tool
        # continuations keep the current todo — so ONE todo owns MANY actions
        # (e.g. todo "Review backend code" → read/grep/read… all under it).
        # The previous per-tool advance split one logical step's actions
        # across consecutive todos. Remaining todos are finalized as done
        # when the turn ends (see the SSE bridge's _finalize_plan_todos).
        def _complete_sub_goals(parent_idx: int) -> None:
            """Complete the sub-goal rows of a finished plan step.

            The sub-goals (plan-{i}-sub-{j}) are guidance
            rows seeded with the parent; when the parent completes, its
            route is done too, so the nested rows flip together. The rows
            stay part of the fixed denominator — no new ids are ever
            created here.
            """
            if not _obs or not goal_tree:
                return
            for tree_entry in goal_tree:
                if not isinstance(tree_entry, dict):
                    continue
                sub_goals = tree_entry.get("sub_goals") or []
                for j in range(len(sub_goals)):
                    _obs.emit(
                        "todo_completed",
                        id=f"plan-{parent_idx}-sub-{j}",
                        completed=True,
                    )

        def _advance_plan_on_narration() -> None:
            nonlocal _plan_step_cursor
            if (
                _plan_steps
                and _plan_step_cursor < len(_plan_steps)
                and (result.raw_content or "").strip()
                and _obs
            ):
                _obs.emit("todo_completed", id=f"plan-{_plan_step_cursor}", completed=True)
                _complete_sub_goals(_plan_step_cursor)
                _plan_step_cursor += 1

        # The 'why' for any tool call under the active plan
        # step. The frontend renders `why: {action.reasoning}` in the
        # Actions/tool-step cards — previously only the model's pre-tool
        # narration (thought=) was attached, so a silent tool run (no
        # narration, the common free-tier case) rendered a blank 'why:'.
        # The plan-step label IS the rationale for the action; attach it.
        def _step_reasoning() -> str:
            if _plan_steps and 0 <= _plan_step_cursor < len(_plan_steps):
                return _plan_steps[_plan_step_cursor]
            return ""

        # Mark the CURRENT plan step's todo complete when the
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
                _complete_sub_goals(_plan_step_cursor)

        # Synthesized harness-owned checklist. The warm-kernel
        # runtime (agent_runtime passes skip_planning=True) gates out ALL plan→
        # todo branches, so the Todos panel was structurally empty and the only
        # remaining path was the model-voluntary todo_write tool. Instead, when
        # no plan-based steps exist, synthesize one todo per REAL tool
        # execution: todo_created on dispatch (pending→in_progress),
        # todo_completed when the tool lands. Model-agnostic, bounded, and
        # skipped for scaffolding calls (describe_tool) and single-step noise.
        # True while the plan is the lookup plan (seeded at the start, or by the first web tool).
        # Its step labels get more specific as the agent commits to a query or a page, so the
        # checks below key off this flag rather than the exact label text.
        _lookup_plan_active = list(_plan_steps) == list(LOOKUP_STEPS)
        _synthetic_todos: list[str] = []
        # Track total gate replans to cap replanning loops
        _gate_replan_count: int = 0
        # Zero-tool force flag. When the acceptance gate
        # detects zero tool calls with criteria unmet (model narrating
        # instead of acting), it sets this so the next iteration forces
        # tool_choice="required". Single-element list for mutability
        # across the gate call boundary.
        _gate_force_tool: list[bool] = [False]
        # Evidence-sufficient answer-only call. Set after a
        # substantive page fetch lands in the transcript; consumed by the
        # NEXT model call, which then runs without tool schemas (answer
        # only) so the model synthesizes instead of re-planning acquisition.
        _evidence_answer_ready: bool = False
        # True for exactly the iteration whose reply came from an
        # answer-only call — read by the acceptance gate to flip the
        # post-evidence-narration recovery from SYNTHESIZE to FORCE_TOOL.
        _answer_only_call_used: bool = False
        _SYNTH_TODO_MAX = 12

        def _synth_begin(tool_name: str, tool_input: str) -> Optional[str]:
            nonlocal _plan_steps, _plan_step_cursor, _lookup_plan_active
            if _lookup_plan_active and _obs:
                _label = lookup_step_label(tool_name, tool_input)
                if _label is not None:
                    _obs.emit(
                        "todo_created",
                        id=f"plan-{_label[0]}",
                        text=_label[1],
                        content=_label[1],
                        completed=False,
                    )
            if _plan_steps or not _obs:
                return None
            if len(_synthetic_todos) >= _SYNTH_TODO_MAX:
                return None
            # todo_write IS the checklist manager — synthesizing
            # a todo for it and then completing it after the tool clears +
            # re-creates the list would upsert an EMPTY leftover row
            # (todo_completed with no text after todo_cleared). Skip it.
            if tool_name == "todo_write":
                return None
            # The first thing the agent actually does is a web lookup and there is no plan
            # yet: show the WHOLE lookup plan now (search -> check sources -> answer) instead
            # of a lone task that ticks itself to 100% while the agent is still working. This
            # keys off real behaviour, so it holds however the request was phrased.
            if not _synthetic_todos and lookup_step_for_tool(tool_name) is not None:
                _first = lookup_step_for_tool(tool_name) or 0
                _plan_steps = list(LOOKUP_STEPS)
                _lookup_plan_active = True
                _plan_step_cursor = _first
                _obs.emit("todo_cleared")
                for _i, _step in enumerate(_plan_steps):
                    _obs.emit("todo_created", id=f"plan-{_i}", text=_step, content=_step, completed=False)
                _first_label = lookup_step_label(tool_name, tool_input)
                if _first_label is not None:
                    _obs.emit(
                        "todo_created",
                        id=f"plan-{_first_label[0]}",
                        text=_first_label[1],
                        content=_first_label[1],
                        completed=False,
                    )
                return f"plan-{_first}"
            todo_id = f"syn-{len(_synthetic_todos)}"
            label = _synthetic_todo_text(tool_name, tool_input)
            _synthetic_todos.append(label)
            _obs.emit(
                "todo_created",
                id=todo_id,
                text=label,
                completed=False,
                status="in_progress",
            )
            return todo_id

        def _synth_end(todo_id: Optional[str], failed: bool) -> None:
            if not todo_id or not _obs or failed:
                return
            _obs.emit("todo_completed", id=todo_id, completed=True)

        # ── Inject agent system prompt (with plan context) ──────────────
        loop_messages = list(messages)

        # Build the parent execution prompt with plan context, memory facts,
        # and any caller-provided routing hint
        # LocalMind Caching (2026-08-31): the STABLE system prompt must be
        # byte-identical across calls so the provider caches it (and cached vs.
        # input tokens count cleanly). Tool descriptions stay here (stable);
        # skills are NOT here (planner-only); and the two dynamic inputs that
        # used to leak in — memory_facts and intent_history — are moved to the
        # trailing turn_context message below. So this prompt = identity +
        # instructions + tool descriptions only.
        system_prompt = build_agent_system_prompt(
            intent=intent,
            available_tools=scoped_available,
            intent_history=None,
            # Context engineering: plan/routing-hint/agent-playbook
            # are PER-TURN or PER-INTENT content — they now ride the trailing
            # turn-context (via build_agent_intent_tail below) instead of the
            # byte-stable system prefix. agent_context is passed through ONLY
            # for the native-bootstrap branch (parent turns), which keeps its
            # own self-contained prompt.
            plan_context=None,
            memory_facts=None,
            orchestrator_context=None,
            agent_context=agent_context if _parent_native_turn else None,
            # Render the in-prompt "Available tools" list from the SAME
            # scoped defs as the native tools param (single source of truth).
            tool_defs=filtered_tools,
            native_bootstrap=_parent_native_turn,
        )
        # Context engineering: the intent-varying sections (skill
        # fragment, expert persona, agent playbook, execution plan, routing
        # hint, current-intent line) used to live INSIDE the system prompt —
        # an intent switch rewrote the cached prefix and every provider cache
        # missed. They now ride the trailing turn-context message, which sits
        # after the stable prefix. Native bootstrap turns keep their compact
        # self-contained prompt (no tail — that surface never had these
        # sections and its leanness is deliberate).
        intent_tail = (
            ""
            if _parent_native_turn
            else build_agent_intent_tail(
                intent=intent,
                plan_context=plan_context or None,
                orchestrator_context=orchestrator_context,
                agent_context=agent_context,
            )
        )

        # Agent-loop token efficiency: the environment
        # (OS/cwd and the CURRENT TIME), the workspace state (git status,
        # diff, last build) and the task-state block are all PER-TURN
        # DYNAMIC. They are deliberately kept OUT of the cacheable system prompt
        # and carried in a SEPARATE trailing turn-context message, so the
        # system+tools prefix stays byte-stable across calls and turns and the
        # provider can cache it (see the cache_control marker in the adapter).
        #
        # ── Workspace state feedback (deferred to the execute path) ────────
        # Mark the turn start (records current HEAD for diff tracking), then
        # take a snapshot of git status/diff/build result. The snapshot is
        # injected into the execute prompt below — this is the "observations
        # flow back into context every turn" loop from the CODING HARNESS
        # diagram, the literal difference between a harness and a bare API.
        #
        # Boot-path efficiency: this block runs 4-5
        # git subprocesses (~100ms on macOS, more on Windows). It is ONLY
        # consumed by the execute prompt — the parent initialization call
        # never sees it. Deferred here (after init/plan decided mode=execute)
        # so DIRECT and CLARIFY turns skip the subprocesses entirely.
        #
        # System-prompt pollution guard: skip the workspace
        # snapshot entirely when the user's message doesn't imply a tool/
        # file/code/git action. Previously the snapshot (Branch: main, dirty
        # working tree, HEAD, untracked files) was injected on EVERY turn,
        # which polluted the prompt for conversational/logic questions —
        # e.g. "We have three branches... How many do we currently have?"
        # made the model waste tokens wondering if "branches" meant git
        # branches, then call describe_tool(shell) to load git, then re-ask.
        # Skipping the subprocesses also saves ~100ms of git subprocess time
        # on turns that don't need them.
        workspace_context = ""
        _user_msg = reformulated_message or _user_message_text(loop_messages) or ""
        # When the pre-init classifier flagged this
        # message as "analyze-only" (do not write code yet / first analyze),
        # skip workspace_state injection. The user wants abstract analysis,
        # not inspection of the on-disk repo.
        if (
            WORKSPACE_STATE_ENABLED
            and _message_implies_tool_action(_user_msg)
            and not _should_skip_workspace_state(_user_msg)
        ):
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
        elif WORKSPACE_STATE_ENABLED and _should_skip_workspace_state(_user_msg):
            logger.debug(
                "[agent_loop] workspace_state skipped — analyze-only prompt "
                "(user said 'do not implement yet' / 'first analyze')",
            )
        else:
            logger.debug(
                "[agent_loop] workspace_state skipped — user message doesn't "
                "imply a tool/file/code/git action (%d chars of context not injected)",
                0,
            )

        # The trailing turn-context is re-sent on EVERY loop iteration —
        # drop the redundant tool-list prose (kept in the native param + the
        # in-prompt list) to save ~279 tokens/iteration. session_id is passed
        # so the Session workspace line lands in the per-iteration context too —
        # free-tier models need the destination
        turn_context_parts = [
            # Context engineering: the intent tail leads the per-iteration context — it
            # varies by intent/turn, so it lives entirely after the stable
            # prefix (byte-identical within a turn, so it caches too).
            *([intent_tail] if intent_tail else []),
            _build_environment_context(include_tool_list=False, session_id=session_id)
        ]
        # LocalMind Caching (2026-08-31): memory + intent history are DYNAMIC
        # (they change per retrieval/turn), so they live here in the trailing
        # turn-context — NOT in the cacheable system prefix above.
        if memory_facts:
            turn_context_parts.append(
                "What you know about this user:\n"
                + "\n".join(f"- {f}" for f in memory_facts)
            )
        if intent_history:
            turn_context_parts.append("Recent intent history: " + ", ".join(intent_history))
        if workspace_context:
            turn_context_parts.append(workspace_context)
        # Inject the session's CURRENT todo list (persisted from
        # previous turns). This is the "agent is aware of its own environment"
        # fix — a follow-up like "mark the task as complete" must see what
        # todos exist and their status instead of looking for them in chat.
        _todo_state_prompt = _render_todo_state(todo_state)
        if _todo_state_prompt:
            turn_context_parts.append(_todo_state_prompt)
        # The derived goal route — the ordered sub-goal path
        # (check → prep → write → verify) per top-level goal, so the model
        # follows the fastest+safest sequence rather than guessing.
        _goal_route_prompt = _render_goal_route(goal_tree)
        if _goal_route_prompt:
            turn_context_parts.append(_goal_route_prompt)
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

        # Context-usage breakdown: the boundary between what the turn INHERITED
        # (history + its own user message) and what the loop APPENDS from here
        # on (thinker block, observation log, nudges, tool calls/results).
        # Captured now, before any per-turn injection lands in loop_messages.
        _turn_msg_boundary = len(loop_messages)

        # ── Seed observation log with initial tool result ──────────────
        observation_log = ""
        last_tool_failed = False
        consecutive_failures = 0
        fabrication_risk = 0  # Incremented on tool errors and fabrication-prone patterns
        # The Thinker consults on real evidence ONLY — the first consult now
        # fires at the moment the model requests its FIRST tool call (see the
        # MultiToolCallResult/ToolCallResult dispatch sites below), not before
        # it. A turn that never calls a tool (the model answers directly,
        # `_force_tool_choice` never forces native parent turns — see
        # `_parent_native_turn` above) never launches a consult at all: zero
        # extra LLM calls for a trivial turn, decided purely by the model's
        # own free choice, not a pre-classification step. Every consult after
        # the first (this one included) runs CONCURRENTLY with the next
        # model call — at most one in flight, capped per turn; each completed
        # analysis is injected into loop_messages at the next iteration head
        # (before the model call), so the reasoning shapes the next action
        # without ever having blocked one. A tool FAILURE keeps the blocking
        # path (recovery advice must shape the very next call) — see the
        # post-tool consult site below.
        _consult_inflight = None
        _consults_fired = 0

        def _maybe_launch_first_tool_consult(tool_names) -> None:
            """Launch a background Thinker consult the moment the model
            requests its FIRST tool call this turn (`trace.steps` still
            empty) — never before. Called from the MultiToolCallResult and
            ToolCallResult dispatch sites below. Mirrors the post-tool
            background-consult contract (`_BackgroundConsult` + the generic
            drain at the next iteration head) so this costs zero wall-clock:
            it overlaps the tool's own dispatch/execution instead of adding a
            separate serial round-trip before any work starts. Same gate the
            old pre-tool block used (open-ended intents only — direct-
            retrieval intents skip it, the action is already obvious), plus
            the throttling the post-tool site already applies.
            """
            nonlocal _consult_inflight, _consults_fired
            if not (
                not trace.steps
                and not initial_tool_result
                and not _pre_init_override.mode
                and intent in AGENT_INTENTS
                and intent not in DIRECT_RETRIEVAL_INTENTS
                and getattr(active_adapter, "thinking_enabled", False)
                and _consults_fired < _THINKER_CONSULT_CAP
                and any(name not in _THINKER_TOOL_SKIP for name in tool_names)
            ):
                return
            try:
                from core.agent.thinker import Evidence

                _pre_hist_text = "\n".join(
                    f"{h.get('role', '?')}: {str(h.get('content', ''))[:200]}"
                    for h in strip_worker_reports_from_history(messages[-4:])
                    if h.get("role") != "system" and h.get("content")
                )
                _ev = Evidence(
                    objective=(initialization.objective if initialization else ""),
                    user_message=_user_msg,
                    conversation_history=_pre_hist_text,
                    observations="",
                    iteration=0,
                )
                if _ev.has_evidence:
                    if _obs:
                        _obs.emit("agent_thinker_start", iteration=0)
                    _consult_timeout = _reasoning_setting(
                        "localmind_reasoning_plan_timeout_secs", REASONING_PLAN_TIMEOUT_SECS
                    )
                    _consults_fired += 1
                    _consult_inflight = _BackgroundConsult(_ev, active_adapter, _consult_timeout)
                    _consult_inflight.start()
            except Exception as _thx:  # never let the Thinker break a turn
                logger.warning("[agent.loop] first-tool Thinker consult skipped: %s", _thx)

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
            # Index a large pre-dispatched result and carry a
            # bounded head + pointer (retrievable via search_tool_results);
            # small results keep the existing bounded head.
            _carried_initial = await _carry_observation(
                safe_initial, initial_tool_result.source or "tool", session_id, loaded_tools,
                fallback=_truncate_observation(safe_initial),
            )
            loop_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": _carried_initial,
                }
            )
            # The SINGLE_TOOL fast path (dir
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

        # Repeated-listings flaw guard: a STRUCTURAL cache for
        # read-only inspection calls. Keyed by _inspection_fingerprint —
        # which strips cosmetic variation (quoting, column order, table
        # formats, object wrappers) — so "the same listing asked a different
        # way" maps onto the earlier result instead of burning a model call.
        # Any tool call that may have MUTATED state invalidates this cache
        # (see _invalidates_inspection_cache below), so a listing that
        # follows a write/edit/exec still runs fresh.
        _inspection_cache: dict[str, str] = {}
        _inspection_seen: set[str] = set()

        def _maybe_invalidate_inspection_cache(tool_name: str, tool_input: str) -> None:
            """Drop the structural inspection cache after a possibly-mutating call.

            Read-only inspections (listing, browsing, file reads, git read
            ops) keep it; anything that could change state on disk or in the
            environment — writes, edits, code exec, mutating shell commands,
            git write ops — must not reuse stale inspection output, so the
            cache is cleared for the rest of the turn.
            """
            nonlocal _inspection_cache, _inspection_seen
            always_mutates = tool_name in (
                "file_write", "edit_file", "propose_edit_file",
                "best_of_n_edit", "code_exec", "terminal",
            )
            maybe_mutates = tool_name in ("shell", "git") and not _is_readonly_inspection(
                tool_name, tool_input
            )
            if (always_mutates or maybe_mutates) and (_inspection_cache or _inspection_seen):
                logger.info(
                    "[agent.loop] mutating call %s — clearing inspection cache (%d keys)",
                    tool_name, len(_inspection_cache),
                )
                _inspection_cache.clear()
                _inspection_seen.clear()

        # ── Collected tool results for post-loop synthesis ──────────────
        # Track all ToolResults from this turn so the AnswerSynthesizer
        # can extract and synthesize them into a user-facing answer after
        # the loop completes. Without this, raw search links and HTML
        # content leak directly to the user.
        collected_results: list[ToolResult] = []

        # ── Name-level dedup for file_write ─────────────────────────────────
        # Track which file paths have been written to in this turn. If the
        # agent calls file_write on the same path twice (even with different
        # content), the second call is almost always redundant or a mistake.
        # The fingerprint-level dedup above only catches identical inputs,
        # but the model may produce slightly different content strings on
        # retry, defeating the exact-match dedup.
        _file_write_paths: set[str] = set()

        # ── Inline-delegation scope ──────────────────────────────────────
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
        # Use _effective_max_iter / _effective_max_wall
        # (agent_config overrides when provided; module-level defaults
        # otherwise) instead of the raw MAX_ITERATIONS / MAX_WALL_CLOCK_SECS.
        _repetition_nudged = False  # fire the progress nudge once per turn
        _divergent_stop = False  # divergent tool budget broke the loop
        for iteration in range(_iter_hard_cap):
            trace.iterations_used = iteration + 1

            # Past the BASE cap, only continue while the run is
            # still making successful progress. The iteration cap is a failsafe
            # for a failing/stuck loop, not a penalty on a legitimately long task
            # whose tools keep succeeding. A non-progressing run stops here at the
            # base cap (unchanged behavior); a succeeding run earns up to
            # _PROGRESS_EXTENSION_ITERS more, still bounded by the wall-clock cap.
            # The failsafe cap measures ACTION iterations —
            # iterations spent purely on describe_tool schema-loading are
            # refunded (see _base_cap_reached), so a task that must load a couple
            # of long-tail tools still gets its full budget instead of hitting
            # the cap on overhead.
            if _base_cap_reached(
                iteration, len(loaded_tools), _effective_max_iter
            ) and not _iteration_budget_extendable(trace):
                # Record WHICH budget broke the loop. The
                # post-loop classification used to report every break as
                # "iteration_limit" — including wall-clock breaks — which
                # misdiagnosed the failure: the remedy for a step-count cap
                # differs from a time cap.
                trace.limit_kind = "iteration_cap"
                logger.info(
                    "[agent_loop] base iteration cap %d reached and not progressing "
                    "(iter %d, describe_tool credits %d) — stopping",
                    _effective_max_iter,
                    iteration + 1,
                    min(len(loaded_tools), _DESCRIBE_TOOL_CREDIT_CAP),
                )
                break

            # Hard wall-clock cap. The loop terminates on "done,
            # blocked, OR limit" — this is the time-based limit. Prevents
            # a small model from spinning forever on a task it can't solve.
            _elapsed = time.monotonic() - _loop_start_time
            if _elapsed > _effective_max_wall:
                # Distinguish the time cap from the step cap.
                trace.limit_kind = "wall_clock"
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

            # ── Acceptance gate (iteration head) ─────────────────────────
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
                iter_max=_iter_hard_cap,
                wall_used=_elapsed,
                wall_max=_effective_max_wall,
            )
            _subgoals = _sub_registry.all()
            task_state.completed = [s.description for s in _subgoals if s.status == "completed"]
            task_state.pending = [s.description for s in _subgoals if s.status in ("pending", "in_progress")]
            task_state.failed = [(s.description, s.notes or "") for s in _subgoals if s.status == "blocked"]

            # Progress nudge. If the model has called the SAME
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

            # Identical-call hard stop. Same tool + the same
            # (normalized) arguments N+ times is the literal "running the
            # same command over and over" loop: the nudge above is soft and
            # fires on the tool name alone, so a model that tweaks one
            # character and re-runs still burns the whole budget. Three
            # identical calls is a no-progress loop regardless of outcome —
            # stop honestly and answer from what was gathered.
            _ident_streak, _ident_sig = identical_call_streak(trace)
            if _ident_streak >= _IDENTICAL_CALL_STOP_CAP:
                trace.limit_kind = "repetition"
                logger.warning(
                    "[agent_loop] identical-call stop: %s x%d — stopping as no-progress loop",
                    _ident_sig[:120],
                    _ident_streak,
                )
                if _obs:
                    _obs.emit(
                        "agent_loop_identical_call_stop",
                        signature=_ident_sig[:200],
                        streak=_ident_streak,
                        iteration=iteration + 1,
                    )
                break

            # Divergent-tool budget. If the model has called many
            # real tools (excluding todo metadata ops) but never set criteria,
            # the task is a goose chase (e.g. "fix it" with no context).
            # Force an honest stop.
            _real_tool_calls = [
                s for s in (trace.steps or [])
                if getattr(s, "tool_name", "") and getattr(s, "tool_name", "") not in ("todo_write",)
            ]
            _has_criteria = bool(getattr(task_state, "criteria", None))
            if (
                len(_real_tool_calls) >= _DIVERGENT_TOOL_BUDGET
                and not _has_criteria
            ):
                logger.info(
                    "[agent.loop] divergent-tool budget hit: %d real tool calls, "
                    "no criteria, no real completed subgoals — forcing honest stop",
                    len(_real_tool_calls),
                )
                loop_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "[DIVERGENT STOP] You have made many tool calls but have not "
                            "defined what success looks like or completed any concrete step. "
                            "STOP exploring and give the best answer you can from what you "
                            "have gathered. If the user's request was unclear, say so and ask "
                            "them what they meant."
                        ),
                    }
                )
                if _obs:
                    _obs.emit(
                        "agent_loop_divergent_stop",
                        tool_calls=len(_real_tool_calls),
                        iteration=iteration + 1,
                    )
                # Break the loop — the nudge is advisory and strong models
                # ignore it. Fall through to synthesis with what we have.
                logger.info("[agent.loop] divergent stop: breaking loop")
                _divergent_stop = True
                break

            # Structured Planner DAG. Advance the plan
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

            if is_done_fn is not None and not skip_head_gate:
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
                        # A gate that passes without an explicit
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

            # Steering without aborting. Drain any
            # user messages queued via POST /api/chat/{session_id}/steer
            # at the NEXT iteration boundary — never mid-tool. The agent
            # sees the steering message as a new user prompt and continues
            # its turn instead of being aborted and re-run. Messages are
            # tagged "steering": True so compaction passes can identify
            # them; they are user-role, so the compactor
            # (simplify_tool_results — tool-role only) never stubs them.
            if steering_queue is not None:
                while not steering_queue.empty():
                    _steer_msg = await steering_queue.get()
                    _steer_msg.setdefault("steering", True)
                    loop_messages.append(_steer_msg)

            # Abort check at each iteration boundary.
            # Set via POST /api/chat/{session_id}/abort (or client
            # disconnect) — the loop raises and the engine yields a clean
            # "stopped" response. Granularity is one step boundary, matching
            # the steering design: a mid-tool abort lands here after the
            # current tool finishes.
            if abort_signal is not None and abort_signal.is_set():
                raise AgentAbortedError("aborted by user")

            # ── Drain a completed background consult ──────────────────────
            # The consult for a previous observation overlapped the last
            # model call; its analysis is injected HERE — before the copy
            # that feeds this iteration's model call — so it shapes the next
            # action without ever having blocked one. Prose queued during
            # the model call flushes to the ThinkingBlock now (near-live).
            if _consult_inflight is not None:
                _drain_chunks, _drain_done = _consult_inflight.drain_nowait()
                for _tc in _drain_chunks:
                    yield StreamChunk(text="", thinking=_filter_system_leaks(_tc.thinking), done=False)
                if _drain_done:
                    _absorb_thinker_analysis(
                        loop_messages, trace, _obs, _consult_inflight.analysis, _consult_inflight.iteration
                    )
                    _consult_inflight = None

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
                context_content = f"{trimmed_log}{failure_hint}\nIteration {iteration + 1}/{_iter_hard_cap}. "
                # Refresh the task-state progress/budget lines
                # into the per-iteration context (criteria stay in the
                # system prompt; only progress changes per iteration).
                if task_state_refresh:
                    context_content += task_state_refresh
                iteration_messages.append({"role": "user", "content": context_content})

            # Synthesis nudge. When tools have succeeded in
            # earlier iterations but the model is past iteration 1, it should
            # SYNTHESIZE from the evidence already gathered, not plan more
            # actions. Without this nudge, weak models keep narrating
            # ("Let me run...") instead of answering, causing the
            # action-narration gate to fire repeatedly. Only inject when
            # real tool evidence exists (successful steps in the trace).
            _has_successful_tools = any(
                s.tool_name and not s.tool_failed
                for s in trace.steps
            )
            _no_pending_tool = not any(
                s.tool_name and s.tool_failed
                for s in trace.steps
            )
            if (
                _has_successful_tools
                and _no_pending_tool
                and iteration >= 1
                and not observation_log  # no failed tools to retry
            ):
                _synth_hint = _stage_card(
                    "STAGE: CONTINUE", "continue", _DECISION_CONTINUE, loop_messages, trace
                )
                iteration_messages.append({"role": "user", "content": _synth_hint})

            # Deterministic tool-result simplification.
            # When the accumulated conversation has more than the newest few
            # tool results, stub the older oversized ones (head + omission
            # marker + tail) to keep the window in budget WITHOUT an LLM
            # call. Preserves tool_call_id (protocol validity) and never
            # touches the newest results the model still needs. Idempotent.
            # Deliberately unconditional — the keep_last window preserves
            # what the model still needs; old results it already acted on
            # are exactly what frees the most context (see
            # context_compactor.simplify_tool_results docstring).
            # Deterministic tool-result simplification.
            iteration_messages = simplify_tool_results(
                iteration_messages,
                policy=getattr(self, "_context_policy", None),
            )

            # Surface the subgoal scratchpad directly in
            # the system message each iteration — tool results alone aren't
            # reliable working memory (the compactor stubs older tool
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
            # Wrap with a hard timeout to prevent "thinking
            # forever" when the model hangs. Uses PER_CALL_TIMEOUT_SECS
            # (45s) — SHORTER than the adapter's 120s HTTP timeout so the
            # user sees a result before the adapter itself times out.
            # The wall-clock cap is checked between iterations.
            # A reasoning model with thinking enabled
            # (z.ai/GLM) legitimately streams many thinking tokens before
            # its answer — a fixed 45s cap would truncate mid-thought on a
            # slow free tier. When the adapter reports thinking_enabled,
            # use the larger reasoning budget instead (Settings UI / env).
            _per_call_timeout = _per_call_timeout_for(active_adapter)
            t_llm = time.monotonic()
            # On the FIRST
            # iteration of a tool-required intent (no tool has run yet),
            # force the model to emit a tool call. Some providers
            # (gemini-2.5-flash via the OpenAI-compat endpoint) otherwise
            # return an empty or text-only response on the first tool call,
            # which failed the turn with the "empty response" message
            # (seen live). tool_choice="required" is applied ONLY
            # here — later iterations keep the default so the model can
            # synthesize its final answer without further tool calls.
            _force_tool_choice = (
                (iteration == 0
                 and intent in AGENT_INTENTS
                 and not trace.steps
                 and bool(filtered_tools)
                 and not _parent_native_turn)
                or _gate_force_tool[0]
            )
            # Consume the gate force flag after applying it — only
            # force ONE iteration, then let the model respond normally.
            if _gate_force_tool[0]:
                _gate_force_tool[0] = False
            # Evidence-sufficient → answer-only call. When the
            # previous iteration's tool already put the requested page
            # content in the transcript, this call runs WITHOUT tool schemas
            # (the adapter omits the tools key, so a native tool call is
            # impossible) plus a one-shot answer directive — the model
            # synthesizes instead of re-reasoning over the tool roster. The
            # normal buffered final-answer path + acceptance gate apply to
            # the reply; if it narrates a further action, the gate maps
            # that to FORCE_TOOL (tools restored) via tools_withheld.
            _answer_only_call_used = False
            _iter_tools = _current_tool_defs()
            if (
                _evidence_answer_ready
                and not _force_tool_choice
                and not last_tool_failed
                and iteration >= 1
            ):
                _evidence_answer_ready = False
                _answer_only_call_used = True
                _iter_tools = []
                iteration_messages.append(
                    {"role": "user", "content": _EVIDENCE_ANSWER_DIRECTIVE}
                )
                if _obs:
                    _obs.emit(
                        "agent_loop_evidence_answer_call",
                        intent=intent.value,
                        iteration=iteration + 1,
                    )
                logger.info(
                    "[agent.loop] iter=%d evidence-sufficient — answer-only call "
                    "(tool schemas withheld)",
                    iteration + 1,
                )
            # Context-usage breakdown estimate for THIS call's exact payload,
            # taken after every per-iteration mutation (observation log,
            # nudges, tool-result simplification, scratchpad, answer-only
            # schema withholding) and scaled to the provider's real
            # prompt_tokens once the call reports usage. Observability only —
            # a failure here must never affect the call itself.
            try:
                _breakdown_est = compute_breakdown(
                    iteration_messages, _iter_tools, _turn_msg_boundary
                )
            except Exception:
                logger.debug("[agent.loop] context breakdown failed", exc_info=True)
                _breakdown_est = None
            try:
                result = await asyncio.wait_for(
                    active_adapter.chat_with_tools(
                        messages=iteration_messages,
                        tools=_iter_tools,
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
                _merge_call_usage(_provider_usage, result_usage)
                if _breakdown_est is not None:
                    _provider_usage["context_breakdown"] = scale_breakdown(
                        _breakdown_est,
                        int(result_usage.get("prompt_tokens") or 0),
                    )
                # Prompt-cache visibility: what fraction of input was a cheap
                # cache HIT (the byte-stable system prefix). Only logs when the
                # provider reports it (DeepSeek/OpenAI/Anthropic-family).
                _cached = result_usage.get("cached_tokens")
                _pt = result_usage.get("prompt_tokens")
                if _cached is not None and _pt:
                    logger.info(
                        "[agent.loop] iter=%d cache: %d/%d prompt tokens hit (%.0f%%)",
                        iteration + 1, _cached, _pt, 100.0 * _cached / max(_pt, 1),
                    )
                yield StreamChunk(text="", done=False, usage=dict(_provider_usage))
            # When the model returns multiple tool calls in a single response,
            # dispatch independent ones concurrently via asyncio.gather().
            # This is safe because independent tool calls (e.g., file_task + sysinfo)
            # have no side-effect dependencies between them.
            if isinstance(result, MultiToolCallResult):
                # Batches can mix a fetch with follow-on work —
                # the answer-only optimization applies only to the clean
                # single-tool fetch shape, so reset the flag here.
                _evidence_answer_ready = False
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
                    if _input_is_degenerate(_name, _inp):
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

                _maybe_launch_first_tool_consult([c.tool_name for c, _ in valid_calls])

                # Dispatch all valid calls concurrently
                async def _dispatch_single(tc_name: str, tc_input: str, tc_args: dict):
                    """Dispatch a single tool and return (name, observation, failed, latency_ms, provider)."""
                    t_start = time.monotonic()
                    tc_result = None
                    try:
                        tc_intent = Intent(tc_name)
                        # Snapshot pre-write content so a diff
                        # can be emitted after a file_write in a batch.
                        if tc_name == "file_write":
                            _record_prewrite_snapshot(tc_args.get("path", ""))
                        tc_result, tc_failed, _ = await dispatch_with_retry(
                            tc_intent,
                            tc_input,
                            obs=_obs,  # ADR 18 P3: delegation streams into the UI
                            allowed_tool_names=effective_allowed,
                        )
                        # A describe_tool call in a batch loads
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
                        # Log write stat for edit_file in batch
                        if tc_result and tc_result.success and tc_result.metadata and tc_result.source == "edit_file":
                            _log_session_write(
                                session_id,
                                path=tc_result.metadata.get("path", ""),
                                tool="edit_file",
                                bytes=0,
                                lines=tc_result.metadata.get("modified_lines", 0),
                                kind="overwritten",
                            )
                        # Compute + emit a diff for file_write
                        # in a batch (same shape as the single-tool path).
                        if tc_name == "file_write" and tc_result and tc_result.success:
                            _pre = _consume_prewrite_snapshot(tc_args.get("path", ""))
                            if _pre is not None:
                                _dest = (tc_result.metadata or {}).get("path", "")
                                if _dest:
                                    try:
                                        with open(_dest, "r", encoding="utf-8", errors="replace") as _f:
                                            _after = _f.read()
                                    except Exception:
                                        _after = ""
                                    _emit_file_diff(
                                        _obs, path=str(_dest), content_before=_pre, content_after=_after
                                    )
                            # Log write stat
                            _log_session_write(
                                session_id,
                                path=(tc_result.metadata or {}).get("path", ""),
                                tool="file_write",
                                bytes=(tc_result.metadata or {}).get("bytes", 0),
                                lines=(tc_result.metadata or {}).get("lines", 0),
                                kind=_write_kind_from_snapshot(_pre),
                            )
                        # Log write stat for apply_proposed_edit in batch
                        if tc_name == "apply_proposed_edit" and tc_result and tc_result.success and tc_result.metadata:
                            _applied = tc_result.metadata.get("applied", False)
                            if _applied:
                                _log_session_write(
                                    session_id,
                                    path=tc_result.metadata.get("path", ""),
                                    tool="apply_proposed_edit",
                                    bytes=tc_result.metadata.get("bytes", 0),
                                    lines=tc_result.metadata.get("lines", 0),
                                    kind="overwritten",
                                )
                    except Exception as e:
                        tc_obs = f"[Tool {tc_name} error: {e}]"
                        tc_failed = True
                    tc_lat = round((time.monotonic() - t_start) * 1000)
                    tc_provider = _tool_provider(tc_result)
                    return tc_name, tc_obs, tc_failed, tc_lat, tc_provider

                # Build labels for each tool call
                # Capture the batch's 'why' ONCE — the started
                # emits below run BEFORE _advance_plan_on_narration and the
                # done emits AFTER it, so calling _step_reasoning() at each
                # emit would stamp the same tool call with two different step
                # labels on a narrated transition. All calls in a batch share
                # the same cursor, so one capture serves the whole batch.
                _batch_reasoning = _step_reasoning()
                _syn_ids: list[Optional[str]] = []
                for call, _inp in valid_calls:
                    _syn_ids.append(_synth_begin(call.tool_name, _inp))
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
                        "dir_explorer": (
                            f"Exploring ({call.tool_args.get('operation', 'list')}): {_path[:80]}"
                            if _path else "Inspecting a folder"
                        ),
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
                            todo_id=_syn_ids[-1] or (f"plan-{_plan_step_cursor}" if _plan_steps else None),
                            thought=result.raw_content or "", reasoning=_batch_reasoning,
                        )

                # A narrated iteration is a step transition —
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
                    _syn_id = _syn_ids[idx] if 0 <= idx < len(_syn_ids) else None
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
                            todo_id=_syn_id or (f"plan-{_plan_step_cursor}" if _plan_steps else None),
                            thought=result.raw_content or "",
                            reasoning=_batch_reasoning,
                            provider=tc_provider,
                        )
                    _synth_end(_syn_id, tc_failed)
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
                    # P0 Step 4 slice 2: bounded head + retrieval pointer for a
                    # large result (indexes the full output so the truncated tail
                    # is recoverable via search_tool_results); plain bounded head
                    # otherwise. Computed ONCE and reused across every carried
                    # surface so they stay consistent.
                    _carried = await _carry_observation(
                        tc_obs, tc_name, session_id, loaded_tools,
                        fallback=_truncate_observation(tc_obs),
                    )
                    observation_log += (
                        f"\n[Tool: {tc_name} | Status: {'FAILED' if tc_failed else 'OK'} | Latency: {tc_lat}ms]\n"
                        f"{_carried}\n"
                    )
                    trace.steps.append(
                        AgentStep(
                            iteration=iteration + 1,
                            thought=result.raw_content or "",
                            tool_name=tc_name,
                            tool_input="",  # individual inputs not tracked in parallel
                            observation=_carried,
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
                            "content": _carried,
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
                    _merge_call_usage(_provider_usage, result_usage)
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

                _maybe_launch_first_tool_consult([tool_name])

                # ── Validate required args before dispatch ──────────────────
                # Reject tool calls missing required parameters (e.g. file_write
                # without 'path' or 'content'). This gives the model a clear
                # error message so it can self-correct instead of dispatching
                # a doomed tool call that wastes an iteration.
                if tool_name == "file_write":
                    # Normalize free-tier aliases (file_path → path,
                    # text/body/code → content) BEFORE every arg check below —
                    # the required-args gate, the content-length guard, and the
                    # contract payload all see canonical fields.
                    from tools.file_writer import _normalize_write_payload

                    tool_args = _normalize_write_payload(tool_args)
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
                # — except for tools that declare empty input as valid
                # (sysinfo/observe default to a full overview when bare).
                if _input_is_degenerate(tool_name, tool_input):
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

                # ── Structural dedup for read-only inspections ──────────────
                # The exact-match fingerprint below misses near-identical
                # repeat listings — "the same Get-ChildItem asked with
                # different columns/formatting" re-ran and burned an
                # iteration each time (user's dev-folder transcript: 5
                # listings). When the call is a read-only inspection whose
                # STRUCTURAL fingerprint already produced a result this turn,
                # reuse it: the inspected state is unchanged (cache is
                # invalidated by any mutating call), so only the
                # presentation differed. The marker check ("|EXACT|")
                # ensures only allow-listed read-only commands are folded.
                _structural_key: str = ""
                if _inspection_can_be_rerun(tool_name, tool_input):
                    _candidate = _inspection_fingerprint(tool_name, tool_input)
                    if _candidate and "|EXACT|" not in _candidate:
                        _structural_key = _candidate
                        if _structural_key in _inspection_cache:
                            cached_obs = _inspection_cache[_structural_key]
                            logger.info(
                                f"[agent.loop] inspection-dedup hit for {tool_name!r} "
                                f"fp={_structural_key[:60]!r} — returning cached result"
                            )
                            observation_log += (
                                f"\n[Tool: {tool_name} | Input: {tool_input[:60]} | "
                                f"Status: CACHED (same inspection already run this turn)]\n"
                                f"{_truncate_observation(cached_obs)}\n"
                            )
                            trace.steps.append(
                                AgentStep(
                                    iteration=iteration + 1,
                                    thought=result.raw_content or "",
                                    tool_name=tool_name,
                                    tool_input=tool_input,
                                    observation=f"[inspection-dedup] {cached_obs[:200]}",
                                    tool_failed=False,
                                    retry_count=0,
                                    latency_ms=llm_ms,
                                )
                            )
                            _inspection_seen.add(_structural_key)
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
                        "dir_explorer": (
                            f"Exploring ({tool_args.get('operation', 'list')}): {_path[:80]}"
                            if _path else "Inspecting a folder"
                        ),
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
                # Narrated iteration → step transition; the new
                # tool call belongs to the next plan todo.
                _advance_plan_on_narration()
                logger.info(
                    f"[agent.loop] iter={iteration + 1} tool={tool_name} input={tool_input[:80]} — {action_label}"
                )
                _syn_todo_id = _synth_begin(tool_name, tool_input)
                if _obs:
                    _obs.emit(
                        "tool_call",
                        tool=tool_name,
                        label=action_label,
                        status="started",
                        tool_args=tool_input,
                        iteration=iteration + 1,
                        todo_id=_syn_todo_id or (f"plan-{_plan_step_cursor}" if _plan_steps else None),
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
                # Bind up front — a pre-assignment exception in
                # the dispatch try (e.g. `Intent(tool_name)` raising) must not
                # leave `tool_result` unbound for the failed-branch emit below.
                tool_result: Optional[ToolResult] = None

                try:
                    tool_intent = _intent_for_tool(tool_name)

                    # ── file_write: validate and use typed contract ──────────
                    # Guard: if the model calls file_write without a meaningful
                    # content arg (e.g. placeholder like "read", "code", "yes"),
                    # REJECT the call so the model can self-correct.
                    # Previously this redirected to file_task (read), but that
                    # caused "not_found" errors when the file didn't exist yet
                    # (the user wanted to CREATE it, not READ it).
                    if tool_name == "file_write":
                        # Normalize aliases (file_path → path,
                        # text/body/code → content) BEFORE the content-length
                        # guard so a `{file_path, text}` payload is not wrongly
                        # rejected — the contract re-normalizes (idempotent).
                        from tools.file_writer import _normalize_write_payload

                        tool_args = _normalize_write_payload(tool_args)
                        _content = tool_args.get("content", "")
                        _path = tool_args.get("path", "")
                        if not _content or (
                            len(_content.strip()) < 5
                            and not _content_requested_by_user(
                                _content, _user_message_text(loop_messages, limit=None)
                            )
                        ):
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
                            # A rejection is a failed tool call: the run tree and
                            # the UI must see it end, not sit at "started" forever.
                            if _obs:
                                _obs.emit(
                                    "tool_call",
                                    tool=tool_name,
                                    label=action_label,
                                    status="failed",
                                    output=_truncate_observation(observation),
                                    latency_ms=round((time.monotonic() - t_tool) * 1000),
                                    tool_args=tool_input,
                                    iteration=iteration + 1,
                                    todo_id=_syn_todo_id or (f"plan-{_plan_step_cursor}" if _plan_steps else None),
                                    thought=result.raw_content or "",
                                    reasoning=_step_reasoning(),
                                )
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

                    # A possibly-mutating call must drop the
                    # structural inspection cache BEFORE running, so a
                    # listing that follows a write/edit/exec is never served
                    # stale output. Read-only inspections (incl. the shell
                    # call executing right now) keep the cache intact.
                    _maybe_invalidate_inspection_cache(tool_name, tool_input)

                    if tool_name == "file_write":
                        # Snapshot the pre-write content so a
                        # diff can be emitted for overwrite/new-write even
                        # though the tool replaces the file in place.
                        _record_prewrite_snapshot(tool_args.get("path", ""))
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
                        except Exception as exc:
                            # A contract execution error (bad args,
                            # IO, transient provider error) must not crash the
                            # loop with an unbound `tool_result` — surface it as
                            # a failed tool result so the normal recovery path
                            # runs. Never silently re-execute.
                            logger.warning(f"[agent.loop] file_write contract failed: {exc}")
                            tool_result = ToolResult(
                                content=f"file_write failed: {exc}",
                                source="file_write",
                                success=False,
                                error_type="contract_error",
                                error_message=str(exc),
                            )
                            tool_failed = True
                            retry_count = 0

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
                        except Exception as exc:
                            # Same unbound-`tool_result` guard as
                            # file_write — a contract exception must become a
                            # failed tool result, never a loop crash (which
                            # also swallowed the diff SSE event).
                            logger.warning(f"[agent.loop] edit_file contract failed: {exc}")
                            tool_result = ToolResult(
                                content=f"edit_file failed: {exc}",
                                source="edit_file",
                                success=False,
                                error_type="contract_error",
                                error_message=str(exc),
                            )
                            tool_failed = True
                            retry_count = 0

                        # Bridge diff metadata from edit_file tool results.
                        # Emit a file_diff obs event so the frontend DiffBlock can
                        # render green/red highlighted diffs — like Cursor/Claude.
                        # (metadata is {} on the failure result above, so a
                        # failed contract never emits a bogus diff.)
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
                        # Snapshot before a shell write so a
                        # diff can be emitted when the command rewrote a file.
                        # dispatch_with_retry is also the path for other tools
                        # — a harmless no-op for reads.
                        _record_prewrite_snapshot(tool_args.get("path", ""))
                        tool_result, tool_failed, retry_count = await dispatch_with_retry(
                            tool_intent,
                            tool_input,
                            adapter=active_adapter,
                            allowed_tool_names=effective_allowed,
                        )

                    # Emit a diff for ANY file-writing tool,
                    # not just edit_file. file_write replaces the file in
                    # place, so the loop computes hunks from the pre-write
                    # snapshot + the now-landed on-disk content — the same
                    # file_diff obs event the frontend DiffBlock renders.
                    if tool_name == "file_write" and tool_result and tool_result.success:
                        _pre = _consume_prewrite_snapshot(tool_args.get("path", ""))
                        if _pre is not None:
                            _dest = (tool_result.metadata or {}).get("path", "")
                            if _dest:
                                try:
                                    with open(_dest, "r", encoding="utf-8", errors="replace") as _f:
                                        _after = _f.read()
                                except Exception:
                                    _after = ""
                                _emit_file_diff(
                                    _obs, path=str(_dest), content_before=_pre, content_after=_after
                                )
                        # Log write stat
                        _log_session_write(
                            session_id,
                            path=(tool_result.metadata or {}).get("path", ""),
                            tool="file_write",
                            bytes=(tool_result.metadata or {}).get("bytes", 0),
                            lines=(tool_result.metadata or {}).get("lines", 0),
                            kind=_write_kind_from_snapshot(_pre),
                        )

                    # Log write stat for edit_file (single-tool path)
                    if tool_name == "edit_file" and tool_result and tool_result.success and tool_result.metadata:
                        _log_session_write(
                            session_id,
                            path=tool_result.metadata.get("path", ""),
                            tool="edit_file",
                            bytes=0,
                            lines=tool_result.metadata.get("modified_lines", 0),
                            kind="overwritten",
                        )

                    # Log write stat for apply_proposed_edit (single-tool path)
                    if (
                        tool_name == "apply_proposed_edit"
                        and tool_result
                        and tool_result.success
                        and tool_result.metadata
                    ):
                        if tool_result.metadata.get("applied", False):
                            _log_session_write(
                                session_id,
                                path=tool_result.metadata.get("path", ""),
                                tool="apply_proposed_edit",
                                bytes=tool_result.metadata.get("bytes", 0),
                                lines=tool_result.metadata.get("lines", 0),
                                kind="overwritten",
                            )

                    # A describe_tool call loads the named
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
                        # so a tool error is never a dead end.
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

                        # Also seed the structural inspection
                        # cache so a later cosmetic variant of the same
                        # read-only listing hits the dedup above. Only
                        # successful, non-mutating inspections are cached.
                        if _structural_key and tool_result.success and tool_name != "file_write":
                            _inspection_cache[_structural_key] = safe_obs

                        # Track file_write paths for name-level dedup
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
                            # Verify WHERE THE WRITE ACTUALLY LANDED
                            # (tool_result.metadata["path"]), not the model's
                            # requested arg. They diverge whenever file_write
                            # re-anchors a path or timestamp-renames a document —
                            # verifying the raw arg then read-back-failed a
                            # perfectly good write and injected a false
                            # [GROUNDING CHECK FAILED].
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

                _todo_id = _syn_todo_id or (f"plan-{_plan_step_cursor}" if _plan_steps else None)
                # A lookup plan ticks with real progress, not only on narration (a silent tool
                # run never narrates): a finished search completes "Search the web", a finished
                # page read completes "Check the sources".
                if _obs and not tool_failed and _lookup_plan_active:
                    _done_idx = lookup_step_for_tool(tool_name)
                    if _done_idx is not None:
                        for _i in range(_done_idx + 1):
                            _obs.emit("todo_completed", id=f"plan-{_i}", completed=True)
                        _plan_step_cursor = max(_plan_step_cursor, _done_idx + 1)
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
                                            todo_id=_todo_id,
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
                                            todo_id=_todo_id,
                                            thought=result.raw_content or "", reasoning=_step_reasoning(),
                                            provider=_tool_provider(tool_result),

                                        )

                _synth_end(_syn_todo_id, tool_failed)
                # Evidence-sufficient detection — the flag says
                # "the last successful real tool put substantive page content
                # in the transcript" (web intent only). The mid-task exclusion
                # (save/write/… in the request) keeps multi-step work free to
                # continue; a failed or stub-sized fetch leaves the flag off
                # so the model can pick another source.
                if not tool_failed and tool_name not in ("todo_write", "describe_tool"):
                    _evidence_answer_ready = (
                        tool_name in _EVIDENCE_COMPLETE_TOOLS
                        and isinstance(observation, str)
                        and len(observation) >= _EVIDENCE_MIN_CHARS
                        and not _EVIDENCE_EXCLUDE_ACTION_RE.search(
                            reformulated_message or ""
                        )
                        and not _EVIDENCE_EXCLUDE_ACTION_RE.search(
                            _user_message_text(loop_messages) or ""
                        )
                    )
                    if _evidence_answer_ready:
                        logger.info(
                            "[agent.loop] evidence-sufficient after %s (%d chars) — "
                            "next call is answer-only",
                            tool_name,
                            len(observation),
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
                # P0 Step 4 slice 2: for a LARGE result, index the full output
                # and carry a bounded head + retrieval pointer instead of the
                # whole payload (the single-tool path otherwise carries the
                # observation whole — the context-bloat driver on research
                # turns). Small results are carried unchanged (fallback).
                _carried_obs = await _carry_observation(
                    observation, tool_name, session_id, loaded_tools,
                    fallback=observation,
                )
                # Anti-fabrication wrapper: the model MUST base its response
                # on the actual tool output. Without this, models (especially
                # smaller ones like MiniMax M2.5) sometimes ignore the tool
                # result and fabricate plausible-looking but false data.
                if not tool_failed and _carried_obs:
                    safe_observation = (
                        f"[ACTUAL TOOL OUTPUT — use ONLY this data in your response]\n"
                        f"{_carried_obs}\n"
                        f"[END TOOL OUTPUT — do NOT invent or add items not shown above]"
                    )
                else:
                    safe_observation = _carried_obs
                loop_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": safe_observation,
                    }
                )

                # ── Post-tool Thinker consult ─────────────────────────────
                # A read-only reasoning pass on what was just GATHERED (not
                # the raw request). Its prose streams to the
                # ThinkingBlock. After a SUCCESSFUL tool the consult
                # no longer blocks the next model call — it runs in the
                # background (overlapping the model work) and its analysis is
                # injected at the next iteration head by the drain there;
                # this is what lets the consult fire after EVERY tool without
                # re-creating the earlier serial latency. After a FAILURE
                # the consult stays BLOCKING: recovery advice must shape the
                # very next call or the model may repeat the failure.
                # Throttling: at most one consult in flight and
                # _THINKER_CONSULT_CAP per turn (token spend + provider rate
                # limits); mechanical tools are skipped. Any failure is
                # swallowed — the Thinker never blocks a turn.
                _last_failed = bool(getattr(trace.steps[-1], "tool_failed", False)) if trace.steps else False
                _consult_eligible = (
                    observation
                    and intent in AGENT_INTENTS
                    and getattr(active_adapter, "thinking_enabled", False)
                    and tool_name not in _THINKER_TOOL_SKIP
                )
                if _consult_eligible and _consult_inflight is not None:
                    # Free the slot when the in-flight consult finished during
                    # tool execution (same drain contract as the head).
                    _drain_chunks, _drain_done = _consult_inflight.drain_nowait()
                    for _tc in _drain_chunks:
                        yield StreamChunk(text="", thinking=_filter_system_leaks(_tc.thinking), done=False)
                    if _drain_done:
                        _absorb_thinker_analysis(
                            loop_messages, trace, _obs, _consult_inflight.analysis, _consult_inflight.iteration
                        )
                        _consult_inflight = None
                if (
                    _consult_eligible
                    and _consults_fired < _THINKER_CONSULT_CAP
                    and (_last_failed or _consult_inflight is None)
                ):
                    _consults_fired += 1
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
                            # Continuity: an earlier consult this turn (the
                            # pre-tool pass or a previous post-tool one) hands
                            # its summary forward so the reasoning compounds
                            # instead of restarting.
                            prior_analysis=trace.thinker_analysis or "",
                        )
                        if _ev.has_evidence:
                            if _obs:
                                _obs.emit("agent_thinker_start", iteration=iteration + 1)
                            _consult_timeout = _reasoning_setting(
                                "localmind_reasoning_plan_timeout_secs", REASONING_PLAN_TIMEOUT_SECS
                            )
                            if _last_failed:
                                # BLOCKING — recovery advice shapes the very
                                # next call (slice-1 forwarding contract).
                                _thinker = Thinker(timeout_secs=_consult_timeout)
                                async for _tc in _thinker.consult(_ev, active_adapter):
                                    if isinstance(getattr(_tc, "thinking", None), str) and _tc.thinking:
                                        yield StreamChunk(
                                            text="", thinking=_filter_system_leaks(_tc.thinking), done=False
                                        )
                                _absorb_thinker_analysis(
                                    loop_messages, trace, _obs, _thinker.last_analysis, iteration + 1
                                )
                            else:
                                # BACKGROUND — overlap the next model call.
                                _consult_inflight = _BackgroundConsult(_ev, active_adapter, _consult_timeout)
                                _consult_inflight.start()
                    except Exception as _thx:  # never let the Thinker break a turn
                        logger.warning("[agent.loop] Thinker consult skipped: %s", _thx)

                # Tool output must NOT become the final assistant
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
                _streamed_reasoning = False  # did this call stream thinking?
                _reasoning_buffer = ""  # capture the reasoning TEXT
                # (not just the flag). On GLM/thinking the model sometimes puts its
                # real answer/analysis in the reasoning channel and leaves content
                # empty; the endgame salvages this instead of failing the turn.
                _minimax_error_msg = ""  # keep the adapter's error
                # message (e.g. "zen returned 429: …") — previously dropped, so
                # the frontend got error="" and rendered nothing.
                _minimax_partial_seen = False  # track if we've seen start of XML

                # Live-stream the final answer instead of buffering
                # it for a single burst (timeline: ~51s of dead air then a dump).
                # SAFE-GATED — live streaming only when NO discard path can fire
                # after text is already on screen (no frontend supersede yet):
                #   (a) POST-TOOL iteration (iteration>=1 with a tool already
                #       run) — first-iteration force-tool recovery cannot apply;
                #   (b) the LAST tool run is NOT high-stakes (file_write/
                #       file_edit/shell/code_exec) — those turns keep the
                #       parent-completion-floor's ability to discard + replan
                #       silently without a duplicate answer;
                #   (c) NO success criteria — a research/chat turn; the
                #       acceptance gate passes trivially, so the
                #       "don't show discarded text" guarantee is not at stake
                #       (goal turns keep buffering).
                # The buffer path stays authoritative: we only ADD live yields
                # once a small lookahead confirms no text-encoded tool-call
                # marker, and per-chunk holds below catch a marker arriving
                # mid-stream. The fabricated-data recovery is bypassed once
                # live streaming started (obs-emitted) — its `continue` would
                # duplicate the shown text.
                from core.agent.post_execution_verifier import is_high_stakes_intent

                _last_tool_name = next(
                    (
                        getattr(s, "tool_name", "") or ""
                        for s in reversed(trace.steps if trace else [])
                        if getattr(s, "tool_name", "")
                    ),
                    "",
                )
                _stream_live_ok = (
                    iteration >= 1
                    and bool(_last_tool_name)
                    and not is_high_stakes_intent(_last_tool_name)
                    and not getattr(trace, "success_criteria", None)
                    # An answer-only reply must stay buffered —
                    # if it turns out to narrate a further action, the gate
                    # withholds it entirely (FORCE_TOOL replan); live-streamed
                    # text could never be taken back.
                    and not _answer_only_call_used
                )
                _streamed_live = False
                _streamed_live_text: list[str] = []
                _pending_text = ""

                async for chunk in result:
                    # Abort check during stream buffering.
                    if abort_signal is not None and abort_signal.is_set():
                        raise AgentAbortedError("aborted during streaming")
                    filtered_text = _filter_system_leaks(chunk.text)
                    _minimax_buffer += filtered_text
                    if chunk.usage:
                        _merge_call_usage(_provider_usage, chunk.usage)
                    _minimax_chunks.append(
                        StreamChunk(text=filtered_text, done=chunk.done, usage=dict(_provider_usage))
                    )
                    # Live streaming (gated): flush the head once past a ~150-char
                    # lookahead with no tool-call marker, then stream each chunk.
                    # Subsequent chunks are held one pending-buffer deep so a
                    # text-encoded tool-call marker arriving mid-stream (<invoke
                    # … / minimax:tool_call) is NEVER yielded live — a marker
                    # flips the turn back to the buffered path (the interceptor
                    # owns it) instead of leaking XML into the chat bubble. A
                    # chunk merely ENDING in "<" is held one more chunk (a
                    # marker can straddle a chunk boundary).
                    if _stream_live_ok:
                        if not _streamed_live:
                            if (len(_minimax_buffer) >= 150 or chunk.done) and not (
                                _MINIMAX_PARTIAL_RE.search(_minimax_buffer)
                                or _STANDALONE_PARTIAL_RE.search(_normalize_dsml(_minimax_buffer))
                                or _has_minimax_tool_call(_minimax_buffer)
                            ):
                                _streamed_live = True
                                _streamed_live_text.append(_minimax_buffer)
                                yield StreamChunk(text=_minimax_buffer, done=False, usage=dict(_provider_usage))
                        elif filtered_text:
                            _pending_text += filtered_text
                            _pending_lower = _pending_text.lower()
                            if (
                                "<invoke" in _pending_lower
                                or "minimax:tool_call" in _pending_lower
                                or _pending_text.rstrip().endswith("<")
                            ):
                                # Possible tool-call XML — stop live-streaming;
                                # pending text stays in the buffer path only.
                                _stream_live_ok = False
                            else:
                                _streamed_live_text.append(_pending_text)
                                yield StreamChunk(text=_pending_text, done=False, usage=dict(_provider_usage))
                                _pending_text = ""
                    # Forward the model's reasoning live
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

                        if (
                            not tool_input or len(tool_input.strip("?. \t")) < 3
                        ) and not _tool_allows_empty_input(tc_name):
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
                            "dir_explorer": (
                                f"Exploring ({_normalized_args.get('operation', 'list')}): {_path[:80]}"
                                if _path else "Inspecting a folder"
                            ),
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
                        _syn_todo_id = _synth_begin(tc_name, tool_input)
                        if _obs:
                            _obs.emit(
                                "tool_call",
                                tool=tc_name,
                                label=action_label,
                                status="started",
                                iteration=iteration + 1,
                                todo_id=_syn_todo_id or (f"plan-{_plan_step_cursor}" if _plan_steps else None),
                                thought=_strip_minimax_tool_calls(_minimax_buffer), reasoning=_step_reasoning(),
                            )

                        # Dispatch the tool
                        t_tool = time.monotonic()
                        tool_failed = False
                        tool_result: Optional[ToolResult] = None
                        try:
                            tool_intent = _intent_for_tool(tc_name)
                            tool_result, tool_failed, retry_count = await dispatch_with_retry(
                                tool_intent,
                                tool_input,
                                adapter=active_adapter,
                                obs=_obs,  # delegation streams into the UI
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
                                # step — never a dead end.
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
                                todo_id=_syn_todo_id or (f"plan-{_plan_step_cursor}" if _plan_steps else None),
                                thought=_strip_minimax_tool_calls(_minimax_buffer), reasoning=_step_reasoning(),
                            )

                        _synth_end(_syn_todo_id, tool_failed)
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
                    # On the
                    # FIRST tool iteration, text without a tool call is
                    # usually model fragility, not a real answer — the
                    # model skipped the tool API (gemini-2.5-flash via
                    # OpenAI-compat returned text/empty on the first tool
                    # call — seen live). Reprompt with a
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
                                    + _recovery_nudge_tail(loop_messages, trace)
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
                        # FIRST try deterministic
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
                        # with the actual evidence, NOT "check the Actions panel."
                        # The user should never be told to look at
                        # the Actions panel — that's a developer debug UX, not
                        # a user-facing response. Instead, build a simple summary
                        # from the tool observations we already have.
                        _tool_count = sum(1 for s in (trace.steps if trace else []) if getattr(s, "tool_name", ""))
                        if _tool_count > 0:
                            # Build a simple evidence summary from trace steps
                            _evidence_lines = []
                            for s in (trace.steps if trace else []):
                                _obs = getattr(s, "observation", "") or ""
                                if _obs and len(_obs.strip()) > 20:
                                    # Strip page chrome (nav/login/loading junk) so
                                    # the fallback shows headlines, not a wall of
                                    # "Subscribe now / LOGOUT". Keep the first ~600
                                    # chars of the cleaned content.
                                    _clean = _clean_evidence_text(_obs) or _obs.strip()
                                    _evidence_lines.append(_clean[:600])
                            if _evidence_lines:
                                _summary = (
                                    "Here's what I found (the model provider was "
                                    "rate-limited on my final synthesis, so this "
                                    "is the raw evidence):\n\n"
                                    + "\n\n---\n\n".join(_evidence_lines[:3])
                                )
                            else:
                                _summary = (
                                    "I gathered the information you asked for, but "
                                    "the model provider was rate-limited. Please "
                                    "try again in a moment and I'll give you a "
                                    "clean summary."
                                )
                            yield StreamChunk(
                                text=_summary,
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
                #
                # This recovery must be intent-gated like the
                # fabrication/forced-tool checks above. Live bug on a plain
                # "Hi" (CHAT intent, deepseek-v4-flash): the greeting mentioned
                # tools ("I'm ready to help — file work, research, coding…")
                # and tripped _is_tool_talk, so the loop suppressed the greeting
                # and injected "You described wanting to use a tool but did not
                # call it. You MUST use the tool-calling API directly…". The
                # small model then spiraled in its reasoning trying to reconcile
                # "Hi needs no tool" with the injected demand — visible to the
                # user as a garbled "Approach" thinking block. Tool-talk is only
                # a failure when the turn is SUPPOSED to use tools (agent
                # intents); a conversational turn must never get the correction.
                if (
                    intent in AGENT_INTENTS
                    and _is_tool_talk(initial_buffer)
                    and trace.tool_talk_recoveries < _MAX_TOOL_TALK_RECOVERIES
                    # On an answer-only call (tool schemas
                    # withheld) the narration IS the signal that the model
                    # needs a tool — nudging it to "call the tool now" is
                    # impossible (no schemas) and burns the recovery budget
                    # before the acceptance gate can FORCE_TOOL properly.
                    and not _answer_only_call_used
                ):
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
                                + _recovery_nudge_tail(loop_messages, trace)
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
                    # Once the answer streamed live, the recovery's
                    # `continue` would show the forced re-search under the text
                    # already on screen (duplicate). The head was veto-checked
                    # before streaming started; a late pattern match is logged
                    # and the answer stands (the deliberate streaming tradeoff).
                    and not _streamed_live
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

                # ── Empty-response guard ──────────────────────────────────
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
                    # An EMPTY
                    # response on the FIRST tool iteration is model
                    # fragility (gemini-2.5-flash returned empty/no-tool in
                    # 788ms — seen live), not evidence that the
                    # model is overloaded. Reprompt once with a forced-tool
                    # nudge before the honest fast-fail below, so the
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
                                    + _recovery_nudge_tail(loop_messages, trace)
                                ),
                            }
                        )
                        continue  # retry this iteration with the forced-tool nudge

                    # Follow-up to the thinking re-enable: the model streamed
                    # reasoning but returned no text and no tool call — on a
                    # slow free tier with thinking ON, GLM sometimes "thinks
                    # but doesn't act" (live user bug: iter-1 ran shell
                    # Get-ChildItem, iter-2 streamed reasoning then went
                    # empty, failing the whole turn). The reasoning is real
                    # progress, so do ONE bounded retry with a nudge before
                    # the honest fail. Two consecutive empties still fail
                    # fast — the think-only protection stays intact.
                    #
                    # Parent turns get a higher
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
                        # Ground truth showed the model streams
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
                        # Include the user's
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
                        # On the LAST empty-reasoning retry for a tool-bearing intent,
                        # force tool_choice so the model MUST call a tool instead of producing
                        # another empty response or prose. This cuts zai's wasted iterations
                        # in half (empty-think -> nudge -> force-tool-call).
                        if (
                            trace.empty_reasoning_recoveries >= _empty_reasoning_cap - 1
                            and intent in AGENT_INTENTS
                            and filtered_tools
                            and _gate_force_tool is not None
                        ):
                            _gate_force_tool[0] = True
                            logger.info(
                                "[agent.loop] last empty-reasoning retry — forcing tool_choice"
                            )
                        continue  # retry with thinking OFF so the model acts

                    trace.empty_response = True  # remember this failure
                    if _obs:
                        _obs.emit(
                            "agent_loop_empty_response",
                            intent=intent.value,
                            iteration=iteration + 1,
                        )
                    if not stream_ended_early:
                        async for _drain in result:
                            pass

                    # FIRST try deterministic
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

                    # SYNTHESIZE a real answer before giving up.
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
                    # LAST safety net. The synthesis-from-reasoning
                    # rescue above failed
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
                    # Post-loop synthesis also failed. Produce
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
                    # Do NOT complete the plan todo here — the
                    # model produced nothing and NO tool ran, so marking the
                    # step done would be a lie. The SSE bridge's end-of-turn
                    # _finalize_plan_todos still closes it (the plan covers
                    # the whole turn), but we don't pretend the work happened.
                    self._emit_failure_memory(trace, intent, _obs)  # record a failure memory
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
                            if (
                                not _tc_input or len(_tc_input.strip("?. \t")) < 3
                            ) and not _tool_allows_empty_input(_tc_name):
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
                                    obs=_obs,  # delegation streams into the UI
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

                # Do NOT yield the initial buffer here. Buffer
                # the iteration's text and only emit it AFTER the acceptance
                # gate confirms is_final=True. If the gate fails, the buffered
                # text is discarded so the user doesn't see a duplicate answer
                # from a doomed iteration.
                # (Previously the buffer was re-yielded here unconditionally,
                # duplicating the answer.)

                # If the stream already ended (short response), we're done
                if stream_ended_early:
                    # Drop a mimicked internal-report block before the gate
                    # evidence check, the flush, and persistence see it.
                    _clean_head = strip_worker_reports(_stripped_buffer)
                    if _clean_head != _stripped_buffer:
                        _stripped_buffer = _clean_head
                        full_text = strip_worker_reports(full_text)
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
                    # The model saying "done" is not enough — gate
                    # the claim against the success criteria (replan or honest
                    # report). Only finish when the gate is satisfied or capped.
                    _gate_suffix, _gate_final = await self._acceptance_gate_at_final_answer(
                        trace=trace,
                        iteration=iteration,
                        effective_max_iter=_iter_hard_cap,
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
                        plan_steps=_plan_steps,
                        gate_replan_count=_gate_replan_count,
                        gate_force_tool=_gate_force_tool,
                        tools_withheld=_answer_only_call_used,
                    )
                    if not _gate_final:
                        _gate_replan_count += 1
                        logger.info("[agent.loop] gate replan #%d", _gate_replan_count)
                        # Discard this iteration's text — don't
                        # emit it. The next iteration will produce the answer.
                        if _obs:
                            _obs.emit(
                                "agent_loop_iteration_discarded",
                                iteration=iteration + 1,
                                reason="gate_failed_text_withheld",
                                discarded_chars=len(_stripped_buffer),
                            )
                        continue
                    # Gate passed — flush the buffered text now.
                    # If the head streamed live, flush only the
                    # unseen tail (prefix-aware) — never re-yield shown text.
                    if _streamed_live:
                        _flush_tail = _flush_after_live_stream(
                            "".join(_streamed_live_text), _stripped_buffer
                        )
                        if _flush_tail:
                            yield StreamChunk(text=_flush_tail, done=False, usage=dict(_provider_usage))
                    elif _stripped_buffer.strip():
                        yield StreamChunk(text=_stripped_buffer, done=False, usage=dict(_provider_usage))
                    # The gate passed but the model may have run
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
                    # Turn-end — close out the current plan step's
                    # todo (covers the stream-ended-early silent path).
                    _complete_current_plan_step()
                    self._emit_failure_memory(trace, intent, _obs)
                    if _obs:
                        _obs.emit("agent_loop_done", intent=intent.value, iterations=iteration + 1)
                    _worker_report = trace.work_report()
                    if _worker_report.needs_report(full_text):
                        # Try one focused synthesis call before
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
                # Buffer chunks instead of yielding live. Emit
                # only after the gate confirms is_final=True. If the gate fails,
                # the buffer is discarded so the user doesn't see a duplicate
                # answer from a doomed iteration.
                _mid_stream_minimax_buffer = ""
                _mid_stream_text = ""
                _iteration_clean_text = ""  # buffered until the gate verdict
                async for chunk in result:
                    # Respond to abort DURING streaming —
                    # the longest phase (up to PER_CALL_TIMEOUT_SECS). is_set()
                    # is a flag read; checked per chunk.
                    if abort_signal is not None and abort_signal.is_set():
                        raise AgentAbortedError("aborted during streaming")
                    if chunk.usage:
                        _merge_call_usage(_provider_usage, chunk.usage)
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
                    # Forward the model's reasoning live
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
                        # Buffer instead of yield. The flush
                        # happens after the acceptance gate confirms is_final.
                        _iteration_clean_text += _chunk_clean

                # If the model mimicked the internal evidence-recap format
                # (it may have read it back from a polluted history), drop
                # the block now — before the gate evidence check, the flush,
                # and persistence see it. The deterministic renderer stays
                # the only author of that format.
                _raw_combined = _stripped_buffer + _iteration_clean_text
                _clean_combined = strip_worker_reports(_raw_combined)
                if _clean_combined != _raw_combined:
                    full_text = strip_worker_reports(full_text)
                    _stripped_buffer, _iteration_clean_text = _clean_combined, ""

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
                # Gate the model's "done" claim (replan or honest
                # report) BEFORE the turn-end events — the loop is only done
                # when the gate is satisfied or the caps force an honest close.
                _gate_suffix, _gate_final = await self._acceptance_gate_at_final_answer(
                    trace=trace,
                    iteration=iteration,
                    effective_max_iter=_iter_hard_cap,
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
                    plan_steps=_plan_steps,
                    gate_replan_count=_gate_replan_count,
                    gate_force_tool=_gate_force_tool,
                    tools_withheld=_answer_only_call_used,
                )
                if not _gate_final:
                    _gate_replan_count += 1
                    logger.info("[agent.loop] gate replan #%d (alt)", _gate_replan_count)
                    # Discard the buffered text — don't emit it.
                    if _obs:
                        _obs.emit(
                            "agent_loop_iteration_discarded",
                            iteration=iteration + 1,
                            reason="gate_failed_text_withheld",
                            discarded_chars=len(_iteration_clean_text),
                        )
                    continue
                # Gate passed — flush the buffered text now.
                # If the head streamed live, flush only the unseen
                # tail. The full clean answer = _stripped_buffer (first buffering
                # loop — includes any held pending chunk) + _iteration_clean_text
                # (this remainder loop's per-chunk cleaned text); the shown prefix
                # is subtracted prefix-aware, so held-but-unseen text is recovered
                # and shown text is never re-yielded.
                if _streamed_live:
                    _flush_tail = _flush_after_live_stream(
                        "".join(_streamed_live_text),
                        _stripped_buffer + _iteration_clean_text,
                    )
                    if _flush_tail:
                        yield StreamChunk(text=_flush_tail, done=False, usage=dict(_provider_usage))
                else:
                    # Head-drop fix (buffered-flush path): the buffered
                    # flush yielded ONLY _iteration_clean_text — on answers long
                    # enough to fill the 2000-char detection buffer, the head
                    # (_stripped_buffer) never reached the user. Flush the head
                    # before the tail (non-streamed turns have no dedupe need:
                    # nothing was shown live).
                    if _stripped_buffer.strip():
                        yield StreamChunk(text=_stripped_buffer, done=False, usage=dict(_provider_usage))
                    if _iteration_clean_text.strip():
                        yield StreamChunk(text=_iteration_clean_text, done=False, usage=dict(_provider_usage))
                # Gate passed but no model answer — synthesize the
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
                    # Try one focused synthesis call before
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
                    # Model stream produced no text after
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
                # Close out the current plan step's todo — a
                # silent tool run never advanced the cursor, so without this
                # the executed step stays 'pending' in the Todos panel.
                _complete_current_plan_step()
                yield StreamChunk(text="", done=True, usage=dict(_provider_usage))
                return

        # ── MAX_ITERATIONS hit (or wall-clock cap / repetition stop) ──
        trace.hit_limit = True
        if not trace.limit_kind:
            trace.limit_kind = "hard_ceiling"
        logger.warning(
            "[agent.loop] loop ended — %s limit_kind=%s", trace.summary(), trace.limit_kind
        )
        # Close out the current plan step's todo on the
        # hit-limit path too — the work for the current step may have
        # completed even though the loop was capped.
        _complete_current_plan_step()
        if _obs:
            _obs.emit(
                "agent_loop_done",
                intent=intent.value,
                iterations=trace.iterations_used,
                hit_limit=True,
                limit_kind=trace.limit_kind,
            )

        # ALWAYS try to synthesize a final answer from what
        # we gathered. Wrap with a timeout so this doesn't hang too.
        # If it times out, yield the observation log directly — the user
        # sees what happened instead of nothing. On the real-text path the
        # synthesis sets trace.final_response itself; the
        # deterministic fallbacks (timeout / exception / empty stream)
        # deliberately do not, so classification still reports the failure.
        try:
            async for chunk in self._force_final_answer(
                loop_messages=loop_messages,
                observation_log=observation_log,
                active_adapter=active_adapter,
                trace=trace,  # pass trace so empty-stream fallback can surface tool outputs
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

        # Classify AFTER the rescue, not before. A capped turn
        # whose forced synthesis delivered a real answer is a rescued turn,
        # not a failure: the old order emitted `agent_loop_failure` before
        # the synthesis ran, so the user saw "✗ Agent loop failed" ABOVE a
        # complete answer (the "find my CV" transcript).
        self._emit_failure_memory(trace, intent, _obs)

    # ------------------------------------------------------------------
    # Acceptance gate at the final-answer point
    # ------------------------------------------------------------------

    # ──────────────────────────────────────────────────────────────────────
    # Failure memory emit
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

        Seen live: execute turns like "list my dev folder" ran the tool and
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

    def _emit_honest_stop(self, criteria, results, obs, plan_steps) -> None:
        """The synthesize/evaluate stage's honest-stop report.

        When the acceptance gate ends the turn with UNMET criteria (iteration
        cap / same-tool streak), emit the per-goal todo state so the Todos
        panel shows the TRUE fraction (never 100%), and flag the turn so the
        SSE bridge skips its end-of-turn todo finalization — which would
        otherwise flip the unmet items to completed (the self-mutating
        checklist lie the user diagnosed: whatever ran defines "done"
        retroactively).

        Passed goal items are completed here; unmet items stay pending.
        """
        if not obs:
            return
        unmet = [c for c, _p, _n in (results or []) if not _p]
        obs.emit(
            "agent_loop_gate_honest_stop",
            unmet_count=len(unmet),
            unmet="; ".join(unmet)[:400],
        )
        for i, (_c, passed, _n) in enumerate(results or []):
            if passed and plan_steps and 0 <= i < len(plan_steps):
                obs.emit("todo_completed", id=f"plan-{i}", completed=True)

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
        # Pass-through from run() so the orchestrator's
        # dead replan() method can finally be called. None = legacy.
        orchestrator=None,
        reformulated_message: str = "",
        memory_facts: Optional[list[str]] = None,
        intent_history: Optional[list[str]] = None,
        is_parent: bool = False,
        # The harness-derived goal checklist (plan_steps).
        # Used to emit the per-goal todo state on an honest stop.
        plan_steps: Optional[list[str]] = None,
        # Total gate replan count
        gate_replan_count: int = 0,
        # Mutable flag for gate→loop zero-tool force signal
        gate_force_tool: list[bool] | None = None,
        # True when the reply being gated came from an
        # answer-only call (tool schemas withheld). Changes the recovery
        # for post-evidence narration from SYNTHESIZE to FORCE_TOOL.
        tools_withheld: bool = False,
    ) -> tuple[str, bool]:
        """Gate the model's "done" claim against the success criteria.

        Runs when the model produces a final answer (no more tool calls).
        "An agent saying done should not mean the task is done":
          - All criteria met → suffix = the verified summary (✓ n/n).
          - Some unmet + iterations remain → EXPLICIT replan LLM call
            (a locked design decision); the revised plan is injected
            as a user block and the loop continues (returns is_final=False).
            When `orchestrator` is provided, it is notified
            FIRST — its replan() produces a structured OrchestrationResult
            (re-route, confidence drop, clarification question) which is
            prepended to the revised plan block. The orchestrator's obs
            events (orchestrator_replan_start/_done/_timeout/_failed) now
            fire for real (consumed by the frontend).
          - Some unmet + cap → suffix = the honest unmet report.
        No criteria → ("", True) — the legacy path is unchanged.
        """
        criteria = getattr(trace, "success_criteria", None) or []
        if not criteria:
            # The parent's missing VERIFY→DONE
            # floor. With no explicit criteria contract, don't accept the
            # parent's "done" when its last real action FAILED —
            # an action failure means the objective is not met.
            # Deterministic, keyed on the dispatcher's tool_failed verdict, and
            # scoped to the parent — read/analysis/successful turns are
            # unchanged (return the legacy model-assertion path below).
            _floor_note = parent_completion_floor_note(trace) if is_parent else None
            if _floor_note is None:
                # Zero-tool success shapes (injected-context gate): turns
                # whose answer is fully grounded in context the loop itself
                # injects (current date/time — the environment context block
                # carries the clock into every turn) and clean policy
                # declines of violation-shaped requests carry NO tool
                # evidence by design. The narration detectors below exist to
                # catch narrated-but-unexecuted ACTIONS, so a grounded
                # answer or a refusal that narrates nothing is accepted.
                # The detectors still win when the text commits to a tool
                # action — "I'll write that to a file" is narration even
                # when it quotes the injected date.
                if is_parent and not any(
                    getattr(s, "tool_name", "") for s in getattr(trace, "steps", []) or []
                ):
                    _final_text = getattr(trace, "final_response", "") or ""
                    from core.agent.injected_context_gate import (
                        zero_tool_turn_is_valid,
                    )

                    if (
                        _final_text.strip()
                        and not prose_commits_to_tool_action(_final_text)
                        and not narrates_pending_action(_final_text)
                        and zero_tool_turn_is_valid(
                            message=reformulated_message or "",
                            answer=_final_text,
                        )
                    ):
                        return "", True
                # The prose-tool-commitment
                # detector. Distinct from the completion floor (which fires
                # when a tool RAN and failed): this fires when NO tool ran
                # this run AND the model's prose *commits* to a tool action
                # ("I'll use the shell tool", "let me describe..."). The
                # model intended to act but didn't emit the tool_call — a
                # known weak-model pattern (glm-4.5-flash live trace).
                # Inject ONE bounded re-prompt; if the model
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
                                    "content": _stage_card(
                                        "TOOL COMMITMENT", "act", _DECISION_ACT, loop_messages, trace
                                    ),
                                }
                            )
                            return "", False
                # Broader action-narration detector. The
                # prose_commits_to_tool_action detector requires BOTH a
                # commitment phrase AND a tool-name mention. But weak models
                # say "I'll start by exploring the Dev/ folder" — an action
                # phrase with no tool name. On the parent agent, if the model
                # produced an action-oriented final answer with ZERO real tool
                # calls on iteration 1, and the intent is execute/analyze,
                # nudge once to force a tool call.
                #
                # Replanning threshold: only fire when the
                # user's message ACTUALLY implies a tool action. Conversational
                # requests ("give me ideas", "what do you think", "recommend
                # a book") don't need tools — the model's prose answer IS the
                # correct response. Firing the detector here caused the
                # cyber-café duplicate-answer bug: the model produced a valid
                # conversational answer, the gate failed it as "narration",
                # and the loop streamed ANOTHER answer into the same bubble.
                if (
                    is_parent
                    and iteration == 0
                    and intent != Intent.CHAT
                    # Lazy import to avoid circular dependency
                    # (core.trivial_input → core.engine._helpers → core.engine
                    # → core.agent_runtime → core.agent.loop). An explicit
                    # approval of an already-narrated action ("go ahead")
                    # escalates even when the approval itself names no
                    # tool/file (B-2026-09-15-8).
                    and (
                        _message_implies_tool_action(reformulated_message or "")
                        or _message_is_action_approval(reformulated_message or "")
                    )
                    # Don't fire the action-narration
                    # detector when the user explicitly said "do not write code
                    # yet" / "first analyze". The model's prose answer IS the
                    # correct response — the user asked for analysis, not tools.
                    and not _should_skip_workspace_state(reformulated_message or "")
                    and not any(
                        getattr(s, "tool_name", "")
                        and getattr(s, "tool_name", "") not in ("todo_write",)
                        for s in getattr(trace, "steps", []) or []
                    )
                ):
                    _final_text = getattr(trace, "final_response", "") or ""
                    _already_action_nudged = any(
                        isinstance(m, dict)
                        and isinstance(m.get("content", ""), str)
                        and "[ACTION NARRATION]" in m.get("content", "")
                        for m in (loop_messages or [])
                    )
                    if not _already_action_nudged and len(_final_text.strip()) > 10:
                        if obs:
                            obs.emit(
                                "agent_loop_gate_failed_replan",
                                intent=intent.value,
                                iteration=iteration + 1,
                                unmet=["model narrated an action plan but made zero tool calls"],
                            )
                        loop_messages.append(
                            {
                                "role": "user",
                                "content": _stage_card(
                                    "ACTION NARRATION", "act", _DECISION_ACT, loop_messages, trace
                                ),
                            }
                        )
                        # Signal the main loop to force tool_choice
                        if gate_force_tool is not None:
                            gate_force_tool[0] = True
                        return "", False
                # Loop-discipline seam: classify this parent final-answer
                # turn ONCE and apply exactly one recovery. Replaces the four
                # stacked detector blocks (pending-action / follow-through ->
                # FORCE_TOOL; hedge / post-evidence -> SYNTHESIZE) with a single
                # decision. See core.agent.turn_outcome.classify_turn_outcome.
                if is_parent:
                    _ft = getattr(trace, "final_response", "") or ""
                    _tools_ran = any(
                        getattr(s, "tool_name", "") for s in getattr(trace, "steps", []) or []
                    )
                    _had_tool_failure = any(
                        getattr(s, "tool_failed", False)
                        or "error" in (getattr(s, "observation", "") or "").lower()
                        for s in getattr(trace, "steps", []) or []
                    )
                    # Conversational-turn guard (B-2026-09-15-8): a zero-tool
                    # turn whose user message never implied a tool action (and
                    # wasn't an approval of one already narrated) doesn't get
                    # judged for pending-action narration — same cyber-café
                    # false-positive this gate's sibling block above guards
                    # against ("11:36/12:03/12:20 pure-design discussion" in
                    # the 2026-09-15 transcript research fired this 3 times
                    # on turns where the prose answer WAS the correct
                    # response). Once a tool has actually run this turn, the
                    # turn is no longer purely conversational and the flag is
                    # judged normally regardless of intent — EXCEPT an
                    # explicit "don't implement yet / first analyze" request
                    # (_should_skip_workspace_state) always suppresses: the
                    # user asked for analysis only, so a hedge like "I would
                    # implement X" must never be coerced into execution.
                    _turn_expects_action = not _should_skip_workspace_state(
                        reformulated_message or ""
                    ) and (
                        _tools_ran
                        or (
                            intent != Intent.CHAT
                            and (
                                _message_implies_tool_action(reformulated_message or "")
                                or _message_is_action_approval(reformulated_message or "")
                            )
                        )
                    )
                    _assessment = classify_turn_outcome(
                        has_tool_calls=False,
                        final_text=_ft,
                        tools_ran_this_turn=_tools_ran,
                        is_pending_action_narration=(
                            _turn_expects_action and narrates_pending_action(_ft)
                        ),
                        is_follow_through_failure=(
                            _tools_ran and answer_fails_follow_through(_ft, _had_tool_failure)
                        ),
                        is_punted_requested_part=(
                            _tools_ran and answer_punts_requested_part(_ft)
                        ),
                        is_internal_scaffold_text=answer_is_internal_scaffold(_ft),
                        is_post_evidence_narration=(_tools_ran and narrates_after_evidence(_ft)),
                        is_hedge_after_evidence=(_tools_ran and answer_hedges_after_evidence(_ft)),
                        # When this reply came from an
                        # answer-only call (tool schemas deliberately
                        # withheld), narrating a further action means the
                        # model NEEDS a tool (e.g. a second fetch) — give
                        # the tools back instead of pushing synthesis.
                        tools_withheld=bool(tools_withheld),
                    )
                    logger.info(
                        "[agent.loop] turn outcome=%s recovery=%s (%s)",
                        _assessment.outcome.value, _assessment.recovery.value, _assessment.reason,
                    )
                    if (
                        _assessment.outcome is TurnOutcome.INCOMPLETE
                        and _assessment.recovery is not Recovery.NONE
                        and iteration + 1 < effective_max_iter
                    ):
                        _tag = (
                            "[FORCE-TOOL]"
                            if _assessment.recovery is Recovery.FORCE_TOOL
                            else "[SYNTHESIZE]"
                        )
                        _already = any(
                            isinstance(m, dict)
                            and isinstance(m.get("content", ""), str)
                            and _tag in m["content"]
                            for m in (loop_messages or [])
                        )
                        if not _already:
                            if obs:
                                obs.emit(
                                    "agent_loop_gate_failed_replan",
                                    intent=intent.value,
                                    iteration=iteration + 1,
                                    unmet=[_assessment.reason],
                                )
                            loop_messages.append(
                                {
                                    "role": "user",
                                    "content": (
                                        _stage_card("FORCE-TOOL", "act", _DECISION_FORCE_TOOL, loop_messages, trace)
                                        if _assessment.recovery is Recovery.FORCE_TOOL
                                        else _stage_card("SYNTHESIZE", "answer", _DECISION_ANSWER, loop_messages, trace)
                                    ),
                                }
                            )
                            if (
                                _assessment.recovery is Recovery.FORCE_TOOL
                                and gate_force_tool is not None
                            ):
                                gate_force_tool[0] = True
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
        #
        # Goal-checklist turns: with a harness-derived goal
        # checklist (plan_steps), a turn whose model ran NO tool must NOT be
        # accepted — the user asked for deliverables, there are no tool
        # outcomes to compare, so the criteria are unmet. Falling through to
        # evaluate_criteria yields all-unmet → replan while iterations remain,
        # or the honest-stop report at the cap (live-verified: the model
        # answered "I'll set up the tools needed for file operations." with
        # zero tool calls and the old guard completed the turn with 3/3
        # todos and no files created). The legacy path (no plan_steps) keeps
        # the old accept-on-no-evidence behavior.
        if not any(step.tool_name for step in getattr(trace, "steps", [])):
            if not plan_steps:
                return "", True
            # Zero-tool force. When criteria/plan_steps
            # exist but NO tools have run, the model is narrating instead
            # of acting ("I'll start by checking...", "Let me use the
            # shell tool"). The LLM replan call below just produces MORE
            # planning text without any tool call — a replan loop.
            # Instead: skip the replan, inject a direct nudge, and signal
            # the main loop to force tool_choice="required" on the next
            # iteration so the provider API itself compels a tool call.
            if iteration + 1 < effective_max_iter:
                if obs:
                    obs.emit(
                        "agent_loop_gate_failed_replan",
                        intent=intent.value,
                        iteration=iteration + 1,
                        unmet=["zero tool calls across entire run — model narrating instead of acting"],
                    )
                loop_messages.append(
                    {
                        "role": "user",
                        "content": _stage_card(
                            "ZERO-TOOL", "act", _DECISION_ACT_ZERO, loop_messages, trace
                        ),
                    }
                )
                # Signal the main loop to force tool_choice on next iter
                if gate_force_tool is not None:
                    gate_force_tool[0] = True
                return "", False

        from core.agent.verify import evaluate_criteria, format_gate_results, gate_passed

        results = evaluate_criteria(criteria, trace)
        trace.criteria_results = results
        trace.gate_passed = gate_passed(results)
        # Same-tool replan bound. Consecutive failures on the
        # same tool means the APPROACH is wrong: stop replanning and report
        # honestly instead of looping the same failure (the 480s spiral).
        #
        # Tradeoff: CAP=2 gives the model exactly ONE
        # replan cycle after the first same-tool failure — the gate only fires
        # at the model's "done" claim, so a model that heeds the revised plan
        # (e.g. pivots to find_path) breaks the streak on the next step and is
        # never blocked. Only a model that repeats the same tool after the
        # corrective replan gets stopped. That is precisely the transcript
        # pattern (17 same-tool retries, never pivoting).
        _streak, _streak_tool = same_tool_failure_streak(trace)
        _block_replan = _streak >= _SAME_TOOL_REPLAN_CAP
        # Session fix: also block if total replans exceeded
        _block_replan = _block_replan or gate_replan_count >= _MAX_TOTAL_GATE_REPLANS
        if trace.gate_passed:
            trace.gate_summary = format_gate_results(results)
            # Mandatory post-execution verifier for
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
                # same-tool failure streak hasn't hit its bound.
                unmet = [("(post-execution verifier)", _pe_note)]
                if iteration + 1 < effective_max_iter and not _block_replan:
                    # Notify the orchestrator (same path as
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
                self._emit_honest_stop(criteria, results, obs, plan_steps)
                return f"\n\n{trace.gate_summary}", True
            return f"\n\n{trace.gate_summary}", True

        unmet = [(c, n) for c, passed, n in results if not passed]
        if iteration + 1 < effective_max_iter and not _block_replan:
            # Notify the orchestrator FIRST so its dead
            # replan() method finally runs, its confidence drops, and
            # the orchestrator_replan_* obs events fire for real (to be
            # consumed by the frontend). The orchestrator
            # may also return a clarification_question or a re-route hint.
            _orchestrator_hint = ""
            if orchestrator is not None:
                # Emit the obs events HERE (in the loop) so
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
        self._emit_honest_stop(criteria, results, obs, plan_steps)
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

        # ── Synthesis pipeline (STREAMED) ───────────────────────────────
        # Stream the synthesis token-by-token instead of
        # buffering the whole answer and emitting one burst at the end. The
        # per-turn timeline showed ~51s of dead air then the answer arriving
        # as ONE chunk — an agent-side defect on any model (opencode streams
        # the same work live). The synthesizer now calls on_chunk per token;
        # we run it as a task, drain a queue, and yield StreamChunk live. A
        # correctness guard re-yields the authoritative final answer if
        # post-processing (fabrication filter / timeout-retry / smart-extract
        # fallback) changed it from what streamed.
        _q: asyncio.Queue = asyncio.Queue()

        async def _run_synthesis() -> str:
            def _sink(t: str) -> None:
                _q.put_nowait(("chunk", t))

            _ans = None
            if self._synthesizer.enabled:
                try:
                    from core.models import RiskLevel, ToolResult

                    search_result = ToolResult(
                        content=safe_obs, risk=RiskLevel.LOW, source="web_search",
                    )
                    synthesis = await self._synthesizer.synthesize(
                        tool_results=[search_result],
                        intent=Intent.WEB_SEARCH,
                        user_question=user_question or query,
                        adapter=adapter or self._adapter,
                        on_chunk=_sink,
                    )
                    if synthesis.needs_followup and synthesis.followup_tool == "web_fetch":
                        followup_url = (synthesis.followup_args or {}).get("url", "")
                        if followup_url:
                            logger.info(f"[agent.loop] synthesis requests web_fetch for: {followup_url[:80]}")
                            _q.put_nowait(("status", f"Reading page: {followup_url[:60]}"))
                            fetch_result, fetch_failed, _ = await dispatch_with_retry(
                                Intent.WEB_FETCH, followup_url,
                                allowed_tool_names=allowed_tool_names,
                            )
                            if fetch_result and not fetch_failed:
                                fetch_synthesis = await self._synthesizer.synthesize_combined(
                                    search_result=search_result,
                                    fetch_result=fetch_result,
                                    user_question=user_question or query,
                                    adapter=adapter or self._adapter,
                                    on_chunk=_sink,
                                )
                                _ans = fetch_synthesis.answer
                            else:
                                _ans = synthesis.answer or (
                                    "I found some relevant results but couldn't read the "
                                    "full page content. The search snippets didn't contain "
                                    "enough detail to fully answer your question."
                                )
                        else:
                            _ans = synthesis.answer or (
                                "I found search results but need more detail. "
                                "The search snippets didn't contain enough specific data."
                            )
                    elif synthesis.answer:
                        _ans = synthesis.answer
                    elif synthesis.is_gap_report:
                        _ans = synthesis.answer
                except Exception as e:
                    logger.warning(f"[agent.loop] synthesis failed: {e}")
                    from core.agent.synthesizer import _smart_extract_key_data
                    _ans = _smart_extract_key_data(safe_obs, user_question or query)
            if not _ans:
                from core.agent.synthesizer import _smart_extract_key_data
                _ans = _smart_extract_key_data(safe_obs, user_question or query)
            return _ans

        _task = asyncio.create_task(_run_synthesis())
        _streamed: list[str] = []
        while not _task.done() or not _q.empty():
            try:
                _kind, _payload = await asyncio.wait_for(_q.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            if _kind == "chunk":
                _streamed.append(_payload)
                yield StreamChunk(text=_payload, done=False)
            elif _kind == "status":
                yield StreamChunk(text="", done=False, status=_payload)
        synthesis_answer = _task.result()

        # Correctness guard: if post-processing changed the answer (or nothing
        # streamed — a gap/fallback path with no LLM stream), show the
        # authoritative final answer. In the common case streamed == final and
        # nothing is re-emitted.
        _streamed_text = "".join(_streamed)
        if synthesis_answer and synthesis_answer.strip() != _streamed_text.strip():
            _prefix = "\n\n" if _streamed_text.strip() else ""
            yield StreamChunk(text=_prefix + synthesis_answer, done=False)

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

        The user must see a model-owned acknowledgement and a
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
        # Accumulate the init call's provider usage. On a DIRECT
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
                    # spaces between streamed JSON deltas survive the join —
                    # the trimming variant once collapsed the init
                    # objective + response into spaceless text.
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
                    # For DIRECT (trivial / needs-thought-no-tools)
                    # turns, suppress the acknowledgement AND the understanding.
                    # The reply itself streams immediately, so an ack like
                    # "Hello there!" before "Hi! How can I help you today?" is
                    # a redundant second greeting, and a "respond to a greeting"
                    # thought is pure theater (trivial → just reply, no
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
                    # chain-of-thought, never shown to the user here.
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
                # Record the init prompt size for budget measurement.
                decision.init_prompt_chars = len(prompt)
                decision.usage = dict(usage_acc)
                # Observability: log the mode AND a snippet of the
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
                        # Strip DSML/MiniMax tool-call markup from
                        # planning text too — a model that emits a stray tool
                        # call block here would otherwise leak it into the plan
                        # context and the thinking stream.
                        # Use the whitespace-SAFE stream variant —
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
                # NOTE: same BaseException trap as the dispatcher:
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
                # Read back WHERE THE WRITE LANDED (result_path from the
                # tool's metadata) not the model's raw arg — they diverge on a
                # re-anchored path or a timestamp-renamed document, which used
                # to fail verification for a perfectly good write.
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
                # Count the FILE, not the read-back report.
                # len(content) counts the file_task REPORT ("File: <path> / Size:
                # N bytes" header + preview), so a 19-byte file reported as ~79
                # "chars" and the ~60-char header skewed the truncation heuristic
                # (real content loss could hide under it). file_task now surfaces
                # the real on-disk size in metadata; fall back to the report
                # length only for callers that don't provide it.
                verify_meta = verify_result.metadata or {}
                if "size_bytes" in verify_meta:
                    actual_len = verify_meta["size_bytes"]
                else:
                    actual_len = len(actual_content)

                # Check if the file was written with reasonable content
                # (guard with expected_len > 0 so a deliberately empty write is
                # not reported as a failure).
                if actual_len == 0 and expected_len > 0:
                    return (
                        f"File verification FAILED — '{path}' exists but is empty. "
                        f"Expected {expected_len} chars of content."
                    )

                # Check for significant truncation (>50% content loss)
                if expected_len > 100 and actual_len < expected_len * 0.5:
                    return (
                        f"File verification WARNING — '{path}' may be truncated. "
                        f"Written {actual_len} bytes but expected ~{expected_len} chars. "
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
                # agent); the agent decides based on the actual task.
                return f"file_write confirmed — {actual_len} bytes verified on disk at {path}."

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
    # Trace summarization — for silent-failure fallbacks
    # ------------------------------------------------------------------

    @staticmethod
    def _summarize_trace_for_user(
        trace, observation_log: str, synthesis_failure_reason: Optional[str] = None
    ) -> str:
        """
        Build a user-facing summary of what tools actually ran, for the
        silent-failure fallback path. Returns an empty string if no tools
        ran (so the caller knows there's nothing to summarize).

        Revised per user feedback: the previous version guessed
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

        # The Thinker's analysis (if any) was preserved on
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
        # If a limit was hit, say WHICH one explicitly. The
        # previous fallback guessed "overload" — a wrong
        # diagnosis. The wording now follows the actual
        # break reason (limit_kind) — a wall-clock break is NOT an
        # iteration-cap break, and the remedies differ. When hit_limit is
        # True, the user needs to know: the model didn't fail, the run
        # was stopped by a budget before finishing the task.
        _limit_kind = (getattr(trace, "limit_kind", "") or "").strip()
        if getattr(trace, "hit_limit", False):
            if _limit_kind == "wall_clock":
                lines.insert(0, (
                    f"I ran out of time ({trace.iterations_used} iterations in) "
                    f"before completing the task. This is NOT a model overload or "
                    f"context-overflow issue — the turn hit its time budget. Here's "
                    f"what I managed to do before the cap:"
                ))
            elif _limit_kind == "repetition":
                lines.insert(0, (
                    f"I stopped myself ({trace.iterations_used} iterations in) "
                    f"because I was repeating the same call without new results. "
                    f"This is NOT a model overload — it's a no-progress loop "
                    f"guard. Here's what I did before stopping:"
                ))
            else:
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
        # Tailor the "what to try" advice to the actual cause.
        # If hit_limit is True, the advice is "tell me to continue" or
        # "raise the limit" — NOT "switch to a larger model" (the model
        # didn't fail, the run was stopped by a budget). The
        # advice now names the budget that actually bound (steps vs time
        # vs the repetition guard).
        if getattr(trace, "hit_limit", False):
            if _limit_kind == "wall_clock":
                lines.append(
                    "What to try next:\n"
                    "  • Tell me to \"continue\" — I'll pick up where I left off\n"
                    "    and finish the remaining steps.\n"
                    "  • Or split the task into smaller turns so each fits\n"
                    "    the time budget.\n"
                    "  • The time budget is configurable via the\n"
                    "    LOCALMIND_MAX_WALL_CLOCK_SECS env var (default: 180)."
                )
            elif _limit_kind == "repetition":
                lines.append(
                    "What to try next:\n"
                    "  • Rephrase the request with more specifics (a fuller\n"
                    "    name, path, or clearer target) so the search doesn't\n"
                    "    repeat the same failing query.\n"
                    "  • Or ask me to do one step at a time."
                )
            else:
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
    # Deterministic evidence extraction (ZERO LLM calls)
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

        The user's insight: "the thinking text
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
        # Handoff agent-followthrough-persistence (live glm-5.3-flash, free
        # tier): after the empty-response budget exhausted, the extractor
        # pulled 124 chars of SCAFFOLD prose from the reasoning buffer
        # ("However, the instruction is emphatic: 'Do NOT call another
        # tool.'...") and served it as the final answer. A scaffold fragment
        # is not an answer — reject it and let later strategies / the clean
        # fallback speak (silent-failure contract: always yield SOMETHING,
        # but it must be meaningful).
        if reasoning_buffer and reasoning_buffer.strip():
            extracted = self._extract_answer_sentence(reasoning_buffer, user_message)
            if extracted and answer_is_internal_scaffold(extracted):
                logger.info(
                    "[agent.loop] reasoning-buffer extraction rejected internal scaffolding (%d chars)",
                    len(extracted),
                )
                extracted = ""
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

        The old fallback dumped raw harness
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
            # Build a simple evidence summary instead of
            # telling the user to "check the Actions panel"
            _evidence_lines = []
            for s in (trace.steps if trace else []):
                _obs = getattr(s, "observation", "") or ""
                if _obs and len(_obs.strip()) > 20:
                    _evidence_lines.append(_obs.strip()[:400])
            if _evidence_lines:
                return (
                    "Here's what I found:\n\n"
                    + "\n\n---\n\n".join(_evidence_lines[:3])
                    + "\n\n(I had trouble generating a clean summary — "
                      "the raw evidence above is from the tools I ran.)"
                )
            return (
                "I found the information you asked for, but I'm having "
                "trouble putting it into a clean final answer right now. "
                "Please try again and I'll retry."
            )
        if observation_log.strip():
            return (
                "I ran some tools but couldn't produce a final answer. "
                "Please try again, or rephrase your question."
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
        """Deterministic post-loop synthesis when tools ran
        but the model produced no usable final text.

        This is the LAST safety net before the empty-response fallback. It
        fires when:
        - at least one tool ran this turn (``trace.steps`` has a tool_name), AND
        - the final text is empty or trivially short.

        Unlike the synthesis-from-reasoning rescue (which
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
        """Rescue a heading-only final answer on NORMAL completion.

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

        Per user feedback, this now accepts an optional `trace` parameter so the
        empty-stream fallback can surface ACTUAL tool inputs/outputs
        instead of guessing "overload" (the overload
        diagnosis was unverified and likely wrong for small tasks).

        The `framing` parameter selects the directive text — "limit" for the
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
        # Track whether the model produced ANY non-empty text.
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
                    _merge_call_usage(_provider_usage, chunk.usage)
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
                # Strip DSML/MiniMax tool-call markup from the
                # final synthesis too — the browser-validated run leaked a raw
                # <｜DSML｜tool_calls> block into the answer because the rescue
                # path (framing='final') only ran the system-leak filter. The
                # model sometimes emits a tool call as plain text here even
                # though plain chat has no tools.
                # Use the STREAM variant — the trimming variant
                # ends with .strip(), which on a per-chunk basis eats the
                # boundary space between every delta and welds the synthesis
                # into spaceless text ("HereHere arethe", "storiesIfound").
                filtered_text = _strip_minimax_tool_calls_stream(filtered_text)
                if filtered_text:
                    _any_text_yielded = True
                    _final_text_parts.append(filtered_text)
                # Forward the model's reasoning in the
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
        # If the synthesis mimicked the internal evidence-recap format (the
        # observation log can echo it from polluted history), drop the block:
        # the deterministic renderer below stays the only author, and the
        # evidence check evaluates the clean answer.
        _clean_final = strip_worker_reports(_final_text)
        if _clean_final != _final_text:
            _final_text = _clean_final
            _seen_text = False
            _rebuilt_chunks: list[StreamChunk] = []
            for _chunk in _final_chunks:
                if _chunk.text:
                    if not _seen_text:
                        _rebuilt_chunks.append(
                            StreamChunk(
                                text=_final_text,
                                thinking=_chunk.thinking,
                                done=False,
                                usage=_chunk.usage,
                            )
                        )
                        _seen_text = True
                    # Subsequent text chunks carried the mimicked block — drop.
                else:
                    _rebuilt_chunks.append(_chunk)
            _final_chunks = _rebuilt_chunks
        # Record that the rescue produced a REAL model answer
        # (not a deterministic fallback) so post-loop failure classification
        # can tell a rescued turn from a failed one — a capped run whose
        # synthesis delivered is not a failure (the "find my CV" false
        # banner). The deterministic fallbacks below (exception / empty
        # stream) deliberately do NOT set final_response: those turns are
        # still failures worth remembering in failure memory.
        if _any_text_yielded and trace is not None and not getattr(trace, "final_response", ""):
            trace.final_response = _final_text.strip()
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

        # Revised per user feedback: if the model returned an
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
                # The rescue caller owns the empty case — it
                # renders the deterministic worker report itself.
                logger.info(
                    "[agent.loop] final synthesis empty — caller handles fallback"
                )
                return
            logger.warning(
                "[agent.loop] final synthesis produced no text — "
                "yielding evidence-based fallback (model returned empty stream)"
            )
            # FIRST try deterministic evidence
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
            # Before dumping raw tool calls to
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
            # The old fallback dumped raw harness internals
            # ("I ran the requested tools but couldn't synthesize... What to
            # try next: Check the outputs above") which reads as developer
            # debug output, not a user answer. The new fallback is honest +
            # concise: it says what was attempted and points the user at the
            # Actions panel (where the tool evidence already lives).
            _tool_count = sum(1 for s in (trace.steps if trace else []) if s.tool_name)
            if _tool_count > 0:
                # Build evidence summary instead of "check Actions panel"
                _evidence_lines = []
                for s in (trace.steps if trace else []):
                    _obs = getattr(s, "observation", "") or ""
                    if _obs and len(_obs.strip()) > 20:
                        _evidence_lines.append(_obs.strip()[:400])
                if _evidence_lines:
                    _summary = (
                        "Here's what I found:\n\n"
                        + "\n\n---\n\n".join(_evidence_lines[:3])
                        + "\n\n(I had trouble generating a clean summary — "
                          "the raw evidence above is from the tools I ran.)"
                    )
                else:
                    _summary = (
                        "I found the information you asked for, but I'm having "
                        "trouble putting it into a clean final answer right now. "
                        "Please try again and I'll retry."
                    )
                yield StreamChunk(
                    text=_summary,
                    done=True,
                    usage=dict(_provider_usage),
                )
            elif observation_log.strip():
                yield StreamChunk(
                    text=(
                        "I ran some tools but couldn't produce a final answer. "
                        "Please try again, or rephrase your question."
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
