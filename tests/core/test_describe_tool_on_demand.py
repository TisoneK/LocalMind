"""ADR-40 option C regression tests: on-demand long-tail tool loading.

B-2026-08-16-2: the 16 long-tail tools (browse, delegate*,
sql, csv, json, best_of_n_edit, propose_*, subgoal, skill, diagnostics)
are NOT sent in the native `tools` param on every call. The model loads
one with `describe_tool(name)` (the `skill`-loader pattern); the loop
then includes that tool's FULL schema in the `tools` param for the rest
of the run.

These tests pin:
1. The tier split integrity (core + long-tail == the 30-tool catalog).
2. `tool_defs_for_call()` composition: core + describe_tool always; a
   long-tail tool appears ONLY after it is loaded; scoped agents never
   gain tools outside their allowed set; no duplicate core schemas.
3. The describe_tool tool itself: loads a long-tail schema (metadata
   carries the loaded name for the loop's bookkeeping), already-loaded
   note for core tools, not_found, missing-arg validation.
4. End-to-end through AgentLoop with a stub adapter: call 1 has no
   browse, describe_tool loads it, call 2's tools param has browse.
5. The `_note_described_tool` bookkeeping helper (metadata-based, so it
   survives the asyncio.wait_for task boundary of dispatch_with_retry).
"""

from __future__ import annotations

import pytest
from core.agent.constants import AGENT_ALLOWED_TOOLS
from core.agent.loop import AgentLoop, _note_described_tool
from core.agent.tool_schemas import (
    CORE_TOOL_NAMES,
    DESCRIBE_TOOL_DEFINITION,
    LONG_TAIL_TOOL_NAMES,
    TOOL_DEFINITIONS,
    get_full_tool_def,
    tool_defs_for_call,
)
from core.models import Intent, RiskLevel, StreamChunk, ToolResult
from tools import dispatch

# ── Tier split integrity ─────────────────────────────────────────────────────


def test_tier_split_covers_catalog_exactly() -> None:
    catalog = {td["function"]["name"] for td in TOOL_DEFINITIONS}
    assert CORE_TOOL_NAMES | LONG_TAIL_TOOL_NAMES == catalog
    assert CORE_TOOL_NAMES.isdisjoint(LONG_TAIL_TOOL_NAMES)
    # Session 411 (P0 Context Engineering): 6 tools moved from CORE to LONG_TAIL
    # (git, process, web_research, observe, sysinfo, calculator) — ~900 tok/call
    # saved on the always-present tools param. Core: 17→11, long-tail: 16→22.
    assert len(CORE_TOOL_NAMES) == 12  # S411 (-6); dir_explorer joined the always-present core surface
    assert len(LONG_TAIL_TOOL_NAMES) == 23  # S411 (+6); S457 (+search_tool_results, P0 slice 2 retrieval tool)
    # the ADR's named long tail is all present (browse is CORE, not long-tail)
    for name in ("delegate", "sql", "csv", "json", "best_of_n_edit",
                 "propose_str_replace", "propose_write_file", "apply_proposed_edit",
                 "add_subgoal", "update_subgoal", "create_plan", "skill", "diagnostics"):
        assert name in LONG_TAIL_TOOL_NAMES
    # The 6 tools moved from core to long-tail
    for name in ("git", "process", "web_research", "observe", "sysinfo", "calculator"):
        assert name in LONG_TAIL_TOOL_NAMES
    # the always-present core set (Session 411: git removed — now on-demand)
    for name in ("shell", "file_task", "file_write", "edit_file", "system_search",
                 "dir_explorer", "web_search", "web_fetch", "code_exec", "browse"):
        assert name in CORE_TOOL_NAMES


def test_describe_tool_is_always_allowed_and_never_duplicated() -> None:
    assert "describe_tool" in AGENT_ALLOWED_TOOLS
    assert DESCRIBE_TOOL_DEFINITION["function"]["name"] == "describe_tool"
    assert Intent.DESCRIBE_TOOL == "describe_tool"
    # meta-tool is NOT part of the 30-tool catalog (kept separate so the
    # catalog constant stays the backward-compatible full set)
    assert "describe_tool" not in {td["function"]["name"] for td in TOOL_DEFINITIONS}


# ── Composition ──────────────────────────────────────────────────────────────


def _names(defs: list[dict]) -> list[str]:
    return [td["function"]["name"] for td in defs]


