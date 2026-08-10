"""
Observe tool — desktop awareness (B-2026-07-31-9, Session 130).

Answers "what's happening right now?" — the observation half of the
Observe→Think→Decide→Act→Observe→Verify loop. Offline, fast, no model
call, <200ms typical.

Sub-queries (routed by keywords in the query string):
  - active_window  — the focused window's app + title
  - clipboard      — current clipboard text
  - running_apps   — top running GUI-ish applications (by memory)
  - system_state   — CPU / RAM / disk / battery quick snapshot
  - recent_files   — filesystem changes: files modified in the last N
                     minutes under a directory (default cwd/home)
  - all / default  — active_window + system_state + running_apps (top)

Design contract (learned from the Session 124/125 context-flood bugs):
  - BOUNDED output by construction: caps on every list (apps, recent
    files), no raw dumps.
  - GRACEFUL DEGRADATION: every sub-query is wrapped; on an unsupported
    platform or missing CLI it returns a short "not available here"
    note with a suggestion — never an exception, never a silent empty
    answer. That is the user's core complaint: silent failure is worse
    than slow failure.

Registered as Intent.OBSERVE.
"""

from __future__ import annotations

import datetime
import logging
import os
import platform
import shutil
import subprocess

from core.models import Intent, RiskLevel, ToolResult
from tools import register_tool

logger = logging.getLogger(__name__)

# Hard caps — the output must stay tiny (context protection).
_MAX_APPS = 8
_MAX_RECENT_FILES = 8
_RECENT_WINDOW_MINUTES = 60


# ── Low-level platform helpers ────────────────────────────────────────────────


def _run(cmd: list[str], timeout: float = 3.0) -> str:
    """Run a quick platform command; return stripped stdout or '' on any failure."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            startupinfo=_no_window() if os.name == "nt" else None,
        )
        return (proc.stdout or "").strip()
    except Exception as e:  # noqa: BLE001 — every failure degrades, never raises
        logger.debug("[observe] command failed %s: %s", cmd[0], e)
        return ""


def _no_window():
    """Windows: don't flash a console for the helper commands."""
    if os.name != "nt":
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return si


def _is_available(bin_name: str) -> bool:
    return shutil.which(bin_name) is not None


def _platform() -> str:
    return platform.system().lower()  # darwin / windows / linux


# ── Sub-query implementations ─────────────────────────────────────────────────


def _active_window() -> str:
    """The focused application + window title, best-effort per platform."""
    sysname = _platform()
    if sysname == "darwin":
        # osascript needs Automation permission; degrade gracefully if denied.
        if not _is_available("osascript"):
            return "active_window unavailable: osascript not found"
        app = _run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to get name of first application process '
                'whose frontmost is true',
            ]
        )
        if not app:
            return (
                "active_window unavailable: macOS Automation permission not granted "
                "(System Settings → Privacy & Security → Automation)"
            )
        title = _run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to get name of front window of first application process '
                'whose frontmost is true',
            ]
        )
        return f"Active window: {app}" + (f" — {title}" if title and title != app else "")
    if sysname == "windows":
        # PowerShell: foreground window title via GetForegroundWindow P/Invoke.
        ps = (
            "Add-Type @'"
            "using System;using System.Runtime.InteropServices;"
            "public class W{"
            "[DllImport(\"user32.dll\")]public static extern IntPtr GetForegroundWindow();"
            "[DllImport(\"user32.dll\")]public static extern int GetWindowText(IntPtr h,StringBuilder s,int n);"
            "}"
            "'@;"
            "$h=[W]::GetForegroundWindow();$s=New-Object System.Text.StringBuilder 512;"
            "[void][W]::GetWindowText($h,$s,512);$s.ToString()"
        )
        title = _run(["powershell", "-NoProfile", "-Command", ps])
        # NOTE: the process name is deliberately NOT paired here — deriving it
        # from the foreground handle needs GetWindowThreadProcessId P/Invoke,
        # and a "top windowed process by title" heuristic pairs the WRONG app
        # with the right title. The GetForegroundWindow title is authoritative.
        return f"Active window: {title}" if title else "Active window: no visible window (desktop/shell)"
    if sysname == "linux":
        if _is_available("xdotool"):
            title = _run(["xdotool", "getactivewindow", "getwindowname"])
            return f"Active window: {title}" if title else "Active window: unknown (no focused window)"
        return "active_window unavailable: install xdotool for X11 active-window detection"
    return f"active_window unavailable on {platform.system()}"


def _clipboard() -> str:
    """Current clipboard text, best-effort per platform. Truncated hard."""
    sysname = _platform()
    if sysname == "darwin":
        if not _is_available("pbpaste"):
            return "clipboard unavailable: pbpaste not found"
        text = _run(["pbpaste"])
    elif sysname == "windows":
        text = _run(["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"])
    elif sysname == "linux":
        if _is_available("xclip"):
            text = _run(["xclip", "-selection", "clipboard", "-o"])
        elif _is_available("wl-paste"):
            text = _run(["wl-paste"])
        else:
            return "clipboard unavailable: install xclip (X11) or wl-clipboard (Wayland)"
    else:
        return f"clipboard unavailable on {platform.system()}"

    if not text:
        return "Clipboard: (empty)"
    if len(text) > 500:
        text = text[:500] + f"… [{len(text) - 500} more chars]"
    return f"Clipboard: {text}"


