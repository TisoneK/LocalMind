"""
Verifier agent context builder.

Gathers verification-specific context before each turn:
    - The verifier workflow (systematic checking, isolate failures,
      use git/process tools, report clearly)
    - Memory facts (passed in by the caller)
    - Orchestrator plan (passed in by the caller)

Per ADR-6: each agent supplies its own build_context(). The verifier's
context is verification-centric — it primes the model to think like a
tester, not a builder.

The workspace_state snapshot (git status/diff/build result) is injected
by AgentLoop.run() per Session 16 — this context_builder does NOT
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

# Path to the verifier workflow file. Per ADR-8 Phase 2, the workflow
# is co-located with the agent class.
_WORKFLOW_PATH = Path(__file__).resolve().parent / "workflow.md"


def _load_workflow() -> str:
    """Load the verifier workflow markdown file.

    Returns an empty string if the file is missing or unreadable
    (best-effort — the workflow is guidance, not a hard requirement).
    """
    try:
        if not _WORKFLOW_PATH.exists():
            logger.warning(
                "[verifier.context_builder] workflow file missing at %s",
                _WORKFLOW_PATH,
            )
            return ""
        return _WORKFLOW_PATH.read_text()
    except Exception as exc:
        logger.warning(
            "[verifier.context_builder] failed to read workflow file %s: %s",
            _WORKFLOW_PATH, exc,
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

    Loads the verifier workflow file (agents/verifier/workflow.md) and
    returns it as the agent_context section. The workflow contains the
    constraints: read before verifying, isolate failures, use git/process
    tools, report clearly.

    The workspace_state snapshot (git status/diff/build result) is
    already injected by AgentLoop.run() per Session 16 — this
    context_builder does NOT duplicate it.
    """
    workflow_md = _load_workflow()

    lines: list[str] = []

    if workflow_md:
        workflow_lines = workflow_md.splitlines()
        # Drop the H1 header line and any leading blank lines
        while workflow_lines and (
            workflow_lines[0].startswith("# ") or not workflow_lines[0].strip()
        ):
            workflow_lines.pop(0)
        lines.append("## Verifier Workflow")
        lines.append("")
        lines.extend(workflow_lines)
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
