"""
Shared Pydantic models used across LocalMind layers.
No business logic here — pure data shapes.

The live request path is the parent-agent runtime: every non-blocked turn
enters one parent AgentLoop, which owns tool selection, delegation,
evaluation, and synthesis. The legacy ThinkingDispatcher contracts
(TaskProfile, OrchestrationPlan, ExecutionConstraints, UnderstandingResult,
ValidationResult, ExecutionMode, SafetyLevel) were deleted — nothing in the
request path consumes them.

Canonical types defined here:
  - Role / Intent — foundational enums
  - Capability — composable capability descriptors
  - RiskLevel — tool risk classification
  - Message / FileAttachment — chat shapes
  - StreamChunk — SSE transport chunk
  - ToolResult — tool execution result
  - AgentAbortedError — user-abort signal
  - EngineContext — prompt assembly input
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator

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
    FIND_PATH = "find_path"  # name-match search for files/folders (path-only, capped)
    # unified local search (files/recent/largest/duplicates/apps/open_with)
    SYSTEM_SEARCH = "system_search"
    # Bounded read-only folder inspection (list/tree/stat)
    DIR_EXPLORER = "dir_explorer"
    WEB_SEARCH = "web_search"
    WEB_FETCH = "web_fetch"
    CODE_EXEC = "code_exec"
    SHELL = "shell"
    SYSINFO = "sysinfo"
    OBSERVE = "observe"  # desktop awareness (window, clipboard, apps, state, recent files)
    CALCULATE = "calculate"  # safe arithmetic evaluation
    CSV = "csv"  # bounded CSV file parsing
    JSON = "json"  # bounded JSON parse/query
    SQL = "sql"  # read-only SQLite queries
    MEMORY_OP = "memory_op"
    FILE_WRITE = "file_write"
    FILE_EDIT = "file_edit"
    BROWSE = "browse"  # Real browser interaction (click, fill, scroll, screenshot)
    GIT = "git"  # Structured Git operations (status, diff, log, branch, commit, etc.)
    GREP_SEARCH = "grep_search"  # grep-like text search (works without shell)
    PROCESS = "process"  # Process management (start, stop, restart, status, logs, wait)
    VERIFY = "verify"  # Verification (run tests, reproduce bugs, check acceptance criteria)
    REVIEW = "review"  # Code review (spec conformance, quality assessment, best practices)
    DEBUG = "debug"  # Debugging (isolate failures, trace root causes, reproduce bugs)
    ANALYZE = "analyze"  # Analysis (understand requirements, clarify what to build)
    DIAGNOSTICS = "diagnostics"  # Diagnostics (inspect errors, analyze tracebacks, inspect logs)
    CHAT = "chat"
    DELEGATE = "delegate"  # agent-initiated delegation
    DELEGATE_PARALLEL = "delegate_parallel"  # parallel delegation fan-out
    DELEGATE_INLINE = "delegate_inline"  # inline delegation (child rewrites parent history)
    PROPOSE_EDIT = "propose_str_replace"  # stage an edit proposal (no write)
    PROPOSE_WRITE = "propose_write_file"  # stage a write proposal (no write)
    APPLY_PROPOSED = "apply_proposed_edit"  # write a staged proposal to disk
    ADD_SUBGOAL = "add_subgoal"  # add a subgoal to the scratchpad
    UPDATE_SUBGOAL = "update_subgoal"  # update a subgoal's status/notes
    CREATE_PLAN = "create_plan"  # create multiple subgoals from a plan
    SKILL = "skill"  # load a skill (markdown playbook) into context
    BEST_OF_N_EDIT = "best_of_n_edit"  # N candidate edits → selector → apply winner
    DESCRIBE_TOOL = "describe_tool"  # load a long-tail tool's full schema on demand
    TODO_WRITE = "todo_write"  # agent-driven live UI todo checklist (create/update/mark)
    GET_GOAL = "get_goal"  # read the durable same-session goal
    UPDATE_GOAL = "update_goal"  # create/edit/pause/resume/complete/block/clear the goal
    WEB_RESEARCH = "web_research"  # adaptive web acquisition (search + fetch + browser)
    SEARCH_TOOL_RESULTS = "search_tool_results"  # read back a large stored tool result


# ═══════════════════════════════════════════════════════════════════════════════
# Capability — composable capability enum
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
    OBSERVE = "observe"  # desktop awareness — "what's happening right now"

    # ── Data ──
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


# ═══════════════════════════════════════════════════════════════════════════════
# Risk level
# ═══════════════════════════════════════════════════════════════════════════════


class RiskLevel(str, Enum):
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
    # Per-turn artifacts persisted with the assistant message so
    # they survive a reload. Stored as JSON in the messages table; the history
    # endpoint returns them and the frontend restores thinking blocks, error
    # cards, tool-step pills, and the cumulative context counter.
    thinking: Optional[str] = None  # accumulated reasoning trace
    # The opening acknowledgement ("I'll do X") the parent
    # streamed before the answer — shown live but previously lost on reload,
    # the same gap the thinking block had.
    acknowledgement: Optional[str] = None
    error: Optional[str] = None  # raw provider error string (normalized at the history boundary)
    tool_calls: Optional[list] = None  # tool-call timeline (pills)
    metrics: Optional[dict] = None  # {prompt_tokens, completion_tokens, latency_ms}
    # The Agent Workspace run tree + phase strip rebuilt
    # server-side from the request's obs events (frontend AgentRun[] /
    # AgentPhase[] shapes) so the Agents tab survives a reload.
    agent_runs: Optional[list] = None
    agent_phases: Optional[list] = None
    # The structured edit diff the live stream rendered (frontend DiffBlock
    # shape: {hunks, language, filePath, additions, deletions}) plus the
    # best-of-N candidate list ({index, strategy, rationale, isWinner}) —
    # both shown live but previously lost on reload.
    diff_data: Optional[dict] = None
    candidates: Optional[list] = None


class FileAttachment(BaseModel):
    filename: str
    content_type: str
    size_bytes: int
    chunks: list[str] = Field(default_factory=list)


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

    # None is the natural "no error" value a tool passes on its success path
    # (e.g. `error_type=None if success else ...`). Without this, that None
    # fails str validation and the whole ToolResult construction raises — the
    # error then gets re-wrapped as a misleading "<tool> failed: validation
    # error" even though the tool SUCCEEDED. Coerce None -> "" so the fields
    # stay real strings for consumers while accepting the intuitive None.
    @field_validator("error_type", "error_message", mode="before")
    @classmethod
    def _none_to_empty(cls, v):
        return "" if v is None else v


class AgentAbortedError(Exception):
    """Raised inside AgentLoop.run() when the user aborts the turn.

    An asyncio.Event is threaded through
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
