"""
Tool registry and dispatch layer.

Tools self-register by importing their module. This __init__ imports all
built-in tools so they're registered at startup -- no manual wiring needed.

To add a new tool:
    1. Create tools/my_tool.py
    2. Call register_tool(Intent.MY_INTENT, my_fn, description="...", cost=0.1, latency_ms=500)
    3. Optionally register a validator: register_validator(Intent.MY_INTENT, my_validator_fn)
    4. Import it here

Validators run before dispatch and return a user-facing error string or None.
This eliminates a class of confusing tool errors (e.g. "no code found") before
they reach real I/O.
"""

from __future__ import annotations

import asyncio
from typing import Callable

from core.models import Intent, RiskLevel, ToolResult

_REGISTRY: dict[Intent, dict] = {}
_VALIDATORS: dict[Intent, Callable[[str], str | None]] = {}


def register_tool(
    intent: Intent,
    fn,
    *,
    description: str,
    cost: float = 0.1,
    latency_ms: int = 500,
    parallelizable: bool = True,  # A3: safe to run concurrently by default
):
    """Register a callable as the handler for an intent, with metadata."""
    _REGISTRY[intent] = {
        "fn": fn,
        "description": description,
        "cost": cost,
        "latency_ms": latency_ms,
        "parallelizable": parallelizable,
    }


def register_validator(intent: Intent, fn: Callable[[str], str | None]) -> None:
    """Register a pre-dispatch validator for an intent.

    fn receives the raw message string and returns:
      - None  if the payload is valid (dispatch proceeds normally)
      - str   an error message shown to the user (dispatch is skipped)

    Validators run synchronously before any I/O. Keep them fast.
    """
    _VALIDATORS[intent] = fn


async def dispatch(intent: Intent, message: str) -> ToolResult | None:
    """Dispatch to the registered tool for an intent.

    Runs the pre-dispatch validator first (if one is registered).
    Returns None if the intent has no registered handler.
    Returns a low-risk ToolResult with the error string if validation fails.
    """
    # Pre-execution validation
    validator = _VALIDATORS.get(intent)
    if validator:
        error = validator(message)
        if error:
            # success=False + error_type=invalid_input so a rejection is
            # never mistaken for a successful tool call (the previous
            # default success=True hid rejections from retry/error
            # handling and made the loop feed the message to the model as
            # if the tool had run).
            return ToolResult(
                content=error,
                risk=RiskLevel.LOW,
                source="validator",
                success=False,
                error_type="invalid_input",
                error_message=error,
            )

    entry = _REGISTRY.get(intent)
    if not entry:
        return None
    return await entry["fn"](message)


async def dispatch_parallel(
    intents_and_inputs: list[tuple[Intent, str]],
) -> list[ToolResult | None]:
    """A3: Dispatch multiple independent tools concurrently via asyncio.gather.

    Tools flagged parallelizable=False (e.g. code_exec which is stateful) are
    still run, but grouped to run after any parallel batch completes -- this
    preserves execution order safety for stateful tools while still allowing
    network-bound tools (web_search, memory_op) to run concurrently.

    Args:
        intents_and_inputs: List of (intent, input_text) pairs.

    Returns:
        List of ToolResult | None in the same order as inputs.
    """
    if not intents_and_inputs:
        return []

    # Split into parallel-safe and sequential
    parallel_idx = []
    sequential_idx = []
    for i, (intent, _) in enumerate(intents_and_inputs):
        entry = _REGISTRY.get(intent)
        if entry and entry.get("parallelizable", True):
            parallel_idx.append(i)
        else:
            sequential_idx.append(i)

    results: list[ToolResult | None] = [None] * len(intents_and_inputs)

    # Run parallelizable tools concurrently
    if parallel_idx:
        tasks = [dispatch(intents_and_inputs[i][0], intents_and_inputs[i][1]) for i in parallel_idx]
        parallel_results = await asyncio.gather(*tasks, return_exceptions=True)
        for idx, res in zip(parallel_idx, parallel_results):
            results[idx] = None if isinstance(res, BaseException) else res

    # Run sequential tools one at a time
    for i in sequential_idx:
        try:
            results[i] = await dispatch(intents_and_inputs[i][0], intents_and_inputs[i][1])
        except Exception:
            results[i] = None

    return results


