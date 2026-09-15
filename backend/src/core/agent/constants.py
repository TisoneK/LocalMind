"""
Agent constants — all tunable values in one place.

The legacy dispatcher-era switches (THINKING_DISPATCH_*, CHAT_AGENT_*,
CAPABILITY_ORCHESTRATION_ENABLED, AGENT_SELECTION_ENABLED) were deleted
with the ThinkingDispatcher. Only constants consumed by the
live parent-agent runtime remain.
"""

import os

from core.models import Intent

# ── Iteration budget ──────────────────────────────────────────────────────────
# Raised from 3: the previous cap of 3 was too low for multi-step
# tasks. The user's "Create hello world repo" scenario needed 6 steps
# (mkdir-check, dir-check, git-version-check, git-init, file-write, git-commit)
# but the model hit the cap at step 3 (during reconnaissance) and never reached
# the actual work. The model was doing exactly what we want — checking state
# before acting — and the cap punished it for being thorough.
#
# New default of 8 gives room for: reconnaissance (2-3 calls) + actual work
# (3-5 calls) + verification (1-2 calls). The wall-clock cap is the real
# safety net — it prevents a small model from spinning forever on a task it
# can't solve, even with 8 iterations available.
#
# Configurable via LOCALMIND_MAX_ITERATIONS env var (must be >= 1).
# LOCALMIND_AGENT_MAX_ITERATIONS is honored as a legacy alias so an existing
# .env using that name is NOT silently ignored (the old config.py
# localmind_agent_max_iterations *field* was removed, which had made the env
# var a no-op). LOCALMIND_MAX_ITERATIONS wins if both are set. This is the
# generic-loop default; the selected agent's AgentConfig.max_iterations
# overrides it when set.
_MAX_ITERATIONS_DEFAULT = 8
try:
    _env_raw = os.getenv("LOCALMIND_MAX_ITERATIONS") or os.getenv(
        "LOCALMIND_AGENT_MAX_ITERATIONS"
    )
    _env_max_iter = int(_env_raw) if _env_raw is not None else _MAX_ITERATIONS_DEFAULT
    MAX_ITERATIONS: int = max(1, _env_max_iter)
except (ValueError, TypeError):
    MAX_ITERATIONS: int = _MAX_ITERATIONS_DEFAULT

PLAN_ITERATION_COST: int = 1
CLARIFICATION_THRESHOLD: float = 0.45

# Hard wall-clock cap. The loop terminates on "done, blocked, OR
# limit" — this is the time-based limit, preventing a small model from
# spinning forever on a task it can't solve.
# Raised from 90s to 180s: the previous 90s cap was too
# aggressive — with MAX_ITERATIONS=8 and free-tier models taking ~20-30s
# per call, 90s only allowed ~3-4 iterations before the cap fired. 180s
# allows 6-8 iterations, which is enough for the recon + work + verify
# pattern. The per-call timeout (PER_CALL_TIMEOUT_SECS) is the real
# protection against a single hanging call.
#
# Configurable via LOCALMIND_MAX_WALL_CLOCK_SECS env var (must be >= 30).
_WALL_CLOCK_DEFAULT = 180.0
try:
    _env_wall = float(os.getenv("LOCALMIND_MAX_WALL_CLOCK_SECS", str(_WALL_CLOCK_DEFAULT)))
    MAX_WALL_CLOCK_SECS: float = max(30.0, _env_wall)
except (ValueError, TypeError):
    MAX_WALL_CLOCK_SECS: float = _WALL_CLOCK_DEFAULT

# Per-iteration timeout for each model call (chat_with_tools).
# This is SEPARATE from the wall-clock cap — it limits a SINGLE model call,
# not the total loop time. If a single call takes longer than this, we break
# with an error instead of waiting for the adapter's 120s HTTP timeout.
# 45s is generous for a free-tier model but prevents the 120s dead-hang.
PER_CALL_TIMEOUT_SECS: float = 45.0

