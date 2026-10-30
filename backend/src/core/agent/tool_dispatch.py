"""
Tool dispatch with exponential-backoff retries and per-tool timeouts.

Extracted from the monolithic agent.py so that retry logic can be tested
and adjusted independently of the main loop.
"""

from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from typing import Optional

from core.agent.constants import TOOL_MAX_RETRIES, TOOL_RETRY_BASE_DELAY
from core.models import Intent, ToolResult
from tools import dispatch

logger = logging.getLogger(__name__)

# Intent → permission-key mapping. Intents not listed here
# are always allowed (e.g. CHAT, SYSINFO, OBSERVE).
_TOOL_PERMISSION_MAP: dict = {
    Intent.FILE_TASK: "file_read",
    Intent.FILE_WRITE: "file_write",
    Intent.FILE_EDIT: "file_edit",
    Intent.SHELL: "shell",
    Intent.CODE_EXEC: "code_exec",
    Intent.WEB_SEARCH: "web_search",
    Intent.WEB_FETCH: "web_fetch",
    Intent.MEMORY_OP: "memory_op",
    Intent.GREP_SEARCH: "file_read",
}

_PERMISSION_LABEL: dict[str, str] = {
    "file_read": "File read",
    "file_write": "File write",
    "file_edit": "File edit",
    "shell": "Shell",
    "code_exec": "Code execution",
    "web_search": "Web search",
    "web_fetch": "Web fetch",
    "memory_op": "Memory operations",
}

# Task-local safety fence used by autonomous objective runs. It is separate
# from model-visible tool filtering so malformed/hallucinated calls are also
# rejected immediately before dispatch.
_allowed_tool_names: ContextVar[frozenset[str] | None] = ContextVar(
    "localmind_allowed_tool_names",
    default=None,
)


def set_allowed_tool_names(names: frozenset[str] | None):
    """Set the tool fence for the current asyncio task and return its token."""
    return _allowed_tool_names.set(names)


def reset_allowed_tool_names(token) -> None:
    """Restore the previous task-local tool fence."""
    _allowed_tool_names.reset(token)


# ── Session-pinned permission mode (§U item 5, rows H + J) ──────────────────
# The mode is read from the durable store, keyed by the current turn's session
# id (set as a contextvar by the engine at turn entry — core.session_workspace).
# Resolution is fail-closed: an *answerer* that is missing or throws (no store,
# a raised read, a pinned value that is not a known mode) denies the effecting
# call. The ABSENCE of a session id is NOT an answerer failure — a tool call
# made outside a session turn (unit tests, bootstrap) resolves to the shipped
# default, so this gate never regresses today's no-session behaviour.


def _perm_store():
    """The shared SessionStore for permission reads/writes, or None if it
    cannot be obtained (treated as an answerer failure by callers)."""
    try:
        from core.config import settings
        from storage.db import get_shared_store

        return get_shared_store(settings.localmind_db_path or "./localmind.db")
    except Exception:
        return None


def _resolve_session_mode(session_id: str):
    """Return ``(mode, resolve_failed)`` for the session's pinned file-effect
    mode. ``resolve_failed`` True means the answerer failed and the caller must
    fail closed; it is never True merely because no mode was pinned."""
    import core.permission_mode as _pm

    if not session_id:
        return _pm.DEFAULT_MODE, False  # outside a session turn → default
    store = _perm_store()
    if store is None:
        return None, True  # no store → cannot answer → fail closed
    try:
        raw = store.get_permission_mode(session_id)
    except Exception:
        return None, True  # read threw → fail closed
    if raw is None:
        return _pm.DEFAULT_MODE, False  # no pin → shipped default
    mode = _pm.coerce_mode(raw)
    if mode is None:
        return None, True  # pinned to an unknown value → fail closed
    return mode, False


def gate_file_effect(tool_intent: Intent):
    """Resolve the current session's mode, decide, and open the write-ahead
    journal for a file-effecting call. The single permission policy, shared by
    every tool-execution path so none can bypass it: ``dispatch_with_retry``
    (shell / code_exec / apply_proposed / …) and the loop's typed-contract path
    (file_write / edit_file, which do not go through dispatch).

    Returns ``(decision, audit_id, store)``. For a non-effecting intent the
    decision is an allow and there is no journal (``audit_id``/``store`` None).
    An allowed effecting call gets a 'pending' journal row (resolve it with
    ``resolve_file_effect`` after the body returns); a denied call is recorded
    'done' (its body must not run).
    """
    import core.permission_mode as _pm

    if not _pm.is_file_effecting(tool_intent):
        return _pm.decide(_pm.DEFAULT_MODE, tool_intent), None, None

    from core.session_workspace import current_session_id

    sid = current_session_id() or ""
    mode, resolve_failed = _resolve_session_mode(sid)
    if resolve_failed:
        decision = _pm.deny_fail_closed(
            tool_intent, "permission mode unavailable — denied (fail-closed)"
        )
    else:
        decision = _pm.decide(mode, tool_intent)

    store = _perm_store() if sid else None
    audit_id = None
    if store is not None and sid:
        audit_id = store.record_permission_decision(
            session_id=sid,
            tool=tool_intent.value,
            mode=(decision.mode.value if decision.mode else ""),
            decision=decision.decision,
            reason=decision.reason,
            fail_closed=decision.fail_closed,
            outcome="pending" if decision.allowed else "done",
        )
    if not decision.allowed:
        logger.info(
            "[agent.dispatch] tool=%s denied by permission mode (mode=%s fail_closed=%s)",
            tool_intent.value,
            decision.mode.value if decision.mode else "unavailable",
            decision.fail_closed,
        )
    return decision, audit_id, store


