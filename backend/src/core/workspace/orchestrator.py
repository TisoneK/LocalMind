"""
Workspace Orchestrator — v2.0 (Contract Layer)

The orchestrator is the only component that sees everything.
Every tool sees only its own typed payload.

Flow
────
  1. Plan   — LLM reads the user message, produces a structured task list.
              Each task declares one tool and emits a typed input dict.
              Dependencies are declared explicitly.

  2. Dispatch — For each task whose dependencies are satisfied:
                a. Validate input dict against the tool's ToolContract schema.
                   HARD REJECT on any schema violation — no fallback.
                b. Dispatch via contract.execute(payload) if the tool has a
                   full ToolContract, else via legacy dispatch(intent, json).
                c. Write result to outbox.
                d. Promote result to CONTEXT.md under the tool's section name.
                e. Mark task done in TODO.md.
                f. Check if any newly-unblocked tasks can now run.
                Parallelizable tasks with satisfied deps run concurrently.

  3. Synthesise — LLM reads CONTEXT.md (all sections) + original message,
                  produces the final answer.

Contract enforcement (the core rule — v2.0 addition)
──────────────────────────────────────────────────────
  Before any tool executes, its input payload is validated against the
  registered ToolContract schema.  A mismatch raises ContractViolationError.
  The orchestrator hard-rejects the task:
    - No retry, no fallback, no NL interpretation.
    - The rejection is surfaced in CONTEXT.md so synthesis can report it.

  Tools with full Phase 3 contracts (currently: shell) execute via
  contract.execute(payload).  Tools still on the legacy bridge execute via
  dispatch(intent, json.dumps(payload)).

Planner output format (v2.0 — structured input)
────────────────────────────────────────────────
  Tasks now carry a typed `input` dict matching the tool's schema.
  The planner no longer emits natural-language goal sentences — it emits
  structured field values the tool can execute directly.

  Old (v1):  {"id": "t1", "tool": "web_search", "goal": "find prices", "depends_on": []}
  New (v2):  {"id": "t1", "tool": "web_search", "input": {"query": "DDR5 32GB prices 2025"}, "depends_on": []}
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, AsyncIterator, Dict, Optional

from core.models import Intent, StreamChunk, ToolResult
from core.workspace.manager import WorkspaceManager
from tools import available_tools
from tools.contracts import (
    TOOL_SCHEMAS,
    ContractViolationError,
    ToolRegistry,
)

logger = logging.getLogger(__name__)

# ── Intent → tool name mapping ────────────────────────────────────────────────
_TOOL_NAME_TO_INTENT: dict[str, Intent] = {
    "sysinfo": Intent.SYSINFO,
    "web_search": Intent.WEB_SEARCH,
    "web_fetch": Intent.WEB_FETCH,
    "file_task": Intent.FILE_TASK,
    "file_write": Intent.FILE_WRITE,
    "code_exec": Intent.CODE_EXEC,
    "shell": Intent.SHELL,
    "memory_op": Intent.MEMORY_OP,
}

# ── Context needs — which CONTEXT.md sections each tool may see ───────────────
TOOL_CONTEXT_NEEDS: dict[str, list[str]] = {
    "web_search": [],
    "web_fetch": [],
    "file_write": [
        "sysinfo",
        "web_search",
        "web_fetch",
        "code_exec",
        "shell",
        "memory_op",
        "file_task",
    ],
    "code_exec": ["sysinfo", "file_task"],
    "shell": ["sysinfo"],
    "memory_op": [],
    "sysinfo": [],
    "file_task": [],
}


# ── Schema reference block injected into the planner prompt ───────────────────
# Built from TOOL_SCHEMAS so the planner sees exactly what each tool expects.
def _build_schema_reference() -> str:
    lines = ["Input schemas (planner MUST match these exactly):"]
    for tool, schema in TOOL_SCHEMAS.items():
        field_list = ", ".join(f'"{k}": {v.__name__}' for k, v in schema.items())
        lines.append(f"  {tool}: {{{field_list}}}")
    return "\n".join(lines)


# ── Planner prompt ────────────────────────────────────────────────────────────
_PLANNER_SYSTEM = """\
You are a task planner for a local AI assistant. Given a user request, output a structured JSON task list.

Available tools:
{tool_list}

{schema_reference}

