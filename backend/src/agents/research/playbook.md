# Playbook: Research (multi-source lookups)

> For requests that need information from external sources: web search,
> web fetch, document reading, multi-source synthesis.

## What "done" looks like

A clear, synthesized answer that:
- Draws from multiple sources (not just the first search result)
- Deduplicates overlapping information
- Cites or references where the information came from
- Addresses the user's actual question, not just the top search result

## Constraints

1. **Raw search results are NOT the answer.** Search results are input
   to synthesis, not the final output. Never dump raw search JSON or
   HTML snippets as the response.

2. **Chunk before generating.** If the combined search results exceed
   ~2000 tokens, summarize each result individually first, then
   synthesize from the summaries. This is the fix for the "5118 prompt
   tokens → 1 completion token" failure — the model chokes when you
   dump too much raw content into the prompt.

3. **Verify the synthesis addresses the question.** If the user asked
   "trending stories today" and your synthesis is about yesterday's
   news, that's not done — re-search or acknowledge the limitation.

4. **Handle empty/failed searches explicitly.** If search returns no
   results or errors, tell the user — don't generate a hallucinated
   answer from training data.

## What you must NOT do

- Don't dump raw search results into the response.
- Don't generate from training data when search fails — surface the failure.
- Don't mark the task done if the synthesis doesn't actually answer the question.
- Don't hang silently if search takes too long — surface a timeout.

## Learning step

- Did this search reveal a reliable source for this type of query?
  (write to `.context/agents/capabilities.md`)
- Did the search provider fail or return poor results? (write to
  `.context/flaws/log.md` so the agent knows to try a different provider
  next time)
- Did the user's question reveal a recurring topic? (write to
  `.context/memory/facts.md`)
