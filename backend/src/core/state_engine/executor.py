"""Run a move against the real tool dispatcher and return what it produced."""
from __future__ import annotations

import asyncio
from typing import Optional, Protocol

from core.state_engine.state import Move, Observation
from core.utils import bounded_output

_OBS_MAX_CHARS = 3000


class Executor(Protocol):
    async def run(self, move: Move) -> Observation: ...


class RegistryExecutor:
    """The default executor: the shared tool dispatcher, not the parent loop."""

    def __init__(self, adapter=None, timeout_s: float = 45.0) -> None:
        self._adapter = adapter
        self._timeout_s = timeout_s

    async def run(self, move: Move) -> Observation:
        from core.agent.text_tools import _extract_tool_input  # pure arg->string helper
        from core.agent.tool_dispatch import dispatch_with_retry
        from core.models import Intent

        try:
            intent = Intent(move.tool)
        except ValueError:
            return Observation(move, False, f"unknown tool {move.tool!r}")
        try:
            text_in = _extract_tool_input(move.tool, dict(move.args))
            result, failed, _ = await asyncio.wait_for(
                dispatch_with_retry(intent, text_in, max_retries=1, adapter=self._adapter),
                timeout=self._timeout_s,
            )
        except Exception as exc:  # noqa: BLE001 — a failed probe is an observation, not a crash
            return Observation(move, False, f"{type(exc).__name__}: {exc}"[:400])
        if result is None or failed:
            detail = "no result"
            if result is not None:
                detail = getattr(result, "error_message", "") or getattr(result, "content", "") or detail
            return Observation(move, False, str(detail)[:400])
        return Observation(move, True, bounded_output(str(result.content or ""), _OBS_MAX_CHARS))


def read_only(move: Move, catalog) -> Optional[bool]:
    spec = catalog.get(move.tool)
    return None if spec is None else spec.read_only