Rules:
- Use only the tools listed above.
- Each task has exactly one tool.
- `input` MUST be a dict matching the tool's schema above — no extra keys, no missing required keys.
- Declare depends_on only when the tool genuinely needs a prior tool's output.
- If the request needs only one tool, output one task.
- If the request can be answered from knowledge alone, output an empty task list.
- `input` values must be concrete and specific — not goal sentences, not "the file the user mentioned".

CRITICAL — file_write rules:
- `content` is the EXACT literal text to write. Write it yourself directly in the plan.
- NEVER use shell or code_exec to generate content for file_write to save. That is always wrong.
  Example: "write a Python hello world to Documents" → ONE file_write task, content="print('Hello, World!')'"
- Only set depends_on on file_write when content genuinely requires another tool's runtime output
  (e.g. live web search results, real sysinfo readings). Never for content you can write directly.

Respond with ONLY a JSON array, no markdown, no explanation:
[
  {{"id": "t1", "tool": "sysinfo", "input": {{"goal": "Get current RAM usage and total installed memory"}}, "depends_on": []}},
  {{"id": "t2", "tool": "web_search", "input": {{"query": "DDR5 32GB upgrade options prices 2025"}}, "depends_on": []}},
  {{"id": "t3", "tool": "file_write", "input": {{"path": "~/LocalMind/ram_report.md", "content": "# RAM Report\\n..."}}, "depends_on": ["t1", "t2"]}}
]"""

_PLANNER_USER = "User request: {message}"

# ── Synthesis prompt ──────────────────────────────────────────────────────────
_SYNTHESIS_SYSTEM = """\
You are LocalMind. Using the tool results below, answer the user's request directly.

