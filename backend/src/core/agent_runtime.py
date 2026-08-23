"""LocalMind parent-agent runtime.

This is the request execution boundary. It owns lifecycle concerns only:
safety, history, context assembly, streaming, persistence, and observability.
The ParentAgent owns the actual decision loop and tool/delegation choices.

The old engine pipeline classified each request, selected a tool, and then
chose an agent. This runtime deliberately does none of that. Every user turn
enters one parent AgentLoop with the boot-owned parent contract and native tool
surface. The first parent call can answer in prose or select tools. Specialized
agents are reached only through the parent's delegation tools.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import sqlite3
import time
from typing import AsyncIterator, Optional

from agents.parent import ParentAgent
from core.agent.constants import AGENT_ALLOWED_TOOLS
from core.agent.loop import AgentLoop, TerminalProviderError
from core.agent_workspace import build_workspace_artifacts
from core.anomalies import detect_turn_anomalies
from core.config import settings

# Compatibility export: the parent kernel no longer calls the legacy generic
# builder, but integrations/tests may still patch this symbol.
from core.context_builder import build as build_context  # noqa: F401 — compatibility patch seam
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
from core.model_router import update_pulled_models
from core.models import AgentAbortedError, Intent, Message, Role, StreamChunk
from core.obs import ObsCollector
from core.observation import ObservationSnapshot
from core.parent_kernel import ParentKernel, active_parent_model
from core.parent_session import ParentSession
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

# Session 266: the persisted tool-call timeline must respect the same
# presentation boundary as the SSE bridge (chat.py): delegated child output
# is intermediate model context, not user-facing content.
_INTERNAL_DELEGATION_TOOLS = frozenset({"delegate", "delegate_parallel", "delegate_inline"})


def _visible_tool_output(tool_name: str, agent_name: str | None, output: str) -> str:
    """Mirror of chat.py's bridge filter for the persisted tool timeline."""
    if agent_name or tool_name in _INTERNAL_DELEGATION_TOOLS:
        return ""
    return output


def _collect_tool_calls(collector: ObsCollector) -> list[dict]:
    """Build the tool-call timeline (pills) from the collector's obs events.

    Same shape and stable-id scheme as chat.py's ``_tool_call_payload`` so the
    frontend restores the same step cards it saw live. Dedupes by id (a
    started event followed by its done event collapses into one row)."""
    calls: dict[str, dict] = {}
    for evt in collector.history():
        if evt.type != "tool_call":
            continue
        d = evt.data
        tool = str(d.get("tool", "unknown"))
        label = d.get("label", tool)
        status = d.get("status", "running")
        iteration = d.get("iteration", "")
        args_str = d.get("tool_args", "")
        args_hash = "-" + hashlib.md5(args_str.encode()).hexdigest()[:6] if args_str else ""
        tc_id = f"tc-{tool}-iter{iteration}{args_hash}"
        agent = d.get("agent") or None
        calls[tc_id] = {
            "id": tc_id,
            "name": tool,
            "label": label,
            "status": status,
            "iteration": iteration,
            "latency_ms": d.get("latency_ms", ""),
            "output": _visible_tool_output(tool, agent, d.get("output", "")),
            "tool_args": args_str,
            "todo_id": d.get("todo_id") or None,
            "reasoning": d.get("reasoning") or d.get("thought"),
            "agent": agent,
            "provider": d.get("provider") or None,
        }
    return list(calls.values())


