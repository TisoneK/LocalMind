"""Research agent context builder — loads the research workflow file.

Per ADR-8 Phase 2 (Session 34): loads agents/research/workflow.md and
returns it as the agent_context. The workflow governs HOW the Research
Agent uses web_search + web_fetch (enough sources, cross-reference key
claims, note dates, distinguish facts from opinions, synthesize).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from core.models import Intent

logger = logging.getLogger(__name__)

_WORKFLOW_PATH = Path(__file__).resolve().parent / "workflow.md"


def _load_workflow() -> str:
    try:
        if not _WORKFLOW_PATH.exists():
            logger.warning(
                "[research.context_builder] workflow file missing at %s — "
                "Phase 2 workflow injection will be empty",
                _WORKFLOW_PATH,
            )
            return ""
        return _WORKFLOW_PATH.read_text()
    except Exception as exc:
        logger.warning(
            "[research.context_builder] failed to read workflow file %s: %s",
            _WORKFLOW_PATH, exc,
        )
        return ""


def build_research_context(
    messages: list[dict],
    intent: Intent,
    memory_facts: Optional[list[str]] = None,
    orchestrator_context: Optional[str] = None,
) -> str:
    workflow_md = _load_workflow()

    lines: list[str] = []

    if workflow_md:
        workflow_lines = workflow_md.splitlines()
        while workflow_lines and (
            workflow_lines[0].startswith("# ") or not workflow_lines[0].strip()
        ):
            workflow_lines.pop(0)
        lines.append("## Research Workflow")
        lines.append("")
        lines.extend(workflow_lines)
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
