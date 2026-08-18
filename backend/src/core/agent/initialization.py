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
from dataclasses import dataclass, field
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
    # ADR-49 (revises ADR-38 for the todo checklist): an ordered list of the
    # concrete steps the agent will take, for a multi-step `execute` task. Emitted
    # up front as the live Todos panel and checked off as the agent works. Empty
    # for direct/clarify and single-step tasks.
    plan_steps: list[str] = field(default_factory=list)
    # ADR-34 B-12: record the init prompt size so init vs execution budgets
    # are measured independently. Set by the streaming initializer.
    init_prompt_chars: int = 0
    # Session 290: provider-reported usage from the init call. On a DIRECT turn
    # the init call IS the whole turn, so this is the turn's real token usage —
    # propagated to the loop so direct turns report actual tokens, not an
    # estimate. Set by the streaming initializer; default empty.
    usage: dict = field(default_factory=dict)

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
  multi-step work. For a multi-step task, list the concrete ordered steps you
  will take in `plan` (2-6 short imperative steps, each a real action toward the
  goal — e.g. "Search the web for X", "Read the top result", "Summarize the
  answer"). Use a single-item `plan` (or omit it) for a genuinely one-step task.

{env_context}{history_block}

JSON schema:
{{
  "mode": "direct|clarify|execute",
  "acknowledgement": "short user-facing acknowledgement (<=180 chars)",
  "response": "complete answer only for direct mode",
  "objective": "what the user actually wants — one concise line (<=200 chars)",
  "plan": ["ordered step 1", "ordered step 2", "..."],
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
- For an execute task, `plan` is the ordered checklist the agent will follow to
  reach the objective — the user sees it as a live task list. Keep steps
  concrete and few; the agent may reorder, add, or skip steps as real evidence
  changes. Leave `plan` empty for direct/clarify.
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


# The bounded answer used when a turn resolves to DIRECT but the model gave us
# nothing usable to say (empty/garbled classify output). It never runs a tool
# and never hangs — the safe floor for any model on an unclear turn.
_FALLBACK_DIRECT_RESPONSE = (
    "I'm here and ready to help. Could you tell me a little more about what "
    "you'd like me to do?"
)


def _salvage_response(raw: str) -> str:
    """Recover a user-facing answer from an unparseable classify output.

    A model that "fails" the JSON contract has almost always just answered the
    user in prose (or emitted partial JSON that still carries the answer). That
    text IS the answer — recover it rather than discarding it and escalating to
    the tool loop. Order: an explicit response/acknowledgement value (even from
    malformed JSON) → the raw prose when the output was never JSON → "".
    """
    for key in ("response", "acknowledgement"):
        # A complete (quoted) value first.
        match = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
        if match:
            try:
                return json.loads(f'"{match.group(1)}"').strip()[:1200]
            except (ValueError, json.JSONDecodeError):
                return match.group(1).strip()[:1200]
        # A value truncated mid-stream (no closing quote) — take it to the end.
        loose = re.search(rf'"{key}"\s*:\s*"(.+)$', raw, re.DOTALL)
        if loose:
            return loose.group(1).strip().rstrip('"').strip()[:1200]
    # No JSON structure at all — the model simply replied in prose. Use it.
    if not raw.lstrip().startswith("{"):
        return raw.strip()[:1200]
    return ""


def parse_initialization(text: str) -> InitializationDecision:
    """Parse the classify decision. EXECUTE IS OPT-IN, never the fallback.

    The tool loop is the most expensive, least-bounded, and only
    state-changing path, so entering it must be an EXPLICIT, parseable choice —
    ``mode == "execute"``. Every uncertain outcome (unparseable output, an
    unknown mode, a direct with no answer, a clarify with no question) resolves
    to a bounded DIRECT answer instead, built from the model's own output via
    ``_salvage_response``. This is model- and provider-agnostic: it stops ANY
    model — 3B local or frontier cloud — from being dragged into a tool loop
    (or an unbounded hang) on a turn it never asked to execute. A model that
    ignores the JSON contract and just greets the user now has that greeting
    shown as the answer, which is what it always should have been.

    Rebuild Step 1 (ADR-38): the init is classify-only — no plan is committed;
    the plan emerges from the loop when execute is chosen. Legacy fields
    (facts/ambiguities/tool_names/plan_steps/success_criteria) are ignored.
    """
    raw = (text or "").strip()
    payload = _first_json_object(raw)
    if payload is None:
        # Unparseable → bounded direct answer from whatever the model produced.
        return InitializationDecision(
            mode="direct",
            response=_salvage_response(raw) or _FALLBACK_DIRECT_RESPONSE,
            raw=raw[:1800],
        )

    mode = str(payload.get("mode", "")).strip().lower()
    decision = InitializationDecision(
        mode="direct",  # default until an explicit execute/clarify earns it
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

    # ADR-49: ordered upfront plan → the live Todos panel. Bounded + sanitized;
    # a model that omits it (or emits junk) just yields an empty plan (no todos).
    _raw_plan = payload.get("plan")
    if isinstance(_raw_plan, list):
        decision.plan_steps = [
            str(s).strip()[:120]
            for s in _raw_plan
            if isinstance(s, str) and s.strip()
        ][:6]

    if mode == "execute":
        # The only path to the tool loop — an explicit, parseable choice.
        decision.mode = "execute"
    elif mode == "clarify" and decision.clarifying_question:
        # Clarify is honored only when it carries a question to ask.
        decision.mode = "clarify"
    else:
        # direct (explicit), an unknown mode, a direct with no answer, or a
        # clarify with no question — all resolve to a bounded direct answer.
        decision.mode = "direct"
        if not decision.response:
            decision.response = (
                _salvage_response(raw) or decision.acknowledgement or _FALLBACK_DIRECT_RESPONSE
            )
    return decision
