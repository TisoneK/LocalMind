"""
Debugger agent context builder.

Gathers debug-specific context before each turn:
    - The debugger playbook (isolate, trace, reproduce, report)
    - Memory facts (passed in by the caller)
    - Orchestrator plan (passed in by the caller)

Per ADR-6: each agent supplies its own build_context(). The debugger's
context primes the model to think like a debugger — tracing failures
through code, isolating root causes, and reproducing errors — not
building or testing.

The workspace_state snapshot (git status/diff/build result) is injected
by AgentLoop.run() per Session 16. For the debugger, git diff and log
are essential — they show what changed that might have introduced the bug.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from core.models import Intent

logger = logging.getLogger(__name__)

_PLAYBOOK_PATH = Path(__file__).resolve().parent / "playbook.md"


def _load_playbook() -> str:
    try:
        if not _PLAYBOOK_PATH.exists():
            logger.warning("[debugger.context_builder] playbook file missing at %s", _PLAYBOOK_PATH)
            return ""
        return _PLAYBOOK_PATH.read_text()
    except Exception as exc:
        logger.warning("[debugger.context_builder] failed to read playbook: %s", exc)
        return ""


def build_debugger_context(
    messages: list[dict],
    intent: Intent,
    memory_facts: Optional[list[str]] = None,
    orchestrator_context: Optional[str] = None,
) -> str:
    playbook_md = _load_playbook()

    lines: list[str] = []

    if playbook_md:
        playbook_lines = playbook_md.splitlines()
        while playbook_lines and (playbook_lines[0].startswith("# ") or not playbook_lines[0].strip()):
            playbook_lines.pop(0)
        lines.append("## Debugger Playbook")
        lines.append("")
        lines.extend(playbook_lines)
        lines.append("")
    else:
        lines.extend([
            "## Debugger Agent",
            "",
            "You are running as the Debugger Agent. Your tool surface is",
            "scoped to diagnostic tools — file_task (read logs/source),",
            "git (check changes), shell (inspect state), process (manage",
            "services).",
            "Your job is to FIND root causes of failures — not to fix them.",
            "",
            "Debugging pattern:",
            "1. Capture the error message or symptom",
            "2. Read the relevant source files and error logs",
            "3. Check git diff/log for recent changes",
            "4. Reproduce the failure (start services if needed)",
            "5. Isolate the root cause (specific line, commit, or condition)",
            "6. Report: root cause + suggested fix direction",
            "7. Delegate the fix to the coding agent — don't edit code yourself",
            "",
        ])

    lines.extend([
        "The workspace state (git status, diff since last turn) is",
        "injected into your context every turn — use it to identify",
        "what changed and narrow down the root cause.",
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
