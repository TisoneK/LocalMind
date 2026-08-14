# Current Task

- **Session:** 194 (2026-08-13, complete)
- **Feature:** adr-8-agent-centric-routing (Phase 4 track 2 — find_path catalog contract)
- **Task:** User's design push — "why can't find_path work like Glob or Grep: find all
  files and paths once, then the agent filters or asks clarification?" Built the
  catalog contract on top of Session 193's deterministic file-ops layer.
- **Done (194):**
  - `tools/find_path.py`: budget-capped catalog walker (2.5s default, NO result cap
    during walk), bounded TTL cache (16 × 60s) — enumerate once, filter many; in-memory
    filters (kind/subpath/ext/exact), offset pagination, all_paths (full list for the
    picker), catalog metadata + content (total, folder/type breakdown, honest partial
    flag).
  - `core/file_ops.py`: spec filters pass through; picker sees the FULL catalog;
    catalog fields on result; `format_top_candidates` ranked ambiguous ask; shared
    `_score_match` (picker + shortlist can't drift).
  - `thinking_dispatcher.py`: "show more"/"only pdf"/"in Documents" → offset/ext/
    subpath signal args (survives the and-split).
  - `engine/_pipeline.py`: spec carry-through + ranked ambiguous ask, zero model calls.
  - Full backend **1728 green** (+22), ruff clean; code-review findings all fixed.
- **Next (backlog):** route the ambiguous-ask reply ("open CV-Tisone.docx") through the
  deterministic chain instead of the agent-loop follow-up path; then ADR-8 Phase 4
  track 1 (task-type classifier) or Phase 2 (build_context → BaseAgent.run) — both need
  real-model testing per the flaw log.
