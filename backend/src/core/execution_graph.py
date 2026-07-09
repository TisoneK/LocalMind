"""
Execution Graph — DAG-based capability execution model.

Nodes represent individual capability invocations. Edges represent
dependencies (node A depends on node B means A waits for B to complete).
Nodes without dependencies can run in parallel.

The graph is built by ThinkingDispatcher (Layer 2), validated and
enhanced by the Planning layer (Layer 3), and executed by the
Execution layer (Layer 4).

Example DAGs:

  "What are today's EPL fixtures?":
    search_epl (web_search) -> synthesize (synthesis)
    Wave 1: [search_epl]
    Wave 2: [synthesize]

  "Compare my specs with game requirements":
    sysinfo_query (sysinfo)  --> compare (comparison)
    search_reqs  (web_search) -->
    Wave 1: [sysinfo_query, search_reqs]  (parallel)
    Wave 2: [compare]
"""
from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from core.models import (
    CAPABILITY_TO_INTENT,
    Capability,
    ExecutionConstraints,
    Intent,
    ToolResult,
)

logger = logging.getLogger(__name__)


# ── Node Status ──────────────────────────────────────────────────────

class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# ── Execution Node ───────────────────────────────────────────────────

class ExecutionNode(BaseModel):
    """A single node in the execution DAG.

    Each node represents one capability invocation. Nodes with
    empty depends_on lists can start immediately (Wave 1). Nodes
    that depend on other nodes wait for their predecessors.

    The `optional` flag allows best-effort execution: if an optional
    node fails, downstream nodes can still run (they should handle
    missing results gracefully).
    """
    id: str                                    # Unique node identifier
    capability: Capability                     # What this node does
    intent: Intent                             # Derived Intent for tool dispatch
    tool_name: str = ""                        # Tool function name (e.g., "web_search")
    tool_args: dict = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    status: NodeStatus = NodeStatus.PENDING
    result: Optional[ToolResult] = None
    retry_count: int = 0
    max_retries: int = 1
    label: str = ""                            # Human-readable label for UI
    optional: bool = False                     # Failure doesn't block downstream

    class Config:
        arbitrary_types_allowed = True


# ── Execution Graph ──────────────────────────────────────────────────

class ExecutionGraph(BaseModel):
    """DAG of execution nodes with dependency tracking.

    The graph supports:
    - Topological ordering (Kahn's algorithm)
    - Parallel group detection (wave-based execution)
    - Status tracking (pending, running, completed, failed, skipped)
    - Cycle detection (via topological order length check)
    """
    nodes: list[ExecutionNode] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True

    def add_node(self, node: ExecutionNode) -> None:
        self.nodes.append(node)

    def get_node(self, node_id: str) -> Optional[ExecutionNode]:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def ready_nodes(self) -> list[ExecutionNode]:
        """Return nodes whose dependencies are all completed."""
        completed_ids = {
            n.id for n in self.nodes if n.status == NodeStatus.COMPLETED
        }
        return [
            n for n in self.nodes
            if n.status == NodeStatus.PENDING
            and all(dep in completed_ids for dep in n.depends_on)
        ]

    def is_complete(self) -> bool:
        """True when all non-optional nodes are completed or skipped."""
        return all(
            n.status in (NodeStatus.COMPLETED, NodeStatus.SKIPPED)
            for n in self.nodes
            if not n.optional
        )

    def has_failed_required(self) -> bool:
        """True when any required (non-optional) node has failed."""
        return any(
            n.status == NodeStatus.FAILED
            for n in self.nodes
            if not n.optional
        )

    def completed_results(self) -> dict[str, ToolResult]:
        """Map of node_id -> ToolResult for completed nodes."""
        return {
            n.id: n.result
            for n in self.nodes
            if n.status == NodeStatus.COMPLETED and n.result is not None
        }

    def has_cycle(self) -> bool:
        """Detect cycles via topological sort (Kahn's algorithm)."""
        in_degree = {n.id: len(n.depends_on) for n in self.nodes}
        node_ids = {n.id for n in self.nodes}
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        visited = 0

        while queue:
            nid = queue.pop(0)
            visited += 1
            for n in self.nodes:
                if nid in n.depends_on:
                    in_degree[n.id] -= 1
                    if in_degree[n.id] == 0:
                        queue.append(n.id)

        return visited < len(self.nodes)

    def topological_order(self) -> list[ExecutionNode]:
        """Return nodes in topological order (Kahn's algorithm)."""
        in_degree = {n.id: len(n.depends_on) for n in self.nodes}
        node_map = {n.id: n for n in self.nodes}
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        order: list[ExecutionNode] = []

        while queue:
            nid = queue.pop(0)
            order.append(node_map[nid])
            for n in self.nodes:
                if nid in n.depends_on:
                    in_degree[n.id] -= 1
                    if in_degree[n.id] == 0:
                        queue.append(n.id)

        return order

    def parallel_groups(self) -> list[list[ExecutionNode]]:
        """Group nodes by execution wave (can run in parallel within a wave).

        Returns a list of waves. Each wave is a list of nodes that
        can execute concurrently since all their dependencies are
        satisfied by previous waves.
        """
        groups: list[list[ExecutionNode]] = []
        completed_ids: set[str] = set()
        remaining = {n.id for n in self.nodes}

        while remaining:
            ready = [
                n for n in self.nodes
                if n.id in remaining
                and all(dep in completed_ids for dep in n.depends_on)
            ]
            if not ready:
                break  # cycle or error
            groups.append(ready)
            for n in ready:
                completed_ids.add(n.id)
                remaining.discard(n.id)

        return groups

    def validate(self) -> list[str]:
        """Validate the graph structure. Returns list of error messages."""
        errors: list[str] = []
        node_ids = {n.id for n in self.nodes}

        # Check for missing dependency references
        for n in self.nodes:
            for dep in n.depends_on:
                if dep not in node_ids:
                    errors.append(f"Node '{n.id}' depends on non-existent node '{dep}'")

        # Check for cycles
        if self.has_cycle():
            errors.append("Graph contains a cycle")

        # Check for duplicate IDs
        seen_ids: set[str] = set()
        for n in self.nodes:
            if n.id in seen_ids:
                errors.append(f"Duplicate node ID: '{n.id}'")
            seen_ids.add(n.id)

        return errors


