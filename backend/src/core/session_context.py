"""
SessionContext — Persistent execution state for LocalMind.

Tracks per-session working directory (CWD), active project context,
recently accessed paths, and environment variable overrides across
tool calls. This is the missing state layer that prevents the agent
from forgetting where it is in the filesystem between turns.

Design Principles:
  1. Detection over declaration — automatically detect CWD changes
     from command output rather than requiring explicit cd commands.
  2. Conservative updates — only update CWD when there is high
     confidence that a directory change occurred.
  3. Graceful degradation — if the CWD becomes invalid, fall back
     to the user's home directory and emit a warning.
  4. Zero-friction integration — the session context is transparent
     to the user; it just works.

Integration Points:
  - Engine._session_contexts: dict[str, SessionContext]
  - tools/shell.py _run(cwd=session_cwd)
  - core/context_builder.py _build_environment_context(session_cwd=...)
  - core/engine.py _detect_cwd_change() after each tool dispatch
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Maximum number of recently accessed paths to retain
RECENT_PATHS_WINDOW = 10

# Maximum number of sessions before pruning old entries
MAX_SESSIONS = 200


@dataclass
class SessionContext:
    """Per-session execution context that persists across tool calls."""

    session_id: str
    cwd: str  # Absolute path, always validated to exist on disk
    active_project: Optional[str] = None  # Last project directory name
    recent_paths: list[str] = field(default_factory=list)  # Rolling window
    env_overrides: dict[str, str] = field(default_factory=dict)
    last_cd_command: Optional[str] = None  # Last cd command for recovery

    def update_cwd(self, new_cwd: str) -> bool:
        """
        Update the CWD to a new absolute path.

        Validates that the target directory exists before updating.
        If the target doesn't exist, returns False without changing state.

        Args:
            new_cwd: The new working directory (absolute or relative path).

        Returns:
            True if the CWD was updated, False if the target doesn't exist.
        """
        try:
            resolved = Path(new_cwd).expanduser().resolve()
            if resolved.is_dir():
                new_cwd_str = str(resolved)
                if new_cwd_str != self.cwd:
                    self.cwd = new_cwd_str
                    self._add_recent_path(new_cwd_str)
                    # Extract project name from the last directory component
                    self.active_project = resolved.name
                    logger.info(
                        f"[session_context] CWD updated for session "
                        f"{self.session_id[:8]}: {self.cwd} "
                        f"(project: {self.active_project})"
                    )
                return True
            else:
                logger.debug(
                    f"[session_context] CWD update rejected — "
                    f"not a directory: {resolved}"
                )
                return False
        except Exception as e:
            logger.warning(f"[session_context] CWD update error: {e}")
            return False

    def get_valid_cwd(self) -> str:
        """
        Return the CWD, falling back to home if the current CWD is invalid.

        This is the safe accessor that should be used before passing
        the CWD to subprocess.run(). It ensures the directory exists
        and is accessible.
        """
        if os.path.isdir(self.cwd):
            return self.cwd

        # Current CWD is invalid — try recent paths in reverse order
        for path in reversed(self.recent_paths):
            if os.path.isdir(path):
                logger.warning(
                    f"[session_context] CWD {self.cwd} no longer exists, "
                    f"falling back to recent path: {path}"
                )
                self.cwd = path
                return self.cwd

        # No valid recent path — fall back to home
        home = str(Path.home())
        logger.warning(
            f"[session_context] CWD {self.cwd} no longer exists, "
            f"falling back to home: {home}"
        )
        self.cwd = home
        return self.cwd

    def _add_recent_path(self, path: str) -> None:
        """Add a path to the rolling window of recently accessed paths."""
        if path in self.recent_paths:
            self.recent_paths.remove(path)
        self.recent_paths.append(path)
        # Keep only the last N paths
        if len(self.recent_paths) > RECENT_PATHS_WINDOW:
            self.recent_paths = self.recent_paths[-RECENT_PATHS_WINDOW:]

    def sync_from_terminal(self, terminal_cwd: str) -> None:
        """
        Synchronize CWD from the terminal session.

        Called at the start of each agent turn to pick up manual
        cd commands the user ran in the terminal UI.
        """
        if terminal_cwd and terminal_cwd != self.cwd:
            self.update_cwd(terminal_cwd)


class SessionContextManager:
    """
    Manages per-session execution contexts.

    Creates SessionContext instances lazily, prunes old sessions,
    and provides the CWD detection logic that updates context from
    tool output.
    """

    def __init__(self):
        self._contexts: dict[str, SessionContext] = {}

    def get_context(self, session_id: str) -> SessionContext:
        """
        Get or create a SessionContext for the given session.

        Creates a new context with the user's home directory as CWD
        if one doesn't exist yet.
        """
        # Prune old sessions if the registry is too large
        if len(self._contexts) > MAX_SESSIONS:
            self._prune_sessions()

        if session_id not in self._contexts:
            self._contexts[session_id] = SessionContext(
                session_id=session_id,
                cwd=str(Path.home()),
            )
            logger.debug(
                f"[session_context] Created new context for session "
                f"{session_id[:8]}, CWD={Path.home()}"
            )
        return self._contexts[session_id]

    def get_cwd(self, session_id: str) -> str:
        """Get the validated CWD for a session (convenience method)."""
        return self.get_context(session_id).get_valid_cwd()

    def update_cwd(self, session_id: str, new_cwd: str) -> bool:
        """Update the CWD for a session (convenience method)."""
        return self.get_context(session_id).update_cwd(new_cwd)

    def _prune_sessions(self) -> None:
        """Remove the oldest session contexts to prevent unbounded growth."""
        oldest = sorted(self._contexts.keys())[
            : len(self._contexts) - MAX_SESSIONS // 2
        ]
        for sid in oldest:
            del self._contexts[sid]
        logger.debug(
            f"[session_context] Pruned {len(oldest)} old sessions"
        )

    # ── CWD Detection from Tool Output ────────────────────────────
    #
    # These methods examine tool command strings and output to detect
    # when the working directory has changed. They are called after
    # each tool dispatch in the Engine.

    @staticmethod
    def detect_cwd_change(
        session_cwd: str,
        command: Optional[str],
        tool_result_content: str,
    ) -> Optional[str]:
        """
        Detect a CWD change from a shell command and its output.

        Examines three sources:
          1. Explicit cd/pushd commands
          2. Windows "Directory of" pattern in output
          3. Path header in list_files output

        Args:
            session_cwd: The current session CWD (for resolving relative paths).
            command: The shell command that was executed (if available).
            tool_result_content: The text content of the tool result.

        Returns:
            The new CWD if a change was detected, or None.
        """
        if not tool_result_content:
            return None

        # ── Case 1: Explicit cd command ────────────────────────────
        if command:
            cd_match = re.match(
                r"^cd\s+(.+)", command.strip(), re.IGNORECASE
            )
            if cd_match:
                target = cd_match.group(1).strip().strip('"').strip("'")
                resolved = _resolve_path(target, session_cwd)
                if resolved and resolved.is_dir():
                    return str(resolved)

            # pushd command
            pushd_match = re.match(
                r"^pushd\s+(.+)", command.strip(), re.IGNORECASE
            )
            if pushd_match:
                target = pushd_match.group(1).strip().strip('"').strip("'")
                resolved = _resolve_path(target, session_cwd)
                if resolved and resolved.is_dir():
                    return str(resolved)

        # ── Case 2: Windows "Directory of" pattern ─────────────────
        dir_match = re.search(
            r"Directory of\s+([A-Za-z]:[\\/][^\r\n]+)",
            tool_result_content,
        )
        if dir_match:
            path_str = dir_match.group(1).strip()
            path = Path(path_str)
            if path.is_dir():
                return str(path.resolve())

        # ── Case 3: Path header in list_files output ───────────────
        # Matches patterns like "📁  C:\Users\..." or "📁  /home/user/..."
        path_header_match = re.search(
            r"\U0001F4C1\s+([A-Za-z]:[\\/][^\s]+|/?[\w./\\-]+)",
            tool_result_content,
        )
        if path_header_match:
            path_str = path_header_match.group(1).strip()
            path = Path(path_str).expanduser().resolve()
            if path.is_dir():
                return str(path)

        # ── Case 4: Unix-style path in ls output ───────────────────
        # Matches lines like "total 24" followed by path-like entries
        unix_path_match = re.search(
            r"(?:^|\n)([/~]?[\w./-]+/):\n",
            tool_result_content,
        )
        if unix_path_match:
            path_str = unix_path_match.group(1).strip()
            path = Path(path_str).expanduser().resolve()
            if path.is_dir():
                return str(path)

        return None


def _resolve_path(target: str, current_cwd: str) -> Optional[Path]:
    r"""
    Resolve a path target relative to the current CWD.

    Handles:
      - Absolute paths (C:\... or /...)
      - Relative paths (resolved against current_cwd)
      - Home-relative paths (~/...)
      - Parent directory references (..)

    Returns None if the resolved path doesn't exist.
    """
    try:
        # Expand ~ first
        expanded = Path(target).expanduser()

        if expanded.is_absolute():
            resolved = expanded.resolve()
        else:
            # Resolve relative to the current session CWD
            resolved = (Path(current_cwd) / expanded).resolve()

        return resolved if resolved.exists() else None
    except Exception:
        return None
