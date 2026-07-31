"""
Reviewer agent context builder.

Gathers review-specific context before each turn:
    - The reviewer workflow (read before assessing, check specs,
      identify quality issues, report clearly, don't fix)
    - Memory facts (passed in by the caller)
    - Orchestrator plan (passed in by the caller)

Per ADR-6: each agent supplies its own build_context(). The reviewer's
context primes the model to think like a code reviewer — assessing
quality, checking conformance, and identifying issues — not building
or fixing.

The workspace_state snapshot (git status/diff/build result) is injected
by AgentLoop.run() per Session 16. For the reviewer, git diff is the
primary input — it shows exactly what changed and needs review.
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
            logger.warning("[reviewer.context_builder] workflow file missing at %s", _WORKFLOW_PATH)
            return ""
        return _WORKFLOW_PATH.read_text()
    except Exception as exc:
        logger.warning("[reviewer.context_builder] failed to read workflow: %s", exc)
        return ""


def build_reviewer_context(
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
        lines.append("## Reviewer Workflow")
        lines.append("")
        lines.extend(workflow_lines)
        lines.append("")
    else:
        lines.extend([
            "## Reviewer Agent",
            "",
            "You are running as the Reviewer Agent. Your tool surface is",
            "scoped to review tools — file_task (read code), git (check",
            "changes), shell (run linters and static analysis).",
            "Your job is to ASSESS whether implementations satisfy",
            "specifications and quality requirements — not to build or fix.",
            "",
            "Review pattern:",
            "1. Read the spec/requirements and the implementation",
            "2. Use git diff to see what changed",
            "3. Assess: correctness, style, performance, security, tests",
            "4. Report findings clearly with specific, actionable feedback",
            "5. Do NOT edit code — hand off findings to the coding agent",
            "",
        ])

    lines.extend([
        "The workspace state (git status, diff since last turn) is",
        "injected into your context every turn — use it to identify",
        "exactly what changed and focus your review on those changes.",
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