# ── Graph Execution Engine ───────────────────────────────────────────

async def execute_graph(
    graph: ExecutionGraph,
    constraints: ExecutionConstraints,
    obs=None,
) -> ExecutionGraph:
    """Execute an ExecutionGraph with bounded retries and timeouts.

    Executes in waves: all nodes in a wave can run in parallel.
    Sequential between waves. Stops if a required node fails.

    Args:
        graph: The execution graph to run
        constraints: Bounded execution parameters
        obs: Optional observability collector

    Returns:
        The same graph with nodes updated with results
    """

    for wave in graph.parallel_groups():
        if constraints.allow_parallel and len(wave) > 1:
            # Execute wave in parallel
            tasks = [
                _execute_node(node, constraints, obs)
                for node in wave
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for node, result in zip(wave, results):
                if isinstance(result, Exception):
                    node.status = NodeStatus.FAILED
                    node.result = ToolResult(
                        content=f"Error: {result}",
                        source=node.tool_name or node.capability.value,
                        success=False,
                        error_type="execution_error",
                        error_message=str(result),
                    )
                    logger.warning(f"[graph] node {node.id} failed in parallel wave: {result}")
        else:
            # Execute wave sequentially
            for node in wave:
                try:
                    await _execute_node(node, constraints, obs)
                except Exception as e:
                    node.status = NodeStatus.FAILED
                    logger.warning(f"[graph] node {node.id} failed: {e}")
                    if not node.optional:
                        break  # Stop on required node failure

        # Emit observability for wave completion
        if obs:
            completed_in_wave = [
                n.id for n in wave if n.status == NodeStatus.COMPLETED
            ]
            failed_in_wave = [
                n.id for n in wave if n.status == NodeStatus.FAILED
            ]
            obs.emit("graph_wave_complete",
                     completed=completed_in_wave,
                     failed=failed_in_wave)

        # Check if we should continue
        if graph.has_failed_required():
            logger.warning("[graph] required node failed — stopping execution")
            break

    # Mark remaining pending nodes as skipped
    for node in graph.nodes:
        if node.status == NodeStatus.PENDING:
            node.status = NodeStatus.SKIPPED

    return graph


async def _execute_node(
    node: ExecutionNode,
    constraints: ExecutionConstraints,
    obs=None,
) -> ExecutionNode:
    """Execute a single graph node with retry logic.

    Uses exponential backoff on retry. Per-tool timeout from
    constraints. Emits observability events for each attempt.
    """
    from tools import dispatch as tool_dispatch

    # Cognitive nodes don't dispatch to tools
    if node.capability in {
        Capability.REASONING, Capability.COMPARISON,
        Capability.SYNTHESIS, Capability.PLANNING, Capability.PREDICTION,
    }:
        node.status = NodeStatus.COMPLETED
        node.result = ToolResult(
            content="",
            source=node.capability.value,
            success=True,
            metadata={"cognitive": True},
        )
        return node

    # Tool nodes dispatch to the tool registry
    if not node.tool_name:
        node.tool_name = _capability_to_tool_name(node.capability)

    node.status = NodeStatus.RUNNING

    for attempt in range(node.max_retries + 1):
        try:
            # Serialize args for legacy dispatch
            args_str = _serialize_tool_args(node)
            result = await asyncio.wait_for(
                tool_dispatch(node.intent, args_str),
                timeout=constraints.timeout_per_tool_secs,
            )
            node.result = result
            node.status = NodeStatus.COMPLETED
            node.retry_count = attempt

            if obs:
                obs.emit("node_completed",
                         node_id=node.id,
                         capability=node.capability.value,
                         attempt=attempt)

            return node

        except asyncio.TimeoutError:
            logger.warning(f"[graph] node {node.id} timed out (attempt {attempt + 1})")
            if obs:
                obs.emit("node_timeout",
                         node_id=node.id,
                         attempt=attempt,
                         timeout=constraints.timeout_per_tool_secs)

        except Exception as e:
            logger.warning(f"[graph] node {node.id} failed: {e} (attempt {attempt + 1})")
            if obs:
                obs.emit("node_failed",
                         node_id=node.id,
                         error=str(e)[:80],
                         attempt=attempt)

        if attempt < node.max_retries:
            delay = constraints.tool_retry_base_delay * (2 ** attempt)
            await asyncio.sleep(delay)

    # All retries exhausted
    node.status = NodeStatus.FAILED
    node.result = ToolResult(
        content=f"Node '{node.id}' failed after {node.max_retries + 1} attempts",
        source=node.tool_name or node.capability.value,
        success=False,
        error_type="max_retries_exceeded",
    )
    return node


# ── Helper Functions ─────────────────────────────────────────────────

def _capability_to_tool_name(cap: Capability) -> str:
    """Map a Capability to its tool dispatch name."""
    _MAP: dict[Capability, str] = {
        Capability.WEB_SEARCH: "web_search",
        Capability.WEB_FETCH: "web_fetch",
        Capability.CODE_EXEC: "code_exec",
        Capability.SHELL: "shell",
        Capability.FILE_READ: "file_reader",
        Capability.FILE_WRITE: "file_writer",
        Capability.FILE_EDIT: "edit_file",
        Capability.MEMORY_STORE: "memory_tool",
        Capability.MEMORY_RETRIEVE: "memory_tool",
        Capability.SYSINFO: "sysinfo",
    }
    return _MAP.get(cap, cap.value)


def _serialize_tool_args(node: ExecutionNode) -> str:
    """Serialize ExecutionNode args into a string for legacy dispatch.

    The legacy tool dispatch layer expects a single string argument.
    This function serializes the structured args dict into a form
    the tool can parse.
    """
    if not node.tool_args:
        # For tools that use the message/query as input, fall back to label
        return node.label or ""
    # Use the first string value as the dispatch argument
    for key in ("query", "action", "goal", "path", "code", "content"):
        if key in node.tool_args:
            return str(node.tool_args[key])
    # Fallback: JSON-serialize the whole dict
    import json
    return json.dumps(node.tool_args)


def build_graph_from_plan_steps(
    steps: list[dict],
    default_max_retries: int = 1,
) -> ExecutionGraph:
    """Build an ExecutionGraph from the LLM's execution_plan.steps JSON.

    This is called by the ThinkingDispatcher to convert the
    structured JSON output into a proper DAG.
    """
    graph = ExecutionGraph()

    for step in steps:
        cap_str = step.get("capability", "")
        try:
            capability = Capability(cap_str)
        except ValueError:
            logger.warning(f"[graph] unknown capability '{cap_str}' — skipping step")
            continue

        # Derive intent from capability
        intent = CAPABILITY_TO_INTENT.get(capability, Intent.CHAT)

        # Get tool name
        tool_name = step.get("tool", "") or _capability_to_tool_name(capability)

        node = ExecutionNode(
            id=step.get("id", f"step_{len(graph.nodes)}"),
            capability=capability,
            intent=intent,
            tool_name=tool_name,
            tool_args=step.get("args", {}),
            depends_on=step.get("depends_on", []),
            max_retries=step.get("max_retries", default_max_retries),
            label=step.get("label", ""),
            optional=step.get("optional", False),
        )
        graph.add_node(node)

    # Validate the graph
    errors = graph.validate()
    if errors:
        logger.warning(f"[graph] validation errors: {errors}")

    return graph
