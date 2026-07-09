"""
Core Engine — v4.0

6-Layer Pipeline:
  [0] Safety Gate → blocks unsafe messages
  [1] Load History + Persist User Message
  [2] Capability Inference via ThinkingDispatcher → OrchestrationPlan (TaskProfile + ExecutionGraph)
  [3] Derive routing from TaskProfile.execution_mode
  [4] Execute: DIRECT (chat) | SINGLE_TOOL | MULTI_TOOL | AGENT_LOOP | MULTI_PHASE
  [5] Post-Processing: Memory persistence, history, observability, metrics

Architecture (v4.0 — No backward compat):
  - ThinkingDispatcher is the SOLE routing mechanism (no regex classifier)
  - TaskProfile replaces single-label Intent classification
  - ExecutionGraph provides DAG-based parallel capability execution
  - No legacy safety-net overrides (SYSINFO regex, CHAT→tool overrides removed)
  - The ThinkingDispatcher's LLM capability inference handles all routing
    correctly, including EPL-style queries and SYSINFO detection
"""
from __future__ import annotations
import asyncio
import logging
import re
import time
import uuid
from typing import AsyncIterator, Optional

from core.models import (
    Intent, Message, Role, EngineContext, StreamChunk,
    FileAttachment, ToolResult, RiskLevel,
    TaskProfile, ExecutionMode, SafetyLevel, Capability,
    OrchestrationPlan, UnderstandingResult, ValidationResult,
    CAPABILITY_TO_INTENT, TOOL_CAPABILITIES,
)
from core.config import settings
from core import context_builder
from core.summarizer import maybe_compress_history
# v4.0: No regex classifier exists. ThinkingDispatcher is the sole router.
from core.flywheel import FlywheelLogger
from core.memory import MemoryComposer
from core.agent import AgentLoop, AGENT_INTENTS
from core.agent.orchestrator import AgentOrchestrator, OrchestrationResult
from core.workspace.orchestrator import WorkspaceOrchestrator, _should_use_orchestrator
from core.tool_scorer import best_tool, score_tools, load_reliability_from_db, record_tool_outcome
from core.obs import ObsCollector
from core.metrics import MetricsStore  # NEW: aggregated p50/p95 per intent + tool success rates
from core.filters import _filter_system_leaks, _filter_tool_injection, _filter_code_output
from core.model_router import best_model_for, update_pulled_models
from core.agent.constants import (
    REFLECT_ENABLED, REFLECT_INTENTS, REFLECT_MAX_TOKENS,
    CAPABILITY_ORCHESTRATION_ENABLED,
)
from core.thinking_dispatcher import ThinkingDispatcher
from storage.db import SessionStore
from adapters.ollama import _is_small_model
from tools import dispatch, available_tools
from core.agent.tool_dispatch import dispatch_with_retry
from core.safety_gate import check as safety_check
from core.session_context import SessionContextManager

# Import extracted helpers and mixins (step 2 of engine split)
from ._helpers import (
    _safe_task,
    _LRUCache,
    _chat_agent_cache,
    _get_chat_agent_cache_key,
    _parse_chat_agent_output,
    _resolve_intent,
    _approx_tokens,
    DuplicateFilter,
    INTENT_HISTORY_WINDOW,
    INTENT_HISTORY_MAX_SESSIONS,
    MEMORY_DEDUP_THRESHOLD,
)
from ._memory_mixin import _MemoryMixin
from ._persistence_mixin import _PersistenceMixin
from ._reflection_mixin import _ReflectionMixin

logger = logging.getLogger(__name__)


def get_adapter(*args, **kwargs):
    """Deferred-lookup wrapper for adapters.get_adapter.

    Looks up get_adapter from the core.engine package at call time so that
    test patches (patch("core.engine.get_adapter", ...)) take effect on
    code in this submodule. Without this, a module-level
    `from adapters import get_adapter` would create a separate binding
    that the patch cannot reach.
    """
    from core.engine import get_adapter as _real
    return _real(*args, **kwargs)


