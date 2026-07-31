"""
Diagnostics tool — structured failure analysis.

Exposes 4 operations for understanding what went wrong:
  - inspect_error    — analyze an error message string
  - analyze_traceback — parse a Python traceback into structured output
  - inspect_logs      — read and analyze log files for error patterns
  - inspect_test_failure — parse pytest/unittest failure output

Unlike raw shell output, these operations extract structured information:
file paths, line numbers, error types, stack frames, and probable causes.
This gives the model semantic access to failure data instead of forcing
it to regex-parse unstructured terminal output.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool

logger = logging.getLogger(__name__)

# ── Traceback parsing patterns ────────────────────────────────────────

_TRACEBACK_LINE_RE = re.compile(
    r'^\s*File\s+"([^"]+)",\s+line\s+(\d+),\s+in\s+(\S+)'
)

_ERROR_TYPE_RE = re.compile(
    r"^(\w+(?:\.\w+)*(?:Error|Exception|Warning|Failure|Interrupt|Exit|Signal))\b"
)

# Common error message patterns for severity classification
_CRITICAL_PATTERNS = re.compile(
    r"(cannot|unable|failed to|permission denied|access denied|out of memory"
    r"|disk full|connection refused|timeout)",
    re.IGNORECASE,
)


def _classify_severity(error_type: str, message: str) -> str:
    """Classify error severity: critical, error, or warning."""
    error_lower = error_type.lower()
    if "warning" in error_lower or "deprecation" in error_lower:
        return "warning"
    if _CRITICAL_PATTERNS.search(message):
        return "critical"
    return "error"


def _parse_frames_and_error(text: str) -> tuple[list[dict], str, str]:
    """Shared parser: extract traceback frames, error type, and message."""
    lines = text.strip().split("\n")
    frames: list[dict] = []
    error_type = "Unknown"
    error_message = ""

    if not lines or not lines[0].strip():
        return frames, error_type, error_message

    for line in lines:
        stripped = line.strip()

        # Skip header
        if stripped == "Traceback (most recent call last):":
            continue

        # Match frame lines
        tb_match = _TRACEBACK_LINE_RE.search(line)
        if tb_match:
            frames.append({
                "file": tb_match.group(1),
                "line": int(tb_match.group(2)),
                "function": tb_match.group(3),
            })
            continue

        # Match error type (after frames or if no frames)
        err_match = _ERROR_TYPE_RE.match(stripped)
        if err_match:
            error_type = err_match.group(1)
            error_message = stripped[len(error_type):].strip(": ")
            continue

        # Additional error detail lines (multi-line messages)
        if error_type != "Unknown" and stripped and not stripped.startswith("^"):
            error_message += " " + stripped if error_message else stripped

    return frames, error_type, error_message


# ── inspect_error ─────────────────────────────────────────────────────


def _inspect_error(error_text: str) -> str:
    """Analyze an error message string and produce structured output."""
    if not error_text.strip():
        return "No error text provided."

    frames, error_type, error_message = _parse_frames_and_error(error_text)
    severity = _classify_severity(error_type, error_message)

    parts = [
        "## Error Analysis",
        "",
        f"**Type:** {error_type}",
        f"**Severity:** {severity}",
        f"**Message:** {error_message}",
    ]

    if frames:
        parts.append("")
        parts.append(f"### Stack Trace ({len(frames)} frames)")
        for i, frame in enumerate(reversed(frames), 1):
            parts.append(
                f"  {i}. {frame['function']}() in "
                f"`{frame['file']}` line {frame['line']}"
            )

        deepest = frames[-1]
        if deepest != frames[0]:
            parts.append("")
            parts.append(
                f"**Likely origin:** {deepest['function']}() in "
                f"`{deepest['file']}` line {deepest['line']}"
            )

    return "\n".join(parts)


# ── analyze_traceback ─────────────────────────────────────────────────


def _analyze_traceback(traceback_text: str) -> str:
    """Parse a Python traceback into structured output."""
    if not traceback_text.strip():
        return "No traceback text provided."

    frames, error_type, error_message = _parse_frames_and_error(traceback_text)
    severity = _classify_severity(error_type, error_message)

    parts = [
        "## Traceback Analysis",
        "",
        f"**Error:** {error_type}",
        f"**Severity:** {severity}",
        f"**Message:** {error_message}",
        "",
        f"### Call Stack ({len(frames)} frames, deepest first)",
    ]

    for i, frame in enumerate(frames, 1):
        parts.append(
            f"  {i}. `{frame['function']}()` — "
            f"{frame['file']}:{frame['line']}"
        )

    if frames:
        deepest = frames[-1]
        parts.append("")
        parts.append("### Immediate Cause")
        parts.append(f"Error occurred in `{deepest['function']}()` at:")
        parts.append(f"  **File:** `{deepest['file']}`")
        parts.append(f"  **Line:** {deepest['line']}")
        parts.append("")
        parts.append(
            f"**Suggested action:** Read `{deepest['file']}` around line "
            f"{deepest['line']} to understand the failing code."
        )

    return "\n".join(parts)


# ── inspect_logs ──────────────────────────────────────────────────────


def _inspect_logs(log_path_or_text: str) -> str:
    """Read and analyze log files for error patterns."""
    content = log_path_or_text.strip()
    if not content:
        return "No log content or path provided."

    if "\n" not in content and len(content) < 500:
        path = Path(content).expanduser()
        try:
            if path.is_file():
                with open(path, "r", errors="replace") as f:
                    all_lines = f.readlines()
                content = "".join(all_lines[-200:])
        except (OSError, PermissionError) as exc:
            return f"Could not read log file `{path}`: {exc}"

    lines = content.split("\n")
    error_lines: list[str] = []
    warning_lines: list[str] = []
    total_errors = 0
    total_warnings = 0

    for line in lines:
        lower = line.lower()
        if any(
            word in lower
            for word in ("error", "critical", "fatal", "fail", "exception", "traceback")
        ):
            error_lines.append(line)
            total_errors += 1
        elif "warning" in lower or "warn" in lower:
            warning_lines.append(line)
            total_warnings += 1

    parts = [
        "## Log Analysis",
        "",
        f"**Total lines:** {len(lines)}",
        f"**Errors/Critical:** {total_errors}",
        f"**Warnings:** {total_warnings}",
        "",
    ]

    if error_lines:
        parts.append(f"### Errors ({total_errors})")
        shown = 0
        for line in error_lines:
            if shown >= 15:
                parts.append(f"  ... and {total_errors - shown} more")
                break
            parts.append(f"  {line.strip()[:200]}")
            shown += 1

    if warning_lines:
        parts.append("")
        parts.append(f"### Warnings ({total_warnings})")
        for line in warning_lines[:5]:
            parts.append(f"  {line.strip()[:200]}")
        if total_warnings > 5:
            parts.append(f"  ... and {total_warnings - 5} more")

    if not error_lines and not warning_lines:
        parts.append("No errors or warnings detected in the log content.")

    return "\n".join(parts)


# ── inspect_test_failure ──────────────────────────────────────────────


def _inspect_test_failure(failure_text: str) -> str:
    """Parse pytest/unittest failure output into structured format."""
    text = failure_text.strip()
    if not text:
        return "No test failure text provided."

    test_name = "Unknown"
    test_name_match = re.search(r"(test_\w+)", text)
    if test_name_match:
        test_name = test_name_match.group(1)

    assertion_type = "Unknown"
    assertion_match = re.search(r"(AssertionError|assert\s+\w+)", text)
    if assertion_match:
        assertion_type = assertion_match.group(1)

    source_file = "Unknown"
    source_line = "Unknown"
    tb_match = _TRACEBACK_LINE_RE.search(text)
    if tb_match:
        source_file = tb_match.group(1)
        source_line = tb_match.group(2)

    expected_val = None
    actual_val = None
    eq_match = re.search(r"(?:assert\s+)(.+?)\s*==\s*(.+)", text)
    if eq_match:
        expected_val = eq_match.group(2).strip()
        actual_val = eq_match.group(1).strip()

    has_diff = ">" in text and "<" in text
    diff_lines: list[str] = []
    if has_diff:
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("E") and ("+" in stripped or "-" in stripped):
                diff_lines.append(stripped)

    parts = [
        "## Test Failure Analysis",
        "",
        f"**Test:** {test_name}",
        f"**Assertion:** {assertion_type}",
        f"**Location:** {source_file}:{source_line}",
    ]

    if expected_val is not None and actual_val is not None:
        parts.extend([
            f"**Expected:** {expected_val}",
            f"**Actual:** {actual_val}",
        ])

    if diff_lines:
        parts.append("")
        parts.append(f"### Diff ({len(diff_lines)} lines)")
        for dl in diff_lines[:10]:
            parts.append(f"  {dl}")

    parts.append("")
    if source_file != "Unknown":
        parts.append(
            f"**Suggested action:** Read `{source_file}` around "
            f"line {source_line} to find the failing assertion."
        )

    return "\n".join(parts)


# ── Dispatcher ────────────────────────────────────────────────────────


async def diagnostics(message: str) -> ToolResult:
    """Dispatch to the correct diagnostics operation."""
    try:
        args = json.loads(message)
        operation = args.get("operation", "").strip()
        text = args.get("text", "").strip()
        log_path = args.get("path", "").strip()
    except json.JSONDecodeError:
        return ToolResult(
            content=_inspect_error(message),
            risk=RiskLevel.LOW,
            source="diagnostics",
            success=True,
        )

    if not operation:
        return ToolResult(
            content=(
                "ERROR: diagnostics tool requires an 'operation' parameter. "
                "Valid operations: inspect_error, analyze_traceback, "
                "inspect_logs, inspect_test_failure."
            ),
            risk=RiskLevel.LOW,
            source="diagnostics",
            success=False,
            error_type="invalid_input",
        )

    try:
        if operation == "inspect_error":
            result = _inspect_error(text)
        elif operation == "analyze_traceback":
            result = _analyze_traceback(text)
        elif operation == "inspect_logs":
            result = _inspect_logs(log_path or text)
        elif operation == "inspect_test_failure":
            result = _inspect_test_failure(text)
        else:
            return ToolResult(
                content=(
                    f"ERROR: unknown operation {operation!r}. "
                    "Valid operations: inspect_error, analyze_traceback, "
                    "inspect_logs, inspect_test_failure."
                ),
                risk=RiskLevel.LOW,
                source="diagnostics",
                success=False,
                error_type="invalid_input",
            )

        return ToolResult(
            content=result,
            risk=RiskLevel.LOW,
            source="diagnostics",
            success=True,
        )
    except Exception as exc:
        return ToolResult(
            content=f"Diagnostics tool error: {exc}",
            risk=RiskLevel.LOW,
            source="diagnostics",
            success=False,
            error_type="tool_error",
        )


# ── Registration ──────────────────────────────────────────────────────

register_tool(
    Intent.DIAGNOSTICS,
    diagnostics,
    description=(
        "Analyze errors, tracebacks, logs, and test failures to provide "
        "structured diagnostic output. Use this instead of raw shell/file_task "
        "when you need to understand WHY something failed. Operations: "
        "inspect_error (analyze an error message), analyze_traceback (parse a "
        "Python traceback into stack frames and root cause), inspect_logs "
        "(scan log files for error/warning patterns), inspect_test_failure "
        "(parse pytest/unittest failure output into expected vs actual). "
        "All operations return structured output with file paths, line numbers, "
        "severity classification, and suggested actions."
    ),
    cost=0.3,
    latency_ms=200,
    parallelizable=True,
)
