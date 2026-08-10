"""
Shared Pydantic models used across LocalMind layers.
No business logic here — pure data shapes.

v4.0 — Unified Dynamic Capability Orchestration
──────────────────────────────────────────────────
Consolidated all routing into ThinkingDispatcher as the sole Layer 2.
Removed backward-compat aliases and deprecated modules.

Canonical types defined here:
  - Capability enum — composable capability descriptors
  - TaskProfile — multi-dimensional capability profile (replaces single Intent)
  - OrchestrationPlan — complete output of ThinkingDispatcher
  - ExecutionGraph — DAG-based parallel execution model
  - ExecutionConstraints — bounded execution parameters
  - UnderstandingResult — Layer 1 structured input parsing
  - ValidationResult — Layer 5 quality/fabrication assessment
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

# ═══════════════════════════════════════════════════════════════════════════════
# Role & Intent — foundational enums
# ═══════════════════════════════════════════════════════════════════════════════


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class Intent(str, Enum):
    FILE_TASK = "file_task"
    FIND_PATH = "find_path"  # Session 125: name-match search for files/folders (path-only, capped)
    WEB_SEARCH = "web_search"
    WEB_FETCH = "web_fetch"
    CODE_EXEC = "code_exec"
    SHELL = "shell"
    SYSINFO = "sysinfo"
    OBSERVE = "observe"  # B-2026-07-31-9: desktop awareness (window, clipboard, apps, state, recent files)
    CALCULATE = "calculate"  # B-2026-07-31-10: safe arithmetic evaluation
    CSV = "csv"  # B-2026-07-31-10: bounded CSV file parsing
    JSON = "json"  # B-2026-07-31-10: bounded JSON parse/query
    SQL = "sql"  # B-2026-07-31-10: read-only SQLite queries
    MEMORY_OP = "memory_op"
    FILE_WRITE = "file_write"
    FILE_EDIT = "file_edit"
    BROWSE = "browse"  # Real browser interaction (click, fill, scroll, screenshot)
    GIT = "git"  # Structured Git operations (status, diff, log, branch, commit, etc.)
    PROCESS = "process"  # Process management (start, stop, restart, status, logs, wait)
    VERIFY = "verify"  # Verification (run tests, reproduce bugs, check acceptance criteria)
    REVIEW = "review"  # Code review (spec conformance, quality assessment, best practices)
    DEBUG = "debug"  # Debugging (isolate failures, trace root causes, reproduce bugs)
    ANALYZE = "analyze"  # Analysis (understand requirements, clarify what to build)
    DIAGNOSTICS = "diagnostics"  # Diagnostics (inspect errors, analyze tracebacks, inspect logs)
    CHAT = "chat"
    DELEGATE = "delegate"  # ADR-8 Phase 3: agent-initiated delegation
    DELEGATE_PARALLEL = "delegate_parallel"  # B-2026-08-02-6: parallel delegation fan-out
    DELEGATE_INLINE = "delegate_inline"  # B-2026-08-02-9: inline delegation (child rewrites parent history)
    PROPOSE_EDIT = "propose_str_replace"  # B-2026-08-02-7: stage an edit proposal (no write)
    PROPOSE_WRITE = "propose_write_file"  # B-2026-08-02-7: stage a write proposal (no write)
    APPLY_PROPOSED = "apply_proposed_edit"  # B-2026-08-02-7: write a staged proposal to disk
    ADD_SUBGOAL = "add_subgoal"  # B-2026-08-02-8: add a subgoal to the scratchpad
    UPDATE_SUBGOAL = "update_subgoal"  # B-2026-08-02-8: update a subgoal's status/notes
    CREATE_PLAN = "create_plan"  # B-2026-08-02-8: create multiple subgoals from a plan
    SKILL = "skill"  # B-2026-08-02-12: load a skill (markdown playbook) into context
    BEST_OF_N_EDIT = "best_of_n_edit"  # B-2026-08-02-11: N candidate edits → selector → apply winner


# ═══════════════════════════════════════════════════════════════════════════════
# Capability — composable capability enum (replaces single-label Intent routing)
# ═══════════════════════════════════════════════════════════════════════════════


class Capability(str, Enum):
    """Fine-grained capability that a message may require.

    Unlike Intent, capabilities are compositional: a single message
    can require multiple capabilities simultaneously.

    Categories:
      Data acquisition: WEB_SEARCH, WEB_FETCH
      Execution: CODE_EXEC, SHELL
      File operations: FILE_READ, FILE_WRITE, FILE_EDIT
      Memory: MEMORY_STORE, MEMORY_RETRIEVE
      System: SYSINFO
      Cognitive: REASONING, COMPARISON, SYNTHESIS, PLANNING, PREDICTION
    """

    # ── Data acquisition ──
    WEB_SEARCH = "web_search"
    WEB_FETCH = "web_fetch"
    BROWSE = "browse"  # Real browser interaction (click, fill, scroll, screenshot)

    # ── Execution ──
    CODE_EXEC = "code_exec"
    SHELL = "shell"

    # ── File operations ──
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_EDIT = "file_edit"

    # ── Memory ──
    MEMORY_STORE = "memory_store"
    MEMORY_RETRIEVE = "memory_retrieve"

    # ── System ──
    SYSINFO = "sysinfo"
    OBSERVE = "observe"  # B-2026-07-31-9: desktop awareness — "what's happening right now"

    # ── Data (B-2026-07-31-10) ──
    CALCULATE = "calculate"  # safe arithmetic evaluation
    CSV = "csv"  # bounded CSV file parsing
    JSON = "json"  # bounded JSON parse/query
    SQL = "sql"  # read-only SQLite queries

    # ── Cognitive ──
    REASONING = "reasoning"
    COMPARISON = "comparison"
    SYNTHESIS = "synthesis"
    PLANNING = "planning"
    PREDICTION = "prediction"


# ── Capability → Intent Mapping ──────────────────────────────────────────────

CAPABILITY_TO_INTENT: dict[Capability, Intent] = {
    Capability.SYSINFO: Intent.SYSINFO,
    Capability.OBSERVE: Intent.OBSERVE,
    Capability.CALCULATE: Intent.CALCULATE,
    Capability.CSV: Intent.CSV,
    Capability.JSON: Intent.JSON,
    Capability.SQL: Intent.SQL,
    Capability.WEB_SEARCH: Intent.WEB_SEARCH,
    Capability.WEB_FETCH: Intent.WEB_FETCH,
    Capability.BROWSE: Intent.BROWSE,
    Capability.CODE_EXEC: Intent.CODE_EXEC,
    Capability.SHELL: Intent.SHELL,
    Capability.FILE_WRITE: Intent.FILE_WRITE,
    Capability.FILE_EDIT: Intent.FILE_EDIT,
    Capability.FILE_READ: Intent.FILE_TASK,
    Capability.MEMORY_STORE: Intent.MEMORY_OP,
    Capability.MEMORY_RETRIEVE: Intent.MEMORY_OP,
}

TOOL_CAPABILITIES: set[Capability] = {
    Capability.WEB_SEARCH,
    Capability.WEB_FETCH,
    Capability.BROWSE,
    Capability.CODE_EXEC,
    Capability.SHELL,
    Capability.FILE_READ,
    Capability.FILE_WRITE,
    Capability.FILE_EDIT,
    Capability.MEMORY_STORE,
    Capability.MEMORY_RETRIEVE,
    Capability.SYSINFO,
    Capability.OBSERVE,  # B-2026-07-31-9: desktop awareness
    Capability.CALCULATE,  # B-2026-07-31-10: safe arithmetic
    Capability.CSV,  # B-2026-07-31-10: bounded CSV parsing
    Capability.JSON,  # B-2026-07-31-10: bounded JSON parse/query
    Capability.SQL,  # B-2026-07-31-10: read-only SQLite queries
}

COGNITIVE_CAPABILITIES: set[Capability] = {
    Capability.REASONING,
    Capability.COMPARISON,
    Capability.SYNTHESIS,
    Capability.PLANNING,
    Capability.PREDICTION,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Execution & Safety enums (unified)
# ═══════════════════════════════════════════════════════════════════════════════


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExecutionMode(str, Enum):
    """How the request should be executed.

    v3.0 unified: merges the old models.ExecutionMode (direct_chat, etc.)
    with capability.ExecutionMode (direct, etc.) into a single enum.

    DIRECT         → Pure conversation, no tools needed.
    SINGLE_TOOL    → One tool call, no orchestration.
    MULTI_TOOL     → Multiple tools, may be parallelizable via DAG.
    AGENT_LOOP     → Plan→Execute→Verify workflow. Full agent loop.
    MULTI_PHASE    → Complex: multi-phase planning with dependencies.
    """

    DIRECT = "direct"
    SINGLE_TOOL = "single_tool"
    MULTI_TOOL = "multi_tool"
    AGENT_LOOP = "agent_loop"
    MULTI_PHASE = "multi_phase"


class SafetyLevel(str, Enum):
    """Safety constraint level for execution."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ═══════════════════════════════════════════════════════════════════════════════
