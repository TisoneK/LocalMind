"""Terminal endpoint - advanced shell command execution with session management.

Features:
- Multi-session terminals with independent working directories
- Command history per session (navigable with up/down arrows)
- Tab-completion suggestions for commands and paths
- Configurable timeout for long-running commands
- Environment variable passthrough
- Tool execution bridge: agent tool results are logged in terminal sessions
- Shared session state: agent shell commands use terminal sessions for CWD continuity
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()
logger = logging.getLogger(__name__)


# ─── Session State ─────────────────────────────────────────────────────

# In-memory terminal sessions. Keyed by session_id.
# Each session tracks: current working directory, command history, env overrides,
# and tool execution log (commands executed by the AI agent).
_terminal_sessions: dict[str, dict] = {}

MAX_HISTORY = 500          # max commands per session
DEFAULT_TIMEOUT = 30       # seconds
MAX_OUTPUT_BYTES = 1_000_000  # 1 MB output cap to prevent memory exhaustion


def _get_session(session_id: str) -> dict:
    """Get or create a terminal session with defaults."""
    if session_id not in _terminal_sessions:
        _terminal_sessions[session_id] = {
            "cwd": os.path.expanduser("~"),
            "history": [],
            "env": {},
            "created_at": time.time(),
            # Tool execution log: entries added when the AI agent uses tools
            # that route through terminal (shell, code_exec, file ops, etc.)
            "tool_log": [],
        }
    return _terminal_sessions[session_id]


# ─── Session Bridge for Agent Tool Execution ───────────────────────────

class TerminalSessionBridge:
    """Bridge between the agent's tool system and terminal sessions.

    This class allows the agent's shell/code_exec tool executions to be
    routed through terminal sessions, providing:
    - Shared CWD: agent shell commands respect the terminal's current directory
    - Shared history: agent commands appear in the terminal's command history
    - Unified view: both user-initiated and agent-initiated commands in one stream
    """

    @staticmethod
    async def execute_in_session(
        command: str,
        session_id: str = "default",
        timeout: int = DEFAULT_TIMEOUT,
        source: str = "agent",
        tool_name: str = "shell",
    ) -> dict:
        """Execute a command in a terminal session context.

        Used by the agent loop to run shell commands through the terminal
        session system so that CWD, history, and tool log are shared.

        Returns dict with: exit_code, stdout, stderr, duration, command, cwd, source, tool_name
        """
        session = _get_session(session_id)
        cwd = session["cwd"]

        env = {**os.environ, **session.get("env", {})}

        # Record in history with source annotation
        history = session["history"]
        history.append(command)
        if len(history) > MAX_HISTORY:
            session["history"] = history[-MAX_HISTORY:]

        try:
            start_time = time.time()

            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                duration = time.time() - start_time
                result = {
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"Command timed out after {timeout}s",
                    "duration": duration,
                    "command": command,
                    "cwd": cwd,
                    "source": source,
                    "tool_name": tool_name,
                }
                _log_tool_execution(session, tool_name, command, result, source)
                return result

            duration = time.time() - start_time

            stdout_str = stdout.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
            stderr_str = stderr.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]

            # Detect directory changes and update session cwd
            _update_cwd_if_changed(session, command, cwd)

            result = {
                "exit_code": process.returncode or 0,
                "stdout": stdout_str,
                "stderr": stderr_str,
                "duration": duration,
                "command": command,
                "cwd": session["cwd"],
                "source": source,
                "tool_name": tool_name,
            }

            _log_tool_execution(session, tool_name, command, result, source)
            return result

        except Exception as e:
            logger.error(f"Terminal session bridge execution failed: {e}")
            result = {
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "duration": 0,
                "command": command,
                "cwd": cwd,
                "source": source,
                "tool_name": tool_name,
            }
            _log_tool_execution(session, tool_name, command, result, source)
            return result


def _log_tool_execution(
    session: dict,
    tool_name: str,
    command: str,
    result: dict,
    source: str = "agent",
) -> None:
    """Log a tool execution in the terminal session's tool_log."""
    entry = {
        "tool": tool_name,
        "command": command,
        "source": source,
        "exit_code": result.get("exit_code", -1),
        "duration": result.get("duration", 0),
        "success": result.get("exit_code", 0) == 0,
        "timestamp": time.time(),
    }
    tool_log = session.get("tool_log", [])
    tool_log.append(entry)
    # Keep last 200 tool executions per session
    if len(tool_log) > 200:
        session["tool_log"] = tool_log[-200:]
    else:
        session["tool_log"] = tool_log