def _summarize_tool_actions(collector: ObsCollector) -> str:
    """One-line summary of the most significant tool actions this turn.

    Folded into the ParentSession's rolling summary so the summary records
    what the agent *did* (tool calls), not just what it said (prose). Bounded
    to the first 3 distinct tools to keep the summary entry compact — a long
    tool list is noise, the names of the actions taken are the signal.
    """
    seen: list[str] = []
    for evt in collector.history():
        if evt.type != "tool_call":
            continue
        d = evt.data
        if d.get("status") not in ("completed", "done", "success"):
            continue
        tool = str(d.get("tool", "unknown"))
        args = str(d.get("tool_args", "") or "").strip()
        # Compact the args to a short hint (first 60 chars, single line).
        args_hint = args.replace("\n", " ")[:60]
        entry = f"{tool}({args_hint})" if args_hint else tool
        if entry not in seen:
            seen.append(entry)
        if len(seen) >= 3:
            break
    return ", ".join(seen)


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

    Every user turn crosses the same native parent boundary. Request
    interpretation belongs to the parent model, not to a runtime regex,
    per-turn initializer, or deterministic prompt shortcut.
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
        self._parent_kernel: ParentKernel | None = None
        self._parent_agent: ParentAgent | None = None
        # Readiness transitions queued since the last turn. Drained onto the
        # next turn's ObsCollector so the frontend SSE learns the parent's
        # boot-time state (ready / degraded / recovered) without needing a
        # separate push channel. Each entry: {"event": str, "reason": str}.
        self._pending_readiness: list[dict[str, str]] = []
        self._parent_readiness_emitted: bool = False
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

    async def _ensure_parent_kernel(self, *, refresh_provider: bool = False) -> ParentKernel:
        """Return the boot-owned kernel, rebuilding it after settings changes.

        Records readiness transitions on ``self._pending_readiness`` so the
        next turn's SSE stream carries ``parent_ready`` / ``parent_degraded``
        / ``parent_recovered`` to the frontend. The kernel's ``degraded_reason``
        field remains the authoritative state; this queue is the wire-level
        notification channel.
        """
        was_degraded = bool(self._parent_kernel and self._parent_kernel.degraded_reason)
        if self._parent_kernel and self._parent_kernel.matches_current_settings():
            return self._parent_kernel

        model = active_parent_model()
        adapter = get_adapter(settings.localmind_adapter, model_override=model)
        degraded_reason = ""
        if refresh_provider:
            try:
                update_pulled_models(await adapter.list_models())
            except Exception as exc:
                degraded_reason = str(exc)[:180]
                logger.warning("[parent-kernel] provider warmup degraded: %s", degraded_reason)

        self._parent_kernel = ParentKernel.build(
            adapter,
            available_tools(),
            degraded_reason=degraded_reason,
        )
        self._parent_agent = ParentAgent(adapter=adapter, loop=self._agent_loop)
        # Queue the readiness transition for the next turn's SSE. The first
        # build emits ``parent_ready`` (or ``parent_degraded``); a rebuild
        # that recovers from a prior degraded state emits ``parent_recovered``.
        if degraded_reason:
            self._pending_readiness.append({"event": "parent_degraded", "reason": degraded_reason})
        elif was_degraded:
            self._pending_readiness.append({"event": "parent_recovered", "reason": ""})
        else:
            self._pending_readiness.append({"event": "parent_ready", "reason": ""})
        logger.info(
            "[parent-kernel] %s adapter=%s model=%s tools=%d%s",
            "ready" if self._parent_kernel.ready else "degraded",
            settings.localmind_adapter,
            model or "(default)",
            len(self._parent_kernel.available_tools),
            f" reason={degraded_reason}" if degraded_reason else "",
        )
        return self._parent_kernel

    def drain_pending_readiness(self) -> list[dict[str, str]]:
        """Return and clear queued readiness transitions (called once per turn).

        The chat route emits these as SSE events at the start of the stream
        so the frontend's StatusBar can reflect the parent's boot-time /
        post-settings-change state without polling.
        """
        if not self._pending_readiness:
            return []
        drained = list(self._pending_readiness)
        self._pending_readiness.clear()
        return drained

    @property
    def parent_ready(self) -> bool:
        """True when the boot kernel is built and not in a degraded state."""
        return bool(self._parent_kernel and self._parent_kernel.ready)

    @property
    def parent_degraded_reason(self) -> str:
        """The degraded reason string (empty when the parent is ready)."""
        return (self._parent_kernel.degraded_reason if self._parent_kernel else "") or ""

    async def startup(self) -> None:
        """Build the parent kernel and warm local memory best-effort."""
        try:
            await self._ensure_parent_kernel(refresh_provider=True)
        except Exception as exc:
            # Boot must remain usable when a provider is unavailable or
            # unconfigured. The first real turn retries lazily.
            logger.warning("[parent-kernel] startup degraded: %s", str(exc)[:180])

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
        if self._parent_kernel and self._parent_kernel.matches_current_settings():
            return self._parent_kernel.adapter
        model = active_parent_model()
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
            # Session 267: persist the snapshot summary to the DB so the
            # Observe panel survives a backend restart (the in-memory cache
            # is capped and dies with the process).
            try:
                self._store.save_observation(
                    session_id,
                    snapshot=snapshot.to_public_summary(),
                )
            except Exception:
                logger.debug("[agent-runtime] observation snapshot persistence skipped", exc_info=True)
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

    async def _persist_user_safe(self, session_id: str, message: str, **file_data) -> None:
        """Fire-and-forget wrapper around _persist_user for the turn-init path.

        B-2026-08-17-10 (Session 312): the user-message DB write is NOT on the
        critical path to the first LLM token (the prompt is assembled from
        get_history + the `message` arg, not from the persisted row). Running
        it in a background task removes a serial DB write from the pre-first-
        token path. Errors are logged (same as _persist_user) but never
        propagated — a failed history write must not fail the turn.
        """
        try:
            await asyncio.to_thread(self._persist_user, session_id, message, **file_data)
        except Exception:
            logger.debug("[agent-runtime] fire-and-forget user persist failed", exc_info=True)

    def _persist_assistant(
        self,
        session_id: str,
        text: str,
        *,
        thinking: Optional[str] = None,
        acknowledgement: Optional[str] = None,
        error: Optional[str] = None,
        tool_calls: Optional[list] = None,
        metrics: Optional[dict] = None,
        agent_runs: Optional[list] = None,
        agent_phases: Optional[list] = None,
    ) -> None:
        # Session 266: an error turn persists an (empty-text) assistant message
        # carrying the canonical error object — the history endpoint returns it
        # so the error card survives a reload. Allow empty text ONLY when an
        # error is attached; a bare empty message is still skipped.
        if not text.strip() and not error:
            return
        try:
            self._store.append(
                session_id,
                Message(
                    role=Role.ASSISTANT,
                    content=text,
                    thinking=thinking,
                    acknowledgement=acknowledgement,
                    error=error,
                    tool_calls=tool_calls,
                    metrics=metrics,
                    agent_runs=agent_runs,
                    agent_phases=agent_phases,
                ),
            )
        except Exception:
            logger.exception("[agent-runtime] failed to persist assistant message")

    @staticmethod
    def _collect_acknowledgement(collector) -> Optional[str]:
        """Extract the parent's opening acknowledgement from the obs trace.

        The loop emits it as an ``agent_initialization_ack`` obs event
        (loop.py). Persisting it lets the ADR-36 opening line survive a reload,
        the same way thinking/tool pills do (Session 290)."""
        try:
            for evt in collector.history():
                if evt.type == "agent_initialization_ack":
                    ack = evt.data.get("acknowledgement") if isinstance(evt.data, dict) else None
                    if ack:
                        return str(ack)[:180]
        except Exception:
            return None
        return None

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
        # Session 267: persist the merged observation to the DB — the
        # observability endpoint falls back to it on a cache miss (backend
        # restart survival). Snapshot summary is written separately by
        # build_observation_snapshot.
        try:
            self._store.save_observation(session_id, data=merged)
        except Exception:
            logger.debug("[agent-runtime] observation persistence skipped", exc_info=True)
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
        kernel = await self._ensure_parent_kernel()
        safe, reason = safety_check(message)
        if not safe:
            collector.emit("safety_blocked", reason=reason[:120])
            yield StreamChunk(text=reason, done=False)
            yield StreamChunk(text="", done=True)
            return

        collector.emit("agent_runtime_start", agent="parent")
        # Drain queued readiness transitions (parent_ready / parent_degraded /
        # parent_recovered) onto this turn's ObsCollector so the frontend
        # SSE learns the parent's boot-time / post-settings-change state on
        # the very first turn after boot or a settings change. No-op when
        # there is nothing pending (the steady-state path).
        for transition in self.drain_pending_readiness():
            collector.emit(
                transition["event"],
                reason=transition.get("reason", ""),
                adapter=settings.localmind_adapter,
                model=active_parent_model() or "(default)",
            )
        if client_intent:
            collector.emit(
                "routing_hint_ignored",
                hint=client_intent,
                confidence=client_confidence,
                reason="parent agent owns tool selection",
            )

        # Session 337 — pre-init deterministic guards run BEFORE the
        # trivial/conversational fast-path. This catches the 4 root-cause
        # clusters (hallucination refusal, analyze-only, pressure-induced
        # fabrication, impossible constraints) even when the prompt would
        # otherwise match the conversational fast-path (e.g. "Give me
        # exactly three examples. Do not use numbers. Number each." matches
        # the "give me" opener but is a Cluster D impossible-constraint
        # prompt that should clarify, not fast-path).
        from core.agent.pre_init_classifier import classify_pre_init

        _pre_init_override = classify_pre_init(message)

        # Session 342: deterministic memory-write path.
        # The user's principle:
        #   > EXPLICIT MEMORY REQUESTS ARE ACTION REQUESTS,
        #   > NOT SUGGESTIONS FOR THE LLM TO CONSIDER.
        # When the user says "Remember this", call memory_op directly —
        # no LLM planning, no describe_tool, no replanning, no fake
        # confirmation. Only confirm after successful persistence.
        from core.memory_intent import classify_memory_intent, MemoryOperation

        _memory_intent = classify_memory_intent(message)

        if _memory_intent.is_write and not _pre_init_override.mode:
            # Deterministic memory-write — call memory_op directly
            logger.info(
                "[agent-runtime] deterministic memory-write: type=%s source_knowledge=%s content=%r",
                _memory_intent.memory_type.value,
                _memory_intent.is_source_knowledge,
                _memory_intent.content[:80],
            )
            collector.emit("agent_loop_start", intent="memory_op")
            collector.emit(
                "stage_timing", stage="intent_classify", latency_ms=0, status="memory_write"
            )
            collector.emit(
                "stage_timing", stage="tool_select", latency_ms=0, status="skipped"
            )
            collector.emit(
                "stage_timing", stage="context_build", latency_ms=0, status="memory_write"
            )
            _gen_start = time.monotonic()
            _response_text = ""
            _memory_success = False
            try:
                from tools.memory_tool import memory_op as _mem_op
                # Session 359: pass the classifier's pre-extracted content and
                # memory_type through — re-extracting inside memory_op with the
                # simpler regex corrupts the fact ("note down my project" →
                # stores "down my project") and always tags it "semantic".
                _mem_result = await _mem_op(
                    message,
                    content=_memory_intent.content or None,
                    memory_type=_memory_intent.memory_type.value,
                )
                _memory_success = _mem_result.success
                _response_text = _mem_result.content
            except Exception as _mem_exc:
                logger.warning("[agent-runtime] memory_op failed: %s", _mem_exc)
                _response_text = (
                    "I couldn't save that to memory right now. "
                    f"Error: {_mem_exc}"
                )

            # Session 342: NEVER fake-confirm. Only say "remembered" if the
            # operation actually succeeded.
            if not _memory_success:
                # Session 356: don't show a technical error message — just
                # acknowledge naturally. The user said something personal
                # ("I prefer concise answers") and getting a technical error
                # breaks the conversation.
                _response_text = "Got it — I'll keep that in mind."

            _gen_ms = round((time.monotonic() - _gen_start) * 1000)
            collector.emit(
                "stage_timing", stage="generate", latency_ms=_gen_ms, status="done"
            )
            collector.emit(
                "stage_timing", stage="execute", latency_ms=0, status="skipped"
            )
            self._persist_assistant(
                session_id,
                _response_text,
                thinking=None,
                acknowledgement=None,
                error=None,
                tool_calls=None,
                metrics={
                    "prompt_tokens": 0,
                    "completion_tokens": len(_response_text) // 4,
                    "latency_ms": _gen_ms,
                },
            )
            collector.emit(
                "agent_runtime_done",
                agent="parent",
                elapsed_ms=_gen_ms,
                response_chars=len(_response_text),
            )
            collector.emit(
                "turn_complete",
                intent="memory_op",
                confidence=1.0,
                tokens_approx=len(_response_text) // 4,
                prompt_tokens_approx=0,
                total_latency_ms=_gen_ms,
                memory_facts=0,
                agent_mode=False,
                provider_usage={},
            )
            self._store_observation(
                session_id,
                collector,
                intent="memory_op",
                confidence=1.0,
                memory_hits=0,
                context_tokens=0,
                latency_ms=_gen_ms,
            )
            yield StreamChunk(text=_response_text, done=False)
            yield StreamChunk(text="", done=True)
            return

        # Session 359: load the session's CURRENT persisted todo list ONCE
        # so BOTH the conversational fast-path ("what todos are left?") and
        # the parent-agent loop ("mark the task as complete") can see the
        # real checklist instead of hunting in chat history.
        try:
            current_todos = await asyncio.to_thread(self._store.list_todos, session_id)
        except Exception:
            logger.debug("[agent-runtime] todo state load skipped", exc_info=True)
            current_todos = []

        # Session 332-C: fast-path for trivial inputs (greetings/thanks/
        # farewells — zero LLM call) and obviously-conversational questions
        # ("What can you do?", "Give me three ideas for ...") — one direct
        # chat call, bypassing the parent-agent loop entirely.
        #
        # Why: the user's review of a cyber-café run showed 57.7s latency /
        # 2,101 prompt tokens / 2 iterations for a no-tool conversational
        # prompt. The full parent-agent pipeline pays 4 LLM round-trips
        # (init + iter 1 + replan + iter 2) for a question that needs ONE call.
        #
        # Safety: never fast-path when (a) a file is attached, (b) the client
        # sent a routing hint, (c) the message contains tool/realtime/
        # system keywords (handled by is_conversational_question's blocked
        # keyword guard), OR (d) the pre-init classifier returned an override
        # mode (Session 337 — Cluster A/D overrides must reach the parent
        # agent loop's direct-return path, not the fast-path's chat call).
        if file is None and not client_intent and _pre_init_override.mode is None:
            from core.trivial_input import (
                _direct_chat_response,
                conversational_response,
                is_conversational_question,
                is_trivial_input,
                trivial_response,
            )

            async def _conversational_response_with_context(msg, adptr, hist, thinker_ctx):
                """Session 354: conversational response with Thinker context injected."""
                todo_block = ""
                if current_todos:
                    from core.trivial_input import _render_conversational_todos

                    todo_block = _render_conversational_todos(current_todos)
                sys_prompt = (
                    "You are LocalMind, a local AI assistant. Answer the user's "
                    "latest message naturally and briefly using the recent conversation "
                    "as context. Resolve short follow-ups against what was just said; "
                    "do not repeat a previous answer when the user asks for more detail. "
                    "Give concrete examples when examples are requested. Do not output "
                    "your reasoning process — just give the response directly.\n\n"
                    f"Context from reasoning: {thinker_ctx}\n{todo_block}"
                )
                async for chunk in _direct_chat_response(msg, adptr, hist, sys_prompt):
                    yield chunk
            # _approx_tokens is already imported at module top (line 35).
            # Session 333: do NOT re-import here — a local `from X import Y`
            # makes Y function-local, shadowing the module-level import for
            # the ENTIRE function (Python scoping rule), and breaking the
            # parent-agent path's prompt-token estimate at line 1192 when
            # the fast-path doesn't fire.

            # Light history load for follow-up detection ("Like what?").
            try:
                _hist = await asyncio.to_thread(self._store.get_history, session_id)
                _hist_dicts = [
                    {"role": h.role.value, "content": h.content}
                    for h in _hist[-4:]
                    if h.content
                ]
            except Exception:
                _hist_dicts = []

            _adapter = kernel.adapter
            _is_trivial = is_trivial_input(message, _hist_dicts)
            _is_conv = (not _is_trivial) and is_conversational_question(message, _hist_dicts)
            if _is_trivial or _is_conv:
                _path = "trivial" if _is_trivial else "conversational"
                logger.info(
                    "[agent-runtime] fast-path(%s) for %r", _path, message[:60]
                )
                # Session 333: emit stage_timings matching the test contract
                # (intent_classify skipped — no classifier runs; tool_select/
                # execute skipped — no tools; generate done with real latency
                # measured at the end). Previously emitted a "fast_path"
                # status which the tests didn't expect and which broke the
                # Observe panel's stage-status contract.
                collector.emit("agent_loop_start", intent="chat")
                collector.emit(
                    "stage_timing", stage="intent_classify", latency_ms=0, status="skipped"
                )
                collector.emit(
                    "stage_timing", stage="tool_select", latency_ms=0, status="skipped"
                )
                collector.emit(
                    "stage_timing", stage="context_build", latency_ms=0, status="skipped"
                )
                _gen_start = time.monotonic()

                # Session 354: run the Thinker BEFORE the conversational
                # response — even on the fast-path, the model needs
                # understanding/intent analysis to avoid clarification loops.
                # Only for the CONVERSATIONAL path (not trivial — trivial gets
                # a canned reply with zero LLM calls).
                _thinker_context = ""
                if not _is_trivial:
                    try:
                        from core.agent.thinker import Evidence, Thinker
                        _hist_text = "\n".join(
                            f"{h.get('role', '?')}: {h.get('content', '')[:200]}"
                            for h in _hist_dicts[-4:]
                            if h.get("content")
                        )
                        _ev = Evidence(
                            user_message=message,
                            conversation_history=_hist_text,
                            observations="",
                            iteration=0,
                        )
                        if _ev.has_evidence and getattr(_adapter, "thinking_enabled", False):
                            if collector:
                                collector.emit("agent_thinker_start", iteration=0)
                            _thinker = Thinker(timeout_secs=15.0)
                            async for _tc in _thinker.consult(_ev, _adapter):
                                pass
                            _analysis = _thinker.last_analysis
                            if _analysis and not _analysis.is_empty:
                                _thinker_context = _analysis.reasoning[:500]
                                if collector:
                                    collector.emit(
                                        "agent_thinker_done",
                                        iteration=0,
                                        next_step=_analysis.next_step[:200],
                                        facts=len(_analysis.facts),
                                        ambiguities=len(_analysis.ambiguities),
                                    )
                    except Exception as _thx:
                        logger.debug("[agent-runtime] Thinker on fast-path skipped: %s", _thx)

                _response_chunks: list[str] = []
                _fast_usage: dict[str, int] = {}
                if _is_trivial:
                    _stream = trivial_response(message, _adapter, _hist_dicts)
                else:
                    # Session 354: if the Thinker provided context, inject it
                    # into the conversational response's system prompt so the
                    # model has understanding guidance.
                    if _thinker_context:
                        _stream = _conversational_response_with_context(
                            message, _adapter, _hist_dicts, _thinker_context
                        )
                    else:
                        _stream = conversational_response(
                            message, _adapter, _hist_dicts, todo_state=current_todos
                        )
                async for _chunk in _stream:
                    if _chunk.usage:
                        _fast_usage.update(_chunk.usage)
                    if _chunk.text:
                        _response_chunks.append(_chunk.text)
                        if _chunk.done:
                            # The helper yields its own done=True chunk with
                            # text — strip done so we emit our own canonical
                            # done at the end (mirrors parent-agent pattern
                            # at line 1113 in this file).
                            yield _chunk.model_copy(update={"done": False})
                            continue
                    # Swallow the helper's bare done chunk — the parent
                    # runtime owns the transport completion marker.
                    if _chunk.done:
                        continue
                    yield _chunk

                # generate stage done — measured from before the stream
                # started until the stream finished. Even the trivial
                # canned-reply path ran "generation" logic (string lookup),
                # so report done with the measured latency.
                _gen_ms = round((time.monotonic() - _gen_start) * 1000)
                collector.emit(
                    "stage_timing", stage="generate", latency_ms=_gen_ms, status="done"
                )
                collector.emit(
                    "stage_timing", stage="execute", latency_ms=0, status="skipped"
                )

                # Finalize: persist + emit turn_complete (mirror the parent-
                # agent path's epilog so observability and history survive
                # reload).
                _response_text = "".join(_response_chunks)
                _total_ms = round((time.monotonic() - started) * 1000)
                _prompt_tokens = int(_fast_usage.get("prompt_tokens", 0) or 0) or _approx_tokens(
                    f"You are LocalMind.\n{message}"
                )
                _completion_tokens = int(
                    _fast_usage.get("completion_tokens", 0) or _approx_tokens(_response_text)
                )
                self._persist_assistant(
                    session_id,
                    _response_text,
                    thinking=None,
                    acknowledgement=None,
                    error=None,
                    tool_calls=None,
                    metrics={
                        "prompt_tokens": _prompt_tokens,
                        "completion_tokens": _completion_tokens,
                        "latency_ms": _total_ms,
                    },
                )
                collector.emit(
                    "agent_runtime_done",
                    agent="parent",
                    elapsed_ms=_total_ms,
                    response_chars=len(_response_text),
                )
                collector.emit(
                    "turn_complete",
                    intent="chat",
                    confidence=1.0,
                    tokens_approx=_completion_tokens,
                    prompt_tokens_approx=_prompt_tokens,
                    total_latency_ms=_total_ms,
                    memory_facts=0,
                    agent_mode=False,
                    provider_usage=_fast_usage,
                )
                self._store_observation(
                    session_id,
                    collector,
                    intent="chat",
                    confidence=1.0,
                    memory_hits=0,
                    context_tokens=_prompt_tokens,
                    latency_ms=_total_ms,
                )
                self._metrics.record_streaming_complete(
                    total_tokens=_prompt_tokens + _completion_tokens,
                    prompt_tokens=_prompt_tokens,
                    completion_tokens=_completion_tokens,
                )
                yield StreamChunk(text="", done=True, usage=_fast_usage)
                return

        # B-2026-08-17-10 (Session 312): maximize turn-init parallelism so the
        # first LLM token streams ASAP. Three changes vs the prior serial path:
        #
        # 1. _persist_user is fire-and-forget. It writes the user's message to
        #    the DB for history — the LLM call does NOT depend on it (the
        #    prompt is assembled from get_history + the `message` arg directly).
        #    Scheduling it as a background task removes a serial DB write from
        #    the pre-first-token path.
        #
        # 2. get_history is folded into the concurrent _gather_nonessential
        #    task (alongside memory + parent_session + adapter prime). It's a
        #    DB read — no reason for it to run serially.
        #
        # 3. The concurrent task is created FIRST — before the cwd sync, before
        #    the adapter setup. This gives it the maximum head start: by the
        #    time the cwd sync + adapter prime complete, history + memory +
        #    parent_session may all be ready.
        #
        # Net effect: the pre-first-token serial path is now just safety_check
        # + emit + cwd sync (all sub-millisecond), and the concurrent task
        # runs max(history, memory, parent_session, adapter_prime) in parallel.
        # The user sees the first thinking token as soon as the LLM's first
        # chunk arrives, with no serial DB round-trips in between.
        asyncio.create_task(
            self._persist_user_safe(
                session_id, message,
                file_name=filename,
                file_path=original_path,
                file_size=len(file) if file else None,
                file_type=content_type,
            )
        )

        # B-2026-08-17-10 (Session 312): the turn-init concurrent task. Runs
        # ALL DB reads + memory retrieval + attachment parsing in parallel,
        # overlapped with the adapter setup below. The task is created FIRST
        # (before the cwd sync + adapter setup) so it gets a head start.
        #
        # Returns (history, facts, attach, parent_session) — everything the
        # prompt assembly needs. The effective turn-start latency is
        # max(history, memory, parent_session, adapter_prime) instead of the
        # serial sum.
        async def _gather_nonessential() -> tuple[list, list[str], Optional[dict], ParentSession]:
            # History + parent_session are synchronous DB reads — run them in
            # threads so they don't block the event loop. Memory retrieval is
            # already async. All three run concurrently via gather.
            async def _load_history():
                try:
                    return await asyncio.to_thread(self._store.get_history, session_id)
                except Exception:
                    logger.debug("[agent-runtime] history load failed; proceeding with empty", exc_info=True)
                    return []

            async def _load_parent_session():
                try:
                    stored = await asyncio.to_thread(
                        self._store.get_parent_session, session_id
                    )
                    return ParentSession.from_store(session_id, stored)
                except Exception:
                    logger.debug("[agent-runtime] parent session load failed; using empty session", exc_info=True)
                    return ParentSession(session_id=session_id)

            async def _load_facts_and_attach():
                # Session 339: gate memory retrieval by conversation state.
                # A casual opener ("Hi", "How's it going?") or the first turn
                # of a new chat must NOT trigger memory retrieval — memory
                # should enrich the conversation, not choose its topic.
                # The user's 6 invariants:
                #   1. New conversation begins without an assumed topic.
                #   2. Memory may support intent but not introduce a topic.
                #   3. Unresolved tasks are conversation state, not memory.
                from core.conversation_state import classify_conversation

                # Load the parent session's turn_count synchronously (the
                # _load_parent_session task runs concurrently but we need
                # the count NOW to classify the conversation state). If the
                # session store is unavailable, default to 0 (first turn).
                try:
                    _stored = await asyncio.to_thread(
                        self._store.get_parent_session, session_id
                    )
                    _turn_count = int((_stored or {}).get("turn_count") or 0)
                except Exception:
                    _turn_count = 0

                conv_state = classify_conversation(
                    message=message,
                    turn_count=_turn_count,
                    has_pending_work=False,  # pending-work retrieval is a separate concern
                )
                logger.info(
                    "[agent-runtime] conversation_state: mode=%s retrieve_memory=%s reason=%s",
                    conv_state.mode.value,
                    conv_state.should_retrieve_memory,
                    conv_state.reason,
                )
                if conv_state.should_retrieve_memory:
                    facts = await self._memory_facts(message, session_id)
                else:
                    facts = []  # no memory injection for casual openers / new chats
                try:
                    failures = self._store.recall_failures(message=message, intent=Intent.ANALYZE.value)
                    hint = format_recall_hint(failures)
                    if hint and conv_state.should_retrieve_memory:
                        facts.append(hint)
                except Exception:
                    logger.debug("[agent-runtime] failure memory recall skipped", exc_info=True)
                try:
                    hint = format_ledger_hint(self._store.recall_decisions(task_type=""))
                    if hint and conv_state.should_retrieve_memory:
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

            # Run all three concurrently. asyncio.gather schedules them as
            # separate tasks on the event loop; the to_thread calls release
            # the GIL-thread so the DB reads don't block each other or the
            # memory retrieval.
            history, parent_sess, facts_attach = await asyncio.gather(
                _load_history(),
                _load_parent_session(),
                _load_facts_and_attach(),
            )
            facts, attach = facts_attach
            return history, facts, attach, parent_sess

        # Start the concurrent task FIRST — before cwd sync + adapter setup.
        nonessential_task = asyncio.create_task(_gather_nonessential())

        # Terminal/cwd sync — fast, runs while the concurrent task is already
        # doing DB reads + memory retrieval in the background.
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

        adapter = kernel.adapter
        if not inspect.iscoroutinefunction(getattr(adapter, "chat_with_tools", None)):
            adapter = _ParentAdapterCompat(adapter)
        # Warm the model's real declared context window (Ollama /api/show) so
        # the budget below and the frontend meter reflect actual capacity, not
        # the 8192 fallback. Best-effort — the property degrades gracefully.
        _prime = getattr(adapter, "prime_context_window", None)
        if callable(_prime):
            try:
                await _prime()
            except Exception:
                logger.debug("[agent-runtime] context-window prime failed", exc_info=True)
        context_window = getattr(adapter, "effective_context_window", 8192)
        if not isinstance(context_window, (int, float)) or context_window <= 0:
            context_window = 8192

        # Await nonessential work before assembling the turn — but the task
        # has been running concurrently with cwd sync + adapter setup, so the
        # effective wait is only the unoverlapped tail (whichever of history /
        # memory / parent_session / adapter_prime finishes last).
        try:
            history, memory_facts, attachment, parent_session = await nonessential_task
        except Exception:
            logger.debug("[agent-runtime] nonessential gather failed; proceeding with empty context", exc_info=True)
            history, memory_facts, attachment = [], [], None
            parent_session = ParentSession(session_id=session_id)

        collector.emit("agent_context_ready", memory_facts=len(memory_facts), attachment=bool(attachment))
        self._metrics.start_request()
        clock = _StageClock(collector)
        clock.mark("intent_classify", 0, "skipped")
        clock.start("context_build")

        # Phase 1: the kernel supplies the immutable parent contract. The
        # turn carries only a bounded recent conversational tail plus the
        # current user message; the legacy generic system prompt (which
        # duplicated identity, tools, environment, and knowledge) is not
        # rebuilt here. The AgentLoop adds dynamic environment/workspace
        # context and the native bootstrap capability surface.
        #
        # ADR-52 phase 2: the per-chat ParentSession's rolling summary is
        # injected as a system message BEFORE the recent tail. The summary
        # compacts older turns so long conversations stay bounded in the
        # prompt while the most recent turns remain verbatim below. The
        # session was loaded concurrently with memory/attachment retrieval
        # in _gather_nonessential (B-2026-08-17-10) and survives backend
        # restart via the persisted store.
        summary_section = parent_session.to_prompt_section()
        prompt_messages: list[dict] = []
        if summary_section:
            prompt_messages.append({"role": "system", "content": summary_section})
        for item in history[-8:]:
            if item.role not in (Role.USER, Role.ASSISTANT) or not item.content.strip():
                continue
            prompt_messages.append(
                {
                    "role": item.role.value,
                    "content": item.content[-4000:],
                }
            )
        if attachment and attachment.chunks:
            attachment_text = "\n\n---\n\n".join(attachment.chunks[:8])[:12000]
            prompt_messages.append(
                {
                    "role": "system",
                    "content": (
                        f"[Attached file: {attachment.filename}]\n{attachment_text}\n"
                        "Use this file as evidence for the current request."
                    ),
                }
            )
        prompt_messages.append({"role": "user", "content": message})
        clock.end("context_build")
        clock.skip("tool_select")
        clock.start("generate")

        parent = self._parent_agent or ParentAgent(adapter=adapter, loop=self._agent_loop)
        requested_tools = frozenset(allowed_tool_names) if allowed_tool_names is not None else AGENT_ALLOWED_TOOLS
        parent_tools = requested_tools.intersection(AGENT_ALLOWED_TOOLS)
        # B-2026-08-20-23 / Session 330: the FIXED goal checklist. Derive the
        # user's concrete deliverables from the message (deterministic, zero
        # LLM calls) and hand them to the loop as BOTH the Todos panel plan
        # (fixed denominator — never mutated by what ran) and the acceptance
        # gate's success criteria (completion gated on evidence against these
        # items, not on tool-call success). Conversational/abstract turns
        # derive [] → None → no contract, legacy behavior unchanged.
        from core.agent.goal_interpreter import derive_goal_items

        goal_items = derive_goal_items(message)
        if goal_items:
            collector.emit(
                "agent_goal_checklist",
                goal_count=len(goal_items),
                goals="; ".join(goal_items)[:400],
            )
        response_chunks: list[str] = []
        # Session 266: accumulate the reasoning trace so the persisted message
        # carries the thinking block the user saw (survives reload). The loop
        # streams thinking as "start"/"end" markers plus token text — mirror
        # the frontend's phase-separator behavior (\n\n between phases).
        thinking_parts: list[str] = []
        usage: dict[str, int] = {}
        try:
            async for chunk in parent.run(
                messages=prompt_messages,
                intent=Intent.ANALYZE,
                initial_tool_result=None,
                available_tools=list(kernel.available_tools),
                confidence=1.0,
                adapter=adapter,
                obs=collector,
                memory_facts=memory_facts,
                allowed_tool_names=parent_tools,
                steering_queue=self._queue_for(session_id),
                abort_signal=self._abort_for(session_id),
                skip_planning=True,
                task_type="",
                reformulated_message=message,
                agent_context_override=kernel.parent_context,
                # Fixed goal checklist: seeds the Todos panel (plan-{i}, the
                # denominator never mutates) AND the acceptance gate's
                # success criteria (completion gated on evidence against
                # these items). None when nothing concrete was derived.
                plan_steps=goal_items or None,
                success_criteria=goal_items or None,
                # The criteria must gate at the FINAL-ANSWER point (the
                # model says done → gate verifies → replan or honest
                # report), never at the iteration head — an early
                # criteria-verified stop would end the turn with a bare
                # "✓ n/n" summary before the model writes its synthesis.
                skip_head_gate=bool(goal_items),
                # Session 359: the persisted todos from previous turns — the
                # model must know its own checklist to act on it.
                todo_state=current_todos,
            ):
                if chunk.usage:
                    usage.update(chunk.usage)
                if chunk.thinking:
                    if chunk.thinking == "start":
                        # Phase boundary — separate reasoning phases like the
                        # frontend does, but only once content exists.
                        if thinking_parts:
                            thinking_parts.append("\n\n")
                    elif chunk.thinking != "end":
                        thinking_parts.append(chunk.thinking)
                # Error chunks are terminal transport events. Do not let the
                # parent runtime's completion bookkeeping turn a provider
                # failure into the generic "no usable answer" fallback.
                if chunk.error:
                    # Session 266: persist the failed turn (error card must
                    # survive reload). chat.py normalizes the raw string at
                    # the presentation boundary; we store it verbatim.
                    agent_runs, agent_phases = build_workspace_artifacts(
                        collector, task=message, root_error=chunk.error
                    )
                    self._persist_assistant(
                        session_id,
                        "".join(response_chunks),
                        thinking="".join(thinking_parts) or None,
                        acknowledgement=self._collect_acknowledgement(collector),
                        error=chunk.error,
                        tool_calls=_collect_tool_calls(collector) or None,
                        agent_runs=agent_runs,
                        agent_phases=agent_phases,
                    )
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
            # Session 266: still persist the failed turn so the error card
            # survives reload.
            agent_runs, agent_phases = build_workspace_artifacts(
                collector, task=message, root_error=exc.raw
            )
            self._persist_assistant(
                session_id,
                "".join(response_chunks),
                thinking="".join(thinking_parts) or None,
                acknowledgement=self._collect_acknowledgement(collector),
                error=exc.raw,
                tool_calls=_collect_tool_calls(collector) or None,
                agent_runs=agent_runs,
                agent_phases=agent_phases,
            )
            yield StreamChunk(text="", done=True, error=exc.raw)
            return
        except AgentAbortedError:
            collector.emit("agent_runtime_aborted", agent="parent")
            yield StreamChunk(text="⏹ Stopped by user.", done=False)

        clock.end("generate")
        clock.mark("execute", 0, "done" if any(evt.type == "tool_call" for evt in collector.history()) else "skipped")

        response_text = "".join(response_chunks).strip()
        # Prompt-token estimate when the provider omits streaming usage. The
        # parent kernel + bounded turn context are the actual request boundary;
        # never estimate from the retired generic prompt builder.
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
                    "Please try again, or rephrase your question."
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
        total_ms = round((time.monotonic() - started) * 1000)
        # Session 266: persist the turn's artifacts (thinking, tool-call pills,
        # per-turn metrics) with the assistant message so a reload restores the
        # thinking block, step cards, and the cumulative context counter.
        # Session 267: also persist the Agent Workspace run tree + phase strip
        # so the Agents tab and phase visibility survive a reload.
        agent_runs, agent_phases = build_workspace_artifacts(collector, task=message)
        self._persist_assistant(
            session_id,
            response_text,
            thinking="".join(thinking_parts) or None,
            acknowledgement=self._collect_acknowledgement(collector),
            tool_calls=_collect_tool_calls(collector) or None,
            metrics={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "latency_ms": total_ms,
            },
            agent_runs=agent_runs,
            agent_phases=agent_phases,
        )
        # ADR-52 phase 2: fold this turn into the per-chat ParentSession and
        # persist. The rolling summary compacts older turns; the recent tail
        # holds the last N pairs verbatim. Skip when the turn produced no
        # usable response (the empty-response fallback path already wrote a
        # placeholder assistant message above; compacting it would add noise).
        if response_text and response_text == "".join(response_chunks).strip():
            try:
                tool_summary = _summarize_tool_actions(collector)
                parent_session.update_with_turn(
                    user_message=message,
                    assistant_message=response_text,
                    tool_summary=tool_summary,
                )
                self._store.save_parent_session(
                    session_id,
                    rolling_summary=parent_session.rolling_summary or None,
                    recent_tail=parent_session.recent_tail or None,
                    turn_count=parent_session.turn_count,
                )
            except Exception:
                logger.debug("[agent-runtime] parent session update skipped", exc_info=True)
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

        # Session 344 Phase 3: Presentation Intelligence — classify the
        # response's presentation type and emit structured blocks alongside
        # the text stream. The frontend renders these natively (tables, charts,
        # diagrams, metrics) instead of forcing everything through Markdown.
        # The agent decides WHAT to show; the UI decides HOW it looks.
        #
        # Session 346: do NOT emit a TextBlock that duplicates the text already
        # streamed via token events — that causes a double-reply in the UI.
        # Only emit structured blocks (table, chart, diagram, metric, etc.)
        # when the presentation type is NOT plain text. For TEXT responses,
        # the text stream IS the rendering — no blocks needed.
        _response_blocks = []
        try:
            from core.presentation import classify_presentation, PresentationType

            _pres_type = classify_presentation(message, response_text)
            if _pres_type != PresentationType.TEXT:
                # Non-text presentation — emit a presentation hint so the
                # frontend knows the intended format. The actual structured
                # blocks (table rows, chart data, diagram nodes) will be
                # produced by future Phase 4 agent-side block generation.
                # For now, just the hint — no TextBlock duplication.
                _response_blocks = [
                    {"type": "presentation_hint", "presentation_type": _pres_type.value},
                ]
        except Exception:
            logger.debug("[agent-runtime] presentation classification skipped", exc_info=True)

        yield StreamChunk(
            text="",
            done=True,
            usage=usage,
            metadata={"response_blocks": _response_blocks} if _response_blocks else {},
        )
