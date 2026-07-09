"""
Code Execution tool — runs Python snippets in a subprocess.

Security model (honest):
- Runs in the SAME Python environment as LocalMind — full filesystem and
  network access. This is intentional for a local, trusted-user tool.
- Timeout enforced (default 30s from config) — runaway loops are killed.
- stdout/stderr captured and truncated to 4000 chars.
- NOT a sandbox. Do not expose to untrusted users without adding one
  (e.g. Docker, nsjail, or RestrictedPython).

v2 changes:
- Fix: Write code to a temp file instead of using `python -c`. On Windows,
  `python -c` with multi-line code fails because the Windows command line
  doesn't handle embedded newlines in arguments — they get passed as
  literal `\n` characters, causing SyntaxError. Writing to a temp file
  and executing `python tempfile.py` avoids this entirely.

Registered as Intent.CODE_EXEC in the tool registry.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import tempfile
import textwrap

from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool

logger = logging.getLogger(__name__)

OUTPUT_MAX = 4000
_CODE_FENCE = re.compile(r"```(?:python|py)?\s*([\s\S]+?)```", re.IGNORECASE)


def _extract_code(message: str) -> str:
    """
    Extract code from a fenced ```python block, or return the raw message
    if it looks like executable Python.

    When called from the agent loop (via dispatch), the message is raw
    Python code without fences — e.g. "import os\nprint(os.getcwd())".
    When called from the legacy path, the message may contain a fenced
    block like "```python\nprint('hello')\n```".

    We try the fenced block first (more precise), then fall back to
    treating the entire message as code if it looks like Python.
    """
    # Try fenced block first
    match = _CODE_FENCE.search(message)
    if match:
        return match.group(1).strip()

    # No fence found — check if the message looks like Python code.
    # Heuristic: if it contains common Python keywords/constructs at the
    # start of lines, treat it as code. This avoids executing random
    # natural language that the LLM might send.
    _PYTHON_INDICATORS = [
        "import ", "from ", "def ", "class ", "if ", "for ", "while ",
        "print(", "return ", "with ", "try:", "else:", "elif ",
        "#", "__", "assert ", "raise ", "lambda ", "global ",
    ]
    lines = message.strip().split("\n")
    if lines:
        first_line = lines[0].strip()
        # If the first line starts with a Python keyword or the message
        # is short enough to be code, treat it as code
        has_indicator = any(first_line.startswith(ind) for ind in _PYTHON_INDICATORS)
        # Also check if it's a simple expression (e.g., "2 + 2" or "psutil.cpu_count()")
        looks_like_expr = bool(re.match(r'^[\w\s\.\(\)\[\]\+\-\*/%=<>!,":]+$', first_line)) and len(first_line) < 200
        if has_indicator or looks_like_expr:
            return message.strip()

    return ""


async def code_exec(message: str) -> ToolResult:
    from core.config import settings

    code = _extract_code(message)
    if not code:
        return ToolResult(
            content="No executable Python code found in the message. Please provide code in a ```python``` block.",
            risk=RiskLevel.LOW,
            source="code_exec",
            success=False,
            error_type="invalid_input",
            error_message="No fenced ```python``` block found in input.",
        )

    timeout = getattr(settings, "localmind_code_exec_timeout", 30)
    enabled = getattr(settings, "localmind_code_exec_enabled", True)

    if not enabled:
        return ToolResult(
            content="Code execution is disabled. Set LOCALMIND_CODE_EXEC_ENABLED=true to enable.",
            risk=RiskLevel.LOW,
            source="code_exec",
            success=False,
            error_type="permission",
            error_message="Code execution disabled via LOCALMIND_CODE_EXEC_ENABLED.",
        )

    # Write code to a temp file and run it as a subprocess.
    # This is more reliable than `python -c` because:
    # 1. On Windows, `python -c "multi\nline\ncode"` fails — the Windows
    #    command line doesn't handle embedded newlines in arguments. They
    #    get passed as literal `\n` characters, causing SyntaxError.
    # 2. Temp files avoid shell quoting issues entirely.
    # 3. The temp file approach works identically on Windows, macOS, and Linux.
    safe_code = textwrap.dedent(code)

    # Use delete=False so the file persists until we read the output,
    # then clean up manually after execution completes.
    tmp_fd = None
    tmp_path = None
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(
            suffix=".py",
            prefix="localmind_exec_",
        )
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(safe_code)
        tmp_fd = None  # closed by os.fdopen context manager

        proc = await asyncio.create_subprocess_exec(
            sys.executable, tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return ToolResult(
                content=f"Code execution timed out after {timeout}s.",
                risk=RiskLevel.MEDIUM,
                source="code_exec",
                metadata={"exit_code": -1, "timed_out": True},
                success=False,
                error_type="timeout",
                error_message=f"Subprocess killed after {timeout}s timeout.",
            )

        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        exit_code = proc.returncode

        parts = []
        if out:
            truncated = out[:OUTPUT_MAX]
            if len(out) > OUTPUT_MAX:
                truncated += f"\n… (truncated {len(out) - OUTPUT_MAX} chars)"
            parts.append(f"**stdout:**\n```\n{truncated}\n```")
        if err:
            truncated = err[:OUTPUT_MAX]
            parts.append(f"**stderr:**\n```\n{truncated}\n```")
        if not parts:
            parts.append("*(no output)*")

        content = "\n".join(parts)
        risk = RiskLevel.MEDIUM if exit_code != 0 else RiskLevel.LOW

        return ToolResult(
            content=content,
            risk=risk,
            source="code_exec",
            metadata={"exit_code": exit_code, "lines": len(out.splitlines())},
        )

    except Exception as e:
        logger.error(f"[code_exec] unexpected error: {e}")
        return ToolResult(
            content=f"Execution failed: {e}",
            risk=RiskLevel.HIGH,
            source="code_exec",
            success=False,
            error_type="internal_error",
            error_message=str(e),
        )
    finally:
        # Clean up the temp file
        if tmp_fd is not None:
            os.close(tmp_fd)
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# Register
register_tool(
    Intent.CODE_EXEC,
    code_exec,
    description="Execute Python code snippets and return stdout/stderr output",
    cost=0.02,
    latency_ms=2000,
    parallelizable=False,  # A3: stateful subprocess — must run sequentially
)


# -- Pre-dispatch validator ----------------------------------------------------
# Registered after the tool so _CODE_FENCE is already in scope.
# This surfaces a clear user-facing message before any subprocess is spawned.

def _validate_code_exec(message: str) -> str | None:
    """Reject early if no code fence is present -- avoids a confusing tool error."""
    if not _CODE_FENCE.search(message):
        return (
            "Please wrap your code in a ```python``` block so I can run it. "
            "Example:\n```python\nprint('hello')\n```"
        )
    return None


from tools import register_validator  # noqa: E402

register_validator(Intent.CODE_EXEC, _validate_code_exec)
