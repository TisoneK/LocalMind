"""
Agent constants — all tunable values in one place.

The legacy dispatcher-era switches (THINKING_DISPATCH_*, CHAT_AGENT_*,
CAPABILITY_ORCHESTRATION_ENABLED, AGENT_SELECTION_ENABLED) were deleted
with the ThinkingDispatcher (Session 239). Only constants consumed by the
live parent-agent runtime remain.
"""

import os

from core.models import Intent

# ── Iteration budget ──────────────────────────────────────────────────────────
# Session 32 (raised from 3): the previous cap of 3 was too low for multi-step
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
# The old config.py localmind_agent_max_iterations (default 6) was dead
# code — removed. This env var is the generic-loop default; the selected
# agent's AgentConfig.max_iterations overrides it per ADR-8 Phase 2.
_MAX_ITERATIONS_DEFAULT = 8
try:
    _env_max_iter = int(os.getenv("LOCALMIND_MAX_ITERATIONS", str(_MAX_ITERATIONS_DEFAULT)))
    MAX_ITERATIONS: int = max(1, _env_max_iter)
except (ValueError, TypeError):
    MAX_ITERATIONS: int = _MAX_ITERATIONS_DEFAULT

PLAN_ITERATION_COST: int = 1
CLARIFICATION_THRESHOLD: float = 0.45

# ADR-5: hard wall-clock cap. The loop terminates on "done, blocked, OR
# limit" — this is the time-based limit, preventing a small model from
# spinning forever on a task it can't solve.
# Session 32 (raised from 90s to 180s): the previous 90s cap was too
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

# Session 31: per-iteration timeout for each model call (chat_with_tools).
# This is SEPARATE from the wall-clock cap — it limits a SINGLE model call,
# not the total loop time. If a single call takes longer than this, we break
# with an error instead of waiting for the adapter's 120s HTTP timeout.
# 45s is generous for a free-tier model but prevents the 120s dead-hang.
PER_CALL_TIMEOUT_SECS: float = 45.0

# ── Workspace state feedback (ADR-5) ─────────────────────────────────────────
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
        Intent.FIND_PATH,  # Session 125: name-match search routes to the agent loop
        Intent.OBSERVE,  # B-2026-07-31-9: desktop awareness routes to the agent loop
        Intent.CALCULATE,  # B-2026-07-31-10: safe arithmetic routes to the agent loop
        Intent.CSV,  # B-2026-07-31-10: bounded CSV parsing routes to the agent loop
        Intent.JSON,  # B-2026-07-31-10: bounded JSON parse/query routes to the agent loop
        Intent.SQL,  # B-2026-07-31-10: read-only SQLite queries route to the agent loop
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
        Intent.BROWSE,
    }
)

AGENT_ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "web_search",
        "web_fetch",
        "browse",
        "code_exec",
        "file_write",
        "diagnostics",
        "edit_file",
        "file_task",
        "find_path",
        "git",
        "process",
        "shell",
        "memory_op",
        "sysinfo",
        "observe",  # B-2026-07-31-9: desktop awareness (window, clipboard, apps, state, recent files)
        "calculator",  # B-2026-07-31-10: safe arithmetic (offline, bounded)
        "csv",  # B-2026-07-31-10: bounded CSV parsing (offline, bounded)
        "json",  # B-2026-07-31-10: bounded JSON parse/query (offline, bounded)
        "sql",  # B-2026-07-31-10: read-only SQLite queries (offline, bounded)
        "delegate",  # ADR-8 Phase 3: agent-initiated delegation
        "delegate_parallel",  # B-2026-08-02-6: parallel delegation fan-out
        "delegate_inline",  # B-2026-08-02-9: inline delegation (child rewrites parent history)
        "propose_str_replace",  # B-2026-08-02-7: stage an edit proposal (no write)
        "propose_write_file",  # B-2026-08-02-7: stage a write proposal (no write)
        "apply_proposed_edit",  # B-2026-08-02-7: write a staged proposal to disk
        "add_subgoal",  # B-2026-08-02-8: subgoal scratchpad
        "update_subgoal",  # B-2026-08-02-8: subgoal scratchpad
        "create_plan",  # B-2026-08-02-8: subgoal scratchpad
        "skill",  # B-2026-08-02-12: load a skill into context (universal tool)
        "best_of_n_edit",  # B-2026-08-02-11: N candidate edits → selector → apply winner
        "describe_tool",  # ADR-40 option C: load a long-tail tool's full schema on demand
    }
)

