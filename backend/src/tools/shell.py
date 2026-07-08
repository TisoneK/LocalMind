"""
tools/shell.py — Shell tool for LocalMind. Phase 3 (T5).

Contract-based execution model.  _dispatch() is gone.

Every handler now accepts typed, pre-resolved arguments supplied by the
planner.  No string parsing, no NL interpretation, no folder-name guessing
inside handlers.  The orchestrator validates the payload against ShellContract
before this module is ever called.

ShellContract actions and their required input fields:

    action          | additional required fields
    ────────────────┼──────────────────────────────────
    list_files      | path: str
    find_files      | path: str, file_type: str
    run_command     | command: str
    open_app        | name: str
    open_file       | path: str
    open_website    | url: str
    check_disk      | (none beyond action)
    check_internet  | (none beyond action)
    get_ip          | (none beyond action)
    get_sysinfo     | (none beyond action)

Integration contract (unchanged from pre-T5):
  • Returns ToolResult — always, never raises
  • Registered as Intent.SHELL via register_tool()
  • Registered as ShellContract via ToolRegistry.register()
  • Async wrapper around sync handlers
"""
from __future__ import annotations

import asyncio
import logging
import platform
import re
import shutil
import subprocess
import traceback
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict

from core.config import settings
from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool
from tools.contracts.base import ToolContract, ToolRegistry

logger = logging.getLogger(__name__)

# ── Platform — resolved once, never guessed ───────────────────────────────────
SYSTEM = platform.system()
HOME   = Path.home()
IS_WIN = SYSTEM == "Windows"
IS_MAC = SYSTEM == "Darwin"

# ── App map ───────────────────────────────────────────────────────────────────
APP_MAP_WINDOWS: dict[str, str] = {
    "chrome":        "start chrome",
    "firefox":       "start firefox",
    "edge":          "start msedge",
    "word":          "start winword",
    "excel":         "start excel",
    "powerpoint":    "start powerpnt",
    "notepad":       "start notepad",
    "calculator":    "start calc",
    "outlook":       "start outlook",
    "explorer":      "start explorer",
    "files":         "start explorer",
    "paint":         "start mspaint",
    "vlc":           "start vlc",
    "spotify":       "start spotify",
    "teams":         "start teams",
    "zoom":          "start zoom",
    "settings":      "start ms-settings:",
    "control panel": "control",
    "task manager":  "taskmgr",
}

APP_MAP_MAC: dict[str, str] = {
    "chrome":      "open -a 'Google Chrome'",
    "firefox":     "open -a Firefox",
    "safari":      "open -a Safari",
    "word":        "open -a 'Microsoft Word'",
    "excel":       "open -a 'Microsoft Excel'",
    "powerpoint":  "open -a 'Microsoft PowerPoint'",
    "calculator":  "open -a Calculator",
    "outlook":     "open -a 'Microsoft Outlook'",
    "finder":      "open .",
    "files":       "open .",
    "spotify":     "open -a Spotify",
    "vlc":         "open -a VLC",
    "teams":       "open -a 'Microsoft Teams'",
    "zoom":        "open -a zoom.us",
    "settings":    "open 'x-apple.systempreferences:'",
    "mail":        "open -a Mail",
    "notes":       "open -a Notes",
}

APP_MAP_LINUX: dict[str, str] = {
    "chrome":      "xdg-open https://google.com",
    "firefox":     "firefox &",
    "calculator":  "gnome-calculator &",
    "files":       "nautilus &",
    "spotify":     "spotify &",
    "vlc":         "vlc &",
    "settings":    "gnome-control-center &",
}

APP_MAP = (
    APP_MAP_WINDOWS if IS_WIN else
    APP_MAP_MAC     if IS_MAC else
    APP_MAP_LINUX
)

KNOWN_SITES: dict[str, str] = {
    "google":    "https://google.com",
    "amazon":    "https://amazon.com",
    "youtube":   "https://youtube.com",
    "facebook":  "https://facebook.com",
    "gmail":     "https://mail.google.com",
    "outlook":   "https://outlook.com",
    "netflix":   "https://netflix.com",
    "wikipedia": "https://wikipedia.org",
}

BLOCKED_COMMANDS = [
    "format", "del /f", "rm -rf /", "rmdir /s /q c:\\",
    "shutdown", "reboot", ":(){:|:&};:", "dd if=", "mkfs",
    "reg delete", "net user", "net localgroup",
]