class Engine(_MemoryMixin, _PersistenceMixin, _ReflectionMixin):
    def __init__(self):
        self._store = SessionStore(settings.localmind_db_path)
        # Don't cache adapter at init - get fresh one each time to respect setting changes
        self._memory = MemoryComposer()
        self._agent_loop = AgentLoop(adapter=None)  # Set adapter dynamically
        self._agent_orchestrator = AgentOrchestrator(adapter=None)  # Three-layer pipeline orchestrator
        self._orchestrator = WorkspaceOrchestrator(adapter=None)
        self._metrics = MetricsStore()
        self._flywheel = FlywheelLogger()
        # REMOVED: self._router = RiskAwareRouter(...) — replaced by ThinkingDispatcher
        # Per-session intent history: {session_id: [intent_value, ...]}
        self._intent_history: dict[str, list[str]] = {}
        # Pending file-write confirmations: {session_id: {path, content, filename}}
        self._pending_writes: dict[str, dict] = {}
        # Pending orchestrator clarifications: {session_id: {question, original_request, reformulated_message, intent}}
        self._pending_clarification: dict[str, dict] = {}
        # Last streamed code blocks per session: {session_id: {code, lang, filename_hint}}
        # Populated whenever the chat path streams a response containing fenced code.
        # Used by the FILE_WRITE recovery path when the user says "save it" / "update the file".
        self._last_code: dict[str, dict] = {}
        # Per-session last observation data: {session_id: dict}
        # Stored on every turn_complete so the /api/observability endpoint
        # can return real data instead of hardcoded zeros.
        self._last_observation: dict[str, dict] = {}
        # Per-session working directory via SessionContextManager.
        # Tracks CWD across tool calls so shell commands execute in the
        # correct directory (e.g., after user navigates to
        # Documents/Code/arcade-bounce, subsequent commands run there).
        self._session_ctx = SessionContextManager()
        # Think-first dispatcher: replaces regex-first RiskAwareRouter.
        # Created lazily with adapter in process() so it picks up setting changes.
        self._dispatcher: ThinkingDispatcher | None = None
        self._warmed_up = False
        # Reliability bootstrap happens in startup(), not here
        try:
            load_reliability_from_db(self._store.get_reliability())
        except Exception as e:
            logger.debug(f"[engine] reliability bootstrap skipped: {e}")

    async def startup(self) -> None:
        """
        Async initialization. Call this from your app lifespan / startup hook.
        Replaces the fragile asyncio.run() / create_task() in __init__.

        Example (FastAPI):
            @app.on_event("startup")
            async def on_startup():
                await engine.startup()
        """
        try:
            adapter = get_adapter(settings.localmind_adapter)
            pulled = await adapter.list_models()
            update_pulled_models(pulled)
            logger.info(f"[engine] model router refreshed: {len(pulled)} models available")
        except Exception as e:
            logger.warning(f"[engine] model router refresh failed (non-fatal): {e}")

        # Pre-warm the embedding model so the first memory retrieval call
        # (step 5) doesn't cold-load Ollama and hang for 180s.
        # Embeddings are always served by local Ollama (nomic-embed-text)
        # even when the LLM adapter is cloud-based. Skip the warmup when
        # Ollama isn't running — memory search falls back to keyword matching.
        if not self._warmed_up:
            # Only try Ollama embedding warmup when the adapter is Ollama.
            # Cloud adapters (Zen, OpenAI, etc.) don't need this, and trying
            # to connect to Ollama when it's not running produces noisy errors.
            if settings.localmind_adapter == "ollama":
                try:
                    await self._memory._store.warmup()
                    self._warmed_up = True
                    logger.info("[engine] vector store embedding model warmed up")
                except Exception as e:
                    logger.warning(f"[engine] vector store warmup failed (non-fatal): {e}")
                    self._warmed_up = True  # Don't retry on every request
            else:
                logger.info("[engine] skipping embedding warmup — cloud adapter active (Ollama not needed)")
                self._warmed_up = True  # Don't retry on every request

        # P11: Run memory consolidation on startup to merge near-duplicate
        # facts that accumulated from previous sessions. This is fire-and-forget
        # — consolidation runs in the background and doesn't block startup.
        _safe_task(self._memory.consolidate())

    def _adapter_for(self, intent: Intent):
        """Return an adapter configured with the best model for this intent."""
        model = best_model_for(intent, fallback=settings.ollama_model)
        return get_adapter(settings.localmind_adapter, model_override=model)

    def _update_intent_history(self, session_id: str, intent: Intent) -> list[str]:
        """Track a rolling window of intent values per session."""
        # Prune old sessions to prevent unbounded memory growth
        if len(self._intent_history) > INTENT_HISTORY_MAX_SESSIONS:
            oldest = sorted(self._intent_history.keys())[:len(self._intent_history) - INTENT_HISTORY_MAX_SESSIONS]
            for sid in oldest:
                del self._intent_history[sid]
        history = self._intent_history.setdefault(session_id, [])
        history.append(intent.value)
        if len(history) > INTENT_HISTORY_WINDOW:
            history.pop(0)
        return list(history)

    def _store_observation(self, session_id: str, obs: ObsCollector, **data):
        """Store the latest observation snapshot for a session.

        Called alongside every turn_complete emit so the
        /api/observability/{session_id} endpoint can return real data
        instead of hardcoded zeros.
        """
        # Prune old sessions to prevent unbounded memory growth
        if len(self._last_observation) > 200:
            oldest = sorted(self._last_observation.keys())[:len(self._last_observation) - 100]
            for sid in oldest:
                del self._last_observation[sid]
        # Merge with existing data so fields from earlier events
        # (e.g. toolsUsed, memoryHits) aren't lost if the current
        # turn_complete doesn't include them.
        existing = self._last_observation.get(session_id, {})
        merged = {**existing, **data}
        self._last_observation[session_id] = merged

    # _persist_user_message and _persist_assistant_message are defined in
    # _PersistenceMixin — see _persistence_mixin.py.

    async def _chat_agent_phase(
        self,
        message: str,
        intent: Intent,
        session_id: str,
        obs: ObsCollector,
        memory_facts: list[str],
        intent_history: list[str],
    ) -> tuple[str, str]:
        """
        Stage 1 of the two-stage pipeline: Chat Agent acknowledges and reformulates.

        Returns (reformulated_message, acknowledgement_text).
        - reformulated_message: the structured instruction for the Execution Agent
        - acknowledgement_text: the text to stream to the user
        If the phase fails, returns (original_message, "").
        """
        import re
        from core.agent.constants import (
            CHAT_AGENT_ENABLED, CHAT_AGENT_MIN_COMPLEXITY, CHAT_AGENT_MAX_TOKENS,
            CHAT_AGENT_TIMEOUT_SECS, CHAT_AGENT_SKIP_PATTERNS,
        )
        from core.agent.prompts import build_chat_agent_prompt
        from core.context_builder import _build_environment_context

        if not CHAT_AGENT_ENABLED:
            return message, ""

        # v0.11 PERFORMANCE: Skip Chat Agent for simple queries that don't need
        # reformulation. This saves 2-5s per simple query.
        if CHAT_AGENT_MIN_COMPLEXITY > 0:
            _is_simple = any(
                re.match(pattern, message.strip(), re.IGNORECASE)
                for pattern in CHAT_AGENT_SKIP_PATTERNS
            )
            if _is_simple:
                logger.info(f"[engine] Skipping Chat Agent for simple query: {message[:50]}")
                return message, ""

        # v0.11 PERFORMANCE: Check cache for repeated queries
        _cache_key = _get_chat_agent_cache_key(message, intent)
        _cached = _chat_agent_cache.get(_cache_key)
        if _cached:
            logger.info(f"[engine] Chat Agent cache hit for: {message[:50]}")
            return _cached

        env_context = _build_environment_context()
        chat_prompt = build_chat_agent_prompt(
            intent=intent,
            user_message=message,
            env_context=env_context,
            intent_history=intent_history,
            memory_facts=memory_facts,
        )

        chat_messages = [
            {"role": "system", "content": chat_prompt},
            {"role": "user", "content": message},
        ]

        try:
            adapter = self._adapter_for(intent)
            obs.emit("chat_agent_start", intent=intent.value)

            # Collect the full response with timeout
            full_response: list[str] = []
            async def _collect():
                async for chunk in adapter.chat(
                    chat_messages,
                    temperature=0.3,
                    intent="chat",
                ):
                    safe_text = _filter_system_leaks(chunk.text)
                    if safe_text:
                        full_response.append(safe_text)

            await asyncio.wait_for(_collect(), timeout=CHAT_AGENT_TIMEOUT_SECS)

            reformulated = "".join(full_response).strip()

            # Strip common uncertainty prefixes that small models emit
            _UNCERTAINTY_PREFIXES = [
                "(Not entirely sure — here's my best answer.)",
                "(Not entirely sure - here's my best answer.)",
                "Not entirely sure — here's my best answer.",
                "Not entirely sure - here's my best answer.",
                "(Not entirely sure)",
                "Not entirely sure",
                "I'm not entirely sure",
                "(I'm not entirely sure)",
                "I am not entirely sure",
                "(I am not entirely sure)",
            ]
            for prefix in _UNCERTAINTY_PREFIXES:
                if reformulated.startswith(prefix):
                    reformulated = reformulated[len(prefix):].strip()

            obs.emit("chat_agent_done", intent=intent.value, response_len=len(reformulated))

            if reformulated and len(reformulated) > 20:
                # Parse the Chat Agent's structured output into:
                #   acknowledgement = Part 1 (friendly confirmation for the user)
                #   reformulated_message = Part 2 (structured instruction for Execution Agent)
                acknowledgement, reformulated_instruction = _parse_chat_agent_output(reformulated)
                
                # v0.11 PERFORMANCE: Cache successful responses
                _chat_agent_cache.set(_cache_key, (reformulated_instruction, acknowledgement))
                
                return reformulated_instruction, acknowledgement
            else:
                return message, ""

        except asyncio.TimeoutError:
            logger.warning("[engine] Chat Agent phase timed out — falling through to agent loop")
            obs.emit("chat_agent_timeout", timeout=CHAT_AGENT_TIMEOUT_SECS)
            return message, ""
        except Exception as e:
            logger.warning(f"[engine] Chat Agent phase failed (non-fatal): {e}")
            obs.emit("chat_agent_failed", error=str(e)[:80])
            return message, ""

    async def _orchestrator_phase(
        self,
        reformulated_message: str,
        intent: Intent,
        session_id: str,
        obs: ObsCollector,
        memory_facts: list[str],
        intent_history: list[str],
    ) -> OrchestrationResult:
        """
        Stage 2 of the three-layer pipeline: Orchestrator plans and assesses confidence.

        Receives the reformulated instruction from the Chat Agent and:
        1. Breaks it into execution steps with specific tools
        2. Assesses confidence (HIGH/MEDIUM/LOW)
        3. If LOW confidence: signals full escalation to user
        4. If MEDIUM confidence: signals one clarifying question
        5. If HIGH confidence: provides structured context for the Execution Agent

        Returns an OrchestrationResult. The caller (process) decides what to do
        based on the confidence level.
        """
        from core.agent.constants import ORCHESTRATOR_ENABLED

        if not ORCHESTRATOR_ENABLED:
            return OrchestrationResult(
                confidence=1.0,
                orchestrator_context="",
            )

        adapter = self._adapter_for(intent)
        self._agent_orchestrator._adapter = adapter

        result = await self._agent_orchestrator.orchestrate(
            reformulated_message=reformulated_message,
            intent=intent,
            adapter=adapter,
            memory_facts=memory_facts,
            intent_history=intent_history,
            obs=obs,
        )

        return result

    async def _chat_agent_reformulate_clarification(
        self,
        original_request: str,
        clarification_question: str,
        user_answer: str,
        session_id: str,
        obs: ObsCollector,
    ) -> str:
        """
        When the user answers an Orchestrator clarification question,
        the Chat Agent reformulates the combined context (original request +
        clarification Q&A) into an updated instruction for the Orchestrator.

        This ensures the user's clarification answer is properly integrated
        with the original request before being sent back to the Orchestrator
        for re-planning. Without this, the Orchestrator would only see the
        user's short answer and lose the original request context.

        Returns the reformulated instruction string.
        """
        from core.agent.constants import CHAT_AGENT_TIMEOUT_SECS
        from core.agent.prompts import build_chat_agent_prompt
        from core.context_builder import _build_environment_context

        env_context = _build_environment_context()

        # Build a specialized prompt for clarification reformulation
        clarification_prompt = f"""You are LocalMind's Chat Agent. The Orchestrator asked a clarification question, and the user has answered. Your job is to REFORMULATE the combined context into a single, precise instruction for the Orchestrator.

{env_context}

ORIGINAL REQUEST:
{original_request}

CLARIFICATION QUESTION ASKED:
{clarification_question}

USER'S ANSWER:
{user_answer}

YOUR TASK:
Combine the original request with the user's clarification answer into a single, precise, structured instruction. The reformulated instruction should:
1. Incorporate the user's answer to resolve the ambiguity
2. Preserve all details from the original request that weren't contradicted
3. Be specific enough for the Orchestrator to create a high-confidence execution plan
4. Include exact file paths, commands, or other specifics mentioned in either the original request or the answer

Respond with ONLY the reformulated instruction — no acknowledgement, no questions, no meta-commentary."""

        messages = [
            {"role": "system", "content": clarification_prompt},
            {"role": "user", "content": f"Original: {original_request}\nClarification: {clarification_question}\nAnswer: {user_answer}"},
        ]

        try:
            adapter = self._adapter_for(Intent.CHAT)
            obs.emit("chat_agent_clarification_start", session_id=session_id[:8])

            full_response: list[str] = []
            async def _collect():
                async for chunk in adapter.chat(
                    messages,
                    temperature=0.3,
                    intent="chat",
                ):
                    safe_text = _filter_system_leaks(chunk.text)
                    if safe_text:
                        full_response.append(safe_text)

            await asyncio.wait_for(_collect(), timeout=CHAT_AGENT_TIMEOUT_SECS)

            reformulated = "".join(full_response).strip()

            obs.emit("chat_agent_clarification_done", response_len=len(reformulated))

            if reformulated and len(reformulated) > 10:
                return reformulated
            else:
                # Fallback: concatenate original request + answer
                return (
                    f"{original_request}\n\n"
                    f"[Clarification: {clarification_question} → {user_answer}]"
                )

        except asyncio.TimeoutError:
            logger.warning("[engine] Chat Agent clarification reformulation timed out — using fallback")
            obs.emit("chat_agent_clarification_timeout", timeout=CHAT_AGENT_TIMEOUT_SECS)
            return (
                f"{original_request}\n\n"
                f"[Clarification: {clarification_question} → {user_answer}]"
            )
        except Exception as e:
            logger.warning(f"[engine] Chat Agent clarification reformulation failed (non-fatal): {e}")
            obs.emit("chat_agent_clarification_failed", error=str(e)[:80])
            return (
                f"{original_request}\n\n"
                f"[Clarification: {clarification_question} → {user_answer}]"
            )

    async def process(
        self,
        message: str,
        session_id: str,
        file: Optional[bytes] = None,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        obs: Optional[ObsCollector] = None,
        original_path: Optional[str] = None,
        client_intent: Optional[str] = None,
        client_confidence: float = 0.0,
    ) -> AsyncIterator[StreamChunk]:
        """
        Process a user message end-to-end and stream chunks.
        Emits structured observability events into obs if provided.
        """
        _obs = obs or ObsCollector()
        t0 = time.monotonic()

        # ── 0. Safety gate ────────────────────────────────────────────────
        is_safe, gate_reason = safety_check(message)
        if not is_safe:
            _obs.emit("safety_blocked", reason=gate_reason[:80])
            yield StreamChunk(text=gate_reason, done=False)
            yield StreamChunk(text="", done=True)
            return

        # ── 1. History ────────────────────────────────────────────────────
        history = self._store.get_history(session_id)

        # ── 1a. Persist user message IMMEDIATELY ─────────────────────────
        # v0.11 CRITICAL FIX: The user message MUST be saved before any
        # LLM calls or streaming. Previously it was saved AFTER streaming,
        # alongside the assistant message. If the generator was interrupted
        # (disconnect, exception), both append() calls were skipped and the
        # entire conversation history was silently lost. The next turn would
        # see empty history and the dispatcher would say "No prior exchange."
        #
        # Note: We load history FIRST (above) so this message doesn't appear
        # in the history for the current turn — only for subsequent turns.
        self._persist_user_message(
            session_id=session_id,
            message=message,
            filename=filename,
            original_path=original_path,
            file=file,
            content_type=content_type,
        )

        # ── 1b. Session CWD ────────────────────────────────────────────────
        # Get the per-session working directory so shell commands execute
        # in the correct directory. Set the context variable so the shell
        # tool can pick it up via _session_cwd_var.
        # Also sync from the terminal session in case the user ran `cd`
        # manually in the terminal UI.
        from api.routes.terminal import _terminal_sessions
        _term_session = _terminal_sessions.get(session_id)
        if _term_session and _term_session.get("cwd"):
            self._session_ctx.sync_from_terminal(_term_session["cwd"])
        session_cwd = self._session_ctx.get_cwd(session_id)
        from tools.shell import set_session_cwd as _set_shell_cwd
        _set_shell_cwd(session_cwd)

        # ── 1a. Attachment flag ──────────────────────────────────────────────
        has_attachment = file is not None

        # ── 2. Capability Inference via ThinkingDispatcher ──────────────────
        # The ThinkingDispatcher is the PRIMARY routing mechanism.
        # It produces a TaskProfile with multi-dimensional capability
        # description instead of a single intent label.
        #
        # ARCHITECTURE v2.0:
        #   Old: RiskAwareRouter → intent label → hardcoded path
        #   New: ThinkingDispatcher → TaskProfile → execution_mode-based routing
        #
        # The TaskProfile includes:
        #   - requires_grounding, requires_tools, requires_planning, etc.
        #   - execution_mode (direct / single_tool / agent_loop / etc.)
        #   - required_tools (derived from capabilities)
        #   - primary_intent (backward compat with tool dispatch)
        #
        # This prevents misrouting like "What is today's EPL games?" being
        # classified as CHAT (conversational tone) when it actually needs
        # requires_grounding=True, realtime_sensitive=True, web_search.
        # v4.0: ThinkingDispatcher is the sole Layer 2 implementation
        adapter = get_adapter(settings.localmind_adapter)
        logger.info("[engine] using adapter: %s (model=%s)", settings.localmind_adapter, getattr(adapter, '_model', '?'))
        _orchestration_plan: OrchestrationPlan | None = None
        _task_profile: TaskProfile | None = None
        _client_intent: Intent | None = None

        # Client-side pre-classification — skip dispatcher for high-confidence
        # client hints. Creates a minimal TaskProfile from the client's hint.
        if client_intent and client_confidence >= 0.9:
            try:
                _client_intent = Intent(client_intent)
                _client_requires_tools = _client_intent != Intent.CHAT
                _client_requires_grounding = _client_intent in (
                    Intent.WEB_SEARCH, Intent.WEB_FETCH, Intent.FILE_TASK, Intent.SYSINFO
                )
                _client_mode = (
                    ExecutionMode.DIRECT if _client_intent == Intent.CHAT
                    else ExecutionMode.SINGLE_TOOL
                )
                # Map client intent to capabilities
                _client_capabilities = []
                _intent_to_cap = {v: k for k, v in CAPABILITY_TO_INTENT.items()}
                if _client_intent in _intent_to_cap:
                    _client_capabilities.append(_intent_to_cap[_client_intent])

                _task_profile = TaskProfile(
                    requires_grounding=_client_requires_grounding,
                    requires_tools=_client_requires_tools,
                    requires_planning=False,
                    requires_memory=False,
                    requires_reasoning=True,
                    realtime_sensitive=_client_intent == Intent.WEB_SEARCH,
                    capabilities=_client_capabilities,
                    execution_mode=_client_mode,
                    confidence=client_confidence,
                    reformulated=message,
                    fast_path=True,
                )
                _orchestration_plan = OrchestrationPlan(profile=_task_profile)
                logger.info(
                    f"[engine] Client pre-classified: {client_intent} "
                    f"(confidence={client_confidence}) — skipping dispatcher"
                )
                _obs.emit("client_preclassified", intent=client_intent, confidence=client_confidence)
            except ValueError:
                _client_intent = None

        if _orchestration_plan is None:
            # No client pre-classification — run the ThinkingDispatcher.
            # The dispatcher streams REAL thinking tokens from the LLM
            # (the model's pre-JSON reasoning) as they arrive — no need
            # for generic "Analyzing..." status placeholders.
            self._dispatcher = ThinkingDispatcher(adapter)

            # Start memory retrieval IN PARALLEL with the dispatcher.
            _memory_task = asyncio.create_task(
                self._memory.compose(
                    query=message,
                    intent=Intent.CHAT,
                    session_id=session_id,
                )
            )

            async for output in self._dispatcher.dispatch(
                message=message,
                history=history,
                memory_facts=[],
                has_attachment=has_attachment,
                obs=_obs,
                session_id=session_id,
                attachment_filename=filename,
            ):
                if isinstance(output, StreamChunk):
                    yield output
                elif isinstance(output, OrchestrationPlan):
                    _orchestration_plan = output
                    _task_profile = output.profile

            if _orchestration_plan is None or _task_profile is None:
                logger.warning("[engine] dispatcher returned no plan — using minimal fallback")
                _task_profile = TaskProfile(
                    capabilities=[],
                    execution_mode=ExecutionMode.DIRECT,
                    confidence=0.5,
                    reformulated=message,
                    reasoning="No plan from dispatcher — minimal fallback",
                )
                _orchestration_plan = OrchestrationPlan(profile=_task_profile)

        # ── 3. Derive routing from TaskProfile ─────────────────────────────
        # The TaskProfile is the source of truth. We derive:
        #   - effective_intent (for backward compat with tool dispatch)
        #   - confidence
        #   - routing decisions
        #
        # IMPORTANT: We no longer use the old Tool Scoring step to resolve
        # intent. The TaskProfile's capability inference is more accurate
        # because it considers multiple dimensions, not just keyword patterns.
        effective_intent = _task_profile.primary_intent()
        confidence = _task_profile.confidence

        # v4.0: Removed legacy CHAT→tool override and SYSINFO safety net.
        # The ThinkingDispatcher's LLM capability inference correctly handles:
        #   - EPL-style queries (grounding + realtime → WEB_SEARCH)
        #   - SYSINFO queries (exact phrases in signal detection + LLM inference)
        # No post-hoc overrides are needed.

        # Track intent history for this session (fed into AgentLoop for follow-ups)
        intent_history = self._update_intent_history(session_id, effective_intent)

        # ── Store profile fields for later use ─────────────────────────────
        _dispatcher_reformulated = _task_profile.reformulated
        _dispatcher_acknowledgement = _task_profile.acknowledgement
        _dispatcher_fast_path = _task_profile.fast_path
        _dispatcher_confidence = _task_profile.confidence
        _execution_mode = _task_profile.execution_mode

        # ── 2b. DIRECT fast-path — skip tool dispatch, stream directly ──
        # When the TaskProfile says execution_mode=DIRECT, no tools,
        # agent loop, or orchestrator are needed. Build context via
        # context_builder and stream directly via adapter.chat().
        #
        # ARCHITECTURE v3.0: We now use _execution_mode (from TaskProfile)
        # instead of effective_intent == Intent.CHAT. This is more accurate
        # because the TaskProfile considers multiple capability dimensions,
        # not just the intent label.
        #
        # ANTI-FABRICATION: The ThinkingDispatcher's capability inference
        # explicitly sets requires_grounding=True and realtime_sensitive=True
        # for time-sensitive queries, preventing them from being routed here.
        # The EPL-style misrouting ("What is today's EPL games?" → CHAT)
        # is now caught by the capability correction in Step 3.
        if _execution_mode == ExecutionMode.DIRECT:
            # Memory retrieval: skip embedding for short messages, but use
            # warm-start facts as a fallback. Short messages like "hi" or
            # "help" can't produce meaningful embedding matches, but the agent
            # should still know basic facts about the user (name, OS, etc.)
            # from recent sessions. Warm-start provides this without any
            # embedding call — it's purely metadata-based scoring.
            word_count = len(message.strip().split())
            if word_count < 5:
                t_warm = time.monotonic()
                memory_facts = await self._memory.warm_start_facts(
                    session_id=session_id,
                    max_facts=3,
                )
                _obs.emit("memory_retrieved",
                          facts=len(memory_facts),
                          latency_ms=round((time.monotonic() - t_warm) * 1000),
                          warm_start=True)
            else:
                t_mem = time.monotonic()
                memory_facts = await self._memory.compose(
                    query=message,
                    intent=effective_intent,
                    session_id=session_id,
                )
                # Complement semantic retrieval with warm-start facts if
                # compose() returned very few results (the query might be
                # about a topic the user hasn't discussed recently, but
                # general context is still useful).
                if len(memory_facts) < 2:
                    warm_facts = await self._memory.warm_start_facts(
                        session_id=session_id,
                        max_facts=2,
                    )
                    # Deduplicate: don't add facts already in memory_facts
                    existing = set(f.lower().strip() for f in memory_facts)
                    for wf in warm_facts:
                        if wf.lower().strip() not in existing:
                            memory_facts.append(wf)
                            existing.add(wf.lower().strip())
                _obs.emit("memory_retrieved",
                          facts=len(memory_facts),
                          latency_ms=round((time.monotonic() - t_mem) * 1000))

            # Build context via context_builder (consistent prompt for all CHAT)
            ctx = EngineContext(
                session_id=session_id,
                message=message,
                intent=effective_intent,
                history=history,
                tool_result=None,
                file_attachment=None,
                memory_facts=memory_facts,
                session_cwd=self._session_ctx.get_cwd(session_id),
            )
            active_adapter = self._adapter_for(effective_intent)
            prompt_messages = context_builder.build(ctx, active_adapter.effective_context_window)
            prompt_messages = await maybe_compress_history(
                prompt_messages, active_adapter, active_adapter.effective_context_window
            )

            # Red-zone preamble for uncertain routing — REMOVED for CHAT path.
            # The Chat Agent's system prompt handles uncertainty naturally
            # ("If you're unsure, mark it..."). An explicit preamble on every
            # uncertain response is trust-destroying noise. Only add a subtle
            # hint for truly ambiguous agent intents, not for normal conversation.
            full_response_chunks: list[str] = []
            _dup_filter = DuplicateFilter()

            _obs.emit("thinking_start", intent="chat")
            self._metrics.start_request()
            async for chunk in active_adapter.chat(prompt_messages, intent="chat"):
                safe_text = _filter_system_leaks(chunk.text)
                # Suppress duplicate paragraphs (small models sometimes loop)
                filtered = _dup_filter.feed(safe_text)
                if filtered:
                    full_response_chunks.append(filtered)
                    yield StreamChunk(text=filtered, done=chunk.done)
            # Record streaming completion — include prompt and completion token
            # breakdown so the frontend metrics bar shows real counts instead of 0/0.
            response_so_far = _dup_filter.text
            token_count = _approx_tokens(response_so_far)
            prompt_token_count = _approx_tokens(
                "".join(m.get("content", "") for m in prompt_messages if isinstance(m, dict))
            )
            self._metrics.record_streaming_complete(
                total_tokens=token_count + prompt_token_count,
                prompt_tokens=prompt_token_count,
                completion_tokens=token_count,
            )
            _obs.emit("thinking_done", intent="chat")

            response_text = "".join(full_response_chunks)

            # ── Post-CHAT fabrication detection (v0.7 enhanced) ──────────────────────
            # After streaming a CHAT response, check if the LLM fabricated tool
            # output despite the anti-fabrication rules in the prompt. Small models
            # (MiniMax, phi3:mini) often ignore prompt instructions and produce
            # fake command output, directory listings, or system specs anyway.
            # v0.7: Also detect fabricated time-sensitive data (sports scores,
            # weather, prices) — when the model answers from training data
            # instead of saying "I need to search the web".
            _FABRICATION_PATTERNS = [
                re.compile(r'Volume Serial Number', re.IGNORECASE),
                re.compile(r'Directory of\s+[A-Za-z]:', re.IGNORECASE),
                re.compile(r'\d+ File\(s\)\s+\d+ bytes', re.IGNORECASE),
                re.compile(r'\d+ Dir\(s\)\s+\d+ bytes', re.IGNORECASE),
                re.compile(r'drwx[rxw-]{9}\s+\d+', re.IGNORECASE),  # Unix ls -la output
                re.compile(r'total \d+\s*\n', re.IGNORECASE),        # Unix ls output header
                re.compile(r'\bI (ran|executed|called|used|invoked)\b.{0,30}\b(command|tool|shell|dir|ls)\b', re.IGNORECASE),
                re.compile(r'\btool:\s*shell\b', re.IGNORECASE),
                re.compile(r'\brunning now\.\.\.\b', re.IGNORECASE),
                re.compile(r'\bactually executing\.\.\.\b', re.IGNORECASE),
                re.compile(r'\bI (just |already )?(ran|checked|listed|read)\b.{0,30}\b(the |your |this )?(directory|folder|file|command)\b', re.IGNORECASE),
                # v0.7: Fabricated time-sensitive data patterns
                # These catch when the model answers from training data for
                # time-sensitive queries (weather, sports, prices, news)
                re.compile(r'\b(current temperature|temperature (is|was|of))\b.{0,20}\d+°', re.IGNORECASE),
                re.compile(r'\b(forecast|weather)\b.{0,30}\d+°(C|F)', re.IGNORECASE),
                re.compile(r'\b(score|result)\b.{0,15}\d+\s*[-–]\s*\d+', re.IGNORECASE),  # "score 2-1"
                re.compile(r'\b(played|vs|versus|against)\b.{0,30}\b(score|won|lost|drew)\b', re.IGNORECASE),
                re.compile(r'\b(table|standings|rankings?)\b.{0,10}\b(1\.|1st|2nd|3rd)', re.IGNORECASE),  # Fabricated league tables
                re.compile(r'\b(fixture|match|game)\b.{0,20}\b(vs|versus|against)\b.{0,30}\b(today|tomorrow|this week|saturday|sunday|monday)', re.IGNORECASE),
                re.compile(r'\b(price|value|rate)\b.{0,20}\$\d+|\€\d+|\£\d+|KES\s*\d+|\₹\d+', re.IGNORECASE),  # Fabricated prices
                re.compile(r'\bas of (my|the) (last|current|latest)\b.{0,15}\b(update|knowledge|information|training)\b', re.IGNORECASE),  # "As of my last update..."
                re.compile(r'\bbased on (my|the) (training|knowledge|available information)\b', re.IGNORECASE),
                re.compile(r'\bI (believe|think|recall|remember)\b.{0,30}\b(the (current|latest|recent))\b', re.IGNORECASE),
            ]
            _fabrication_detected = any(p.search(response_text) for p in _FABRICATION_PATTERNS)
            if _fabrication_detected:
                logger.warning(
                    f"[engine] POST-CHAT FABRICATION DETECTED in session {session_id[:8]}: "
                    f"CHAT response contains fabricated tool output. "
                    f"Message: {message[:60]!r}, Response preview: {response_text[:100]!r}"
                )
                _obs.emit("fabrication_detected",
                          intent="chat",
                          message_preview=message[:60],
                          response_preview=response_text[:100])
                # Note: We cannot retroactively re-run the tool after streaming the
                # fabricated output to the user. The detection serves two purposes:
                # 1. Observability: the event is logged and visible in the UI
                # 2. Flywheel: future routing can learn from this misclassification
                # The anti-fabrication gate (FIX 3) should prevent this from
                # happening in the first place by re-routing before the CHAT path.

            # Capture code blocks for FILE_WRITE recovery
            _FENCE_RE = re.compile(r'```(?P<lang>\w+)?\s*\n(?P<code>[\s\S]+?)\n```', re.IGNORECASE)
            _code_blocks = _FENCE_RE.findall(response_text)
            if _code_blocks:
                _lang, _code = _code_blocks[-1]
                self._last_code[session_id] = {
                    "code": _code,
                    "lang": _lang or "",
                    "original_message": message,
                }

            # Persist assistant message (user message already persisted at start of process())
            self._persist_assistant_message(session_id, response_text)

            total_ms = round((time.monotonic() - t0) * 1000)
            self._metrics.record("chat", latency_ms=total_ms, success=True)
            _prompt_tok = _approx_tokens("".join(m.get("content", "") for m in prompt_messages if isinstance(m, dict)))
            _obs.emit("turn_complete", intent="chat", confidence=round(confidence, 2),
                      tokens_approx=_approx_tokens(response_text),
                      prompt_tokens_approx=_prompt_tok,
                      total_latency_ms=total_ms, memory_facts=len(memory_facts), agent_mode=False)
            self._store_observation(session_id, _obs,
                intent="chat", confidence=round(confidence, 2),
                tools_used="", memory_hits=len(memory_facts),
                context_tokens=_prompt_tok, latency_ms=total_ms)

            # Post-response memory (pass user message for user-initiated fact extraction)
            _safe_task(self._maybe_store_response_facts(response_text, session_id, _obs, user_message=message))

            # Explicitly yield a done chunk so the SSE bridge sends {"type":"done"}
            # to the frontend. Without this, the frontend relies on the stream
            # closing to detect completion — which can be delayed by the final
            # obs flush. The explicit done ensures isStreaming is reset immediately.
            yield StreamChunk(text="", done=True)
            return

        # ── 4+5. File attachment + Memory retrieval (parallel) ─────────────
        # When a file is attached, parse it AND retrieve memory concurrently.
        # These are independent I/O-bound operations — no reason to wait
        # for one before starting the other. Saves ~200-500ms on average.
        #
        # v0.11 LATENCY FIX: When the ThinkingDispatcher was used, memory
        # retrieval was already started in parallel with the dispatcher call.
        # Re-use that task instead of starting a new one, saving another
        # 0.5-3s of sequential waiting.
        _file_attach_coro = None
        if file and filename:
            async def _parse_attachment():
                try:
                    from tools.file_reader import parse_file
                    return await parse_file(
                        data=file,
                        filename=filename,
                        content_type=content_type or "application/octet-stream",
                        chunk_size=settings.localmind_chunk_size_tokens,
                        original_path=original_path,
                    )
                except Exception as e:
                    logger.error(f"[engine] File parsing failed: {e}", exc_info=True)
                    return None

            _file_attach_coro = _parse_attachment()

        # v0.11: Use pre-started memory task if the dispatcher ran in parallel
        # v2.0: Always true now — ThinkingDispatcher is the primary routing.
        _has_prestarted_memory = False
        try:
            _memory_coro = _memory_task  # Already running task from Step 2
            _has_prestarted_memory = True
        except NameError:
            pass

        if not _has_prestarted_memory:
            _memory_coro = self._memory.compose(
                query=message,
                intent=effective_intent,
                session_id=session_id,
            )

        # Run both concurrently when both are needed
        if _file_attach_coro:
            t_parallel = time.monotonic()
            file_attachment, memory_facts = await asyncio.gather(
                _file_attach_coro, _memory_coro,
            )
            parallel_ms = round((time.monotonic() - t_parallel) * 1000)
            if file_attachment:
                logger.info(f"[engine] File parsed successfully: {filename}, {len(file)} bytes")
            _obs.emit("memory_retrieved",
                      facts=len(memory_facts),
                      latency_ms=parallel_ms)
        else:
            file_attachment = None
            t_mem = time.monotonic()
            memory_facts = await _memory_coro
            _obs.emit("memory_retrieved",
                      facts=len(memory_facts),
                      latency_ms=round((time.monotonic() - t_mem) * 1000))

        # Warm-start supplement: if compose() returned very few facts for
        # agent intents, add warm-start facts so the agent still has basic
        # user context (OS, preferences, etc.) even when the query is novel.
        if len(memory_facts) < 2:
            warm_facts = await self._memory.warm_start_facts(
                session_id=session_id,
                max_facts=2,
            )
            existing = set(f.lower().strip() for f in memory_facts)
            for wf in warm_facts:
                if wf.lower().strip() not in existing:
                    memory_facts.append(wf)
                    existing.add(wf.lower().strip())

        # ── 5b. Workspace orchestrator — parallel track ───────────────────
        # Routes tool-bearing intents (SHELL, SYSINFO, FILE_WRITE,
        # CODE_EXEC, MEMORY_OP, FILE_TASK without attachment) through the
        # Plan → Execute → Synthesise loop.
        # WEB_SEARCH is excluded — it goes through direct dispatch + context_builder.
        # FILE_TASK with an attachment uses the inline fast-path below instead.
        # CHAT exits early (step 2b) and never reaches here.
        _file_task_with_attachment = (
            effective_intent == Intent.FILE_TASK and file_attachment is not None
        )

        # ── 5c. Pending write confirmation fast-path ──────────────────────────
        # When the orchestrator's file_write contract hits requires_confirmation,
        # it stores {path, content, filename} here keyed by session_id.
        # On the very next turn, if the user confirms ("yes", "ok", "confirm",
        # "sure", "do it", "go ahead", "write it"), we skip the orchestrator
        # entirely and call _do_write() directly with the stored payload.
        # Any other message cancels the pending write and falls through normally.
        _pending = self._pending_writes.get(session_id)
        if _pending:
            _confirm_words = {"yes", "ok", "okay", "sure", "confirm", "do it",
                              "go ahead", "save", "save it", "write it", "proceed"}
            _msg_lower = message.strip().lower().rstrip("!.")
            if _msg_lower in _confirm_words or _msg_lower.startswith("yes") or _msg_lower.startswith("save"):
                # Execute the stored write immediately
                from pathlib import Path
                from tools.file_writer import _do_write, _safe_output_path
                del self._pending_writes[session_id]
                _obs.emit("workspace_orchestrator_start", intent="file_write")
                _obs.emit("workspace_tool_start", task_id="t1", tool="file_write")
                _filepath = Path(_pending["path"])
                _result = await _do_write(_filepath, _pending["content"])
                _obs.emit("workspace_tool_done", task_id="t1", tool="file_write",
                          latency_ms=0, chars=len(_result.content))
                _text = _result.content
                self._persist_assistant_message(session_id, _text)
                total_ms = round((time.monotonic() - t0) * 1000)
                self._metrics.record("file_write", latency_ms=total_ms, success=_result.success)
                _obs.emit("turn_complete", intent="file_write", confidence=1.0,
                          tokens_approx=_approx_tokens(_text),
                          total_latency_ms=total_ms, memory_facts=0, agent_mode=False)
                self._store_observation(session_id, _obs,
                    intent="file_write", confidence=1.0,
                    tools_used="file_write", memory_hits=0,
                    context_tokens=0, latency_ms=total_ms)
                yield StreamChunk(text=_text, done=False,
                                  metadata={"path": str(_filepath),
                                            "filename": _filepath.name} if _result.success else {})
                yield StreamChunk(text="", done=True,
                                  metadata={"path": str(_filepath),
                                            "filename": _filepath.name} if _result.success else {})
                return
            else:
                # User said something other than yes — cancel the pending write
                logger.info("[engine] pending write cancelled for session %s", session_id)
                del self._pending_writes[session_id]
                # Fall through to normal processing

        # ── 5c-clar. Pending clarification answer routing ───────────────────
        # When the Orchestrator asked a clarification question (MEDIUM confidence)
        # and stored it in _pending_clarification, the user's next message is
        # likely an answer. Route it through the Chat Agent to reformulate the
        # combined context (original request + clarification Q&A) before
        # sending to the Orchestrator again.
        _pending_clar = self._pending_clarification.get(session_id)
        if _pending_clar and effective_intent in AGENT_INTENTS:
            # The user is answering a clarification question — reformulate
            # the combined context and re-run the pipeline.
            del self._pending_clarification[session_id]
            _obs.emit("clarification_answer", original_intent=_pending_clar.get("intent", ""))

            # Route through Chat Agent to reformulate the combined context
            try:
                reformulated_clarification = await self._chat_agent_reformulate_clarification(
                    original_request=_pending_clar["original_request"],
                    clarification_question=_pending_clar["question"],
                    user_answer=message,
                    session_id=session_id,
                    obs=_obs,
                )
                # Inject the reformulated clarification as the agent message
                # This bypasses the normal Chat Agent phase since we already
                # reformulated through the clarification path.
                # The reformulated message will be used directly by the
                # Orchestrator and Execution Agent.
                _clarification_context = (
                    f"[CLARIFICATION RESOLVED]\n"
                    f"Original request: {_pending_clar['original_request']}\n"
                    f"Clarification asked: {_pending_clar['question']}\n"
                    f"User's answer: {message}\n"
                    f"Reformulated instruction: {reformulated_clarification}\n"
                )
                logger.info(
                    "[engine] clarification answered for session %s — "
                    "reformulated (%d chars)",
                    session_id[:8], len(reformulated_clarification),
                )
            except Exception as e:
                logger.warning(f"[engine] clarification reformulation failed (non-fatal): {e}")
                _obs.emit("clarification_reformulate_failed", error=str(e)[:80])
            # Fall through to normal processing with the original message

        # 5d. FILE_WRITE recovery — inject last cached code when user says
        # "save it" / "update the file" without supplying inline code.
        _fence_present = "```" in message
        if (
            effective_intent == Intent.FILE_WRITE
            and session_id in self._last_code
            and not _fence_present
        ):
            _cached = self._last_code.pop(session_id)
            _lang   = _cached.get("lang", "")
            _code   = _cached.get("code", "")
            _orig   = _cached.get("original_message", "")[:80]
            if _code:
                message = (
                    message + "\n\n"
                    "[Content generated from earlier request: \"" + _orig + "\"]\n"
                    "```" + _lang + "\n" + _code + "\n```"
                )
                logger.info(
                    "[engine] FILE_WRITE recovery: injected cached code (%d chars, lang=%s)",
                    len(_code), _lang,
                )

        if _should_use_orchestrator(message, effective_intent) and not _file_task_with_attachment and effective_intent not in (Intent.WEB_SEARCH, Intent.WEB_FETCH):
            _obs.emit("workspace_orchestrator_start", intent=effective_intent.value)
            full_response_chunks: list[str] = []
            # Get fresh adapter for orchestrator
            orch_adapter = get_adapter(settings.localmind_adapter)
            self._orchestrator._adapter = orch_adapter
            async for chunk in self._orchestrator.run(
                message=message,
                session_id=session_id,
                memory_facts=memory_facts,
                obs=_obs,
            ):
                safe = _filter_system_leaks(chunk.text)
                full_response_chunks.append(safe)
                # Capture pending_write payload from done chunk and persist it
                # so the confirmation fast-path can resume on the next turn.
                if chunk.done and chunk.metadata and "pending_write" in chunk.metadata:
                    self._pending_writes[session_id] = chunk.metadata["pending_write"]
                    logger.info(
                        "[engine] pending write stored for session %s → %s",
                        session_id, chunk.metadata["pending_write"].get("path"),
                    )
                yield StreamChunk(text=safe, done=chunk.done, metadata=chunk.metadata)

            response_text = "".join(full_response_chunks)
            self._persist_assistant_message(session_id, response_text)
            total_ms = round((time.monotonic() - t0) * 1000)
            self._metrics.record(effective_intent.value, latency_ms=total_ms, success=True)
            _pt = _approx_tokens("".join(m.get("content", "") for m in prompt_messages if isinstance(m, dict) and m.get("content")))
            _obs.emit("turn_complete", intent=effective_intent.value,
                      confidence=round(confidence, 2),
                      tokens_approx=_approx_tokens(response_text),
                      prompt_tokens_approx=_pt,
                      total_latency_ms=total_ms, memory_facts=len(memory_facts),
                      agent_mode=True)
            self._store_observation(session_id, _obs,
                intent=effective_intent.value, confidence=round(confidence, 2),
                tools_used=effective_intent.value, memory_hits=len(memory_facts),
                context_tokens=_pt, latency_ms=total_ms)
            yield StreamChunk(text="", done=True)
            return

        # ── 6. Tool dispatch ───────────────────────────────────────────
        tool_result: Optional[ToolResult] = None

        # CRITICAL: FILE_TASK and SYSINFO always call real tools.
        # These are handled directly — NOT through the agent loop.
        #
        # WEB_SEARCH and WEB_FETCH were moved to AGENT_INTENTS (agent loop)
        # because the direct dispatch path caused three bugs:
        # 1. The LLM received search results but wanted to search again, and
        #    output minimax:tool_call XML as plain text — leaked to the user.
        # 2. When snippets were thin, the LLM couldn't call web_fetch to read
        #    actual page content, so it fabricated answers from memory fragments.
        # 3. The raw user message was passed as the search query, producing poor
        #    results (e.g., "Cheptais" matched "Chapais" in Quebec).
        # The agent loop lets the model: formulate better queries, chain
        # web_search → web_fetch, and use proper native tool calling.
        _TOOL_LABELS = {
            Intent.WEB_SEARCH: "Searching the web",
            Intent.FILE_TASK:  "Reading file",
            Intent.FILE_WRITE: "Writing file",
            Intent.CODE_EXEC:  "Running code",
            Intent.SHELL:      "Running command",
            Intent.SYSINFO:    "Getting system info",
            Intent.WEB_FETCH:  "Fetching web page",
            Intent.MEMORY_OP:  "Checking memory",
        }

        if effective_intent == Intent.SYSINFO:
            # FILE_TASK was removed from direct dispatch — it now goes through
            # the agent loop (AGENT_INTENTS). Direct dispatch couldn't handle
            # multi-step file operations like "Read my CV 'C:\\Users\\tison\\Documents'"
            # where the path is a directory, not a file. The agent loop can chain
            # shell (list directory) → file_task (read the target file).
            # SHELL was also removed — it goes through the agent loop too.
            # Only SYSINFO remains as direct dispatch because it's instant and offline.
            # Emit a tool_status obs event — renders as an animated ToolStep in the UI,
            # disappears when the response arrives. Never touches the text content stream.
            label = _TOOL_LABELS.get(effective_intent, effective_intent.value)
            _obs.emit("tool_status", tool=effective_intent.value, label=label, status="running")
            logger.info("[engine] Direct tool dispatch for %s", effective_intent.value)
            t_tool = time.monotonic()
            try:
                tool_result = await dispatch(effective_intent, message)
                
                # ── CWD Detection from Tool Output ────────────────────────
                # After dispatching a shell command, check if the output
                # reveals a CWD change (e.g., "cd Documents/Code") and
                # update the session context so subsequent commands run there.
                if tool_result and tool_result.content:
                    new_cwd = SessionContextManager.detect_cwd_change(
                        session_cwd=session_cwd,
                        command=message if effective_intent == Intent.SHELL else None,
                        tool_result_content=tool_result.content,
                    )
                    if new_cwd:
                        self._session_ctx.update_cwd(session_id, new_cwd)
                        session_cwd = new_cwd
                        _set_shell_cwd(session_cwd)
                        logger.info(
                            f"[engine] CWD updated for session {session_id[:8]}: {new_cwd}"
                        )
                
                # Filter injection from tool output
                # FIX: preserve all ToolResult fields when reconstructing —
                # previously success/error_type/error_message were silently dropped,
                # causing failed tools to appear successful to the LLM.
                if tool_result and tool_result.content:
                    filtered_content = _filter_tool_injection(tool_result.content)
                    tool_result = ToolResult(
                        content=filtered_content,
                        risk=tool_result.risk,
                        source=tool_result.source,
                        metadata=tool_result.metadata if hasattr(tool_result, "metadata") else {},
                        requires_confirmation=tool_result.requires_confirmation,
                        success=tool_result.success,
                        error_type=tool_result.error_type,
                        error_message=tool_result.error_message,
                    )
                
                tool_latency = round((time.monotonic() - t_tool) * 1000)
                _obs.emit("tool_dispatched", tool=effective_intent.value, success=bool(tool_result), latency_ms=tool_latency)
                record_tool_outcome(self._store, effective_intent.value, success=bool(tool_result), latency_ms=tool_latency)
                self._metrics.record(effective_intent.value, latency_ms=tool_latency, success=bool(tool_result))

                # Bridge diff metadata from edit_file tool results.
                # When edit_file produces structured diff hunks, emit a
                # file_diff obs event so the frontend DiffBlock can render
                # green/red highlighted diffs — like Cursor/Claude.
                if (tool_result and tool_result.metadata
                    and tool_result.source == "edit_file"
                    and tool_result.metadata.get("diff_hunks")):
                    _obs.emit("file_diff",
                              diff_hunks=tool_result.metadata.get("diff_hunks", []),
                              diff_language=tool_result.metadata.get("diff_language", ""),
                              path=tool_result.metadata.get("path", ""),
                              diff_additions=tool_result.metadata.get("diff_additions", 0),
                              diff_deletions=tool_result.metadata.get("diff_deletions", 0))

                # SYSINFO: stream the raw result directly — no LLM reformatting.
                # The data is factual and structured; passing it through the LLM
                # on a small context window causes hallucination (model ignores the
                # injected result and answers from its training data instead).
                if effective_intent == Intent.SYSINFO and tool_result and tool_result.content:
                    result_text = tool_result.content.strip()
                    _obs.emit("tool_status", tool="sysinfo", label="Getting system info", status="done")
                    self._persist_assistant_message(session_id, result_text)
                    total_ms = round((time.monotonic() - t0) * 1000)
                    self._metrics.record("sysinfo", latency_ms=total_ms, success=True)
                    _obs.emit("turn_complete", intent="sysinfo", confidence=round(confidence, 2),
                              tokens_approx=_approx_tokens(result_text), total_latency_ms=total_ms,
                              memory_facts=0, agent_mode=False)
                    self._store_observation(session_id, _obs,
                        intent="sysinfo", confidence=round(confidence, 2),
                        tools_used="sysinfo", memory_hits=0,
                        context_tokens=0, latency_ms=total_ms)
                    yield StreamChunk(text=result_text, done=False)
                    yield StreamChunk(text="", done=True)
                    return

            except Exception as e:
                logger.error(f"Direct tool dispatch failed for {effective_intent.value}: {e}")
                _obs.emit("tool_failed", tool=effective_intent.value, error=str(e)[:80])
                # Structural feedback: tool dispatch failure.
                self._flywheel.mark_tool_failure(session_id)
                tool_result = None
        
        # ── FILE_TASK fast-path for uploaded files ────────────────────────
        # The file already read in ~0ms. The only remaining work is the LLM
        # call that processes the content. On small models (gemma3:1b etc.)
        # the full context_builder pipeline injects history + memory + system
        # prompt + tool result + file chunks, easily blowing the context window
        # and causing a 180s timeout with no output.
        #
        # Fix: build a minimal prompt — system instruction + file content +
        # user message ONLY. No history. No memory. No tool_result duplication.
        # Token budget capped to 60% of context window to leave headroom for
        # generation. Stream directly and return, bypassing steps 7-10 build.
        if effective_intent == Intent.FILE_TASK and file_attachment:
            _obs.emit("tool_status", tool="file_task", label="Reading file", status="done")
            active_adapter = self._adapter_for(effective_intent)
            cw = active_adapter.effective_context_window

            # Build file content block.
            # Hard cap at 6000 tokens (~24000 chars) regardless of context window —
            # small local models (gemma3:1b) hang or time out processing large contexts
            # even when the window technically fits. Beyond ~6k tokens the model's
            # attention degrades and generation stalls.
            MAX_FILE_TOKENS = 6000
            file_char_budget = min(round(cw * 0.40) * 4, MAX_FILE_TOKENS * 4)
            all_chunks = "\n\n---\n\n".join(file_attachment.chunks)
            if len(all_chunks) > file_char_budget:
                all_chunks = all_chunks[:file_char_budget] + "\n\n[... content truncated for performance]"

            # Response contract: structured output for summarize/general queries;
            # direct answer for specific questions. The contract ensures consistent,
            # scannable output regardless of model size.
            _file_ext = file_attachment.filename.rsplit(".", 1)[-1].lower() if "." in file_attachment.filename else ""
            _is_doc = _file_ext in ("pdf", "docx", "doc", "txt", "md")
            _contract = (
                "\n\nWhen asked to summarize or describe the file, respond using this structure:\n"
                "**Document type:** <type>\n"
                "**Key entities:** <names, organisations, dates, amounts — comma separated>\n"
                "**Summary:** <3–5 sentence overview>\n"
                "**Important clauses / details:** <bullet list of notable items, or 'None' if not applicable>\n\n"
                "For specific questions, answer directly without this structure."
            ) if _is_doc else ""

            _file_system = (
                "You are LocalMind. A file has been uploaded. Read it carefully and respond to the user's request.\n"
                "Only reference content that is actually in the file."
                f"{_contract}\n\n"
                f"[File: {file_attachment.filename}]\n{all_chunks}"
            )
            # Include last 2 history turns so follow-up messages (e.g. "What about this one?")
            # have prior context. Capped at 4 messages (2 turns) to protect context budget.
            _file_messages: list[dict] = [{"role": "system", "content": _file_system}]
            _recent_history = [m for m in history if m.role.value in ("user", "assistant")][-4:]
            for _hm in _recent_history:
                _file_messages.append({"role": _hm.role.value, "content": _hm.content[:800]})

            _file_messages.append({"role": "user", "content": message})

            # Pass intent so the per-intent timeout (OLLAMA_TIMEOUT_FILE_TASK) is used.
            # Without intent=, the adapter falls back to the default 120s client timeout.
            full_response: list[str] = []
            self._metrics.start_request()
            async for chunk in active_adapter.chat(_file_messages, temperature=0.0, intent="file_task"):
                safe = _filter_system_leaks(chunk.text)
                full_response.append(safe)
                yield StreamChunk(text=safe, done=chunk.done)
            response_text = "".join(full_response)
            token_count = _approx_tokens(response_text)
            _prompt_token_count = _approx_tokens(
                "".join(m.get("content", "") for m in _file_messages if isinstance(m, dict))
            )
            self._metrics.record_streaming_complete(
                total_tokens=token_count + _prompt_token_count,
                prompt_tokens=_prompt_token_count,
                completion_tokens=token_count,
            )

            response_text = "".join(full_response)
            _obs.emit("tool_status", tool="file_task", label="Reading file", status="done")
            self._persist_assistant_message(session_id, response_text)
            total_ms = round((time.monotonic() - t0) * 1000)
            self._metrics.record("file_task", latency_ms=total_ms, success=True)
            _ft_prompt_tok = _approx_tokens("".join(m.get("content", "") for m in _file_messages if isinstance(m, dict)))
            _obs.emit("turn_complete", intent="file_task", confidence=round(confidence, 2),
                      tokens_approx=_approx_tokens(response_text), prompt_tokens_approx=_ft_prompt_tok,
                      total_latency_ms=total_ms,
                      memory_facts=len(memory_facts), agent_mode=False)
            self._store_observation(session_id, _obs,
                intent="file_task", confidence=round(confidence, 2),
                tools_used="file_task", memory_hits=len(memory_facts),
                context_tokens=_ft_prompt_tok, latency_ms=total_ms)
            yield StreamChunk(text="", done=True)
            return
        # Agent intents (CODE_EXEC, FILE_WRITE, FILE_EDIT, FILE_TASK, MEMORY_OP, SHELL) get tool result in agent loop
        if effective_intent in AGENT_INTENTS:
            # No initial dispatch - agent loop handles it
            pass
        elif effective_intent == Intent.SYSINFO:
            # Already dispatched above — tool_result is set; preserve it for context builder
            pass
        # CHAT and other unhandled intents get no tool result
        else:
            tool_result = None

        # ── 7a-chat. Chat Agent phase (acknowledge + reformulate) ────────────
        agent_message = message  # Default: use original message
        orchestrator_context = ""  # Will be set by orchestrator if enabled
        _skip_orchestrator = False  # v0.11: skip orchestrator when dispatcher has high confidence
        _skip_planning = False      # v0.11: skip agent planning when dispatcher has high confidence
        if effective_intent in AGENT_INTENTS:
            # Yield a status update so the user knows what's happening
            # (previously: the user saw "Thinking..." with no indication of progress)
            # v0.10: Enhanced status messages with context-aware descriptions
            # that tell the user EXACTLY what's about to happen, not just a
            # generic "Working on it". The status is also emitted as a
            # status_update SSE event so the frontend can show it in real-time.
            _STATUS_MESSAGES = {
                Intent.WEB_SEARCH: "Let me search the web for that...",
                Intent.WEB_FETCH: "Let me fetch that web page...",
                Intent.CODE_EXEC: "Let me run that code...",
                Intent.FILE_WRITE: "Let me create that file...",
                Intent.FILE_EDIT: "Let me edit that file...",
                Intent.FILE_TASK: "Let me read that file...",
                Intent.SHELL: "Let me run that command...",
                Intent.MEMORY_OP: "Let me check my memory...",
            }
            _status_msg = _STATUS_MESSAGES.get(effective_intent, f"Working on that...")
            yield StreamChunk(text="", done=False, status=_status_msg)

            # v0.10: Yield status for Chat Agent phase
            yield StreamChunk(
                text="", done=False,
                status=f"Understanding your request...",
            )
            # ThinkingDispatcher already reformulated and acknowledged?
            # Skip the Chat Agent phase — the dispatcher already did this work.
            if not _dispatcher_fast_path and _dispatcher_reformulated:
                reformulated = _dispatcher_reformulated
                acknowledgement = _dispatcher_acknowledgement
                if acknowledgement:
                    yield StreamChunk(text="", done=False, status=acknowledgement)
                agent_message = reformulated

                # v0.11 LATENCY FIX: When the dispatcher already determined
                # intent with HIGH confidence (≥0.7), the Orchestrator and
                # Agent Planning are redundant — they just re-do the same
                # classification and planning work. Skip them to save 5-16s.
                #
                # The dispatcher already:
                # - Classified intent with reasoning
                # - Reformulated the instruction
                # - Assessed confidence
                # Running the Orchestrator (another LLM call, 3-10s) and
                # Agent Planning (another LLM call, 2-6s) on top adds latency
                # without value when the dispatcher was confident.
                if _dispatcher_confidence >= 0.7:
                    _skip_orchestrator = True
                    _skip_planning = True
                    _obs.emit("dispatcher_high_confidence_skip",
                              confidence=round(_dispatcher_confidence, 2),
                              skipped=["orchestrator", "planning"])
                    logger.info(
                        "[engine] dispatcher confidence %.2f ≥ 0.7 — "
                        "skipping orchestrator + planning (saves ~5-16s)",
                        _dispatcher_confidence,
                    )
            else:
                # v0.11 PHASE 3 OPTIMIZATION: For trivial high-confidence CHAT intents,
                # skip directly to context building without running Chat Agent at all.
                # The dispatcher already reformulated for simple intents.
                # This saves 2-5s for ~15-20% of requests.
                _is_trivial = (
                    effective_intent == Intent.CHAT and
                    _dispatcher_confidence >= 0.8 and
                    len(message.strip()) < 100
                )
                
                if _is_trivial and _dispatcher_reformulated:
                    # Dispatcher already handled it — skip Chat Agent entirely
                    reformulated = _dispatcher_reformulated
                    acknowledgement = ""
                    logger.info(f"[engine] Fast path: trivial CHAT, skipping Chat Agent")
                else:
                    # Fast-path or dispatcher didn't reformulate — run Chat Agent as fallback
                    reformulated, acknowledgement = await self._chat_agent_phase(
                        message=message,
                        intent=effective_intent,
                        session_id=session_id,
                        obs=_obs,
                        memory_facts=memory_facts,
                        intent_history=intent_history,
                    )
                if acknowledgement:
                    # Stream the acknowledgement to the user immediately
                    # v0.10: Show acknowledgement as status_update (visible in thinking
                    # area) rather than inline text that gets mixed with the final answer.
                    yield StreamChunk(text="", done=False, status=acknowledgement)
                agent_message = reformulated

            # ── 7a-orch. Orchestrator phase (plan + confidence check) ────────
            # Three-layer pipeline: after Chat Agent reformulates, the
            # Orchestrator plans execution steps and assesses confidence.
            # - HIGH confidence: inject plan into Execution Agent and proceed
            # - MEDIUM confidence: ask one clarifying question via Chat Agent
            # - LOW confidence: escalate fully to user and stop
            #
            # v0.11: SKIPPED when dispatcher returned high confidence (≥0.7).
            # The dispatcher already did classification + reformulation +
            # confidence assessment. Running the orchestrator on top just
            # burns 3-10s for no additional value.
            from core.agent.constants import ORCHESTRATOR_ENABLED
            if ORCHESTRATOR_ENABLED and not _skip_orchestrator:
                # Yield a planning status update so the user isn't in the dark
                yield StreamChunk(
                    text="", done=False,
                    status="Planning the best approach...",
                )

                orch_result = await self._orchestrator_phase(
                    reformulated_message=agent_message,
                    intent=effective_intent,
                    session_id=session_id,
                    obs=_obs,
                    memory_facts=memory_facts,
                    intent_history=intent_history,
                )

                if orch_result.should_escalate:
                    # LOW confidence — stop and ask the user for more detail
                    _obs.emit("orchestrator_escalate", confidence=round(orch_result.confidence, 2))
                    question = orch_result.clarification_question or (
                        "I'm not sure I understand exactly what you'd like me to do. "
                        "Could you provide more detail about what you need?"
                    )
                    self._persist_assistant_message(session_id, question)
                    total_ms = round((time.monotonic() - t0) * 1000)
                    self._metrics.record(effective_intent.value, latency_ms=total_ms, success=True)
                    _obs.emit("turn_complete", intent=effective_intent.value,
                              confidence=round(orch_result.confidence, 2),
                              tokens_approx=_approx_tokens(question),
                              total_latency_ms=total_ms,
                              memory_facts=len(memory_facts),
                              agent_mode=False,
                              orchestrator_escalated=True)
                    self._store_observation(session_id, _obs,
                        intent=effective_intent.value, confidence=round(orch_result.confidence, 2),
                        tools_used="", memory_hits=len(memory_facts),
                        context_tokens=0, latency_ms=total_ms)
                    yield StreamChunk(text=question, done=False)
                    yield StreamChunk(text="", done=True)
                    return

                elif orch_result.should_ask_clarification:
                    # MEDIUM confidence — ask one clarifying question but
                    # still proceed with execution using best-guess plan
                    _obs.emit("orchestrator_clarify", confidence=round(orch_result.confidence, 2))
                    clarification = orch_result.clarification_question
                    if clarification:
                        # Store the clarification for potential follow-up routing.
                        # When the user answers this question on the next turn,
                        # the engine will route the answer through the Chat Agent
                        # to reformulate the combined context before re-running
                        # the Orchestrator.
                        self._pending_clarification[session_id] = {
                            "question": clarification,
                            "original_request": message,
                            "reformulated_message": agent_message,
                            "intent": effective_intent.value,
                        }
                        # v0.10: Show clarification as status_update instead of
                        # inline text, so it appears in the thinking area and
                        # doesn't get mixed with the final answer.
                        yield StreamChunk(
                            text="", done=False,
                            status=f"Quick question: {clarification}",
                        )

                # HIGH confidence or MEDIUM (proceeding with best-guess):
                # Inject orchestrator context into the execution agent
                if orch_result.orchestrator_context:
                    orchestrator_context = orch_result.orchestrator_context

        # ── 7. Build context ───────────────────────────────────────────────
        ctx = EngineContext(
            session_id=session_id,
            message=agent_message,
            intent=effective_intent,
            history=history,
            tool_result=tool_result,
            file_attachment=file_attachment,
            memory_facts=memory_facts,
            session_cwd=self._session_ctx.get_cwd(session_id),
        )

        active_adapter = self._adapter_for(effective_intent)
        prompt_messages = context_builder.build(ctx, active_adapter.effective_context_window)
        prompt_messages = await maybe_compress_history(
            prompt_messages, active_adapter, active_adapter.effective_context_window
        )

        # ── 7a/7b. Stream response ─────────────────────────────────────────
        full_response_chunks: list[str] = []

        # ── 7b. Agent loop (CHAT fast-path exits above) ───────────────────────

        # ── 7b-small. Small-model FILE_WRITE fast-path ────────────────────
        # Models ≤3B / phi3:mini cannot reliably produce valid tool-call JSON
        # for the agent loop — they hallucinate asking for "tool results"
        # instead of invoking the tool.  For these models we bypass the agent
        # loop entirely:
        #   1. Stream the response as a plain CHAT call (model writes code/content)
        #   2. Capture the last code block from the response
        #   3. Write the file directly via _do_write() — no LLM tool-calling needed
        #   4. Append a confirmation line so the UI shows the file link
        if effective_intent == Intent.FILE_WRITE and _is_small_model(active_adapter._model):
            logger.info(
                "[engine] FILE_WRITE small-model fast-path for %s (model=%s)",
                session_id[:8], active_adapter._model,
            )
            _obs.emit("tool_status", tool="file_write", label="Writing file", status="running")

            # Use CHAT adapter and CHAT-intent context (no tool_result injection)
            ctx_sm = EngineContext(
                session_id=session_id,
                message=message,
                intent=Intent.CHAT,
                history=history,
                tool_result=None,
                file_attachment=file_attachment,
                memory_facts=memory_facts,
                session_cwd=self._session_ctx.get_cwd(session_id),
            )
            sm_adapter = self._adapter_for(Intent.CHAT)
            sm_messages = context_builder.build(ctx_sm, sm_adapter.effective_context_window)
            sm_messages = await maybe_compress_history(
                sm_messages, sm_adapter, sm_adapter.effective_context_window
            )

            _obs.emit("thinking_start", intent="file_write")
            async for chunk in sm_adapter.chat(sm_messages, intent="chat"):
                safe_text = _filter_system_leaks(chunk.text)
                full_response_chunks.append(safe_text)
                yield StreamChunk(text=safe_text, done=False)
            _obs.emit("thinking_done", intent="file_write")

            response_text = "".join(full_response_chunks)

            # Extract last code block and write it to disk
            _FENCE_RE_SM = re.compile(r'```(?P<lang>\w+)?\s*\n(?P<code>[\s\S]+?)\n```', re.IGNORECASE)
            sm_blocks = _FENCE_RE_SM.findall(response_text)
            if sm_blocks:
                from tools.file_writer import _infer_filename, _extract_requested_dir, _do_write, resolve_write_path, PathUnresolvableError
                import os as _os
                from core.config import settings as _s

                _lang, _code = sm_blocks[-1]
                _filename = _infer_filename(message, _lang)
                _requested_dir = _extract_requested_dir(message)
                _home = Path(_os.path.expandvars(_s.localmind_home)).expanduser().resolve()
                _scratch = _home / _filename

                _final_dest = None
                if _requested_dir:
                    _raw = _requested_dir.rstrip("/''") + "/" + _filename
                    try:
                        _final_dest = resolve_write_path(_raw, fallback_filename=_filename)
                    except PathUnresolvableError:
                        _final_dest = None

                write_result = await _do_write(_scratch, _code, final_dest=_final_dest)
                if write_result.metadata and write_result.metadata.get("path"):
                    _written_path = write_result.metadata["path"]
                    _written_name = write_result.metadata.get("filename", Path(_written_path).name)
                    confirm_text = f"\n\n✅ Saved as **{_written_name}** → `{_written_path}`"
                    full_response_chunks.append(confirm_text)
                    yield StreamChunk(
                        text=confirm_text,
                        done=False,
                        metadata={"path": _written_path, "filename": _written_name},
                    )
                    self._last_code[session_id] = {"code": _code, "lang": _lang or "", "original_message": message}
                    _obs.emit("tool_status", tool="file_write", label="Writing file", status="done")

            response_text = "".join(full_response_chunks)
            yield StreamChunk(text="", done=True)

            self._persist_assistant_message(session_id, response_text)

            total_ms = round((time.monotonic() - t0) * 1000)
            self._metrics.record("file_write", latency_ms=total_ms, success=True)
            _obs.emit("turn_complete", intent="file_write", confidence=round(confidence, 2),
                      tokens_approx=_approx_tokens(response_text),
                      total_latency_ms=total_ms, memory_facts=len(memory_facts), agent_mode=False)
            self._store_observation(session_id, _obs,
                intent="file_write", confidence=round(confidence, 2),
                tools_used="file_write", memory_hits=len(memory_facts),
                context_tokens=0, latency_ms=total_ms)
            _safe_task(self._maybe_store_response_facts(response_text, session_id, _obs, user_message=message))
            yield StreamChunk(text="", done=True)
            return

        if effective_intent in AGENT_INTENTS:
            _obs.emit("agent_loop_start", intent=effective_intent.value)
            label = _TOOL_LABELS.get(effective_intent, effective_intent.value)
            _obs.emit("tool_status", tool=effective_intent.value, label=label, status="running")

            # The agent loop and planning phase produce their own thinking
            # tokens and status updates. We should NOT emit a hardcoded
            # status here that uses the user's raw message — that reveals
            # the system's mechanical interpretation instead of the model's
            # actual reasoning. The model should interpret intent, decide
            # the right query, and the thinking block should show that
            # reasoning in real-time.
            #
            # Previously this emitted "Searching the web for: Should I carry
            # an umbrella today in Kitengela?" — literally the user's raw
            # message as the search query. Instead, the model should think
            # "User is asking about rain probability in Kitengela → I need
            # weather data → I'll search for 'Kitengela weather today'" and
            # that reasoning should appear in the thinking block.

            # ── Sub-agent delegation for complex multi-domain tasks ────────────
            # When the request is complex enough to need multiple specialized
            # agents (e.g., "build a todo app and write a README"), we decompose
            # the task and delegate to sub-agents instead of using the standard
            # agent loop. This gives each sub-task a focused persona and
            # restricted tool set, reducing hallucination and improving quality.
            from core.agent.sub_agent import (
                should_use_sub_agents, decompose_task, execute_sub_tasks,
                SubAgentRegistry,
            )
            if should_use_sub_agents(message, effective_intent, confidence):
                _obs.emit("sub_agent_delegation", intent=effective_intent.value)
                logger.info(
                    "[engine] sub-agent delegation for session=%s intent=%s",
                    session_id[:8], effective_intent.value,
                )
                try:
                    _registry = SubAgentRegistry()
                    sub_tasks = await decompose_task(message, _registry, active_adapter)
                    if sub_tasks and len(sub_tasks) >= 2:
                        _obs.emit("sub_agent_decomposed", task_count=len(sub_tasks))
                        execution = await execute_sub_tasks(
                            message=message,
                            sub_tasks=sub_tasks,
                            registry=_registry,
                            adapter=active_adapter,
                            obs=_obs,
                        )
                        if execution.success and execution.final_output:
                            response_text = execution.final_output
                            yield StreamChunk(text=response_text, done=False)
                            yield StreamChunk(text="", done=True)

                            # Persist assistant message
                            self._persist_assistant_message(session_id, response_text)
                            total_ms = round((time.monotonic() - t0) * 1000)
                            self._metrics.record(
                                effective_intent.value,
                                latency_ms=total_ms,
                                success=True,
                            )
                            _obs.emit(
                                "turn_complete",
                                intent=effective_intent.value,
                                confidence=round(confidence, 2),
                                tokens_approx=_approx_tokens(response_text),
                                prompt_tokens_approx=_approx_tokens("".join(m.get("content", "") for m in prompt_messages if isinstance(m, dict) and m.get("content"))),
                                total_latency_ms=total_ms,
                                memory_facts=len(memory_facts),
                                agent_mode=True,
                                sub_agents=len(sub_tasks),
                                synthesized=execution.synthesized,
                            )
                            # Post-response memory
                            _safe_task(
                                self._maybe_store_response_facts(
                                    response_text, session_id, _obs,
                                    user_message=message,
                                )
                            )
                            # P12: Reflection on sub-agent results
                            # Sub-agent results are especially prone to fabrication
                            # because each sub-agent operates with limited context.
                            # Run reflection to catch cross-agent inconsistencies.
                            if REFLECT_ENABLED and effective_intent in REFLECT_INTENTS:
                                _safe_task(
                                    self._reflect_on_answer(
                                        response_text, effective_intent,
                                        message, session_id, _obs,
                                    )
                                )
                            return
                        else:
                            # Sub-agent execution failed — fall through to
                            # standard agent loop as a recovery path.
                            logger.info(
                                "[engine] sub-agent execution failed — "
                                "falling back to agent loop (session=%s)",
                                session_id[:8],
                            )
                    # else: decomposition returned <2 tasks — not multi-domain,
                    # fall through to standard agent loop.
                except Exception as e:
                    logger.warning(
                        "[engine] sub-agent delegation error: %s — "
                        "falling back to agent loop", e,
                    )

            # ── Small-model fast-paths for CODE_EXEC and MEMORY_OP ────────────
            # gemma3:1b / phi3:mini / ≤3B models cannot produce valid tool-call JSON.
            # FILE_WRITE has its own fast-path above.  Here we cover the remaining
            # AGENT_INTENTS: CODE_EXEC and MEMORY_OP.
            if _is_small_model(active_adapter._model):
                if effective_intent == Intent.CODE_EXEC:
                    # Extract code from message and dispatch directly — no LLM tool-calling
                    logger.info(
                        "[engine] CODE_EXEC small-model fast-path for %s (model=%s)",
                        session_id[:8], active_adapter._model,
                    )
                    # dispatch_with_retry imported at module level — do NOT re-import here
                    code_result, code_failed, _ = await dispatch_with_retry(Intent.CODE_EXEC, message)
                    if code_result and not code_failed:
                        safe_output = _filter_code_output(code_result.content)
                        # Stream the raw output + a short LLM explanation
                        _obs.emit("tool_status", tool="code_exec", label="Running code", status="done")
                        explanation_messages = prompt_messages + [{
                            "role": "user",
                            "content": f"Code output:\n```\n{safe_output[:2000]}\n```\nBriefly explain what happened.",
                        }]
                        full_response_chunks: list[str] = []
                        async for chunk in active_adapter.chat(explanation_messages, intent="code_exec"):
                            safe = _filter_system_leaks(chunk.text)
                            full_response_chunks.append(safe)
                            yield StreamChunk(text=safe, done=chunk.done)
                        response_text = "".join(full_response_chunks)
                    else:
                        response_text = f"Code execution failed: {code_result.content if code_result else 'unknown error'}"
                        yield StreamChunk(text=response_text, done=False)
                        yield StreamChunk(text="", done=True)
                    self._persist_assistant_message(session_id, response_text)
                    total_ms = round((time.monotonic() - t0) * 1000)
                    self._metrics.record("code_exec", latency_ms=total_ms, success=not code_failed)
                    _obs.emit("turn_complete", intent="code_exec", confidence=round(confidence, 2),
                              tokens_approx=_approx_tokens(response_text),
                              total_latency_ms=total_ms, memory_facts=len(memory_facts), agent_mode=False)
                    self._store_observation(session_id, _obs,
                        intent="code_exec", confidence=round(confidence, 2),
                        tools_used="code_exec", memory_hits=len(memory_facts),
                        context_tokens=0, latency_ms=total_ms)
                    return

                elif effective_intent == Intent.MEMORY_OP:
                    # Dispatch memory op directly — no LLM needed for store/recall
                    logger.info(
                        "[engine] MEMORY_OP small-model fast-path for %s (model=%s)",
                        session_id[:8], active_adapter._model,
                    )
                    # dispatch_with_retry imported at module level — do NOT re-import here
                    mem_result, mem_failed, _ = await dispatch_with_retry(Intent.MEMORY_OP, message)
                    _obs.emit("tool_status", tool="memory_op", label="Checking memory", status="done")
                    if mem_result and not mem_failed:
                        response_text = mem_result.content
                    else:
                        response_text = f"Memory operation failed: {mem_result.content if mem_result else 'unknown error'}"
                    yield StreamChunk(text=response_text, done=False)
                    yield StreamChunk(text="", done=True)
                    self._persist_assistant_message(session_id, response_text)
                    total_ms = round((time.monotonic() - t0) * 1000)
                    self._metrics.record("memory_op", latency_ms=total_ms, success=not mem_failed)
                    _obs.emit("turn_complete", intent="memory_op", confidence=round(confidence, 2),
                              tokens_approx=_approx_tokens(response_text),
                              total_latency_ms=total_ms, memory_facts=len(memory_facts), agent_mode=False)
                    self._store_observation(session_id, _obs,
                        intent="memory_op", confidence=round(confidence, 2),
                        tools_used="memory_op", memory_hits=len(memory_facts),
                        context_tokens=0, latency_ms=total_ms)
                    return

            # Get fresh adapter for agent loop
            agent_adapter = get_adapter(settings.localmind_adapter)
            logger.info("[engine] agent loop adapter: %s type=%s model=%s",
                       settings.localmind_adapter, type(agent_adapter).__name__, getattr(agent_adapter, '_model', '?'))
            self._agent_loop._adapter = agent_adapter
            # Track metrics for agent-mode intents (SHELL, CODE_EXEC, etc.)
            # Without this, the status bar shows 0 tok/s and 0ms latency because
            # start_request() was only called in the CHAT path.
            self._metrics.start_request()
            async for chunk in self._agent_loop.run(
                messages=prompt_messages,
                intent=effective_intent,
                initial_tool_result=tool_result,
                available_tools=available_tools(),
                confidence=confidence,
                adapter=active_adapter,
                intent_history=intent_history,
                obs=_obs,
                memory_facts=memory_facts,
                orchestrator_context=orchestrator_context or None,
                skip_planning=_skip_planning,
            ):
                safe_text = _filter_system_leaks(chunk.text)
                full_response_chunks.append(safe_text)
                yield StreamChunk(text=safe_text, done=chunk.done)

            # ── FIX: Mark the top-level tool_status as done after agent loop completes ──
            # Without this, the frontend's "Running command" spinner stays stuck because
            # we emitted tool_status=running at the start of the agent loop but never
            # emitted tool_status=done when it finishes. The agent loop emits done events
            # for individual tool calls, but the top-level intent tool_status is separate.
            label = _TOOL_LABELS.get(effective_intent, effective_intent.value)
            _obs.emit("tool_status", tool=effective_intent.value, label=label, status="done")
            _obs.emit("thinking_done", intent=effective_intent.value)
        else:
            # CHAT and other non-agent intents: direct stream, no loop overhead.
            # Emit thinking_start so the UI shows a thinking indicator, then stream.
            _obs.emit("thinking_start", intent=effective_intent.value)
            async for chunk in active_adapter.chat(prompt_messages, intent=effective_intent.value):
                safe_text = _filter_system_leaks(chunk.text)
                full_response_chunks.append(safe_text)
                yield StreamChunk(text=safe_text, done=chunk.done)
            _obs.emit("thinking_done", intent=effective_intent.value)

        response_text = "".join(full_response_chunks)

        # Strip uncertainty prefixes from the final response in agent loop path
        _UNCERTAINTY_PREFIXES_FINAL = [
            "(Not entirely sure — here's my best answer.)",
            "(Not entirely sure - here's my best answer.)",
            "Not entirely sure — here's my best answer.",
            "Not entirely sure - here's my best answer.",
            "(Not entirely sure)",
            "Not entirely sure",
            "I'm not entirely sure",
            "(I'm not entirely sure)",
            "I am not entirely sure",
            "(I am not entirely sure)",
        ]
        for prefix in _UNCERTAINTY_PREFIXES_FINAL:
            if response_text.startswith(prefix):
                response_text = response_text[len(prefix):].strip()

        # ── 7b-metrics. Record streaming completion for agent-mode paths ───────
        # CHAT and FILE_TASK call record_streaming_complete() inside their own
        # streaming blocks.  Agent-mode intents (SHELL, CODE_EXEC, etc.) stream
        # through the agent loop but never record token counts — leaving the
        # status bar showing 0 tokens and 0 tok/s.  Compute approximate metrics
        # from the response text now that we have it.
        if effective_intent in AGENT_INTENTS:
            _agent_token_count = _approx_tokens(response_text)
            _prompt_tokens_approx = _approx_tokens(
                "".join(m.get("content", "") for m in prompt_messages if isinstance(m, dict))
            )
            self._metrics.record_streaming_complete(
                total_tokens=_agent_token_count + _prompt_tokens_approx,
                prompt_tokens=_prompt_tokens_approx,
                completion_tokens=_agent_token_count,
            )

        # ── 7b. Capture last code block for FILE_WRITE recovery ──────────────
        # If the model streamed fenced code (common when intent is CHAT but user
        # asked for code), cache it so a follow-up "save it" / "update the file"
        # can write the actual file instead of showing code in chat again.
        _FENCE_RE = re.compile(r'```(?P<lang>\w+)?\s*\n(?P<code>[\s\S]+?)\n```', re.IGNORECASE)
        _code_blocks = _FENCE_RE.findall(response_text)
        if _code_blocks:
            _lang, _code = _code_blocks[-1]  # use last (most likely the updated version)
            self._last_code[session_id] = {
                "code": _code,
                "lang": _lang or "",
                "original_message": message,
            }
            logger.debug("[engine] cached last code block for session %s (%s, %d chars)",
                         session_id, _lang, len(_code))

        # Collapse the running tool status indicator now that we have a response
        if effective_intent in _TOOL_LABELS:
            _obs.emit("tool_status", tool=effective_intent.value,
                      label=_TOOL_LABELS[effective_intent], status="done")

        # ── 8. Secondary intent ────────────────────────────────────────────
        if secondary_intent:
            match secondary_intent:
                case Intent.FILE_WRITE if tool_result:
                    try:
                        from tools.file_writer import write_response
                        await write_response(message=message, content=response_text)
                    except Exception as e:
                        logger.warning(f"Secondary FILE_WRITE failed: {e}")
                case Intent.MEMORY_OP:
                    # Secondary memory op — fire-and-forget, same as primary path
                    _safe_task(
                        self._extract_and_store_facts(message, session_id, _obs)
                    )
                case _:
                    logger.debug(
                        f"[engine] secondary intent {secondary_intent.value} — no handler, skipping"
                    )

        # ── 9. Memory persistence ──────────────────────────────────────────
        # Both storage calls are fire-and-forget: they must not block the
        # caller (client is waiting for stream close / next request).
        # _safe_task logs any exceptions — no silent data loss.
        if effective_intent == Intent.MEMORY_OP:
            _safe_task(
                self._extract_and_store_facts(message, session_id, _obs)
            )

        # Post-response memory: assistant's own answer can surface new facts.
        _safe_task(
            self._maybe_store_response_facts(response_text, session_id, _obs, user_message=message)
        )

        # Post-response reflection: fire-and-forget self-critique for
        # fabrication-prone intents. Runs AFTER streaming is done.
        if REFLECT_ENABLED and effective_intent in REFLECT_INTENTS:
            _safe_task(
                self._reflect_on_answer(
                    response_text, effective_intent, message, session_id, _obs,
                )
            )

        # ── 10. Persist history ────────────────────────────────────────────
        self._persist_assistant_message(session_id, response_text)

        total_ms = round((time.monotonic() - t0) * 1000)
        self._metrics.record(effective_intent.value, latency_ms=total_ms, success=True)
        _final_prompt_tok = _approx_tokens("".join(m.get("content", "") for m in prompt_messages if isinstance(m, dict)))
        _obs.emit("turn_complete",
                  intent=effective_intent.value,
                  confidence=round(confidence, 2),
                  tokens_approx=_approx_tokens(response_text),
                  prompt_tokens_approx=_final_prompt_tok,
                  total_latency_ms=total_ms,
                  memory_facts=len(memory_facts),
                  agent_mode=effective_intent in AGENT_INTENTS)
        self._store_observation(session_id, _obs,
            intent=effective_intent.value, confidence=round(confidence, 2),
            tools_used=effective_intent.value, memory_hits=len(memory_facts),
            context_tokens=_final_prompt_tok, latency_ms=total_ms)

        # Explicitly yield done so the frontend resets isStreaming immediately.
        yield StreamChunk(text="", done=True)

        # GUARANTEE: The API route's _event_stream() has a finally block
        # that calls _guarantee_persist_assistant() to catch any case where
        # the generator was interrupted before reaching this point.

    # The following methods are defined in the mixin submodules:
    #   _guarantee_persist_assistant  → _persistence_mixin.py
    #   _extract_and_store_facts      → _memory_mixin.py
    #   _maybe_store_response_facts   → _memory_mixin.py
    #   _store_fact_if_valid          → _memory_mixin.py
    #   _simple_similarity            → _memory_mixin.py
    #   _reflect_on_answer            → _reflection_mixin.py