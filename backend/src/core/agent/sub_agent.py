"""
Sub-Agent Framework — v0.2 (Engine-integrated)

Provides the infrastructure for decomposing complex multi-domain tasks
into focused sub-tasks, each handled by a specialized agent instance.

Architecture:
    SubAgentRegistry — defines available sub-agents and their capabilities
    SubAgent — a focused agent with a scoped system prompt and tool subset
    TaskDecomposer — breaks a complex request into ordered sub-tasks
    should_use_sub_agents() — detects when sub-agent delegation is appropriate
    execute_sub_tasks() — runs a decomposition plan through the registry

v0.2 changes vs v0.1:
- Added should_use_sub_agents() — keyword-based + complexity heuristic that
  detects when a request needs multi-domain delegation. This prevents the
  overhead of decomposition on simple single-intent tasks.
- Added execute_sub_tasks() — orchestrator that runs sub-tasks in dependency
  order, feeding results from earlier tasks into later ones. Independent
  tasks run concurrently via asyncio.gather().
- SubAgent.run() now uses direct adapter.chat_with_tools() for tool-calling
  instead of the full AgentLoop (which carries too much context overhead for
  a focused sub-task).
- Integrated with Engine.process() — when should_use_sub_agents() returns
  True and the routing intent is multi-domain, the engine delegates to
  execute_sub_tasks() instead of the standard agent loop.
- Added SUB_AGENT_ENABLED flag for easy on/off without code changes.
- Added SUB_AGENT_MAX_SUBTASKS to cap decomposition depth.

Design decisions:
    - Sub-agents share the same adapter pool as the main agent (no separate
      model instances needed)
    - Each sub-agent gets a minimal context: its persona prompt + the sub-task
      prompt + relevant results from previous sub-tasks. This prevents context
      overflow.
    - Sub-agent results are plain text (not streamed) — the main agent
      assembles the final streamed response.
    - Decomposition is opt-in: only complex multi-domain requests trigger it.
      Simple requests (single intent, short message) always use the standard
      agent loop path. This avoids unnecessary LLM calls for decomposition.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from core.models import Intent

# Lazy imports to avoid circular dependency — these are imported inside
# functions that need them rather than at module level.
# from adapters.ollama import ToolCallResult, MultiToolCallResult
# from tools import dispatch

logger = logging.getLogger(__name__)


# ── Feature flags ────────────────────────────────────────────────────────────

SUB_AGENT_ENABLED: bool = True
"""Master switch for sub-agent delegation. Set False to bypass entirely."""

SUB_AGENT_MAX_SUBTASKS: int = 4
"""Maximum sub-tasks in a decomposition. Prevents runaway decomposition
on vague or overly broad requests."""

SUB_AGENT_MAX_ITERATIONS: int = 4
"""Max think→act→observe cycles per sub-agent. Lower than the main loop
because sub-tasks are focused and should complete quickly."""

SUB_AGENT_MIN_MESSAGE_LENGTH: int = 40
"""Minimum message length (chars) to even consider sub-agent delegation.
Short messages are almost always single-intent and don't need decomposition."""


# ── Sub-Agent Types ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SubAgentType:
    """Definition of a specialized sub-agent."""

    name: str
    description: str
    persona: str
    allowed_intents: frozenset[Intent]
    allowed_tools: frozenset[str]


# Pre-defined sub-agent types. Each has a focused persona and a restricted
# set of tools that prevents scope creep (e.g., the Researcher shouldn't
# be writing files, the Coder shouldn't be doing web searches).

CODER_AGENT = SubAgentType(
    name="coder",
    description="Writes, edits, and debugs code. Runs Python and shell commands.",
    persona=(
        "You are the Coder — a focused coding agent. Your only job is to write "
        "correct, complete, runnable code and verify it works. You don't explain "
        "your approach — you just write the code, test it, and report the result. "
        "If the code fails, you fix it and try again. You don't give up."
    ),
    allowed_intents=frozenset({Intent.CODE_EXEC, Intent.FILE_WRITE, Intent.FILE_EDIT, Intent.FILE_TASK, Intent.SHELL}),
    allowed_tools=frozenset({"code_exec", "file_write", "edit_file", "file_task", "shell", "sysinfo"}),
)

