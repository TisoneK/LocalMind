# The `.context_ledger/` Schema — Single Source of Truth

This file defines every file in a project's `.context_ledger/` directory: where
it lives, who owns it, how it may be written, and which *scope* its facts
belong to. When any other document (a README, an edition, a template
comment) disagrees with this schema, **this schema wins** — and the
disagreement is a flaw to log.

A machine-readable mirror lives beside this file as
`ledger.schema.json`. The markdown is authoritative; the JSON is
generated from it by hand and must be updated in the same commit as any
schema change.

---

## The two zones

```text
{project}/
├── AGENTS.md              # generated digest for agent discovery (see Translation layer)
├── CLAUDE.md              # pointer so Claude Code (auto-loads CLAUDE.md) reaches the protocol
└── .context_ledger/
    ├── README.md          # zone map — copied from core/templates at bootstrap/update
    ├── kickoff.md         # front door — generated at bootstrap, project-owned
    ├── .gitattributes     # LF policy for core + memory (Windows CRLF guard)
    ├── core/              # ZONE 1 — package-owned, READ-ONLY, version-stamped
    ├── memory/            # ZONE 2 — project-owned, writable, never synced; holds the LIVE office + durable files
    ├── history/           # closed offices (frozen verbatim) + permanent accomplishments records — NOT read at session start
    └── archive/           # cold storage of closed offices (zipped) — NOT read at session start
```

`history/` and `archive/` hold closed offices produced by `ledger-history`
(see **Office lifecycle** below). They are never in the session-start
reading order — only the live office in `memory/office/` is.

| Zone | Owner | Agents may write? | How it changes |
|---|---|---|---|
| `core/` | The protocol package | **Never.** Not one byte. | Only via `ledger-sync update` (whole-tree, version-stamped) |
| `memory/` | The project | Yes — per each file's write mode below | Normal session work, committed with the project |

The zone rule is the entire sync model: **core is replaced as a unit,
memory is never touched by sync.** There is no per-file structural/data
classification anymore (the old `SYNC.md` basename rule is retired). If
you are editing a path that starts with `.context_ledger/core/`, stop — you are
either syncing (use `ledger-sync`) or making a protocol change, which
belongs in the package repo, not in a project.

Two root files sit outside both zones:

- **`.context_ledger/README.md`** — the zone map. Package-owned *content*
  (refreshed from `core/templates/ledger-README.md` on core updates)
  but deliberately kept at the root so a fresh agent's first `ls` +
  `cat` explains the layout.
- **`.context_ledger/kickoff.md`** — the front door. Project-owned **data**:
  generated once at bootstrap from `core/templates/kickoff.md`, its
  facts kept current by sessions. Core updates never overwrite it; if
  its template changes materially (see `core/CHANGELOG.md`), the next
  session **regenerates** it from the new template and refills the
  facts from memory.

---

## Zone 1 — `core/` (read-only reference)

```text
core/
├── VERSION              # semver of this core tree, e.g. 0.2.0
├── CHANGELOG.md         # one entry per release + migration notes
├── MANIFEST.sha256      # checksums of every core file — integrity check
├── bin/
│   ├── ledger-sync     # POSIX-sh: status / verify / update / migrate / rollback / bootstrap
│   ├── ledger-sync.ps1   # PowerShell port (Windows): status / verify / update / rollback / lock
│   ├── ledger-collab       # POSIX-sh: atomic collaboration events + status + check
│   ├── ledger-collab.ps1   # PowerShell port (Windows): emit + status + check
│   ├── ledger-collab-check # POSIX integration-readiness validator
│   ├── ledger-collab-check.ps1 # PowerShell integration-readiness validator
│   ├── ledger-gates        # POSIX lifecycle gates + checkpoint
│   ├── ledger-gates.ps1    # PowerShell lifecycle gates + checkpoint
│   ├── ledger-mem          # POSIX: check (registry dup keys) + lint (.context_ledger leak) + prune (log-archive advisory)
│   ├── ledger-mem.ps1      # PowerShell port: same hygiene checks
│   ├── ledger-history      # POSIX: office lifecycle — freeze the live office verbatim,
│   │                        #   number it at close, rotate memory/office→history→archive→gc
│   ├── ledger-history.ps1  # PowerShell port: office rotation
│   └── context-*.cmd        # cmd.exe launchers, one per .ps1 port: each
│                            #   runs it with -ExecutionPolicy Bypass -- no
│                            #   Windows Set-ExecutionPolicy setup needed
├── rules/
│   ├── ai-engineering-protocol-local.md   # LOCAL agents' edition
│   └── ai-engineering-protocol.md         # CLOUD/SANDBOX agents' edition
├── roles/               # mission overlays: reviewer, security-auditor, docs-agent, feature-engineer
├── schemas/
│   ├── ledger-schema.md         # this file
│   ├── ledger.schema.json       # machine-readable mirror
│   └── collab-event.schema.json # collaboration event document (v1)
└── templates/
    ├── AGENTS.md            # root discovery digest (translation layer)
    ├── ledger-README.md    # becomes .context_ledger/README.md
    ├── kickoff.md           # becomes .context_ledger/kickoff.md (filled at bootstrap)
    └── memory/              # the memory/ stub tree copied at bootstrap
```