# Thinking-aware per-call timeout for reasoning models
# (z.ai/GLM with thinking enabled). A reasoning model streams many thinking
# tokens BEFORE the answer; on a slow free tier that can legitimately exceed
# the 45s cap mid-thought — truncating the answer before it lands. When the
# active adapter reports thinking_enabled, the loop uses this larger budget
# instead. The wall-clock cap remains the real safety net against a spinning
# model; this only relaxes the SINGLE-call limit for models that think.
# Configurable via LOCALMIND_REASONING_TIMEOUT_SECS env var (>= 45).
_REASONING_TIMEOUT_DEFAULT = 180.0
try:
    _env_reasoning = float(os.getenv("LOCALMIND_REASONING_TIMEOUT_SECS", str(_REASONING_TIMEOUT_DEFAULT)))
    REASONING_PER_CALL_TIMEOUT_SECS: float = max(45.0, _env_reasoning)
except (ValueError, TypeError):
    REASONING_PER_CALL_TIMEOUT_SECS: float = _REASONING_TIMEOUT_DEFAULT

# Thinking-aware WALL-CLOCK cap. The 180s
# MAX_WALL_CLOCK_SECS fits only ~1-2 thinking calls on a slow free tier
# (each call can spend 30-170s reasoning before acting), so a multi-step
# turn (init + tool + answer) hits the cap before finishing. When the
# adapter reports thinking_enabled, the loop uses this larger cap instead.
# The per-call timeout, iteration cap, and bounded recovery retries remain
# the real spin protections — this only gives legitimate thinking turns
# room to finish. Configurable via LOCALMIND_REASONING_MAX_WALL_CLOCK_SECS
# env var (>= 180).
_REASONING_WALL_DEFAULT = 360.0
try:
    _env_reasoning_wall = float(
        os.getenv("LOCALMIND_REASONING_MAX_WALL_CLOCK_SECS", str(_REASONING_WALL_DEFAULT))
    )
    REASONING_MAX_WALL_CLOCK_SECS: float = max(180.0, _env_reasoning_wall)
except (ValueError, TypeError):
    REASONING_MAX_WALL_CLOCK_SECS: float = _REASONING_WALL_DEFAULT

# ── Workspace state feedback ─────────────────────────────────────────────────
# Whether to inject workspace_state.snapshot() into the agent's context
# at step 1 (assemble prompt) of each turn. This is the "observations
# flow back into context every turn" loop from the CODING HARNESS
# diagram — the literal difference between a harness and a bare API.
WORKSPACE_STATE_ENABLED: bool = True

# ── Context window protection ─────────────────────────────────────────────────

OBS_LOG_MAX_CHARS: int = 2000

# ── Tool retry config ─────────────────────────────────────────────────────────

TOOL_MAX_RETRIES: int = 1
TOOL_RETRY_BASE_DELAY: float = 0.3

# ── File operation timeouts ───────────────────────────────────────────────────

FILE_OP_TIMEOUT_SECONDS: float = 10.0
FILE_READ_MAX_BYTES: int = 512 * 1024

# ── Web-search result limits ──────────────────────────────────────────────────

WEB_SEARCH_MAX_CHARS_PER_RESULT: int = 1000
WEB_SEARCH_MAX_RESULTS: int = 5

# ── Planning phase ────────────────────────────────────────────────────────────

PLAN_ENABLED: bool = True

# ── Verification phase ────────────────────────────────────────────────────────

VERIFY_ENABLED: bool = True
VERIFY_FILE_WRITE: bool = True
VERIFY_CODE_EXEC: bool = True

# ── Reflection phase ─────────────────────────────────────────────────────────

REFLECT_ENABLED: bool = True

REFLECT_INTENTS: frozenset = frozenset(
    {
        Intent.SHELL,
        Intent.FILE_TASK,
        Intent.FILE_WRITE,
        Intent.CODE_EXEC,
        Intent.WEB_SEARCH,
        Intent.WEB_FETCH,
    }
)

# ── Intent routing ────────────────────────────────────────────────────────────