# ─── Request / Response Models ─────────────────────────────────────────

class TerminalRequest(BaseModel):
    command: str
    cwd: Optional[str] = None
    session_id: Optional[str] = "default"
    timeout: Optional[int] = Field(default=DEFAULT_TIMEOUT, ge=1, le=300, description="Execution timeout in seconds")
    env: Optional[dict[str, str]] = None


class TerminalResponse(BaseModel):
    """Response uses camelCase aliases to match frontend TypeScript types."""
    exit_code: int = Field(alias="exitCode")
    stdout: str
    stderr: str
    duration: float
    command: str
    cwd: str

    model_config = {"populate_by_name": True}


class HistoryResponse(BaseModel):
    session_id: str = Field(alias="sessionId")
    commands: list[str]
    count: int

    model_config = {"populate_by_name": True}


class CompletionRequest(BaseModel):
    partial: str
    cwd: Optional[str] = None
    session_id: Optional[str] = "default"


class CompletionResponse(BaseModel):
    suggestions: list[str]
    count: int


class SessionInfoResponse(BaseModel):
    session_id: str = Field(alias="sessionId")
    cwd: str
    history_count: int = Field(alias="historyCount")
    env_count: int = Field(alias="envCount")
    tool_execution_count: int = Field(alias="toolExecutionCount")

    model_config = {"populate_by_name": True}


class ProcessKillRequest(BaseModel):
    pid: int


class ProcessKillResponse(BaseModel):
    success: bool
    message: str


class ToolExecutionLogEntry(BaseModel):
    """A single tool execution logged in the terminal session."""
    tool: str
    command: str
    source: str
    exit_code: int = Field(alias="exitCode")
    duration: float
    success: bool
    timestamp: float

    model_config = {"populate_by_name": True}


class ToolExecutionLogResponse(BaseModel):
    session_id: str = Field(alias="sessionId")
    entries: list[ToolExecutionLogEntry]
    count: int

    model_config = {"populate_by_name": True}


class ToolEventRequest(BaseModel):
    """Request to log a tool execution event from the agent into a terminal session."""
    tool: str
    command: str
    output: str
    success: bool
    latency_ms: int = Field(alias="latencyMs")
    session_id: Optional[str] = "default"
    source: Optional[str] = "agent"

    model_config = {"populate_by_name": True}


class ToolEventResponse(BaseModel):
    logged: bool
    session_id: str = Field(alias="sessionId")
    entry_count: int = Field(alias="entryCount")

    model_config = {"populate_by_name": True}


# ─── Endpoints ─────────────────────────────────────────────────────────

@router.post("/terminal/execute", response_model=TerminalResponse)
async def execute_terminal_command(request: TerminalRequest):
    """Execute a shell command and return the result.

    Supports:
    - Per-session working directory (cwd is persisted across commands)
    - Configurable timeout
    - Environment variable overrides
    - Command history tracking
    - Tool execution logging
    """
    session = _get_session(request.session_id or "default")

    # Resolve working directory: explicit cwd > session cwd > home
    cwd = request.cwd or session["cwd"]
    if not os.path.isdir(cwd):
        cwd = os.path.expanduser("~")

    # Merge environment: base env + session env + per-command env
    env = {**os.environ, **session.get("env", {})}
    if request.env:
        env.update(request.env)

    # Record command in history
    history = session["history"]
    history.append(request.command)
    if len(history) > MAX_HISTORY:
        session["history"] = history[-MAX_HISTORY:]

    try:
        start_time = time.time()

        process = await asyncio.create_subprocess_shell(
            request.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=request.timeout or DEFAULT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            duration = time.time() - start_time
            result = TerminalResponse(
                exit_code=-1,
                stdout="",
                stderr=f"Command timed out after {request.timeout or DEFAULT_TIMEOUT}s",
                duration=duration,
                command=request.command,
                cwd=cwd,
            )
            _log_tool_execution(session, "terminal", request.command, {
                "exit_code": -1, "duration": duration,
            }, source="user")
            return result

        duration = time.time() - start_time

        # Truncate oversized output
        stdout_str = stdout.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
        stderr_str = stderr.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]

        # Detect directory changes and update session cwd
        _update_cwd_if_changed(session, request.command, cwd)

        # Log the execution
        _log_tool_execution(session, "terminal", request.command, {
            "exit_code": process.returncode or 0,
            "duration": duration,
        }, source="user")

        return TerminalResponse(
            exit_code=process.returncode or 0,
            stdout=stdout_str,
            stderr=stderr_str,
            duration=duration,
            command=request.command,
            cwd=session["cwd"],  # Return the *current* session cwd
        )

    except Exception as e:
        logger.error(f"Terminal command failed: {e}")
        raise HTTPException(status_code=500, detail=f"Command execution failed: {str(e)}")


