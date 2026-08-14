"""Parent-agent initialization contract.

The request runtime must not decide from prompt-shaped shortcuts whether a
turn is conversation, clarification, or tool work.  The parent agent's first
model call owns that decision.  This module keeps the wire contract small and
machine-readable while deliberately excluding hidden chain-of-thought.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

INITIALIZATION_MODES = frozenset({"direct", "clarify", "execute"})
_MAX_TEXT = 600
_MAX_STEPS = 10
_MAX_TOOLS = 12


@dataclass
class InitializationDecision:
    """The parent agent's first-turn decision."""

    mode: str = "execute"
    acknowledgement: str = ""
    response: str = ""
    objective: str = ""
    clarifying_question: str = ""
    tool_names: list[str] = field(default_factory=list)
    plan_steps: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    confidence: float = 0.0
    raw: str = ""
    # ADR-34 B-12: record the init prompt size so init vs execution budgets
    # are measured independently. Set by the streaming initializer.
    init_prompt_chars: int = 0

    @property
    def is_direct(self) -> bool:
        return self.mode == "direct"

    @property
    def is_clarification(self) -> bool:
        return self.mode == "clarify"

    def plan_text(self) -> str:
        """Render bounded structured plan context for the execution model."""
        lines: list[str] = []
        if self.objective:
            lines.append(f"UNDERSTANDING: {self.objective}")
        if self.tool_names:
            lines.append(f"TOOLS: {', '.join(self.tool_names)}")
        if self.plan_steps:
            lines.append("STEPS:")
            lines.extend(f"{i}. {step}" for i, step in enumerate(self.plan_steps, 1))
        if self.success_criteria:
            lines.append("SUCCESS_CRITERIA:")
            lines.extend(f"- {criterion}" for criterion in self.success_criteria)
        return "\n".join(lines)[:1800]


def _compact_capability_summary(available_tools: Iterable[dict[str, Any]]) -> str:
    """Build a compact, categorized capability summary for the init prompt.

    ADR-34 B-12: the initializer does NOT need the full 180-char description
    of every tool. It only needs to know WHAT CATEGORIES of capability exist
    so it can decide direct/clarify/execute and name the likely tool_names.
    Full tool schemas are loaded only for the execution path after the
    decision is made.

    Returns a single string like:
      file ops: file_task, file_write, file_edit, find_path
      code: code_exec, shell, git, process
      web: web_search, web_fetch, browse
      ...
    """
    # Map tool names to coarse capability categories. The categories are
    # deliberately broad — the model only needs to recognize the shape of
    # work it can delegate to, not the exact schema.
    category_keywords: dict[str, list[str]] = {
        "file ops": [
            "file_task", "file_write", "file_edit", "find_path",
            "propose_write_file", "propose_str_replace", "apply_proposed_edit",
            "csv", "json", "sql",
        ],
        "code": ["code_exec", "shell", "git", "process"],
        "web": ["web_search", "web_fetch", "browse"],
        "memory": ["memory_op", "skill"],
        "system": ["sysinfo", "observe", "diagnostics"],
        "planning": ["add_subgoal", "update_subgoal", "create_plan"],
        "delegation": ["delegate", "delegate_parallel", "delegate_inline", "best_of_n_edit"],
        "math": ["calculate"],
    }
    # Collect all tool names
    tool_names: list[str] = []
    for tool in available_tools:
        name = str(tool.get("intent") or tool.get("name") or "").strip()
        if name:
            tool_names.append(name)
    if not tool_names:
        return "(no tools available)"
    # Bucket each tool into its category
    categorized: dict[str, list[str]] = {cat: [] for cat in category_keywords}
    uncategorized: list[str] = []
    for name in tool_names:
        placed = False
        for cat, keywords in category_keywords.items():
            if any(name == kw or name.startswith(kw) for kw in keywords):
                categorized[cat].append(name)
                placed = True
                break
        if not placed:
            uncategorized.append(name)
    # Build the summary
    lines: list[str] = []
    for cat in category_keywords:
        tools_in_cat = categorized[cat]
        if tools_in_cat:
            lines.append(f"- {cat}: {', '.join(tools_in_cat)}")
    if uncategorized:
        lines.append(f"- other: {', '.join(uncategorized)}")
    return "\n".join(lines)