AGENT_INTENTS: frozenset[Intent] = frozenset(
    {
        Intent.CODE_EXEC,
        Intent.FILE_WRITE,
        Intent.FILE_EDIT,
        Intent.FILE_TASK,
        Intent.FIND_PATH,  # name-match search routes to the agent loop
        Intent.OBSERVE,  # desktop awareness routes to the agent loop
        Intent.CALCULATE,  # safe arithmetic routes to the agent loop
        Intent.CSV,  # bounded CSV parsing routes to the agent loop
        Intent.JSON,  # bounded JSON parse/query routes to the agent loop
        Intent.SQL,  # read-only SQLite queries route to the agent loop
        Intent.GIT,
        Intent.MEMORY_OP,
        Intent.PROCESS,
        Intent.VERIFY,
        Intent.REVIEW,
        Intent.DEBUG,
        Intent.ANALYZE,
        Intent.DIAGNOSTICS,
        Intent.SHELL,
        Intent.WEB_SEARCH,
        Intent.WEB_FETCH,
        Intent.WEB_RESEARCH,  # adaptive web acquisition
        Intent.BROWSE,
    }
)

# Agent intents whose action is obvious from
# the request itself — a direct retrieval, search, or bounded compute the
# model will execute without a planning pass. The pre-tool Thinker
# earns its serial LLM round-trip only on OPEN-ENDED objectives (ANALYZE
# "understand what to build", DEBUG, REVIEW, file/code work) where
# narration-without-action is the real risk (CONV-05/06/11). On these direct
# intents the pre-consult is dead time before the first tool, so it is
# skipped. This is a subset of AGENT_INTENTS; anything not listed keeps the
# pre-tool consult.
DIRECT_RETRIEVAL_INTENTS: frozenset[Intent] = frozenset(
    {
        Intent.WEB_SEARCH,
        Intent.WEB_FETCH,
        Intent.WEB_RESEARCH,
        Intent.FIND_PATH,
        Intent.OBSERVE,
        Intent.CALCULATE,
        Intent.CSV,
        Intent.JSON,
        Intent.SQL,
        Intent.GIT,
        Intent.MEMORY_OP,
    }
)

AGENT_ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "web_search",
        "web_fetch",
        "web_research",  # adaptive web acquisition
        "browse",
        "code_exec",
        "file_write",
        "diagnostics",
        "edit_file",
        "file_task",
        "system_search",  # unified local search — front door for find/discover questions
        "dir_explorer",  # bounded read-only folder inspection (list/tree/stat)
        "git",
        "process",
        "shell",
        "memory_op",
        "sysinfo",
        "observe",  # desktop awareness (window, clipboard, apps, state, recent files)
        "calculator",  # safe arithmetic (offline, bounded)
        "csv",  # bounded CSV parsing (offline, bounded)
        "json",  # bounded JSON parse/query (offline, bounded)
        "sql",  # read-only SQLite queries (offline, bounded)
        "delegate",  # agent-initiated delegation
        "delegate_parallel",  # parallel delegation fan-out
        "delegate_inline",  # inline delegation (child rewrites parent history)
        "propose_str_replace",  # stage an edit proposal (no write)
        "propose_write_file",  # stage a write proposal (no write)
        "apply_proposed_edit",  # write a staged proposal to disk
        "add_subgoal",  # subgoal scratchpad
        "update_subgoal",  # subgoal scratchpad
        "create_plan",  # subgoal scratchpad
        "skill",  # load a skill into context (universal tool)
        "best_of_n_edit",  # N candidate edits → selector → apply winner
        "describe_tool",  # load a long-tail tool's full schema on demand
        "todo_write",  # agent-driven live UI todo checklist (universal)
        "search_tool_results",  # read back a large stored tool result
    }
)