RESEARCHER_AGENT = SubAgentType(
    name="researcher",
    description="Searches the web and synthesizes information from multiple sources.",
    persona=(
        "You are the Researcher — a focused information-gathering agent. Your job is to "
        "find accurate, current information and synthesize it into a clear summary. You "
        "always cite your sources. You distinguish between facts and opinions. If you "
        "can't find a definitive answer, you say so rather than guessing."
    ),
    allowed_intents=frozenset({Intent.WEB_SEARCH, Intent.FILE_TASK}),
    allowed_tools=frozenset({"web_search", "file_task", "sysinfo"}),
)

WRITER_AGENT = SubAgentType(
    name="writer",
    description="Creates and edits documents, configs, and content files.",
    persona=(
        "You are the Writer — a focused content-creation agent. Your job is to produce "
        "well-structured, complete files. You write the entire file in one shot — no "
        "placeholders, no TODOs, no partial content. Every line is intentional. You "
        "match the existing style when editing, and establish clear structure when creating."
    ),
    allowed_intents=frozenset({Intent.FILE_WRITE, Intent.FILE_EDIT, Intent.FILE_TASK}),
    allowed_tools=frozenset({"file_write", "edit_file", "file_task", "sysinfo"}),
)

OPERATOR_AGENT = SubAgentType(
    name="operator",
    description="Runs system commands, manages files, and checks system state.",
    persona=(
        "You are the Operator — a focused system-management agent. Your job is to "
        "execute system commands accurately and report exact results. You never "
        "fabricate output. You use the right commands for the OS. You verify before "
        "destructive operations. You report exactly what the tools return — nothing more."
    ),
    allowed_intents=frozenset({Intent.SHELL, Intent.FILE_TASK, Intent.SYSINFO}),
    allowed_tools=frozenset({"shell", "file_task", "sysinfo"}),
)

ANALYST_AGENT = SubAgentType(
    name="analyst",
    description="Analyzes data, computes statistics, and produces data-driven insights.",
    persona=(
        "You are the Analyst — a focused data-analysis agent. Your job is to "
        "examine data, run computations, and produce clear, evidence-based "
        "insights. You always show your work — code, calculations, and "
        "assumptions. You distinguish between correlation and causation. You "
        "note sample sizes and limitations. You never present estimates as "
        "exact measurements."
    ),
    allowed_intents=frozenset({Intent.CODE_EXEC, Intent.FILE_TASK, Intent.SHELL}),
    allowed_tools=frozenset({"code_exec", "file_task", "shell", "sysinfo"}),
)


# ── Registry ────────────────────────────────────────────────────────────────


class SubAgentRegistry:
    """Registry of available sub-agent types."""

    def __init__(self):
        self._agents: dict[str, SubAgentType] = {}
        # Register built-in agents
        for agent in [CODER_AGENT, RESEARCHER_AGENT, WRITER_AGENT, OPERATOR_AGENT, ANALYST_AGENT]:
            self.register(agent)

    def register(self, agent: SubAgentType) -> None:
        self._agents[agent.name] = agent

    def get(self, name: str) -> Optional[SubAgentType]:
        return self._agents.get(name)

    def list_agents(self) -> list[SubAgentType]:
        return list(self._agents.values())

    def agent_for_intent(self, intent: Intent) -> Optional[SubAgentType]:
        """Find the best sub-agent for a given intent."""
        for agent in self._agents.values():
            if intent in agent.allowed_intents:
                return agent
        return None


# ── Sub-Agent Instance ──────────────────────────────────────────────────────


@dataclass
class SubAgentResult:
    """Result from a sub-agent execution."""

    agent_name: str
    success: bool
    output: str
    iterations_used: int = 0
    latency_ms: int = 0


