# ruff: noqa: E501 — prompt templates are intentionally long lines.
"""Fail-closed templates for auxiliary model calls.

Auxiliary calls — a checkpoint summary, a classification, a judgment —
spend a model call to produce structured material the turn then RELIES on.
A soft "please summarize" ask with no output contract produces exactly one
failure mode that matters: an output cut by the model's limit lands as if
it were complete, and the turn replaces real history with a half-artifact.
The discipline here is the opposite of ad hoc:

1. **Exact skeleton** — the instruction names the output structure
   section-by-section; a section with nothing to say says "(none)"; no
   section is ever dropped.
2. **Verbatim preservation** — the classes of text a checkpoint must never
   paraphrase (paths, commands, identifiers, numbers, the user's own
   wording for a constraint) are named in the instruction.
3. **Fail-closed validation** — the output is checked BEFORE it is used:
   empty output and a missing required section (the signature of an
   output-limit cut) both raise, and the caller keeps its original
   material. An incomplete checkpoint never lands.
"""

from __future__ import annotations

from typing import Optional

__all__ = [
    "AuxiliaryCallError",
    "AuxiliaryCallOutputError",
    "SUMMARY_SECTIONS",
    "build_summary_call_prompt",
    "validate_summary_output",
]


class AuxiliaryCallError(Exception):
    """An auxiliary model call could not produce usable material."""


class AuxiliaryCallOutputError(AuxiliaryCallError):
    """The auxiliary call's output violated its contract — fail closed."""


# The summary checkpoint's required sections, in render order. The
# validator demands every one of them; "(none)" is the documented empty
# marker, so an empty section is still a PRESENT section.
SUMMARY_SECTIONS: tuple[str, ...] = (
    "[Continuing task]",
    "[Decisions and constraints]",
    "[Open threads]",
)

_SUMMARY_NONE_MARKER = "(none)"

_SUMMARY_SKELETON = (
    "You are a conversation summarizer. Condense the conversation excerpt "
    "below into the EXACT structure shown — all three section headers, in "
    "this order, each on its own line:\n"
    "[Continuing task] — what the user is trying to get done and how far it "
    "has progressed.\n"
    "[Decisions and constraints] — choices made, options rejected, "
    "preferences stated, hard limits.\n"
    "[Open threads] — what remains undone, was promised, or was asked and "
    "not yet answered.\n"
    "\n"
    "Rules:\n"
    "- Never drop a section. A section with nothing to say contains exactly "
    f"{_SUMMARY_NONE_MARKER} and nothing else.\n"
    "- Preserve VERBATIM: file paths, commands, tool names, identifiers, "
    "numbers, error strings, and the user's own wording for a preference or "
    "a rejection. A decision the user made in their own words must survive "
    "in those words, not as your paraphrase of it.\n"
    "- Do not invent facts, do not add a preamble or a closing remark, and "
    "do not comment on the task of summarizing.\n"
    "- Do not call tools."
)


def build_summary_call_prompt(task_focus: Optional[str] = None) -> str:
    """The summary checkpoint's instruction: skeleton + rules, fail-closed.

    `task_focus` is the task-aware policy's own focus line (what deserves
    the most care for THIS kind of conversation) — it rides AFTER the
    skeleton so the structure contract is never displaced by it.
    """
    prompt = _SUMMARY_SKELETON
    if task_focus:
        prompt += f"\n- For this kind of conversation, weight this most of all: {task_focus}"
    return prompt


def validate_summary_output(text: str) -> str:
    """Check a summary checkpoint against its contract — fail closed.

    Returns the cleaned text when it satisfies the skeleton. Raises
    AuxiliaryCallOutputError when it does not: an empty output (the call
    produced nothing) or a missing required section (the signature of an
    output-limit cut). The caller keeps its original material in both
    cases — compression is skipped, never half-applied.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        raise AuxiliaryCallOutputError(
            "summary checkpoint came back empty — there is nothing to keep; "
            "compression skipped, original history intact"
        )
    missing = [s for s in SUMMARY_SECTIONS if s not in cleaned]
    if missing:
        raise AuxiliaryCallOutputError(
            "summary checkpoint is INCOMPLETE — required section(s) missing: "
            f"{', '.join(missing)} (the signature of an output cut mid-"
            "generation); an incomplete checkpoint never lands — compression "
            "skipped, original history intact"
        )
    return cleaned