FILE_TYPE_EXTENSIONS: dict[str, list[str]] = {
    "photo":       ["jpg", "jpeg", "png", "heic", "raw"],
    "photos":      ["jpg", "jpeg", "png", "heic", "raw"],
    "picture":     ["jpg", "jpeg", "png", "heic", "raw"],
    "image":       ["jpg", "jpeg", "png", "heic", "raw", "gif", "webp"],
    "video":       ["mp4", "mov", "avi", "mkv", "wmv"],
    "music":       ["mp3", "wav", "flac", "aac", "m4a"],
    "document":    ["docx", "doc", "pdf", "odt", "rtf"],
    "pdf":         ["pdf"],
    "spreadsheet": ["xlsx", "xls", "csv", "ods"],
    "tax":         ["pdf", "xlsx", "docx"],
    "receipt":     ["pdf", "jpg", "jpeg", "png"],
}

# ── Internal helpers ───────────────────────────────────────────────────────────

def _ok(message: str) -> dict:
    return {"success": True, "message": message}


def _err(message: str) -> dict:
    return {"success": False, "message": message}


# ── Session CWD context variable ─────────────────────────────────────────────
# Set by the Engine before each tool dispatch so that shell commands
# run in the correct working directory. Uses contextvars so it works
# correctly with asyncio (each coroutine sees its own value).
_session_cwd_var: ContextVar[str | None] = ContextVar("_session_cwd", default=None)


def set_session_cwd(cwd: str | None) -> None:
    """Set the session CWD for subsequent shell command execution.

    Called by the Engine before each tool dispatch so that shell commands
    execute in the user's current working directory, not the server's CWD.
    """
    _session_cwd_var.set(cwd)


def _run(cmd: str | list, timeout: int = 20, cwd: str | None = None) -> dict:
    """Execute a shell command. Returns {success, message}. Never raises."""
    for blocked in BLOCKED_COMMANDS:
        target = cmd if isinstance(cmd, str) else " ".join(cmd)
        if blocked.lower() in target.lower():
            return _err(f"Command blocked for safety: contains '{blocked}'")
    # Resolve CWD: explicit parameter > session context var > None (inherit OS default)
    effective_cwd = cwd or _session_cwd_var.get(None)
    # Validate that the CWD directory still exists before passing it
    if effective_cwd and not Path(effective_cwd).is_dir():
        logger.warning(f"[shell] Session CWD {effective_cwd} no longer exists, falling back to default")
        effective_cwd = None
    try:
        result = subprocess.run(
            cmd,
            shell=isinstance(cmd, str),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=effective_cwd,
        )
        output = (result.stdout + result.stderr).strip()
        return _ok(output) if result.returncode == 0 else _err(output or "Command failed (no output)")
    except subprocess.TimeoutExpired:
        return _err(f"Command timed out after {timeout}s")
    except FileNotFoundError as exc:
        return _err(f"Command not found: {exc}")
    except Exception as exc:
        return _err(str(exc))


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} PB"


# ── Typed handlers — accept concrete values, no string interpretation ──────────
#
# Each function takes the exact type(s) the planner emits.
# No string parsing, no regex over intent-bearing strings, no guessing.


def _show_files(path: Path) -> tuple[str, RiskLevel]:
    """List files in a directory. path must be a fully-resolved Path."""
    if not path.exists():
        return (
            f"Folder not found: {path}\nIt may not exist on this computer.",
            RiskLevel.LOW,
        )
    if not path.is_dir():
        return f"'{path}' is a file, not a folder.", RiskLevel.LOW
    try:
        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        if not entries:
            return f"The {path.name} folder is empty.", RiskLevel.LOW

        lines = [f"📁  {path}\n"]
        dirs  = [e for e in entries if e.is_dir()]
        files = [e for e in entries if e.is_file()]

        if dirs:
            lines.append(f"Folders ({len(dirs)}):")
            for d in dirs[:20]:
                lines.append(f"  📁  {d.name}")
            if len(dirs) > 20:
                lines.append(f"  … and {len(dirs) - 20} more folders")

        if files:
            lines.append(f"\nFiles ({len(files)}):")
            for f in files[:30]:
                size = _human_size(f.stat().st_size)
                lines.append(f"  📄  {f.name}  ({size})")
            if len(files) > 30:
                lines.append(f"  … and {len(files) - 30} more files")

        return "\n".join(lines), RiskLevel.LOW
    except PermissionError:
        return f"No permission to view {path}.", RiskLevel.LOW


