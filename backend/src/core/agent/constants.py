"""
Agent constants — all tunable values in one place.

v3.0: Updated for Dynamic Capability Orchestration architecture.
- CAPABILITY_ORCHESTRATION_ENABLED is now always True (no rollback)
- Removed all DEPRECATED legacy switches
- Capability-aware constants only
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
# config.py also has localmind_agent_max_iterations (default 6) but that
# value was never read — this env var is the actual source of truth.
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

# ── Agent selection (ADR-6) ──────────────────────────────────────────────────
# Whether the engine uses agents.registry.select_agent(intent) to pick
# the agent for a given intent, instead of calling AgentLoop directly.
# When True, the engine constructs the selected agent and calls its
# run() method — which passes the agent's scoped toolset to AgentLoop
# (ADR-6: a coding agent sees only 5 tools, a browser agent sees only 1,
# etc.). When False, the engine calls AgentLoop directly with the global
# AGENT_ALLOWED_TOOLS (pre-ADR-6 behavior).
AGENT_SELECTION_ENABLED: bool = True

# ── Context window protection ─────────────────────────────────────────────────

OBS_LOG_MAX_CHARS: int = 2000

# ── Tool retry config ─────────────────────────────────────────────────────────

TOOL_MAX_RETRIES: int = 1
TOOL_RETRY_BASE_DELAY: float = 0.3

# ── File operation timeouts ───────────────────────────────────────────────────

FILE_OP_TIMEOUT_SECONDS: float = 10.0
FILE_READ_MAX_BYTES: int = 512 * 1024
SHELL_OP_TIMEOUT_SECONDS: float = 20.0

# ── Follow-up detection ───────────────────────────────────────────────────────

FOLLOWUP_HISTORY_DEPTH: int = 6

# ── Web-search result limits ──────────────────────────────────────────────────

WEB_SEARCH_MAX_CHARS_PER_RESULT: int = 1000
WEB_SEARCH_MAX_RESULTS: int = 5

# ── Agent response streaming ──────────────────────────────────────────────────

AGENT_THINKING_MIN_CHARS: int = 20

# ── Planning phase ────────────────────────────────────────────────────────────

PLAN_ENABLED: bool = True
PLAN_MAX_TOKENS: int = 512

# ── Verification phase ────────────────────────────────────────────────────────

VERIFY_ENABLED: bool = True
VERIFY_FILE_WRITE: bool = True
VERIFY_CODE_EXEC: bool = True

# ── Reflection phase ─────────────────────────────────────────────────────────

REFLECT_ENABLED: bool = True
REFLECT_MAX_TOKENS: int = 256

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

# ── Capability Orchestration (v3.0) ───────────────────────────────────────────

CAPABILITY_ORCHESTRATION_ENABLED: bool = True
"""Always True in v4.0. The ThinkingDispatcher is the sole routing mechanism."""

ORCHESTRATOR_TIMEOUT_SECS: float = 10.0
ORCHESTRATOR_TEMPERATURE: float = 0.2

# ── Intent routing ────────────────────────────────────────────────────────────

AGENT_INTENTS: frozenset[Intent] = frozenset(
    {
        Intent.CODE_EXEC,
        Intent.FILE_WRITE,
        Intent.FILE_EDIT,
        Intent.FILE_TASK,
        Intent.GIT,
        Intent.MEMORY_OP,
        Intent.PROCESS,
        Intent.VERIFY,
        Intent.REVIEW,
        Intent.DEBUG,
        Intent.ANALYZE,
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
        "edit_file",
        "file_task",
        "git",
        "process",
        "shell",
        "memory_op",
        "sysinfo",
        "delegate",  # ADR-8 Phase 3: agent-initiated delegation
    }
)

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

# ── Legacy DEPRECATED constants ──────────────────────────────────────────────
# These are kept ONLY for import compatibility during migration.
# They are NOT used in the v3.0 pipeline.

THINKING_DISPATCH_ENABLED: bool = True
THINKING_DISPATCH_TIMEOUT_SECS: float = 12.0
DISPATCHER_HIGH_CONFIDENCE_SKIP: float = 0.6

CHAT_AGENT_ENABLED: bool = True
CHAT_AGENT_MIN_COMPLEXITY: float = 0.4
CHAT_AGENT_MAX_TOKENS: int = 300
CHAT_AGENT_TIMEOUT_SECS: float = 8.0
CHAT_AGENT_SKIP_PATTERNS: list[str] = [
    r"^(hi|hello|hey|howdy|greetings)\s*$",
    r"^(thanks?|thank you|thx)\s*$",
    r"^(ok|okay|yes|no|sure|alright|yep|nope)\s*$",
    r"^[\s\W]{0,15}$",
]

ORCHESTRATOR_ENABLED: bool = True
ORCHESTRATOR_MAX_TOKENS: int = 400
ORCHESTRATOR_TIMEOUT_SECS: float = 10.0
ORCHESTRATOR_CONFIDENCE_HIGH: float = 0.7
ORCHESTRATOR_CONFIDENCE_MEDIUM: float = 0.4

PLAN_TIMEOUT_SECS: float = 8.0