def test_composition_always_present_surface_is_core_plus_meta() -> None:
    composed = tool_defs_for_call(TOOL_DEFINITIONS, AGENT_ALLOWED_TOOLS)
    names = _names(composed)
    assert set(names) == set(CORE_TOOL_NAMES) | {"describe_tool"}
    # no long-tail tool leaks into the always-present surface
    assert set(names).isdisjoint(LONG_TAIL_TOOL_NAMES)
    assert names.count("describe_tool") == 1
    # describe_tool's description advertises the on-demand index (sql is a
    # long-tail example — browse is CORE now, B-2026-08-30-13)
    assert "sql" in DESCRIBE_TOOL_DEFINITION["function"]["description"]
    assert "delegate" in DESCRIBE_TOOL_DEFINITION["function"]["description"]


def test_composition_loaded_tool_appears_with_full_schema() -> None:
    composed = tool_defs_for_call(TOOL_DEFINITIONS, AGENT_ALLOWED_TOOLS, {"sql"})
    names = _names(composed)
    assert "sql" in names
    sql_def = next(td for td in composed if td["function"]["name"] == "sql")
    assert sql_def == get_full_tool_def("sql"), "loaded schema must be the FULL def"
    # core tools can never be duplicated by a load (git is core)
    composed2 = tool_defs_for_call(TOOL_DEFINITIONS, AGENT_ALLOWED_TOOLS, {"sql", "git"})
    assert _names(composed2).count("git") == 1


def test_composition_respects_scope() -> None:
    scope = frozenset({"shell", "file_task", "sql"})
    scoped = [td for td in TOOL_DEFINITIONS if td["function"]["name"] in scope]
    composed = tool_defs_for_call(scoped, scope, {"sql", "delegate"})
    names = _names(composed)
    assert "sql" in names and "shell" in names and "file_task" in names
    assert "delegate" not in names, "a loaded tool outside the scope must not appear"
    assert "describe_tool" in names


def test_composition_after_load_is_monotonic_and_stable() -> None:
    base = tool_defs_for_call(TOOL_DEFINITIONS, AGENT_ALLOWED_TOOLS)
    loaded = tool_defs_for_call(TOOL_DEFINITIONS, AGENT_ALLOWED_TOOLS, {"sql", "csv"})
    base_names, loaded_names = _names(base), _names(loaded)
    # loaded == base + the two new full schemas (catalog order preserved)
    assert len(loaded_names) == len(base_names) + 2
    for name in base_names:
        assert loaded_names.count(name) == 1


# ── The describe_tool tool itself ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_describe_tool_loads_long_tail_schema() -> None:
    result = await dispatch(Intent.DESCRIBE_TOOL, "sql")
    assert result is not None and result.success
    assert result.metadata["loaded_tool"] == "sql"
    assert result.metadata["chars"] > 100
    # the returned text contains the actual schema (params + required)
    assert '"query"' in result.content
    assert '"required"' in result.content


@pytest.mark.asyncio
async def test_describe_tool_core_tool_not_loaded() -> None:
    # Git moved to LONG_TAIL — use "shell" (still CORE) as the
    # example of a core tool that describe_tool should NOT re-load.
    result = await dispatch(Intent.DESCRIBE_TOOL, "shell")
    assert result is not None and result.success
    assert result.metadata.get("already_loaded") is True
    assert "loaded_tool" not in result.metadata, "core tools are never 'loaded'"


@pytest.mark.asyncio
async def test_describe_tool_core_tool_does_not_redump_schema() -> None:
    """Describe_tool on a CORE tool must NOT re-dump the full
    schema (it's already in the tools list) — that ~3k dump for browse overflowed
    the context window. Return a short 'call it directly' nudge instead."""
    for name in ("browse", "web_fetch"):
        result = await dispatch(Intent.DESCRIBE_TOOL, name)
        assert result.success and result.metadata.get("already_loaded") is True
        assert len(result.content) < 400, f"{name} describe result should be short"
        assert '"enum"' not in result.content and '"parameters"' not in result.content
        assert "directly" in result.content.lower()


@pytest.mark.asyncio
async def test_describe_tool_unknown_and_missing() -> None:
    unknown = await dispatch(Intent.DESCRIBE_TOOL, "nope")
    assert unknown is not None and not unknown.success and unknown.error_type == "not_found"
    assert "sql" in unknown.content  # hints the available on-demand names
    missing = await dispatch(Intent.DESCRIBE_TOOL, "")
    assert missing is not None and not missing.success and missing.error_type == "validation_error"