# Core message models
# ═══════════════════════════════════════════════════════════════════════════════


class Message(BaseModel):
    role: Role
    content: str
    timestamp: float = Field(default_factory=time.time)
    tool_name: Optional[str] = None
    file_name: Optional[str] = None
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    file_type: Optional[str] = None


class FileAttachment(BaseModel):
    filename: str
    content_type: str
    size_bytes: int
    chunks: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str
    session_id: str


class ChatResponse(BaseModel):
    text: str
    session_id: str
    intent: Intent
    tool_used: Optional[str] = None
    sources: list[str] = Field(default_factory=list)


class StreamChunk(BaseModel):
    text: str
    done: bool = False
    error: Optional[str] = None
    thinking: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    # Provider-reported usage, normalized by adapters to OpenAI names.
    # Providers may omit this on streaming responses, so an empty mapping
    # means the engine should retain its estimation fallback.
    usage: dict = Field(default_factory=dict)
    status: Optional[str] = None
    dispatch_steps: list[dict] = Field(default_factory=list)


class ToolResult(BaseModel):
    content: str
    risk: RiskLevel = RiskLevel.LOW
    source: str
    metadata: dict = Field(default_factory=dict)
    requires_confirmation: bool = False
    success: bool = True
    error_type: str = ""
    error_message: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# Execution Constraints
