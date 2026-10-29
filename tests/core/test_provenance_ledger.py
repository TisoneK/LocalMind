"""
The audit ledger for injected context and retried tool attempts.

Two records that used to vanish behind a final status:

1. Retry attempts — a tool that succeeded on its third try must not read as
   if the first worked. ``dispatch_with_retry`` now keeps one entry per
   failed attempt (timeout/exception), attaches it to the returned result
   and/or hands it to the caller's list so it survives even an exhausted
   retry budget (result of None).

2. Injected context items — the per-turn environment block records its exact
   rendered fragments (kind/source/text) via ``items_out``. Record and
   prompt are built from the same variables, so they cannot drift: the test
   asserts every recorded fragment appears verbatim in the rendered block.

3. The provider-death degraded signal persists as a phase strip entry, so a
   reloaded transcript still shows what happened to the run.
"""

from __future__ import annotations

import pytest

from core.agent.tool_dispatch import dispatch_with_retry
from core.context_builder import _build_environment_context
from core.models import Intent, ToolResult


# ── retry ledger ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_try_success_carries_no_attempts(monkeypatch):
    ok = ToolResult(content="done", source="sysinfo", success=True)

    async def fake_dispatch(*args, **kwargs):
        return ok

    monkeypatch.setattr("core.agent.tool_dispatch.dispatch", fake_dispatch)
    attempts: list = []
    result, failed, retries = await dispatch_with_retry(
        Intent.SYSINFO, "clock", collect_attempts=attempts
    )

    assert result is ok
    assert failed is False
    assert retries == 0
    assert attempts == []
    assert result.retry_attempts == []


