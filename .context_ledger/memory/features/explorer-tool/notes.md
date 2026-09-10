# Session 459 — Explorer tool design notes

## Context

Owner: "design Explorer tool for LocalMind — tool for exploring files and
folders." A generic blueprint was pasted (5 functions, multi-agent framing, a
fixed `BASE_DIR` jail). The brief's memory of LocalMind was wrong (multi-agent),
so the design re-grounded it in the actual tool surface.

## Key findings (the constraints that shaped the design)

1. **The gap is real but narrow.** LocalMind already has `system_search`
   (find), `file_task` (read), `grep_search` (content). Only directory
   *inspection* (list/tree/stat) is missing — today it's done via unbounded
   `shell ls`/`tree`, the exact pattern Sessions 124/125 fixed.
2. **Schema budget is a hard constraint (ADR-40).** Adding 5 tools would blow
   the per-call token budget and risk the `find_path` name-affinity failure
   (S400: weak models split traffic between two name-search tools). So: ONE
   tool, three ops, mirroring `system_search`.
3. **`system_search` is the model to copy.** One front door, sub-operations,
   normalized rows, bounded by construction, never raises, honest `walk_complete`
   flags.
4. **Security is already solved** via `settings.is_path_allowed` — no bespoke
   jail. Explorer returns only names+metadata, never bytes, so a read-only tool
   cannot exfiltrate secrets even if pointed at an allowed root containing a
   `.env`.
5. **UX primitives exist.** `ToolSteps.tsx` + `action_label` render every tool
   call; `ToolResult.requires_confirmation`/`RiskLevel` are the permission
   mechanism. Explorer is read-only → never prompts. No new UI needed.
6. **Pairs with the safety workflow.** `backend/data/workflows/safety.md`
   (check-before-acting) currently uses shell `ls`/`file_task` errors as the
   pre-flight check; Explorer makes that bounded and first-class.

## Decisions made this session

- ONE tool `explorer` = {list, tree, stat}; read_file → `file_task`, search →
  `system_search` (no duplication).
- Read-only by construction; reuse `find_path._HEAVY_DIR_NAMES`/`_walk_catalog`.
- Proposed CORE tier, position after `system_search` — contingent on ADR-40
  weak-model live trace.

## Open questions handed to owner (doc §9)

- Name collision `explorer` vs `browse` (web browser tool).
- Core vs long-tail tier.
- `trivial_input.py` routing extension for "show me / structure of".
- `tree` output format (plain text vs JSON).

## Process note (worth a memory entry)

During check-in, Kofi (S458) was mid-closeout — the working tree had 5 dirty
memory files (uncommitted closeout), and the roster was updated live under my
edit. The project override (overrides/rules.md) made collab-topology mandatory
while a peer was live. Kofi's closeout landed (`f8d17aff`) before I began
product work, so I ran standard solo mode. Lesson: when `git status` shows
uncommitted `.context_ledger/` edits you didn't make, treat it as a live peer
and isolate — don't `git add` whole files (would sweep their hunks).
