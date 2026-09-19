# Notes: stage-prompts (append-only while alive)

## 2026-09-19 — Imani (S024)
- Method that worked: tap the HTTP layer (requests AND streamed responses) in a harness outside the repo;
  it found three input/adapter bugs no log showed. Keep doing this before changing any prompt.
- Serial runs only per provider key; count `429` per run; a "valid" run needs a clean final synthesis
  (look for "rate-limited on my final synthesis" in the answer), not just no error event.
- The repo's HEAD moves while agents work — never score against the live repo; use the fixture.
- glm-4.5-flash with thinking ON: reasoning-only replies were an ADAPTER bug (fixed), not model behavior.