class SubAgent:
    """
    A focused agent with a scoped system prompt and tool subset.

    Uses direct adapter.chat() for focused sub-tasks. Does NOT use the full
    AgentLoop — the loop's planning, verification, and reflection phases add
    latency that's unnecessary for a focused sub-task with a clear objective.
    Instead, this uses a simple 2-turn pattern: system prompt + user prompt,
    with one tool-calling round if needed.

    Designed for delegation from the main agent — not for direct user interaction.
    """

    def __init__(self, agent_type: SubAgentType, adapter):
        self._type = agent_type
        self._adapter = adapter

    def _load_skill_for_agent(self) -> str:
        """Load the skill .md file matching this sub-agent's primary intent."""
        from pathlib import Path

        _SKILL_MAP = {
            "coder": "coding",
            "researcher": "research",
            "writer": "writing",
            "operator": "shell",
            "analyst": "coding",  # analyst uses coding skill for data analysis
            "debugger": "debugging",
        }
        skill_name = _SKILL_MAP.get(self._type.name, "")
        if not skill_name:
            return ""
        skill_path = Path(__file__).parent.parent / "prompts" / "skills" / f"{skill_name}.md"
        if skill_path.exists():
            try:
                return skill_path.read_text()
            except Exception:
                return ""
        return ""

    async def run(
        self,
        prompt: str,
        context: str = "",
        max_iterations: int = SUB_AGENT_MAX_ITERATIONS,
    ) -> SubAgentResult:
        """
        Run a focused sub-task and return the result.

        Args:
            prompt: The specific sub-task to execute.
            context: Additional context from previous sub-tasks.
            max_iterations: Max tool-calling iterations.

        Returns:
            SubAgentResult with the output or error.
        """
        from adapters.ollama import MultiToolCallResult, ToolCallResult
        from tools import dispatch

        t0 = time.monotonic()

        # Build a minimal system prompt scoped to this sub-agent's persona
        # P9: Inject skill .md content for domain expertise
        _skill_content = self._load_skill_for_agent()
        _skill_section = ""
        if _skill_content:
            # Cap at 1500 chars to avoid context overflow in sub-agent
            _truncated = _skill_content[:1500]
            if len(_skill_content) > 1500:
                _truncated += "\n[...expertise truncated for focus]"
            _skill_section = f"\n## Domain Expertise\n{_truncated}\n"

        system_prompt = (
            f"{self._type.persona}\n\n"
            f"{_skill_section}"
            f"Available tools: {', '.join(sorted(self._type.allowed_tools))}\n\n"
            f"CRITICAL RULES:\n"
            f"- Only use tools in your allowed list\n"
            f"- Report exactly what tools return — never fabricate\n"
            f"- When done, respond with your final answer in plain text\n"
        )
        if context:
            # Cap context to prevent overflow — sub-agents need focused context
            _ctx = context[:2000]
            if len(context) > 2000:
                _ctx += "\n[...context truncated]"
            system_prompt += f"\nContext from previous steps:\n{_ctx}\n"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        # Simple tool-calling loop: max_iterations rounds of
        # chat_with_tools → dispatch → append results → continue
        full_text = ""
        iterations = 0
        try:
            for iteration in range(max_iterations):
                iterations = iteration + 1

                # Try tool-calling first (for models that support it)
                try:
                    result = await self._adapter.chat_with_tools(
                        messages=messages,
                        tools=_build_tool_defs(self._type.allowed_tools),
                        temperature=0.2,
                        intent=prompt[:50],
                    )

                    # Handle multi-tool calls
                    if isinstance(result, MultiToolCallResult):
                        # Process each tool call
                        for tc in result.calls:
                            _obs_text = await _dispatch_sub_agent_tool(tc.tool_name, tc.tool_args, dispatch)
                            messages.append(
                                {
                                    "role": "assistant",
                                    "content": result.raw_content or "",
                                    "tool_calls": [
                                        {
                                            "id": f"sa_{iteration}_{tc.tool_name}",
                                            "type": "function",
                                            "function": {
                                                "name": tc.tool_name,
                                                "arguments": json.dumps(tc.tool_args),
                                            },
                                        }
                                    ],
                                }
                            )
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": f"sa_{iteration}_{tc.tool_name}",
                                    "content": _obs_text[:3000],
                                }
                            )
                        # Continue to next iteration for the model to process results
                        continue

                    # Handle single tool call
                    if isinstance(result, ToolCallResult):
                        tc_name = result.tool_name
                        tc_args = result.tool_args

                        # Validate tool is in allowed set
                        if tc_name not in self._type.allowed_tools:
                            messages.append(
                                {
                                    "role": "user",
                                    "content": f"Tool '{tc_name}' not available. Respond with your best answer without tools.",
                                }
                            )
                            continue

                        obs_text = await _dispatch_sub_agent_tool(tc_name, tc_args, dispatch)

                        # If the model produced text before the tool call, capture it
                        if result.raw_content:
                            full_text += result.raw_content

                        # Add tool result to messages
                        messages.append(
                            {
                                "role": "assistant",
                                "content": result.raw_content or "",
                                "tool_calls": [
                                    {
                                        "id": f"sa_{iteration}_{tc_name}",
                                        "type": "function",
                                        "function": {
                                            "name": tc_name,
                                            "arguments": json.dumps(tc_args),
                                        },
                                    }
                                ],
                            }
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": f"sa_{iteration}_{tc_name}",
                                "content": obs_text[:3000],
                            }
                        )
                        continue

                except (AttributeError, TypeError):
                    # Adapter doesn't support chat_with_tools — fall back to plain chat
                    pass

                # No tool call (or fallback) — stream the final text answer
                chunks = []
                async for chunk in self._adapter.chat(messages, temperature=0.2):
                    if hasattr(chunk, "error") and chunk.error:
                        logger.warning("[sub_agent] adapter error: %s", chunk.error[:120])
                        break
                    chunks.append(chunk.text if hasattr(chunk, "text") else str(chunk))
                full_text += "".join(chunks)
                break

        except Exception as e:
            logger.error("[sub_agent] %s failed: %s", self._type.name, e)
            return SubAgentResult(
                agent_name=self._type.name,
                success=False,
                output=f"Sub-agent error: {e}",
                iterations_used=iterations,
                latency_ms=round((time.monotonic() - t0) * 1000),
            )

        return SubAgentResult(
            agent_name=self._type.name,
            success=True,
            output=full_text.strip(),
            iterations_used=iterations,
            latency_ms=round((time.monotonic() - t0) * 1000),
        )


