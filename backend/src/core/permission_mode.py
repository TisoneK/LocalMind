"""
Permission modes — the named file-effect surface for a session.

Three named modes decide, before a tool can cause a file effect, what classes
of effect the session permits. The mode is *pinned per session* and durable
(``storage.db`` persists it, so it survives a backend restart and never crosses
into another session), and it is resolved and enforced at exactly one seam:
``core.agent.tool_dispatch.dispatch_with_retry``, the same place the coarse
global ``settings.localmind_permissions`` toggles are already checked.

    read_only        — no file effects at all. Reads, searches, web and chat
                       still run; a write / edit / shell / code-exec intent is
                       denied before its body can touch anything.
    workspace_write  — the shipped default. Effecting intents run, but file
                       writes stay inside the allowed workspace folders (the
                       existing ``settings.is_path_allowed`` boundary).
    full             — full access; the workspace path boundary is lifted.

Two guarantees this module carries beyond the enum:

  * **Fail closed.** Resolving a mode that is missing, unknown, or raised while
    being read collapses to the most restrictive answer — a *denial* labelled
    ``fail_closed`` — never to "allow". An approval surface that fails open is
    worse than one that is absent, because it looks like a guarantee.
  * **The decision is pure.** ``decide()`` takes the mode and the intent and
    returns a verdict with its reason; it reads no global state and causes no
    effect, so it is trivially testable and the same inputs always yield the
    same verdict. Persistence, auditing and journalling live in ``storage.db``;
    enforcement lives at the dispatch seam.

Nothing here is ever injected into a prompt: the model is told which tools it
may call (the existing tool-filtering surface), never which permission mode is
in force or that a decision was audited.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.models import Intent


class FileEffectMode(str, Enum):
    """The three named file-effect modes, lowest capability first."""

    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    FULL = "full"


# The shipped default — effecting intents run, writes stay workspace-scoped.
DEFAULT_MODE = FileEffectMode.WORKSPACE_WRITE


# Intents whose body can cause a file effect (write/edit/execute). A mode gates
# exactly these; every other intent (reads, search, web, memory, sysinfo, chat)
# is always allowed by the mode and governed by its own existing guards.
FILE_EFFECTING_INTENTS: frozenset[Intent] = frozenset(
    {
        Intent.FILE_WRITE,
        Intent.FILE_EDIT,
        Intent.APPLY_PROPOSED,  # writes a staged proposal to disk
        Intent.SHELL,
        Intent.CODE_EXEC,
    }
)
# Known effect-capable intents whose effect depends on the sub-command
# (git commit vs status, process start vs logs, a browser click vs a read) are
# NOT gated by mode yet — mixing read and effect in one intent needs
# sub-command classification. Tracked as a follow-up (parking lot); for now the
# five unambiguous effecting intents above are the mode boundary.


def coerce_mode(value: object) -> FileEffectMode | None:
    """Return the ``FileEffectMode`` for ``value``, or ``None`` if it is not a
    recognised mode. ``None`` input (never pinned) is distinguished from a
    malformed value by the caller: ``resolve_mode`` maps missing → default,
    while an unrecognised string is treated as a fault and fails closed."""
    if isinstance(value, FileEffectMode):
        return value
    if isinstance(value, str):
        try:
            return FileEffectMode(value.strip().lower())
        except ValueError:
            return None
    return None


def is_file_effecting(intent: Intent) -> bool:
    """True when ``intent``'s body can cause a file effect that a mode gates."""
    return intent in FILE_EFFECTING_INTENTS


@dataclass(frozen=True)
class PermissionDecision:
    """The verdict for one (mode, intent) pair.

    ``allowed`` is the only thing enforcement acts on; ``reason`` is the audit
    line; ``mode`` is the mode that produced the verdict (``None`` when the mode
    itself could not be resolved); ``fail_closed`` marks a denial that came from
    a fault (missing/unknown mode or a raised read) rather than from the mode's
    normal policy.
    """

    allowed: bool
    reason: str
    intent: Intent
    mode: FileEffectMode | None
    fail_closed: bool = False

    @property
    def decision(self) -> str:
        """``"allow"`` / ``"deny"`` — the audit-column form."""
        return "allow" if self.allowed else "deny"


def deny_fail_closed(intent: Intent, reason: str) -> PermissionDecision:
    """A denial produced by a fault, not by policy — the fail-closed path."""
    return PermissionDecision(
        allowed=False,
        reason=reason,
        intent=intent,
        mode=None,
        fail_closed=True,
    )


def decide(mode: FileEffectMode | None, intent: Intent) -> PermissionDecision:
    """Decide whether ``intent`` may run under ``mode`` — pure, no I/O.

    ``mode is None`` means the mode could not be resolved at all; that is a
    fault, so an *effecting* intent fails closed. (A non-effecting intent is
    allowed regardless of mode: a read was never a file effect.) The workspace
    path boundary for ``workspace_write`` is enforced separately, at the file
    writer's own path check — this seam decides the effect class only.
    """
    if not is_file_effecting(intent):
        return PermissionDecision(
            allowed=True,
            reason="not a file-effecting intent",
            intent=intent,
            mode=mode,
        )

    if mode is None:
        return deny_fail_closed(
            intent, "permission mode unavailable — denied (fail-closed)"
        )

    if mode is FileEffectMode.READ_ONLY:
        return PermissionDecision(
            allowed=False,
            reason="read-only mode — file effects are not permitted",
            intent=intent,
            mode=mode,
        )

    # WORKSPACE_WRITE and FULL both permit the effect class here; the
    # workspace↔full distinction is the write path boundary, enforced by the
    # writer via ``write_path_allowed`` below.
    return PermissionDecision(
        allowed=True,
        reason=f"{mode.value} mode permits {intent.value}",
        intent=intent,
        mode=mode,
    )


def write_path_allowed(mode: FileEffectMode | None, path, settings) -> bool:
    """The write path boundary, mode-aware.

    ``full`` lifts the workspace boundary (writes anywhere the OS permits);
    every other mode — including an unresolved one — keeps the existing
    ``settings.is_path_allowed`` folder boundary. Keeping the default and the
    fault case on the *restrictive* side preserves the fail-closed posture:
    only an explicit ``full`` pin widens the boundary.
    """
    if mode is FileEffectMode.FULL:
        return True
    try:
        return bool(settings.is_path_allowed(path))
    except Exception:
        return False
