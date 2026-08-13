"""
Tests for the structured planner parser (Session 180 — F3).

The parser converts the free-text plan output from `_plan_stream`
(loop.py:4354) into a typed `list[PlanNode]`. Each node has:
  - id (stable: "node-1", "node-2", ...)
  - subgoal (the action description)
  - depends_on (parsed from "after X" / "depends on X" syntax)
  - success_criteria (parsed from "(criteria: ...)" suffixes or
    fallback_criteria param)

These tests pin the parser's behavior across the plan formats the
LLM actually emits: numbered, bulleted, with/without dependencies,
with/without per-node criteria.
"""

from __future__ import annotations

from core.agent.plan_parser import (
    advance_node_for_step,
    parse_plan_to_nodes,
)
from core.agent.task_state import PlanNode

# ── parse_plan_to_nodes — basic shapes ───────────────────────────────────────


def test_empty_plan_returns_empty_list():
    """Empty / whitespace input → empty list."""
    assert parse_plan_to_nodes("") == []
    assert parse_plan_to_nodes("   ") == []
    assert parse_plan_to_nodes("\n\n") == []


def test_no_plan_lines_returns_empty_list():
    """Free-form paragraphs with no numbered/bulleted lines → empty."""
    text = (
        "This is a paragraph describing the task. It has no list.\n\n"
        "Another paragraph. Still no list."
    )
    assert parse_plan_to_nodes(text) == []


def test_numbered_plan_parsed():
    """Standard '1. xxx' / '2. yyy' format."""
    text = (
        "1. Read the file at /tmp/foo\n"
        "2. Edit the second line\n"
        "3. Run the test suite"
    )
    nodes = parse_plan_to_nodes(text)
    assert len(nodes) == 3
    assert [n.id for n in nodes] == ["node-1", "node-2", "node-3"]
    assert "Read the file" in nodes[0].subgoal
    assert "Edit the second line" in nodes[1].subgoal
    assert "Run the test suite" in nodes[2].subgoal
    # No dependencies declared
    assert all(n.depends_on == [] for n in nodes)


def test_bulleted_plan_parsed():
    """Bulleted '- xxx' / '* yyy' format."""
    text = (
        "- Read the file\n"
        "* Edit the file\n"
        "- Run tests"
    )
    nodes = parse_plan_to_nodes(text)
    assert len(nodes) == 3
    assert "Read the file" in nodes[0].subgoal
    assert "Edit the file" in nodes[1].subgoal


def test_step_prefix_parsed():
    """'Step 1: xxx' / 'Step 2 — yyy' format."""
    text = (
        "Step 1: Read the file\n"
        "Step 2 — Edit the file"
    )
    nodes = parse_plan_to_nodes(text)
    assert len(nodes) == 2
    assert "Read the file" in nodes[0].subgoal


def test_mixed_numbering_parsed():
    """Mixed '1.' / '2)' / '3:' formats."""
    text = (
        "1. First step\n"
        "2) Second step\n"
        "3: Third step"
    )
    nodes = parse_plan_to_nodes(text)
    assert len(nodes) == 3
    assert "First" in nodes[0].subgoal
    assert "Second" in nodes[1].subgoal
    assert "Third" in nodes[2].subgoal


# ── Dependencies ────────────────────────────────────────────────────────────


def test_depends_on_after_syntax():
    """'after node-1' syntax."""
    text = (
        "1. Read the file\n"
        "2. Edit the file (after node-1)\n"
    )
    nodes = parse_plan_to_nodes(text)
    assert len(nodes) == 2
    assert nodes[1].depends_on == ["node-1"]
    # The 'after node-1' suffix is stripped from the subgoal text
    assert "after node-1" not in nodes[1].subgoal


def test_depends_on_depends_syntax():
    """'depends on node-1' syntax."""
    text = (
        "1. Setup\n"
        "2. Run depends on node-1"
    )
    nodes = parse_plan_to_nodes(text)
    assert nodes[1].depends_on == ["node-1"]


def test_depends_on_multiple():
    """Multiple dependencies: 'after node-1, node-2'."""
    text = (
        "1. First\n"
        "2. Second\n"
        "3. Third (after node-1, node-2)"
    )
    nodes = parse_plan_to_nodes(text)
    assert nodes[2].depends_on == ["node-1", "node-2"]


def test_depends_on_ignores_unknown_ids():
    """References to non-existent ids are dropped (e.g. 'after the user confirms')."""
    text = (
        "1. Setup\n"
        "2. Run after the user confirms"
    )
    nodes = parse_plan_to_nodes(text)
    assert nodes[1].depends_on == []  # "the user confirms" isn't a node id


def test_self_reference_dropped():
    """A node depending on itself is dropped (cycle prevention)."""
    text = "1. Self-dependent (after node-1)"
    nodes = parse_plan_to_nodes(text)
    assert nodes[0].depends_on == []


# ── Per-node success criteria ───────────────────────────────────────────────


def test_criteria_in_parens():
    """'(criteria: ...)' suffix."""
    text = "1. Write file (criteria: file exists with content)"
    nodes = parse_plan_to_nodes(text)
    assert len(nodes) == 1
    assert "file exists with content" in nodes[0].success_criteria


def test_verifies_in_brackets():
    """'[verifies: ...]' suffix."""
    text = "1. Run tests [verifies: pytest exits 0]"
    nodes = parse_plan_to_nodes(text)
    assert "pytest exits 0" in nodes[0].success_criteria


def test_multiple_criteria_in_one_block():
    """'(criteria: a; b; c)' → 3 criteria."""
    text = "1. Build (criteria: tests pass; lint clean; typecheck ok)"
    nodes = parse_plan_to_nodes(text)
    assert len(nodes[0].success_criteria) == 3
    assert "tests pass" in nodes[0].success_criteria
    assert "lint clean" in nodes[0].success_criteria
    assert "typecheck ok" in nodes[0].success_criteria


