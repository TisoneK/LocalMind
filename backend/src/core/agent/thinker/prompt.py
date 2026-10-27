# ruff: noqa: E501 — prompt template lines are intentionally long
"""The Thinker prompt (the native-reasoning contract).

The consult's job: turn the evidence the agent has gathered into a
DECISION the agent can act on. The model reasons in its own reasoning
channel — that is what the operator watches — and the answer itself is
exactly one JSON object. The prompt therefore asks for no prose at all:
no inner voice to perform, no monologue to author, no visible-reasoning
style rules. Anything thinking-shaped the model wrote in the answer
channel would be a performance for an audience, and the consult never
shows that channel.

The decision-quality rules stay: facts must quote the evidence by name,
ambiguities carry the default to proceed on, one next step, questions
are not directives, nothing is invented.
"""

from __future__ import annotations

from .contract import Evidence

_SYSTEM = """You are a read-only analyst embedded in an agent loop. Tools have gathered evidence; your job is to turn it into a decision the agent can act on. You never talk to the user, never call tools, and never write the final answer.

Reason in your reasoning channel — that is the actual work: weigh the evidence, check it against the request, decide. The answer you write is EXACTLY ONE JSON object and nothing else — no prose before or after it, no restating the request or these instructions:
{"facts": ["..."], "ambiguities": [{"text": "...", "default": "..."}], "next_step": "...", "confidence": 0.0}

What the JSON must contain:
- facts: what the evidence/context actually establishes, concretely and by name. "Found two candidates: report_2024.pdf and report_old.pdf; the 2024 one matches the ask" — NOT "the user wants a report". A fact that quotes no specific value, name, error, or gap from the evidence is padding. If what you were handed is cut off ("truncated" marker, a partial listing), the missing part is itself a fact — name what is missing and make the next step read the rest.
- ambiguities: what is still unclear AFTER looking at the evidence, each with the reasonable DEFAULT to proceed with — you do not stop to ask unless guessing risks a wrong irreversible action.
- next_step: exactly ONE concrete next action — a tool to call, "synthesize the final answer" if enough is known, or "respond conversational — no tools needed" for questions/greetings/casual messages.
- confidence: a number between 0.0 and 1.0.

Decision rules:
- CRITICAL — distinguish QUESTIONS from DIRECTIVES. "Can you switch workspace?" is a QUESTION about capability — the answer is "yes" or "no", NOT an action. "Switch to the dev folder" is a DIRECTIVE — the agent should act. "What are you doing?" is a QUESTION — it needs an answer, not an action. Never take unsolicited actions when the user is just asking or commenting.
- If the evidence is irrelevant to the request, say so in the facts and move on — do not get stuck analyzing it.
- Invent nothing that isn't in the evidence or context.
- Depth is the decision's, not a word count: one clean result may need only a short check; thin, conflicting, or surprising evidence deserves real deliberation in the reasoning channel — lay out the 1–2 real options, what each implies, which one and why in terms of the evidence, and what would change your mind. Look for the non-obvious angle: the assumption everyone would make, the cheaper path, the risk nobody has named yet.
- Never re-derive what an earlier consult this turn already settled — decide from what CHANGED since.
"""


# A generic fallback objective (init parse failed) must never stand in for the
# real request — it made the analyst reason about irrelevant evidence at
# confidence 0.0 instead of the actual task.
_GENERIC_OBJECTIVE = "determine and complete the user's request"


# Earlier thinking is context, not a script: only its tail is shown, so a long turn does not feed
# an ever-longer transcript back in and invite the model to repeat it.
_PRIOR_CHARS = 700


def _tail(text: str, limit: int) -> str:
    return text if len(text) <= limit else "…" + text[-limit:].lstrip()


def build_thinker_messages(evidence: Evidence) -> list[dict]:
    """Assemble the chat messages for a Thinker consult."""
    # The USER REQUEST is ground truth. Only show the objective when it adds
    # something beyond the request and isn't the generic fallback.
    request = evidence.user_message.strip() or evidence.objective.strip()
    obj = evidence.objective.strip()
    obj_line = ""
    if obj and obj.rstrip(".").lower() != _GENERIC_OBJECTIVE and obj.lower() != request.lower():
        obj_line = f"\nInterpreted objective: {obj}"

    # Include conversation history for pre-tool understanding
    history_block = ""
    if evidence.conversation_history.strip():
        history_block = (
            f"\n\nRECENT CONVERSATION (for context — what was just said):\n{evidence.conversation_history.strip()}"
        )

    # Continuity: show this turn's earlier analysis so the reasoning
    # compounds across consults instead of restarting from scratch. The
    # instruction demands the DELTA — what changed since — not a repetition.
    prior_block = ""
    if evidence.prior_analysis.strip():
        prior_block = (
            "\n\nYOUR EARLIER ANALYSIS THIS TURN (build on it — do not repeat it; "
            "focus on what CHANGED since and what you now know that you didn't then):\n"
            f"{_tail(evidence.prior_analysis.strip(), _PRIOR_CHARS)}"
        )

    evidence_block = evidence.observations.strip()
    if evidence_block:
        evidence_section = f"""EVIDENCE GATHERED SO FAR (decide from THIS, in service of the request):
{evidence_block}"""
    else:
        evidence_section = """NO TOOLS HAVE RUN YET. Decide from the user's intent:
- Is this a casual greeting? ("Hi", "How's it going", "What's up")
- Is this a follow-up to a previous conversation? (what context is relevant?)
- Is this a new task? (what tools might be needed?)
- What should the agent do next? (respond directly, call a tool, or clarify)"""

    user = f"""USER REQUEST (what to accomplish): {request}{obj_line}{history_block}{prior_block}

{evidence_section}

Most recent action: {evidence.last_action or "(none)"}
Loop step: {evidence.iteration}

Decide whether the evidence/context moves the REQUEST forward and what the one next move is. Then give the JSON object."""
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
