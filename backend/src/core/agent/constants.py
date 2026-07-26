"""
Agent constants — all tunable values in one place.

v3.0: Updated for Dynamic Capability Orchestration architecture.
- CAPABILITY_ORCHESTRATION_ENABLED is now always True (no rollback)
- Removed all DEPRECATED legacy switches
- Capability-aware constants only
"""

from core.models import Intent

# ── Iteration budget ──────────────────────────────────────────────────────────

MAX_ITERATIONS: int = 5
PLAN_ITERATION_COST: int = 1
CLARIFICATION_THRESHOLD: float = 0.45

# ADR-5: hard wall-clock cap. The loop terminates on "done, blocked, OR
# limit" — this is the time-based limit, preventing a small model from
# spinning forever on a task it can't solve. Sized for gemma3:1b-class
# target hardware where every iteration is expensive. 300s = 5 minutes.
MAX_WALL_CLOCK_SECS: float = 300.0

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
        Intent.MEMORY_OP,
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
        "shell",
        "memory_op",
        "sysinfo",
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
