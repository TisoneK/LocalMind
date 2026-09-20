"""Where `pip install` puts things: LocalMind's own folder, or the system Python.

An agent that runs `pip install Pillow` on the user's machine changes the user's Python, which is
not something to do silently ("Defaulting to user installation because normal site-packages is not
writeable" was the symptom). So installs go to a folder LocalMind owns by default, and the user can
choose the system Python instead in Settings.

The "LocalMind" mode is a `--target` directory added to `PYTHONPATH` for every command and code run
LocalMind starts, so anything installed there imports normally without a virtualenv, and removing
the folder undoes it.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

MODES = ("localmind", "system")

# `pip install`, `pip3 install`, `python -m pip install`, `py -m pip install`.
_PIP_INSTALL_RE = re.compile(r"(\bpip3?\s+install\b|-m\s+pip\s+install\b)", re.IGNORECASE)
# An install that already says where it goes is left alone.
_HAS_DESTINATION_RE = re.compile(r"(?:^|\s)(?:--target|-t|--user|--prefix|--root|--dry-run)\b", re.IGNORECASE)


def mode() -> str:
    from core.config import settings

    value = str(getattr(settings, "localmind_package_env", "localmind") or "localmind").lower()
    return value if value in MODES else "localmind"


def packages_dir() -> Path:
    from core.config import settings

    return Path(settings.localmind_home).expanduser() / "packages"


def rewrite_install(command: str) -> str:
    """Send `pip install` to LocalMind's packages folder, unless the user chose the system Python.

    Only the install verb is touched, wherever it sits in a compound command.
    """
    if mode() != "localmind" or not isinstance(command, str) or not _PIP_INSTALL_RE.search(command):
        return command
    if _HAS_DESTINATION_RE.search(command):
        return command
    target = str(packages_dir())
    quoted = f'"{target}"' if (" " in target or os.name == "nt") else target
    return _PIP_INSTALL_RE.sub(lambda m: f"{m.group(1)} --target {quoted}", command, count=1)


def apply_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """`env` (or a copy of the process environment) with the packages folder on PYTHONPATH."""
    out = dict(os.environ if env is None else env)
    if mode() == "localmind":
        folder = str(packages_dir())
        existing = out.get("PYTHONPATH", "")
        parts = [p for p in existing.split(os.pathsep) if p]
        if folder not in parts:
            out["PYTHONPATH"] = os.pathsep.join([folder, *parts])
    return out
