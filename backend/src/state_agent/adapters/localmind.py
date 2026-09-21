"""LocalMind as an environment for the state engine — adapter #1.

Everything LocalMind-specific about running the engine lives here: which actions exist (its read-only
tools), how to perform one (the shared tool dispatcher, not the parent loop), how the model is reached
(its provider adapters), and how the backend builds a run. The engine itself (``state_agent``) imports
none of this; that asymmetry is the point, and ``tests/state_agent/test_boundary.py`` enforces it.

Adding another environment (a CLI, an IDE, a browser, a standalone app) means writing another module like
this one — not touching the engine.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from state_agent.model import LLMEvaluator, LLMMoveProposer, ModelPort
from state_agent.protocols import Action, ActionSpec, Observation
from state_agent.search import EngineBudget, StateEngine
from state_agent.simulator import LLMSimulator

# ─── The environment: what the engine may do here ───────────────────────────
# READ-ONLY by construction. An action missing from this table is not an action in this environment; an
# action marked read_only=False is never probed — the engine predicts it (with a simulator) or surfaces it
# for confirmation. Adding a tool is one entry.

LOCALMIND_ACTIONS: dict[str, ActionSpec] = {
    s.name: s
    for s in (
        ActionSpec("dir_explorer", "Look inside a local folder (list/tree/stat). Read-only.",
                   '{"operation": "list|tree|stat", "path": "<folder or file>"}'),
        ActionSpec("file_task", "Read the text contents of one local FILE.", '{"path": "<file>"}'),
        ActionSpec("web_search", "Keyword web search; returns links + snippets.", '{"query": "<keywords>"}'),
        ActionSpec("web_fetch", "Fetch and read one web page.", '{"url": "<https url>"}'),
        ActionSpec("sysinfo", "Machine facts: time, OS, CPU, RAM, disk, network.", '{"query": "<what>"}'),
        ActionSpec("calculate", "Evaluate an arithmetic expression exactly.", '{"expression": "<expr>"}'),
        # Not read-only: the engine may PROPOSE it and have its outcome PREDICTED, but never performs it
        # (it surfaces needs_confirmation when no simulator is configured). This is what lets a goal that
        # needs something written be planned without anything being written.
        ActionSpec("file_write", "Write or overwrite one file with given content. NOT read-only — simulated.",
                   '{"path": "<file>", "content": "<text>"}', read_only=False),
    )
}

_OBS_MAX_CHARS = 3000
_PROBE_TIMEOUT_S = 45.0


class LocalMindEnvironment:
    """Probes actions through LocalMind's tool dispatcher and reports what really happened."""

    name = "localmind"

    def __init__(self, adapter=None, actions: Optional[dict[str, ActionSpec]] = None) -> None:
        self._adapter = adapter
        self._actions = actions if actions is not None else LOCALMIND_ACTIONS

    def tools(self) -> dict[str, ActionSpec]:
        return self._actions

    def is_read_only(self, action: Action) -> Optional[bool]:
        spec = self._actions.get(action.tool)
        return None if spec is None else spec.read_only

    async def probe(self, action: Action) -> Observation:
        from core.agent.text_tools import _extract_tool_input  # pure arg->string helper
        from core.agent.tool_dispatch import dispatch_with_retry
        from core.models import Intent
        from core.utils import bounded_output

        try:
            intent = Intent(action.tool)
        except ValueError:
            return Observation(action, False, f"unknown tool {action.tool!r}")
        try:
            text_in = _extract_tool_input(action.tool, dict(action.args))
            result, failed, _ = await asyncio.wait_for(
                dispatch_with_retry(intent, text_in, max_retries=1, adapter=self._adapter),
                timeout=_PROBE_TIMEOUT_S,
            )
        except Exception as exc:  # noqa: BLE001 — a failed probe is an observation, not a crash
            return Observation(action, False, f"{type(exc).__name__}: {exc}"[:400])
        if result is None or failed:
            detail = "no result"
            if result is not None:
                detail = getattr(result, "error_message", "") or getattr(result, "content", "") or detail
            return Observation(action, False, str(detail)[:400])
        return Observation(action, True, bounded_output(str(result.content or ""), _OBS_MAX_CHARS))


class LocalMindModel:
    """The engine's model port, answered by a LocalMind provider adapter."""

    def __init__(self, adapter) -> None:
        self._adapter = adapter

    async def complete(self, prompt: str, *, max_chars: int = 4000) -> str:
        text = ""
        async for chunk in self._adapter.chat([{"role": "user", "content": prompt}], temperature=0.2, intent="chat"):
            if getattr(chunk, "error", None):
                raise RuntimeError(str(chunk.error))
            text += getattr(chunk, "text", "") or ""
            if len(text) > max_chars:
                break
        return text


def make_model_port(adapter) -> ModelPort:
    """The port the engine's proposer/evaluator are built against."""
    return LocalMindModel(adapter)


def build_engine(
    adapter,
    budget: Optional[EngineBudget] = None,
    *,
    environment=None,
    simulator=None,
    simulate: bool = True,
) -> StateEngine:
    """A ready engine on LocalMind's tools + provider. The seam the API and the CLI both use.

    ``simulate`` (default on) means an action that must not be performed is PREDICTED rather than merely
    refused, so a goal that needs a write can be planned without anything being written.
    """
    env = environment or LocalMindEnvironment(adapter)
    port = make_model_port(adapter)
    if simulator is None and simulate:
        simulator = LLMSimulator(port)
    return StateEngine(
        env,
        proposer=LLMMoveProposer(port, env.tools()),
        evaluator=LLMEvaluator(port),
        simulator=simulator,
        budget=budget,
    )


# Back-compat alias: the API route and the prototype data used this name for the tool table.
DEFAULT_CATALOG = LOCALMIND_ACTIONS