def available_tools() -> list[dict]:
    """Return metadata for all registered tools."""
    return [
        {
            "intent": intent.value,
            "description": meta["description"],
            "cost": meta["cost"],
            "latency_ms": meta["latency_ms"],
            "parallelizable": meta.get("parallelizable", True),
        }
        for intent, meta in _REGISTRY.items()
    ]


# -- Auto-register all built-in tools -----------------------------------------
# Import order matters: file_reader must be before engine uses parse_file
from tools import (
    apply_proposed,  # noqa: E402, F401 -- B-2026-08-02-7: write a staged proposal to disk
    # Last: best_of_n_edit module-level-imports delegate/delegate_parallel/
    # edit_file — importing it here guarantees those are loaded first.
    best_of_n_edit,  # noqa: E402, F401 -- B-2026-08-02-11: N candidate edits → selector → apply
    browser_agent,  # noqa: E402, F401 -- BROWSE (real browser interaction)
    calculator,  # noqa: E402, F401 -- B-2026-07-31-10: CALCULATE (safe arithmetic)
    code_exec,  # noqa: E402, F401 -- registers CODE_EXEC
    csv_tool,  # noqa: E402, F401 -- B-2026-07-31-10: CSV (bounded CSV parsing)
    delegate,  # noqa: E402, F401 -- ADR-8 Phase 3: agent-initiated delegation
    delegate_inline,  # noqa: E402, F401 -- B-2026-08-02-9: inline delegation (after delegate: imports its contextvars)
    delegate_parallel,  # noqa: E402, F401 -- B-2026-08-02-6: parallel delegation fan-out
    describe_tool,  # noqa: E402, F401 -- ADR-40 option C: load a long-tail tool's full schema on demand
    diagnostics,  # noqa: E402, F401 -- DIAGNOSTICS (structured failure analysis)
    edit_file,  # noqa: E402, F401 -- FILE_EDIT (in-place file editing)
    file_reader,  # noqa: E402, F401 -- registers FILE_TASK
    file_writer,  # noqa: E402, F401 -- FILE_WRITE (secondary intent)
    find_path,  # noqa: E402, F401 -- FIND_PATH (name-match search, path-only, capped)
    git_tool,  # noqa: E402, F401 -- GIT (structured git operations)
    json_tool,  # noqa: E402, F401 -- B-2026-07-31-10: JSON (bounded JSON parse/query)
    memory_tool,  # noqa: E402, F401 -- registers MEMORY_OP
    observe,  # noqa: E402, F401 -- B-2026-07-31-9: OBSERVE (desktop awareness: window, clipboard, apps, state, recent files)
    process_tool,  # noqa: E402, F401 -- PROCESS (long-running process management)
    propose_edit,  # noqa: E402, F401 -- B-2026-08-02-7: stage an edit proposal (no write)
    propose_write,  # noqa: E402, F401 -- B-2026-08-02-7: stage a write proposal (no write)
    shell,  # noqa: E402, F401 -- registers SHELL
    skill,  # noqa: E402, F401 -- B-2026-08-02-12: load a skill into context
    sql_tool,  # noqa: E402, F401 -- B-2026-07-31-10: SQL (read-only SQLite queries)
    subgoal,  # noqa: E402, F401 -- B-2026-08-02-8: subgoal scratchpad tools
    sysinfo,  # noqa: E402, F401 -- registers SYSINFO (offline: time, date, specs)
    todo_write,  # noqa: E402, F401 -- ADR-43: agent-driven live UI todo checklist
    web_fetch,  # noqa: E402, F401 -- registers WEB_FETCH (follow-up URL fetching)
    web_search,  # noqa: E402, F401 -- registers WEB_SEARCH
    web_research,  # noqa: E402, F401 -- Session 340: adaptive web acquisition (search + fetch + browser)
)
