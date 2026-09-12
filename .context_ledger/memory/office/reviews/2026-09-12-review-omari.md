# Review — 2026-09-12 — Omari (S472), frontend: the thinking block now formats the thought

## What happened

The owner reported: "the thinking block does not format the LLM's thought."
Root cause confirmed in code: the chat answer renders model text through the
app's themed markdown pipeline (repair → ReactMarkdown + GitHub-flavored
markdown + themed components), but the Thinking block skipped all of that —
it printed the model's reasoning as one raw text node. Any reasoning written
in markdown (headings, bullets, **bold**, code snippets) therefore arrived
flattened into an unformatted wall of text. The formatting was never missing
on the answer side; it was simply never wired into the thinking side.

## What changed

- Extracted the themed markdown pipeline out of `ChatMessage.tsx` into a new
  shared component, `frontend/src/components/shared/MarkdownContent.tsx`.
  This is a verbatim move; `ChatMessage` keeps rendering exactly as before,
  now importing the shared component. One source of truth for markdown
  formatting instead of two renderers drifting apart.
- `ThinkingBlock.tsx` now renders the thought through that same pipeline.
  The live streaming caret, the copy button (still copies the raw source),
  the structured `[Label] detail` step-line chips, the bounded-height
  auto-scroll, and the collapse-after-answer behavior are all preserved —
  only the text-vs-markdown path changed.
- Added markdown-formatting cases to `ThinkingBlock.test.tsx` (bold renders
  as `<strong>`, bullets render as list items, `##` headings format instead
  of showing the marker, and the copy button still copies raw source).
- One CHANGELOG entry under Fixed, plain language.

## What was verified vs assumed

- `tsc -b --noEmit`: clean (rc=0).
- `eslint . --max-warnings 53`: rc=0 at exactly 53 warnings — the move
  carried the existing `any` warnings with it, no net-new lint debt.
- `vite build`: clean (rc=0).
- `vitest`: ThinkingBlock 14/14 green, plus TurnTimeline and buildAgentPhase
  suites green.
- The full frontend vitest run shows ~7–9 failures, but they are
  **pre-existing flake**, not caused by this change: a baseline run of the
  full suite on the *unmodified* tree fails a different, overlapping set in
  files this change never touches (ChatInput, LeftPanel, FilePreviewDialog,
  SettingsModal); every suspect file passes in isolation. The exit gate
  (`scripts/ci-check.sh`) runs tsc + eslint + ruff + pytest only — it does
  not run vitest — so this flake cannot gate the session. Worth a future
  backlog item on frontend-test determinism.
- This is a UI-rendering change; the provider/loop live-testing bar was
  considered and judged not to apply (nothing touched the SSE stream, the
  loop, or an adapter). It was verified through the component tests above
  plus a clean production build.

## Coordination

Owner confirmed the split: Kojo (S471) owns the backend thinking path and
workspace-persistence symptoms (which surfaced after yesterday's
history-feed fix, `78fadbcc`); I own the frontend thinking-block formatting.
Zero path overlap. The owner's regression-timeline message was relayed to
Kojo by note event before either of us went further. Worked in an isolated
worktree per the project override (a peer was live), claim → work → release,
and integrated to main by fast-forward so the shared checkout was never
touched.

## Still open (not mine)

- Backend: glm-5.3-flash silent >60s thinking and agent-workspace
  non-persistence — Kojo's scope.
- Frontend-test flake (documented above) — candidate backlog item.
