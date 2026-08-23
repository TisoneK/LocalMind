"""
tools/contracts/schemas.py — Input schemas for all LocalMind tools.

One schema dict per tool. Each schema defines the REQUIRED fields that the
orchestrator's planner must emit. Optional / action-specific fields are
documented per-tool and validated inside execute().

Schema format:
    {field_name: expected_python_type, ...}

Only required fields appear here — this keeps validate() O(n) and avoids
the need for optional-field logic in the base class.

Migration status (Phase 3 progress):
    ✅ shell       — full ToolContract + typed execute() (T5)
    🔲 sysinfo     — schema registered, execute() delegates to legacy fn
    🔲 web_search  — schema registered, execute() delegates to legacy fn
    🔲 file_task   — schema registered, execute() delegates to legacy fn
    ✅ file_write  — bypasses legacy bridge; calls _do_write() directly
    ✅ edit_file   — bypasses legacy bridge; calls _edit_from_payload() directly (v7)
    ✅ code_exec   — full ToolContract; execute() calls the sandboxed runner
                     (tools.code_executor.runner.run_code) directly (Session 107).
                     The legacy bridge was BROKEN for code_exec: it serialised
                     the payload to JSON and dispatched to the string-based
                     legacy tool, whose pre-dispatch validator demands a
                     ```python fence — a clean planner payload has no fence,
                     so execution was silently rejected with success=True.
    🔲 memory_op   — schema registered, execute() delegates to legacy fn

When a tool moves to ✅, replace its LegacyBridgeContract subclass with a
full ToolContract and remove the legacy fn call from execute().
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from core.models import Intent, RiskLevel, ToolResult
from tools.contracts.base import ToolContract, ToolRegistry

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Canonical schemas
# One source of truth — used by validate() AND shown in planner prompt so the
# LLM knows exactly what fields to emit.
# ─────────────────────────────────────────────────────────────────────────────

TOOL_SCHEMAS: Dict[str, Dict[str, type]] = {
    # ── sysinfo ───────────────────────────────────────────────────────────────
    # goal: what system information to retrieve (RAM, CPU, OS, battery, etc.)
    "sysinfo": {
        "goal": str,
    },
    # ── web_search ────────────────────────────────────────────────────────────
    # query: the exact search string — not a goal sentence, not NL instructions.
    # The planner must emit a clean query, not "search for X".
    "web_search": {
        "query": str,
    },
    # ── file_task ─────────────────────────────────────────────────────────────
    # path: absolute or home-relative path to a single FILE to read.
    #       Do NOT use for directories — use shell list_files for folder listings.
    # goal: what to do with the file (read, summarise, count lines, extract tables…).
    "file_task": {
        "path": str,
        "goal": str,
    },
    # ── file_write ────────────────────────────────────────────────────────────
    # path: destination path (absolute or ~/…). Defaults to ~/LocalMind/.
    # content: the exact text/code to write. No fences, no NL wrappers.
    "file_write": {
        "path": str,
        "content": str,
    },
    # ── edit_file ─────────────────────────────────────────────────────────────
    # path: file path to edit (absolute or ~/…).
    # action: one of "replace", "regex_replace", "insert", "delete", "append", "prepend".
    # Additional action-specific fields (search, replace, insert_text, line,
    # start_line, end_line, pattern, all) are validated inside EditFileContract.execute().
    "edit_file": {
        "path": str,
        "action": str,
    },
    # ── code_exec ─────────────────────────────────────────────────────────────
    # code: the code to execute — verbatim, no fences.
    # language: "python" | "javascript" | "bash" (determines the runner).
    # NOTE: language is NOT in the required schema — small models omit it.
    # CodeExecContract.execute() infers "python" as the default.
    "code_exec": {
        "code": str,
    },
    # ── shell ─────────────────────────────────────────────────────────────────
    # action: one of the canonical action keys (see ShellContract.ACTIONS).
    # Additional action-specific fields are validated inside ShellContract.execute().
    # The planner MUST emit the action key — no NL phrases.
    #
    # Canonical actions and their additional required fields:
    #   list_files   → path: str
    #   find_files   → path: str, file_type: str
    #   run_command  → command: str
    #   open_app     → name: str
    #   open_file    → path: str
    #   open_website → url: str
    #   check_disk   → (no additional fields)
    #   check_internet → (no additional fields)
    #   get_ip       → (no additional fields)
    #   get_sysinfo  → (no additional fields)
    "shell": {
        "action": str,
    },
    # ── memory_op ─────────────────────────────────────────────────────────────
    # operation: "store" | "retrieve" | "delete"
    # content:   for store → the text to remember.
    #            for retrieve → the query to search by.
    #            for delete → the fact/key to remove.
    "memory_op": {
        "operation": str,
        "content": str,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Legacy-bridge base class
# Used by tools not yet in Phase 3.  execute() serialises the payload to JSON
# and passes it to the existing string-based dispatch function.
# When a tool is fully migrated, delete its LegacyBridgeContract and replace
# with a proper ToolContract.
# ─────────────────────────────────────────────────────────────────────────────


class _LegacyBridgeContract(ToolContract):
    """
    Stub contract for tools pending Phase 3 migration.

    Provides schema validation (T3 enforcement) while keeping the existing
    string-based tool function alive (no big-bang rewrite required).

    execute() serialises the validated payload to a JSON string and forwards
    it to the legacy dispatch() function.  The legacy tool receives a compact
    JSON string instead of a natural-language message — better than before,
    though not yet fully typed.

    Subclasses MUST set:
        name   — tool registry key
        schema — inherited from TOOL_SCHEMAS
        _intent — the Intent enum value for this tool
    """

    _intent: Intent  # set by each subclass

    async def execute(self, payload: Dict[str, Any]) -> ToolResult:
        # Import here to avoid circular imports at module load time.
        from tools import dispatch  # noqa: PLC0415

        # Serialise the validated typed dict → compact JSON string.
        # The legacy tool receives structured data even if it can't use it fully.
        message = json.dumps(payload, ensure_ascii=False)
        try:
            result = await dispatch(self._intent, message)
            if result is None:
                return ToolResult(
                    content=f"[{self.name}] legacy dispatch returned None",
                    risk=RiskLevel.LOW,
                    source=self.name,
                    success=False,
                )
            return result
        except Exception as exc:
            logger.error("[contracts] legacy bridge error for %s: %s", self.name, exc)
            return ToolResult(
                content=f"[{self.name}] execution error: {exc}",
                risk=RiskLevel.HIGH,
                source=self.name,
                success=False,
                error_type="internal_error",
                error_message=str(exc),
            )


# ─────────────────────────────────────────────────────────────────────────────
# Stub contracts — Phase 3 migration queue
# ─────────────────────────────────────────────────────────────────────────────


class SysinfoContract(_LegacyBridgeContract):
    name = "sysinfo"
    schema = TOOL_SCHEMAS["sysinfo"]
    _intent = Intent.SYSINFO


class WebSearchContract(_LegacyBridgeContract):
    name = "web_search"
    schema = TOOL_SCHEMAS["web_search"]
    _intent = Intent.WEB_SEARCH


class FileTaskContract(_LegacyBridgeContract):
    name = "file_task"
    schema = TOOL_SCHEMAS["file_task"]
    _intent = Intent.FILE_TASK


class FileWriteContract(_LegacyBridgeContract):
    name = "file_write"
    schema = TOOL_SCHEMAS["file_write"]
    _intent = Intent.FILE_WRITE

    async def execute(self, payload: Dict[str, Any]) -> "ToolResult":
        """
        Bypass the legacy bridge entirely.

        The legacy write_file(message: str) expects a natural-language string
        containing fenced code blocks and NL path hints.  When called via
        _LegacyBridgeContract.execute(), it receives a compact JSON string
        (e.g. '{"path": "C:\\\\...\\\\hello.py", "content": "print(...)"}'),
        finds no code fences, and writes that raw JSON as the file content —
        which is wrong.

        Fix: resolve the path and call _do_write() directly with the typed
        fields from the validated payload.  This is always safe because
        validate() has already enforced that `path` and `content` are present
        and are strings.
        """
        import os
        import time as _time
        from pathlib import Path

        from core.config import settings
        from tools.file_writer import (
            PathUnresolvableError,
            _do_write,
            _is_document,
            _normalize_write_payload,
            _timestamped_name,
            resolve_write_path,
        )
        # RiskLevel imported at module level — no inner re-import

        # Session 376: normalize free-tier aliases (file_path → path,
        # text/body/code → content) before reading the fields below.
        payload = _normalize_write_payload(payload)

        # ── Path resolution ───────────────────────────────────────────────────
        raw_path: str = payload.get("path", "").strip()
        content: str = payload.get("content", "")

        # Determine if this is a no-path (scratch-only) write
        is_scratch_only = not raw_path or raw_path.startswith("~/LocalMind")

        if is_scratch_only:
            # No user destination — write to scratch and stay there.
            # B-2026-08-23-17 follow-up: default scratch = session workspace
            # when a session is active (mirrors tools/file_writer.py).
            filename = Path(raw_path).name if raw_path else f"output_{int(_time.time())}.txt"
            home = Path(os.path.expandvars(settings.localmind_home)).expanduser().resolve()
            from tools.file_writer import _default_scratch

            scratch_path = _default_scratch(home, filename)
            if settings.localmind_require_write_permission:
                return ToolResult(
                    content=(
                        f"I want to write **{filename}** to:\n`{scratch_path}`\n\n"
                        "Reply **yes** to confirm or specify a different path."
                    ),
                    risk=RiskLevel.LOW,
                    source="file_writer",
                    metadata={
                        "requires_permission": True,
                        "pending_path": str(scratch_path),
                        "pending_content": content,
                        "filename": filename,
                        "final_dest": "",
                        "user_named": False,
                    },
                    requires_confirmation=True,
                )
            return await _do_write(scratch_path, content)

        # ── Resolve user's final destination ─────────────────────────────────
        try:
            final_dest = resolve_write_path(raw_path)
        except PathUnresolvableError:
            # Instead of asking the user, resolve the path against home
            # and auto-create the directory.  This ensures file_write
            # always writes to the user's requested location.
            logger.warning(
                "[contracts] PathUnresolvableError for %r — resolving against home instead",
                raw_path,
            )
            # Try to resolve: strip drive letter if present, then anchor to home
            from tools.file_writer import _cross_os_parts

            parts = _cross_os_parts(raw_path)
            # Filter out Windows drive letter (e.g. "C:")
            filtered = [p for p in parts if not (len(p) == 2 and p[1] == ":")]
            if filtered:
                filename_from_path = ""
                last = filtered[-1]
                if "." in last and last.rsplit(".", 1)[-1].lower() in (
                    "py",
                    "js",
                    "ts",
                    "txt",
                    "md",
                    "csv",
                    "json",
                    "html",
                    "css",
                    "sh",
                    "yaml",
                    "yml",
                    "toml",
                    "sql",
                    "rs",
                    "go",
                ):
                    filename_from_path = last
                    filtered = filtered[:-1]
                if filtered:
                    final_dest = Path.home().joinpath(*filtered)
                    if filename_from_path:
                        final_dest = final_dest / filename_from_path
                    else:
                        final_dest = final_dest / Path(raw_path).name
                else:
                    final_dest = Path.home() / Path(raw_path).name
            else:
                final_dest = Path.home() / Path(raw_path).name

            # Ensure the parent directory exists
            final_dest.parent.mkdir(parents=True, exist_ok=True)
            logger.info("[contracts] resolved unresolvable path to: %s", final_dest)

        # Always write to scratch first, then copy back. B-2026-08-23-17
        # follow-up: the scratch write lands in the session's workspace folder
        # when a session is active (artifacts stay with the session and are
        # deleted with it); without a session the historic ~/LocalMind/
        # scratch is used. This mirrors tools/file_writer.py's write_file.
        from tools.file_writer import _default_scratch

        filename = final_dest.name
        home = Path(os.path.expandvars(settings.localmind_home)).expanduser().resolve()
        scratch_path = _default_scratch(home, filename)

        # user_named: planner supplied a full filename that differs from a
        # timestamped variant — treat as explicit override, skip rename.
        user_named = bool(final_dest.suffix and final_dest.name == filename)

        # ── Permission gate ───────────────────────────────────────────────────
        if settings.localmind_require_write_permission:
            if _is_document(filename) and not user_named:
                display_name = _timestamped_name(filename)
            else:
                display_name = filename
            display_dest = str(final_dest.parent / display_name)
            return ToolResult(
                content=(
                    f"I want to write **{display_name}** to:\n`{display_dest}`\n\n"
                    "Reply **yes** to confirm or specify a different path."
                ),
                risk=RiskLevel.LOW,
                source="file_writer",
                metadata={
                    "requires_permission": True,
                    "pending_path": display_dest,
                    "pending_content": content,
                    "filename": filename,
                    "final_dest": str(final_dest),
                    "user_named": user_named,
                },
                requires_confirmation=True,
            )

        return await _do_write(scratch_path, content, final_dest=final_dest, user_named=user_named)


class EditFileContract(ToolContract):
    """
    Contract for the edit_file tool — in-place file editing.

    Bypasses the legacy bridge entirely. Calls _edit_from_payload() directly
    with the validated typed payload.

    Required fields:
      - path:   the file to edit
      - action: one of "replace", "regex_replace", "insert", "delete", "append", "prepend"

    Action-specific fields (validated inside execute()):
      - replace:       search, replace, all (optional)
      - regex_replace: pattern, replace, all (optional)
      - insert:        insert_text, line
      - delete:        start_line, end_line
      - append:        insert_text
      - prepend:       insert_text
    """

    name = "edit_file"
    schema = TOOL_SCHEMAS["edit_file"]

    async def execute(self, payload: Dict[str, Any]) -> ToolResult:
        """
        Execute the edit_file tool with a validated typed dict payload.

        Delegates to tools.edit_file._edit_from_payload() which handles
        all the heavy lifting: path resolution, backup creation, edit
        application, diff generation, and error handling.
        """
        # Session 376: normalize free-tier model aliases (old_pattern/new_string,
        # content-only → rewrite) BEFORE the action validation below — a
        # content-only payload would otherwise be rejected here without ever
        # reaching prepare_edit's normalizer.
        from tools.edit_file import _edit_from_payload, _normalize_edit_payload

        payload = _normalize_edit_payload(payload)

        # Validate action value
        action = payload.get("action", "")
        valid_actions = {"replace", "regex_replace", "insert", "delete", "append", "prepend", "rewrite"}
        if action not in valid_actions:
            return ToolResult(
                content=f"Invalid action '{action}'. Valid: {', '.join(sorted(valid_actions))}",
                risk=RiskLevel.LOW,
                source="edit_file",
                success=False,
                error_type="validation_error",
                error_message=f"Invalid action '{action}'",
            )

        # Delegate to the edit_file module's payload handler
        return await _edit_from_payload(payload)


class CodeExecContract(ToolContract):
    """
    Contract for the code_exec tool — sandboxed code execution.

    Bypasses the legacy bridge entirely. Calls the sandboxed runner
    (tools.code_executor.runner.run_code) directly with the validated typed
    payload. This fixes a real breakage: the legacy bridge serialised the
    payload to JSON and dispatched to the string-based legacy tool, whose
    pre-dispatch validator demands a ```python fence — a clean planner
    payload has no fence, so code was silently NEVER executed (the caller
    got a "wrap your code in a fence" error while success stayed True).

    Required fields:
      - code: the code to execute — verbatim, no fences.
    Optional:
      - language: "python" | "javascript" — defaults to "python" (small
        models often omit it; python covers >95% of real usage).
    """

    name = "code_exec"
    schema = TOOL_SCHEMAS["code_exec"]

    async def execute(self, payload: Dict[str, Any]) -> ToolResult:
        code = payload.get("code", "")
        if not code or not code.strip():
            return ToolResult(
                content="No code provided in the payload ('code' field is empty).",
                risk=RiskLevel.LOW,
                source="code_exec",
                success=False,
                error_type="invalid_input",
                error_message="code_exec payload missing 'code'.",
            )
        language = payload.get("language") or "python"
        # Import here to avoid a circular import at module load time.
        from tools.code_executor.runner import run_code  # noqa: PLC0415

        return await run_code(code, language)


class MemoryOpContract(_LegacyBridgeContract):
    name = "memory_op"
    schema = TOOL_SCHEMAS["memory_op"]
    _intent = Intent.MEMORY_OP


# ShellContract lives in tools/shell.py (T5 — full Phase 3 implementation).
# It is registered at import time by tools/shell.py, not here.


# ─────────────────────────────────────────────────────────────────────────────
# Auto-register all contracts in this file
# Call register_all_stub_contracts() from tools/contracts/__init__.py
# ─────────────────────────────────────────────────────────────────────────────

_STUB_CONTRACTS = [
    SysinfoContract,
    WebSearchContract,
    FileTaskContract,
    FileWriteContract,
    EditFileContract,
    CodeExecContract,
    MemoryOpContract,
]


def register_all_stub_contracts() -> None:
    """
    Register every stub contract with the ToolRegistry.

    Called once at application startup (from tools/contracts/__init__.py).
    ShellContract registers itself when tools/shell.py is imported.
    """
    for contract_cls in _STUB_CONTRACTS:
        if not ToolRegistry.exists(contract_cls.name):
            ToolRegistry.register(contract_cls)
            logger.debug("[contracts] registered stub: %s", contract_cls.name)
