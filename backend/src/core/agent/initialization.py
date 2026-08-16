"""Parent-agent initialization contract — CLASSIFY-ONLY (rebuild Step 1).

The request runtime must not decide from prompt-shaped shortcuts whether a
turn is conversation, clarification, or tool work.  The parent agent's first
model call owns that decision — but ONLY the tier decision (ADR-37 three-tier:
trivial / needs-thought / needs-tools) plus the opening line and the objective.

ADR-38 (Thinker/Agent rebuild, Step 1): the upfront init call no longer
commits a plan, success criteria, tool names, or facts/ambiguities — the
old monolithic call reasoned BEFORE any tool ran, so its assessment could
only narrate assumptions ("assumed dev-folder path"). The plan EMERGES from
the loop on gathered evidence, and the Thinker's real facts/ambiguities
consult happens mid-loop (Step 2). The legacy fields were DELETED, not
preserved: a model that emits them anyway is ignored — only the classify
fields (mode/acknowledgement/response/objective/clarifying_question) parse.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

INITIALIZATION_MODES = frozenset({"direct", "clarify", "execute"})
_MAX_TEXT = 600


@dataclass
class InitializationDecision:
    """The parent agent's first-turn decision (classify-only)."""

    mode: str = "execute"
    acknowledgement: str = ""
    response: str = ""
    objective: str = ""
    clarifying_question: str = ""
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

    def objective_line(self) -> str:
        """Render the bounded objective context for the execution model.

        No plan, tool list, or criteria — the plan emerges from the loop on
        gathered evidence (ADR-38 Step 1).
        """
        if self.objective:
            return f"UNDERSTANDING: {self.objective}"[:1800]
        return ""


def build_initialization_prompt(
    user_message: str,
    env_context: str = "",
    history: Iterable[dict[str, Any]] | None = None,
) -> str:
    """Build the CLASSIFY-ONLY initialization prompt (rebuild Step 1, ADR-38).

    The init call decides ONLY the tier (direct / clarify / execute), the
    opening acknowledgement, and the one-line objective. It no longer
    commits a plan, success criteria, tool names, or facts/ambiguities —
    the old monolithic call reasoned BEFORE any tool ran, so its "facts"
    were assumptions and its plan was committed blind. The plan EMERGES
    from the loop on gathered evidence; the Thinker's real assessment
    happens mid-loop (Step 2). The tool catalog is deliberately NOT
    injected: a classifier does not need it to pick a tier (and dropping
    it shrank the init prompt ~40%).
    """
    history_lines = []
    for item in list(history or [])[-6:]:
        role = str(item.get("role", ""))
        content = str(item.get("content", ""))[:500]
        if role and content:
            history_lines.append(f"{role}: {content}")

    history_block = "\nRecent conversation:\n" + "\n".join(history_lines) if history_lines else ""
    return f"""You are the initialization stage of LocalMind's parent agent.

Decide how the parent should handle the user's latest request. Do not
execute tools. Return ONLY one JSON object matching the schema.

Modes (choose the tier):
- direct: trivial or conversational — no tools, no lookups needed; put the
  complete answer in response.
- clarify: a material detail is missing that NO search or inspection could
  resolve; put one question in clarifying_question.
- execute: anything needing current info, files, code, browser, memory, or
  multi-step work. Do NOT plan the steps here — the agent will look at the
  actual state first and decide step by step from what it finds.

{env_context}{history_block}

JSON schema:
{{
  "mode": "direct|clarify|execute",
  "acknowledgement": "short user-facing acknowledgement (<=180 chars)",
  "response": "complete answer only for direct mode",
  "objective": "what the user actually wants — one concise line (<=200 chars)",
  "clarifying_question": "one question only for clarify mode",
  "confidence": 0.0
}}

Rules:
- direct for greetings and general questions needing no local/live data.
- direct for questions about YOURSELF — your capabilities, identity, or how
  you work ("what can you do", "who are you", "what tools do you have"). These
  DESCRIBE your tools; they do not require RUNNING any. Answer from the
  response field. Do NOT route them to execute just because they mention files
  or code — nothing needs to be looked up.
- execute for anything requiring current info, files, code, browser, memory,
  or evidence. BIAS STRONGLY TOWARD execute, and ACT rather than ask. If a
  detail is unknown but DISCOVERABLE — a file to find, a folder to list, a
  value to look up — do NOT clarify: execute and discover it. Example:
  "read my CV" → search the home directory for *cv*/*resume*.{{pdf,docx,doc}}
  and read the best match; NEVER ask for a filename or path you could find
  yourself.
- clarify is a LAST RESORT — only when the request is genuinely underspecified
  in a way NO search or inspection could resolve AND guessing would risk a
  wrong irreversible action. When in doubt, execute with a reasonable default.
- The plan is NOT decided here. You only classify the tier, acknowledge, and
  state the objective. The agent gathers real evidence first, then decides
  each next step from what it actually finds.
- acknowledgement <=180 chars, response <=1200 chars, objective <=200 chars.

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


def parse_initialization(text: str) -> InitializationDecision:
    """Parse a model decision and fail safely into execute mode.

    An unparsable initialization response must never cause a prompt-shaped
    routing fallback.  Execute mode preserves the parent loop's ability to
    inspect the request and choose a tool; the raw response is retained only
    as bounded internal context.

    Rebuild Step 1 (ADR-38): the init is classify-only, so a decision with
    NO plan is legitimate — the plan emerges from the loop. Legacy fields
    (facts/ambiguities/tool_names/plan_steps/success_criteria) were DELETED:
    a model that returns them is ignored, not preserved.
    """
    raw = (text or "").strip()
    payload = _first_json_object(raw)
    if payload is None:
        # Fail open into execute WITHOUT inventing a plan — the loop will
        # look at the request and pick the first action from evidence.
        return InitializationDecision(
            mode="execute",
            objective="Determine and complete the user's request.",
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
    return decision
