# ruff: noqa: E501 — prompt template lines are intentionally long
"""The Thinker prompt (ADR-42).

The prompt's single job: make the model reason on the EVIDENCE it just
gathered — concretely, by name — and decide the smartest next move. It must
NOT restate the request (that produced the one-line echo the Thinker
replaces), and it must NOT answer the user (the Thinker is silent; the agent
synthesizes the reply). The model reasons in prose first (streamed live as
thought), then emits a compact JSON block the agent parses.
"""

from __future__ import annotations

from .contract import Evidence

_SYSTEM = """You are the Thinker — the reasoning core of an AI agent. You are SILENT and READ-ONLY: you never talk to the user, never call tools, and never write the final answer. Your only job is to think about the evidence the agent has just gathered and decide the smartest next move.

Rules:
- Reason about the ACTUAL EVIDENCE, concretely and by name — not the request in the abstract. "Found two candidates: report_2024.pdf and report_old.pdf; the 2024 one matches the ask" — NOT "the user wants a report".
- Think a step beyond the obvious: what does this evidence imply, what's the risk, what's the most useful next action, what would a careful expert notice here.
- Separate what you now KNOW (facts, grounded in the evidence) from what is still AMBIGUOUS (and for each ambiguity, the reasonable DEFAULT to proceed with — you do not stop to ask unless guessing risks a wrong irreversible action).
- Decide ONE concrete NEXT STEP (a tool to call, or "synthesize the final answer" if enough is known).
- Be brief and concrete. Invent nothing that isn't in the evidence.

Output: first your reasoning in a few plain sentences, then EXACTLY ONE JSON object on its own:
{"facts": ["..."], "ambiguities": [{"text": "...", "default": "..."}], "next_step": "...", "confidence": 0.0}
"""


# A generic fallback objective (init parse failed) must never stand in for the
# real request — it made the Thinker reason about irrelevant evidence at
# confidence 0.0 instead of the actual task (Session 263).
_GENERIC_OBJECTIVE = "determine and complete the user's request"


def build_thinker_messages(evidence: Evidence) -> list[dict]:
    """Assemble the chat messages for a Thinker consult."""
    # The USER REQUEST is ground truth. Only show the objective when it adds
    # something beyond the request and isn't the generic fallback.
    request = evidence.user_message.strip() or evidence.objective.strip()
    obj = evidence.objective.strip()
    obj_line = ""
    if obj and obj.rstrip(".").lower() != _GENERIC_OBJECTIVE and obj.lower() != request.lower():
        obj_line = f"\nInterpreted objective: {obj}"

    user = f"""USER REQUEST (what to accomplish): {request}{obj_line}

EVIDENCE GATHERED SO FAR (reason about THIS in service of the request):
{evidence.observations.strip() or "(nothing gathered yet)"}

Most recent action: {evidence.last_action or "(none)"}
Loop step: {evidence.iteration}

Reason about whether the evidence moves the REQUEST forward and what to do next. If the evidence is irrelevant to the request, say so and move on — do not get stuck analyzing it. Then give the JSON."""
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
