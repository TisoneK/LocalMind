"""
Coding agent context builder.

Gathers coding-specific context before each turn:
    - The coding workflow (read-before-write, verify-after-write,
      use-workspace-state, follow-conventions, small-verifiable-changes)
      loaded from agents/coding/workflow.md
    - Memory facts (passed in by the caller)
    - Orchestrator plan (passed in by the caller)

Per ADR-6: each agent supplies its own build_context(). The coding
agent's context is codebase-centric, unlike the browser agent (page-
state-centric) or the research agent (source-tracking-centric).

Per ADR-8 Phase 2 (Session 34): this function ACTUALLY loads the
workflow file. Phase 1 returned a static header; Phase 2 makes the
workflow load-bearing — the file's contents reach the model's system
prompt via the `agent_context` parameter of
`build_agent_system_prompt()`. This is the "the workflow is the value"
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

# Path to the coding workflow file. Per ADR-8 Phase 2 (Session 34),
# the workflow file moved from backend/data/workflows/coding.md to
# agents/coding/workflow.md — co-located with the agent class. The
# path is resolved relative to this file so it works regardless of
# the process CWD.
_WORKFLOW_PATH = Path(__file__).resolve().parent / "workflow.md"


def _load_workflow() -> str:
    """Load the coding workflow markdown file.

    Returns an empty string if the file is missing or unreadable
    (best-effort — the workflow is guidance, not a hard requirement).
    Logs a warning on failure so the regression is visible.
    """
    try:
        if not _WORKFLOW_PATH.exists():
            logger.warning(
                "[coding.context_builder] workflow file missing at %s — "
                "Phase 2 workflow injection will be empty",
                _WORKFLOW_PATH,
            )
            return ""
        return _WORKFLOW_PATH.read_text()
    except Exception as exc:
        logger.warning(
            "[coding.context_builder] failed to read workflow file %s: %s",
            _WORKFLOW_PATH, exc,
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

    Phase 2 (ADR-8, Session 34): loads the coding workflow file
    (agents/coding/workflow.md) and returns it as the agent_context
    section. The workflow contains the constraints:
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
    workflow_md = _load_workflow()

    lines: list[str] = []

    if workflow_md:
        # Strip the H1 header line (it duplicates the AGENT CONTEXT section
        # header that build_agent_system_prompt() adds). Keep the rest.
        workflow_lines = workflow_md.splitlines()
        # Drop the first "# Workflow: Coding ..." line and any leading blank lines
        while workflow_lines and (
            workflow_lines[0].startswith("# ") or not workflow_lines[0].strip()
        ):
            workflow_lines.pop(0)
        lines.append("## Coding Workflow")
        lines.append("")
        lines.extend(workflow_lines)
        lines.append("")
    else:
        # Fallback: the static header from Phase 1, so the prompt isn't
        # empty if the workflow file is missing.
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