Integrity: `sh .context_ledger/core/bin/ledger-sync verify` checks every core
file against `MANIFEST.sha256` (on Windows:
`.context_ledger/core/bin/ledger-sync.cmd verify` — the launcher shares
the same manifest). A failed verify means core was
hand-edited or corrupted — restore it (`ledger-sync rollback` or
`git checkout` of the last good commit) and log a flaw. Never "fix"
core in place inside a project.

---

## Zone 2 — `memory/` (the project's living memory)

Memory has two layers. The **live office** — `memory/office/` — holds
everything session-produced: the team roster, the session registry, session
notes and summaries, tasks, plans, flaw and inefficiency logs, reviews.
Only one office is ever live, so its paths are stable; when it fills up it
is frozen **verbatim** into `history/` and the next office opens from empty
skeletons (see **Office lifecycle** below). The **durable files** at the
memory root — `workflows/`, `collaboration/`, `system/`, `user/`,
`overrides/`, `core.lock`, `secrets/` — orient a session (standing rules,
tool config, machine/model registries, the human's facts, the coordination
trail) and never rotate.

File inventory, write modes, and scopes. **Write modes:**

- **append-only** — entries are only added at the bottom; corrections
  are appended, never edited in. Sole exception: byte-identical
  duplicate entries may be removed, leaving a one-line note in place.
- **live queue** — open work only. New items are added as rows in their
  priority table (High/Medium/Low — see "The backlog" below); a row is
  deleted when its item is finished or no longer relevant. Never delete
  a row whose item is still open (git history keeps every removed row,
  so nothing is lost). The only live-queue file is
  `office/tasks/backlog.md`; completion records live in
  `office/agents/sessions.md` and the commits, not in the backlog.
  `ledger-mem closeout` still sweeps checked-off `- [x]` tombstones
  from legacy checkbox-format backlogs.
- **overwrite** — current-state only; replace the content, history
  lives in the append-only logs.
- **update-in-place** — structured records with one entry per key,
  updated where they stand (a row, a block, a bullet); never wholesale
  replaced. **This is the opposite of append-only: you correct an entry by
  editing it, not by appending a second one.** The prior value survives in
  git history, so editing loses nothing. Appending a duplicate for a key
  that already exists is the failure mode (two rows, conflicting counts);
  `ledger-mem check` flags it. Keys: `ai-models.md` = (Agent, Model),
  `environments.md` = the "Identify by:" line.
- **generated** — created from a `core/templates/` file at bootstrap,
  then maintained as data (facts updated in place; regenerated only
  when the template materially changes).
- **local-only** — never tracked by git, never travels.

**The live office** (`memory/office/…`) — everything session-produced, frozen verbatim at close:

| Path (under `.context_ledger/memory/office/`) | Mode | Scope | Holds |
|---|---|---|---|
| `agents/sessions.md` | append-only (current office) | project | One entry per session: agent, model, platform, task, commits, outcome |
| `agents/roster.md` | update-in-place (current office) | project | Team roster — the "who's in the office *now*" board. Every session (solo included) adds its row at check-in and pushes it before product work; removes the row (clocks out) at session end. Who was on duty *when* lives in `agents/sessions.md` + this file's git history. Name and codename each unique in the office; `ledger-mem check` enforces it. Identity is *claimed* at check-in (fresh name + codename you pick), never *inferred* from a model/harness-string match — model strings are shared across sessions, so duplicate model values are normal. Never reset or trimmed: the whole office is frozen verbatim at close |
| `tasks/current.md` | overwrite | project | The one task in progress — a lock only in single-agent mode |
| `tasks/backlog.md` | live queue (priority-grouped tables; add/delete rows) | project | Open items for future sessions only — one row per item in its priority table (High/Medium/Low, ID + Summary); a finished item's row is deleted, its completion record is the session entry + commit. Office-scoped: still-open items are re-seeded into the next office at close |
| `plans/decisions.md` | append-only | project | ADR-style decisions — respected, not relitigated. Decisions still in force are re-seeded into the next office and recorded in the office's permanent record |
| `flaws/log.md` | append-only | project→package | Friction with the protocol/`.context_ledger/` system itself; flows upstream |
| `flaws/README.md` | generated | project | The flaws-vs-inefficiencies split rule (pointer to this schema) |
| `inefficiencies/log.md` | append-only | project | Friction with the project's code, env, deps |
| `reviews/YYYY-MM-DD-*.md` | new file per session | project | Session reports (deliverables — commit as `docs(review):`) |
| `reviews/README.md` | generated | project | Naming + report structure (pointer to this schema) |
| `sessions/README.md` | generated | project | Session-scoped memory rules, disposable principle, promotion rule |
| `sessions/SUMMARY.md` | update-in-place (entries are removable) | project | Compressed session history — one line per session, prunable. The permanent record is `agents/sessions.md` |
| `sessions/YYYY-MM-DD-N/notes.md` | append-only while active; deletable after promotion | project | Per-session detailed notes — research, exploration, dead ends. Disposable; durable facts must be promoted first |

**Durable files** (at the `memory/` root) — orient a session, never rotate:

| Path (under `.context_ledger/memory/`) | Mode | Scope | Holds |
|---|---|---|---|
| `collaboration/README.md` | generated | project | Peer collaboration rules and event contract |
| `collaboration/events/<event-id>.json` | immutable new file | project | Coordination events — notes (informal), claims, proposals, assessments, agreements, corrections, handoffs, releases. JSON documents validated by `core/schemas/collab-event.schema.json`. Every session writes the light path (claim → release), solo included; solo `session` is the roster codename, `issue` a task slug. Legacy `<event-id>.md` frontmatter files (pre-0.22.0) stay readable, never rewritten |
| `workflows/active.md` | overwrite | project (see scoping!) | Standing session parameters + core version in force |
| `workflows/gates.conf` | update-in-place | project | Explicit lifecycle commands and hybrid discovery mode |
| `workflows/history.conf` | update-in-place | project | Office rotation knobs: `office_size`, `history_keep`, `archive_keep` |
| `system/environments.md` | update-in-place | **machine** | One block per machine/sandbox, keyed by an "Identify by" line |
| `system/ai-models.md` | update-in-place | **agent** | Registry + evidence-based observations per agent/model |
| `user/identity.md` | update-in-place | user | Who the user is |
| `user/preferences.md` | update-in-place | user | Standing preferences, each bullet with provenance |
| `overrides/rules.md` | update-in-place | project | Project-local protocol adjustments (see Overrides) |
| `core.lock` | overwrite (by `ledger-sync`) | project | Last-known-good core version + when it was verified |
| `secrets/<slug>` | local-only | machine | One secret per file; line 1 = value. Self-gitignored |
| `secrets/README.md`, `secrets/.gitignore` | generated | project | The secrets hard rules; the self-ignore |

Entry formats: every writable file carries its entry template in an HTML
comment at the top (seeded from `core/templates/memory/`). **Read the
template before writing; never invent formats.** If a file's in-repo
template comment and this schema's mode column disagree, this schema
wins.

### The backlog: arrangement + workstream view

`office/tasks/backlog.md` is **arranged, not a checkbox list**: open
items live as rows in priority-grouped tables, so the shape of the work
is visible the moment the file opens. The file is arranged exactly like
this:

    ## Open Items

    ### High Priority

    | ID | Summary |
    |----|---------|
    | B-2026-08-15-12 | Three-tier classification: tier decides whether the feature boots |

    ### Medium Priority

    | ID | Summary |
    |----|---------|
    | B-2026-08-17-9 | OUTPUT tokens: cap file_read injection + uniform choke-point cap |

    ### Low Priority

    | ID | Summary |
    |----|---------|
    | B-2026-07-31-10 | Non-coding capability roadmap |