# ═══════════════════════════════════════════════════════════════════════════════


class ExecutionConstraints(BaseModel):
    """Bounded execution parameters for the orchestration plan.

    These constraints are enforced at every layer of the 6-layer pipeline:
    - Layer 3 (Planning): uses max_iterations for agent loop bounds
    - Layer 4 (Execution): uses per-tool timeout and retry limits
    - Layer 5 (Validation): uses max_fabrication_risk to force stops
    """

    max_retries: int = 1
    max_iterations: int = 5
    timeout_total_secs: float = 120.0
    timeout_per_tool_secs: float = 30.0
    timeout_llm_secs: float = 12.0
    allow_parallel: bool = True
    require_confirmation: bool = False
    fallback_to_chat: bool = True
    max_fabrication_risk: int = 3
    tool_retry_base_delay: float = 0.3


# ═══════════════════════════════════════════════════════════════════════════════
# TaskProfile — the central routing object (v3.0 unified)
# ═══════════════════════════════════════════════════════════════════════════════


class TaskProfile(BaseModel):
    """Multi-dimensional capability profile replacing single Intent label.

    v3.0: Merges the old TaskProfile (models.py) and the new TaskProfile
    (capability.py) into a single canonical definition. The capabilities
    list is the source of truth — primary_intent and required_tools are
    derived from it, not independently set.

    Design principle: "What capabilities are required to satisfy this
    correctly?" instead of "What type of message is this?"

    Examples:
      "What is today's EPL fixtures?" ->
        capabilities=[WEB_SEARCH, SYNTHESIS],
        requires_grounding=True,
        realtime_sensitive=True,
        execution_mode=SINGLE_TOOL

      "Compare my system specs with game requirements" ->
        capabilities=[SYSINFO, WEB_SEARCH, COMPARISON],
        requires_grounding=True,
        requires_reasoning=True,
        execution_mode=MULTI_TOOL

      "Hello, how are you?" ->
        capabilities=[],
        execution_mode=DIRECT
    """

    # ── Capability flags (derived from capabilities list, but also settable) ──
    requires_grounding: bool = False
    requires_tools: bool = False
    requires_planning: bool = False
    requires_memory: bool = False
    requires_reasoning: bool = False
    requires_execution: bool = False
    requires_file_access: bool = False
    realtime_sensitive: bool = False

    # ── Classification metadata ──
    capabilities: list[Capability] = Field(default_factory=list)
    safety_level: SafetyLevel = SafetyLevel.LOW
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    execution_mode: ExecutionMode = ExecutionMode.DIRECT
    primary_domain: str = ""

    # ── Execution constraints ──
    constraints: ExecutionConstraints = Field(default_factory=ExecutionConstraints)

    # ── User-facing ──
    reformulated: str = ""
    acknowledgement: str = ""

    # ── Metadata ──
    reasoning: str = ""
    fast_path: bool = False
    dispatch_steps: list[dict] = Field(default_factory=list)

    # ── Derived Intent accessors (for backward compat with tool dispatch) ──

    def primary_intent(self) -> Intent:
        """Derive the primary Intent from the capability profile.

        Maps the capability list to the single Intent that best
        represents the dominant capability. Used by the tool registry
        and model router which still key on Intent.
        """
        for cap in self.capabilities:
            if cap in CAPABILITY_TO_INTENT:
                return CAPABILITY_TO_INTENT[cap]
        return Intent.CHAT

    def secondary_intent(self) -> Optional[Intent]:
        """Derive secondary Intent from capabilities."""
        primary = self.primary_intent()
        for cap in self.capabilities:
            if cap in CAPABILITY_TO_INTENT:
                intent = CAPABILITY_TO_INTENT[cap]
                if intent != primary:
                    return intent
        return None

    def all_intents(self) -> list[Intent]:
        """Get all derived Intents from capabilities."""
        intents = []
        seen: set[Intent] = set()
        for cap in self.capabilities:
            if cap in CAPABILITY_TO_INTENT:
                intent = CAPABILITY_TO_INTENT[cap]
                if intent not in seen:
                    intents.append(intent)
                    seen.add(intent)
        return intents

    def is_chat_only(self) -> bool:
        """True when no tool capabilities are needed."""
        return not any(cap in TOOL_CAPABILITIES for cap in self.capabilities)

    def tool_capabilities(self) -> list[Capability]:
        """Return only the tool-type capabilities."""
        return [cap for cap in self.capabilities if cap in TOOL_CAPABILITIES]

    def cognitive_capabilities(self) -> list[Capability]:
        """Return only the cognitive-type capabilities."""
        return [cap for cap in self.capabilities if cap in COGNITIVE_CAPABILITIES]

    def required_tools(self) -> list[str]:
        """Derive required tool names from capabilities.

        Replaces the old required_tools field with a derived list.
        The ThinkingDispatcher sets capabilities; this method
        maps them to tool dispatch names.
        """
        _CAPABILITY_TO_TOOL: dict[Capability, str] = {
            Capability.WEB_SEARCH: "web_search",
            Capability.WEB_FETCH: "web_fetch",
            Capability.CODE_EXEC: "code_exec",
            Capability.SHELL: "shell",
            Capability.FILE_READ: "file_task",
            Capability.FILE_WRITE: "file_write",
            Capability.FILE_EDIT: "edit_file",
            Capability.MEMORY_STORE: "memory_op",
            Capability.MEMORY_RETRIEVE: "memory_op",
            Capability.SYSINFO: "sysinfo",
            Capability.OBSERVE: "observe",  # B-2026-07-31-9: desktop awareness
            Capability.CALCULATE: "calculator",  # B-2026-07-31-10: safe arithmetic
            Capability.CSV: "csv",  # B-2026-07-31-10: bounded CSV parsing
            Capability.JSON: "json",  # B-2026-07-31-10: bounded JSON parse/query
            Capability.SQL: "sql",  # B-2026-07-31-10: read-only SQLite queries
        }
        tools: list[str] = []
        seen: set[str] = set()
        for cap in self.capabilities:
            if cap in _CAPABILITY_TO_TOOL:
                tool = _CAPABILITY_TO_TOOL[cap]
                if tool not in seen:
                    tools.append(tool)
                    seen.add(tool)
        # Supplement from flags
        if self.realtime_sensitive and "web_search" not in seen:
            tools.append("web_search")
        return tools

    def auto_correct(self) -> None:
        """Auto-correct inconsistencies between flags and capabilities.

        Ensures that if tool capabilities exist, requires_tools is True,
        and if grounding capabilities exist, requires_grounding is True.
        Called by the ThinkingDispatcher after parsing LLM output.
        """
        if any(cap in TOOL_CAPABILITIES for cap in self.capabilities):
            self.requires_tools = True
        if Capability.WEB_SEARCH in self.capabilities or Capability.WEB_FETCH in self.capabilities:
            self.requires_grounding = True
        if self.realtime_sensitive:
            self.requires_grounding = True


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 1: Understanding Result
# ═══════════════════════════════════════════════════════════════════════════════


