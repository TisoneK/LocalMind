# Review — S002 (Nadia) — the Harness skin + a correct turn/step reading

- **Date:** 2026-10-26
- **Agent:** Nadia (S002), deepseek-flash
- **Task:** adopt the DeepSeek Harness skin and fix the turn/step vocabulary, after the owner supplied the public Harness source (`deepseek-ai/deepseek-harness`, MIT).
- **Scope:** frontend only; no backend or agent-loop change in this slice.

## What the owner asked for

Two things, in one message: the **skin** of the DeepSeek Harness desktop app, and a fix for the feeling that a LocalMind turn is "just little fixed steps … not that deep dive." The owner also noted that turns and steps had been confused.

## What the Harness source says (the concepts transferred)

Cloned the public repository (`master`, sparse checkout of `apps/`, `packages/`, `docs/`) and read the packages that own these two concepts:

| Harness package | What it defines | What we took |
|---|---|---|
| `packages/client/ui-theme` | The exact neutral-bluish token ramps, hairline borders, one DeepSeek-blue accent, text/code font stacks, 4/8/12/16/20/28 px radii | The **Harness** palette blocks in `globals.css` (dark and light), the Harness surface mapping (transcript is the ground, rails are layers above it), and the text stack |
| `packages/session/session-stats` | `turns` = distinct turns with ≥1 closed step; `steps` = closed `step/end` events; plus LLM/tool/first-token/decode wall time | The **turn/step contract** behind the new strip; plan checklist items are not steps |
| `packages/client/ui-chat/src/client/chat/StatsPills.tsx` | The composer's `turns · steps · tok/s` and `tokens · cache hit` readings | The reading layout and compact formatting (`19M tok`, `Cache hit 99%`) |
| `packages/goal/goal` + `goal-round-driver` | A durable same-session goal; an idle driver queues a `<goal_round>` continuation turn until the objective is complete or a round cap is hit | **Design reference for the next slice**, not implemented here |

Key conceptual correction: a **turn** is one user request. A **step** is one entered model iteration inside it; tool calls happen inside steps and do not add steps. A plan is a prior the agent may rewrite — its checklist item count is not a step count. LocalMind was showing the plan's `Step n/m` badge, which made a turn look finished when its fixed checklist was done.

## Shipped

1. `38eaf01c` **feat(ui): adopt the DeepSeek Harness skin** — `harness` theme (dark + light) with the Harness neutral-bluish ramp and DeepSeek blue; Harness surface mapping so the transcript is darker than the rails; Harness text/mono stacks; Harness becomes the default for fresh installs (existing stored choices are preserved); neutral boot screen; sidebar on the panel surface; "New Session"; calmer composer (sans text, rounded-xl, pill mode picker, round send button).
2. `c607ed60` **feat(chat): read turns and steps the Harness way** — `ChatStatsStrip` under the composer (`N turns · M steps · 200 tok/s · 19M tok · Cache hit 99%`), with `Deep diving for 4m16s…` while a turn is open; `sessionReading.ts` pure reading builder with the turn/step contract; the TurnView badge now says `Plan n/m`, never `Step n/m`.

## Verification

- Frontend suite: **609 passed / 59 files**.
- `tsc -b --noEmit`: clean.
- `ledger-gates run pre-commit`: pass.
- Built the production bundle (`npm run build -w localmind-frontend`): pass.
- **Visual:** rendered the app in Electron against the Vite dev server and captured `scratch/harness-skin/harness-skin.png`. Confirmed the neutral canvas, rail elevation, blue accent, New Session surface, sans composer, mode pill and round send button. The backend was offline, so the strip shows only the keyboard hint; the populated reading is covered by the component test.
- Not verified live: a real streamed turn showing the populated strip. The reading is pure and tested, but the assembled UI was only seen at rest.

## Not done / next

- **The deep-dive behavior.** Raising the accent's depth is not a step-budget tweak: the Harness source fixes it with a *goal round driver* — a durable same-session objective that survives a turn ending, and a driver that queues the next round at idle until the objective is complete or the cap is hit. LocalMind's retired `ObjectiveRuntime` already implements a read-only version of exactly this loop (`MAX_OBJECTIVE_ROUNDS`, `ROUND_CONTINUATION`, natural-end vs hit-limit). The next slice should bring that loop into the chat session, write-capable behind the existing confirmation rules, with `get_goal` / `update_goal` tools and a round meter in the composer.
- **Structural shell parity** (optional): the Harness app's brand rail + nav + workspaces, the `Chat / Trajectory` tab strip, and the right-side `Start` cards. This slice deliberately changed surfaces and tokens, not the information architecture.
- **Live verification** of the agent-loop slice on an isolated backend (never port 8000) with a weak model, per the project's live-testing bar.

## Risks / notes

- Making Harness the default only affects users with no stored theme; any saved palette wins.
- The strip's `steps` reads `SessionStats.llmCalls` (calls that reported usage). A provider that omits usage on a call undercounts that step; the durable `step/end`-based count the Harness uses has no LocalMind equivalent yet.
- The token/cache figures are durable-session + open-turn; speed falls back to the open turn's own provider reading until the first turn settles.
- The existing eslint warning budget (`B-2026-09-21-1`) is unchanged; no new warnings came from the new files.
