"""
ContextPrunerAgent — inline delegation.

The context-pruner pattern: an inline agent that rewrites the parent's
message history in place. It is the FIRST and (for now) ONLY agent with
AgentConfig.allow_inline_mutation=True — the parent loop only spawns it
via the delegate_inline tool, which passes:

    - messages: the parent's LIVE message list BY REFERENCE (read-only
      for the pruner — it must never mutate the list directly);
    - mutate_parent_history: the parent's validated in-place rewrite
      callback (the ONLY write path).

The pruner overrides BaseAgent.run() instead of going through AgentLoop:
it makes ONE direct model call asking for a rewritten (smaller) message
history, parses the JSON array (tolerant extraction), validates it
fail-safe, and — only then — calls mutate_parent_history(). The parent's
callback re-validates, snapshots the pre-mutation history to disk, and
replaces the list in place.

Failure is always fail-safe: an unparseable or structurally invalid
rewrite leaves the parent's history UNCHANGED.

Lives in its own agent directory
(`agents/context_pruner/`) so it is registry-discovered, listable, and —
thanks to per-agent model routing — can be routed to a STRONG model via
`LOCALMIND_AGENT_MODEL_CONTEXT_PRUNER=...` even when the orchestrator is
local (the spec's explicit model-readiness note).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Optional

from agents.base_agent import AgentConfig, BaseAgent
from agents.context_pruner.context_builder import build_context_pruner_context
from agents.context_pruner.is_done import is_context_pruner_done
from agents.context_pruner.tools import CONTEXT_PRUNER_TOOLS
from core.agent.delegation import validate_rewritten_history
from core.models import Intent, StreamChunk, ToolResult

logger = logging.getLogger(__name__)

# One message's content is truncated to this many chars when serializing
# the parent history into the rewrite prompt (the pruner sees a bounded
# view; the parent's own context still holds the full history).
_MAX_CONTENT_CHARS = 2_000
# Total serialized history cap for the rewrite prompt.
_MAX_SERIALIZED_CHARS = 24_000

_PRUNER_SYSTEM_PROMPT = (
    "You are the Context Pruner — an inline agent that rewrites an agent "
    "conversation history to be smaller and tighter. Output ONLY a JSON "
    "array of message objects. Keep the system message at index 0 and the "
    "user's most recent message verbatim. Summarize older turns and tool "
    "results. Never change tool_call ids; never leave a 'tool' message "
    "without its preceding assistant tool_calls message with the same id; "
    "never end with a tool message. No prose before or after the JSON."
)


def _serialize_history(messages: list[dict]) -> str:
    """Bounded JSON serialization of the parent history for the rewrite prompt."""
    parts: list[str] = []
    for msg in messages:
        entry: dict = {"role": msg.get("role", "?")}
        content = msg.get("content") or ""
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, default=str)
        if len(content) > _MAX_CONTENT_CHARS:
            content = content[:_MAX_CONTENT_CHARS] + (
                f"\n…[{len(content) - _MAX_CONTENT_CHARS} chars truncated]…"
            )
        entry["content"] = content
        if msg.get("tool_call_id"):
            entry["tool_call_id"] = msg["tool_call_id"]
        if msg.get("tool_calls"):
            entry["tool_calls"] = msg["tool_calls"]
        parts.append(json.dumps(entry, ensure_ascii=False))
    joined = "\n".join(parts)
    if len(joined) <= _MAX_SERIALIZED_CHARS:
        return joined
    # Drop from the middle, keeping the head (system prompt) and tail
    # (most recent turns) — never the tail, which the pruner must keep.
    head = parts[0]
    tail = parts[1:]
    budget = _MAX_SERIALIZED_CHARS - len(head) - 200
    kept: list[str] = []
    for part in reversed(tail):
        if sum(len(p) for p in kept) + len(part) > budget:
            break
        kept.append(part)
    kept.reverse()
    return head + "\n…[middle messages dropped for length]…\n" + "\n".join(kept)


def _build_rewrite_prompt(messages: list[dict], task: str) -> str:
    return (
        "Rewrite the agent conversation history below as a SMALLER JSON "
        "array of messages, following the system instructions.\n\n"
        f"TASK: {task or 'Summarize the conversation; keep the latest user message verbatim.'}\n\n"
        "HISTORY (JSON array):\n"
        + _serialize_history(messages)
    )


def _extract_messages(text: str) -> Optional[list[dict]]:
    """Tolerantly extract the first JSON array of dicts from model output."""
    if not text:
        return None
    decoder = json.JSONDecoder()
    idx = 0
    while True:
        idx = text.find("[", idx)
        if idx == -1:
            return None
        try:
            obj, _end = decoder.raw_decode(text[idx:])
        except json.JSONDecodeError:
            idx += 1
            continue
        if isinstance(obj, list) and all(isinstance(m, dict) for m in obj):
            return obj
        idx += 1


class ContextPrunerAgent(BaseAgent):
    def config(self) -> AgentConfig:
        return AgentConfig(
            name="context_pruner",
            max_iterations=1,  # single model call — no loop
            max_wall_clock_secs=60,  # 1 min — just one model call
            allowed_tools=CONTEXT_PRUNER_TOOLS,  # empty frozenset
            tools_enabled=False,  # no tool execution — transparent transformation
            allow_inline_mutation=True,  # B4: THE inline-capable agent
        )

    def build_context(
        self,
        messages: list[dict],
        intent: Intent,
        memory_facts: Optional[list[str]] = None,
        orchestrator_context: Optional[str] = None,
    ) -> str:
        return build_context_pruner_context(
            messages=messages,
            intent=intent,
            memory_facts=memory_facts,
            orchestrator_context=orchestrator_context,
        )

    def is_done(
        self,
        iterations: int,
        wall_clock_secs: float,
        last_tool_result: Optional[ToolResult],
        trace: object,
    ) -> tuple[bool, str]:
        return is_context_pruner_done(
            iterations=iterations,
            wall_clock_secs=wall_clock_secs,
            last_tool_result=last_tool_result,
            trace=trace,
        )

    def description(self) -> str:
        return (
            "Context Pruner — inline agent (single model call, no tools) "
            "that rewrites the parent agent's message history in place to "
            "keep it small. Spawned ONLY via delegate_inline; never invoked "
            "directly by the user."
        )

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
        agent_config=None,
        agent_context: Optional[str] = None,
        allowed_tool_names: Optional[frozenset[str]] = None,
        steering_queue=None,
        abort_signal=None,
        mutate_parent_history=None,  # B4: the parent's validated rewrite callback
        task: str = "",
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """Rewrite the parent's history via one direct model call.

        Unlike BaseAgent.run() (which delegates to AgentLoop), this override
        performs the mutation itself: read parent history → one model call →
        parse + validate → call mutate_parent_history(). Fail-safe: any
        parse/validation failure leaves the parent's history unchanged.
        """
        cfg = self.config()
        # Per-agent model routing — the pruner can be
        # routed to a stronger model via LOCALMIND_AGENT_MODEL_CONTEXT_PRUNER.
        fallback = adapter or self._adapter
        from core.model_router import resolve_agent_adapter

        effective_adapter = resolve_agent_adapter(
            cfg.name,
            config_model=cfg.model,
            config_adapter=cfg.adapter,
            fallback=fallback,
        )

        if mutate_parent_history is None:
            yield StreamChunk(
                text=(
                    "ERROR: context_pruner must be spawned via delegate_inline "
                    "(the mutate_parent_history callback is required). The "
                    "parent history was NOT changed."
                ),
                done=True,
            )
            return

        if not isinstance(messages, list) or not messages:
            yield StreamChunk(
                text="ERROR: context_pruner received an empty parent history — nothing to prune.",
                done=True,
            )
            return

        if abort_signal is not None and abort_signal.is_set():
            yield StreamChunk(
                text="Context pruner aborted before rewriting — the parent history was NOT changed.",
                done=True,
            )
            return

        before = len(messages)
        prompt = _build_rewrite_prompt(messages, task or "")
        try:
            chat_messages = [
                {"role": "system", "content": _PRUNER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]

            async def _stream() -> str:
                chunks: list[str] = []
                async for chunk in effective_adapter.chat(chat_messages, temperature=0.2):
                    if chunk.text:
                        chunks.append(chunk.text)
                return "".join(chunks)

            response = await asyncio.wait_for(
                _stream(),
                timeout=cfg.max_wall_clock_secs,
            )
        except asyncio.TimeoutError:
            logger.warning("[context_pruner] rewrite request timed out after %ss", cfg.max_wall_clock_secs)
            yield StreamChunk(
                text=(
                    "Context pruner timed out — the parent history was NOT "
                    "changed (fail-safe)."
                ),
                done=True,
            )
            return
        except Exception as exc:
            logger.warning("[context_pruner] rewrite request failed: %s", exc)
            yield StreamChunk(
                text=(
                    "Context pruner failed — the parent history was NOT "
                    f"changed (fail-safe: {exc})."
                ),
                done=True,
            )
            return

        new_history = _extract_messages(response)
        if new_history is None:
            logger.warning("[context_pruner] no valid JSON array in model output")
            yield StreamChunk(
                text=(
                    "Context pruner could not parse a rewritten history from "
                    "the model output — the parent history was NOT changed "
                    "(fail-safe)."
                ),
                done=True,
            )
            return

        ok, reason = validate_rewritten_history(new_history, original_len=before)
        if not ok:
            logger.warning("[context_pruner] rewrite failed validation: %s", reason)
            yield StreamChunk(
                text=(
                    "Context pruner produced an invalid rewrite "
                    f"({reason}) — the parent history was NOT changed "
                    "(fail-safe)."
                ),
                done=True,
            )
            return

        applied = mutate_parent_history(new_history)
        if applied:
            logger.info("[context_pruner] applied rewrite: %d → %d messages", before, len(new_history))
            yield StreamChunk(
                text=f"Context pruned: {before} → {len(new_history)} messages.",
                done=True,
            )
        else:
            yield StreamChunk(
                text=(
                    "Context pruner's rewrite was rejected by the parent "
                    "(structural validation) — the parent history was NOT "
                    "changed (fail-safe)."
                ),
                done=True,
            )
