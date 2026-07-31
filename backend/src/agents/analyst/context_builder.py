"""
Analyst agent context builder.

Gathers analysis-specific context before each turn:
    - The analyst workflow (read specs, clarify requirements, produce
      actionable description, don't design or build)
    - Memory facts (passed in by the caller)
    - Orchestrator plan (passed in by the caller)

Per ADR-6: each agent supplies its own build_context(). The analyst's
context primes the model to think like a requirements analyst —
understanding what needs to be built, not how to build it.

The workstation state snapshot is injected by AgentLoop.run() per
Session 16.
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
            logger.warning("[analyst.context_builder] workflow file missing at %s", _WORKFLOW_PATH)
            return ""
        return _WORKFLOW_PATH.read_text()
    except Exception as exc:
        logger.warning("[analyst.context_builder] failed to read workflow: %s", exc)
        return ""


def build_analyst_context(
    messages: list[dict],
    intent: Intent,
    memory_facts: Optional[list[str]] = None,
    orchestrator_context: Optional[str] = None,
) -> str:
    workflow_md = _load_workflow()

    lines: list[str] = []

    if workflow_md:
        workflow_lines = workflow_md.splitlines()
        while workflow_lines and (workflow_lines[0].startswith("# ") or not workflow_lines[0].strip()):
            workflow_lines.pop(0)
        lines.append("## Analyst Workflow")
        lines.append("")
        lines.extend(workflow_lines)
        lines.append("")
    else:
        lines.extend([
            "## Analyst Agent",
            "",
            "You are running as the Analyst Agent. Your tool surface is",
            "scoped to analysis tools — file_task (read specs/docs),",
            "git (check project history).",
            "Your job is to UNDERSTAND what needs to be built — not to",
            "design solutions or write code.",
            "",
            "Analysis pattern:",
            "1. Read all available specifications and requirements",
            "2. Examine the project structure and existing code",
            "3. Check git history for relevant context",
            "4. Identify gaps, ambiguities, and implicit requirements",
            "5. Produce a clear, actionable specification",
            "6. Delegate to the planner or coding agent when ready",
            "",
        ])

    lines.extend([
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