def _find_files(path: Path, file_type: str) -> tuple[str, RiskLevel]:
    """Find files of a given type under path. Both are caller-supplied."""
    extensions = FILE_TYPE_EXTENSIONS.get(file_type.lower(), [])
    if not extensions:
        # file_type not in map — treat as a literal extension
        extensions = [file_type.lstrip(".").lower()]

    try:
        matches: list[Path] = []
        for ext in extensions:
            matches.extend(path.rglob(f"*.{ext}"))
        matches = sorted(set(matches))[:50]

        if not matches:
            ext_str = ", ".join(f".{e}" for e in extensions)
            return (
                f"No {file_type} files ({ext_str}) found under {path}.",
                RiskLevel.LOW,
            )

        lines = [f"Found {len(matches)} {file_type} file(s) in {path}:\n"]
        for m in matches:
            size = _human_size(m.stat().st_size)
            lines.append(f"  📄  {m.name}  ({size})\n      {m.parent}")
        return "\n".join(lines), RiskLevel.LOW
    except PermissionError:
        return f"No permission to search {path}.", RiskLevel.LOW


def _run_command(command: str, cwd: str | None = None) -> tuple[str, RiskLevel]:
    """Execute a raw shell command. command must be a literal command string."""
    result = _run(command, cwd=cwd)
    if result["success"]:
        output = result["message"].strip() or "(command completed with no output)"
        return output, RiskLevel.MEDIUM
    return f"Command failed:\n{result['message']}", RiskLevel.MEDIUM


def _open_app(name: str) -> tuple[str, RiskLevel]:
    """Open a named application. name is a lowercase app key or alias."""
    key = name.lower().strip()
    cmd = APP_MAP.get(key)
    if cmd:
        result = _run(cmd)
        if result["success"]:
            return f"✅  Opening {name.title()}…", RiskLevel.LOW
        return f"Couldn't open {name.title()}. It may not be installed.", RiskLevel.MEDIUM

    return (
        f"Unknown app '{name}'.\n"
        f"Known apps: {', '.join(sorted(APP_MAP))}",
        RiskLevel.LOW,
    )


def _open_file(path: Path) -> tuple[str, RiskLevel]:
    """Open a file with the system default handler. path must be fully resolved."""
    if not path.exists():
        return f"File not found: {path}", RiskLevel.LOW
    cmd = (
        f'start "" "{path}"' if IS_WIN else
        f'open "{path}"'     if IS_MAC else
        f'xdg-open "{path}"'
    )
    _run(cmd)
    return f"✅  Opening {path.name} from {path.parent}", RiskLevel.LOW


def _open_website(url: str) -> tuple[str, RiskLevel]:
    """Open a URL in the default browser. url must be a fully-formed https:// URL."""
    # Resolve known site aliases before opening
    key = url.lower().rstrip("/").lstrip("https://").lstrip("http://").split("/")[0]
    resolved = KNOWN_SITES.get(key, url)
    if not resolved.startswith(("http://", "https://")):
        resolved = "https://" + resolved

    cmd = (
        f"start {resolved}"  if IS_WIN else
        f"open {resolved}"   if IS_MAC else
        f"xdg-open {resolved}"
    )
    _run(cmd)
    return f"✅  Opening {resolved} in your browser…", RiskLevel.LOW


def _check_disk_space() -> tuple[str, RiskLevel]:
    try:
        usage = shutil.disk_usage(HOME)
        pct   = (usage.used / usage.total) * 100
        bar   = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        msg = (
            f"💾  Disk Space\n\n"
            f"  [{bar}] {pct:.0f}% used\n\n"
            f"  Used:  {_human_size(usage.used)}\n"
            f"  Free:  {_human_size(usage.free)}\n"
            f"  Total: {_human_size(usage.total)}"
        )
        if usage.free < 5 * (1024 ** 3):
            msg += "\n\n⚠️  Low disk space! Consider deleting large files."
        return msg, RiskLevel.LOW
    except Exception as exc:
        return str(exc), RiskLevel.LOW


def _check_internet() -> tuple[str, RiskLevel]:
    cmd = ["ping", "-n", "2", "8.8.8.8"] if IS_WIN else ["ping", "-c", "2", "8.8.8.8"]
    result = _run(cmd, timeout=10)
    return (
        "✅  Internet is working." if result["success"]
        else "❌  No internet connection detected.",
        RiskLevel.LOW,
    )


