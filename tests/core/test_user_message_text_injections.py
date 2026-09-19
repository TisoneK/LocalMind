"""`_user_message_text` must return what the user wrote, never a loop-injected
nudge. Live trace: the Thinker was given the recovery nudge as "USER REQUEST",
so its reasoning and next step were about the nudge, not the task."""
from __future__ import annotations

import pytest

from core.agent import loop as L

REQUEST = "List the folders in /Users/bao/Code and count the .py files."

# The real injected texts, taken from the loop's own constants and call sites.
INJECTED = [
    L._FORCE_TOOL_NUDGE,
    L._SYNTHESIZE_NUDGE,
    L._EVIDENCE_ANSWER_DIRECTIVE,
    "\n[ACTION NARRATION] You described what you would do but did not call any tool.\n",
    "\n[TOOL COMMITMENT] You wrote that you would use a tool.",
    "\n[COMPLETION FLOOR] You reported done, but your last action failed.",
    "\n[ZERO-TOOL] You have written text but made ZERO tool calls.",
    "\n[POST-EXECUTION VERIFIER] Your last tool reported an error:",
    "\n[ACCEPTANCE GATE] Your success criteria are NOT yet met:",
    "\nSYNTHESIS REMINDER: You have already gathered tool evidence.",
    "You reasoned about this task but returned no answer and no tool call.",
    "You described wanting to use a tool but did not call it.",
    "This request requires a tool call, but you did not call one.",
    "You returned an empty response. This request requires tool use.",
    "You tried to call tool 'x' but it's not available.",
    "[PROGRESS CHECK] You have called `shell` 3 times in a row.",
    "[DIVERGENT STOP] You have made many tool calls.",
    "[Tool result]: ok",
]


@pytest.mark.parametrize("nudge", INJECTED)
def test_injected_nudge_never_replaces_the_request(nudge):
    msgs = [
        {"role": "user", "content": REQUEST},
        {"role": "assistant", "content": "I'll start by listing."},
        {"role": "user", "content": nudge},
    ]
    assert L._user_message_text(msgs) == REQUEST[:200]


def test_stacked_nudges_still_resolve_to_the_original_request():
    msgs = [{"role": "user", "content": REQUEST}]
    for n in INJECTED[:6]:
        msgs += [{"role": "assistant", "content": ""}, {"role": "user", "content": n}]
    assert L._user_message_text(msgs) == REQUEST[:200]


@pytest.mark.parametrize(
    "typed",
    [
        "[URGENT] fix the login bug",
        "[Tool result] is what I pasted below, explain it",
        "SYNTHESIS is the part I don't get",
        "You tried a few tools already, right?",
        "Task: rename the files",
    ],
)
def test_a_real_user_message_is_never_mistaken_for_an_injection(typed):
    msgs = [
        {"role": "user", "content": "earlier question"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": typed},
    ]
    assert L._user_message_text(msgs) == typed[:200]


def test_no_user_message_returns_empty():
    assert L._user_message_text([{"role": "system", "content": "s"}]) == ""