# ── Task Decomposer ─────────────────────────────────────────────────────────


@dataclass
class SubTask:
    """A decomposed sub-task with an assigned agent type."""

    id: int
    agent_name: str
    prompt: str
    depends_on: list[int] = field(default_factory=list)  # IDs of tasks this depends on


_DECOMPOSITION_PROMPT = """You are a task decomposer for LocalMind. Break down the user's complex request into focused sub-tasks.

Available sub-agents:
{agent_list}

Rules:
- Each sub-task should be handled by exactly ONE sub-agent
- Order tasks by dependency — earlier tasks produce output that later tasks need
- Keep each sub-task focused — one clear objective per task
- If the request is simple enough for one agent, say so with a single task
- Maximum {max_subtasks} sub-tasks — if you need more, the request is too broad
- For data analysis tasks (statistics, computation, CSV processing), use the "analyst" agent
- For code + documentation tasks, use "coder" for code and "writer" for docs

Respond in this exact JSON format:
[
  {{
    "id": 1,
    "agent": "coder",
    "prompt": "Write a Flask app with /api/todos endpoint...",
    "depends_on": []
  }},
  {{
    "id": 2,
    "agent": "writer",
    "prompt": "Create a README.md for the todo app based on the code from step 1...",
    "depends_on": [1]
  }}
]

User request: {request}"""


async def decompose_task(
    request: str,
    registry: SubAgentRegistry,
    adapter,
) -> list[SubTask]:
    """
    Use an LLM call to decompose a complex request into sub-tasks.

    Returns a list of SubTask objects ordered by dependency.
    If decomposition fails, returns a single task using the best-matching agent.
    If the decomposition returns only one sub-task, sub-agent overhead is
    unnecessary — the caller should fall back to the standard agent loop.
    """
    agent_list = "\n".join(f"- {a.name}: {a.description}" for a in registry.list_agents())

    messages = [
        {
            "role": "system",
            "content": _DECOMPOSITION_PROMPT.format(
                agent_list=agent_list,
                request=request,
                max_subtasks=SUB_AGENT_MAX_SUBTASKS,
            ),
        },
        {"role": "user", "content": request},
    ]

    try:
        chunks = []
        async for chunk in adapter.chat(messages, temperature=0.0):
            if hasattr(chunk, "error") and chunk.error:
                logger.warning("[sub_agent] adapter error: %s", chunk.error[:120])
                break
            chunks.append(chunk.text if hasattr(chunk, "text") else str(chunk))

        raw = "".join(chunks).strip()

        # Extract JSON from the response (model may wrap it in markdown)
        json_start = raw.find("[")
        json_end = raw.rfind("]") + 1
        if json_start >= 0 and json_end > json_start:
            json_str = raw[json_start:json_end]
            parsed = json.loads(json_str)

            sub_tasks = []
            for item in parsed[:SUB_AGENT_MAX_SUBTASKS]:
                agent_name = item.get("agent", "coder")
                sub_tasks.append(
                    SubTask(
                        id=item.get("id", len(sub_tasks) + 1),
                        agent_name=agent_name,
                        prompt=item.get("prompt", ""),
                        depends_on=item.get("depends_on", []),
                    )
                )

            # Validate: if all sub-tasks use the same agent, this isn't
            # really multi-domain — fall back to single agent loop
            unique_agents = set(st.agent_name for st in sub_tasks)
            if len(unique_agents) <= 1 and len(sub_tasks) <= 2:
                logger.info(
                    "[decomposer] single-domain decomposition (%s) — falling back to standard agent loop",
                    unique_agents,
                )
                return []

            return sub_tasks

    except (json.JSONDecodeError, Exception) as e:
        logger.warning("[decomposer] failed: %s — falling back to single task", e)

    # Fallback: return empty list — caller will use standard agent loop
    return []


