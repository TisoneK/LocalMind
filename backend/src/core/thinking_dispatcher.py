"""
ThinkingDispatcher — sole capability-based orchestration dispatcher for LocalMind.

v4.0 — Consolidated single-source dispatcher
═══════════════════════════════════════════════════════════════════════

This module is the CANONICAL Layer 2 of the 6-layer pipeline.
It replaces both the previous ThinkingDispatcher (v3) and the
CapabilityOrchestrator (which was a parallel/alternate implementation
that was never wired into engine.py).

Capabilities:
  1. Signal detection — structural fast-paths without LLM call
  2. Follow-up detection — short contextual messages inherit prior intent
  3. LLM-based capability inference — single LLM call produces TaskProfile
  4. Real-time thinking token streaming to the frontend
  5. ExecutionGraph construction from LLM output
  6. Fallback to minimal TaskProfile on timeout/error
  7. System leak filtering on LLM output

Removed in v4.0:
  - CapabilityOrchestrator (consolidated into this module)
  - Lazy imports of execution_graph (now top-level)
  - capability.py re-export layer (deleted)

Architecture:
  Input → Signal Detection → Follow-up Detection → LLM Inference → OrchestrationPlan
                                                                          ├── TaskProfile
                                                                          └── ExecutionGraph
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import AsyncIterator, Optional, Union

from core.cache import TTLCache
from core.execution_graph import ExecutionGraph, build_graph_from_plan_steps
from core.file_ops import detect_read_request
from core.filters import _filter_system_leaks
from core.models import (
    Capability,
    ExecutionMode,
    Intent,
    OrchestrationPlan,
    SafetyLevel,
    StreamChunk,
    TaskProfile,
)
from core.obs import ObsCollector

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────

DISPATCHER_TIMEOUT_SECS: float = 45.0  # was 10.0 (GLM/Z.ai 18s typical) → 30.0. Session 133:
# free-tier providers now run 20-40s/call, so 30s fired constant dispatcher
# timeouts → fallback CHAT plans (tool requests misrouted as conversation).
# 45s matches PER_CALL_TIMEOUT_SECS: a slow-but-productive classification gets
# its chance; the fallback fires only after 45s of true silence.
DISPATCHER_TEMPERATURE: float = 0.2
MAX_HISTORY_FOR_PROMPT: int = 6

# ── Dispatcher result cache (Session 135) ────────────────────────────────
# Repeated/near-duplicate requests (same normalized message + same recent
# intent-history context) reuse the previous routing decision and SKIP the
# capability-inference LLM call entirely. Safe because the plan is only a
# ROUTING decision (intent + capabilities + execution mode + reformulated
# query) — the agent loop still executes tools fresh on every turn, so
# caching the route never serves stale tool data (realtime-sensitive plans
# still run their web_search/file_read live).
#
# The cache is MODULE-LEVEL (a shared TTLCache instance) because the engine
# constructs a fresh ThinkingDispatcher per request; without a shared store
# every request would start cold. Plans are deep-copied on read so engine
# mutations (auto_correct / execution-mode derivation) never corrupt the
# cached entry.
_PLAN_CACHE: "TTLCache[OrchestrationPlan]" = TTLCache(
    ttl_seconds=300.0,  # 5 min — long enough for retries/follow-ups, short enough to drift
    max_entries=64,
    copier=lambda plan: plan.model_copy(deep=True),
)
# Only plans at/above this confidence are cached. Sits safely above the
# fallback floor (0.3) so a parsed-but-garbage routing decision can never
# be served to a repeat request.
_PLAN_CACHE_MIN_CONFIDENCE: float = 0.35


def _normalize_message_for_cache(message: str) -> str:
    """Lowercase + collapse whitespace + strip punctuation for cache keying.

    Turns "Check git status!!" and "check  git status" into the same key
    so near-duplicate phrasings reuse the plan instead of re-classifying.
    """
    text = re.sub(r"\s+", " ", (message or "").strip().lower())
    return text.strip(" .,!?;:'\"").strip()


def _dispatcher_cache_key(
    message: str,
    intent_history: Optional[list[str]],
    has_attachment: bool,
) -> tuple:
    """Cache key: normalized message + recent intent-history signature.

    Intent history is the disambiguator the user asked for: the same words
    after a SHELL task vs after a CHAT turn can legitimately route
    differently, so the key must capture which intents preceded this
    message. Attachment presence also changes routing (file upload).
    """
    history_sig = tuple((intent_history or [])[-MAX_HISTORY_FOR_PROMPT:])
    return (_normalize_message_for_cache(message), history_sig, has_attachment)


def _store_plan(key: tuple, plan: "OrchestrationPlan") -> None:
    """Store a plan, enforcing the "only quality plans cached" invariant.

    Plans below _PLAN_CACHE_MIN_CONFIDENCE (fallback floor is 0.3) are
    rejected so a garbage routing decision can never be served to a repeat
    request. TTL + bounded eviction + deep-copy-on-read are handled by the
    shared TTLCache (reads go straight through ``_PLAN_CACHE.get``).
    """
    if plan.profile.confidence < _PLAN_CACHE_MIN_CONFIDENCE:
        return
    _PLAN_CACHE.set(key, plan)

# Signal detection: only intercept truly unambiguous one-way signals.
# These produce TaskProfile objects without an LLM call, saving 2-5s.
# IMPORTANT: Fast-paths do NOT route to CHAT.
_SHELL_PREFIXES = (
    "ls ",
    "ls\t",
    "dir ",
    "dir\t",
    "pwd",
    "cat ",
    "cat\t",
    "echo ",
    "cd ",
    "mkdir ",
    "rm ",
    "cp ",
    "mv ",
    "grep ",
    "find ",
    "chmod ",
    "chown ",
    "pip install ",
    "npm install ",
    "git ",
    "python ",
    "node ",
)

_EXACT_SYSINFO_PHRASES = {
    "what time is it",
    "what's the time",
    "whats the time",
    "what time is it now",
    "current time",
    "what's the date",
    "whats the date",
    "what is the date",
    "what day is it",
    "what's today's date",
    "whats todays date",
}

_URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)

# Follow-up detection — short messages that inherit context
_FOLLOW_UP_PATTERNS = re.compile(
    r"^(yes|yeah|yep|sure|ok|okay|go ahead|do it|read it|read it now|"
    r"please|proceed|confirm|continue|show me|open it|check it|"
    r"try again|retry|again|run it|"
    r"did you\?|have you\?|were you\?|is it\?|can you\?)\s*[.!?]*$",
    re.IGNORECASE,
)

# Intent → display label mapping for structured dispatch steps.
_INTENT_STEP_LABELS: dict[str, str] = {
    "chat": "Chat",
    "web_search": "Web Search",
    "web_fetch": "Fetch URL",
    "code_exec": "Execute Code",
    "shell": "Run Command",
    "file_task": "Read File",
    "file_write": "Write File",
    "file_edit": "Edit File",
    "sysinfo": "System Info",
    "observe": "Observe",
    "calculate": "Calculate",
    "csv": "CSV",
    "json": "JSON",
    "sql": "SQL",
    "memory_op": "Memory",
}


# ── Helper: Build dispatch steps ─────────────────────────────────────────────


def _build_dispatch_steps(
    intent: Intent,
    message: str,
    reformulated: str,
    profile: Optional[TaskProfile] = None,
) -> list[dict]:
    """Build deterministic, user-facing dispatch steps from the routing decision."""
    steps = []
    intent_val = intent.value

    label = _INTENT_STEP_LABELS.get(intent_val, intent_val.replace("_", " ").title())
    steps.append({"intent": intent_val, "label": label, "detail": reformulated[:120]})

    if profile is not None:
        if profile.realtime_sensitive:
            steps.append(
                {
                    "intent": "capability",
                    "label": "Live Data",
                    "detail": "Requires current data — will not use cached/training data",
                }
            )
        tools = profile.required_tools()
        if tools:
            tool_names = ", ".join(t.replace("_", " ").title() for t in tools)
            steps.append({"intent": "tools", "label": "Tools", "detail": tool_names})
        if profile.execution_mode not in (ExecutionMode.DIRECT, ExecutionMode.SINGLE_TOOL):
            mode_label = profile.execution_mode.value.replace("_", " ").title()
            steps.append({"intent": "execution", "label": "Execution", "detail": f"{mode_label} workflow"})

    msg_lower = message.lower().strip()
    if msg_lower in ("yes", "yeah", "yep", "sure", "ok", "okay", "go ahead", "proceed", "continue"):
        steps.append(
            {
                "intent": "followup",
                "label": "Follow-up",
                "detail": f"Continuing previous request: {reformulated[:80]}",
            }
        )

    return steps


# ── Capability inference system prompt ────────────────────────────────────────

_CAPABILITY_INFERENCE_SYSTEM = """\
You are LocalMind's capability inference engine. Your job is to analyze a user message and determine WHAT CAPABILITIES are needed to fulfill it — not just classify it into a single bucket.

HOW TO THINK (reason before you classify):
Before outputting the JSON, think about the request like a person would:
- What is the user ACTUALLY trying to accomplish? (not just what words they used)
- What do you already know that's relevant?
- What information is missing that you'd need to find?
- If a human expert got this request, what would they do first?
- Are there multiple steps needed, or is this a single action?
Write your reasoning naturally — don't follow a fixed checklist. Engage with the specific substance of the request. Then, based on that understanding, output the JSON.