def _running_apps() -> str:
    """Top memory-consuming applications (processes with a name)."""
    try:
        import psutil
    except ImportError:
        return "running_apps unavailable: install psutil"
    try:
        procs = []
        for p in psutil.process_iter(["name", "memory_percent"]):
            try:
                name = p.info.get("name") or ""
                if not name:
                    continue
                # Skip kernel/system noise on Windows.
                if name.lower() in ("system idle process", "system"):
                    continue
                procs.append((p.info.get("memory_percent") or 0.0, name))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        procs.sort(reverse=True)
        top = procs[: _MAX_APPS]
        lines = [f"{name} ({mem:.1f}%)" for mem, name in top]
        return "Running apps (top by memory):\n- " + "\n- ".join(lines)
    except Exception as e:  # noqa: BLE001
        return f"running_apps error: {e}"


def _system_state() -> str:
    """CPU / RAM / disk / battery quick snapshot (psutil)."""
    try:
        import psutil
    except ImportError:
        return "system_state unavailable: install psutil"
    try:
        parts = []
        cpu = psutil.cpu_percent(interval=0.2)
        parts.append(f"CPU: {cpu:.0f}%")
        mem = psutil.virtual_memory()
        parts.append(f"RAM: {mem.percent:.0f}% used ({mem.used / 1e9:.1f}/{mem.total / 1e9:.1f} GB)")
        try:
            disk = psutil.disk_usage(os.path.expanduser("~"))
            parts.append(f"Disk(home): {disk.percent:.0f}% used ({disk.free / 1e9:.1f} GB free)")
        except OSError:
            pass
        try:
            bat = psutil.sensors_battery()
            if bat:
                parts.append(f"Battery: {bat.percent:.0f}%" + ("" if bat.power_plugged else " (on battery)"))
        except AttributeError:
            pass
        return "System state: " + " | ".join(parts)
    except Exception as e:  # noqa: BLE001
        return f"system_state error: {e}"


def _recent_files(query: str) -> str:
    """Files modified in the last N minutes under a directory (filesystem changes).

    Bounded by construction: max _MAX_RECENT_FILES results, depth cap, skips
    heavy dirs. Security: the walk root must pass settings.is_path_allowed
    (mirrors file_task / find_path) so "under C:\\" can't dump arbitrary
    filenames into context.
    """
    import re
    from pathlib import Path

    from core.config import settings

    root = os.getcwd()
    m = re.search(r"(?:under|in)\s+[\"']?([^\"'\s]+)", query, re.IGNORECASE)
    if m and os.path.isdir(m.group(1)):
        root = m.group(1)
    # is_path_allowed resolves the path — it needs a Path, not a str.
    if not settings.is_path_allowed(Path(root)):
        return f"recent_files: path not allowed: {root}"

    minutes = _RECENT_WINDOW_MINUTES
    m2 = re.search(r"last\s+(\d+)\s*minutes?", query, re.IGNORECASE)
    if m2:
        minutes = min(int(m2.group(1)), 24 * 60)  # cap at 24h
    cutoff = datetime.datetime.now().timestamp() - minutes * 60

    found: list[tuple[float, str]] = []
    heavy = {"node_modules", ".git", "__pycache__", ".venv", "venv", "build", "dist", ".cache"}
    max_depth = 6

    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath[len(root):].count(os.sep)
        if depth >= max_depth:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in heavy]
        try:
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                if st.st_mtime >= cutoff:
                    found.append((st.st_mtime, fp))
        except OSError:
            continue
        if len(found) >= _MAX_RECENT_FILES * 4:
            break  # don't walk forever

    found.sort(reverse=True)
    top = found[: _MAX_RECENT_FILES]
    if not top:
        return f"No files modified in the last {minutes} min under {root}"
    lines = [
        f"{datetime.datetime.fromtimestamp(mt).strftime('%H:%M')}  {fp}"
        for mt, fp in top
    ]
    return f"Recently modified (last {minutes} min, under {root}):\n" + "\n".join(lines)


# ── Dispatcher ────────────────────────────────────────────────────────────────


def _observe(query: str) -> str:
    import re

    q = query.lower()
    parts: list[str] = []

    # Word-boundary matching — "app" must NOT match inside "happening".
    def has(*words: str) -> bool:
        return any(re.search(rf"\b{w}\b", q) for w in words)
    wants_clipboard = has("clipboard")
    wants_apps = has("app", "apps", "program", "process", "processes", "running", "open")
    wants_state = has("cpu", "ram", "memory", "disk", "battery", "load", "state", "usage", "resource")
    wants_recent = has("recent", "modified", "changed", "filesystem")
    wants_window = has("window", "active", "focused", "frontmost", "foreground")

    # Default: window + apps + state (a compact "what's happening" summary).
    if not any([wants_clipboard, wants_apps, wants_state, wants_recent, wants_window]):
        wants_window = wants_apps = wants_state = True

    if wants_window:
        parts.append(_active_window())
    if wants_clipboard:
        parts.append(_clipboard())
    if wants_apps:
        parts.append(_running_apps())
    if wants_state:
        parts.append(_system_state())
    if wants_recent:
        parts.append(_recent_files(query))

    return "\n\n".join(parts)


async def observe(query: str) -> ToolResult:
    try:
        info = _observe(query)
        return ToolResult(
            content=info,
            risk=RiskLevel.LOW,
            source="observe",
            metadata={"offline": True},
        )
    except Exception as e:  # noqa: BLE001 — last-resort: never crash the loop
        logger.error("[observe] error: %s", e)
        return ToolResult(
            content=f"Observe error: {e}",
            risk=RiskLevel.LOW,
            source="observe",
        )


register_tool(
    Intent.OBSERVE,
    observe,
    description=(
        "Observe the desktop right now: active window, clipboard, running apps, "
        "CPU/RAM/disk/battery state, recently modified files. Offline, instant, bounded output."
    ),
    cost=0.0,
    latency_ms=150,
    parallelizable=True,
)