# ── Complexity Detection ─────────────────────────────────────────────────────

# Multi-domain signals: keywords that indicate the request spans multiple
# tool domains (code + writing, search + code, system + writing, etc.)
_MULTI_DOMAIN_PATTERNS = [
    # Build + document
    re.compile(
        r"\b(?:build|create|make|develop|implement|write|set up)\s+.*\b(?:and|then|also|plus|with)\s+.*\b(?:readme|doc|documentation|guide|tutorial)\b",
        re.IGNORECASE,
    ),
    # Search + code
    re.compile(
        r"\b(?:search|find|look up|research)\s+.*\b(?:and|then)\s+.*\b(?:code|script|program|implement|write|build)\b",
        re.IGNORECASE,
    ),
    # Code + test
    re.compile(
        r"\b(?:write|create|build|implement)\s+.*\b(?:and|then)\s+.*\b(?:test|run|verify|check)\b",
        re.IGNORECASE,
    ),
    # Setup project (implies multiple domains)
    re.compile(
        r"\b(?:set up|setup|initialize|scaffold|bootstrap)\s+(?:a\s+)?(?:project|app|application|workspace|environment)\b",
        re.IGNORECASE,
    ),
    # Full-stack patterns
    re.compile(r"\b(?:full.?stack|front.?end.*back.?end|client.*server|api.*ui)\b", re.IGNORECASE),
    # Multi-file operations
    re.compile(
        r"\b(?:create|write|update)\s+(?:multiple|several|these)\s+(?:files|scripts|configs)\b",
        re.IGNORECASE,
    ),
    # Research + write
    re.compile(
        r"\b(?:research|investigate|analyze)\s+.*\b(?:and|then)\s+.*\b(?:write|create|document|report)\b",
        re.IGNORECASE,
    ),
    # Deploy patterns
    re.compile(
        r"\b(?:deploy|publish|release)\s+.*\b(?:and|then)\s+.*\b(?:test|verify|check|monitor)\b",
        re.IGNORECASE,
    ),
    # Data analysis + report
    re.compile(
        r"\b(?:analyze|analyse|compute|calculate|process)\s+.*\b(?:and|then)\s+.*\b(?:report|document|visualize|chart|graph|summary)\b",
        re.IGNORECASE,
    ),
    # Code + analysis
    re.compile(
        r"\b(?:write|create|build)\s+.*\b(?:and|then)\s+.*\b(?:analyze|analyse|compute|process|test|benchmark)\b",
        re.IGNORECASE,
    ),
]

# Exclusion patterns: things that LOOK multi-domain but are actually single-intent
_EXCLUSION_PATTERNS = [
    re.compile(r"\b(?:just|only|simply)\s+(?:search|find|read|check|run)\b", re.IGNORECASE),
    re.compile(r"\bwhat (?:is|are)\b", re.IGNORECASE),
    re.compile(r"^\s*(?:how|why|when|where|who)\s", re.IGNORECASE),
]


