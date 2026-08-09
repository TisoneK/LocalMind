"""
Session 83: B-2026-08-02-8 (B3) — subgoal scratchpad tools tests.

add_subgoal / update_subgoal / create_plan operate on a per-run
SubgoalRegistry (contextvars) so the model can decompose a multi-step
task and track progress across iterations. The scratchpad must not
leak across runs (AgentLoop.run() resets it at the start of every run).
"""

from __future__ import annotations

import json

import pytest
from core.models import Intent
from core.subgoal import get_registry, reset_subgoals

# ── Registration / wiring ───────────────────────────────────────────────


def test_subgoal_intents_exist():
    assert Intent.ADD_SUBGOAL.value == "add_subgoal"
    assert Intent.UPDATE_SUBGOAL.value == "update_subgoal"
    assert Intent.CREATE_PLAN.value == "create_plan"


def test_subgoal_tools_are_registered():
    """All three registered in the tool registry, parallelizable (pure memory)."""
    from tools import _REGISTRY

    for intent in (Intent.ADD_SUBGOAL, Intent.UPDATE_SUBGOAL, Intent.CREATE_PLAN):
        assert intent in _REGISTRY, f"{intent.value} not registered — must be imported in tools/__init__.py"
        entry = _REGISTRY[intent]
        assert entry["description"], f"{intent.value} has no description"
        assert entry["parallelizable"] is True


def test_subgoal_tools_in_agent_allowed_and_coding_tools():
    from agents.coding.tools import CODING_TOOLS
    from core.agent.constants import AGENT_ALLOWED_TOOLS

    for tool in ("add_subgoal", "update_subgoal", "create_plan"):
        assert tool in AGENT_ALLOWED_TOOLS
        assert tool in CODING_TOOLS


# ── Fixture ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def fresh_scratchpad():
    """Every test starts with a clean per-run scratchpad."""
    reset_subgoals()
    yield
    reset_subgoals()


# ── add_subgoal ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_subgoal_stages_in_scratchpad():
    from tools.subgoal import add_subgoal

    result = await add_subgoal("create hello.py")

    assert result.success
    assert result.metadata["subgoal"]["id"] == "sg-1"
    assert result.metadata["subgoal"]["description"] == "create hello.py"
    assert result.metadata["subgoal"]["status"] == "pending"
    assert "sg-1" in result.content
    assert "create hello.py" in result.content


@pytest.mark.asyncio
async def test_add_subgoal_requires_description():
    from tools.subgoal import add_subgoal

    result = await add_subgoal("   ")

    assert not result.success
    assert result.error_type == "validation_error"


@pytest.mark.asyncio
async def test_add_subgoal_sequential_ids():
    from tools.subgoal import add_subgoal

    await add_subgoal("first")
    await add_subgoal("second")

    registry = get_registry()
    assert [s.id for s in registry.all()] == ["sg-1", "sg-2"]


# ── update_subgoal ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_subgoal_status_and_notes():
    from tools.subgoal import add_subgoal, update_subgoal

    await add_subgoal("write hello.py")
    result = await update_subgoal(
        json.dumps({"id": "sg-1", "status": "in_progress", "notes": "started the file"})
    )

    assert result.success
    subgoal = get_registry().get("sg-1")
    assert subgoal is not None
    assert subgoal.status == "in_progress"
    assert subgoal.notes == "started the file"


@pytest.mark.asyncio
async def test_update_subgoal_complete():
    from tools.subgoal import add_subgoal, update_subgoal

    await add_subgoal("git init")
    result = await update_subgoal(json.dumps({"id": "sg-1", "status": "completed"}))

    assert result.success
    assert get_registry().get("sg-1").status == "completed"
    assert "✅" in result.content


@pytest.mark.asyncio
async def test_update_subgoal_not_found():
    from tools.subgoal import update_subgoal

    result = await update_subgoal(json.dumps({"id": "sg-99", "status": "completed"}))

    assert not result.success
    assert result.error_type == "not_found"


@pytest.mark.asyncio
async def test_update_subgoal_invalid_status():
    from tools.subgoal import add_subgoal, update_subgoal

    await add_subgoal("x")
    result = await update_subgoal(json.dumps({"id": "sg-1", "status": "banana"}))

    assert not result.success
    assert result.error_type == "validation_error"
    assert get_registry().get("sg-1").status == "pending"  # unchanged


@pytest.mark.asyncio
async def test_update_subgoal_requires_id():
    from tools.subgoal import update_subgoal

    result = await update_subgoal(json.dumps({"status": "completed"}))

    assert not result.success
    assert result.error_type == "validation_error"


# ── create_plan ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_plan_from_markdown_list():
    from tools.subgoal import create_plan

    result = await create_plan("1. create dir\n2. write hello.py\n3. git init")

    assert result.success
    registry = get_registry()
    assert [s.description for s in registry.all()] == [
        "create dir",
        "write hello.py",
        "git init",
    ]
    assert [s.id for s in registry.all()] == ["sg-1", "sg-2", "sg-3"]
    assert "3 subgoals" in result.content


@pytest.mark.asyncio
async def test_create_plan_from_json_steps():
    from tools.subgoal import create_plan

    payload = json.dumps({"steps": ["a", "b"]})
    result = await create_plan(payload)

    assert result.success
    assert [s.description for s in get_registry().all()] == ["a", "b"]


@pytest.mark.asyncio
async def test_create_plan_requires_steps():
    from tools.subgoal import create_plan

    result = await create_plan("")

    assert not result.success
    assert result.error_type == "validation_error"


# ── Per-run isolation ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scratchpad_does_not_leak_across_runs():
    """A run that ends without clearing its scratchpad must not leak it."""
    from tools.subgoal import create_plan

    # Run 1: build a plan, then the run ends (loop reset) without clearing
    await create_plan("1. step one\n2. step two")
    assert len(get_registry()) == 2
    reset_subgoals()  # AgentLoop.run() does this at the start of the next run

    # Run 2: the scratchpad is empty — nothing from run 1 is visible
    assert len(get_registry()) == 0
    from tools.subgoal import update_subgoal

    result = await update_subgoal(json.dumps({"id": "sg-1", "status": "completed"}))
    assert not result.success
    assert result.error_type == "not_found"


@pytest.mark.asyncio
async def test_scratchpad_lists_are_ordered_and_rendered():
    from tools.subgoal import add_subgoal, update_subgoal

    await add_subgoal("first")
    await add_subgoal("second")
    await update_subgoal(json.dumps({"id": "sg-1", "status": "completed"}))

    registry = get_registry()
    markdown = registry.as_markdown()
    assert markdown.index("sg-1") < markdown.index("sg-2")
    assert "✅" in markdown
    assert "(completed)" in markdown