def build_initialization_prompt(
    user_message: str,
    available_tools: Iterable[dict[str, Any]],
    env_context: str = "",
    history: Iterable[dict[str, Any]] | None = None,
) -> str:
    """Build the model-owned request interpretation prompt.

    ADR-34 B-12: the init prompt uses a COMPACT CAPABILITY SUMMARY instead
    of listing all 30 tools with 180-char descriptions. The model only needs
    to recognize the shape of work it can delegate to (file ops, code, web,
    memory, system, planning, delegation, math) — full tool schemas are
    loaded only for the execution path after the decision is made.

    The response is intentionally suitable for streaming internally and
    parsing at the parent/runtime boundary.
    """
    history_lines = []
    for item in list(history or [])[-6:]:
        role = str(item.get("role", ""))
        content = str(item.get("content", ""))[:500]
        if role and content:
            history_lines.append(f"{role}: {content}")

    history_block = "\nRecent conversation:\n" + "\n".join(history_lines) if history_lines else ""
    tools_block = _compact_capability_summary(available_tools)
    return f"""You are the initialization stage of LocalMind's parent agent.

Decide how the parent should handle the user's latest request. Do not
execute tools. Return ONLY one JSON object matching the schema.

Modes:
- direct: no tools needed; put the complete answer in response.
- clarify: a material detail is missing; put one question in clarifying_question.
- execute: tools/multi-step reasoning needed; provide acknowledgement, plan, tool_names, success_criteria.

Capabilities (use these names in tool_names):
{tools_block}

{env_context}{history_block}

JSON schema:
{{
  "mode": "direct|clarify|execute",
  "acknowledgement": "short user-facing acknowledgement (<=180 chars)",
  "response": "complete answer only for direct mode",
  "objective": "what the user actually wants",
  "clarifying_question": "one question only for clarify mode",
  "tool_names": ["tool_name"],
  "plan_steps": ["goal-level step with concrete tool/arguments"],
  "success_criteria": ["observable evidence that proves completion"],
  "confidence": 0.0
}}

Rules:
- direct for greetings and general questions needing no local/live data.
- execute for anything requiring current info, files, code, browser, memory, or evidence.
- clarify only when proceeding would require guessing a material requirement.
- acknowledgement <=180 chars, response <=1200 chars, plan_steps <=8, tool_names <=8, success_criteria <=4.

User request:
{user_message}
"""


def _first_json_object(text: str) -> dict[str, Any] | None:
    """Extract the first balanced JSON object from a noisy model response."""
    source = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", source, re.IGNORECASE | re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    start = source.find("{")
    if start >= 0:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(source)):
            char = source[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(source[start : index + 1])
                    break
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            return value
    return None


def _bounded_strings(value: Any, limit: int, max_chars: int = _MAX_TEXT) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text[:max_chars])
        if len(result) >= limit:
            break
    return result


def parse_initialization(text: str) -> InitializationDecision:
    """Parse a model decision and fail safely into execute mode.

    An unparsable initialization response must never cause a prompt-shaped
    routing fallback.  Execute mode preserves the parent loop's ability to
    inspect the request and choose a tool; the raw response is retained only
    as bounded internal plan context.
    """
    raw = (text or "").strip()
    payload = _first_json_object(raw)
    if payload is None:
        fallback_step = raw[:_MAX_TEXT] if raw else "Inspect the request and determine the required action."
        return InitializationDecision(
            mode="execute",
            objective="Determine and complete the user's request.",
            plan_steps=[fallback_step],
            raw=raw[:1800],
        )

    mode = str(payload.get("mode", "execute")).strip().lower()
    if mode not in INITIALIZATION_MODES:
        mode = "execute"
    decision = InitializationDecision(
        mode=mode,
        acknowledgement=str(payload.get("acknowledgement", "")).strip()[:_MAX_TEXT],
        response=str(payload.get("response", "")).strip()[:1200],
        objective=str(payload.get("objective", "")).strip()[:_MAX_TEXT],
        clarifying_question=str(payload.get("clarifying_question", "")).strip()[:_MAX_TEXT],
        tool_names=_bounded_strings(payload.get("tool_names"), _MAX_TOOLS, 80),
        plan_steps=_bounded_strings(payload.get("plan_steps"), _MAX_STEPS),
        success_criteria=_bounded_strings(payload.get("success_criteria"), 4),
        raw=raw[:1800],
    )
    try:
        decision.confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.0))))
    except (TypeError, ValueError):
        decision.confidence = 0.0

    if decision.mode == "direct" and not decision.response:
        # A direct decision without an answer cannot complete the user turn.
        decision.mode = "execute"
    if decision.mode == "clarify" and not decision.clarifying_question:
        decision.mode = "execute"
    if decision.mode == "execute" and not decision.plan_steps:
        decision.plan_steps = ["Inspect the request and choose the first verifiable action."]
    return decision