Rules:
- Report tool results accurately — do not substitute your own estimates.
- Be concise. Use markdown only for code blocks and tables.
- If a tool failed or was rejected due to a schema error, say so plainly.
- If a contract violation occurred, explain that the planner emitted an invalid payload.
- NEVER fabricate data. If no tool results are provided, say you couldn't retrieve the information rather than making up answers.
- Every specific detail (file names, folder contents, system specs, search results) MUST come from the tool results above.
- If the tool results show 3 items, report 3 items — never add items that "seem typical"."""

_MAX_CONTEXT_TOKENS = 2000
_MAX_SECTION_CHARS = 2000


# ── Orchestrator ──────────────────────────────────────────────────────────────


class WorkspaceOrchestrator:
    """
    Contract-enforced parallel-track orchestrator.

    v2.0 changes vs v1.0:
      - Planner emits structured `input` dicts, not goal sentences.
      - _run_one_task validates payload against ToolContract before dispatch.
      - ContractViolationError causes a hard reject — no fallback.
      - Tools with full Phase 3 contracts execute via contract.execute(payload).
      - Legacy tools execute via dispatch(intent, json.dumps(payload)).
    """

    def __init__(self, adapter):
        self._adapter = adapter

    async def run(
        self,
        message: str,
        session_id: str,
        memory_facts: list[str],
        obs,
        adapter=None,
    ) -> AsyncIterator[StreamChunk]:
        ws = WorkspaceManager.new()
        logger.info("[orch] turn=%s session=%s", ws.turn_id, session_id)

        try:
            if memory_facts:
                ws.write_context("memory", "\n".join(f"- {f}" for f in memory_facts))

            # ── 1. Plan ───────────────────────────────────────────────────────
            obs.emit("workspace_planning", turn=ws.turn_id)
            tasks = await self._plan(message, ws, adapter)

            if not tasks:
                logger.info("[orch] planner: no tools needed, direct answer")
                # ANTI-FABRICATION: When the planner fails to produce tasks but
                # the intent clearly requires tool use (SHELL, FILE_TASK, etc.),
                # do NOT synthesize with skip_context=True — that would cause
                # the LLM to fabricate answers from training data.
                # Instead, inform the user that the tool couldn't be used.
                _TOOL_INTENTS = {"shell", "file_task", "web_search", "sysinfo"}
                if any(
                    t in message.lower()
                    for t in [
                        "file",
                        "folder",
                        "directory",
                        "list",
                        "show",
                        "dir",
                        "ls",
                        "disk",
                        "system",
                        "search",
                    ]
                ):
                    yield StreamChunk(
                        text='I wasn\'t able to execute that command. Could you try rephrasing your request? For example: "Run dir Documents" or "List files in my Code folder".',
                        done=False,
                    )
                    yield StreamChunk(text="", done=True)
                    return
                async for chunk in self._synthesise(message, ws, obs, skip_context=True, adapter=adapter):
                    yield chunk
                return

            ws.write_todo(tasks)
            logger.info(
                "[orch] planned %d tasks: %s",
                len(tasks),
                [t["tool"] for t in tasks],
            )
            obs.emit(
                "workspace_tasks_planned",
                count=len(tasks),
                tools=[t["tool"] for t in tasks],
            )

            # ── 2. Dispatch loop ──────────────────────────────────────────────
            await self._dispatch_loop(tasks, ws, obs)

            # ── 3. Synthesise or surface confirmation prompt ──────────────────
            # If a file_write task is waiting for user confirmation, skip the
            # synthesiser entirely — it would read the confirmation question
            # from CONTEXT.md and answer "Yes" on the user's behalf.
            # Instead, stream the confirmation prompt directly and attach the
            # pending payload to the done chunk for the engine to persist.
            pending = getattr(ws, "pending_confirmation", None)
            if pending:
                # Pull the confirmation text from the file_write outbox
                confirmation_text = ws.read_outbox("file_write").strip()
                if not confirmation_text:
                    confirmation_text = (
                        f"I want to write **{pending.get('filename', 'file')}** to:\n"
                        f"`{pending.get('path', '')}` — reply **yes** to confirm."
                    )
                yield StreamChunk(text=confirmation_text, done=False)
                yield StreamChunk(
                    text="",
                    done=True,
                    metadata={"pending_write": pending},
                )
                return

            chunks = []
            async for chunk in self._synthesise(message, ws, obs, adapter=adapter):
                chunks.append(chunk)
                if not chunk.done:
                    yield chunk

            done_chunk = chunks[-1] if chunks else StreamChunk(text="", done=True)
            yield done_chunk

        except Exception as exc:
            logger.error("[orch] fatal error: %s", exc, exc_info=True)
            yield StreamChunk(text=f"Orchestrator error: {exc}", done=False)
            yield StreamChunk(text="", done=True)
        finally:
            ws.cleanup()

    # ── Planning ──────────────────────────────────────────────────────────────

    async def _plan(self, message: str, ws: WorkspaceManager, adapter=None) -> list[dict]:
        """Ask the LLM to produce a structured task list with typed input dicts."""
        tools = available_tools()
        tool_list = "\n".join(f"- {t['intent']}: {t['description']}" for t in tools)
        schema_reference = _build_schema_reference()

        messages = [
            {
                "role": "system",
                "content": _PLANNER_SYSTEM.format(
                    tool_list=tool_list,
                    schema_reference=schema_reference,
                ),
            },
            {"role": "user", "content": _PLANNER_USER.format(message=message)},
        ]

        active_adapter = adapter or self._adapter
        chunks: list[str] = []
        try:
            async for chunk in active_adapter.chat(messages, temperature=0.0):
                if chunk.error:
                    logger.warning("[orch] planner adapter error: %s", chunk.error[:120])
                    break
                chunks.append(chunk.text)
        except Exception as exc:
            logger.warning("[orch] planner LLM failed: %s", exc)
            return []

        raw = "".join(chunks).strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)

        try:
            data = json.loads(raw)
            if not isinstance(data, list):
                return []
            tasks = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                tool = item.get("tool", "").strip().lower()
                if tool not in _TOOL_NAME_TO_INTENT:
                    logger.warning("[orch] planner returned unknown tool: %s", tool)
                    continue

                # v2.0: tasks carry `input` dict, not `goal` string.
                # Accept `goal` as a fallback for backward compat during rollout,
                # wrapping it in a minimal dict so validation can reject it clearly.
                raw_input = item.get("input")
                if raw_input is None:
                    # Planner emitted old-format task — treat as validation failure
                    logger.warning(
                        "[orch] planner emitted old-format task for '%s' (missing 'input'). "
                        "Update planner prompt or model.",
                        tool,
                    )
                    raw_input = {}  # will fail contract validation → clean rejection

                if not isinstance(raw_input, dict):
                    logger.warning("[orch] task input for '%s' is not a dict: %r", tool, raw_input)
                    raw_input = {}

                tasks.append(
                    {
                        "id": item.get("id", f"t{len(tasks) + 1}"),
                        "tool": tool,
                        "input": raw_input,
                        "depends_on": item.get("depends_on", []),
                    }
                )
            ws.write_thinking(f"Plan:\n{json.dumps(tasks, indent=2)}")
            return tasks
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("[orch] planner JSON parse failed: %s — raw: %s", exc, raw[:200])
            return []

    # ── Dispatch loop ─────────────────────────────────────────────────────────

    async def _dispatch_loop(
        self,
        tasks: list[dict],
        ws: WorkspaceManager,
        obs,
    ) -> None:
        remaining = {t["id"]: t for t in tasks}
        in_flight: set[str] = set()

        while remaining or in_flight:
            completed = ws.completed_task_ids()
            runnable = [
                t
                for tid, t in remaining.items()
                if tid not in in_flight and all(dep in completed for dep in t["depends_on"])
            ]

            if not runnable and not in_flight:
                logger.warning("[orch] dependency deadlock — forcing remaining tasks")
                runnable = list(remaining.values())

            if runnable:
                coros = []
                for task in runnable:
                    in_flight.add(task["id"])
                    del remaining[task["id"]]
                    obs.emit(
                        "workspace_tool_start",
                        task_id=task["id"],
                        tool=task["tool"],
                    )
                    coros.append(self._run_one_task(task, ws, obs))

                results = await asyncio.gather(*coros, return_exceptions=True)
                for task, result in zip(runnable, results):
                    in_flight.discard(task["id"])
                    if isinstance(result, BaseException):
                        logger.error("[orch] task %s failed: %s", task["id"], result)
                        ws.write_outbox(task["tool"], f"[Error: {result}]")
                        ws.write_context(task["tool"], f"Tool failed: {result}")
                    ws.mark_done(task["id"])
            else:
                await asyncio.sleep(0.05)

    # ── Single task execution (v2.0 — contract-enforced) ─────────────────────

    async def _run_one_task(
        self,
        task: dict,
        ws: WorkspaceManager,
        obs,
    ) -> None:
        """
        Execute one tool with contract enforcement.

        Execution path (v2.0):
          1. Look up the tool's ToolContract in the registry.
          2. Validate task["input"] against the contract schema.
             HARD REJECT (ContractViolationError) on any mismatch.
          3a. If the tool has a full Phase 3 contract: contract.execute(payload).
          3b. Otherwise: legacy dispatch(intent, json.dumps(payload)).
          4. Write result to outbox and promote to CONTEXT.md.

        No fallback. No NL interpretation. No guessing.
        """
        tool_name = task["tool"]
        payload: Dict[str, Any] = task["input"]
        t0 = time.monotonic()

        # ── Step 1 & 2: Contract validation ───────────────────────────────────
        if not ToolRegistry.exists(tool_name):
            # No contract registered — this should not happen after T2 ships.
            # Treat as a hard reject to prevent unvalidated execution.
            err = f"[{tool_name}] no contract registered. Register a ToolContract before dispatching."
            logger.error("[orch] %s", err)
            ws.write_outbox(tool_name, f"[ContractError] {err}")
            ws.write_context(tool_name, f"Schema error: {err}")
            obs.emit("workspace_tool_error", task_id=task["id"], tool=tool_name, error=err[:80])
            return

        contract_cls = ToolRegistry.get(tool_name)

        # Hard reject — no fallback if schema is violated
        try:
            contract_cls.validate_or_raise(payload)
        except ContractViolationError as exc:
            logger.error("[orch] HARD REJECT task %s: %s", task["id"], exc)
            rejection = (
                f"[ContractViolation] {exc}\n"
                f"Payload received: {json.dumps(payload, ensure_ascii=False)}\n"
                f"Expected schema: {{\n"
                + "".join(f'  "{k}": {v.__name__}\n' for k, v in contract_cls.schema.items())
                + "}"
            )
            ws.write_outbox(tool_name, rejection)
            ws.write_context(tool_name, rejection[:_MAX_SECTION_CHARS])
            obs.emit(
                "workspace_tool_contract_violation",
                task_id=task["id"],
                tool=tool_name,
                error=str(exc)[:120],
            )
            return

        # ── Step 3: Execute via contract ──────────────────────────────────────
        try:
            result: Optional[ToolResult] = await contract_cls().execute(payload)
            latency = round((time.monotonic() - t0) * 1000)

            if result and getattr(result, "requires_confirmation", False):
                ws.write_outbox(tool_name, result.content)
                ws.write_context(tool_name, result.content[:_MAX_SECTION_CHARS])
                # Store the pending payload on the workspace so the engine can
                # persist it in _pending_writes and resume on the next "yes" turn.
                meta = result.metadata or {}
                ws.pending_confirmation = {
                    "path": meta.get("pending_path", payload.get("path", "")),
                    "content": meta.get("pending_content", payload.get("content", "")),
                    "filename": meta.get("filename", ""),
                }
                obs.emit("workspace_tool_confirmation_required", task_id=task["id"], tool=tool_name)
                logger.info(
                    "[orch] task %s [%s] requires confirmation",
                    task["id"],
                    tool_name,
                )
                return

            content = result.content if result else "[no result]"
            ws.write_outbox(tool_name, content)
            ws.write_context(tool_name, content[:_MAX_SECTION_CHARS])

            obs.emit(
                "workspace_tool_done",
                task_id=task["id"],
                tool=tool_name,
                latency_ms=latency,
                chars=len(content),
            )
            logger.info(
                "[orch] task %s [%s] done in %dms (%d chars)",
                task["id"],
                tool_name,
                latency,
                len(content),
            )

        except ContractViolationError:
            raise  # already handled above — should not re-enter here
        except Exception as exc:
            ws.write_outbox(tool_name, f"[Error: {exc}]")
            ws.write_context(tool_name, f"Tool error: {exc}")
            obs.emit("workspace_tool_error", task_id=task["id"], tool=tool_name, error=str(exc)[:80])
            raise

    # ── Synthesis ─────────────────────────────────────────────────────────────

    async def _synthesise(
        self,
        message: str,
        ws: WorkspaceManager,
        obs,
        skip_context: bool = False,
        adapter=None,
    ) -> AsyncIterator[StreamChunk]:
        obs.emit("workspace_synthesising")

        context_block = ""
        if not skip_context:
            ctx = ws.read_context()
            if ctx.strip():
                trimmed = _trim_context(ctx, max_chars=_MAX_CONTEXT_TOKENS * 4)
                context_block = f"\n\nTool results:\n{trimmed}"

        messages = [
            {"role": "system", "content": _SYNTHESIS_SYSTEM + context_block},
            {"role": "user", "content": message},
        ]

        active_adapter = adapter or self._adapter
        async for chunk in active_adapter.chat(messages):
            if chunk.error:
                yield StreamChunk(text="", done=True, error=chunk.error)
                return
            yield StreamChunk(text=chunk.text, done=chunk.done)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _trim_context(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    lines = text.splitlines(keepends=True)
    while len("".join(lines)) > max_chars and lines:
        lines.pop(0)
    return f"[... earlier context trimmed ...]\n{''.join(lines)}"


def _should_use_orchestrator(message: str, intent: Intent) -> bool:
    """
    Route decision: orchestrator vs agent loop / direct-dispatch + chat path.

    CHAT → direct stream (handled in engine.py fast-path, never reaches here).
    AGENT_INTENTS (CODE_EXEC, FILE_WRITE, MEMORY_OP, SHELL) → agent loop, NOT orchestrator.
      The orchestrator uses adapter.chat() for its planner step which cannot produce
      valid tool-call JSON on small models; the dedicated AgentLoop uses
      chat_with_tools() which is what Ollama natively supports for function calling.
    SHELL → agent loop (moved from orchestrator to prevent fabrication).
      The orchestrator's Plan→Dispatch→Synthesize pipeline was causing the
      synthesis LLM to fabricate shell results: when the planner fails (common
      with small models), the synthesiser runs with skip_context=True and
      generates answers from training data alone. The agent loop's native tool
      calling is more reliable — the model calls the shell tool directly and
      receives real output as a proper tool message.
    SYSINFO, WEB_SEARCH, FILE_TASK → direct dispatch in engine.py.
    """
    from core.agent.constants import AGENT_INTENTS

    return intent not in {Intent.CHAT} and intent not in AGENT_INTENTS
