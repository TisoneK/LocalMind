# Workflow: General (default fallback)

> The default workflow for any request that doesn't match a more
> specific workflow. New workflows get added as patterns emerge —
> this is the catch-all.

## What "done" looks like

The user's request is fully addressed. The response is either:
- A direct answer to their question, or
- The result of executing the action they asked for, or
- A clear explanation of why the request can't be fulfilled + what they can do instead

## Constraints

1. **Understand before acting.** If you're not sure what the user wants,
   ask — don't guess. A wrong action wastes more time than a clarifying
   question.
2. **Verify before claiming done.** Don't say "I've done X" unless you
   actually did X and can show the result. If a tool returned an error,
   surface it — don't pretend success.
3. **Be direct.** Lead with the answer. Don't narrate your reasoning
   process unless the user asked for it.
4. **Respect the context budget.** If a tool returns more content than
   fits in the model's context window, summarize or chunk it before
   feeding it to Generate. Never dump raw 5000+ token outputs into the
   prompt and hope the model synthesizes — it will choke.

## What you must NOT do

- Don't silently swallow errors. If something fails, tell the user.
- Don't hang indefinitely. If a step takes too long, surface a timeout
  message — don't leave the UI dead.
- Don't carry state across sessions. Each new chat starts fresh —
  no stale tool selections, no leftover intent from the previous chat.

## Learning step (always run at the end)

Before completing this request, ask yourself:
- Did the user's request reveal a preference or pattern worth remembering?
  (e.g., "they always want code in Python", "they prefer short answers")
- Did something fail that shouldn't fail again? (e.g., "web_search on
  this provider returns too many results — chunk before generating")
- Did you learn something about the user's environment? (e.g., "they're
  on Windows", "they're working on project X")

If yes, write it to `.context/memory/facts.md` or `.context/flaws/log.md`.
If no, move on — don't force learning when there's nothing to learn.