- **One row per open item, in its priority table.** Priority is the
  table an item sits in (High / Medium / Low); when unsure, Medium.
- **ID every row:** `B-<added YYYY-MM-DD>-<n>`, n = that date's next
  sequence in the file. Stable IDs are what make cross-references and
  workstream clustering possible. Legacy checkbox-format items keep
  their line until next touched; re-row them with an ID then.
- **The Summary cell carries the context** — enough for a fresh agent
  to act without chat history — with status qualifiers in the text
  ("partial — features present, lib not replaced", "done, pending
  sign-off", "deferred by owner", "advisory").
- **Finished = delete the row.** The backlog holds open work only; the
  completion record is the session entry + commit. There are no
  checkboxes in the file, so there is nothing to "check off" — a row
  that remains is open work. (`ledger-mem closeout` still sweeps
  checked-off `- [x]` tombstones from pre-1.0.5 checkbox-format
  backlogs.)
- **Workstream view — derived, never stored.** When the backlog is
  large (roughly 20+ rows) or the user asks for a planning pass, render
  the workstreams: numbered clusters of items attacking the same
  problem ("Code Block / Code Display (3 items → 1 effort)"), each
  listing its item IDs, a one-line rationale, dedupe/partial notes
  ("treat as the same effort; dedupe when picked up"), and an ordering
  suggestion when one exists ("ship measurement first — you can't
  optimize what you can't measure"). Close with a summary table:

  | Workstream | Items | Estimated Effort |
  |------------|-------|------------------|
  | Token efficiency | 6 | Large |

  …plus a leverage note: which workstreams touch the most surface
  (e.g., "affects every agent turn") and what is currently blocking
  (e.g., the one item blocking the exit gate). Count the mapping
  ("70 items → ~12 workstreams"). Workstreams are an analysis of the
  rows, never a second copy of them — an item has one home (its
  priority-table row), so finishing it stays a single delete.

### Reading order (session start)

`.context_ledger/README.md` → `kickoff.md` → `memory/workflows/active.md` →
`memory/office/agents/sessions.md` (last 3–5) → `memory/office/agents/roster.md`
(the "who's in the office now" board — a live row you didn't write means a
peer is here) → `memory/office/sessions/SUMMARY.md`
(skim last 10 entries for compressed continuity) → `memory/collaboration/README.md`
(and active event files when collaboration is enabled) →
`memory/office/tasks/current.md` → `memory/office/tasks/backlog.md` →
`memory/office/inefficiencies/log.md` →
`memory/office/flaws/log.md` → `memory/office/plans/decisions.md` →
`memory/overrides/rules.md` → `memory/workflows/gates.conf` →
`memory/system/` → `memory/user/` → note what's in `memory/secrets/`
(never print values). The `history/` and `archive/` zones are never in
this order — deliberate lookback only.


---

## Office lifecycle

Session history lives in discrete **offices** so it never grows unbounded
and a new office is never misdirected by a previous one's leftovers. The
live office is the unnumbered directory `memory/office/` — the team roster
(`agents/roster.md`), the session registry (`agents/sessions.md`), the
session notes and summaries (`sessions/`), tasks (`tasks/`), plans
(`plans/`), the flaw and inefficiency logs (`flaws/`, `inefficiencies/`),
and reviews (`reviews/`). Only one office is ever live, so its paths are
stable. **Durable files never rotate:** `user/`, `system/`,
`workflows/`, `overrides/`, `collaboration/` (including the event trail),
`core.lock`, and `secrets/` stay at the memory root across offices.

The **roster** is the team board for the current office: **every session
(solo included) checks in** — picks a human name, adds a row (Name,
codename `S<NNN>`, model, what they're doing), and pushes it before
product work — and **clocks out** by removing the row in the closing
memory commit, so the board shows who is in the office *now*. Who was on
duty *when* is the duty log's job: append-only `agents/sessions.md`
entries plus the roster file's own git history (check-in commit opens a
shift, clock-out closes it). Each agent presents itself by that name in
events and to the supervisor, and
name + codename are each unique in the office. `ledger-mem check` flags a
duplicate and warns when a session entry was logged while a row still
claimed the office (a forgotten clock-out). The roster is never reset or
trimmed — the whole office is frozen with it intact at close.

An office moves through three zones, and only the live one is read at session
start:

| Zone | Holds | Read at start? | Format |
|---|---|---|---|
| `memory/office/` | the current live office | yes | working files |
| `history/` | permanent records (all offices) + recently closed offices | no | `office-<NNN>.md` (permanent) + `office-<NNN>/` (frozen, verbatim) |
| `archive/` | older closed offices | no | `office-<NNN>.tar.gz` (cold) |

`ledger-history` rotates them: `close` freezes the live office directory
**verbatim** — no condensing, no resetting, the roster keeps every shift —
into `history/office-<NNN>/`, numbering it **at that moment** (the next
number is derived from the records; there is no state file), writes the
**permanent accomplishments record** `history/office-<NNN>.md` (what the
office achieved, decisions still in force, open threads re-seeded), and
opens a fresh empty office from templates (default `office_size` = 20
sessions, or a milestone). When `history/` holds more than `history_keep`
(default 3) frozen directories, the oldest is zipped into `archive/` and
removed — its record stays in `history/` forever. `gc` deletes `archive/`
tarballs over `archive_keep` (default 12), oldest-first, git-recoverable.
Config lives in `memory/workflows/history.conf`.

**No implicit carryover:** a new office starts from empty skeletons.
Anything from a closing office that still matters is re-seeded into the
new office's files explicitly by the closing session, and recorded in the
permanent record — the same promotion rule as session notes, applied at
the office boundary. This is what lets a closed office be archived and
eventually deleted without losing institutional knowledge: the permanent
record plus the durable files remember what matters.

---

## Peer collaboration

Collaboration is opt-in for a shared `session` + `issue` identity. Peers
are one team with one goal, not rivals. Each agent uses an isolated product
git worktree/branch; product edits never happen in the same checkout. Live
coordination is published on the shared `collab/<session-id>/coordination`
ref as immutable, one-file-per-event records under
`memory/collaboration/events/`, not in a shared append-only file. This
makes simultaneous notes, claims, proposals, assessments, agreements,
corrections, handoffs, and releases mergeable.

The everyday event is a **note** — the informal office channel (a heads-up,
a hand-off in plain words, a peer review). A note needs only a body, never
gates the integration check, and never has to be "resolved"; optional
`--to` addresses a peer and `--re` points at an event, path, or commit. The
common lifecycle is a note plus `claim → release`. The formal
`proposal → assessment → agreement` ceremony is the escalation for a
genuine conflict (same paths, incompatible changes) only.

A claim makes scope visible but is not a lock. A `release`/`handoff` closes
a claim when it cites the claim's event ID **or** shares its session+issue
and overlaps its paths — so a release citing only its commit SHA still
closes the claim. Overlapping *active* claims require peers to compare the
two changes and agree who takes it, via an explicit agreement selecting the
best-supported option and one implementation owner. A correction names the
evidence, likely cause, candidate repairs, and suggested owner; peers agree
on the repair and owner before it is applied. There is no timestamp or
agent-ID tie-breaker. If evidence remains tied, pause the conflicting work
and ask the user. Use `.context_ledger/core/bin/ledger-collab` (or the `.ps1` port
on Windows) to emit events and inspect status; run `ledger-collab check`
before integration. Event commits remain separate from product commits.

`office/tasks/current.md` remains the single-agent lock when collaboration is not
enabled — but "no collaboration declared" no longer means "alone": the
roster's live rows are the occupancy evidence. A live row you didn't
write means a peer is in the office — declare or join a shared
session/issue and coordinate before editing. In collaboration mode
`tasks/current.md` is not a lock and must not be used to
block a peer; use the collaboration event trail instead.

---

## Fact scoping — the contamination rules

`.context_ledger/` memory serves **every** agent that will ever work on the
project: local and cloud, strong and weak, on any machine. The single
biggest failure mode observed in the field is *scope contamination*:
one agent records a fact that is true only for its own type, machine,
or model — and the next agent of a different kind reads it as binding.
(A local agent on a cloud-bootstrapped repo starts doing PAT dances and
re-cloning; a cloud agent trusts a macOS-only command.)

Every fact you write into memory belongs to exactly one scope. Record
it so the scope is explicit:

| Scope | Definition | Where it lives | How it's keyed |
|---|---|---|---|
| **project** | True for this repo regardless of who works on it (repo URL, default branch, decisions, backlog) | most of `memory/` | nothing — unqualified facts are project facts |
| **agent-type** | True only for local OR only for cloud/sandbox agents (edition, credential flow, clone steps) | **never as a single value** — always recorded keyed "by agent type", naming both branches | explicit `local: … / cloud: …` |
| **machine** | True only on one machine/sandbox (paths, installed tools, verified commands) | `memory/system/environments.md` blocks | the block's "Identify by" line — apply a block only if it matches where you are |
| **agent/model** | True only for one agent or model (capabilities, blind spots) | `memory/system/ai-models.md` | the registry row |
| **user** | About the person (identity, preferences) | `memory/user/` | provenance markers |

Binding consequences:

1. **Edition choice is a function of your agent type at session start —
   never of memory.** `workflows/active.md` records the protocol "by
   agent type", naming BOTH editions. If you ever find a single edition
   recorded there, that's the *previous* agent's type leaking; follow
   your own type and fix the record.
2. **A machine-scoped block applies only where its "Identify by"
   matches.** Never run another environment's verified commands as if
   they were yours; add or update your own block.
3. **Credential flows are agent-type facts.** PAT steps exist only in
   the cloud edition; a local agent that finds PAT instructions in
   memory ignores them and logs a flaw.
4. **When writing, ask: "would this sentence be wrong for an agent of
   the other type, on another machine?"** If yes, key it to its scope
   or don't write it.

---

## Overrides — project-local protocol adjustments

`memory/overrides/rules.md` is the one sanctioned place a project bends
the protocol without forking core. Sessions read it right after loading
their edition; where an override and the edition conflict, **the
override wins** — with two exceptions that nothing can override:
secret-handling rules and the append-only guarantee.

Overrides are for standing, project-shaped deltas ("this repo squashes
to a release branch, not main", "reports go in docs/reports/ for
legacy reasons"). They are *not* a scratchpad for session instructions
(those die with the session) or user preferences (those go in
`user/preferences.md`). Each override carries provenance and a date,
like a preference. Core updates never touch this file — that's the
point: customizations survive every core version bump.

---

## Translation layer — how weaker agents consume this system

Not every agent reads a 900-line edition reliably. The system degrades
gracefully through three tiers, all generated from core — never
hand-maintained per project:

1. **`AGENTS.md` at the project root** (from `core/templates/AGENTS.md`,
   generated at bootstrap; optionally copied as `CLAUDE.md` and
   `.github/copilot-instructions.md` for tools that auto-load those
   paths). ~60 lines: the zones, the read-only rule for core, the entry
   point (`.context_ledger/kickoff.md`), and the condensed binding rules. This
   is the floor — an agent that reads nothing else still learns where
   memory lives, what it must never write to, and where to start.
2. **`.context_ledger/kickoff.md`** — the front door: typed entry steps that
   route by agent type and point into core.
3. **The full edition in `core/rules/`** — the complete instruction set
   for agents that can hold it.

Each tier links down to the next; no tier contradicts another because
all three are rendered from the same core version. A weak agent
following only tier 1 does less, but nothing *wrong* — it cannot
clobber core (rule stated in tier 1), cannot miss the entry point, and
cannot pick the wrong edition (the kickoff routes by type).

---

## Sync, change detection, and fallback

- **Startup check:** the kickoff's entry steps run
  `sh .context_ledger/core/bin/ledger-sync status` — compares the vendored
  core's `VERSION` against the best reachable source (an explicit path,
  a sibling package clone, or the package remote). Unreachable source =
  skip and note; **never fail a session over sync.**
- **Safe auto-update:** same-MAJOR updates (`1.0.x → 1.0.y`, minor
  bumps included) may be applied without asking; a MAJOR bump requires
  the user (there may be migration steps in `CHANGELOG.md`). Updating
  core never rewrites durable memory — the one deliberate exception is
  the office-layout migration (a legacy flat layout is grouped into
  `memory/office/`), which runs once and only moves files.
- **core.lock:** after any successful `verify`, `ledger-sync` records
  the version + date in `memory/core.lock`. That is the
  **last-known-good** marker.
- **Fallback:** if a session cannot parse or trust the current core
  (failed verify, half-applied update), roll back to the locked
  version — `ledger-sync rollback` restores `core/` from the project's
  own git history — then log the incident in `memory/flaws/log.md` and
  continue on the restored version. The session proceeds; the flaw
  flows upstream.