def resolve_file_effect(store, audit_id, failed: bool) -> None:
    """Close an allowed effecting call's write-ahead journal row once its body
    has returned. No-op when there was no journal (non-effecting / no session)."""
    if audit_id is not None and store is not None:
        store.resolve_tool_effect(audit_id, "failed" if failed else "done")

# Error types where retrying the identical input is guaranteed to produce
# the same failure.  On these we return immediately rather than burning
# the full retry budget on pointless attempts.
_NON_RETRIABLE: frozenset[str] = frozenset(
    {
        "invalid_input",  # bad/missing code fence, malformed path, etc.
        "permission",  # tool disabled — won't change between retries
        "not_found",  # file doesn't exist — won't appear by retrying
    }
)


# Per-tool hard timeout in seconds.  Sourced from settings so operators can
# tune them via .env without touching code.  Falls back to a safe default so
# this module works even if settings are unavailable (e.g. in unit tests).
def _tool_timeout(intent: Intent) -> float:
    """Return the configured timeout for this tool intent, in seconds."""
    try:
        from core.config import settings

        mapping = {
            Intent.WEB_SEARCH: settings.ollama_timeout_web_search,
            Intent.CODE_EXEC: settings.localmind_code_exec_timeout,
            Intent.FILE_WRITE: settings.ollama_timeout_file_write,
            Intent.FILE_TASK: settings.ollama_timeout_file_task,
            Intent.SHELL: settings.ollama_timeout_shell,
            Intent.SYSINFO: settings.ollama_timeout_sysinfo,
            Intent.MEMORY_OP: settings.ollama_timeout_memory_op,
            Intent.BROWSE: settings.ollama_timeout_browse,
            Intent.WEB_RESEARCH: settings.ollama_timeout_web_research,
        }
        return float(mapping.get(intent, settings.ollama_timeout_default))
    except Exception:
        return 60.0  # safe fallback