# ── Per-intent tool scoping ──────────────────────────────────────────────────
# The 21.9K-prompt-token bug: the agent loop sent ALL 24 tool definitions
# (~24.2K chars ≈ 6K tokens) on EVERY step of every intent — a git-status
# task paid the same fixed cost as a web-research task, 4+ times over a
# multi-step plan. Per-intent scoping intersects the agent's toolset with
# only the tools the current intent can plausibly need, cutting the fixed
# per-step cost roughly in half (24 → ~11 tools for local-execution
# intents) with zero capability loss: web tools are only relevant to
# WEB_* intents, the proposal/subgoal scratchpad to editing intents, etc.
#
# Each scope is a subset of AGENT_ALLOWED_TOOLS. Unknown intents fall back
# to the full AGENT_ALLOWED_TOOLS (safe default — same as the pre-scoping
# behavior).
_INTENT_CORE_LOCAL_TOOLS: frozenset[str] = frozenset(
    {
        "shell",
        "git",
        "file_task",
        "file_write",
        "edit_file",
        "code_exec",
        "process",
        "diagnostics",
        "sysinfo",
        "observe",  # desktop awareness — cheap, offline, bounded
        "calculator",  # safe arithmetic — cheap, offline, bounded
        "csv",  # bounded CSV parsing — cheap, offline, bounded
        "json",  # bounded JSON parse/query — cheap, offline, bounded
        "sql",  # read-only SQLite queries — cheap, offline, bounded
        "memory_op",
        "system_search",  # unified local search (files/recent/largest/duplicates/apps/open_with)
        "dir_explorer",  # bounded read-only folder inspection — look around / structure / pre-write check
        "delegate",  # keep delegation available everywhere
        "skill",  # universal tool — playbooks are cheap (~130 tok)
        "todo_write",  # live UI checklist — universal, cheap, multi-step progress
    }
)

INTENT_TOOL_SCOPES: dict[Intent, frozenset[str]] = {
    Intent.SHELL: _INTENT_CORE_LOCAL_TOOLS,
    Intent.GIT: _INTENT_CORE_LOCAL_TOOLS,
    Intent.CODE_EXEC: _INTENT_CORE_LOCAL_TOOLS,
    Intent.FILE_TASK: _INTENT_CORE_LOCAL_TOOLS,
    Intent.FIND_PATH: _INTENT_CORE_LOCAL_TOOLS,  # locate before listing
    Intent.SYSTEM_SEARCH: _INTENT_CORE_LOCAL_TOOLS,  # unified local search
    Intent.DIR_EXPLORER: _INTENT_CORE_LOCAL_TOOLS,  # folder inspection needs the local file tools too
    # Editing intents keep the proposal/best-of-N family —
    # those are coding-agent editing features that must not be lost.
    Intent.FILE_WRITE: _INTENT_CORE_LOCAL_TOOLS | frozenset(
        {"propose_write_file", "propose_str_replace", "apply_proposed_edit", "best_of_n_edit"}
    ),
    Intent.FILE_EDIT: _INTENT_CORE_LOCAL_TOOLS | frozenset(
        {"propose_str_replace", "propose_write_file", "apply_proposed_edit", "best_of_n_edit"}
    ),
    Intent.MEMORY_OP: _INTENT_CORE_LOCAL_TOOLS,
    Intent.PROCESS: _INTENT_CORE_LOCAL_TOOLS,
    Intent.SYSINFO: _INTENT_CORE_LOCAL_TOOLS,
    Intent.OBSERVE: _INTENT_CORE_LOCAL_TOOLS,  # desktop awareness
    Intent.CALCULATE: _INTENT_CORE_LOCAL_TOOLS,  # safe arithmetic
    Intent.CSV: _INTENT_CORE_LOCAL_TOOLS,  # bounded CSV parsing
    Intent.JSON: _INTENT_CORE_LOCAL_TOOLS,  # bounded JSON parse/query
    Intent.SQL: _INTENT_CORE_LOCAL_TOOLS,  # read-only SQLite queries
    Intent.DIAGNOSTICS: _INTENT_CORE_LOCAL_TOOLS,
    Intent.VERIFY: _INTENT_CORE_LOCAL_TOOLS,
    Intent.REVIEW: _INTENT_CORE_LOCAL_TOOLS,
    Intent.DEBUG: _INTENT_CORE_LOCAL_TOOLS,
    Intent.ANALYZE: _INTENT_CORE_LOCAL_TOOLS,
    # Web/browse intents keep their domain tools + delegation + skill.
    Intent.WEB_SEARCH: frozenset(
        {"web_search", "web_fetch", "delegate", "skill", "file_task", "todo_write"}
    ),
    Intent.WEB_FETCH: frozenset(
        {"web_search", "web_fetch", "delegate", "skill", "file_task", "todo_write"}
    ),
    Intent.BROWSE: frozenset({"browse", "delegate", "skill", "file_task", "todo_write"}),
    # Delegation intents only need the delegation + domain tools.
    Intent.DELEGATE: frozenset({"delegate"}),
    Intent.DELEGATE_PARALLEL: frozenset({"delegate", "delegate_parallel"}),
    Intent.DELEGATE_INLINE: frozenset({"delegate", "delegate_inline"}),
    Intent.PROPOSE_EDIT: frozenset(
        {"propose_str_replace", "edit_file", "file_task", "file_write", "apply_proposed_edit"}
    ),
    Intent.PROPOSE_WRITE: frozenset(
        {"propose_write_file", "file_write", "file_task", "apply_proposed_edit"}
    ),
    Intent.APPLY_PROPOSED: frozenset({"apply_proposed_edit", "file_write", "file_task"}),
    Intent.ADD_SUBGOAL: frozenset({"add_subgoal", "update_subgoal", "create_plan"}),
    Intent.UPDATE_SUBGOAL: frozenset({"add_subgoal", "update_subgoal", "create_plan"}),
    Intent.CREATE_PLAN: frozenset({"create_plan", "add_subgoal", "update_subgoal"}),
    Intent.SKILL: frozenset({"skill", "file_task"}),
    Intent.BEST_OF_N_EDIT: frozenset(
        {"best_of_n_edit", "propose_str_replace", "apply_proposed_edit", "file_task"}
    ),
}

