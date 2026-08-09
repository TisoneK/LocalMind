"""
Code Executor — tool entry point.

Detects language, runs in sandbox, returns formatted result.
Disabled if LOCALMIND_CODE_EXEC_ENABLED=false in .env.
"""

from __future__ import annotations

import logging

from core.config import settings
from core.models import RiskLevel
from tools.base import ToolResult
from tools.code_executor.detector import detect
from tools.code_executor.sandbox import run_javascript, run_python

logger = logging.getLogger(__name__)


async def run_code(code: str, language: str) -> ToolResult:
    """
    Execute a raw code string in the sandboxed runner (typed contract API).

    Unlike run(), this takes the already-extracted code plus an explicit
    language — the caller (CodeExecContract) holds a typed payload, so no
    detector heuristics are applied. Mirrors the legacy code_exec tool's
    ToolResult contract (source="code_exec", risk on non-zero exit) so the
    orchestrator/outbox path stays uniform.

    Args:
        code: The code to execute — verbatim, no fences.
        language: "python" | "javascript" (or common aliases).

    Returns:
        ToolResult with the sandboxed execution output. Mirrors legacy
        code_exec.py semantics: a non-zero exit is NOT success=False — the
        code ran, so success stays True and the failure is signaled via
        risk=MEDIUM plus the captured error text in content.
    """
    if not settings.localmind_code_exec_enabled:
        return ToolResult(
            content="Code execution is disabled. Set LOCALMIND_CODE_EXEC_ENABLED=true to enable.",
            risk=RiskLevel.LOW,
            source="code_exec",
            success=False,
            error_type="permission",
            error_message="Code execution disabled via LOCALMIND_CODE_EXEC_ENABLED.",
        )

    # language is an OPTIONAL schema field, so it is not type-checked by the
    # contract's structural validator — a rogue payload could carry a non-string.
    lang = (language or "python").strip().lower() if isinstance(language, str) else "python"
    if lang in ("javascript", "js", "node", "nodejs"):
        result = await run_javascript(code)
    elif lang in ("python", "py"):
        result = await run_python(code)
    else:
        return ToolResult(
            content=f"Unsupported language '{language}'. Supported: python, javascript.",
            risk=RiskLevel.LOW,
            source="code_exec",
            success=False,
            error_type="invalid_input",
            error_message=f"Unsupported code_exec language '{language}'.",
        )

    return ToolResult(
        content=result.summary(),
        risk=RiskLevel.MEDIUM if (result.exit_code != 0 or result.timed_out) else RiskLevel.LOW,
        source="code_exec",
        metadata={
            "language": lang,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
        },
    )


async def run(input_data: dict, context: dict) -> ToolResult:
    """
    Execute code extracted from the user message.

    Args:
        input_data: Dict with 'message' or 'query' key.
        context: Engine context dict.

    Returns:
        ToolResult with execution output.
    """
    # The disabled-flag check + result construction live in run_code() — this
    # entry point only adds the message→code extraction on top of it.
    message = input_data.get("message", input_data.get("query", ""))
    detected = detect(message)

    if not detected:
        return ToolResult(
            content="No executable code found in the message. Please include a code block.",
            risk=RiskLevel.LOW,
            source="code_executor",
        )

    logger.info(f"Executing {detected.language} code ({len(detected.code)} chars)")
    return await run_code(detected.code, detected.language)