@router.get("/terminal/history/{session_id}", response_model=HistoryResponse)
async def get_command_history(session_id: str, limit: int = 50, offset: int = 0):
    """Retrieve command history for a session, newest first."""
    session = _get_session(session_id)
    history = session["history"]
    sliced = history[-(offset + limit):][::-1] if offset == 0 else history[-(offset + limit):-offset][::-1]
    return HistoryResponse(
        session_id=session_id,
        commands=sliced,
        count=len(history),
    )


@router.post("/terminal/complete", response_model=CompletionResponse)
async def tab_complete(request: CompletionRequest):
    """Provide tab-completion suggestions for a partial command.

    Returns matching files/directories and common command prefixes.
    """
    session = _get_session(request.session_id or "default")
    cwd = request.cwd or session["cwd"]
    suggestions: list[str] = []

    partial = request.partial.strip()
    if not partial:
        return CompletionResponse(suggestions=[], count=0)

    # ── Path completion ──
    if "/" in partial or partial.startswith("~") or partial.startswith("."):
        path_part = partial
        prefix = ""

        parts = partial.rsplit(maxsplit=1)
        if len(parts) == 2:
            prefix = parts[0] + " "
            path_part = parts[1]

        path_part = os.path.expanduser(path_part)

        if path_part.endswith("/"):
            base_dir = path_part
            name_prefix = ""
        else:
            base_dir = os.path.dirname(path_part) or cwd
            name_prefix = os.path.basename(path_part)

        try:
            entries = os.listdir(base_dir)
            matches = [
                e for e in sorted(entries)
                if e.startswith(name_prefix) and not e.startswith(".")
            ][:20]
            for m in matches:
                full_path = os.path.join(base_dir, m)
                suffix = "/" if os.path.isdir(full_path) else ""
                suggestions.append(f"{prefix}{os.path.join(base_dir, m)}{suffix}")
        except (OSError, ValueError):
            pass

    # ── Command completion ──
    if " " not in partial:
        common_commands = [
            "ls", "cd", "pwd", "cat", "echo", "mkdir", "rm", "cp", "mv",
            "grep", "find", "head", "tail", "wc", "sort", "uniq", "diff",
            "chmod", "chown", "curl", "wget", "tar", "gzip", "unzip",
            "python3", "pip", "node", "npm", "git", "docker", "code",
            "vim", "nano", "less", "more", "which", "env", "export",
            "ps", "top", "htop", "kill", "df", "du", "free", "uname",
            "date", "whoami", "hostname", "ip", "ping", "netstat",
            "apt", "brew", "yum", "dnf", "systemctl", "journalctl",
        ]
        matches = [c for c in common_commands if c.startswith(partial)][:10]
        suggestions.extend(matches)

    return CompletionResponse(suggestions=suggestions[:30], count=len(suggestions))


@router.get("/terminal/session/{session_id}", response_model=SessionInfoResponse)
async def get_session_info(session_id: str):
    """Get information about a terminal session."""
    session = _get_session(session_id)
    return SessionInfoResponse(
        session_id=session_id,
        cwd=session["cwd"],
        history_count=len(session["history"]),
        env_count=len(session.get("env", {})),
        tool_execution_count=len(session.get("tool_log", [])),
    )


@router.post("/terminal/session/{session_id}/cwd")
async def set_session_cwd(session_id: str, cwd: str):
    """Update the working directory for a terminal session."""
    session = _get_session(session_id)
    if os.path.isdir(cwd):
        session["cwd"] = cwd
        return {"status": "ok", "cwd": cwd}
    raise HTTPException(status_code=400, detail=f"Not a directory: {cwd}")


