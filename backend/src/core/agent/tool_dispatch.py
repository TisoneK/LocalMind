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

    # ADR-8 Phase 3: set the current adapter + obs so the delegate tools
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
                return result, True, attempt
            return result, result is None or not result.success, attempt
        except asyncio.TimeoutError:
            last_error = TimeoutError(
                f"tool {tool_intent.value} timed out after {timeout_secs:.0f}s"
            )
            logger.warning(
                f"[agent.dispatch] tool={tool_intent.value} attempt={attempt + 1} "
                f"timed out after {timeout_secs:.0f}s"
            )
        except Exception as exc:
            last_error = exc
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
    return None, True, max_retries