AVAILABLE CAPABILITIES:
- web_search: Search the web for current/live information (sports, news, weather, prices, events)
- web_fetch: Fetch and read a specific URL
- code_exec: Execute Python code
- shell: Run system commands, browse directories
- file_read: Read file contents
- file_write: Create/overwrite a file
- file_edit: Edit an existing file in-place
- memory_store: Store a persistent fact for later recall
- memory_retrieve: Recall stored facts from memory
- sysinfo: Get system info (current time, date, hardware specs, installed programs)
- observe: Observe the desktop right now (active window, clipboard, running apps, CPU/RAM/disk/battery, recently modified files)
- calculate: Evaluate a safe arithmetic expression exactly (percentages, formulas)
- csv: Read a CSV file into a compact bounded table
- json: Parse local JSON (file or inline) with optional dot-path queries
- sql: Run read-only SQLite SELECT queries against a local database
- reasoning: Deep analysis, logical deduction, evaluation
- synthesis: Combine information from multiple sources into coherent output
- planning: Multi-step task decomposition and sequencing
- comparison: Compare options, data, or alternatives
- prediction: Forecast, predict, or estimate future outcomes

CAPABILITY FLAGS:
- requires_grounding: Needs real external data (web search, file read, system info)
- requires_tools: Needs tool execution (shell, code_exec, file_write, etc.)
- requires_planning: Needs multi-step planning before execution
- requires_memory: Needs memory retrieval or storage
- requires_reasoning: Needs analytical reasoning
- requires_execution: Needs code/shell execution
- requires_file_access: Needs file read/write
- realtime_sensitive: Data MUST be current — weather, sports, prices, news

EXECUTION MODES:
- direct: Pure conversation, no tools needed
- single_tool: One tool call, no orchestration
- multi_tool: Multiple tools, may be parallelizable
- agent_loop: Plan→Execute→Verify workflow for complex tasks
- multi_phase: Very complex — needs multi-phase planning with dependencies

CRITICAL RULES:
1. Follow-ups ("yes", "go ahead", "try again") refer to the previous message — use history.
2. Live/current info (weather, sports, prices, news) → ALWAYS web_search + realtime_sensitive=true
   - "Today's", "latest", "current", "recent" are signals for live data
   - INDIRECT requests count too: "Should I carry an umbrella?" → needs weather data → web_search
   - "Is it a good day for a picnic?" → needs weather data → web_search
   - "Will my flight be on time?" → needs flight data → web_search
   - Interpret WHAT THE USER NEEDS, not just what they literally said
3. Time/date queries → sysinfo only (NOT web_search)
   - "What time is it", "what's the date", "what day is it"
4. System specification queries → sysinfo only
   - "How much RAM", "CPU specs", "disk space", "installed programs"
5. Browse/list directories → shell (NOT code_exec)
6. A query can need MULTIPLE capabilities:
   - "Search for X and save to file" → web_search + file_write
   - "Compare my specs with requirements" → sysinfo + web_search + comparison
   - "Summarize this PDF and fact-check it" → file_read + web_search + synthesis
7. When unsure about a capability, INCLUDE it — the execution layer will skip it if unneeded.
8. NEVER set execution_mode=direct when live/external data is needed.
9. The reformulated_query should be the ACTUAL query to search/execute — NOT the user's
   raw message. "Should I carry an umbrella in Kitengela?" → reformulated_query should be
   "Kitengela weather today rain forecast" — the optimal query for getting the data the
   user needs, not a literal copy of their question.

Reply with ONLY valid JSON:
{"capabilities":["cap1","cap2"],"flags":{"requires_grounding":false,"requires_tools":false,"requires_planning":false,"requires_memory":false,"requires_reasoning":false,"requires_execution":false,"requires_file_access":false,"realtime_sensitive":false},"execution_mode":"direct","safety_level":"low","confidence":0.85,"primary_domain":"","reformulated_query":"the optimal query for getting the data the user needs — NOT their raw message","acknowledgement":"brief 1-sentence acknowledgement","execution_plan":{"steps":[{"id":"step_id","capability":"cap_name","tool":"tool_name","args":{},"depends_on":[],"label":"Human-readable step description"}],"success_criteria":["2-4 CONCRETE checkable statements that prove success"],"task_type":"debug|plan|code|research|chat|verify"}}

CRITICAL RULE — task_type (ADR-19 task-aware context):
- OPTIONAL. Set it ONLY when the task clearly maps to one of: debug
  (fixing/finding a failure), plan (design/requirements), code (writing or
  editing implementation), research (gathering sources/facts), verify
  (running tests/checks to confirm), chat (general conversation).
- When unset or ambiguous, omit it entirely — the engine falls back to
  the legacy positional context behavior (no task-aware compaction).
- It only controls WHICH tool results/history stay verbatim in context —
  never the routing or the tools.

