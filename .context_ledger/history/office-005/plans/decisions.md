# Architectural Decisions (append-only, ADR-style)

Decisions already made — future agents respect these rather than
relitigating them. To reverse one, append a new ADR that supersedes it.

<!-- TEMPLATE — copy below the last entry:
---
## ADR-N: <short title> (YYYY-MM-DD)
- **Status:** accepted | superseded by ADR-M
- **Context:** <what forced the decision>
- **Decision:** <what was decided>
- **Consequences:** <trade-offs accepted; what future agents must respect>
-->

---
## ADR-73: Carryover decisions in force from the closed office (2026-11-02)
- **Status:** accepted
- **Context:** the previous office closed; its frozen decisions live at
  `history/office-004/plans/decisions.md` and its permanent summary at
  `history/office-004.md`. The decisions below still bind.
- **Decision:** respect ADR-41 (thinking policy on the answer path), ADR-66b
  (an answer is final when the reply is final; post-turn bookkeeping runs as
  detached lanes), ADR-67 (refuse only on a verified fact, name the fact and
  the confirming flag), ADR-69 as amended (explicit `fallback_to` only — no
  implicit keyed-provider tail; record `{from, code, to}`; identity stamps
  name the adapter that actually served), ADR-70 (where commands run and where
  installs land are user settings), ADR-71 (state engine beside the classic
  parent; engine owns state; read-only by construction in slice 1; every step
  is an `EngineEvent`; `Auto` not built first), and ADR-72 (the engine is
  environment-agnostic; LocalMind is its first adapter; no engine import of
  LocalMind).
- **Consequences:** the live-testing bar is mandatory for loop / tool /
  adapter changes; cure the disease, not single prompts; fixes are model- and
  environment-agnostic ("there is no weak model", neutral terms only); a
  wording-dependent defect gets a semantic or state check, never a wording
  list; never port 8000 — isolated 8765 + `LOCALMIND_HOME` only; no secrets in
  tracked files; push to main after each commit.
