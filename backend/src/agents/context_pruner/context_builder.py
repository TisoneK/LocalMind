"""
Context pruner agent context builder.

Loads the pruner playbook (agents/context_pruner/playbook.md) into the
agent_context. The pruner's run() override performs the rewrite via a
direct model call, so the playbook is a secondary reference — it is kept
for consistency with the ADR-8 Phase 2 pattern (every agent directory
owns its playbook) and for future reuse if the pruner ever gains tools.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from core.models import Intent

logger = logging.getLogger(__name__)

_PLAYBOOK_PATH = Path(__file__).resolve().parent / "playbook.md"


def _load_playbook() -> str:
    """Load the pruner playbook markdown file (best-effort)."""
    try:
        if not _PLAYBOOK_PATH.exists():
            logger.warning(
                "[context_pruner.context_builder] playbook missing at %s",
                _PLAYBOOK_PATH,
            )
            return ""
        return _PLAYBOOK_PATH.read_text()
    except Exception as exc:
        logger.warning(
            "[context_pruner.context_builder] failed to read playbook %s: %s",
            _PLAYBOOK_PATH, exc,
        )
        return ""


def build_context_pruner_context(
    messages: list[dict],
    intent: Intent,
    memory_facts: Optional[list[str]] = None,
    orchestrator_context: Optional[str] = None,
) -> str:
    """Build the context-pruner agent context string (the playbook)."""
    playbook_md = _load_playbook()
    lines: list[str] = []
    if playbook_md:
        playbook_lines = playbook_md.splitlines()
        while playbook_lines and (
            playbook_lines[0].startswith("# ") or not playbook_lines[0].strip()
        ):
            playbook_lines.pop(0)
        lines.append("## Context Pruner")
        lines.append("")
        lines.extend(playbook_lines)
        lines.append("")
    else:
        lines.extend([
            "## Context Pruner",
            "",
            "You rewrite an agent conversation history to be smaller and",
            "tighter. Preserve the system message and the user's latest",
            "message verbatim; summarize older turns and tool results;",
            "never change tool_call ids; output ONLY a JSON array of",
            "message objects.",
            "",
        ])
    return "\n".join(lines)