async def dispatch_with_retry(
    tool_intent: Intent,
    tool_input: str,
    max_retries: int = TOOL_MAX_RETRIES,
    base_delay: float = TOOL_RETRY_BASE_DELAY,
    adapter=None,
    obs=None,
    allowed_tool_names: frozenset[str] | None = None,
    collect_attempts: Optional[list] = None,
) -> tuple[Optional[ToolResult], bool, int]:
    """
    Dispatch a tool with exponential-backoff retries and a per-tool timeout.

    Args:
        adapter: optional adapter instance, made available to tools that
            need it (e.g., the `delegate` tool uses it to construct the
            sub-agent with the same model + provider). When provided, it's
            set as the "current adapter" via contextvar before dispatch.
            Tools that don't need an adapter ignore it.
        obs: optional ObsCollector, made available to tools that need it
            (e.g., the `delegate` tools use it to stream the sub-agent's
            work into the parent's UI). When provided, it's set as the
            "current obs" via contextvar before dispatch. Tools that
            don't need obs ignore it.

    Returns:
        (result, failed, retry_count)
        - result:      ToolResult on success or structured failure, None on exhausted retries
        - failed:      True when the result is None or ``result.success`` is False
        - retry_count: number of retries used (0 = succeeded first try)

        ``collect_attempts``: optional list the caller owns; every failed
        attempt is appended to it as {"attempt", "error", "waited_ms"} so
        the retry ledger survives even a result of None (all retries
        exhausted) — the caller can then put it on the tool's audit record.
        When a ToolResult comes back, the same ledger is also attached to
        ``result.retry_attempts`` directly.
    """
    effective_allowed = allowed_tool_names if allowed_tool_names is not None else _allowed_tool_names.get()
    if effective_allowed is not None and tool_intent.value not in effective_allowed:
        return (
            ToolResult(
                content=(f"Tool '{tool_intent.value}' is not available in this read-only objective."),
                source=tool_intent.value,
                success=False,
                error_type="permission",
                error_message="Tool blocked by objective safety policy",
            ),
            True,
            0,
        )

    # Check configurable operation permissions.
    perm_key = _TOOL_PERMISSION_MAP.get(tool_intent)
    if perm_key is not None:
        try:
            from core.config import settings as _settings
            if not _settings.localmind_permissions.get(perm_key, True):
                label = _PERMISSION_LABEL.get(perm_key, perm_key)
                logger.info(
                    f"[agent.dispatch] tool={tool_intent.value} blocked by permission '{perm_key}'"
                )
                return (
                    ToolResult(
                        content=(
                            f"The '{label}' operation is currently disabled in "
                            "Settings. Enable it to use this tool."
                        ),
                        source=tool_intent.value,
                        success=False,
                        error_type="permission",
                        error_message=f"Permission '{perm_key}' is disabled",
                    ),
                    True,
                    0,
                )
        except Exception:
            pass  # settings unavailable — allow through

    # ── Session-pinned permission mode + write-ahead journal ────────────────
    # The shared gate (gate_file_effect) is the one policy for every tool path;
    # here it covers tools dispatched directly (shell / code_exec /
    # apply_proposed / objective runs). Only file-effecting intents are gated;
    # reads/search/web/memory pass through. A denied effecting call returns
    # before its body runs; an allowed one is journalled 'pending' now and
    # resolved to 'done'/'failed' by _finish below.
    decision, _effect_audit_id, _effect_store = gate_file_effect(tool_intent)
    if not decision.allowed:
        return (
            ToolResult(
                content=decision.reason,
                source=tool_intent.value,
                success=False,
                error_type="permission",
                error_message=decision.reason,
            ),
            True,
            0,
        )

    def _finish(result, failed, count):
        """Resolve the write-ahead journal row for an allowed effecting call,
        then hand back the dispatch tuple. Every return below goes through it so
        no exit path leaves a 'pending' row behind on a normal completion."""
        resolve_file_effect(_effect_store, _effect_audit_id, failed)
        return result, failed, count

    # Set the current adapter + obs so the delegate tools
    # can access them. The sets are conditional on the args being provided
    # (some tests call dispatch_with_retry without them).
    if adapter is not None or obs is not None:
        try:
            from tools.delegate import set_current_adapter, set_current_obs
            if adapter is not None:
                set_current_adapter(adapter)
            if obs is not None:
                set_current_obs(obs)
        except ImportError:
            # tools.delegate not yet imported (e.g., during bootstrap) — skip
            pass

    timeout_secs = _tool_timeout(tool_intent)
    last_error: Optional[Exception] = None
    # The attempt ledger: caller-owned when collect_attempts was passed (so
    # it outlives a None result), otherwise local. Entries are appended
    # BEFORE the retry sleep so even a caller-side abort between attempts
    # leaves the failed attempt on the record.
    attempts: list = collect_attempts if collect_attempts is not None else []

    for attempt in range(max_retries + 1):
        try:
            result = await asyncio.wait_for(
                dispatch(tool_intent, tool_input),
                timeout=timeout_secs,
            )
            # Short-circuit: if the tool returned a structured non-retriable error,
            # return immediately — retrying the same input is guaranteed to fail
            # the same way and wastes the retry budget. The second tuple value
            # is the tool's failure signal, not whether dispatch itself raised;
            # callers use it to drive recovery, Thinker gating, failure memory,
            # and the acceptance floor.
            if result is not None and not result.success and result.error_type in _NON_RETRIABLE:
                logger.info(
                    f"[agent.dispatch] tool={tool_intent.value} non-retriable "
                    f"error_type={result.error_type!r} — skipping retries"
                )
                if attempts:
                    result.retry_attempts = list(attempts)
                return _finish(result, True, attempt)
            if result is not None and attempts:
                result.retry_attempts = list(attempts)
            return _finish(result, result is None or not result.success, attempt)
        except asyncio.TimeoutError:
            last_error = TimeoutError(
                f"tool {tool_intent.value} timed out after {timeout_secs:.0f}s"
            )
            attempts.append(
                {
                    "attempt": attempt + 1,
                    "error": f"timed out after {timeout_secs:.0f}s",
                    "waited_ms": int(timeout_secs * 1000),
                }
            )
            logger.warning(
                f"[agent.dispatch] tool={tool_intent.value} attempt={attempt + 1} "
                f"timed out after {timeout_secs:.0f}s"
            )
        except Exception as exc:
            last_error = exc
            attempts.append(
                {
                    "attempt": attempt + 1,
                    "error": str(exc)[:300],
                    "waited_ms": int(base_delay * (2**attempt) * 1000) if attempt < max_retries else 0,
                }
            )
            if attempt < max_retries:
                delay = base_delay * (2**attempt)
                logger.warning(
                    f"[agent.dispatch] tool={tool_intent.value} attempt={attempt + 1} "
                    f"failed: {exc} — retrying in {delay:.1f}s"
                )
                await asyncio.sleep(delay)

    logger.error(
        f"[agent.dispatch] tool={tool_intent.value} exhausted {max_retries} retries: {last_error}"
    )
    return _finish(None, True, max_retries)