# ── Per-intent tool scoping (Session 124) ────────────────────────────────────
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
# to the full AGENT_ALLOWED_TOOLS (safe default — same as pre-Session-124
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
        "observe",  # B-2026-07-31-9: desktop awareness — cheap, offline, bounded
        "calculator",  # B-2026-07-31-10: safe arithmetic — cheap, offline, bounded
        "csv",  # B-2026-07-31-10: bounded CSV parsing — cheap, offline, bounded
        "json",  # B-2026-07-31-10: bounded JSON parse/query — cheap, offline, bounded
        "sql",  # B-2026-07-31-10: read-only SQLite queries — cheap, offline, bounded
        "memory_op",
        "find_path",  # Session 125: name-match search (locate before listing)
        "delegate",  # ADR-8 Phase 3: keep delegation available everywhere
        "skill",  # B-2026-08-02-12: universal tool — playbooks are cheap (~130 tok)
    }
)

INTENT_TOOL_SCOPES: dict[Intent, frozenset[str]] = {
    Intent.SHELL: _INTENT_CORE_LOCAL_TOOLS,
    Intent.GIT: _INTENT_CORE_LOCAL_TOOLS,
    Intent.CODE_EXEC: _INTENT_CORE_LOCAL_TOOLS,
    Intent.FILE_TASK: _INTENT_CORE_LOCAL_TOOLS,
    Intent.FIND_PATH: _INTENT_CORE_LOCAL_TOOLS,  # Session 125: locate before listing
    # Editing intents keep the proposal/best-of-N family (B-2026-08-02-7/11)
    # — those are coding-agent editing features that must not be lost.
    Intent.FILE_WRITE: _INTENT_CORE_LOCAL_TOOLS | frozenset(
        {"propose_write_file", "propose_str_replace", "apply_proposed_edit", "best_of_n_edit"}
    ),
    Intent.FILE_EDIT: _INTENT_CORE_LOCAL_TOOLS | frozenset(
        {"propose_str_replace", "propose_write_file", "apply_proposed_edit", "best_of_n_edit"}
    ),
    Intent.MEMORY_OP: _INTENT_CORE_LOCAL_TOOLS,
    Intent.PROCESS: _INTENT_CORE_LOCAL_TOOLS,
    Intent.SYSINFO: _INTENT_CORE_LOCAL_TOOLS,
    Intent.OBSERVE: _INTENT_CORE_LOCAL_TOOLS,  # B-2026-07-31-9: desktop awareness
    Intent.CALCULATE: _INTENT_CORE_LOCAL_TOOLS,  # B-2026-07-31-10: safe arithmetic
    Intent.CSV: _INTENT_CORE_LOCAL_TOOLS,  # B-2026-07-31-10: bounded CSV parsing
    Intent.JSON: _INTENT_CORE_LOCAL_TOOLS,  # B-2026-07-31-10: bounded JSON parse/query
    Intent.SQL: _INTENT_CORE_LOCAL_TOOLS,  # B-2026-07-31-10: read-only SQLite queries
    Intent.DIAGNOSTICS: _INTENT_CORE_LOCAL_TOOLS,
    Intent.VERIFY: _INTENT_CORE_LOCAL_TOOLS,
    Intent.REVIEW: _INTENT_CORE_LOCAL_TOOLS,
    Intent.DEBUG: _INTENT_CORE_LOCAL_TOOLS,
    Intent.ANALYZE: _INTENT_CORE_LOCAL_TOOLS,
    # Web/browse intents keep their domain tools + delegation + skill.
    Intent.WEB_SEARCH: frozenset(
        {"web_search", "web_fetch", "delegate", "skill", "file_task"}
    ),
    Intent.WEB_FETCH: frozenset(
        {"web_search", "web_fetch", "delegate", "skill", "file_task"}
    ),
    Intent.BROWSE: frozenset({"browse", "delegate", "skill", "file_task"}),
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
