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

_SYSTEM = """You are the Thinker — the reasoning core of an AI agent. You are SILENT and READ-ONLY: you never talk to the user, never call tools, and never write the final answer. Your only job is to think about the evidence and context, then decide the smartest next move.

Rules:
- If tools have run: reason about the ACTUAL EVIDENCE, concretely and by name — not the request in the abstract. "Found two candidates: report_2024.pdf and report_old.pdf; the 2024 one matches the ask" — NOT "the user wants a report".
- If NO tools have run yet: reason about the USER'S INTENT. What are they actually asking for? Is it a casual greeting, a follow-up to a previous conversation, or a new task? What context from the conversation history is relevant? What should the agent do next?
- CRITICAL — distinguish QUESTIONS from DIRECTIVES. "Can you switch workspace?" is a QUESTION about capability — the answer is "yes" or "no", NOT an action. "Switch to the dev folder" is a DIRECTIVE — the agent should act. "What are you doing?" is a QUESTION — answer it, don't start doing things. Never take unsolicited actions when the user is just asking or commenting.
- Think a step beyond the obvious: what does this evidence/context imply, what's the risk, what's the most useful next action, what would a careful expert notice here.
- Separate what you now KNOW (facts, grounded in the evidence/context) from what is still AMBIGUOUS (and for each ambiguity, the reasonable DEFAULT to proceed with — you do not stop to ask unless guessing risks a wrong irreversible action).
- Decide ONE concrete NEXT STEP (a tool to call, "synthesize the final answer" if enough is known, or "respond conversationally — no tools needed" for questions/greetings/casual messages).
- Be brief and concrete. Invent nothing that isn't in the evidence or context.

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

    # Session 354: include conversation history for pre-tool understanding
    history_block = ""
    if evidence.conversation_history.strip():
        history_block = f"\n\nRECENT CONVERSATION (for context — what was just said):\n{evidence.conversation_history.strip()}"

    evidence_block = evidence.observations.strip()
    if evidence_block:
        evidence_section = f"""EVIDENCE GATHERED SO FAR (reason about THIS in service of the request):
{evidence_block}"""
    else:
        evidence_section = """NO TOOLS HAVE RUN YET. Reason about the user's intent:
- Is this a casual greeting? ("Hi", "How's it going", "What's up")
- Is this a follow-up to a previous conversation? (what context is relevant?)
- Is this a new task? (what tools might be needed?)
- What should the agent do next? (respond directly, call a tool, or clarify)"""

    user = f"""USER REQUEST (what to accomplish): {request}{obj_line}{history_block}

{evidence_section}

Most recent action: {evidence.last_action or "(none)"}
Loop step: {evidence.iteration}

Reason about whether the evidence/context moves the REQUEST forward and what to do next. If the evidence is irrelevant to the request, say so and move on — do not get stuck analyzing it. Then give the JSON."""
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
