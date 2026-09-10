# .context_ledger/ — Agent Memory + Vendored Protocol

<!-- CORE-OWNED — refreshed from core/templates/ledger-README.md on
core updates. Project-specific notes belong in memory/ files, never here. -->

This directory makes any AI agent — any model, any machine, local or
cloud — a continuing member of this project instead of a stranger. It
is committed to git and travels with the repo. It has **two zones**:

```text
.context_ledger/
├── README.md     # this file — the zone map
├── kickoff.md    # THE FRONT DOOR — read this first, every session
├── core/         # the protocol, vendored — package-owned, READ-ONLY
│   ├── VERSION           # core semver in force here
│   ├── rules/            # the protocol editions (local + cloud)
│   ├── roles/            # mission overlays
│   ├── schemas/          # ledger-schema.md — the single source of truth on formats
│   ├── templates/        # what memory files are generated from
│   └── bin/              # ledger-sync + ledger-collab (+ .ps1): sync, peer coordination, and integration checks
└── memory/       # this project's living memory — project-owned, writable
    ├── agents/sessions.md       # append-only session log
    ├── collaboration/           # opt-in peer coordination
    │   ├── README.md            # worktree + event contract
    │   └── events/               # immutable one-file-per-event records
    ├── tasks/current.md         # task in progress (single-agent lock only)
    ├── tasks/backlog.md         # live queue of open items (delete a line when done)
    ├── plans/decisions.md       # append-only ADRs
    ├── flaws/log.md             # protocol friction — flows upstream to the package
    ├── inefficiencies/log.md    # project friction
    ├── reviews/                 # session reports
    ├── workflows/
    │   ├── active.md             # standing session parameters
    │   └── gates.conf             # explicit lifecycle commands + hybrid discovery mode
    ├── system/                  # machines + agent/model registry
    ├── user/                    # identity + preferences
    ├── overrides/rules.md       # project-local protocol adjustments
    ├── sessions/                # per-session detailed notes (optional, deletable)
    │   ├── SUMMARY.md           # compressed history — entries are removable
    │   └── YYYY-MM-DD-N/
    │       └── notes.md         # session-scoped detail
    ├── core.lock                # last-known-good core version (ledger-sync writes it)
    └── secrets/                 # LOCAL-ONLY — self-gitignored, never travels
```

## The three rules that matter most

1. **Never write under `core/`.** It is a versioned, checksummed copy
   of the protocol package — updated only as a whole tree by
   `core/bin/ledger-sync`. Protocol improvements go to the package
   repo via `memory/flaws/log.md`, not into this copy.
2. **`memory/` is this project's data.** Write it per each file's mode —
   append-only logs stay append-only, `chore(ledger):` commit prefix,
   no secret values in tracked files, ever. The full spec:
   `core/schemas/ledger-schema.md`.
3. **Sessions start at `kickoff.md`** (one level up from memory —
   `.context_ledger/kickoff.md`). It routes you by agent type to your edition
   in `core/rules/`. Memory never chooses your edition — your agent
   type does. For concurrent work, use isolated branches/worktrees and
   `memory/collaboration/events/`; overlapping changes require a peer
   agreement before implementation.
