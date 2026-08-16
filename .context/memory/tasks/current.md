# Current Task

**Status:** done — Session 256: fixed the user-reported "Agent loop failed — empty_response" on z.ai/glm-4.5-flash with thinking ON (recipe-on-desktop turn: iter-1 ran shell, iter-2 streamed reasoning then returned no content/tool call → whole turn failed). Root cause: with thinking re-enabled, a slow free tier sometimes "thinks but doesn't act"; the loop's empty-response guard treated reasoning-only streams as empty. Fix: one bounded retry with a continue-nudge when reasoning streamed but no text/tool call arrived (`_MAX_EMPTY_REASONING_RECOVERIES = 1`); a second consecutive empty still fails fast. 2 regression tests; suite 1,799 pass. See review-46.

**Feature:** none