def should_use_sub_agents(
    message: str,
    effective_intent: Intent,
    confidence: float,
) -> bool:
    """
    Decide whether a request should be delegated to sub-agents.

    Returns True when the request is complex enough to benefit from
    multi-domain decomposition. Returns False for simple, single-intent
    requests that the standard agent loop handles well.

    Heuristic:
    1. Gate on minimum message length (short messages are almost always simple)
    2. Check exclusion patterns (questions, simple requests)
    3. Check for multi-domain keyword patterns
    4. Check for intent + length heuristics (long FILE_WRITE with research terms)

    This function is intentionally conservative: it's better to miss a
    decomposition opportunity than to add unnecessary overhead and latency
    to a simple request. The standard agent loop is already good at
    single-domain tasks.
    """
    if not SUB_AGENT_ENABLED:
        return False

    # Gate: short messages never need decomposition
    if len(message.strip()) < SUB_AGENT_MIN_MESSAGE_LENGTH:
        return False

    # Exclusion: simple questions and directives
    for pattern in _EXCLUSION_PATTERNS:
        if pattern.search(message):
            return False

    # Positive signal: explicit multi-domain patterns
    for pattern in _MULTI_DOMAIN_PATTERNS:
        if pattern.search(message):
            return True

    # Heuristic: long messages with intent that could be multi-domain
    # A 100+ char FILE_WRITE message that mentions "and" is likely complex
    if effective_intent == Intent.FILE_WRITE and len(message) > 100:
        _conj_count = message.lower().count(" and ") + message.lower().count(", then ")
        if _conj_count >= 2:
            return True

    # Heuristic: CODE_EXEC with research terms
    if effective_intent == Intent.CODE_EXEC:
        _has_research = any(
            kw in message.lower() for kw in ("search", "find", "look up", "research", "latest", "current")
        )
        if _has_research and len(message) > 60:
            return True

    return False


# ── Sub-Task Orchestrator ────────────────────────────────────────────────────


@dataclass
class SubAgentExecution:
    """Result of a complete sub-agent execution pipeline."""

    success: bool
    sub_results: list[SubAgentResult]
    final_output: str
    total_latency_ms: int
    synthesized: bool = False
    """P12: Whether final_output was produced by synthesis (True) or simple
    concatenation (False). Synthesis produces higher-quality output but
    costs an additional LLM call."""


# ── P12: Result Synthesis ────────────────────────────────────────────────────

_SYNTHESIS_PROMPT = """You are a synthesis agent for LocalMind. Your job is to combine the results
from multiple specialized sub-agents into a single, coherent, well-structured response.

The sub-agents worked independently on different parts of the user's request. Your job is to:
1. Combine their outputs into a unified answer — no contradictions, no duplication
2. Order information logically — background first, then details, then conclusions
3. Remove redundancy — if two agents mention the same thing, keep the better version
4. Add transitions between sections so the response flows naturally
5. If there are contradictions between sub-agent results, note them honestly

Do NOT add new information that wasn't in the sub-agent results. Your job is to
organize and polish, not to generate new content.

Original user request: {request}

Sub-agent results:
{results}

Synthesize these into a single coherent response:"""


async def synthesize_sub_agent_results(
    results: list[SubAgentResult],
    original_request: str,
    adapter,
) -> str:
    """
    P12: Use an LLM call to synthesize multiple sub-agent results into a
    single coherent response.

    Without synthesis, sub-agent results are just concatenated with newlines,
    which produces jarring transitions and duplicated information. Synthesis
    produces a polished, unified answer that reads as if one person wrote it.

    Falls back to simple concatenation if synthesis fails (non-critical).
    """
    if len(results) <= 1:
        # Only one result — no synthesis needed
        return results[0].output if results else ""

    try:
        results_text = "\n\n---\n\n".join(
            f"[{r.agent_name} agent]:\n{r.output}" for r in results if r.success and r.output
        )

        if not results_text:
            return ""

        messages = [
            {
                "role": "system",
                "content": _SYNTHESIS_PROMPT.format(
                    request=original_request[:500],
                    results=results_text[:6000],  # Cap to avoid context overflow
                ),
            },
            {"role": "user", "content": original_request},
        ]

        chunks = []
        async for chunk in adapter.chat(messages, temperature=0.2):
            if hasattr(chunk, "error") and chunk.error:
                logger.warning("[sub_agent] adapter error: %s", chunk.error[:120])
                break
            chunks.append(chunk.text if hasattr(chunk, "text") else str(chunk))

        synthesized = "".join(chunks).strip()
        return synthesized if len(synthesized) > 50 else results_text

    except Exception as e:
        logger.warning("[sub_agent] synthesis failed (falling back to concat): %s", e)
        # Fallback: simple concatenation
        return "\n\n".join(r.output for r in results if r.success and r.output)


