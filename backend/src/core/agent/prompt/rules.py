"""Shared instruction rules — one canonical statement per rule.

Several behavior rules are load-bearing on MORE than one prompt surface
(the parent execution prompt, the conversational fast path, the thinker
consult). When each surface carries its own copy, the copies drift and
a fix to one surface silently misses the others. Each rule below is the
single canonical statement; surfaces that need it embed the constant and
add only their surface-specific framing around it.

A rule text here is contract: changing wording changes several prompts at
once — update the consuming surfaces' tests together, never hand-edit a
surface's copy back in.
"""

from __future__ import annotations

# QUESTIONS vs DIRECTIVES. Lived incident: "Can you switch workspace?" was
# taken as a command and the agent acted; "what are you doing?" invited an
# action instead of an answer. Every conversational and analytical surface
# carries this rule.
QUESTION_VS_DIRECTIVE_RULE = (
    "Distinguish QUESTIONS from DIRECTIVES. A QUESTION asks about capability "
    "or state — answer it; a DIRECTIVE requests an action — take it. "
    "\"Can you switch workspace?\" is a QUESTION about capability (\"do you "
    "have this capability?\"), not a command to switch. \"What are you "
    "doing?\" needs an answer, not an action. \"Switch to the dev folder\" "
    "is a DIRECTIVE — act on it. Only take an action when the user gives a "
    "DIRECTIVE; never take unsolicited actions when the user is just asking "
    "or commenting."
)

# The capability-honesty spine. Lived incident (user live-report): without
# it, the conversational surfaces fabricate "I don't have access to your
# filesystem" / "I can't do that" — a false claim that spirals once the
# model starts. The two lightweight-reply variants below share this spine;
# only their tails differ (direct chat has an Agent mode to point at; auto
# has no modes at all).
CAPABILITY_HONESTY_SPINE = (
    "You are LocalMind, a real AI agent running ON the user's machine with "
    "actual tools (shell, file read/write/delete, code, web). NEVER claim you "
    "lack access to the filesystem or that you 'can't' do something you could "
    "do with a tool — that is false. "
)

# Auto mode has no "other mode" to switch to: one loop decides per message
# whether to act. A lightweight reply that ends up needing a tool must not
# send the user off to a mode that does not exist for them (owner live-report:
# "Found it and???" got a promise plus "flip me to Agent mode" in an Auto
# session).
NO_MODES_RULE = (
    "There are no modes for the user to switch between; never mention modes. "
)
