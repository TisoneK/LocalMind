"""
Verifier agent scoped toolset.

Per ADR-6: each agent has its own scoped toolset. A verifier agent has
shell + process + git + file_task + edit_file. It does NOT have web
tools, browser, code_exec, or memory_op — those belong to other agents.

The verifier's tools map to its responsibilities:
  - shell    → run tests, linters, typecheckers, build commands
  - process  → start services before testing (Session 42 prerequisite)
  - git      → check what changed, diff against baseline
  - file_task → read test output, error logs, source files
  - edit_file → fix bugs when found (reproduce → diagnose → fix → verify)
  - delegate → ADR-8 Phase 3: delegate to coding/research when needed

The verifier's job is to PROVE things work (or find what's broken), not
to build new features. It's a separate agent from the coder so it can
be independently tasked and so its tool surface is scoped to
verification — no code_exec, no file_write (use edit_file for targeted
bug fixes only).
"""

from __future__ import annotations

from core.agent.constants import AGENT_ALLOWED_TOOLS

VERIFIER_TOOLS: frozenset[str] = frozenset(
    {
        "shell",
        "process",
        "git",
        "file_task",
        "edit_file",
        "delegate",  # ADR-8 Phase 3: delegate to coding for complex fixes
        "diagnostics",  # Session 49: structured failure analysis
        "skill",  # B-2026-08-02-12: universal skill tool
    }
)

# Sanity check: VERIFIER_TOOLS must be a subset of AGENT_ALLOWED_TOOLS.
assert VERIFIER_TOOLS.issubset(AGENT_ALLOWED_TOOLS), (
    f"VERIFIER_TOOLS ({VERIFIER_TOOLS}) must be a subset of "
    f"AGENT_ALLOWED_TOOLS ({AGENT_ALLOWED_TOOLS})"
)
