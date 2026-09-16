"""
Editor selector agent context builder.

Loads the selector playbook (agents/editor_selector/playbook.md) into the
agent_context so the selector knows HOW to pick: judge against the
instruction, prefer the strategy that best serves the goal, prefer smaller
diffs when the instruction doesn't demand more, and return the exact JSON
contract {choice, reason, suggested_improvements}.

The playbook file is load-bearing — it reaches the
model's system prompt via BaseAgent.run() → build_context() →
build_agent_system_prompt().
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from core.models import Intent

logger = logging.getLogger(__name__)

_PLAYBOOK_PATH = Path(__file__).resolve().parent / "playbook.md"


def _load_playbook() -> str:
    """Load the selector playbook markdown file (best-effort)."""
    try:
        if not _PLAYBOOK_PATH.exists():
            logger.warning(
                "[editor_selector.context_builder] playbook missing at %s",
                _PLAYBOOK_PATH,
            )
            return ""
        return _PLAYBOOK_PATH.read_text()
    except Exception as exc:
        logger.warning(
            "[editor_selector.context_builder] failed to read playbook %s: %s",
            _PLAYBOOK_PATH, exc,
        )
        return ""


def build_editor_selector_context(
    messages: list[dict],
    intent: Intent,
    memory_facts: Optional[list[str]] = None,
    orchestrator_context: Optional[str] = None,
) -> str:
    """Build the editor-selector agent context string (the playbook)."""
    playbook_md = _load_playbook()
    lines: list[str] = []
    if playbook_md:
        playbook_lines = playbook_md.splitlines()
        while playbook_lines and (
            playbook_lines[0].startswith("# ") or not playbook_lines[0].strip()
        ):
            playbook_lines.pop(0)
        lines.append("## Editor Selector")
        lines.append("")
        lines.extend(playbook_lines)
        lines.append("")
    else:
        lines.extend([
            "## Editor Selector",
            "",
            "You are the Editor Selector. You receive N candidate edit",
            "proposals for one file and pick the single best one. Respond",
            "with ONLY a JSON object:",
            '{"choice": <0-based index>, "reason": "<why>",',
            ' "suggested_improvements": "<optional>".}',
            "",
        ])
    return "\n".join(lines)