def test_fallback_criteria_applied_when_no_per_node():
    """When a node has no per-node criteria and fallback_criteria is
    provided, the fallback is applied to that node."""
    text = "1. Read file"
    nodes = parse_plan_to_nodes(
        text,
        fallback_criteria=["file content read without error"],
    )
    assert nodes[0].success_criteria == ["file content read without error"]


def test_fallback_does_not_override_per_node():
    """Per-node criteria take precedence over fallback."""
    text = "1. Read file (criteria: specific criterion)"
    nodes = parse_plan_to_nodes(
        text,
        fallback_criteria=["fallback criterion"],
    )
    assert nodes[0].success_criteria == ["specific criterion"]


def test_no_fallback_leaves_criteria_empty():
    """No per-node criteria and no fallback → empty list."""
    text = "1. Read file"
    nodes = parse_plan_to_nodes(text)
    assert nodes[0].success_criteria == []


# ── PlanNode.is_ready ──────────────────────────────────────────────────────


def test_node_is_ready_when_deps_met():
    """A pending node with all deps completed is ready."""
    node = PlanNode(id="node-2", subgoal="X", depends_on=["node-1"])
    assert node.is_ready({"node-1"}) is True


def test_node_not_ready_when_deps_unmet():
    """A pending node with unmet deps is not ready."""
    node = PlanNode(id="node-2", subgoal="X", depends_on=["node-1", "node-3"])
    assert node.is_ready({"node-1"}) is False  # node-3 missing


def test_node_not_ready_when_already_in_progress():
    """An in_progress node is not ready (already started)."""
    node = PlanNode(id="node-1", subgoal="X", status="in_progress")
    assert node.is_ready(set()) is False


def test_node_not_ready_when_completed():
    """A completed node is not ready."""
    node = PlanNode(id="node-1", subgoal="X", status="completed")
    assert node.is_ready(set()) is False


# ── advance_node_for_step ───────────────────────────────────────────────────


def test_advance_node_marks_completed_on_success():
    """When a tool's input/observation matches a pending node, the node
    transitions to completed when succeeded=True."""
    nodes = [
        PlanNode(id="node-1", subgoal="Read the file at /home/z/project/foo.py"),
        PlanNode(id="node-2", subgoal="Edit the second line"),
    ]
    advanced = advance_node_for_step(
        nodes,
        tool_name="file_task",
        tool_input='{"path": "/home/z/project/foo.py"}',
        observation="file content read",
        succeeded=True,
    )
    assert advanced == "node-1"
    assert nodes[0].status == "completed"
    assert nodes[1].status == "pending"


def test_advance_node_marks_failed_on_failure():
    """When the tool failed, the matched node transitions to failed."""
    nodes = [
        PlanNode(id="node-1", subgoal="Read the file at /home/z/project/foo.py"),
    ]
    advanced = advance_node_for_step(
        nodes,
        tool_name="file_task",
        tool_input='{"path": "/home/z/project/foo.py"}',
        observation="error: file not found",
        succeeded=False,
    )
    assert advanced == "node-1"
    assert nodes[0].status == "failed"
    assert "file not found" in nodes[0].error


def test_advance_node_returns_none_when_no_match():
    """When no node's tokens appear in the tool input, no node advances.

    'ls /tmp' shouldn't match a node about reading a specific file at
    /home/z/project/foo.py — the common tokens (file, project, etc.)
    are filtered out, and 'foo' isn't in the tool input.
    """
    nodes = [
        PlanNode(id="node-1", subgoal="Read the file at /home/z/project/foo.py"),
    ]
    advanced = advance_node_for_step(
        nodes,
        tool_name="shell",
        tool_input='{"command": "ls /tmp"}',
        observation="file1\nfile2",
        succeeded=True,
    )
    assert advanced is None
    assert nodes[0].status == "pending"


def test_advance_node_skips_completed_nodes():
    """Already-completed nodes are not re-advanced."""
    nodes = [
        PlanNode(id="node-1", subgoal="Read /home/z/project/foo.py", status="completed"),
        PlanNode(id="node-2", subgoal="Read /home/z/project/foo.py too"),
    ]
    advanced = advance_node_for_step(
        nodes,
        tool_name="file_task",
        tool_input='{"path": "/home/z/project/foo.py"}',
        observation="content",
        succeeded=True,
    )
    # node-2 was the next matching pending node
    assert advanced == "node-2"
    assert nodes[0].status == "completed"  # unchanged
    assert nodes[1].status == "completed"


def test_advance_node_empty_list_returns_none():
    """Empty nodes list → None."""
    assert advance_node_for_step(
        [],
        tool_name="shell",
        tool_input="ls",
        observation="output",
        succeeded=True,
    ) is None


# ── Integration: realistic LLM plan output ──────────────────────────────────


def test_realistic_llm_plan_parsed():
    """A realistic plan output from a small LLM, including reasoning
    preamble + numbered steps."""
    text = """I'll start by reading the file, then editing it, then running the tests.

1. Read the file at /tmp/foo.py to understand its current state
2. Edit the file to fix the bug (criteria: file edited without error)
3. Run pytest (after node-2) [verifies: pytest exits 0]

Let me know if you'd like me to proceed."""
    nodes = parse_plan_to_nodes(text)
    assert len(nodes) == 3
    assert nodes[0].id == "node-1"
    assert "Read the file" in nodes[0].subgoal
    assert nodes[1].success_criteria == ["file edited without error"]
    assert nodes[2].depends_on == ["node-2"]
    assert "pytest exits 0" in nodes[2].success_criteria
