"""
Verifier agent context builder.

Gathers verification-specific context before each turn:
    - The verifier playbook (systematic checking, isolate failures,
      use git/process tools, report clearly)
    - Memory facts (passed in by the caller)
    - Orchestrator plan (passed in by the caller)

Each agent supplies its own build_context(). The verifier's
context is verification-centric — it primes the model to think like a
tester, not a builder.

The workspace_state snapshot (git status/diff/build result) is injected
by AgentLoop.run() — this context_builder does NOT
duplicate it. For the verifier, workspace state is especially important:
it shows what changed since the last turn, which is the primary
diagnostic tool for understanding test failures.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from core.models import Intent

logger = logging.getLogger(__name__)

# Path to the verifier playbook file. The playbook
# is co-located with the agent class.
_PLAYBOOK_PATH = Path(__file__).resolve().parent / "playbook.md"


def _load_playbook() -> str:
    """Load the verifier playbook markdown file.

    Returns an empty string if the file is missing or unreadable
    (best-effort — the playbook is guidance, not a hard requirement).
    """
    try:
        if not _PLAYBOOK_PATH.exists():
            logger.warning(
                "[verifier.context_builder] playbook file missing at %s",
                _PLAYBOOK_PATH,
            )
            return ""
        return _PLAYBOOK_PATH.read_text()
    except Exception as exc:
        logger.warning(
            "[verifier.context_builder] failed to read playbook file %s: %s",
            _PLAYBOOK_PATH, exc,
        )
        return ""


def build_verifier_context(
    messages: list[dict],
    intent: Intent,
    memory_facts: Optional[list[str]] = None,
    orchestrator_context: Optional[str] = None,
) -> str:
    """
    Build the verifier-agent context string.

    Loads the verifier playbook file (agents/verifier/playbook.md) and
    returns it as the agent_context section. The playbook contains the
    constraints: read before verifying, isolate failures, use git/process
    tools, report clearly.

    The workspace_state snapshot (git status/diff/build result) is
    already injected by AgentLoop.run() — this
    context_builder does NOT duplicate it.
    """
    playbook_md = _load_playbook()

    lines: list[str] = []

    if playbook_md:
        playbook_lines = playbook_md.splitlines()
        # Drop the H1 header line and any leading blank lines
        while playbook_lines and (
            playbook_lines[0].startswith("# ") or not playbook_lines[0].strip()
        ):
            playbook_lines.pop(0)
        lines.append("## Verifier Playbook")
        lines.append("")
        lines.extend(playbook_lines)
        lines.append("")
    else:
        lines.extend([
            "## Verifier Agent",
            "",
            "You are running as the Verifier Agent. Your tool surface is",
            "scoped to verification tools — shell (run tests/commands),",
            "process (manage services), git (check changes), file_task",
            "(read files), and edit_file (targeted bug fixes only).",
            "Your job is to PROVE things work or FIND what's broken —",
            "not to build new features.",
            "",
            "Systematic verification pattern:",
            "1. Read the relevant files (tests, source, config)",
            "2. Check git status/diff for recent changes",
            "3. Start any required services (process tool)",
            "4. Run the verification commands",
            "5. Report results clearly (passed/failed/skipped + root cause)",
            "",
        ])

    lines.extend([
        "The workspace state (git status, diff since last turn, last",
        "build/test result) is injected into your context every turn —",
        "use it to understand what changed and diagnose failures.",
        "",
    ])

    if memory_facts:
        lines.append("## Relevant Memory")
        lines.append("")
        for fact in memory_facts[:10]:
            lines.append(f"- {fact}")
        lines.append("")

    if orchestrator_context:
        lines.append("## Orchestrator Plan")
        lines.append("")
        lines.append(orchestrator_context)
        lines.append("")

    return "\n".join(lines)