# ── Answer Synthesis ────────────────────────────────────────────────────────

SYNTHESIS_ENABLED: bool = True
SYNTHESIS_TIMEOUT_SECS: int = 30

SYNTHESIS_INTENTS: frozenset[Intent] = frozenset(
    {
        Intent.WEB_SEARCH,
        Intent.WEB_FETCH,
    }
)

SYNTHESIS_TEMPLATE_FALLBACK: bool = True

ORCHESTRATOR_ENABLED: bool = True
ORCHESTRATOR_TIMEOUT_SECS: float = 10.0
ORCHESTRATOR_CONFIDENCE_HIGH: float = 0.7
ORCHESTRATOR_CONFIDENCE_MEDIUM: float = 0.4

PLAN_TIMEOUT_SECS: float = 8.0

# Thinking-aware plan/init timeout. The planning and
# initialization paths stream a model-owned JSON decision behind the scenes;
# with thinking enabled the model reasons BEFORE emitting the JSON, so the
# 8s PLAN_TIMEOUT_SECS can fire mid-thought (observed live:
# "initialization timed out after 8s" with GLM-4.5-Flash thinking ON). When
# the active adapter reports thinking_enabled, these waits use this larger
# budget. The parent loop's wall-clock cap still bounds total turn time.
# Configurable via LOCALMIND_REASONING_PLAN_TIMEOUT_SECS env var (>= 8).
_REASONING_PLAN_TIMEOUT_DEFAULT = 30.0
try:
    _env_reasoning_plan = float(
        os.getenv("LOCALMIND_REASONING_PLAN_TIMEOUT_SECS", str(_REASONING_PLAN_TIMEOUT_DEFAULT))
    )
    REASONING_PLAN_TIMEOUT_SECS: float = max(8.0, _env_reasoning_plan)
except (ValueError, TypeError):
    REASONING_PLAN_TIMEOUT_SECS: float = _REASONING_PLAN_TIMEOUT_DEFAULT
