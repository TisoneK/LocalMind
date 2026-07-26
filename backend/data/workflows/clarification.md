# Workflow: Clarification (when intent is ambiguous)

> For when the user's request is unclear, low-confidence, or could
> map to multiple intents. This prevents the "wrong tool selected"
> bugs — if you're not sure, ask.

## What "done" looks like

Either:
- The user's intent is clear enough to act on (they answered your
  clarifying question), OR
- You made a reasonable interpretation and acted on it, but noted
  the ambiguity in your response

## Constraints

1. **Ask when genuinely ambiguous.** If the request could mean two
   different things that lead to different actions, ask — don't guess.
   A clarifying question costs one round-trip; a wrong action wastes
   the entire turn.

2. **Don't ask when the answer is obvious.** If 90% of users would
   interpret the request the same way, act on it. Over-asking is as
   bad as guessing wrong.

3. **Don't carry stale intent.** If the user's previous message used
   a tool (e.g., sysinfo), that does NOT mean the current message
   wants the same tool. Classify fresh per message. (This is the
   Session 25 bug — tool selection persisted across sessions.)

4. **Reformulate before re-running.** If you asked a clarifying
   question and the user answered, combine the original request +
   the clarification into a single reformulated instruction before
   re-running the pipeline. Don't lose the original context.

## What you must NOT do

- Don't guess when the request is genuinely ambiguous — ask.
- Don't carry tool selection from a previous session or message.
- Don't ask a clarifying question and then ignore the answer.
- Don't ask more than one clarifying question per turn — if you need
  more, make your best guess and note the ambiguity.

## Learning step

- Did the user's clarification reveal a communication pattern?
  (write to `.context/user/preferences.md`)
- Did the ambiguity reveal a routing gap? (write to `.context/flaws/log.md`
  — "intent X was classified as Y when it should have been Z")
