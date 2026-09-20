"""Which shell LocalMind runs commands in (terminal panel and the agent's shell tool).

"auto" keeps the platform default (cmd.exe/PowerShell heuristics on Windows, /bin/sh elsewhere).
Choosing one makes every command run there, so the agent and the terminal agree with the user's
habits: PowerShell, Command Prompt or Git Bash on Windows; bash, zsh, fish or sh elsewhere.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

AUTO = "auto"


@dataclass(frozen=True)
class ShellChoice:
    id: str
    label: str
    path: str  # "" when not found
    available: bool

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "path": self.path, "available": self.available}


def _git_bash_path() -> str:
    """Git for Windows' bash.exe: on PATH, next to git.exe, or in the standard install folders."""
    found = shutil.which("bash")
    # WSL's bash.exe lives in System32 and is a different thing; skip it.
    if found and "system32" not in found.lower():
        return found
    git = shutil.which("git")
    candidates = []
    if git:
        root = Path(git).resolve().parent.parent  # <Git>/cmd/git.exe or <Git>/bin/git.exe
        candidates += [root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"]
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidates.append(Path(base) / "Git" / "bin" / "bash.exe")
            candidates.append(Path(base) / "Programs" / "Git" / "bin" / "bash.exe")
    for c in candidates:
        if c.is_file():
            return str(c)
    return ""


def detect_shells(platform: str | None = None) -> list[ShellChoice]:
    """The shells worth offering on this machine, with whether each is installed."""
    plat = platform or sys.platform
    which = shutil.which
    if plat.startswith("win"):
        pwsh = which("pwsh") or ""
        winps = which("powershell") or ""
        comspec = os.environ.get("COMSPEC") or which("cmd") or ""
        git_bash = _git_bash_path()
        return [
            ShellChoice("powershell", "PowerShell", pwsh or winps, bool(pwsh or winps)),
            ShellChoice("cmd", "Command Prompt (cmd)", comspec, bool(comspec)),
            ShellChoice("git-bash", "Git Bash", git_bash, bool(git_bash)),
        ]
    out = []
    for sid, label in (("bash", "bash"), ("zsh", "zsh"), ("fish", "fish"), ("sh", "sh")):
        path = which(sid) or ""
        out.append(ShellChoice(sid, label, path, bool(path)))
    return out


def configured() -> str:
    from core.config import settings

    return str(getattr(settings, "localmind_shell", AUTO) or AUTO).lower()


def resolve(shell_id: str | None = None, platform: str | None = None) -> ShellChoice | None:
    """The chosen shell if it is installed here, else None (meaning: use the platform default)."""
    sid = (shell_id or configured()).lower()
    if sid == AUTO:
        return None
    for choice in detect_shells(platform):
        if choice.id == sid and choice.available:
            return choice
    return None


def exec_args(command: str, choice: ShellChoice) -> list[str]:
    """argv that runs `command` in `choice` (no shell=True needed)."""
    if choice.id == "powershell":
        return [choice.path, "-NoProfile", "-NonInteractive", "-Command", command]
    if choice.id == "cmd":
        return [choice.path, "/d", "/s", "/c", command]
    return [choice.path, "-c", command]


def note() -> str:
    """One line for the agent's context when a shell was chosen explicitly; empty on "auto"."""
    choice = resolve()
    if choice is None:
        return ""
    return f"Shell: {choice.label} — write commands in this shell's syntax."