class UnderstandingResult(BaseModel):
    """Structured output of Layer 1: Understanding.

    No classification, no regex — just structured extraction
    of everything the downstream layers need from the raw input.
    """

    message: str
    session_id: str
    has_attachment: bool = False
    attachment_filename: Optional[str] = None
    attachment_content_type: Optional[str] = None
    attachment_size: Optional[int] = None
    session_cwd: str = ""
    history_window: list[Message] = Field(default_factory=list)
    is_followup: bool = False
    followup_context: Optional[dict] = None


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 5: Validation Result
# ═══════════════════════════════════════════════════════════════════════════════


class ValidationResult(BaseModel):
    """Layer 5 output: quality and fabrication assessment.

    Used to decide whether to re-execute, synthesize, or
    deliver the result to the user.
    """

    satisfied: bool = True
    fabrication_risk: int = 0
    needs_synthesis: bool = False
    needs_reflection: bool = False
    missing_capabilities: list[Capability] = Field(default_factory=list)
    quality_score: float = 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# OrchestrationPlan — complete output of ThinkingDispatcher (Layer 2)
# ═══════════════════════════════════════════════════════════════════════════════


class OrchestrationPlan(BaseModel):
    """Complete output of the ThinkingDispatcher (Layer 2).

    Contains the TaskProfile, optional execution graph, and all
    metadata needed for the 6-layer pipeline. The ExecutionGraph
    is imported lazily to avoid circular references.
    """

    profile: TaskProfile
    graph: object = None  # ExecutionGraph, set lazily
    reasoning: str = ""
    dispatch_steps: list[dict] = Field(default_factory=list)
    fast_path: bool = False

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def set_graph(self, graph: object) -> None:
        """Set the execution graph after lazy import."""
        self.graph = graph


class AgentAbortedError(Exception):
    """Raised inside AgentLoop.run() when the user aborts the turn.

    B-2026-08-02-2 (A2): an asyncio.Event is threaded through
    AgentLoop.run() / BaseAgent.run(); when it is set, the loop raises
    this at the next iteration boundary so the engine can yield a clean
    "stopped" response instead of letting the backend run to the
    wall-clock/iteration cap after the client closed the stream.
    """


# ═══════════════════════════════════════════════════════════════════════════════
# EngineContext — prompt assembly input
# ═══════════════════════════════════════════════════════════════════════════════


class EngineContext(BaseModel):
    """Everything the context builder needs to assemble a prompt."""

    session_id: str
    message: str
    intent: Intent
    history: list[Message] = Field(default_factory=list)
    tool_result: Optional[ToolResult] = None
    file_attachment: Optional[FileAttachment] = None
    memory_facts: list[str] = Field(default_factory=list)
    session_cwd: str = ""
