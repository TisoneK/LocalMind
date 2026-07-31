"""
Process tool — long-running process management for LocalMind agents.

Phase A (Session 42): enables agents to start, monitor, and stop
long-running processes like `npm run dev`, `uvicorn`, `pytest`,
`docker compose`, etc. Without this, every process is a one-shot
shell command — the agent can't start a dev server, wait for it to
be ready, interact with it, and then stop it.

Operations:
  start   — Start a process and track it by name. Returns the PID.
  stop    — Stop a tracked process (SIGTERM, then SIGKILL on timeout).
  restart — Stop (if running) and start a process again.
  status  — List all tracked processes with their state (running/stopped).
  logs    — Read captured stdout/stderr from a tracked process.
  wait    — Block until a process finishes or timeout is reached.

Design:
  - ProcessRegistry: module-level dict of {name: ManagedProcess} that
    survives across tool calls within a session. Each ManagedProcess
    holds a Popen object, stdout/stderr buffers, start time, and state.
  - Output capture: stdout and stderr are piped and read by background
    threads into line-buffered lists (capped at _MAX_LOG_LINES).
  - Safety: start requires a name; stop is graceful (SIGTERM → SIGKILL
    after _GRACEFUL_TIMEOUT); restart checks if already running.
  - All operations are synchronous subprocess calls run in an executor
    (same pattern as git_tool.py and shell.py).

Integration:
  - Registered as Intent.PROCESS via register_tool()
  - Added to AGENT_ALLOWED_TOOLS and CODING_TOOLS
  - Added to TOOL_DEFINITIONS for model visibility
  - Wired through _extract_tool_input() in loop.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Max lines of stdout/stderr to buffer per process
_MAX_LOG_LINES = 200

# Time to wait after SIGTERM before sending SIGKILL
_GRACEFUL_TIMEOUT = 5.0

# Default wait timeout
_DEFAULT_WAIT_TIMEOUT = 30.0

# Max wait timeout to prevent deadlock
_MAX_WAIT_TIMEOUT = 300.0  # 5 minutes

# CWD context var
_session_cwd_var: ContextVar[str | None] = ContextVar("_session_cwd", default=None)


def set_session_cwd(cwd: str | None) -> None:
    """Set session CWD for process operations. Called by the Engine."""
    _session_cwd_var.set(cwd)


def _get_cwd() -> str:
    cwd = _session_cwd_var.get(None)
    if cwd and Path(cwd).is_dir():
        return cwd
    return os.getcwd()


# ── Process Registry ──────────────────────────────────────────────────────────


@dataclass
class ManagedProcess:
    """A tracked long-running process."""

    name: str
    command: str
    process: subprocess.Popen
    started_at: float = field(default_factory=time.time)
    state: str = "running"  # running, stopped, failed
    exit_code: Optional[int] = None

    # Buffered output lines (capped at _MAX_LOG_LINES)
    stdout_lines: list[str] = field(default_factory=list)
    stderr_lines: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def append_stdout(self, line: str) -> None:
        with self._lock:
            self.stdout_lines.append(line)
            if len(self.stdout_lines) > _MAX_LOG_LINES:
                self.stdout_lines = self.stdout_lines[-_MAX_LOG_LINES:]

    def append_stderr(self, line: str) -> None:
        with self._lock:
            self.stderr_lines.append(line)
            if len(self.stderr_lines) > _MAX_LOG_LINES:
                self.stderr_lines = self.stderr_lines[-_MAX_LOG_LINES:]

    def runtime_secs(self) -> float:
        return time.time() - self.started_at

    def get_logs(self) -> str:
        with self._lock:
            lines: list[str] = []
            if self.stdout_lines:
                lines.append("--- stdout ---")
                lines.extend(self.stdout_lines)
            if self.stderr_lines:
                lines.append("--- stderr ---")
                lines.extend(self.stderr_lines)
            return "\n".join(lines) if lines else "(no output yet)"


class ProcessRegistry:
    """Thread-safe registry of managed processes."""

    def __init__(self):
        self._processes: dict[str, ManagedProcess] = {}
        self._lock = threading.Lock()

    def add(self, proc: ManagedProcess) -> None:
        with self._lock:
            self._processes[proc.name] = proc

    def get(self, name: str) -> Optional[ManagedProcess]:
        with self._lock:
            return self._processes.get(name)

    def remove(self, name: str) -> Optional[ManagedProcess]:
        with self._lock:
            return self._processes.pop(name, None)

    def list_all(self) -> list[ManagedProcess]:
        with self._lock:
            return list(self._processes.values())

    def list_names(self) -> list[str]:
        with self._lock:
            return sorted(self._processes.keys())

    def reset(self) -> None:
        """Stop all processes and clear registry. For testing."""
        with self._lock:
            for proc in self._processes.values():
                try:
                    if proc.process.poll() is None:
                        proc.process.terminate()
                except Exception:
                    pass
            self._processes.clear()


# Global registry instance
_registry = ProcessRegistry()


# ── Output reader threads ─────────────────────────────────────────────────────


def _reader_thread(proc: ManagedProcess, stream_name: str) -> None:
    """Read lines from a process stream and buffer them."""
    stream = proc.process.stdout if stream_name == "stdout" else proc.process.stderr
    if stream is None:
        return
    append = proc.append_stdout if stream_name == "stdout" else proc.append_stderr
    try:
        for line in stream:
            decoded = line.decode("utf-8", errors="replace").rstrip("\n\r")
            append(decoded)
    except (ValueError, OSError):
        pass  # Stream closed


# ── Operation handlers ─────────────────────────────────────────────────────────


def _process_start(cwd: str, name: str, command: str) -> ToolResult:
    """Start a process and track it."""
    if not name.strip():
        return ToolResult(
            content="start requires a 'name' for the process.",
            risk=RiskLevel.LOW,
            source="process",
            success=False,
            error_type="missing_arg",
        )
    if not command.strip():
        return ToolResult(
            content="start requires a 'command' to run.",
            risk=RiskLevel.LOW,
            source="process",
            success=False,
            error_type="missing_arg",
        )

    existing = _registry.get(name)
    if existing is not None and existing.state == "running":
        return ToolResult(
            content=(
                f"Process '{name}' is already running (PID {existing.process.pid}, "
                f"runtime {existing.runtime_secs():.0f}s). "
                f"Use 'restart' to stop and restart, or 'stop' first."
            ),
            risk=RiskLevel.LOW,
            source="process",
            success=False,
            error_type="already_running",
        )

    # Remove any stopped/failed entry with this name
    _registry.remove(name)

    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return ToolResult(
            content=f"Command not found: {command.split()[0] if command else command}",
            risk=RiskLevel.LOW,
            source="process",
            success=False,
            error_type="command_not_found",
        )
    except OSError as exc:
        return ToolResult(
            content=f"Failed to start process: {exc}",
            risk=RiskLevel.LOW,
            source="process",
            success=False,
            error_type="os_error",
            error_message=str(exc),
        )

    managed = ManagedProcess(name=name, command=command, process=proc)
    _registry.add(managed)

    # Start output reader threads
    threading.Thread(target=_reader_thread, args=(managed, "stdout"), daemon=True).start()
    threading.Thread(target=_reader_thread, args=(managed, "stderr"), daemon=True).start()

    return ToolResult(
        content=(
            f"Started process '{name}' (PID {proc.pid}). "
            f"Use 'status' to check, 'logs {name}' to see output, "
            f"'wait {name}' to wait for completion, or 'stop {name}' to terminate."
        ),
        risk=RiskLevel.MEDIUM,
        source="process",
        metadata={"pid": proc.pid, "name": name, "command": command},
    )


def _do_stop(managed: ManagedProcess, force: bool = False) -> bool:
    """Internal stop logic. Returns True if the process was stopped."""
    proc = managed.process
    if proc.poll() is not None:
        managed.state = "stopped"
        managed.exit_code = proc.returncode
        return True

    if force:
        proc.kill()
        managed.state = "stopped"
        managed.exit_code = proc.returncode if proc.poll() is not None else -9
        return True

    proc.terminate()
    try:
        proc.wait(timeout=_GRACEFUL_TIMEOUT)
        managed.state = "stopped"
        managed.exit_code = proc.returncode
        return True
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        managed.state = "stopped"
        managed.exit_code = -9
        return True


def _process_stop(name: str, force: bool = False) -> ToolResult:
    """Stop a tracked process. Graceful (SIGTERM) by default, SIGKILL if force=True."""
    if not name.strip():
        return ToolResult(
            content="stop requires a 'name' of the process to stop.",
            risk=RiskLevel.LOW,
            source="process",
            success=False,
            error_type="missing_arg",
        )

    managed = _registry.get(name)
    if managed is None:
        names = _registry.list_names()
        return ToolResult(
            content=(
                f"No process named '{name}' is being tracked. "
                + (f"Tracked processes: {', '.join(names)}" if names else "No processes are currently tracked.")
            ),
            risk=RiskLevel.LOW,
            source="process",
            success=False,
            error_type="not_found",
        )

    if managed.state == "stopped":
        return ToolResult(
            content=f"Process '{name}' is already stopped (exit code {managed.exit_code}).",
            risk=RiskLevel.LOW,
            source="process",
        )

    if managed.process.poll() is not None:
        _do_stop(managed)
        return ToolResult(
            content=f"Process '{name}' had already exited (exit code {managed.exit_code}).",
            risk=RiskLevel.LOW,
            source="process",
        )

    _do_stop(managed, force=force)
    if force:
        return ToolResult(
            content=f"Force-killed process '{name}' (SIGKILL).",
            risk=RiskLevel.MEDIUM,
            source="process",
        )
    elif managed.exit_code == -9:
        return ToolResult(
            content=(
                f"Process '{name}' did not stop gracefully after {_GRACEFUL_TIMEOUT}s. "
                f"Force-killed (SIGKILL)."
            ),
            risk=RiskLevel.MEDIUM,
            source="process",
        )
    else:
        return ToolResult(
            content=f"Stopped process '{name}' gracefully (exit code {managed.exit_code}).",
            risk=RiskLevel.LOW,
            source="process",
        )


def _process_restart(cwd: str, name: str, command: str = "") -> ToolResult:
    """Restart a process: stop if running, then start."""
    if not name.strip():
        return ToolResult(
            content="restart requires a 'name' of the process to restart.",
            risk=RiskLevel.LOW,
            source="process",
            success=False,
            error_type="missing_arg",
        )

    managed = _registry.get(name)

    # Determine the command: explicit > stored > error
    if not command.strip():
        if managed is not None:
            command = managed.command
        else:
            return ToolResult(
                content=(
                    f"No process named '{name}' is tracked, and no command was provided. "
                    f"Provide a 'command' to start a new process with this name."
                ),
                risk=RiskLevel.LOW,
                source="process",
                success=False,
                error_type="missing_arg",
            )

    # Stop if running
    if managed is not None and managed.state == "running":
        # Use internal stop directly — bypass the ToolResult wrapper
        _do_stop(managed)
        if managed.state != "stopped":
            return ToolResult(
                content=f"Failed to stop existing process '{name}' before restart.",
                risk=RiskLevel.HIGH,
                source="process",
                success=False,
                error_type="stop_failed",
            )

    # Start
    return _process_start(cwd, name, command)


def _process_status(name: str = "") -> ToolResult:
    """Get status of all tracked processes or a specific one."""
    if name.strip():
        managed = _registry.get(name)
        if managed is None:
            return ToolResult(
                content=f"No process named '{name}' is being tracked.",
                risk=RiskLevel.LOW,
                source="process",
                success=False,
                error_type="not_found",
            )
        return _format_single_status(managed)

    all_procs = _registry.list_all()
    if not all_procs:
        return ToolResult(
            content="No processes are currently being tracked.",
            risk=RiskLevel.LOW,
            source="process",
        )

    lines = [f"Tracked processes ({len(all_procs)}):\n"]
    for proc in all_procs:
        lines.append(_format_single_line(proc))
    return ToolResult(
        content="\n".join(lines),
        risk=RiskLevel.LOW,
        source="process",
    )


def _check_completion(proc: ManagedProcess) -> None:
    """Check if a running process has exited and update its state."""
    if proc.state == "running" and proc.process.poll() is not None:
        proc.state = "stopped"
        proc.exit_code = proc.process.returncode


def _format_single_line(proc: ManagedProcess) -> str:
    """Format a single process as a one-liner. Pure formatting — no side effects."""
    _check_completion(proc)
    pid_str = str(proc.process.pid) if proc.process.pid else "?"
    runtime = proc.runtime_secs()
    return (
        f"  {proc.name:20s}  PID {pid_str:>6s}  {proc.state:>8s}  "
        f"{runtime:>6.0f}s  {proc.command[:60]}"
    )


def _format_single_status(proc: ManagedProcess) -> ToolResult:
    """Format detailed status for a single process. Pure formatting — no side effects."""
    _check_completion(proc)
    pid_str = str(proc.process.pid) if proc.process.pid else "?"
    runtime = proc.runtime_secs()

    lines = [
        f"Process: {proc.name}",
        f"  Command:  {proc.command}",
        f"  PID:      {pid_str}",
        f"  State:    {proc.state}",
        f"  Runtime:  {runtime:.0f}s",
    ]
    if proc.exit_code is not None:
        lines.append(f"  Exit code: {proc.exit_code}")
    lines.append(f"  Log lines: {len(proc.stdout_lines)} stdout, {len(proc.stderr_lines)} stderr")

    return ToolResult(
        content="\n".join(lines),
        risk=RiskLevel.LOW,
        source="process",
    )


def _process_logs(name: str) -> ToolResult:
    """Read captured stdout/stderr from a tracked process."""
    if not name.strip():
        return ToolResult(
            content="logs requires a 'name' of the process.",
            risk=RiskLevel.LOW,
            source="process",
            success=False,
            error_type="missing_arg",
        )

    managed = _registry.get(name)
    if managed is None:
        return ToolResult(
            content=f"No process named '{name}' is being tracked.",
            risk=RiskLevel.LOW,
            source="process",
            success=False,
            error_type="not_found",
        )

    logs = managed.get_logs()
    runtime = managed.runtime_secs()
    header = f"Logs for '{name}' (runtime {runtime:.0f}s):\n"

    return ToolResult(
        content=header + logs,
        risk=RiskLevel.LOW,
        source="process",
    )


def _process_wait(name: str, timeout: float = _DEFAULT_WAIT_TIMEOUT) -> ToolResult:
    """Wait for a process to finish."""
    if not name.strip():
        return ToolResult(
            content="wait requires a 'name' of the process.",
            risk=RiskLevel.LOW,
            source="process",
            success=False,
            error_type="missing_arg",
        )

    timeout = max(1.0, min(timeout, _MAX_WAIT_TIMEOUT))

    managed = _registry.get(name)
    if managed is None:
        return ToolResult(
            content=f"No process named '{name}' is being tracked.",
            risk=RiskLevel.LOW,
            source="process",
            success=False,
            error_type="not_found",
        )

    if managed.state == "stopped":
        return ToolResult(
            content=f"Process '{name}' already finished (exit code {managed.exit_code}).",
            risk=RiskLevel.LOW,
            source="process",
        )

    proc = managed.process
    try:
        proc.wait(timeout=timeout)
        managed.state = "stopped"
        managed.exit_code = proc.returncode
        return ToolResult(
            content=f"Process '{name}' finished (exit code {managed.exit_code}).",
            risk=RiskLevel.LOW,
            source="process",
        )
    except subprocess.TimeoutExpired:
        return ToolResult(
            content=(
                f"Process '{name}' is still running after {timeout:.0f}s. "
                f"Use 'logs {name}' to see output, or wait longer."
            ),
            risk=RiskLevel.LOW,
            source="process",
            metadata={"timeout": timeout, "still_running": True},
        )


# ── Main dispatch ──────────────────────────────────────────────────────────────


async def process_dispatch(message: str) -> ToolResult:
    """Route to the correct process operation based on parsed args.

    Args:
        message: JSON-encoded arguments from the agent loop.
    """
    try:
        if message.strip().startswith("{"):
            args = json.loads(message)
        else:
            return ToolResult(
                content=(
                    "Process tool requires structured arguments. "
                    "Use 'operation' plus operation-specific parameters. "
                    'Example: {"operation": "start", "name": "dev-server", "command": "npm run dev"}'
                ),
                risk=RiskLevel.LOW,
                source="process",
                success=False,
                error_type="invalid_input",
            )
    except json.JSONDecodeError as exc:
        return ToolResult(
            content=f"Could not parse process arguments: {exc}",
            risk=RiskLevel.LOW,
            source="process",
            success=False,
            error_type="invalid_input",
        )

    operation = args.get("operation", "").strip().lower()
    cwd = _get_cwd()

    def _sync_dispatch() -> ToolResult:
        if operation == "start":
            name = args.get("name", "").strip()
            command = args.get("command", "").strip()
            return _process_start(cwd, name, command)
        elif operation == "stop":
            name = args.get("name", "").strip()
            force = args.get("force", False)
            return _process_stop(name, force=force)
        elif operation == "restart":
            name = args.get("name", "").strip()
            command = args.get("command", "").strip()
            return _process_restart(cwd, name, command)
        elif operation == "status":
            name = args.get("name", "").strip()
            return _process_status(name)
        elif operation == "logs":
            name = args.get("name", "").strip()
            return _process_logs(name)
        elif operation == "wait":
            name = args.get("name", "").strip()
            timeout = args.get("timeout", _DEFAULT_WAIT_TIMEOUT)
            try:
                timeout = float(timeout)
            except (ValueError, TypeError):
                timeout = _DEFAULT_WAIT_TIMEOUT
            return _process_wait(name, timeout=timeout)
        else:
            return ToolResult(
                content=(
                    f"Unknown process operation '{operation}'. "
                    f"Valid operations: start, stop, restart, status, logs, wait."
                ),
                risk=RiskLevel.LOW,
                source="process",
                success=False,
                error_type="unknown_operation",
            )

    try:
        return await asyncio.get_event_loop().run_in_executor(None, _sync_dispatch)
    except Exception as exc:
        logger.error("[process_tool] unexpected error: %s", exc, exc_info=True)
        return ToolResult(
            content=f"Process tool internal error: {exc}",
            risk=RiskLevel.HIGH,
            source="process",
            success=False,
            error_type="internal_error",
            error_message=str(exc),
        )


# ── Registration ───────────────────────────────────────────────────────────────

register_tool(
    Intent.PROCESS,
    process_dispatch,
    description=(
        "Manage long-running processes — start, stop, restart, check status, "
        "read logs, and wait for completion. Use this instead of shell for "
        "commands that run for more than a few seconds (dev servers, test runners, "
        "builds, docker containers). Operations: start (name + command → PID), "
        "stop (name → graceful SIGTERM or force SIGKILL), restart (stop + start), "
        "status (list all or check one), logs (captured stdout/stderr), "
        "wait (block until finished or timeout). Max log buffer: 200 lines per "
        "process. Stopped processes retain their logs until restart or reset."
    ),
    cost=0.2,
    latency_ms=1000,
    parallelizable=False,  # stateful — keep sequential
)