CRITICAL RULE — success_criteria (ADR-18 P0 acceptance gate):
- Write 2-4 CONCRETE, CHECKABLE statements that prove the task succeeded:
  a command that passes ("pytest passes"), a file that exists with content
  ("hello.py exists with content"), a git-diff outcome ("git diff contains
  hello.py"), an HTTP status ("the endpoint returns 200"), or the absence of
  error output ("no errors in the build output").
- ONE criterion per checkable statement. Never vague/subjective ("works well",
  "looks good", "make it nice") — the acceptance gate checks these
  deterministically against tool evidence.
- Omit success_criteria entirely for pure chat/trivial requests (no contract).
"""  # noqa: E501


# ── ThinkingDispatcher ────────────────────────────────────────────────────────


class ThinkingDispatcher:
    """
    Capability-based orchestrating dispatcher — the sole Layer 2 implementation.

    Yields OrchestrationPlan objects (TaskProfile + ExecutionGraph).
    The engine.py consumes these plans directly in the 6-layer pipeline.

    The dispatcher is the PRIMARY routing mechanism. It does NOT fall
    back to any regex classifier. On failure, it falls back to a minimal
    TaskProfile with low confidence.

    Usage in engine.py:
        async for output in dispatcher.dispatch(...):
            if isinstance(output, StreamChunk):
                yield output
            elif isinstance(output, OrchestrationPlan):
                plan = output
                # Use plan.profile, plan.graph, etc.
    """

    def __init__(self, base_adapter):
        self._base_adapter = base_adapter
        self._adapter = None
        try:
            from adapters import get_adapter
            from core.config import settings

            fast_model = getattr(settings, "ollama_model_fast", "") or ""
            if fast_model and fast_model != settings.ollama_model:
                self._adapter = get_adapter(settings.localmind_adapter, model_override=fast_model)
            else:
                self._adapter = base_adapter
        except Exception:
            self._adapter = base_adapter

    async def dispatch(
        self,
        message: str,
        history: list,
        memory_facts: list[str],
        has_attachment: bool,
        obs: ObsCollector,
        session_id: str = "",
        attachment_filename: Optional[str] = None,
        intent_history: Optional[list[str]] = None,
    ) -> AsyncIterator[Union[StreamChunk, OrchestrationPlan]]:
        """
        Infer capabilities and return an OrchestrationPlan.

        Steps:
          0. Check the module-level plan cache (Session 135) — a repeat of
             a normalized message with the same recent intent-history
             context reuses the previous routing decision and SKIPS the
             LLM call entirely (safe: only the route is cached, tools still
             execute fresh).
          1. Check signal detection for truly unambiguous signals.
          2. Check follow-up detection for short contextual messages.
          3. Build context from history + memory.
          4. Call the LLM with capability inference prompt.
          5. Stream thinking tokens to the frontend IN REAL-TIME.
          6. Parse the structured JSON output into OrchestrationPlan.
          7. Build ExecutionGraph from plan steps.

        Args:
            intent_history: Optional rolling window of this session's prior
                intent values (most recent last). Part of the cache key —
                the same words after a SHELL task vs after a CHAT turn may
                route differently, so the key must capture the preceding
                routing context. The engine passes its per-session
                intent-history list.

        Yields:
            StreamChunk — thinking tokens streamed in real-time
            OrchestrationPlan — the final plan with profile + graph
        """
        t0 = time.monotonic()

        # ── 1. Signal detection for truly unambiguous signals ────────────
        signal_plan = self._try_signal_detection(message, has_attachment, attachment_filename)
        if signal_plan:
            obs.emit(
                "dispatcher_signal_detected",
                intent=signal_plan.profile.primary_intent().value,
                execution_mode=signal_plan.profile.execution_mode.value,
                message_preview=message[:60],
            )
            logger.info(
                "[dispatcher] signal: %s/%s for %r",
                signal_plan.profile.primary_intent().value,
                signal_plan.profile.execution_mode.value,
                message[:40],
            )
            if signal_plan.profile.acknowledgement:
                yield StreamChunk(
                    text="",
                    status=signal_plan.profile.acknowledgement,
                    dispatch_steps=signal_plan.dispatch_steps,
                )
            yield signal_plan
            return

        # ── 1b. Follow-up detection for short contextual messages ────────
        if _FOLLOW_UP_PATTERNS.match(message.strip()) and history:
            followup_plan = self._try_followup_plan(message, history, obs)
            if followup_plan:
                obs.emit(
                    "dispatcher_followup",
                    intent=followup_plan.profile.primary_intent().value,
                    message_preview=message[:60],
                    inherited_from="previous_turn",
                )
                logger.info(
                    "[dispatcher] follow-up: %s for %r",
                    followup_plan.profile.primary_intent().value,
                    message[:40],
                )
                yield StreamChunk(text="", thinking="start")
                yield StreamChunk(
                    text="",
                    thinking=followup_plan.profile.acknowledgement or "Following up on your previous request.",
                )
                yield StreamChunk(text="", thinking="end")
                yield followup_plan
                return

        # ── 1c. Plan cache — repeated/near-duplicate requests skip the LLM ──
        # Session 135: the previous routing decision is safe to reuse because
        # it only decides HOW to route (intent/capabilities/reformulation) —
        # the agent loop executes tools fresh on every turn, so cached routes
        # never serve stale tool data. Emit the same obs events the normal
        # path emits (intent_classified / dispatcher_complete) so the Observe
        # panel and the engine's downstream reads behave identically.
        _cache_key = _dispatcher_cache_key(message, intent_history, has_attachment)
        _cached = _PLAN_CACHE.get(_cache_key)
        if _cached is not None:
            _cached_intent = _cached.profile.primary_intent().value
            logger.info(
                "[dispatcher] cache hit for %r (intent=%s) — skipping LLM call",
                message[:50],
                _cached_intent,
            )
            obs.emit(
                "dispatcher_cache_hit",
                intent=_cached_intent,
                message_preview=message[:60],
            )
            obs.emit(
                "intent_classified",
                primary=_cached_intent,
                confidence=round(_cached.profile.confidence, 2),
            )
            obs.emit(
                "dispatcher_complete",
                intent=_cached_intent,
                execution_mode=_cached.profile.execution_mode.value,
                confidence=round(_cached.profile.confidence, 2),
                latency_ms=0,
                capabilities=[c.value for c in _cached.profile.capabilities],
                cached=True,
                session_id=session_id[:8] if session_id else "",
            )
            if _cached.profile.acknowledgement:
                yield StreamChunk(
                    text="",
                    status=_cached.profile.acknowledgement,
                    dispatch_steps=_cached.dispatch_steps,
                )
            yield _cached
            return

        # ── 2. Build context from history ────────────────────────────────
        history_text = self._format_history(history)
        memory_text = self._format_memory(memory_facts)

        user_content = (
            f"CONVERSATION HISTORY (most recent last):\n{history_text}\n\n"
            f"MEMORY FACTS:\n{memory_text}\n\n"
            f"has_attachment={str(has_attachment).lower()}\n"
            f"CURRENT USER MESSAGE: {message}"
        )

        messages = [
            {"role": "system", "content": _CAPABILITY_INFERENCE_SYSTEM},
            {"role": "user", "content": user_content},
        ]

        # ── 3. Stream from LLM — emit thinking in real-time ─────────────
        # Session 115 + 132: DO NOT emit intent="dispatch" here. It is an
        # internal routing marker, not a classified intent — the Observe panel
        # rendered it verbatim (with no confidence) whenever the dispatcher
        # failed before intent_classified fired. At this point the real intent
        # is not known yet; the panel falls back to its previous/chat value
        # until intent_classified (or the engine's own intent event) lands.
        obs.emit("thinking_start")
        yield StreamChunk(text="", thinking="start")

        raw_chunks: list[str] = []
        _in_json = False
        _brace_depth = 0
        _thinking_buffer: list[str] = []
        _json_buffer: list[str] = []

        try:
            # Use a queue to stream thinking tokens in real-time while
            # collecting the JSON output. This avoids the async generator
            # + asyncio.wait_for incompatibility.
            _thinking_queue: asyncio.Queue = asyncio.Queue()
            _SENTINEL = object()

            async def _stream_and_collect():
                nonlocal _in_json, _brace_depth
                try:
                    async for chunk in self._adapter.chat(
                        messages,
                        temperature=DISPATCHER_TEMPERATURE,
                        intent="chat",
                    ):
                        # If the adapter returned an error, stop collecting —
                        # the dispatcher will fall back to a minimal plan, and
                        # the subsequent chat-phase call will surface the error
                        # to the user via the SSE bridge.
                        if chunk.error:
                            logger.warning(
                                "[dispatcher] adapter error during capability inference: %s",
                                chunk.error[:120],
                            )
                            break
                        text = _filter_system_leaks(chunk.text)
                        if not text:
                            continue
                        raw_chunks.append(text)
                        if not _in_json:
                            brace_idx = text.find("{")
                            if brace_idx >= 0:
                                pre_brace = text[:brace_idx]
                                if pre_brace.strip():
                                    _thinking_buffer.append(pre_brace)
                                    await _thinking_queue.put(pre_brace)
                                _in_json = True
                                _brace_depth = 1
                                json_part = text[brace_idx + 1 :]
                                if json_part:
                                    _json_buffer.append(json_part)
                                for ch in json_part:
                                    if ch == "{":
                                        _brace_depth += 1
                                    elif ch == "}":
                                        _brace_depth -= 1
                            else:
                                _thinking_buffer.append(text)
                                await _thinking_queue.put(text)
                        else:
                            _json_buffer.append(text)
                            for ch in text:
                                if ch == "{":
                                    _brace_depth += 1
                                elif ch == "}":
                                    _brace_depth -= 1
                finally:
                    await _thinking_queue.put(_SENTINEL)

            # Start the collection task
            _collect_task = asyncio.create_task(_stream_and_collect())

            # Stream thinking tokens in real-time with timeout
            try:
                while True:
                    try:
                        item = await asyncio.wait_for(
                            _thinking_queue.get(),
                            timeout=DISPATCHER_TIMEOUT_SECS,
                        )
                    except asyncio.TimeoutError:
                        _collect_task.cancel()
                        logger.warning("[dispatcher] timed out — falling back")
                        break
                    if item is _SENTINEL:
                        break
                    yield StreamChunk(text="", thinking=item)
                # Ensure the task completes — but don't hang if it already
                # finished or errored. Use a short timeout.
                # NOTE: CancelledError is a BaseException in py3.8+ — a bare
                # `await asyncio.wait_for(_collect_task, timeout=5)` on a task
                # cancelled by the timeout path above raises CancelledError,
                # which `except (TimeoutError, Exception)` does NOT catch. It
                # would escape and kill the whole request instead of falling
                # back to the minimal plan (the free-tier overload case).
                # gather(return_exceptions=True) absorbs the child's
                # CancelledError as a RESULT deterministically (no reliance on
                # the racy task.cancelled() flag).
                try:
                    await asyncio.wait_for(
                        asyncio.gather(_collect_task, return_exceptions=True),
                        timeout=5,
                    )
                except Exception:
                    _collect_task.cancel()
            except asyncio.CancelledError:
                # The dispatcher generator itself is being cancelled externally
                # (client abort / engine shutdown). Cancel the child collect
                # task so it doesn't dangle, then propagate cleanly — a real
                # cancellation must NOT be swallowed by the fallback below.
                _collect_task.cancel()
                raise
            except Exception:
                _collect_task.cancel()
                raise

        except asyncio.TimeoutError:
            logger.warning("[dispatcher] timed out — falling back to minimal profile")
            obs.emit("dispatcher_timeout", timeout=DISPATCHER_TIMEOUT_SECS)
            yield StreamChunk(text="", thinking="end")
            yield self._fallback_plan(message, has_attachment, history)
            return
        except Exception as e:
            logger.warning("[dispatcher] error (%s) — falling back to minimal profile", e)
            obs.emit("dispatcher_error", error=str(e)[:80])
            yield StreamChunk(text="", thinking="end")
            yield self._fallback_plan(message, has_attachment, history)
            return

        raw = "".join(raw_chunks).strip()
        raw_json = "".join(_json_buffer)
        if not raw_json.strip() or _brace_depth > 0:
            raw_json = raw

        # ── 4. Parse JSON output ────────────────────────────────────────
        data = None
        try:
            clean = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
            clean = re.sub(r"\s*```$", "", clean)
            data = json.loads(clean)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]+\}", raw)
            if match:
                try:
                    data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    logger.warning("[dispatcher] JSON parse failed — using minimal profile")
                    yield StreamChunk(text="", thinking="end")
                    yield self._fallback_plan(message, has_attachment, history)
                    return
            else:
                logger.warning("[dispatcher] no JSON found in response — using minimal profile")
                yield StreamChunk(text="", thinking="end")
                yield self._fallback_plan(message, has_attachment, history)
                return

        # ── 5. Build OrchestrationPlan from parsed data ─────────────────
        plan = self._parse_llm_output(data, message, has_attachment, history)

        # Stream the dispatch steps as thinking tokens
        yield StreamChunk(text="", thinking="end")
        yield StreamChunk(text="", thinking="start", dispatch_steps=[])
        for step in plan.dispatch_steps:
            yield StreamChunk(
                text="",
                thinking=f"[{step.get('label', step.get('intent', ''))}] {step.get('detail', '')}",
                dispatch_steps=[],
            )
        yield StreamChunk(text="", thinking="end", dispatch_steps=[])
        # Session 115: 'dispatch' is an internal routing marker, NOT a
        # classified intent. Emitting it as `intent` made the Observe panel
        # show "dispatch" (with no confidence) and clobber the real
        # classification. The real intent arrives via the intent_classified /
        # dispatcher_complete events that follow — drop the placeholder field.
        obs.emit("thinking_done")

        latency_ms = round((time.monotonic() - t0) * 1000)
        # Emit intent_classified so the SSE bridge sends an 'intent' event
        # to the frontend — this populates the Observe tab's intent display
        # and confidence bar in real-time, BEFORE the response is generated.
        obs.emit(
            "intent_classified",
            primary=plan.profile.primary_intent().value,
            confidence=round(plan.profile.confidence, 2),
        )
        obs.emit(
            "dispatcher_complete",
            intent=plan.profile.primary_intent().value,
            execution_mode=plan.profile.execution_mode.value,
            confidence=round(plan.profile.confidence, 2),
            latency_ms=latency_ms,
            capabilities=[c.value for c in plan.profile.capabilities],
            session_id=session_id[:8] if session_id else "",
        )

        logger.info(
            "[dispatcher] intent=%s mode=%s conf=%.2f latency=%dms capabilities=%s reformulated=%r",
            plan.profile.primary_intent().value,
            plan.profile.execution_mode.value,
            plan.profile.confidence,
            latency_ms,
            [c.value for c in plan.profile.capabilities],
            plan.profile.reformulated[:60],
        )

        # Session 135: store the routing plan for repeated/near-duplicate
        # requests. Only REAL LLM-produced plans — fallback plans
        # (timeout/error) return earlier and never reach here, and _store_plan
        # itself rejects low-confidence (garbage) plans.
        _store_plan(_cache_key, plan)

        yield plan

    # ── Signal Detection (structural only, no semantic regex) ────────────

    def _try_signal_detection(
        self,
        message: str,
        has_attachment: bool,
        attachment_filename: Optional[str] = None,
    ) -> Optional[OrchestrationPlan]:
        """Detect unambiguous structural signals.

        Only signals with exactly ONE valid interpretation are detected.
        All semantic classification goes through the LLM.

        Detected signals:
          - URL present → WEB_FETCH
          - File attachment → FILE_READ
          - Exact time/date query → SYSINFO
          - Shell command prefix → SHELL
        """
        msg = message.strip()
        msg_lower = msg.lower()

        # URL detection → WEB_FETCH (or BROWSE if interactive keywords present)
        url_match = _URL_PATTERN.search(msg)
        if url_match:
            url = url_match.group(0)
            # Check if the user wants to interact with the page (not just read it)
            _interactive_keywords = any(
                kw in msg_lower
                for kw in [
                    "click",
                    "fill",
                    "type",
                    "login",
                    "sign in",
                    "submit",
                    "form",
                    "button",
                    "scroll",
                    "screenshot",
                    "interact",
                ]
            )
            if _interactive_keywords:
                # Interactive browsing → use the browser agent
                profile = TaskProfile(
                    capabilities=[Capability.BROWSE, Capability.SYNTHESIS],
                    requires_grounding=True,
                    requires_tools=True,
                    execution_mode=ExecutionMode.AGENT_LOOP,
                    safety_level=SafetyLevel.MEDIUM,
                    confidence=0.85,
                    primary_domain="browse",
                    reformulated=f"Open {url} in the browser and interact with it",
                    acknowledgement=f"Opening {url} in the browser...",
                )
                return OrchestrationPlan(
                    profile=profile,
                    graph=build_graph_from_plan_steps(
                        [
                            {
                                "id": "browse_url",
                                "capability": "browse",
                                "tool": "browse",
                                "args": {"action": "open", "url": url},
                                "depends_on": [],
                                "label": f"Opening: {url[:60]}",
                            }
                        ]
                    ),
                    dispatch_steps=[{"intent": "browse", "detail": f"Browse: {url[:50]}"}],
                    fast_path=True,
                )
            # Static fetch → web_fetch
            profile = TaskProfile(
                capabilities=[Capability.WEB_FETCH, Capability.SYNTHESIS],
                requires_grounding=True,
                requires_tools=True,
                execution_mode=ExecutionMode.SINGLE_TOOL,
                safety_level=SafetyLevel.LOW,
                confidence=0.95,
                primary_domain="web_fetch",
                reformulated=f"Fetch and read the content from {url}",
                acknowledgement=f"Fetching content from {url}...",
            )
            return OrchestrationPlan(
                profile=profile,
                graph=build_graph_from_plan_steps(
                    [
                        {
                            "id": "fetch_url",
                            "capability": "web_fetch",
                            "tool": "web_fetch",
                            "args": {"url": url},
                            "depends_on": [],
                            "label": f"Fetching: {url[:60]}",
                        }
                    ]
                ),
                dispatch_steps=[{"intent": "web_fetch", "detail": f"Fetch: {url[:50]}"}],
                fast_path=True,
            )

        # File attachment → FILE_READ
        if has_attachment:
            filename = attachment_filename or "uploaded file"
            profile = TaskProfile(
                capabilities=[Capability.FILE_READ, Capability.SYNTHESIS],
                requires_tools=True,
                requires_file_access=True,
                execution_mode=ExecutionMode.SINGLE_TOOL,
                safety_level=SafetyLevel.LOW,
                confidence=0.95,
                primary_domain="file_analysis",
                reformulated=f"Analyze the uploaded file: {filename}",
                acknowledgement=f"Reading {filename}...",
            )
            return OrchestrationPlan(
                profile=profile,
                graph=build_graph_from_plan_steps(
                    [
                        {
                            "id": "read_file",
                            "capability": "file_read",
                            "tool": "file_reader",
                            "args": {"path": filename},
                            "depends_on": [],
                            "label": f"Reading: {filename}",
                        }
                    ]
                ),
                dispatch_steps=[{"intent": "file_task", "detail": f"Read: {filename}"}],
                fast_path=True,
            )

        # Exact time/date query → SYSINFO
        if msg_lower in _EXACT_SYSINFO_PHRASES:
            profile = TaskProfile(
                capabilities=[Capability.SYSINFO],
                requires_tools=True,
                execution_mode=ExecutionMode.SINGLE_TOOL,
                safety_level=SafetyLevel.LOW,
                confidence=0.98,
                primary_domain="system_info",
                reformulated=msg,
                acknowledgement="Let me check that for you.",
            )
            return OrchestrationPlan(
                profile=profile,
                graph=build_graph_from_plan_steps(
                    [
                        {
                            "id": "sysinfo",
                            "capability": "sysinfo",
                            "tool": "sysinfo",
                            "args": {"goal": msg},
                            "depends_on": [],
                            "label": "Getting system info",
                        }
                    ]
                ),
                dispatch_steps=[{"intent": "sysinfo", "detail": "System info query"}],
                fast_path=True,
            )

        # Weather queries → WEB_SEARCH (Session 195). "Whats the weather like
        # in Kitengela now?" is the canonical realtime query, but the LLM
        # classifier sometimes misroutes it to CHAT (the live transcript:
        # intent=Conversation, confidence 0.30, tools none — and the model
        # then leaked a web_search <tool_call> as raw text in the bubble). A
        # weather keyword + a place makes it unambiguous: route to a
        # SINGLE_TOOL web_search plan with zero dispatcher LLM calls (same
        # pattern as the file-search signal). The classifier prompt still
        # owns INDIRECT weather phrasing ("should I carry an umbrella?").
        _WEATHER_KW = re.compile(
            r"\b(weather|temperature|forecast|humidity|uv\s*(?:index)?|rain(?:ing)?|"
            r"snow(?:ing)?|sunny|cloudy|overcast|storm|thunderstorm|wind(?:y| speed)?|"
            r"hot|cold|warm|chilly|freezing|scorching)\b",
            re.IGNORECASE,
        )
        _WEATHER_PLACE = re.compile(
            r"\b(?:in|at|for|around|near|like in)\s+([A-Za-z][A-Za-z0-9 .'\-]*"
            r"(?:[,/]\s*[A-Za-z][A-Za-z0-9 .'\-]*)?)\s*[?.!]?\s*$",
            re.IGNORECASE,
        )
        # File/read phrasing must NOT become a weather search ("find the
        # weather report", "read the weather file", "weather log").
        _WEATHER_NOT_FILE = re.compile(
            r"\b(file|files|folder|folders|directory|report|log|document|doc|"
            r"read|open|search for|locate|find)\b",
            re.IGNORECASE,
        )
        # Code-review guard (Session 195): adjectives alone ("hot", "cold",
        # "windy") appear in casual statements — "It's getting hot in here",
        # "It's cold in the office today" — which must NOT become nonsense web
        # searches. Fire when the message has a weather NOUN (weather,
        # temperature, raining...) OR is a request/interrogative form
        # ("how hot is it in X?", "is it raining in X?"). Statements fall
        # through to the LLM classifier.
        _WEATHER_NOUN = re.compile(
            r"\b(weather|temperature|forecast|humidity|uv\s*index|rain(?:ing)?|"
            r"snow(?:ing)?|storm|thunderstorm|sunny|cloudy|overcast)\b",
            re.IGNORECASE,
        )
        _WEATHER_QUESTION = re.compile(
            r"^(?:what|whats|what's|what is|how|hows|how's|how is|is it|will it|"
            r"does it|can you|could you|please|check|show me|tell me|get me)\b",
            re.IGNORECASE,
        )
        # A TIME word is not a place — "what is the forecast for tomorrow"
        # must not become a search for "tomorrow". Leave time-only phrasing
        # to the LLM classifier.
        _WEATHER_TIME_WORDS = {
            "tomorrow", "today", "tonight", "now", "later", "weekend",
            "week", "morning", "afternoon", "evening", "night",
            "yesterday", "this week", "next week", "this weekend",
        }
        _weather_m = _WEATHER_PLACE.search(msg)
        if (
            _WEATHER_KW.search(msg)
            and (_WEATHER_NOUN.search(msg) or _WEATHER_QUESTION.match(msg))
            and _weather_m
            and not _WEATHER_NOT_FILE.search(msg)
        ):
            _place = re.sub(
                r"\b(now|today|right now|please|thanks|asap)\b\s*$",
                "",
                _weather_m.group(1).strip(),
                flags=re.IGNORECASE,
            ).strip()
            # "forecast for TOMORROW" — a time word is not a place; skip the
            # signal and let the LLM classifier own time-only phrasing.
            if _place and _place.lower() not in _WEATHER_TIME_WORDS:
                _wq = f"{_place} current weather temperature conditions"
                profile = TaskProfile(
                    capabilities=[Capability.WEB_SEARCH, Capability.SYNTHESIS],
                    requires_grounding=True,
                    requires_tools=True,
                    realtime_sensitive=True,
                    execution_mode=ExecutionMode.SINGLE_TOOL,
                    safety_level=SafetyLevel.LOW,
                    confidence=0.92,
                    primary_domain="web_search",
                    reformulated=f"Search the web for the current weather in {_place}",
                    acknowledgement=f"Let me check the current weather in {_place}...",
                )
                return OrchestrationPlan(
                    profile=profile,
                    graph=build_graph_from_plan_steps(
                        [
                            {
                                "id": "weather_search",
                                "capability": "web_search",
                                "tool": "web_search",
                                "args": {"query": _wq},
                                "depends_on": [],
                                "label": f"Searching: {_wq[:50]}",
                            }
                        ]
                    ),
                    dispatch_steps=_build_dispatch_steps(
                        Intent.WEB_SEARCH, message, f"Weather: {_place[:60]}"
                    ),
                    fast_path=True,
                )

        # File-search phrasing → FIND_PATH (Session 191, ADR-17 track 2).
        # "find my CV", "locate the invoice", "search for resume files",
        # "where is the config file" are unambiguous NAME-SEARCH requests,
        # but they used to route through the LLM dispatcher → SHELL intent
        # → the model's Get-ChildItem -Recurse (20s timeouts on Windows
        # home dirs, then an orchestrator replan spiral). The purpose-built
        # find_path tool (Session 124/125) finds by NAME, bounded, in ~2s.
        # This signal routes find-phrasing to a SINGLE_TOOL find_path plan
        # with zero dispatcher LLM calls; the FIND_PATH toolset scopes the
        # agent (find_path-first, "locate before listing").
        #
        # Runs BEFORE the shell-prefix signal because "find" IS a shell
        # prefix (the Windows cmd `find` command) — a natural-language
        # "find my CV" must not become a shell command. A raw-shell guard
        # (first token a path/flag, or " -" options present) leaves real
        # `find <path> <opts>` commands on the shell path.
        #
        # Other guards (fall through to the LLM):
        #   - Investigation: "find out why/how/what", "figure out",
        #     "find a way to" → reasoning, not file search.
        #   - Debug targets: "find the bug/issue/problem/error" →
        #     debugging, not a name search ("find the error log" still
        #     searches — it's a file).
        #   - "find where X is" → too ambiguous to parse deterministically.
        #   - No searchable target left after stripping → fall through.
        _FIND_VERB = re.compile(
            r"^(?:(?:can|could|please)\s+(?:you\s+)?)?(?:find|locate|search for|look for|"
            r"hunt for|where(?:'s| is| are))(?=\s|$)",
            re.IGNORECASE,
        )
        _FIND_INVESTIGATION = re.compile(
            r"\b(find out|find a way|figure out|look into|investigate|"
            r"search the web|google it)\b",
            re.IGNORECASE,
        )
        _FIND_POSSESSIVE = re.compile(r"^(?:my|our|the|a|an|me|us)\s+", re.IGNORECASE)
        _FIND_SPLIT = re.compile(r"\s+(?:and|but|then|so|please)\b", re.IGNORECASE)
        _FIND_LOCATION = re.compile(
            r"\s+(?:in|under|inside|within)\s+([^\s].*)$", re.IGNORECASE
        )
        _FIND_TRAILING_NOUN = re.compile(
            r"\s+(?:files?|folders?|directories?|docs?|documents?)\s*$", re.IGNORECASE
        )
        _FIND_DEBUG_TARGET = re.compile(
            r"^(?:bug|bugs|issue|issues|problem|problems|error|errors|cause|reason)"
            r"(?:\s+(?:with|in|on|for|about)\b.*)?$",
            re.IGNORECASE,
        )
        _FIND_SHELLISH = re.compile(r"^[-./~]|\\|:\s*\\", re.IGNORECASE)
        # Strip a leading identity/greeting clause so the ANCHORED verb can
        # match the exact live phrasing "I'm Tisone, find my cv and read it"
        # (Session 191 review: the real-world message escaped the signal and
        # fell back to the SHELL spiral). "I'm <name>, " / "my name is <name>,"
        # / "hey, "/"hi "/"ok " only — anything else keeps the anchor.
        _FIND_LEAD = re.compile(
            r"^(?:(?:i'?m|i am|my name is)\s+[^,.]*[,.]\s*|"
            r"(?:hey|hi|hello|ok(?:ay)?)\s*[,!]?\s*)",
            re.IGNORECASE,
        )
        # Session 193 (deterministic file-ops layer): is this a compound
        # READ request ("find my cv AND READ it")? The read flag routes the
        # plan to primary_domain="file_ops", which the engine intercepts
        # and executes deterministically (find → pick → read) with the model
        # reduced to final synthesis. Also captures the identity name
        # ("I'm Tisone...") so the picker prefers CV-Tisone*.docx.
        _read_requested, _identity = detect_read_request(msg)
        _domain = "file_ops" if _read_requested else "file_search"

        _msg_for_find = _FIND_LEAD.sub("", msg, count=1)
        _find_m = _FIND_VERB.match(_msg_for_find)
        if _find_m and not _FIND_INVESTIGATION.search(msg):
            _rest = _msg_for_find[_find_m.end() :]
            # Session 194 (code review): continuation phrases must survive
            # the split below (which truncates at and/but/then/so/please) —
            # "find my cv AND SHOW MORE" must still page the catalog, and
            # "find my cv, ONLY PDF" must still filter. Extract them from
            # the raw rest FIRST.
            _cont_filters: dict[str, object] = {}
            if re.search(
                r"\b(?:show|see|list|get)\s+(?:me\s+)?more\b", _rest, re.IGNORECASE
            ):
                _cont_filters["offset"] = 25  # page 2 of the cached catalog
                _rest = re.sub(
                    r"\b(?:and\s+)?(?:show|see|list|get)\s+(?:me\s+)?more\b",
                    "",
                    _rest,
                    flags=re.IGNORECASE,
                )
            _cont_ext = re.search(
                r"\bonly\s+([a-zA-Z0-9]+)\s*(?:files?)?\s*$", _rest, re.IGNORECASE
            )
            if _cont_ext:
                _cont_filters["ext"] = _cont_ext.group(1).lower()
                _rest = _rest[: _cont_ext.start()]
            _rest = _FIND_SPLIT.split(_rest, 1)[0].strip().strip("\"'")
            if _rest.lower().startswith("where"):
                _rest = ""  # "find where X is" — too ambiguous to parse
            _rest = _FIND_POSSESSIVE.sub("", _rest).strip()
            if _rest:
                # Raw shell guard: `find . -name` / `find C:\ -type f` stay
                # shell commands (also catches " -" option lists).
                _first_tok = _rest.split(None, 1)[0] if _rest else ""
                _shellish = bool(
                    _FIND_SHELLISH.search(_first_tok) or re.search(r"\s-", _rest)
                )
                _root = ""
                # Session 194 (catalog contract): continuation filters become
                # instant in-memory narrowing of the cached walk. "show more"
                # and "only <ext>" were extracted pre-split (above) so they
                # survive "and"; here absolute locations stay the search ROOT
                # and bare folder names ("in Documents") become a SUBPATH
                # filter.
                _filters: dict[str, object] = dict(_cont_filters)
                _loc_m = _FIND_LOCATION.search(_rest)
                if _loc_m:
                    _loc = _loc_m.group(1).strip().strip("\"'").rstrip("/\\,;.")
                    if re.match(r"^(?:[A-Za-z]:[\\/]|/|~)", _loc):
                        _root = _loc
                    elif _loc:
                        _filters["subpath"] = _loc
                    _rest = _rest[: _loc_m.start()].strip()
                _target = (
                    _FIND_TRAILING_NOUN.sub("", _rest).strip().strip("\"'").strip(",;.")
                )
                if (
                    not _shellish
                    and _target
                    and not _FIND_DEBUG_TARGET.match(_target)
                ):
                    # Bare word → substring match (CV matches CV-Tisone.docx);
                    # multi-word → glob so "annual budget report" matches
                    # annual_budget_report.pdf.
                    if " " in _target:
                        _pattern = "*" + "*".join(_target.split()) + "*"
                    else:
                        _pattern = _target
                    _where = _root if _root else "the user home directory"
                    _reform = (
                        f"Find files/folders whose name matches '{_target}' under "
                        f"{_where}, then complete the original request: {message[:160]}"
                    )
                    profile = TaskProfile(
                        capabilities=[Capability.FILE_READ],
                        requires_tools=True,
                        requires_file_access=True,
                        execution_mode=ExecutionMode.SINGLE_TOOL,
                        safety_level=SafetyLevel.LOW,
                        confidence=0.9,
                        primary_domain=_domain,
                        reformulated=_reform,
                        acknowledgement=f"Searching for '{_target}'...",
                    )
                    return OrchestrationPlan(
                        profile=profile,
                        graph=build_graph_from_plan_steps(
                            [
                                {
                                    "id": "find_file",
                                    "capability": "file_read",
                                    "tool": "find_path",
                                    "args": {
                                        "name": _pattern,
                                        "root": _root,
                                        "max_depth": 4,
                                        "max_results": 25,
                                        **_filters,
                                    },
                                    "depends_on": [],
                                    "label": f"Searching for: {_target[:50]}",
                                }
                            ]
                        ),
                        dispatch_steps=_build_dispatch_steps(
                            Intent.FIND_PATH, message, f"Find: {_target[:80]}"
                        ),
                        fast_path=True,
                    )

        # Direct read phrasing → file_ops (Session 193). "READ my cv",
        # "SHOW me the invoice", "OPEN the budget file", "SUMMARIZE the
        # report" are unambiguous find+read requests, but they don't start
        # with find/locate/search so the file-search branch above can't see
        # them — they used to route through the LLM dispatcher to FILE_TASK
        # (agent loop), where the free-tier model had to chain find → pick
        # → read and often stalled (the "find my CV" transcript: find_path
        # succeeded in 1.9s, the model never read the file). This branch
        # produces the same file_ops plan; the engine runs the chain
        # deterministically.
        #
        # Guards (fall through to the LLM):
        #   - Explicit paths ("read ~/Documents/notes.txt") → the FILE_TASK
        #     path handles those; a name-search here would be wrong.
        #   - Listing phrasing ("show me all projects in dev") → the
        #     directory-listing signal owns that.
        #   - Non-file targets ("read the news") → not a name search.
        #   - Investigation ("show me how to...", "tell me about...").
        _READ_VERB_START = re.compile(
            r"^(?:(?:can|could|please)\s+(?:you\s+)?)?(?:read|show me|open|"
            r"view|display|summariz\w*|review|analy[sz]e|print)\b",
            re.IGNORECASE,
        )
        _READ_LISTING = re.compile(
            r"\b(?:all|the)\s+(?:files|folders|directories|projects|contents|"
            r"items|things|dirs|subfolders)\b",
            re.IGNORECASE,
        )
        _READ_PATHISH = re.compile(r"[\\/]|^~[/.]|\.[a-z0-9]{1,6}$", re.IGNORECASE)
        _READ_NON_FILE = re.compile(
            r"^\s*(news|weather|emails?|messages|notifications|website|url|page|article)\b",
            re.IGNORECASE,
        )
        # Direct-read targets must LOOK like a document/file, else the phrase
        # is not a name-search ("review my CODE" / "analyze the problem" /
        # "open the browser" are NOT file reads). The find+read compound
        # branch above already passes the stricter find guards; this guard
        # keeps the direct-read branch from swallowing coding/debug phrases.
        _READ_DOC_NOUN = re.compile(
            r"\b(cv|resume|invoice|report|document|docs?|notes?|letter|log|"
            r"budget|contract|agreement|receipt|statement|config|readme|manual|"
            r"guide|minutes|agenda|proposal|spec|summary|essay|thesis|paper|"
            r"article|profile|bio|biodata|photo|photos?|image|images?|"
            r"picture|pictures?|scan|scans?)\b",
            re.IGNORECASE,
        )
        _READ_INVESTIGATION = re.compile(
            r"\b(how to|tell me about|about how|why|what would happen)\b", re.IGNORECASE
        )
        _read_m = _READ_VERB_START.match(_msg_for_find)
        if _read_m and not _FIND_INVESTIGATION.search(msg) and not _READ_INVESTIGATION.search(msg):
            _rest = _msg_for_find[_read_m.end() :]
            _rest = _FIND_SPLIT.split(_rest, 1)[0].strip().strip("\"'")
            _rest = _FIND_POSSESSIVE.sub("", _rest).strip()
            # Session 194: "read my cv in Documents" — absolute location →
            # search root; bare folder → subpath filter on the cached walk.
            _root_r = ""
            _filters_r: dict[str, object] = {}
            _loc_m = _FIND_LOCATION.search(_rest)
            if _loc_m:
                _loc = _loc_m.group(1).strip().strip("\"'").rstrip("/\\,;.")
                if re.match(r"^(?:[A-Za-z]:[\\/]|/|~)", _loc):
                    _root_r = _loc
                elif _loc:
                    _filters_r["subpath"] = _loc
                _rest = _rest[: _loc_m.start()].strip()
            if _rest and not _READ_LISTING.search(_rest) and not _READ_PATHISH.search(_rest):
                _target = (
                    _FIND_TRAILING_NOUN.sub("", _rest).strip().strip("\"'").strip(",;.")
                )
                # Doc-noun guard checks the FULL rest (pre trailing-noun
                # strip) so "display the license document" matches on
                # "document" while "review my code" still falls through.
                if (
                    _target
                    and not _READ_NON_FILE.search(_target)
                    and not _FIND_DEBUG_TARGET.match(_target)
                    and _READ_DOC_NOUN.search(_rest)
                ):
                    if " " in _target:
                        _pattern = "*" + "*".join(_target.split()) + "*"
                    else:
                        _pattern = _target
                    _reform = (
                        f"Find and read the file matching '{_target}' under the "
                        f"user home directory, then present its contents: {message[:160]}"
                    )
                    profile = TaskProfile(
                        capabilities=[Capability.FILE_READ],
                        requires_tools=True,
                        requires_file_access=True,
                        execution_mode=ExecutionMode.SINGLE_TOOL,
                        safety_level=SafetyLevel.LOW,
                        confidence=0.9,
                        primary_domain="file_ops",
                        reformulated=_reform,
                        acknowledgement=f"Searching for '{_target}'...",
                    )
                    return OrchestrationPlan(
                        profile=profile,
                        graph=build_graph_from_plan_steps(
                            [
                                {
                                    "id": "find_read_file",
                                    "capability": "file_read",
                                    "tool": "find_path",
                                    "args": {
                                        "name": _pattern,
                                        "root": _root_r,
                                        "max_depth": 4,
                                        "max_results": 25,
                                        **_filters_r,
                                    },
                                    "depends_on": [],
                                    "label": f"Searching for: {_target[:50]}",
                                }
                            ]
                        ),
                        dispatch_steps=_build_dispatch_steps(
                            Intent.FIND_PATH, message, f"Find: {_target[:80]}"
                        ),
                        fast_path=True,
                    )

        # Shell command prefix → SHELL
        if any(msg.startswith(prefix) for prefix in _SHELL_PREFIXES):
            profile = TaskProfile(
                capabilities=[Capability.SHELL],
                requires_tools=True,
                requires_execution=True,
                execution_mode=ExecutionMode.SINGLE_TOOL,
                safety_level=SafetyLevel.HIGH,
                confidence=0.92,
                primary_domain="shell_command",
                reformulated=msg,
                acknowledgement=f"Running: {msg[:50]}...",
            )
            return OrchestrationPlan(
                profile=profile,
                graph=build_graph_from_plan_steps(
                    [
                        {
                            "id": "shell_cmd",
                            "capability": "shell",
                            "tool": "shell",
                            "args": {"action": msg},
                            "depends_on": [],
                            "label": f"Shell: {msg[:50]}",
                        }
                    ]
                ),
                dispatch_steps=[{"intent": "shell", "detail": f"Shell: {msg[:50]}"}],
                fast_path=True,
            )

        # Directory-listing phrasing → SHELL (Session 145, ADR-17 track 2).
        # "Show me all projects in dev" / "List projects available in dev/"
        # are unambiguous directory-list requests but don't START with a
        # shell prefix, so they used to pay the full dispatcher LLM call
        # (~10-20s on the free tier) for a routing decision a regex can
        # make. The listing noun (files/folders/projects/contents/items)
        # + a location preposition (in/of/under/inside) + a non-empty
        # target makes the signal unambiguous. Anything with a verb that
        # implies non-listing work (read, open, create, edit, search) or
        # a non-filesystem target falls through to the LLM.
        _LIST_VERB = re.compile(
            r"^(?:show|list|display|see)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?",
            re.IGNORECASE,
        )
        _LIST_NOUN = re.compile(
            r"\b(files|folders|directories|projects|contents|items|things|dirs|subfolders)\b",
            re.IGNORECASE,
        )
        _LIST_LOCATION = re.compile(
            r"\b(in|of|under|inside)\s+(?P<target>[^\s]+.*)$",
            re.IGNORECASE,
        )
        _NON_LIST_VERBS = re.compile(
            r"\b(read|open|create|make|write|edit|delete|search|find|install|run|execute|check|show me how)\b",
            re.IGNORECASE,
        )
        if (
            _LIST_VERB.match(msg)
            and _LIST_NOUN.search(msg)
            and _LIST_LOCATION.search(msg)
            and not _NON_LIST_VERBS.search(msg)
        ):
            _target = _LIST_LOCATION.search(msg).group("target").strip("\"' ").rstrip("/")
            if _target:
                profile = TaskProfile(
                    capabilities=[Capability.SHELL],
                    requires_tools=True,
                    requires_execution=True,
                    execution_mode=ExecutionMode.SINGLE_TOOL,
                    safety_level=SafetyLevel.HIGH,
                    confidence=0.9,
                    primary_domain="shell_command",
                    reformulated=f"List the contents of the directory: {_target}",
                    acknowledgement=f"Listing contents of {_target}...",
                )
                return OrchestrationPlan(
                    profile=profile,
                    graph=build_graph_from_plan_steps(
                        [
                            {
                                "id": "list_dir",
                                "capability": "shell",
                                "tool": "shell",
                                "args": {"action": f"list {_target}"},
                                "depends_on": [],
                                "label": f"Listing contents: {_target[:50]}",
                            }
                        ]
                    ),
                    dispatch_steps=_build_dispatch_steps(Intent.SHELL, message, f"List directory {_target}"),
                    fast_path=True,
                )

        # Git-phrasing → git tool (Session 149, ADR-17 track 2).
        # The canonical dev-tool request — "Check git status on the
        # localmind repo, and if there are uncommitted changes, show me
        # the diff" — starts with "Check" (no shell prefix) and is not a
        # directory listing, so it used to pay the full dispatcher LLM
        # call (~10-20s on the free tier) for a routing decision a regex
        # can make. Fire only when the message explicitly anchors on git
        # state:
        #   - "git <subcommand>" (status/diff/log/branch/stash)
        #   - git-state phrasing: uncommitted/unstaged changes, working
        #     tree, committed changes, commit history, recent commits
        #   - "show (me )?the diff" combined with one of the anchors above
        # Requests with no git anchor (a bare "show me the diff" between
        # two files) or a git verb outside the detected set (push, pull,
        # commit, merge as the only operation) fall through to the LLM.
        _msg_lower = msg.lower()
        _git_anchored = bool(
            re.search(
                r"\bgit\b|\b(uncommitted|unstaged|committed|working tree|"
                r"repo|repository|commit history|recent commits|branches)\b",
                _msg_lower,
            )
        )
        if _git_anchored:
            _want: list[tuple[str, str, str]] = []
            if re.search(
                r"\bgit\s+status\b|\bstatus\s+of\s+the\s+repo\b|"
                r"\b(uncommitted|unstaged)\s+changes\b|\bworking\s+tree\b|"
                r"\brepo\s+status\b",
                _msg_lower,
            ):
                _want.append(("status", "Git status", "git_status"))
            if re.search(
                r"\bgit\s+diff\b|\bshow\s+(?:me\s+)?the\s+diff\b|"
                r"\bwhat('|\u2019|&#39;)?s\s+changed\b|\bwhat\s+changed\b|"
                r"\bcommitted\s+changes\b|\bthe\s+diff\b",
                _msg_lower,
            ):
                _want.append(("diff", "Git diff (if changes)", "git_diff"))
            if re.search(
                r"\bgit\s+log\b|\bcommit\s+history\b|\brecent\s+commits\b|"
                r"\bgit\s+history\b",
                _msg_lower,
            ):
                _want.append(("log", "Git log", "git_log"))
            if re.search(
                r"\bgit\s+branch\b|\bshow\s+(?:me\s+)?(?:the\s+)?branches\b",
                _msg_lower,
            ):
                _want.append(("branch", "Git branch", "git_branch"))
            if re.search(r"\bgit\s+stash\b", _msg_lower):
                _want.append(("stash", "Git stash", "git_stash"))
            if _want:
                # Deduplicate (a message can name the same op twice).
                _seen: set[str] = set()
                _ops: list[tuple[str, str, str]] = []
                for _op in _want:
                    if _op[0] not in _seen:
                        _seen.add(_op[0])
                        _ops.append(_op)
                _steps: list[dict] = []
                _prev: str | None = None
                for _op, _label, _node_id in _ops:
                    _steps.append(
                        {
                            "id": _node_id,
                            "capability": "shell",
                            "tool": "git",
                            "args": {"operation": _op},
                            "depends_on": [_prev] if _prev else [],
                            "label": _label,
                        }
                    )
                    _prev = _node_id
                profile = TaskProfile(
                    capabilities=[Capability.SHELL],
                    requires_tools=True,
                    requires_execution=True,
                    execution_mode=ExecutionMode.SINGLE_TOOL,
                    safety_level=SafetyLevel.HIGH,
                    confidence=0.9,
                    primary_domain="shell_command",
                    reformulated=(
                        "Run git operations on the current repository: "
                        + ", ".join(o for o, _, _ in _ops)
                    ),
                    acknowledgement=f"Checking {_ops[0][1].lower()}...",
                )
                return OrchestrationPlan(
                    profile=profile,
                    graph=build_graph_from_plan_steps(_steps),
                    dispatch_steps=[{"intent": "shell", "detail": f"Git: {_ops[0][1]}"}],
                    fast_path=True,
                )

        return None

    # ── Follow-up Detection ─────────────────────────────────────────────

    def _try_followup_plan(self, message: str, history: list, obs: ObsCollector) -> Optional[OrchestrationPlan]:
        """Follow-up detection that returns OrchestrationPlan."""
        from core.agent.constants import FOLLOWUP_HISTORY_DEPTH

        if not history or len(history) < 2:
            return None

        msg_lower = message.strip().lower().rstrip("!?.,")
        depth = FOLLOWUP_HISTORY_DEPTH
        recent_messages = history[-depth:] if len(history) > depth else history

        user_msgs = []
        assistant_msgs = []
        for msg in reversed(recent_messages):
            role = getattr(msg, "role", None)
            content = getattr(msg, "content", "") or ""
            role_str = role.value if hasattr(role, "value") else str(role)
            if role_str == "user":
                user_msgs.append(content[:300])
            elif role_str == "assistant":
                assistant_msgs.append(content[:500])

        last_user = user_msgs[0] if user_msgs else ""
        last_asst = assistant_msgs[0] if assistant_msgs else ""
        prior_user = user_msgs[1] if len(user_msgs) > 1 else ""
        prior_asst = assistant_msgs[1] if len(assistant_msgs) > 1 else ""

        # Detect prior SHELL context
        _SHELL_KEYWORDS = re.compile(
            r"\b(run|execute|install|start|launch|open|command|terminal|shell|cmd|"
            r"browse|directory|folder|list files|find|locate|search for|look for|"
            r"documents|downloads|desktop|projects?)\b",
            re.IGNORECASE,
        )

        all_text = " ".join([last_user, last_asst, prior_user, prior_asst]).lower()
        shell_keyword_hits = len(_SHELL_KEYWORDS.findall(all_text))
        has_prior_shell_context = shell_keyword_hits >= 1

        if has_prior_shell_context:
            _CONFIRM_WORDS = {
                "yes",
                "yeah",
                "yep",
                "ok",
                "okay",
                "go ahead",
                "do it",
                "please",
                "proceed",
                "confirm",
                "continue",
                "sure",
                "try again",
                "retry",
                "again",
                "run it",
            }
            if msg_lower in _CONFIRM_WORDS:
                reformulated = (
                    f"Previous request: '{prior_user or last_user}'. "
                    f"User confirmed with '{message}' — rerun the prior shell/command task."
                )
                profile = TaskProfile(
                    capabilities=[Capability.SHELL],
                    requires_tools=True,
                    requires_execution=True,
                    execution_mode=ExecutionMode.SINGLE_TOOL,
                    safety_level=SafetyLevel.HIGH,
                    confidence=0.80,
                    reformulated=reformulated,
                    acknowledgement="Running that for you.",
                    reasoning="Follow-up: prior shell context detected, user confirmed.",
                )
                return OrchestrationPlan(
                    profile=profile,
                    graph=build_graph_from_plan_steps(
                        [
                            {
                                "id": "shell_followup",
                                "capability": "shell",
                                "tool": "shell",
                                "args": {"action": reformulated},
                                "depends_on": [],
                                "label": "Rerunning previous command",
                            }
                        ]
                    ),
                    dispatch_steps=_build_dispatch_steps(Intent.SHELL, message, reformulated),
                    fast_path=False,
                )

        # Detect file-related follow-ups
        _FILE_SIGNALS_PATTERNS = [
            re.compile(
                r"\b(read|open|view|show|check|fetch)\b.*\b(file|cv|resume|document|pdf|doc)\b",
                re.IGNORECASE,
            ),
            re.compile(r"\.(pdf|docx?|txt|csv|xlsx?|md)\b", re.IGNORECASE),
        ]
        _file_signal_count = sum(
            1
            for p in _FILE_SIGNALS_PATTERNS
            for text in [last_asst, last_user, prior_user, prior_asst]
            if p.search(text)
        )

        if _file_signal_count >= 1:
            reformulated = (
                f"User originally asked: '{prior_user or last_user}'. "
                f"User confirmed: '{message}' — proceed with file operation."
            )
            profile = TaskProfile(
                capabilities=[Capability.FILE_READ],
                requires_grounding=True,
                requires_tools=True,
                requires_file_access=True,
                execution_mode=ExecutionMode.SINGLE_TOOL,
                safety_level=SafetyLevel.LOW,
                confidence=0.80,
                reformulated=reformulated,
                acknowledgement="Reading that file for you now.",
                reasoning="Follow-up: file operation context detected from history.",
            )
            return OrchestrationPlan(
                profile=profile,
                graph=build_graph_from_plan_steps(
                    [
                        {
                            "id": "file_followup",
                            "capability": "file_read",
                            "tool": "file_task",
                            "args": {},
                            "depends_on": [],
                            "label": "Reading file",
                        }
                    ]
                ),
                dispatch_steps=_build_dispatch_steps(Intent.FILE_TASK, message, reformulated),
                fast_path=False,
            )

        # Generic confirmation
        _GENERIC_CONFIRM = {
            "yes",
            "yeah",
            "yep",
            "ok",
            "okay",
            "go ahead",
            "do it",
            "please",
            "proceed",
            "confirm",
            "continue",
            "sure",
        }
        if msg_lower in _GENERIC_CONFIRM:
            reformulated = (
                f"User originally asked: '{prior_user or last_user}'. "
                f"User said '{message}' — confirming action from prior turn."
            )
            profile = TaskProfile(
                capabilities=[Capability.FILE_READ],
                requires_grounding=True,
                requires_tools=True,
                requires_file_access=True,
                execution_mode=ExecutionMode.SINGLE_TOOL,
                safety_level=SafetyLevel.LOW,
                confidence=0.70,
                reformulated=reformulated,
                acknowledgement="Proceeding with the previous request.",
                reasoning="Follow-up: generic confirmation from history.",
            )
            return OrchestrationPlan(
                profile=profile,
                graph=build_graph_from_plan_steps(
                    [
                        {
                            "id": "followup",
                            "capability": "file_read",
                            "tool": "file_task",
                            "args": {},
                            "depends_on": [],
                            "label": "Following up",
                        }
                    ]
                ),
                dispatch_steps=_build_dispatch_steps(Intent.FILE_TASK, message, reformulated),
                fast_path=False,
            )

        return None

    # ── LLM Output Parsing ──────────────────────────────────────────────

    def _parse_llm_output(self, data: dict, message: str, has_attachment: bool, history: list) -> OrchestrationPlan:
        """Parse the LLM's JSON output into an OrchestrationPlan."""
        # Parse capabilities
        capabilities = []
        for cap_str in data.get("capabilities", []):
            try:
                capabilities.append(Capability(cap_str))
            except ValueError:
                logger.debug(f"[dispatcher] unknown capability: {cap_str}")

        # Parse flags
        flags = data.get("flags", {})

        # Parse execution mode
        execution_mode = ExecutionMode.DIRECT
        mode_str = data.get("execution_mode", "direct")
        try:
            execution_mode = ExecutionMode(mode_str)
        except ValueError:
            pass

        # Parse safety level
        safety_level = SafetyLevel.LOW
        safety_str = data.get("safety_level", "low")
        try:
            safety_level = SafetyLevel(safety_str)
        except ValueError:
            pass

        # Build TaskProfile
        profile = TaskProfile(
            requires_grounding=flags.get("requires_grounding", False),
            requires_tools=flags.get("requires_tools", bool(capabilities)),
            requires_planning=flags.get("requires_planning", False),
            requires_memory=flags.get("requires_memory", False),
            requires_reasoning=flags.get("requires_reasoning", False),
            requires_execution=flags.get("requires_execution", False),
            requires_file_access=flags.get("requires_file_access", False),
            realtime_sensitive=flags.get("realtime_sensitive", False),
            capabilities=capabilities,
            safety_level=safety_level,
            confidence=min(1.0, max(0.0, float(data.get("confidence", 0.7)))),
            execution_mode=execution_mode,
            primary_domain=data.get("primary_domain", ""),
            reformulated=data.get("reformulated_query", message),
            acknowledgement=data.get("acknowledgement", ""),
        )

        # Auto-correct inconsistencies
        profile.auto_correct()

        # Capability correction: if realtime_sensitive but no WEB_SEARCH, add it
        if profile.realtime_sensitive and Capability.WEB_SEARCH not in capabilities:
            capabilities.insert(0, Capability.WEB_SEARCH)
            profile.capabilities = capabilities
            profile.auto_correct()
            logger.info("[dispatcher] adding WEB_SEARCH: realtime_sensitive=True but no web_search capability")

        # Derive execution mode if not already set correctly
        if profile.is_chat_only() and profile.execution_mode != ExecutionMode.DIRECT:
            profile.execution_mode = ExecutionMode.DIRECT
        elif not profile.is_chat_only() and profile.execution_mode == ExecutionMode.DIRECT:
            if len(profile.tool_capabilities()) >= 2:
                profile.execution_mode = ExecutionMode.MULTI_TOOL
            else:
                profile.execution_mode = ExecutionMode.SINGLE_TOOL
            logger.info(
                "[dispatcher] correcting execution_mode: %s → %s for capabilities=%s",
                ExecutionMode.DIRECT.value,
                profile.execution_mode.value,
                [c.value for c in capabilities],
            )

        # Build execution graph from plan steps. Defensive (Session 160
        # review): execution_plan may be malformed (list/string) — guard the
        # steps, success_criteria, and task_type reads with one isinstance.
        execution_plan = data.get("execution_plan")
        plan_dict = execution_plan if isinstance(execution_plan, dict) else {}

        steps = plan_dict.get("steps", [])
        graph = build_graph_from_plan_steps(steps) if steps else ExecutionGraph()

        # ADR-18/19: typed success_criteria + task_type from execution_plan.
        criteria_raw = plan_dict.get("success_criteria", [])
        success_criteria: list[str] = []
        if isinstance(criteria_raw, list):
            success_criteria = [
                str(c).strip() for c in criteria_raw if str(c).strip()
            ][:6]

        # ADR-19: explicit task_type from the plan's execution_plan (optional).
        # Controls task-aware context compaction; empty = legacy behavior.
        from core.context_policy import parse_task_type_from_plan

        task_type = parse_task_type_from_plan(
            plan_dict.get("task_type", ""),
            primary_domain=str(data.get("primary_domain", "")),
        )

        # Build dispatch steps for UI
        dispatch_steps = []
        for step in steps:
            cap_name = step.get("capability", "")
            label = step.get("label", cap_name)
            dispatch_steps.append({"intent": cap_name, "detail": label})

        if not dispatch_steps:
            dispatch_steps = _build_dispatch_steps(profile.primary_intent(), message, profile.reformulated, profile)

        return OrchestrationPlan(
            profile=profile,
            graph=graph,
            reasoning=data.get("reasoning", ""),
            dispatch_steps=dispatch_steps,
            fast_path=False,
            success_criteria=success_criteria,
            task_type=task_type,
        )

    # ── Fallback ────────────────────────────────────────────────────────

    def _fallback_plan(self, message: str, has_attachment: bool, history: list) -> OrchestrationPlan:
        """Fallback on timeout/error. Returns a minimal CHAT TaskProfile."""
        return OrchestrationPlan(
            profile=TaskProfile(
                capabilities=[],
                execution_mode=ExecutionMode.DIRECT,
                safety_level=SafetyLevel.LOW,
                confidence=0.3,
                reformulated=message,
                acknowledgement="",
                reasoning="Fallback: LLM dispatch call failed or timed out",
            ),
            graph=ExecutionGraph(),
            reasoning="Fallback: LLM dispatch call failed or timed out",
            dispatch_steps=[{"intent": "chat", "detail": "Direct conversation"}],
            fast_path=False,
        )

    # ── Private helpers ─────────────────────────────────────────────────

    def _format_history(self, history: list) -> str:
        if not history:
            return "(No prior exchange exists.)"
        lines = []
        for msg in history[-MAX_HISTORY_FOR_PROMPT:]:
            role = getattr(msg, "role", None)
            content = getattr(msg, "content", "") or ""
            role_str = role.value if hasattr(role, "value") else str(role)
            lines.append(f"  {role_str}: {content[:200]}")
        return "\n".join(lines)

    def _format_memory(self, facts: list[str]) -> str:
        if not facts:
            return "(No memory facts.)"
        return "\n".join(f"  - {f[:200]}" for f in facts[:10])