def _get_ip_address() -> tuple[str, RiskLevel]:
    result = _run("ipconfig" if IS_WIN else ("ifconfig" if IS_MAC else "ip addr show"))
    if not result["success"]:
        return "Couldn't retrieve IP address.", RiskLevel.LOW
    ips = [
        m.group(1)
        for line in result["message"].splitlines()
        if (m := re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", line))
        and not m.group(1).startswith(("127.", "255."))
    ]
    return (
        f"🌐  Your IP address: {ips[0]}" if ips
        else "Couldn't determine IP address.",
        RiskLevel.LOW,
    )


def _get_system_info() -> tuple[str, RiskLevel]:
    lines = [
        "💻  System Information\n",
        f"  Computer: {platform.node()}",
        f"  OS:       {SYSTEM} {platform.release()}",
        f"  Version:  {platform.version()[:60]}",
        f"  User:     {HOME.name}",
        f"  Home:     {HOME}",
    ]
    try:
        import psutil
        lines.append(
            f"  RAM:      {_human_size(psutil.virtual_memory().available)} free "
            f"of {_human_size(psutil.virtual_memory().total)}"
        )
    except ImportError:
        pass
    return "\n".join(lines), RiskLevel.LOW


# ── ShellContract — Phase 3 full contract ─────────────────────────────────────

class ShellContract(ToolContract):
    """
    Full Phase 3 contract for the shell tool.

    Required payload field:  action: str (one of ACTIONS below)
    Additional fields:       action-specific — validated inside execute().

    The orchestrator validates action: str exists before calling execute().
    execute() validates the action-specific fields (e.g. path for list_files)
    and raises ValueError on any missing field — this is an executor error,
    not a contract violation (the contract is satisfied; the payload is just
    incomplete for the declared action).
    """

    name = "shell"
    schema = {"action": str}   # T2 schema — action is the only universal field

    # Canonical action set — the planner MUST use one of these.
    ACTIONS = frozenset({
        "list_files",
        "find_files",
        "run_command",
        "open_app",
        "open_file",
        "open_website",
        "check_disk",
        "check_internet",
        "get_ip",
        "get_sysinfo",
    })

    async def execute(self, payload: Dict[str, Any]) -> ToolResult:
        """
        Route to the correct typed handler based on payload["action"].

        Precondition: payload["action"] is a str (guaranteed by validate()).
        Each branch extracts only the fields it needs and passes typed values
        to the handler — no string parsing, no NL inside handlers.
        """
        if not getattr(settings, "localmind_shell_enabled", False):
            return ToolResult(
                content="Shell tool is disabled. Set LOCALMIND_SHELL_ENABLED=true to enable.",
                risk=RiskLevel.LOW,
                source="shell",
                success=False,
                error_type="permission",
                error_message="Shell tool disabled via LOCALMIND_SHELL_ENABLED.",
            )

        action = payload["action"].lower().strip()
        if action not in self.ACTIONS:
            return ToolResult(
                content=(
                    f"Unknown shell action '{action}'.\n"
                    f"Valid actions: {', '.join(sorted(self.ACTIONS))}"
                ),
                risk=RiskLevel.LOW,
                source="shell",
                success=False,
                error_type="invalid_action",
            )

        def _sync() -> tuple[str, RiskLevel]:
            if action == "list_files":
                path = _require_path(payload, "path", action)
                return _show_files(path)

            if action == "find_files":
                path      = _require_path(payload, "path", action)
                file_type = _require_str(payload, "file_type", action)
                return _find_files(path, file_type)

            if action == "run_command":
                command = _require_str(payload, "command", action)
                return _run_command(command)

            if action == "open_app":
                name = _require_str(payload, "name", action)
                return _open_app(name)

            if action == "open_file":
                path = _require_path(payload, "path", action)
                return _open_file(path)

            if action == "open_website":
                url = _require_str(payload, "url", action)
                return _open_website(url)

            if action == "check_disk":
                return _check_disk_space()

            if action == "check_internet":
                return _check_internet()

            if action == "get_ip":
                return _get_ip_address()

            if action == "get_sysinfo":
                return _get_system_info()

            # Unreachable — action in ACTIONS guard above — but be explicit.
            return f"Unhandled action '{action}'", RiskLevel.LOW

        try:
            content, risk = await asyncio.get_event_loop().run_in_executor(None, _sync)
            return ToolResult(content=content, risk=risk, source="shell")
        except _FieldError as exc:
            return ToolResult(
                content=str(exc),
                risk=RiskLevel.LOW,
                source="shell",
                success=False,
                error_type="missing_field",
                error_message=str(exc),
            )
        except Exception as exc:
            return ToolResult(
                content=f"[TOOL ERROR] Unexpected shell failure: {exc}",
                risk=RiskLevel.HIGH,
                source="shell",
                metadata={"traceback": traceback.format_exc()},
                success=False,
                error_type="internal_error",
                error_message=str(exc),
            )


# ── Field extraction helpers ───────────────────────────────────────────────────
# Used inside ShellContract.execute() to extract action-specific fields cleanly.

class _FieldError(ValueError):
    """Raised when an action-required field is missing from the payload."""


def _require_str(payload: Dict[str, Any], field: str, action: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise _FieldError(
            f"shell action '{action}' requires '{field}': str in payload. "
            f"Planner must emit this field."
        )
    return value.strip()


def _require_path(payload: Dict[str, Any], field: str, action: str) -> Path:
    raw = _require_str(payload, field, action)
    # Expand ~ once — the planner may emit home-relative paths.
    # No further interpretation: we use what the planner gave us.
    return Path(raw).expanduser().resolve()


# ── Legacy entry point — kept for backward compat during Phase 3 migration ────

async def shell_exec(message: str) -> ToolResult:
    """
    Legacy string-based entry point — kept so that existing callers that go
    through dispatch(Intent.SHELL, str) continue to work during the Phase 3
    migration period.

    Behaviour:
      1. If message is a JSON dict (emitted by the legacy bridge contract),
         delegate to ShellContract().execute(payload) directly.
      2. If message is a raw shell command (contains operators or known tokens),
         route to run_command action.
      3. Otherwise return a graceful error — NL dispatch is gone.

    This function will be removed when all callers are migrated to the
    contract path.
    """
    import json as _json

    # Case 1 — structured payload from legacy bridge
    try:
        parsed = _json.loads(message)
        if isinstance(parsed, dict) and "action" in parsed:
            return await ShellContract().execute(parsed)
    except (_json.JSONDecodeError, ValueError):
        pass

    # Case 2 — raw shell command (deterministic gate, no heuristics)
    _RAW_CMD_TOKENS = {
        "&&", "||", ">>", ">", ";", "|",
        "echo", "mkdir", "touch", "cp", "mv", "rm", "cat",
        "type", "copy", "move", "del", "md", "rd", "cd",
        "ls", "dir", "pwd", "chmod", "chown",
        "python", "python3", "node", "npm", "git", "pip",
    }
    first_token = message.strip().split()[0].lower() if message.strip() else ""
    has_operator = any(op in message for op in {"&&", "||", ">>", ">", ";", "|"})
    if has_operator or first_token in _RAW_CMD_TOKENS:
        return await ShellContract().execute({"action": "run_command", "command": message})

    # Case 3 — NL string with no structured payload
    # ANTI-FABRICATION: Instead of returning an error that leads the LLM
    # to fabricate results, try to extract a path from the NL string and
    # route to list_files. This handles cases like "Show me projects in
    # Documents/Code/" that arrive via the direct dispatch path.
    _PATH_PATTERNS = [
        # "Show me projects in Documents/Code/" → extract path
        re.compile(r'(?:in|from|at|inside|under)\s+["\']?([A-Za-z]:[\\/][^\s"\']+|~?/?[A-Za-z][\w./\\-]*)', re.IGNORECASE),
        # "List C:\Users\tison\Documents" → extract path
        re.compile(r'["\']([A-Za-z]:[\\/][^\s"\']+)["\']'),
        # "Documents/Code" or "~/Documents" as standalone path
        re.compile(r'^[~./\\\w][\w./\\-]*$', re.IGNORECASE),
    ]
    for pattern in _PATH_PATTERNS:
        m = pattern.search(message.strip())
        if m:
            raw_path = m.group(1) if m.lastindex else m.group(0)
            resolved = Path(raw_path).expanduser().resolve()
            if resolved.exists() and resolved.is_dir():
                logger.info(f"[shell] NL fallback: extracted path={resolved}, routing to list_files")
                return await ShellContract().execute({"action": "list_files", "path": str(resolved)})

    return ToolResult(
        content=(
            "Shell tool v2 requires structured input via the orchestrator contract layer.\n"
            "NL dispatch (e.g. 'show my documents') is no longer supported.\n"
            "Use the orchestrator planner to emit: "
            '{"action": "list_files", "path": "/path/to/folder"}'
        ),
        risk=RiskLevel.LOW,
        source="shell",
        success=False,
        error_type="nl_dispatch_removed",
    )


# ── Registration ───────────────────────────────────────────────────────────────

# Register with the legacy string-dispatch registry (backward compat)
register_tool(
    Intent.SHELL,
    shell_exec,
    description="Execute shell commands and filesystem operations: list directory contents, "
                "find files, run commands, open apps/files/websites, check disk/internet/IP. "
                "Use shell list_files for directory/folder listings — NOT file_task. "
                "Commands must match the current OS (Windows: dir, type | Unix: ls, cat).",
    cost=0.3,
    latency_ms=800,
    parallelizable=False,   # stateful OS calls — keep sequential
)

# Register with the ToolRegistry (contract enforcement layer — T3)
ToolRegistry.register(ShellContract)
