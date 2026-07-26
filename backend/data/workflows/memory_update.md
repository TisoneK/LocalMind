# Workflow: Memory Update (writing to .context/)

> For when the agent learns something during a session that should
> persist to `.context/` — user facts, system info, codebase
> conventions, or flaws. This is the WRITE side of the learning loop.

## What "done" looks like

The learned fact is:
- Written to the appropriate `.context/` file
- Concise (one line per fact, not a paragraph)
- Useful to a future session (not trivia)
- Timestamped or attributable so it can be pruned if stale

## Constraints

1. **Write facts, not narration.** "User prefers Python 3.12" is a
   fact. "The user asked about Python and I helped them" is narration.
   Only write facts that a future session would act on.

2. **Write to the right file.**
   - `.context/user/preferences.md` — how the user likes things done
   - `.context/user/identity.md` — who the user is (name, role, timezone)
   - `.context/system/environment.md` — machine facts (OS, tools, hardware)
   - `.context/system/models.md` — model strengths/weaknesses observed
   - `.context/agents/capabilities.md` — what each agent can do
   - `.context/codebase/architecture.md` — how the codebase is structured
   - `.context/codebase/known_bugs.md` — bugs found and fixed
   - `.context/memory/facts.md` — accumulated user facts
   - `.context/flaws/log.md` — what went wrong + what was learned

3. **Don't overwrite — append.** `.context/` files are append-only
   (except preferences/identity which update in place). Add new facts
   at the bottom. If a fact contradicts an old one, append the
   correction — don't edit history.

4. **Prune aggressively.** If a fact is stale (the user's environment
   changed, the bug was fixed, the preference no longer applies),
   either update it in place (for preferences/identity) or note the
   supersession in an append (for logs).

5. **Never write secrets.** API keys, passwords, tokens — never. If
   the agent learned a secret, it goes in the secrets store, not
   `.context/`.

## What you must NOT do

- Don't write narration or session logs to fact files.
- Don't write facts that are obvious (e.g., "the user has a keyboard").
- Don't write facts that are too specific to be reused (e.g., "the user
  said 'hi' at 3pm on Tuesday").
- Don't overwrite append-only files — append corrections instead.

## Learning step

This workflow IS the learning step. The fact that it ran means the
agent identified something worth remembering. The quality check:
would a future session act differently because this fact exists? If
yes, it was worth writing. If no, prune it.