async def execute_sub_tasks(
    message: str,
    sub_tasks: list[SubTask],
    registry: SubAgentRegistry,
    adapter,
    obs=None,
) -> SubAgentExecution:
    """
    Execute a list of decomposed sub-tasks using the sub-agent registry.

    Execution strategy:
    - Tasks with no dependencies run in parallel (via asyncio.gather)
    - Tasks that depend on others wait for their dependencies to complete
    - Results from completed tasks are fed as context to dependent tasks
    - Final output is a synthesis of all sub-agent results

    Returns a SubAgentExecution with the assembled output.
    """
    t0 = time.monotonic()

    if not sub_tasks:
        return SubAgentExecution(
            success=False,
            sub_results=[],
            final_output="",
            total_latency_ms=round((time.monotonic() - t0) * 1000),
        )

    # Track completed task results: {task_id: SubAgentResult}
    completed: dict[int, SubAgentResult] = {}
    failed_tasks: set[int] = set()

    # Execute in waves: each wave contains tasks whose dependencies are all met
    remaining = list(sub_tasks)

    while remaining:
        # Find tasks whose dependencies are all completed
        ready = []
        blocked = []
        for task in remaining:
            deps_met = all(d in completed for d in task.depends_on)
            deps_failed = any(d in failed_tasks for d in task.depends_on)
            if deps_failed:
                # Dependency failed — this task can't proceed
                failed_tasks.add(task.id)
                logger.warning("[sub_agent] task %d skipped — dependency failed", task.id)
            elif deps_met:
                ready.append(task)
            else:
                blocked.append(task)

        if not ready:
            # No progress — all remaining are blocked or failed
            for task in blocked:
                failed_tasks.add(task.id)
            break

        # Build context from completed dependencies for each ready task
        async def _run_task(task: SubTask) -> tuple[int, SubAgentResult]:
            # Assemble context from dependencies
            dep_contexts = []
            for dep_id in task.depends_on:
                dep_result = completed.get(dep_id)
                if dep_result:
                    dep_contexts.append(f"[Result from {dep_result.agent_name} agent]:\n{dep_result.output[:1500]}")
            context = "\n\n".join(dep_contexts) if dep_contexts else ""

            # Get the sub-agent type
            agent_type = registry.get(task.agent_name)
            if not agent_type:
                return task.id, SubAgentResult(
                    agent_name=task.agent_name,
                    success=False,
                    output=f"Unknown agent type: {task.agent_name}",
                )

            # Create and run the sub-agent
            sub_agent = SubAgent(agent_type=agent_type, adapter=adapter)
            result = await sub_agent.run(
                prompt=task.prompt,
                context=context,
            )
            return task.id, result

        # Run all ready tasks concurrently
        if len(ready) == 1:
            # Single task — no gather overhead
            task_id, result = await _run_task(ready[0])
            if result.success:
                completed[task_id] = result
            else:
                failed_tasks.add(task_id)
        else:
            # Multiple independent tasks — run in parallel
            results = await asyncio.gather(*[_run_task(t) for t in ready])
            for task_id, result in results:
                if result.success:
                    completed[task_id] = result
                else:
                    failed_tasks.add(task_id)

        # Remove completed/failed from remaining
        remaining = [t for t in remaining if t.id not in completed and t.id not in failed_tasks]

        # Emit observability
        if obs:
            for task_id, result in completed.items():
                obs.emit(
                    "sub_agent_done",
                    agent=result.agent_name,
                    task_id=task_id,
                    success=result.success,
                    latency_ms=result.latency_ms,
                )

    # Assemble final output from all completed results (in task order)
    output_parts = []
    for task in sub_tasks:
        result = completed.get(task.id)
        if result and result.success and result.output:
            output_parts.append(result)

    # P12: Use LLM synthesis instead of simple concatenation when we have
    # multiple successful sub-agent results. Synthesis produces a unified,
    # coherent response instead of a jarring concat of separate outputs.
    if len(output_parts) > 1:
        try:
            final_output = await synthesize_sub_agent_results(
                results=output_parts,
                original_request=message,
                adapter=adapter,
            )
            synthesized = True
        except Exception:
            # Fallback to concatenation
            final_output = "\n\n".join(r.output for r in output_parts)
            synthesized = False
    elif output_parts:
        final_output = output_parts[0].output
        synthesized = False
    else:
        final_output = ""
        synthesized = False

    # If nothing succeeded, we still want some output
    if not final_output and failed_tasks:
        final_output = "I wasn't able to complete this multi-step task. Let me try a different approach."

    total_ms = round((time.monotonic() - t0) * 1000)

    return SubAgentExecution(
        success=len(completed) > 0,
        sub_results=list(completed.values()),
        final_output=final_output,
        total_latency_ms=total_ms,
        synthesized=synthesized,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _dispatch_sub_agent_tool(
    tool_name: str,
    tool_args: dict,
    dispatch_fn,
) -> str:
    """Dispatch a single tool for a sub-agent and return the observation text."""
    try:
        # Map tool name to Intent for dispatch
        _tool_intent_map = {
            "code_exec": Intent.CODE_EXEC,
            "file_write": Intent.FILE_WRITE,
            "edit_file": Intent.FILE_EDIT,
            "file_task": Intent.FILE_TASK,
            "shell": Intent.SHELL,
            "web_search": Intent.WEB_SEARCH,
            "memory_op": Intent.MEMORY_OP,
            "sysinfo": Intent.SYSINFO,
        }
        intent = _tool_intent_map.get(tool_name)
        if not intent:
            return f"[Unknown tool: {tool_name}]"

        # Build input string from args
        if tool_name == "file_write":
            inp = f"{tool_args.get('path', '')}:\n\n{tool_args.get('content', '')}"
        elif tool_name == "edit_file":
            inp = json.dumps(tool_args, ensure_ascii=False)
        elif tool_name == "memory_op":
            inp = f"{tool_args.get('operation', 'recall')} {tool_args.get('content', '')}".strip()
        else:
            inp = tool_args.get("query", tool_args.get("command", tool_args.get("code", "")))
            if not inp:
                inp = tool_args.get("path", "")

        result, failed, _ = await dispatch_fn(intent, inp)
        if result:
            return result.content
        return f"[Tool {tool_name} returned no result]"

    except Exception as e:
        return f"[Tool {tool_name} error: {e}]"


def _build_tool_defs(allowed_tools: frozenset[str]) -> list[dict]:
    """Build minimal tool definitions for the sub-agent's allowed tools."""
    # Full definitions live in loop.py — here we provide a minimal subset
    # that's sufficient for chat_with_tools() to work.
    _ALL_DEFS = {
        "web_search": {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web for current information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The search query"},
                    },
                    "required": ["query"],
                },
            },
        },
        "code_exec": {
            "type": "function",
            "function": {
                "name": "code_exec",
                "description": "Execute Python code and return the output",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Python code to execute"},
                    },
                    "required": ["code"],
                },
            },
        },
        "file_write": {
            "type": "function",
            "function": {
                "name": "file_write",
                "description": "Write content to a file on disk",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path to write to"},
                        "content": {"type": "string", "description": "Content to write"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        "edit_file": {
            "type": "function",
            "function": {
                "name": "edit_file",
                "description": "Edit an existing file in-place",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file to edit"},
                        "action": {
                            "type": "string",
                            "description": "Edit action (replace, insert, append, etc.)",
                        },
                        "search": {"type": "string", "description": "Text to search for"},
                        "replace": {"type": "string", "description": "Replacement text"},
                    },
                    "required": ["path", "action"],
                },
            },
        },
        "file_task": {
            "type": "function",
            "function": {
                "name": "file_task",
                "description": "Read file contents (PDF, DOCX, XLSX, TXT, etc.). Supports binary formats via automatic parsing. Use for reading ANY file — NOT for directories. Do NOT use shell commands like 'type' or 'cat' to read files.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file to read"},
                    },
                    "required": ["path"],
                },
            },
        },
        "shell": {
            "type": "function",
            "function": {
                "name": "shell",
                "description": "Run a system command (dir/ls, git, disk checks). For reading file contents, use file_task — NOT 'type' or 'cat' commands which fail on PDFs/binary files.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Shell command to execute (NOT for reading files — use file_task)",
                        },
                    },
                    "required": ["command"],
                },
            },
        },
        "memory_op": {
            "type": "function",
            "function": {
                "name": "memory_op",
                "description": "Store, recall, or delete persistent facts",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "description": "The memory operation"},
                        "content": {"type": "string", "description": "The fact or query"},
                    },
                    "required": ["operation", "content"],
                },
            },
        },
        "sysinfo": {
            "type": "function",
            "function": {
                "name": "sysinfo",
                "description": "Get system information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "What system info to retrieve"},
                    },
                    "required": ["query"],
                },
            },
        },
    }
    return [_ALL_DEFS[t] for t in allowed_tools if t in _ALL_DEFS]
