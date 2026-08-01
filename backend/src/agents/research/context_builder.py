"""Research agent context builder — loads the research playbook file.

Per ADR-8 Phase 2 (Session 34): loads agents/research/playbook.md and
returns it as the agent_context. The playbook governs HOW the Research
Agent uses web_search + web_fetch (enough sources, cross-reference key
claims, note dates, distinguish facts from opinions, synthesize).
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
            logger.warning(
                "[research.context_builder] playbook file missing at %s — "
                "Phase 2 playbook injection will be empty",
                _PLAYBOOK_PATH,
            )
            return ""
        return _PLAYBOOK_PATH.read_text()
    except Exception as exc:
        logger.warning(
            "[research.context_builder] failed to read playbook file %s: %s",
            _PLAYBOOK_PATH, exc,
        )
        return ""


def build_research_context(
    messages: list[dict],
    intent: Intent,
    memory_facts: Optional[list[str]] = None,
    orchestrator_context: Optional[str] = None,
) -> str:
    playbook_md = _load_playbook()

    lines: list[str] = []

    if playbook_md:
        playbook_lines = playbook_md.splitlines()
        while playbook_lines and (
            playbook_lines[0].startswith("# ") or not playbook_lines[0].strip()
        ):
            playbook_lines.pop(0)
        lines.append("## Research Playbook")
        lines.append("")
        lines.extend(playbook_lines)
        lines.append("")
    else:
        lines.extend([
            "## Research Agent",
            "",
            "You are running as the Research Agent. Your tool surface is",
            "scoped to web search and web fetch — you cannot run shell",
            "commands, edit files, execute code, or drive a browser. Use",
            "web_search to find sources, then web_fetch to read them in",
            "full. Track your sources and synthesize findings into a",
            "coherent answer.",
            "",
        ])

    lines.extend([
        "Track your sources. Cross-reference key claims. Note dates — a",
        "2022 source may be outdated for a 2026 question. Synthesize,",
        "don't just list.",
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