@router.post("/terminal/kill", response_model=ProcessKillResponse)
async def kill_process(request: ProcessKillRequest):
    """Attempt to kill a running process by PID."""
    try:
        os.kill(request.pid, 9)
        return ProcessKillResponse(success=True, message=f"Sent SIGKILL to PID {request.pid}")
    except ProcessLookupError:
        return ProcessKillResponse(success=False, message=f"PID {request.pid} not found")
    except PermissionError:
        return ProcessKillResponse(success=False, message=f"Permission denied for PID {request.pid}")
    except Exception as e:
        return ProcessKillResponse(success=False, message=str(e))


@router.get("/terminal/sessions")
async def list_sessions():
    """List all active terminal sessions."""
    return {
        "sessions": [
            {
                "sessionId": sid,
                "cwd": s["cwd"],
                "historyCount": len(s["history"]),
                "envCount": len(s.get("env", {})),
                "toolExecutionCount": len(s.get("tool_log", [])),
            }
            for sid, s in _terminal_sessions.items()
        ]
    }


@router.delete("/terminal/session/{session_id}")
async def delete_session(session_id: str):
    """Delete a terminal session and its history."""
    if session_id in _terminal_sessions:
        del _terminal_sessions[session_id]
        return {"status": "ok", "message": f"Session {session_id} deleted"}
    raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


# ─── Tool Execution Bridge Endpoints ──────────────────────────────────

@router.post("/terminal/tool-event", response_model=ToolEventResponse)
async def log_tool_event(request: ToolEventRequest):
    """Log a tool execution event from the agent into a terminal session.

    This endpoint allows the agent's tool system to record its executions
    in the terminal session's tool log. This creates a unified history of
    both user-initiated and agent-initiated operations.

    Called by the agent loop when any tool is executed (shell, code_exec,
    file_task, file_write, edit_file, web_search, sysinfo, memory_op).
    """
    session = _get_session(request.session_id or "default")

    entry = {
        "tool": request.tool,
        "command": request.command,
        "source": request.source or "agent",
        "exit_code": 0 if request.success else 1,
        "duration": request.latency_ms / 1000.0,
        "success": request.success,
        "timestamp": time.time(),
    }

    tool_log = session.get("tool_log", [])
    tool_log.append(entry)
    if len(tool_log) > 200:
        session["tool_log"] = tool_log[-200:]
    else:
        session["tool_log"] = tool_log

    # Also add to command history for agent-initiated shell commands
    if request.tool in ("shell", "code_exec") and request.command:
        history = session["history"]
        history.append(request.command)
        if len(history) > MAX_HISTORY:
            session["history"] = history[-MAX_HISTORY:]

    # Update CWD if the agent shell command changed directory
    if request.tool == "shell" and request.command.strip().startswith("cd "):
        _update_cwd_if_changed(session, request.command, session["cwd"])

    return ToolEventResponse(
        logged=True,
        session_id=request.session_id or "default",
        entry_count=len(session.get("tool_log", [])),
    )


@router.get("/terminal/tool-log/{session_id}", response_model=ToolExecutionLogResponse)
async def get_tool_execution_log(session_id: str, limit: int = 50, offset: int = 0):
    """Get the tool execution log for a terminal session.

    Returns a list of tool executions (both user-initiated and agent-initiated)
    that were logged in this session.
    """
    session = _get_session(session_id)
    tool_log = session.get("tool_log", [])

    if offset == 0:
        sliced = tool_log[-limit:][::-1]
    else:
        sliced = tool_log[-(offset + limit):-offset][::-1]

    entries = [
        ToolExecutionLogEntry(
            tool=e.get("tool", "unknown"),
            command=e.get("command", ""),
            source=e.get("source", "agent"),
            exit_code=e.get("exit_code", -1),
            duration=e.get("duration", 0),
            success=e.get("success", False),
            timestamp=e.get("timestamp", 0),
        )
        for e in sliced
    ]

    return ToolExecutionLogResponse(
        session_id=session_id,
        entries=entries,
        count=len(tool_log),
    )


# ─── Helpers ───────────────────────────────────────────────────────────

def _update_cwd_if_changed(session: dict, command: str, current_cwd: str) -> None:
    """If the command was a 'cd', update the session's working directory."""
    stripped = command.strip()
    if not stripped.startswith("cd "):
        return

    target = stripped[3:].strip()

    target = target.strip("'\"")

    if target == "~" or target == "":
        session["cwd"] = os.path.expanduser("~")
    elif target == "-":
        pass
    else:
        target = os.path.expanduser(target)
        if not os.path.isabs(target):
            target = os.path.join(current_cwd, target)
        target = os.path.normpath(target)
        if os.path.isdir(target):
            session["cwd"] = target