@pytest.mark.asyncio
async def test_success_after_retry_keeps_the_failed_attempt(monkeypatch):
    ok = ToolResult(content="recovered", source="web_fetch", success=True)
    calls = {"n": 0}

    async def flaky_dispatch(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("connection refused")
        return ok

    monkeypatch.setattr("core.agent.tool_dispatch.dispatch", flaky_dispatch)
    attempts: list = []
    result, failed, retries = await dispatch_with_retry(
        Intent.WEB_FETCH, "http://example.test", base_delay=0.0, collect_attempts=attempts
    )

    assert result is ok
    assert failed is False
    assert retries == 1
    assert len(attempts) == 1
    assert attempts[0]["attempt"] == 1
    assert "connection refused" in attempts[0]["error"]
    # The same ledger rides the result — a consumer that never passed a
    # collect list still sees the recovery.
    assert result.retry_attempts == attempts


@pytest.mark.asyncio
async def test_timeout_attempts_are_ledgered_with_the_wait(monkeypatch):
    ok = ToolResult(content="late but done", source="shell", success=True)
    calls = {"n": 0}

    async def slow_dispatch(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError()
        return ok

    monkeypatch.setattr("core.agent.tool_dispatch.dispatch", slow_dispatch)
    attempts: list = []
    result, failed, retries = await dispatch_with_retry(
        Intent.SHELL, "sleep 999", base_delay=0.0, collect_attempts=attempts
    )

    assert failed is False
    assert retries == 1
    assert "timed out" in attempts[0]["error"]
    assert attempts[0]["waited_ms"] > 0
    assert result.retry_attempts == attempts


@pytest.mark.asyncio
async def test_non_retriable_structured_failure_keeps_prior_attempts(monkeypatch):
    missing = ToolResult(
        content="not found",
        source="file_task",
        success=False,
        error_type="not_found",
    )

    async def flaky_dispatch(*args, **kwargs):
        raise ConnectionError("transient blip")
        yield  # pragma: no cover — makes this an async generator-free coroutine

    async def then_missing(*args, **kwargs):
        return missing

    state = {"n": 0}

    async def dispatch_twice(*args, **kwargs):
        state["n"] += 1
        if state["n"] == 1:
            raise ConnectionError("transient blip")
        return missing

    monkeypatch.setattr("core.agent.tool_dispatch.dispatch", dispatch_twice)
    attempts: list = []
    result, failed, retries = await dispatch_with_retry(
        Intent.FILE_TASK, "/missing", base_delay=0.0, collect_attempts=attempts
    )

    # A structured non-retriable error returns immediately — but the failed
    # attempt that preceded it stays on the record.
    assert result is missing
    assert failed is True
    assert retries == 1
    assert len(attempts) == 1
    assert result.retry_attempts == attempts


@pytest.mark.asyncio
async def test_exhausted_retries_hand_the_ledger_to_the_caller(monkeypatch):
    async def always_down(*args, **kwargs):
        raise ConnectionError("port closed")

    monkeypatch.setattr("core.agent.tool_dispatch.dispatch", always_down)
    attempts: list = []
    result, failed, retries = await dispatch_with_retry(
        Intent.WEB_FETCH, "http://blackhole.test", max_retries=2, base_delay=0.0,
        collect_attempts=attempts,
    )

    assert result is None
    assert failed is True
    assert retries == 2
    # Every failed attempt — including the last, which got no retry — is on
    # the caller's list. The ledger outlives the None result.
    assert [a["attempt"] for a in attempts] == [1, 2, 3]
    assert all("port closed" in a["error"] for a in attempts)


# ── injected-items ledger ─────────────────────────────────────────────────────


def test_items_do_not_change_the_rendered_block():
    without = _build_environment_context()
    items: list = []
    with_items = _build_environment_context(items_out=items)
    assert without == with_items
    assert items, "the full env must record items"


def test_every_recorded_fragment_is_verbatim_in_the_block():
    items: list = []
    block = _build_environment_context(items_out=items)
    for item in items:
        assert item["text"] in block, f"fragment drifted: {item['kind']}"
        assert item["chars"] == len(item["text"])
        assert item["source"], "every item names its producer"


def test_full_variant_records_stated_identity_and_tool_catalog():
    items: list = []
    _build_environment_context(items_out=items)
    kinds = {i["kind"] for i in items}
    assert "user_identity.stated" in kinds
    assert "user_context.deduced" in kinds
    assert "environment.clock" in kinds
    assert "shell_state" in kinds
    assert "tool_catalog" in kinds
    identity = next(i for i in items if i["kind"] == "user_identity.stated")
    assert identity["source"] == "user profile (stated in Settings)"


def test_compact_variant_records_its_narrowness():
    items: list = []
    block = _build_environment_context(compact=True, items_out=items)
    kinds = {i["kind"] for i in items}
    # The classify call deliberately omits the stated identity and the tool
    # catalog — the record must SHOW that, not hide it.
    assert "user_identity.stated" not in kinds
    assert "tool_catalog" not in kinds
    assert "environment.hardware" not in kinds
    assert "environment.clock" in kinds
    for item in items:
        assert item["text"] in block


def test_workspace_item_only_when_a_session_has_one():
    items: list = []
    _build_environment_context(items_out=items)
    assert "workspace_folder" not in {i["kind"] for i in items}

    with_session: list = []
    _build_environment_context(session_id="ws-probe", items_out=with_session)
    ws = [i for i in with_session if i["kind"] == "workspace_folder"]
    assert ws and ws[0]["chars"] > 0


# ── degraded phase persistence ────────────────────────────────────────────────


def _phases_for(obs_events):
    from core.agent_workspace import build_agent_phases
    from core.obs import ObsCollector

    collector = ObsCollector()
    for event_type, data in obs_events:
        collector.emit(event_type, **data)
    return build_agent_phases(collector)


def test_terminal_death_persists_as_a_degraded_phase():
    phases = _phases_for(
        [
            (
                "agent_loop_degraded",
                {
                    "iteration": 2,
                    "provider_error_code": "payment_required",
                    "provider": "stub-provider",
                    "evidence_preserved": True,
                    "terminal": True,
                },
            )
        ]
    )
    degraded = [p for p in phases if p["type"] == "agent_loop_degraded"]
    assert len(degraded) == 1
    assert degraded[0]["label"] == "Provider died — evidence delivered as gathered"
    assert "stub-provider" in degraded[0]["detail"]
    assert "payment_required" in degraded[0]["detail"]


def test_retryable_cutoff_persists_with_its_own_label():
    phases = _phases_for(
        [
            (
                "agent_loop_degraded",
                {
                    "provider_error_code": "rate_limit",
                    "evidence_preserved": True,
                    "terminal": False,
                },
            )
        ]
    )
    degraded = [p for p in phases if p["type"] == "agent_loop_degraded"]
    assert degraded[0]["label"] == "Provider interrupted — partial evidence delivered"


def test_degraded_phase_without_fields_still_names_the_event():
    phases = _phases_for([("agent_loop_degraded", {})])
    degraded = [p for p in phases if p["type"] == "agent_loop_degraded"]
    assert degraded[0]["label"] == "Provider interrupted the run"
    assert degraded[0]["detail"] is None
