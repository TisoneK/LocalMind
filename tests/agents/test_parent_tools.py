"""
Tests for S426 — the parent's tool surface must not advertise the parked
multi-agent tools (ADR-53 parent-only scope).

Before this change ``PARENT_TOOLS`` was the full ``AGENT_ALLOWED_TOOLS``, so
the parent's bootstrap prompt advertised ``delegate`` / ``delegate_parallel``
/ ``delegate_inline`` / ``best_of_n_edit`` — tools the Parent must never
route through — on every turn, in both the compact capability index and the
on-demand tool-name instructions. The parked child agents (analyst, coding,
browser, ...) keep the full shared allowlist; only the parent is narrowed.
"""

from __future__ import annotations

from agents.parent.tools import PARENT_TOOLS
from core.agent.constants import AGENT_ALLOWED_TOOLS

_PARKED_MULTI_AGENT_TOOLS = frozenset(
    {"delegate", "delegate_parallel", "delegate_inline", "best_of_n_edit"}
)


class TestParentToolSurface:
    def test_parent_tools_exclude_parked_multi_agent_tools(self):
        missing = _PARKED_MULTI_AGENT_TOOLS & PARENT_TOOLS
        assert not missing, (
            f"parked multi-agent tools must not be parent-reachable: {sorted(missing)}"
        )

    def test_parent_tools_stay_within_shared_allowlist(self):
        assert PARENT_TOOLS <= AGENT_ALLOWED_TOOLS
        # The cut only REMOVES; every other tool stays.
        assert PARENT_TOOLS == AGENT_ALLOWED_TOOLS - _PARKED_MULTI_AGENT_TOOLS

    def test_parent_agent_config_uses_narrowed_toolset(self):
        from unittest.mock import MagicMock

        from agents.parent.agent import ParentAgent

        config = ParentAgent(MagicMock()).config()
        assert config.allowed_tools == PARENT_TOOLS

    def test_parked_children_keep_full_allowlist_available(self):
        """The cut is parent-only: a parked child toolset that includes
        delegate still subsets AGENT_ALLOWED_TOOLS (their import-time sanity
        asserts must stay true)."""
        from agents.analyst.tools import ANALYST_TOOLS
        from agents.coding.tools import CODING_TOOLS

        assert CODING_TOOLS.issubset(AGENT_ALLOWED_TOOLS)
        assert ANALYST_TOOLS.issubset(AGENT_ALLOWED_TOOLS)

    def test_bootstrap_prompt_omits_parked_tools(self):
        """The parent's native-bootstrap system prompt — compact capability
        index AND on-demand tool instructions — must never name a parked
        multi-agent tool."""
        from unittest.mock import MagicMock

        from agents.parent.agent import ParentAgent
        from core.agent.loop import _filtered_tool_defs
        from core.agent.prompts import build_agent_system_prompt
        from core.models import Intent
        from tools import available_tools

        config = ParentAgent(MagicMock()).config()
        tools = available_tools()
        scoped = [t for t in tools if t["intent"] in config.allowed_tools]
        prompt = build_agent_system_prompt(
            Intent.FILE_TASK,
            scoped,
            tool_defs=_filtered_tool_defs(config.allowed_tools),
            native_bootstrap=True,
        )
        for name in _PARKED_MULTI_AGENT_TOOLS:
            assert name not in prompt, (
                f"parent bootstrap prompt advertises parked tool {name!r}"
            )
        # The prompt must still be a real catalog — the cut didn't gut it.
        assert "system_search" in prompt and "file_task" in prompt

    def test_unscoped_bootstrap_summary_unchanged(self):
        """The no-arg compact_tool_summary still covers the whole registry —
        other consumers (tests, non-parent callers) are unaffected by the
        parent scoping."""
        from core.agent.tool_schemas import compact_tool_summary

        summary = compact_tool_summary()
        assert "delegate" in summary  # full registry, not parent-scoped
