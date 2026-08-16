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


def build_thinker_messages(evidence: Evidence) -> list[dict]:
    """Assemble the chat messages for a Thinker consult."""
    user = f"""OBJECTIVE (what the user ultimately wants): {evidence.objective or evidence.user_message}

EVIDENCE GATHERED SO FAR (reason about THIS):
{evidence.observations.strip() or "(nothing gathered yet)"}

Most recent action: {evidence.last_action or "(none)"}
Loop step: {evidence.iteration}

Think about the evidence above, then give the JSON."""
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
