"""
Safety Gate -- hard-block filter + destructive operation guardrails for LocalMind.

Two layers:
1. HARD BLOCKS: Content that is unambiguously harmful regardless of context.
   These are blocked before the message reaches any tool or LLM.

2. DESTRUCTIVE OPERATION DETECTION: Identifies shell/file commands that could
   cause data loss or system damage. These are NOT blocked — they're flagged
   so the engine can insert confirmation gates before execution.

Vocabulary-level keyword matching produces too many false positives to be
useful -- "crack a walnut", "drug policy", "kill the process" would all be
blocked by a broad blocklist. Keep the hard-block layer extremely tight.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

# ── Layer 1: Hard blocks ─────────────────────────────────────────────────────
# Only patterns that are harmful in every possible context.
# Do NOT add general vocabulary like "hack", "drug", "kill", "steal" --
# those are common English words with many legitimate uses.
_HARD_BLOCKS: list[tuple[str, str]] = [
    (r"\b(csam|child pornography|child sexual abuse material)\b", "CSAM content"),
    (r"\b(make a bomb|build a bomb|synthesize\s+\w+\s+explosive)\b", "explosive synthesis"),
    (r"\b(bioweapon synthesis|nerve agent synthesis|sarin production)\b", "WMD content"),
]


_POLITE_BLOCK = (
    "I'm sorry, I'm not able to help with that request. "
    "If there's something else I can assist you with, I'd be happy to help."
)


def check(message: str) -> Tuple[bool, str, str]:
    """
    Hard-block check for incoming messages.

    Returns:
        (is_safe, user_message, debug_label) -- True if safe, False with a
        polite user-facing message and a debug label for observability.

    Only blocks content that is harmful in every conceivable context.
    Rely on the LLM's own safety training for everything else.
    """
    if not message or not message.strip():
        return False, _POLITE_BLOCK, "Empty message"

    message_lower = message.lower()
    for pattern, label in _HARD_BLOCKS:
        if re.search(pattern, message_lower, re.IGNORECASE):
            return False, _POLITE_BLOCK, label

    return True, "", ""


# ── Layer 2: Destructive operation detection ─────────────────────────────────
# These patterns identify commands that could cause data loss or system damage.
# They are NOT blocked — they're flagged so the engine can require confirmation.

_DESTRUCTIVE_SHELL_PATTERNS: list[tuple[str, str]] = [
    # File deletion
    (r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+|--force\s+).+", "Force file deletion"),
    (r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*\s+.+", "Recursive file deletion"),
    (r"\brmdir\s+", "Directory deletion"),
    (r"\bdel\s+/[sqa]+\s+", "Windows recursive file deletion"),
    (r"\brd\s+/[sqa]+\s+", "Windows directory deletion"),
    # Overwrite/move
    (r"\bmv\s+.+\s+.+", "File move/rename (may overwrite destination)"),
    (r"\bcp\s+.+\s+.+", "File copy (may overwrite destination)"),
    (r"\bcopy\s+.+\s+.+", "Windows file copy (may overwrite)"),
    (r"\bmove\s+.+\s+.+", "Windows file move (may overwrite)"),
    # System modification
    (r"\bsudo\s+rm\b", "Privileged file deletion"),
    (r"\bsudo\s+apt(\s+|-)get\s+remove\b", "Package removal"),
    (r"\bsudo\s+pip\s+uninstall\b", "Python package removal"),
    (r"\bsudo\s+systemctl\s+(stop|disable|restart)\b", "Service management"),
    (r"\bformat\s+[a-zA-Z]:", "Drive formatting"),
    # Database operations
    (r"\bDROP\s+(TABLE|DATABASE|SCHEMA)\b", "Database object deletion"),
    (r"\bTRUNCATE\s+", "Table truncation"),
    # Network
    (r"\bshutdown\b", "System shutdown"),
    (r"\breboot\b", "System reboot"),
    (r"\bpoweroff\b", "System power off"),
]

_DESTRUCTIVE_FILE_PATTERNS: list[tuple[str, str]] = [
    # Overwriting existing files
    (r"\b(overwrite|replace|clobber)\b", "File overwrite"),
]


def is_destructive_shell_command(command: str) -> Tuple[bool, Optional[str]]:
    """
    Check if a shell command appears to be destructive.

    Returns:
        (is_destructive, reason) -- True if the command matches a destructive
        pattern, with a human-readable reason. False if the command appears safe.

    This is a heuristic — it catches common destructive patterns but cannot
    catch all possible destructive commands. Use it as a confirmation gate,
    not a security boundary.
    """
    if not command or not command.strip():
        return False, None

    command_lower = command.lower().strip()

    for pattern, label in _DESTRUCTIVE_SHELL_PATTERNS:
        if re.search(pattern, command_lower, re.IGNORECASE):
            return True, label

    return False, None


def is_destructive_file_op(path: str, action: str) -> Tuple[bool, Optional[str]]:
    """
    Check if a file operation appears to be destructive.

    Args:
        path: The target file path.
        action: The operation being performed (replace, overwrite, etc.)

    Returns:
        (is_destructive, reason) -- True if the operation matches a destructive
        pattern, with a human-readable reason.
    """
    if not action:
        return False, None

    action_lower = action.lower()
    for pattern, label in _DESTRUCTIVE_FILE_PATTERNS:
        if re.search(pattern, action_lower, re.IGNORECASE):
            return True, label

    return False, None
