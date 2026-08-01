"""
Coding agent context builder.

Gathers coding-specific context before each turn:
    - The coding playbook (read-before-write, verify-after-write,
      use-workspace-state, follow-conventions, small-verifiable-changes)
      loaded from agents/coding/playbook.md
    - Memory facts (passed in by the caller)
    - Orchestrator plan (passed in by the caller)

Per ADR-6: each agent supplies its own build_context(). The coding
agent's context is codebase-centric, unlike the browser agent (page-
state-centric) or the research agent (source-tracking-centric).

Per ADR-8 Phase 2 (Session 34): this function ACTUALLY loads the
playbook file. Phase 1 returned a static header; Phase 2 makes the
playbook load-bearing — the file's contents reach the model's system
prompt via the `agent_context` parameter of
`build_agent_system_prompt()`. This is the "the playbook is the value"
piece of ADR-8 Principle 4.

The workspace_state snapshot (git status/diff/build result) is injected
by AgentLoop.run() per Session 16 — this context_builder does NOT
duplicate it. This keeps the context concise for the gemma3:1b-class
target hardware.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from core.models import Intent

logger = logging.getLogger(__name__)

# Path to the coding playbook file. Per ADR-8 Phase 2 (Session 34),
# the playbook file moved from backend/data/playbooks/coding.md to
# agents/coding/playbook.md — co-located with the agent class. The
# path is resolved relative to this file so it works regardless of
# the process CWD.
_PLAYBOOK_PATH = Path(__file__).resolve().parent / "playbook.md"


def _load_playbook() -> str:
    """Load the coding playbook markdown file.

    Returns an empty string if the file is missing or unreadable
    (best-effort — the playbook is guidance, not a hard requirement).
    Logs a warning on failure so the regression is visible.
    """
    try:
        if not _PLAYBOOK_PATH.exists():
            logger.warning(
                "[coding.context_builder] playbook file missing at %s — "
                "Phase 2 playbook injection will be empty",
                _PLAYBOOK_PATH,
            )
            return ""
        return _PLAYBOOK_PATH.read_text()
    except Exception as exc:
        logger.warning(
            "[coding.context_builder] failed to read playbook file %s: %s",
            _PLAYBOOK_PATH, exc,
        )
        return ""


def build_coding_context(
    messages: list[dict],
    intent: Intent,
    memory_facts: Optional[list[str]] = None,
    orchestrator_context: Optional[str] = None,
) -> str:
    """
    Build the coding-agent context string.

    Phase 2 (ADR-8, Session 34): loads the coding playbook file
    (agents/coding/playbook.md) and returns it as the agent_context
    section. The playbook contains the constraints:
        1. Read before writing
        2. Verify after writing
        3. Use the workspace state (git status/diff injected every turn)
        4. Follow existing conventions
        5. Small, verifiable changes

    These constraints previously sat on disk UNUSED (per Session 33
    finding); now they reach the model's system prompt when the
    CodingAgent is selected for SHELL/FILE_*/CODE_EXEC intents.

    The workspace_state snapshot (git status/diff/build result) is
    already injected by AgentLoop.run() per Session 16 — this
    context_builder does NOT duplicate it. This keeps the context
    concise for the gemma3:1b-class target hardware.
    """
    playbook_md = _load_playbook()

    lines: list[str] = []

    if playbook_md:
        # Strip the H1 header line (it duplicates the AGENT CONTEXT section
        # header that build_agent_system_prompt() adds). Keep the rest.
        playbook_lines = playbook_md.splitlines()
        # Drop the first "# Playbook: Coding ..." line and any leading blank lines
        while playbook_lines and (
            playbook_lines[0].startswith("# ") or not playbook_lines[0].strip()
        ):
            playbook_lines.pop(0)
        lines.append("## Coding Playbook")
        lines.append("")
        lines.extend(playbook_lines)
        lines.append("")
    else:
        # Fallback: the static header from Phase 1, so the prompt isn't
        # empty if the playbook file is missing.
        lines.extend([
            "## Coding Agent",
            "",
            "You are running as the Coding Agent. Your tool surface is",
            "scoped to coding tools only — shell, file read/write/edit, and",
            "code execution. You cannot search the web, drive a browser, or",
            "manage memory. Use the shell tool for terminal commands, the",
            "file tools for reading and editing files, and the code_exec",
            "tool for running code.",
            "",
        ])

    lines.extend([
        "The workspace state (git status, diff since last turn, last",
        "build/test result) is injected into your context every turn —",
        "use it to verify your changes and catch errors.",
        "",
    ])

    if memory_facts:
        lines.append("## Relevant Memory")
        lines.append("")
        for fact in memory_facts[:10]:  # cap to avoid context bloat
            lines.append(f"- {fact}")
        lines.append("")

    if orchestrator_context:
        lines.append("## Orchestrator Plan")
        lines.append("")
        lines.append(orchestrator_context)
        lines.append("")

    return "\n".join(lines)
