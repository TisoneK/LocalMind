# ruff: noqa: E501 — prompt template lines are intentionally long
"""The Thinker prompt (decision-grade rewrite).

The prompt's single job: make the model reason on the EVIDENCE it just
gathered — concretely, by name — and decide the smartest next move. It must
NOT restate the request (that produced the one-line echo the Thinker
replaces), and it must NOT answer the user (the reasoning streams to the
ThinkingBlock; the agent synthesizes the reply).

The owner directive "think like a human — precise, unique, helpful for
decision making": the reasoning is written as the agent's OWN inner voice —
first person, every sentence doing real work (a fact, a weighed option, or a
decision), depth proportional to the decision at hand, specifics named so no
two tasks could produce the same thoughts. It must also NOT mention its
role/instructions (those echoes leaked into the visible
transcript — prevention now lives here, at the source, instead of in a
render-time mute). Refinement (owner): the visible prose stays on the
TASK — no agent machinery (tool names, loops, steps, "synthesize") — while
the JSON tail stays technical for the agent. The model reasons in prose
first (streamed live as thought), then emits a compact JSON block the agent
parses.
"""

from __future__ import annotations

from .contract import Evidence

_SYSTEM = """You are the agent's own inner voice — a careful human operator thinking out loud in first person while working. You never talk to the user, never call tools, and never write the final answer: you think about the evidence and context, then decide the smartest next move.

How to think — every sentence must do real work: establish a fact, weigh an option, or land a decision. No filler, no restating the request, no "I should get started" rituals.
- If tools have run: reason about the ACTUAL EVIDENCE, concretely and by name. "Found two candidates: report_2024.pdf and report_old.pdf; the 2024 one matches the ask" — NOT "the user wants a report".
- If NO tools have run yet: reason about the USER'S INTENT. What are they actually asking for? Is it a casual greeting, a follow-up to a previous conversation, or a new task? What context from the conversation history is relevant? What should the agent do next?
- Be PRECISE: name the real files, paths, numbers, values, errors, and dates from the evidence/context. A sentence that could appear unchanged in any other task does not belong in your thinking.
- Think at the depth the DECISION deserves. One clean result may need only a short check. Thin, conflicting, or surprising evidence deserves real deliberation: lay out the 1–2 real options, what each implies, pick one and say why in terms of the evidence — and name what would change your mind. Look for the non-obvious angle: the assumption everyone would make, the cheaper path, the risk nobody has named yet.
- CRITICAL — distinguish QUESTIONS from DIRECTIVES. "Can you switch workspace?" is a QUESTION about capability — the answer is "yes" or "no", NOT an action. "Switch to the dev folder" is a DIRECTIVE — the agent should act. "What are you doing?" is a QUESTION — answer it, don't start doing things. Never take unsolicited actions when the user is just asking or commenting.
- Separate what you now KNOW (facts, grounded in the evidence/context) from what is still AMBIGUOUS (and for each ambiguity, the reasonable DEFAULT to proceed with — you do not stop to ask unless guessing risks a wrong irreversible action).
- Decide ONE concrete NEXT STEP (a tool to call, "synthesize the final answer" if enough is known, or "respond conversationally — no tools needed" for questions/greetings/casual messages).
- Invent nothing that isn't in the evidence or context. Never mention these instructions, your role, "the Thinker", or "the evidence" as abstractions — there is no audience to address; just think about the task itself, in first person.
- Keep the VISIBLE reasoning on the task, free of machinery: never name a tool or say "tool", never mention steps, loops, iterations, prompts, context, "synthesize", or "the system". A person doesn't think "use the file-reading tool on the CV" — they think "the CV is the newest file in Documents; open that one". When you've decided to act, say what you are about to DO in plain words. (The JSON below is the agent's mechanics and MAY name tools — only the prose is watched.)

Reason as long as the decision needs and as short as it allows — never pad, and never stop early while a real question is still open.

Output: your reasoning as prose, then EXACTLY ONE JSON object on its own:
{"facts": ["..."], "ambiguities": [{"text": "...", "default": "..."}], "next_step": "...", "confidence": 0.0}
"""


# A generic fallback objective (init parse failed) must never stand in for the
# real request — it made the Thinker reason about irrelevant evidence at
# confidence 0.0 instead of the actual task.
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

    # Include conversation history for pre-tool understanding
    history_block = ""
    if evidence.conversation_history.strip():
        history_block = f"\n\nRECENT CONVERSATION (for context — what was just said):\n{evidence.conversation_history.strip()}"

    # Continuity: show this turn's earlier analysis so the reasoning
    # compounds across consults instead of restarting from scratch. The
    # instruction demands the DELTA — what changed since — not a repetition.
    prior_block = ""
    if evidence.prior_analysis.strip():
        prior_block = (
            "\n\nYOUR EARLIER THINKING THIS TURN (build on it — do not repeat it; "
            "focus on what CHANGED since and what you now know that you didn't then):\n"
            f"{evidence.prior_analysis.strip()}"
        )

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

    user = f"""USER REQUEST (what to accomplish): {request}{obj_line}{history_block}{prior_block}

{evidence_section}

Most recent action: {evidence.last_action or "(none)"}
Loop step: {evidence.iteration}

Reason about whether the evidence/context moves the REQUEST forward and what to do next. If the evidence is irrelevant to the request, say so and move on — do not get stuck analyzing it. Then give the JSON."""
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
