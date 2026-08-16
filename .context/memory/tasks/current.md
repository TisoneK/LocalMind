# Current Task

**Status:** idle — Session 250 completed (research + design only, no code).

**Last completed:** Documented the tool-context architecture problem + fix.
The native `tools` param sends all 30 full "kitchen-sink" tool schemas
EVERY call (~6,334 tok) — the biggest per-call line item and why free
tiers run out of output budget (S249). A lean name+one-liner index is
~609 tok → ~5,725 tok/call (~90%) reclaimable by loading a tool's full
context ON DEMAND (the `skill` tool is the existing template). Wrote
ADR-40, review-40, backlog B-2026-08-16-1.

**Open next (implementation — its own session, needs a capable provider to
live-verify tool SELECTION):** B-2026-08-16-1 per ADR-40 — start with (B)
lean-but-callable schemas (strip to name + one-liner + non-obvious params +
guardrails; drop tutorial prose), live-verify tool-calling on cerebras;
then (C) on-demand loading for the long-tail tools. Keep guardrails; do NOT
claim a win from unit tests alone.

**Feature:** none
