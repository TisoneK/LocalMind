"""LocalMind parent-agent runtime.

This is the request execution boundary. It owns lifecycle concerns only:
safety, history, context assembly, streaming, persistence, and observability.
The ParentAgent owns the actual decision loop and tool/delegation choices.

The old engine pipeline classified each request, selected a tool, and then
chose an agent. This runtime deliberately does none of that. Every user turn
enters one parent AgentLoop with the full parent tool contract. The parent's
initialization call decides whether the turn is direct conversation,
clarification, or tool work. Specialized agents are reached only through the
parent's delegation tools.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import sqlite3
import time
from typing import AsyncIterator, Optional

from agents.parent import ParentAgent
from core.agent.constants import AGENT_ALLOWED_TOOLS
from core.agent.loop import AgentLoop, TerminalProviderError
from core.anomalies import detect_turn_anomalies
from core.config import settings
from core.context_builder import build as build_context
from core.decision_ledger import format_ledger_hint
from core.engine._helpers import _approx_tokens
from core.engine._memory_mixin import _MemoryMixin
from core.engine._persistence_mixin import _PersistenceMixin
from core.engine._reflection_mixin import _ReflectionMixin
from core.engine.stage_clock import _StageClock
from core.episode_memory import EpisodeMemory, format_episode_hint
from core.failure_memory import format_recall_hint
from core.flywheel import FlywheelLogger
from core.memory import MemoryComposer
from core.metrics import MetricsStore
from core.model_router import best_model_for, update_pulled_models
from core.models import AgentAbortedError, EngineContext, Intent, Message, Role, StreamChunk
from core.obs import ObsCollector
from core.observation import ObservationSnapshot
from core.safety_gate import check as safety_check
from core.session_context import SessionContextManager
from core.workspace_state import snapshot as workspace_snapshot
from storage.db import SessionStore
from tools import available_tools


def get_adapter(*args, **kwargs):
    """Resolve through the public engine seam so adapter changes are patchable."""
    from core.engine import get_adapter as _real_get_adapter

    return _real_get_adapter(*args, **kwargs)

logger = logging.getLogger(__name__)

STEERING_QUEUE_MAX = 10


class _ParentAdapterCompat:
    """Give simple chat-only adapters the parent loop's tool-call seam.

    Production adapters implement native ``chat_with_tools``. This narrow
    fallback is useful for local/test adapters and still keeps the request in
    the parent AgentLoop; it does not create a direct execution path.
    """

    def __init__(self, base):
        self._base = base

    def __getattr__(self, name):
        return getattr(self._base, name)

    async def chat_with_tools(self, messages, tools, temperature=0.3, intent=None, tool_choice=None):
        return self._base.chat(messages, temperature=temperature, intent=intent)


class AgentRuntime(_MemoryMixin, _PersistenceMixin, _ReflectionMixin):
    """Single front door for LocalMind's parent-agent execution model.

    Every user turn crosses the same parent boundary. Request interpretation
    belongs to the parent's model-owned initialization stage, not to a
    runtime regex or deterministic prompt shortcut.
    """

    def __init__(self):
        self._store = SessionStore(settings.localmind_db_path)
        self._memory = MemoryComposer()
        self._metrics = MetricsStore()
        self._flywheel = FlywheelLogger()
        # One reusable loop object is the parent runtime's execution seam.
        # AgentLoop receives the request adapter at run time, so this object
        # remains safe when settings or tests change providers between turns.
        self._agent_loop = AgentLoop(adapter=None)
        self._episodes = EpisodeMemory(store=self._store)
        self._session_ctx = SessionContextManager()
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._steering_queues: dict[str, asyncio.Queue] = {}
        self._abort_events: dict[str, asyncio.Event] = {}
        self._last_observation: dict[str, dict] = {}
        self._last_observation_snapshots: dict[str, ObservationSnapshot] = {}
        # Session-scoped lifecycle state retained by the transport boundary;
        # it is not used for routing or tool selection.
        self._intent_history: dict[str, list[str]] = {}
        self._pending_writes: dict[str, dict] = {}
        self._pending_clarification: dict[str, dict] = {}
        self._last_code: dict[str, dict] = {}
        self._last_active_session_id = ""
        self._last_turn_prompt_tokens = 0
        self._last_turn_session_id = ""
        self._warmed_up = False

    async def startup(self) -> None:
        """Refresh adapter metadata and warm local memory best-effort."""
        try:
            adapter = get_adapter(settings.localmind_adapter)
            update_pulled_models(await adapter.list_models())
        except Exception as exc:
            logger.warning("[agent-runtime] model refresh failed (non-fatal): %s", exc)

        if self._warmed_up:
            return
        if settings.localmind_adapter == "ollama":
            try:
                await self._memory._store.warmup()
            except Exception as exc:
                logger.warning("[agent-runtime] memory warmup failed (non-fatal): %s", exc)
        self._warmed_up = True
        try:
            asyncio.create_task(self._episodes.sweep())
        except RuntimeError:
            pass

    def _lock_for(self, session_id: str) -> asyncio.Lock:
        if len(self._session_locks) > 200:
            for sid in list(self._session_locks)[:100]:
                self._session_locks.pop(sid, None)
        return self._session_locks.setdefault(session_id, asyncio.Lock())

    def _queue_for(self, session_id: str) -> asyncio.Queue:
        return self._steering_queues.setdefault(
            session_id, asyncio.Queue(maxsize=STEERING_QUEUE_MAX)
        )

    def _abort_for(self, session_id: str) -> asyncio.Event:
        return self._abort_events.setdefault(session_id, asyncio.Event())

    def abort(self, session_id: str) -> bool:
        self._abort_for(session_id).set()
        return True

    def steer(self, session_id: str, message: str) -> bool:
        text = (message or "").strip()
        if not text:
            return False
        try:
            self._queue_for(session_id).put_nowait(
                {"role": "user", "content": text, "steering": True}
            )
            return True
        except asyncio.QueueFull:
            return False

    def _adapter_for_parent(self):
        model = best_model_for(Intent.ANALYZE, fallback=settings.ollama_model)
        return get_adapter(settings.localmind_adapter, model_override=model)

    # Compatibility names for transport and existing integrations. These are
    # lifecycle helpers only; none of them selects a tool or bypasses the
    # ParentAgent loop.
    def _adapter_for(self, intent: Intent):
        return self._adapter_for_parent()

    def _persist_user_message(self, session_id: str, message: str, **file_data) -> None:
        self._persist_user(session_id, message, **file_data)

    def _persist_assistant_message(self, session_id: str, response_text: str) -> None:
        self._persist_assistant(session_id, response_text)

    def _guarantee_persist_assistant(self, session_id: str, response_chunks: list[str]) -> None:
        response_text = "".join(response_chunks).strip()
        if not response_text:
            return
        try:
            # Must check the LATEST assistant message. get_history() orders ASC,
            # so `limit=2` there returned the OLDEST two messages and the dedup
            # silently failed for any multi-turn session — double-persisting
            # every reply from turn 2 on (visible as duplicated transcript
            # messages after reopening a chat).
            recent = self._store.get_recent_history(session_id, limit=2)
            if any(
                msg.role == Role.ASSISTANT and msg.content.strip() == response_text
                for msg in recent
            ):
                return
            self._persist_assistant(session_id, response_text)
        except Exception:
            logger.exception("[agent-runtime] guaranteed assistant persistence failed")

    def build_observation_snapshot(
        self,
        obs: Optional[ObsCollector] = None,
        cwd: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> ObservationSnapshot:
        collector = obs or ObsCollector()
        snapshot = ObservationSnapshot.from_collector(
            workspace=workspace_snapshot(cwd, include_turn_diff=cwd is None),
            collector=collector,
        )
        if session_id:
            if len(self._last_observation_snapshots) >= 200:
                self._last_observation_snapshots.pop(next(iter(self._last_observation_snapshots)))
            self._last_observation_snapshots[session_id] = snapshot
        return snapshot

    def cleanup_session(self, session_id: str) -> None:
        for state in (
            self._session_locks,
            self._steering_queues,
            self._abort_events,
            self._last_observation,
            self._last_observation_snapshots,
            self._intent_history,
            self._pending_writes,
            self._pending_clarification,
            self._last_code,
        ):
            state.pop(session_id, None)
        self._session_ctx.clear_session(session_id)
        if self._last_turn_session_id == session_id:
            self._last_turn_prompt_tokens = 0
            self._last_turn_session_id = ""
        try:
            with sqlite3.connect(settings.localmind_db_path, timeout=5) as conn:
                conn.execute("DELETE FROM todos WHERE session_id = ?", (session_id,))
                conn.commit()
        except Exception:
            logger.debug("[agent-runtime] todo cleanup skipped", exc_info=True)

    def _update_intent_history(self, session_id: str, intent: Intent) -> None:
        self._intent_history.setdefault(session_id, []).append(intent.value)

    def _emit_todo_plan(self, session_id: str, intent: Intent, message: str, obs: ObsCollector) -> None:
        """No-op compatibility hook: the parent AgentLoop owns planning/todos."""
        obs.emit("parent_plan_owned", session_id=session_id, intent=intent.value)

    def _persist_user(self, session_id: str, message: str, **file_data) -> None:
        try:
            self._store.append(
                session_id,
                Message(role=Role.USER, content=message, **file_data),
            )
        except Exception:
            logger.exception("[agent-runtime] failed to persist user message")

    def _persist_assistant(self, session_id: str, text: str) -> None:
        if not text.strip():
            return
        try:
            self._store.append(
                session_id,
                Message(role=Role.ASSISTANT, content=text),
            )
        except Exception:
            logger.exception("[agent-runtime] failed to persist assistant message")

    async def _memory_facts(self, message: str, session_id: str) -> list[str]:
        try:
            facts = await self._memory.retrieve_for_task(
                query=message,
                intent=Intent.ANALYZE,
                session_id=session_id,
                task_type="",
            )
            if len(facts) < 2:
                for fact in await self._memory.warm_start_facts(session_id=session_id, max_facts=2):
                    if fact not in facts:
                        facts.append(fact)
            episode = format_episode_hint(
                self._store.latest_episode(exclude_session_id=session_id)
            )
            if episode:
                facts.append(episode)
            return facts
        except Exception:
            logger.debug("[agent-runtime] memory retrieval skipped", exc_info=True)
            return []

    @staticmethod
    def _failure_source_intent(obs: ObsCollector, failure_evt) -> str:
        """Use the failed tool as the memory key when the parent is generic."""
        if failure_evt.data.get("intent") not in (None, "", Intent.ANALYZE.value):
            return str(failure_evt.data["intent"])
        for evt in reversed(obs.history()):
            if evt.type == "tool_call" and evt.data.get("status") == "failed":
                return str(evt.data.get("tool", Intent.ANALYZE.value))
        return Intent.ANALYZE.value

    def _store_observation(self, session_id: str, obs: ObsCollector, **data) -> None:
        if len(self._last_observation) > 200:
            for sid in list(self._last_observation)[:100]:
                self._last_observation.pop(sid, None)
        tool_names = [
            str(evt.data.get("tool"))
            for evt in obs.history()
            if evt.type == "tool_call" and evt.data.get("tool")
        ]
        merged = {
            **self._last_observation.get(session_id, {}),
            **data,
            "tools_used": ",".join(dict.fromkeys(tool_names)),
        }
        stage_timings = {
            str(evt.data.get("stage")): {
                "latency_ms": evt.data.get("latency_ms", 0),
                "status": evt.data.get("status", "done"),
            }
            for evt in obs.history()
            if evt.type == "stage_timing" and evt.data.get("stage")
        }
        if stage_timings:
            merged["stage_timings"] = stage_timings

        tool_timings: dict[str, dict] = {}
        for evt in obs.history():
            if evt.type != "tool_call":
                continue
            tool = str(evt.data.get("tool", ""))
            if not tool:
                continue
            try:
                latency_ms = int(evt.data.get("latency_ms", 0) or 0)
            except (TypeError, ValueError):
                continue
            entry = tool_timings.setdefault(
                tool,
                {"calls": 0, "total_ms": 0, "avg_ms": 0, "max_ms": 0, "last_status": "done"},
            )
            entry["calls"] += 1
            entry["total_ms"] += latency_ms
            entry["max_ms"] = max(entry["max_ms"], latency_ms)
            entry["avg_ms"] = round(entry["total_ms"] / entry["calls"])
            entry["last_status"] = str(evt.data.get("status", "done"))
        if tool_timings:
            merged["tool_timings"] = tool_timings

        try:
            completion_tokens = next(
                (
                    evt.data.get("tokens_approx", 0) or 0
                    for evt in reversed(obs.history())
                    if evt.type == "turn_complete"
                ),
                0,
            )
            anomalies = detect_turn_anomalies(
                session_id=session_id,
                latency_ms=merged.get("latency_ms", 0) or 0,
                completion_tokens=completion_tokens,
                context_tokens=merged.get("context_tokens", 0) or 0,
                is_first_turn=session_id not in self._last_observation,
                prev_prompt_tokens=self._last_turn_prompt_tokens,
                prev_session_id=self._last_turn_session_id,
            )
            if anomalies:
                merged["anomalies"] = anomalies
                for anomaly in anomalies:
                    obs.emit("anomaly", **anomaly)
        except Exception:
            logger.debug("[agent-runtime] anomaly detection skipped", exc_info=True)

        self._last_observation[session_id] = merged
        self._last_turn_prompt_tokens = int(merged.get("context_tokens", 0) or 0)
        self._last_turn_session_id = session_id

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
        allowed_tool_names: Optional[set[str]] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Run one user turn through the LocalMind parent agent."""
        async with self._lock_for(session_id):
            self._steering_queues[session_id] = asyncio.Queue(maxsize=STEERING_QUEUE_MAX)
            self._abort_events[session_id] = asyncio.Event()
            async for chunk in self._process_unlocked(
                message=message,
                session_id=session_id,
                file=file,
                filename=filename,
                content_type=content_type,
                obs=obs,
                original_path=original_path,
                client_intent=client_intent,
                client_confidence=client_confidence,
                allowed_tool_names=allowed_tool_names,
            ):
                yield chunk

    async def _process_unlocked(
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
        allowed_tool_names: Optional[set[str]] = None,
    ) -> AsyncIterator[StreamChunk]:
        collector = obs or ObsCollector()
        started = time.monotonic()
        safe, reason = safety_check(message)
        if not safe:
            collector.emit("safety_blocked", reason=reason[:120])
            yield StreamChunk(text=reason, done=False)
            yield StreamChunk(text="", done=True)
            return

        collector.emit("agent_runtime_start", agent="parent")
        if client_intent:
            collector.emit(
                "routing_hint_ignored",
                hint=client_intent,
                confidence=client_confidence,
                reason="parent agent owns tool selection",
            )

        history = self._store.get_history(session_id)
        self._persist_user(
            session_id,
            message,
            file_name=filename,
            file_path=original_path,
            file_size=len(file) if file else None,
            file_type=content_type,
        )

        # ADR-37: no hardcoded stage narration. The parent's real model
        # output (acknowledgement + thinking stream) is the status signal;
        # the frontend's neutral fallback covers the pre-first-token gap.

        try:
            from api.routes.terminal import _terminal_sessions
            terminal = _terminal_sessions.get(session_id)
            if terminal and terminal.get("cwd"):
                self._session_ctx.sync_from_terminal(terminal["cwd"])
        except Exception:
            pass
        session_cwd = self._session_ctx.get_cwd(session_id)
        try:
            from tools.shell import set_session_cwd
            set_session_cwd(session_cwd)
        except Exception:
            pass

        # ADR-34 B-7: kick off nonessential memory + attachment work as a
        # concurrent task so the model-owned initializer can start without
        # waiting behind it.  The initializer only needs the user message +
        # recent history + tool catalog; memory_facts and attachment context
        # are consumed by the execution loop AFTER the initializer returns.
        # On a healthy provider the initializer takes multi-second TTFB, so
        # overlapping it with memory retrieval saves the full memory latency
        # instead of serializing it.
        async def _gather_nonessential() -> tuple[list[str], Optional[dict]]:
            facts = await self._memory_facts(message, session_id)
            try:
                failures = self._store.recall_failures(message=message, intent=Intent.ANALYZE.value)
                hint = format_recall_hint(failures)
                if hint:
                    facts.append(hint)
            except Exception:
                logger.debug("[agent-runtime] failure memory recall skipped", exc_info=True)
            try:
                hint = format_ledger_hint(self._store.recall_decisions(task_type=""))
                if hint:
                    facts.append(hint)
            except Exception:
                logger.debug("[agent-runtime] decision memory recall skipped", exc_info=True)
            attach = None
            if file and filename:
                try:
                    from tools.file_reader import parse_file
                    attach = await parse_file(
                        data=file,
                        filename=filename,
                        content_type=content_type or "application/octet-stream",
                        chunk_size=settings.localmind_chunk_size_tokens,
                        original_path=original_path,
                    )
                except Exception as exc:
                    collector.emit("attachment_failed", error=str(exc)[:120])
            return facts, attach

        nonessential_task = asyncio.create_task(_gather_nonessential())

        adapter = self._adapter_for_parent()
        if not inspect.iscoroutinefunction(getattr(adapter, "chat_with_tools", None)):
            adapter = _ParentAdapterCompat(adapter)
        context_window = getattr(adapter, "effective_context_window", 8192)
        if not isinstance(context_window, (int, float)) or context_window <= 0:
            context_window = 8192

        # Await nonessential work before build_context — but the task has been
        # running concurrently with the adapter setup above, so the effective
        # wait is only the unoverlapped tail.
        try:
            memory_facts, attachment = await nonessential_task
        except Exception:
            logger.debug("[agent-runtime] nonessential gather failed; proceeding with empty context", exc_info=True)
            memory_facts, attachment = [], None

        collector.emit("agent_context_ready", memory_facts=len(memory_facts), attachment=bool(attachment))
        self._metrics.start_request()
        clock = _StageClock(collector)
        clock.mark("intent_classify", 0, "skipped")
        clock.start("context_build")
        prompt_messages = build_context(
            EngineContext(
                session_id=session_id,
                message=message,
                intent=Intent.ANALYZE,
                history=history,
                file_attachment=attachment,
                memory_facts=memory_facts,
                session_cwd=session_cwd,
            ),
            int(context_window),
        )
        clock.end("context_build")
        clock.skip("tool_select")
        clock.start("generate")

        parent = ParentAgent(adapter=adapter, loop=self._agent_loop)
        requested_tools = frozenset(allowed_tool_names) if allowed_tool_names is not None else AGENT_ALLOWED_TOOLS
        parent_tools = requested_tools.intersection(AGENT_ALLOWED_TOOLS)
        response_chunks: list[str] = []
        usage: dict[str, int] = {}
        try:
            async for chunk in parent.run(
                messages=prompt_messages,
                intent=Intent.ANALYZE,
                initial_tool_result=None,
                available_tools=available_tools(),
                confidence=1.0,
                adapter=adapter,
                obs=collector,
                memory_facts=memory_facts,
                allowed_tool_names=parent_tools,
                steering_queue=self._queue_for(session_id),
                abort_signal=self._abort_for(session_id),
                task_type="",
                reformulated_message=message,
            ):
                if chunk.usage:
                    usage.update(chunk.usage)
                # Error chunks are terminal transport events. Do not let the
                # parent runtime's completion bookkeeping turn a provider
                # failure into the generic "no usable answer" fallback.
                if chunk.error:
                    yield chunk
                    return
                if chunk.text:
                    response_chunks.append(chunk.text)
                    if chunk.done:
                        yield chunk.model_copy(update={"done": False})
                        continue
                # The parent runtime owns the transport completion marker.
                # Child loop completion is an internal boundary and must not
                # create duplicate user-facing `done` events.
                if chunk.done:
                    continue
                yield chunk
        except TerminalProviderError as exc:
            collector.emit("agent_loop_error", error=exc.raw[:120], terminal=True)
            # chat.py owns the one canonical normalization/presentation
            # boundary; keep the raw adapter string internal to this chunk.
            yield StreamChunk(text="", done=True, error=exc.raw)
            return
        except AgentAbortedError:
            collector.emit("agent_runtime_aborted", agent="parent")
            yield StreamChunk(text="⏹ Stopped by user.", done=False)

        clock.end("generate")
        clock.mark("execute", 0, "done" if any(evt.type == "tool_call" for evt in collector.history()) else "skipped")

        response_text = "".join(response_chunks).strip()
        # Prompt-token estimate when the provider omits streaming usage.
        # A DIRECT turn only sent the compact initialization prompt to the
        # provider — the full assembled context (build_context) was prepared
        # but never sent. Approximating that full context over-counted ~5x and
        # grew with conversation history (Session 233: a greeting reported
        # ~5,100 tokens when ~900 were actually sent). So when the provider
        # gives no usage and no tool ran, estimate from the initialization
        # prompt that was actually sent, not the unsent full context.
        provider_prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        if provider_prompt_tokens:
            prompt_tokens = provider_prompt_tokens
        else:
            had_tool_calls = any(evt.type == "tool_call" for evt in collector.history())
            init_prompt_chars = 0
            for evt in collector.history():
                chars = evt.data.get("init_prompt_chars") if isinstance(evt.data, dict) else None
                if chars:
                    init_prompt_chars = int(chars)
                    break
            if not had_tool_calls and init_prompt_chars:
                prompt_tokens = max(1, init_prompt_chars // 4)
            else:
                prompt_tokens = _approx_tokens(
                    "".join(str(m.get("content", "")) for m in prompt_messages)
                )
        completion_tokens = int(
            usage.get("completion_tokens", 0) or _approx_tokens(response_text)
        )
        if not response_text:
            hit_limit = any(
                evt.type == "agent_loop_done" and bool(evt.data.get("hit_limit"))
                for evt in collector.history()
            )
            if hit_limit:
                response_text = (
                    "I hit the iteration limit before completing this request. "
                    "Tell me to continue and I will pick up from the last verified step."
                )
            else:
                response_text = (
                    "I ran the parent agent loop, but it produced no usable final answer. "
                    "The Actions panel shows the work that actually ran."
                )
            yield StreamChunk(text=response_text, done=False)

        for evt in collector.history():
            if evt.type == "agent_loop_failure":
                try:
                    self._store.record_failure(
                        session_id=session_id,
                        intent=self._failure_source_intent(collector, evt),
                        message=message,
                        failure_type=evt.data.get("failure_type", ""),
                        summary=evt.data.get("summary", ""),
                    )
                except Exception:
                    logger.debug("[agent-runtime] failure memory write skipped", exc_info=True)
                break

        if response_text:
            self._metrics.record_streaming_complete(
                total_tokens=int(usage.get("prompt_tokens", 0) or 0)
                + int(usage.get("completion_tokens", 0) or 0),
                prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
                completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            )

        # Reflection and response-fact extraction remain post-turn services;
        # they never make routing decisions or expose child tool output.
        try:
            await self._maybe_store_response_facts(response_text, session_id, collector, user_message=message)
        except Exception:
            logger.debug("[agent-runtime] response fact extraction skipped", exc_info=True)
        try:
            await self._reflect_on_answer(response_text, Intent.ANALYZE, message, session_id, collector)
        except Exception:
            logger.debug("[agent-runtime] reflection skipped", exc_info=True)
        self._persist_assistant(session_id, response_text)
        total_ms = round((time.monotonic() - started) * 1000)
        # prompt_tokens/completion_tokens were normalized above, with a local
        # estimate when a provider omits streaming usage.
        collector.emit(
            "agent_runtime_done",
            agent="parent",
            elapsed_ms=total_ms,
            response_chars=len(response_text),
        )
        collector.emit(
            "turn_complete",
            intent="parent",
            confidence=1.0,
            tokens_approx=completion_tokens,
            prompt_tokens_approx=prompt_tokens,
            total_latency_ms=total_ms,
            memory_facts=len(memory_facts),
            agent_mode=True,
            provider_usage=usage,
        )
        self._store_observation(
            session_id,
            collector,
            intent="parent",
            confidence=1.0,
            memory_hits=len(memory_facts),
            context_tokens=prompt_tokens,
            latency_ms=total_ms,
        )
        yield StreamChunk(text="", done=True, usage=usage)