# ── Loop bookkeeping helper ──────────────────────────────────────────────────


def test_note_described_tool_uses_metadata_not_contextvar() -> None:
    loaded: set[str] = set()
    ok = ToolResult(content="", risk=RiskLevel.LOW, source="describe_tool", success=True,
                    metadata={"loaded_tool": "csv", "chars": 400})
    _note_described_tool("describe_tool", ok, loaded)
    assert loaded == {"csv"}

    # non-describe_tool tools never touch the set
    _note_described_tool("shell", ok, loaded)
    assert loaded == {"csv"}

    # failed describe_tool never loads
    failed = ToolResult(content="nope", risk=RiskLevel.LOW, source="describe_tool",
                        success=False, error_type="not_found")
    _note_described_tool("describe_tool", failed, loaded)
    assert loaded == {"csv"}


# ── End-to-end through AgentLoop (stub adapter) ──────────────────────────────


class _OnDemandAdapter:
    """Stub adapter: describe_tool on call 1, sql on call 2, final text.

    Uses `sql` as the on-demand example — browse is CORE now,
    so it's always present and no longer exercises the describe_tool→load path.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.tools_seen: list[list[dict]] = []

    async def chat(self, messages, temperature=0.1, intent="chat"):
        yield StreamChunk(text="STEPS:\n1. Load sql and query the db\n2. Answer\n")

    async def chat_with_tools(self, messages, tools, temperature=0.3, intent=None, tool_choice=None):
        self.calls += 1
        self.tools_seen.append(tools)
        from adapters.ollama import ToolCallResult

        if self.calls == 1:
            return ToolCallResult(tool_name="describe_tool", tool_args={"tool_name": "sql"},
                                  raw_content="sql is on-demand — loading it.")
        if self.calls == 2:
            return ToolCallResult(tool_name="sql", tool_args={"path": "data.db", "query": "SELECT 1"},
                                  raw_content="Querying the db.")

        async def _stream():
            yield StreamChunk(text="The query ran.", done=False)
            yield StreamChunk(text="", done=True)

        return _stream()


@pytest.mark.asyncio
async def test_loop_loads_on_demand_tool_then_calls_it() -> None:
    adapter = _OnDemandAdapter()
    sql_result = ToolResult(
        content="1 row: (1,)", risk=RiskLevel.LOW,
        source="sql", success=True,
    )
    describe_result = ToolResult(
        content="Tool 'sql' is now LOADED — its full schema is below.\n\n{...}",
        risk=RiskLevel.LOW, source="describe_tool", success=True,
        metadata={"loaded_tool": "sql", "chars": 100},
    )

    from unittest.mock import patch

    async def _fake_dispatch(tool_intent, tool_input, **kwargs):
        if tool_intent == Intent.DESCRIBE_TOOL:
            return describe_result, False, 0
        return sql_result, False, 0

    with patch("core.agent.loop.dispatch_with_retry", side_effect=_fake_dispatch):
        chunks = [
            chunk
            async for chunk in AgentLoop(adapter=adapter).run(
                messages=[{"role": "user", "content": "query data.db"}],
                intent=Intent.SQL,
                initial_tool_result=None,
                available_tools=[],
                adapter=adapter,
            )
        ]

    assert adapter.calls == 3, "describe_tool → sql → final answer"
    names0 = [td["function"]["name"] for td in adapter.tools_seen[0]]
    names1 = [td["function"]["name"] for td in adapter.tools_seen[1]]
    names2 = [td["function"]["name"] for td in adapter.tools_seen[2]]

    # call 1: sql NOT present (on-demand), describe_tool IS
    assert "describe_tool" in names0 and "sql" not in names0
    # call 2: sql is now present with its FULL schema
    assert "sql" in names1
    sql_def = next(td for td in adapter.tools_seen[1] if td["function"]["name"] == "sql")
    assert sql_def == get_full_tool_def("sql")
    # the load persists for the rest of the run
    assert "sql" in names2
    # no duplicates — describe_tool appears exactly once in every tools param
    for names in (names0, names1, names2):
        assert names.count("describe_tool") == 1
    assert "The query ran." in "".join(chunk.text for chunk in chunks)
    assert sum(chunk.done for chunk in chunks) == 1
