"""
BaseAgent — abstract base class for LocalMind's multi-agent architecture.

Implements ADR-6 (refines ADR-5): multiple distinct agents (coding,
research, browser, direct) sharing a common 5-step loop shape:
    assemble → call model → parse → execute → observe → repeat
    "until done, blocked, or limit"

This module defines the *interface* and the *shared loop delegation*.
Each concrete subclass (BrowserAgent, CodingAgent, ResearchAgent,
DirectAgent) supplies its own:
    - context_builder  — what to gather before each turn
    - tools            — its scoped toolset (smaller surface = more
                          reliable selection on gemma3:1b-class models)
    - is_done()        — its own stop condition

What's shared here (and eventually in the loop itself, once the
existing AgentLoop is fully decomposed):
    - The 5-step loop shape
    - Hard iteration cap + wall-clock cap (ADR-5 requirement)
    - Token budget & compaction (ADR-5 / B-2026-07-26-2)
    - Streaming interface back to the frontend
    - Permission checking (the upgraded safety_gate from ADR-5)

Phase 1 (this session, Session 15): BaseAgent is a structural skeleton.
It defines the interface and delegates run() to the existing AgentLoop
for backward compatibility. The existing AgentLoop continues to handle
all traffic; BrowserAgent is wired into the registry but the actual
routing migration happens in a future session.

Phase 2 (future session): extract the loop body from AgentLoop into
BaseAgent._run_loop(), with per-agent hooks for build_context() and
is_done(). The existing AgentLoop becomes a thin shim that constructs
a default agent and calls its run() method.

Phase 3 (future session): CodingAgent, ResearchAgent, DirectAgent
subclasses. The intent router / model_router becomes a registry lookup.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from core.agent.constants import AGENT_ALLOWED_TOOLS
from core.models import Intent, StreamChunk, ToolResult

logger = logging.getLogger(__name__)


# B-2026-08-09-15 (ADR-15 §1): render an AgentConfig.output_schema as a
# literal "return EXACTLY this JSON shape" contract for the model's system
# prompt. Returns "" when no schema is configured (general agents).
def render_output_contract(output_schema: Optional[dict]) -> str:
    if not output_schema:
        return ""
    import json as _json

    schema_json = _json.dumps(output_schema, ensure_ascii=False, indent=2)
    return (
        "\n"
        "OUTPUT CONTRACT — return your final answer as a SINGLE JSON object "
        "matching EXACTLY this shape (no prose wrapper, no markdown fence):\n"
        f"{schema_json}\n"
        "Every field in the shape is required. Omit optional fields (or use "
        "null) rather than inventing fields the shape does not list."
    )


# ── Hard caps (ADR-5 requirement: "repeat until done, blocked, OR limit") ────
# These prevent a small model from spinning forever on a task it can't solve.
# Configured here so per-agent subclasses can override if they need more
# headroom (e.g., a coding agent may need more iterations than a browser agent).

DEFAULT_MAX_ITERATIONS = 20
DEFAULT_MAX_WALL_CLOCK_SECS = 300  # 5 minutes


@dataclass
class AgentConfig:
    """Per-agent configuration. Subclasses override defaults as needed."""

    name: str  # e.g., "browser", "coding", "research", "direct"
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    max_wall_clock_secs: int = DEFAULT_MAX_WALL_CLOCK_SECS
    # The scoped toolset — a subset of AGENT_ALLOWED_TOOLS. A browser agent
    # shouldn't have shell tools; a coding agent shouldn't have browser tools.
    # Smaller surface = more reliable selection on small models (ADR-6 point 6).
    allowed_tools: frozenset[str] = field(default_factory=lambda: AGENT_ALLOWED_TOOLS)
    # Whether this agent executes tools at all. DirectAgent sets this to False
    # — it's steps 1-2 only (assemble → model → respond), no tool execution.
    tools_enabled: bool = True
    # B-2026-08-02-10 (C1) — per-agent model routing. When set, this agent
    # runs on its own model/adapter instead of the shared one. Both fields
    # are OPTIONAL overrides: the LOCALMIND_AGENT_MODEL_<NAME> env var wins
    # over these, and unset fields fall back to the caller's adapter (the
    # pre-C1 behavior — every agent on the shared model). Mixing local +
    # cloud adapters is explicit opt-in only; nothing egresses by default.
    model: Optional[str] = None  # e.g. "llama3.1:70b" (uses `adapter` or the current one)
    adapter: Optional[str] = None  # e.g. "zen", "ollama" (uses the provider's configured model)
    # B-2026-08-02-9 (B4) — inline delegation. ONLY agents with this flag
    # set to True may be spawned via the delegate_inline tool (which lets
    # the child rewrite the PARENT's message history in place — it breaks
    # the strict delegation isolation invariant). Defaults to False; the
    # only built-in opt-in is ContextPrunerAgent.
    allow_inline_mutation: bool = False
    # B-2026-08-09-15 (ADR-15 §1) — SPECIFIC sub-agent fixed output schema.
    # When set, this agent's FINAL answer must be JSON matching exactly
    # this shape (e.g. reviewer: {"issues": [{"severity", "file", "line",
    # "description"}], "verdict"}). The schema is rendered into the agent
    # context (system prompt) so the model returns a machine-parseable
    # fixed shape instead of free-form prose — the "specific sub-agent
    # with a fixed output contract" pattern from the architecture thread.
    # Leave None for general-purpose agents (prose answers are fine).
    output_schema: Optional[dict] = None


class BaseAgent(ABC):
    """
    Abstract base for all LocalMind agents.

    A concrete agent supplies:
        - config()           — its AgentConfig (name, caps, scoped tools)
        - build_context()    — gather/shape logic before each turn
        - is_done()          — stop condition (tests pass / enough sources / ...)
        - description()      — human-readable tool description for the model

    The run() method is shared — it delegates to the existing AgentLoop
    in Phase 1, and will host the actual 5-step loop in Phase 2.
    """

    def __init__(self, adapter):
        """
        Args:
            adapter: the model adapter (Ollama, OpenAI-compat, etc.) used
                for LLM calls. Passed in by the engine at construction time.
        """
        self._adapter = adapter

    # ------------------------------------------------------------------
    # Abstract interface — each concrete agent must supply these
    # ------------------------------------------------------------------

    @abstractmethod
    def config(self) -> AgentConfig:
        """Return this agent's configuration (name, caps, scoped tools)."""

    @abstractmethod
    def build_context(
        self,
        messages: list[dict],
        intent: Intent,
        memory_facts: Optional[list[str]] = None,
        orchestrator_context: Optional[str] = None,
    ) -> str:
        """
        Gather and shape context before each turn.

        This is the agent's "Column 1 — Shape" from the CODING HARNESS
        diagram (ADR-5). Each agent type gathers differently:
            - CodingAgent: codebase search/index, @file resolution, AGENTS.md
            - ResearchAgent: web/doc search, source tracking
            - BrowserAgent: page state, DOM snapshot, nav history
            - DirectAgent: nothing (thin wrapper)

        Returns a string to inject into the system prompt for the next
        model call. Per ADR-5, this is also where workspace_state.snapshot()
        gets injected for the coding agent (the feedback loop).
        """

    @abstractmethod
    def is_done(
        self,
        iterations: int,
        wall_clock_secs: float,
        last_tool_result: Optional[ToolResult],
        trace: object,
    ) -> tuple[bool, str]:
        """
        Decide whether the loop should terminate.

        Returns:
            (done, reason) — True if the loop should stop, with a
            human-readable reason. False to continue.

        Per-agent stop conditions:
            - CodingAgent: tests pass / build succeeds / user says stop
            - ResearchAgent: enough sources gathered / query exhausted
            - BrowserAgent: task-page reached / form submitted / user says stop
            - DirectAgent: always done after one model call (no loop)

        The base loop also enforces hard caps (max_iterations,
        max_wall_clock_secs) regardless of is_done()'s answer — that's
        the "OR limit" from ADR-5.
        """

    @abstractmethod
    def description(self) -> str:
        """
        Human-readable description of what this agent does, for the
        model's tool-calling prompt. Per ADR-6 point 6, this must be
        concrete enough that a gemma3:1b-class model can reliably pick
        the right agent from the registry.
        """

    # ------------------------------------------------------------------
    # Shared loop — delegates to existing AgentLoop in Phase 1
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
        # Session 134: when the engine skips the separate planning call
        # because the ThinkingDispatcher already produced an
        # execution_plan, those step labels come through here and seed
        # the Todos panel (same plan-{i} ids the planner would emit).
        # Must be forwarded to AgentLoop.run() — forgetting this param
        # crashes with "got an unexpected keyword argument 'plan_steps'"
        # (Session 141 regression fix).
        plan_steps: Optional[list[str]] = None,
        allowed_tool_names: Optional[frozenset[str]] = None,
        steering_queue=None,  # B-2026-08-02-5 (A5): per-session asyncio.Queue
        abort_signal=None,  # B-2026-08-02-2 (A2): per-session asyncio.Event
    ) -> AsyncIterator[StreamChunk]:
        """
        Run the agent loop.

        Phase 1 (this session): delegates to the existing AgentLoop.
        This keeps the new abstraction non-breaking — all existing
        traffic continues to flow through AgentLoop unchanged. The
        BaseAgent subclass is wired into the registry but the actual
        routing migration happens in a future session.

        Phase 2 (future): this method hosts the actual 5-step loop:
            1. assemble prompt from build_context() + workspace_state
            2. call model (plan · tool calls · stream)
            3. parse calls · route · permissions
            4. execute tools · capture output
            5. observe (errors · diff · test logs) → feed back into context
            ↻ repeat until is_done() returns True, blocked, or hard cap hit

        The hard caps (max_iterations, max_wall_clock_secs) are enforced
        here regardless of is_done()'s answer — that's the "OR limit"
        from ADR-5.
        """
        # Phase 1 delegation: construct an AgentLoop and call its run().
        # Import is local to avoid circular imports at module load time
        # (core.agent.loop imports from core.agent.constants, etc.).
        from core.agent.loop import AgentLoop

        cfg = self.config()
        logger.info(
            "[base_agent] %s running (intent=%s, tools_enabled=%s, "
            "max_iter=%d, max_wall=%ds)",
            cfg.name,
            intent.value,
            cfg.tools_enabled,
            cfg.max_iterations,
            cfg.max_wall_clock_secs,
        )

        # B-2026-08-02-10 (C1) — per-agent model routing. Resolve this
        # agent's adapter: LOCALMIND_AGENT_MODEL_<NAME> env override, then
        # AgentConfig.model/adapter, else the caller's adapter (unchanged
        # behavior). Applies to the TOP-LEVEL agent and, because every
        # delegated child runs through BaseAgent.run() too, to delegated
        # children automatically. The delegate tools also construct
        # children with the routed adapter directly (belt-and-suspenders;
        # get_adapter() caches per (name, model), so both resolve to the
        # same instance).
        fallback_adapter = adapter or self._adapter
        # resolve_agent_adapter never raises (get_adapter_for_agent catches
        # construction failures and returns None) — no try/except needed.
        from core.model_router import resolve_agent_adapter

        effective_adapter = resolve_agent_adapter(
            cfg.name,
            config_model=cfg.model,
            config_adapter=cfg.adapter,
            fallback=fallback_adapter,
        )
        if effective_adapter is not fallback_adapter:
            logger.info(
                "[base_agent] %s routed to per-agent adapter (model=%s)",
                cfg.name,
                getattr(effective_adapter, "_model", "?"),
            )

        if not cfg.tools_enabled:
            # DirectAgent path: steps 1-2 only (assemble → model → respond).
            # No tool execution. The existing AgentLoop isn't invoked.
            # Phase 2 will implement this properly; for now, log and fall
            # through to the engine's CHAT path (which already handles
            # no-tool streaming).
            logger.info(
                "[base_agent] %s has tools_enabled=False — caller should "
                "route to the CHAT path, not the agent loop",
                cfg.name,
            )

        loop = AgentLoop(adapter=effective_adapter)

        # ADR-8 Phase 2 (Session 34): call build_context() and pass the
        # result as `agent_context` to AgentLoop.run(). This is the
        # load-bearing piece — the agent's playbook file
        # (agents/coding/playbook.md, agents/research/playbook.md) is
        # loaded by build_context() and reaches the model's system
        # prompt via the `agent_context_section` in
        # build_agent_system_prompt(). Without this call, the playbook
        # files sit on disk unused (Session 33 finding); with it, they
        # govern HOW the agent uses its scoped tools.
        try:
            agent_context_str = self.build_context(
                messages=messages,
                intent=intent,
                memory_facts=memory_facts,
                orchestrator_context=orchestrator_context,
            )
        except Exception as exc:
            # Best-effort: if the context builder throws, log and
            # continue with empty context — the agent loop still runs.
            logger.warning(
                "[base_agent] %s build_context() failed: %s — continuing with empty agent_context",
                cfg.name, exc,
            )
            agent_context_str = ""

        # B-2026-08-09-15 (ADR-15 §1): append the fixed output contract so
        # the model's system prompt demands the JSON shape. Gated to
        # DELEGATED child runs only (the delegate tools set a current run
        # id via core.agent.delegation): a top-level user query routed to
        # e.g. the reviewer must still get a readable prose answer, not a
        # JSON blob — the fixed schema is for machine-parseable sub-agent
        # handoff. No-op for general agents (output_schema=None) and for
        # top-level runs.
        from core.agent.delegation import get_current_run_id

        if cfg.output_schema and get_current_run_id() is not None:
            agent_context_str += render_output_contract(cfg.output_schema)

        async for chunk in loop.run(
            messages=messages,
            intent=intent,
            initial_tool_result=initial_tool_result,
            available_tools=available_tools,
            confidence=confidence,
            adapter=effective_adapter,
            intent_history=intent_history,
            obs=obs,
            memory_facts=memory_facts,
            orchestrator_context=orchestrator_context,
            agent_context=agent_context_str,
            agent_config=cfg,  # ADR-6: pass the scoped toolset + caps
            skip_planning=skip_planning,
            plan_steps=plan_steps,  # Session 134: dispatcher plan reuse
            allowed_tool_names=allowed_tool_names,
            steering_queue=steering_queue,  # B-2026-08-02-5 (A5)
            abort_signal=abort_signal,  # B-2026-08-02-2 (A2)
        ):
            yield chunk

    # ------------------------------------------------------------------
    # Helpers shared across all agents
    # ------------------------------------------------------------------

    def scoped_tools(self, all_tools: list[dict]) -> list[dict]:
        """
        Filter the global tool list down to this agent's scoped allowlist.

        Per ADR-6: a coding agent doesn't have browser tools; a browser
        agent doesn't have shell tools. Smaller surface = more reliable
        selection on small models.

        Args:
            all_tools: the full list of registered tool dicts (from
                tools.available_tools()).

        Returns:
            The subset matching this agent's config().allowed_tools.
        """
        allowed = self.config().allowed_tools
        return [t for t in all_tools if t.get("intent") in allowed]
