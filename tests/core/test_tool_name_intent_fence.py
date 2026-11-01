"""The tool name↔intent mismatch class, pinned (standing eval harness finds).

The schema advertises tool NAMES; dispatch knows Intents. Two tools' names
differ from their intent values (`edit_file`→FILE_EDIT, `calculator`→
CALCULATE). Both mismatch sites are pinned here:

- `loop._intent_for_tool` must resolve the NAME to the right Intent (it
  used to fall back to Intent.SHELL, so every native calculator call died
  inside the shell contract with the raw args JSON — found live by the
  eval suite, B-2026-10-31-23).
- `tool_dispatch.dispatch_with_retry`'s allowed-tool fence compares the
  intent against TOOL-NAME sets (AGENT_ALLOWED_TOOLS and every caller);
  the check must accept the aliased name too (the fence held "calculator"
  while the check looked for "calculate" — permission-blocked every
  calculator call inside any scoped turn).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from core.agent.loop import _intent_for_tool
from core.agent.tool_dispatch import dispatch_with_retry
from core.models import Intent, ToolResult


@pytest.mark.parametrize(
    ("tool_name", "expected"),
    [
        ("edit_file", Intent.FILE_EDIT),
        ("calculator", Intent.CALCULATE),
        # A direct name→value tool keeps resolving without the alias map.
        ("sysinfo", Intent("sysinfo")),
        ("file_task", Intent("file_task")),
    ],
)
def test_intent_for_tool_resolves_schema_names(tool_name: str, expected: Intent) -> None:
    assert _intent_for_tool(tool_name) is expected


def _no_retry_tool_result() -> ToolResult:
    return ToolResult(content="ok", source="calculator")


@pytest.mark.anyio
@pytest.mark.parametrize("allowed", [{"calculator"}, {"calculate"}, {"calculator", "sysinfo"}])
async def test_fence_accepts_name_and_value_forms(allowed: set[str]) -> None:
    """The fence must not block CALCULATE when the set carries either form."""
    called = False

    async def _fake_dispatch(intent: Intent, message: str):
        nonlocal called
        called = True
        return _no_retry_tool_result()

    import core.agent.tool_dispatch as td

    original = td.dispatch
    td.dispatch = _fake_dispatch
    try:
        result, failed, retries = await dispatch_with_retry(
            Intent.CALCULATE, "3*8", allowed_tool_names=frozenset(allowed)
        )
    finally:
        td.dispatch = original
    assert called, "the tool must be dispatched, not fence-blocked"
    assert not failed
    assert result is not None


@pytest.mark.anyio
async def test_fence_still_blocks_a_genuinely_absent_tool() -> None:
    """A tool absent from the set in BOTH forms stays blocked."""
    result, failed, retries = await dispatch_with_retry(
        Intent.CALCULATE, "3*8", allowed_tool_names=frozenset({"sysinfo", "web_search"})
    )
    assert failed
    assert result is not None
    assert result.error_type == "permission"
    assert retries == 0
