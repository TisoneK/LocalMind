# The `.context/` Schema — Single Source of Truth

This file defines every file in a project's `.context/` directory: where
it lives, who owns it, how it may be written, and which *scope* its facts
belong to. When any other document (a README, an edition, a template
comment) disagrees with this schema, **this schema wins** — and the
disagreement is a flaw to log.

A machine-readable mirror lives beside this file as
`context.schema.json`. The markdown is authoritative; the JSON is
generated from it by hand and must be updated in the same commit as any
schema change.

---

## The two zones

```text
{project}/
├── AGENTS.md              # generated digest for agent discovery (see Translation layer)
├── CLAUDE.md              # pointer so Claude Code (auto-loads CLAUDE.md) reaches the protocol
└── .context/
    ├── README.md          # zone map — copied from core/templates at bootstrap/update
    ├── kickoff.md         # front door — generated at bootstrap, project-owned
    ├── .gitattributes     # LF policy for core + memory (Windows CRLF guard)
    ├── core/              # ZONE 1 — package-owned, READ-ONLY, version-stamped
    ├── memory/            # ZONE 2 — project-owned, writable, never synced; holds the LIVE session group
    ├── history/           # closed session groups, readable — NOT read at session start
    └── archive/           # cold storage of old groups (zipped) — NOT read at session start
```

`history/` and `archive/` hold closed session groups produced by
`context-history` (see **Session grouping** below). They are never in the
session-start reading order — only the live group in `memory/` is.

| Zone | Owner | Agents may write? | How it changes |
|---|---|---|---|
| `core/` | The protocol package | **Never.** Not one byte. | Only via `context-sync update` (whole-tree, version-stamped) |
| `memory/` | The project | Yes — per each file's write mode below | Normal session work, committed with the project |

The zone rule is the entire sync model: **core is replaced as a unit,
memory is never touched by sync.** There is no per-file structural/data
classification anymore (the old `SYNC.md` basename rule is retired). If
you are editing a path that starts with `.context/core/`, stop — you are
either syncing (use `context-sync`) or making a protocol change, which
belongs in the package repo, not in a project.

Two root files sit outside both zones:

- **`.context/README.md`** — the zone map. Package-owned *content*
  (refreshed from `core/templates/context-README.md` on core updates)
  but deliberately kept at the root so a fresh agent's first `ls` +
  `cat` explains the layout.
- **`.context/kickoff.md`** — the front door. Project-owned **data**:
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
│   ├── context-sync     # POSIX-sh: status / verify / update / rollback / bootstrap
│   ├── context-sync.ps1   # PowerShell port (Windows): status / verify / update / rollback / lock
│   ├── context-collab       # POSIX-sh: atomic collaboration events + status + check
│   ├── context-collab.ps1   # PowerShell port (Windows): emit + status + check
│   ├── context-collab-check # POSIX integration-readiness validator
│   ├── context-collab-check.ps1 # PowerShell integration-readiness validator
│   ├── context-gates        # POSIX lifecycle gates + checkpoint
│   ├── context-gates.ps1    # PowerShell lifecycle gates + checkpoint
│   ├── context-mem          # POSIX: check (registry dup keys) + lint (.context leak) + prune (log-archive advisory)
│   ├── context-mem.ps1      # PowerShell port: same hygiene checks
│   ├── context-history      # POSIX: group session history, rotate memory→history→archive→gc
│   ├── context-history.ps1  # PowerShell port: session-group rotation
│   └── context-*.cmd        # cmd.exe launchers, one per .ps1 port: each
│                            #   runs it with -ExecutionPolicy Bypass -- no
│                            #   Windows Set-ExecutionPolicy setup needed
├── rules/
│   ├── ai-engineering-protocol-local.md   # LOCAL agents' edition
│   └── ai-engineering-protocol.md         # CLOUD/SANDBOX agents' edition
├── roles/               # mission overlays: reviewer, security-auditor, docs-agent, feature-engineer
├── schemas/
│   ├── context-schema.md    # this file
│   └── context.schema.json  # machine-readable mirror
└── templates/
    ├── AGENTS.md            # root discovery digest (translation layer)
    ├── context-README.md    # becomes .context/README.md
    ├── kickoff.md           # becomes .context/kickoff.md (filled at bootstrap)
    └── memory/              # the memory/ stub tree copied at bootstrap
```

Integrity: `sh .context/core/bin/context-sync verify` checks every core
file against `MANIFEST.sha256` (on Windows:
`.context/core/bin/context-sync.cmd verify` — the launcher shares
the same manifest). A failed verify means core was
hand-edited or corrupted — restore it (`context-sync rollback` or
`git checkout` of the last good commit) and log a flaw. Never "fix"
core in place inside a project.

---

## Zone 2 — `memory/` (the project's living memory)

File inventory, write modes, and scopes. **Write modes:**

- **append-only** — entries are only added at the bottom; corrections
  are appended, never edited in. Sole exception: byte-identical
  duplicate entries may be removed, leaving a one-line note in place.
- **overwrite** — current-state only; replace the content, history
  lives in the append-only logs.
- **update-in-place** — structured records with one entry per key,
  updated where they stand (a row, a block, a bullet); never wholesale
  replaced. **This is the opposite of append-only: you correct an entry by
  editing it, not by appending a second one.** The prior value survives in
  git history, so editing loses nothing. Appending a duplicate for a key
  that already exists is the failure mode (two rows, conflicting counts);
  `context-mem check` flags it. Keys: `ai-models.md` = (Agent, Model),
  `environments.md` = the "Identify by:" line.
- **generated** — created from a `core/templates/` file at bootstrap,
  then maintained as data (facts updated in place; regenerated only
  when the template materially changes).
- **local-only** — never tracked by git, never travels.

| Path (under `.context/memory/`) | Mode | Scope | Holds |
|---|---|---|---|
| `agents/sessions.md` | append-only | project | One entry per session: agent, model, platform, task, commits, outcome |
| `tasks/current.md` | overwrite | project | The one task in progress — a lock only in single-agent mode |
| `tasks/backlog.md` | append-only | project | Open items for future sessions |
| `collaboration/README.md` | generated | project | Peer collaboration rules and event contract |
| `collaboration/events/<event-id>.md` | immutable new file | project | Notes (informal), claims, proposals, assessments, agreements, corrections, handoffs, releases |
| `plans/decisions.md` | append-only | project | ADR-style decisions — respected, not relitigated |
| `flaws/log.md` | append-only | project→package | Friction with the protocol/`.context/` system itself; flows upstream |
| `flaws/README.md` | generated | project | The flaws-vs-inefficiencies split rule (pointer to this schema) |
| `inefficiencies/log.md` | append-only | project | Friction with the project's code, env, deps |
| `reviews/YYYY-MM-DD-*.md` | new file per session | project | Session reports (deliverables — commit as `docs(review):`) |
| `reviews/README.md` | generated | project | Naming + report structure (pointer to this schema) |
| `sessions/README.md` | generated | project | Session-scoped memory rules, disposable principle, promotion rule |
| `sessions/SUMMARY.md` | update-in-place (entries are removable) | project | Compressed session history — one line per session, prunable. The permanent record is `agents/sessions.md` |
| `sessions/YYYY-MM-DD-N/notes.md` | append-only while active; deletable after promotion | project | Per-session detailed notes — research, exploration, dead ends. Disposable; durable facts must be promoted first |
| `workflows/active.md` | overwrite | project (see scoping!) | Standing session parameters + core version in force |
| `workflows/gates.conf` | update-in-place | project | Explicit lifecycle commands and hybrid discovery mode |
| `system/environments.md` | update-in-place | **machine** | One block per machine/sandbox, keyed by an "Identify by" line |
| `system/ai-models.md` | update-in-place | **agent** | Registry + evidence-based observations per agent/model |
| `user/identity.md` | update-in-place | user | Who the user is |
| `user/preferences.md` | update-in-place | user | Standing preferences, each bullet with provenance |
| `overrides/rules.md` | update-in-place | project | Project-local protocol adjustments (see Overrides) |
| `core.lock` | overwrite (by `context-sync`) | project | Last-known-good core version + when it was verified |
| `secrets/<slug>` | local-only | machine | One secret per file; line 1 = value. Self-gitignored |
| `secrets/README.md`, `secrets/.gitignore` | generated | project | The secrets hard rules; the self-ignore |

Entry formats: every writable file carries its entry template in an HTML
comment at the top (seeded from `core/templates/memory/`). **Read the
template before writing; never invent formats.** If a file's in-repo
template comment and this schema's mode column disagree, this schema
wins.

### Reading order (session start)

`.context/README.md` → `kickoff.md` → `memory/workflows/active.md` →
`memory/agents/sessions.md` (last 3–5) → `memory/sessions/SUMMARY.md`
(skim last 10 entries for compressed continuity) → `memory/collaboration/README.md`
(and active event files when collaboration is enabled) →
`memory/tasks/current.md` → `memory/tasks/backlog.md` →
`memory/inefficiencies/log.md` →
`memory/flaws/log.md` → `memory/plans/decisions.md` →
`memory/overrides/rules.md` → `memory/workflows/gates.conf` →
`memory/system/` → `memory/user/` → note what's in `memory/secrets/`
(never print values).


---

## Session grouping

Session history is collected into discrete **groups** so it never grows
unbounded. A group is the session-history subtree only — `agents/sessions.md`
entries, `sessions/SUMMARY.md` lines, `sessions/<date-N>/` notes. Durable
facts (`user/`, `system/`, `plans/decisions.md`, `tasks/backlog.md`,
`flaws/`, `inefficiencies/`) and collaboration events are **not** part of a
group and never rotate.

A group moves through three zones, and only the live one is read at session
start:

| Zone | Holds | Read at start? | Format |
|---|---|---|---|
| `memory/` | current live group | yes | working files |
| `history/` | recently closed groups | no | `group-<NNN>.md` (condensed) |
| `archive/` | older closed groups | no | `group-<NNN>.tar.gz` (cold) |

`context-history` rotates them: `close` consolidates the live group into
`history/` and starts a fresh one (default `group_size` = 20 sessions, or a
milestone); when `history/` exceeds `history_keep` (default 3) the oldest
group is zipped into `archive/`; `gc` deletes `archive/` tarballs over
`archive_keep` (default 12), oldest-first, git-recoverable. Config lives in
`memory/workflows/history.conf`; the current group number is in
`memory/agents/GROUP`.

**No implicit carryover:** a new group starts clean. Anything from a closing
group that still matters must be promoted into its durable domain file before
the close — the same promotion rule as session notes, applied at the group
boundary. This is what lets a closed group be archived and eventually deleted
without losing institutional knowledge.

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
and ask the user. Use `.context/core/bin/context-collab` (or the `.ps1` port
on Windows) to emit events and inspect status; run `context-collab check`
before integration. Event commits remain separate from product commits.

`tasks/current.md` remains the single-agent lock when collaboration is not
enabled. In collaboration mode it is not a lock and must not be used to
block a peer; use the collaboration event trail instead.

---

## Fact scoping — the contamination rules

`.context/` memory serves **every** agent that will ever work on the
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
   point (`.context/kickoff.md`), and the condensed binding rules. This
   is the floor — an agent that reads nothing else still learns where
   memory lives, what it must never write to, and where to start.
2. **`.context/kickoff.md`** — the front door: typed entry steps that
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
  `sh .context/core/bin/context-sync status` — compares the vendored
  core's `VERSION` against the best reachable source (an explicit path,
  a sibling package clone, or the package remote). Unreachable source =
  skip and note; **never fail a session over sync.**
- **Safe auto-update:** same-MAJOR updates (`0.2.x → 0.2.y`, minor
  bumps included) may be applied without asking; a MAJOR bump requires
  the user (there may be migration steps in `CHANGELOG.md`). Updating
  core never touches `memory/` — that is what makes auto-update safe.
- **core.lock:** after any successful `verify`, `context-sync` records
  the version + date in `memory/core.lock`. That is the
  **last-known-good** marker.
- **Fallback:** if a session cannot parse or trust the current core
  (failed verify, half-applied update), roll back to the locked
  version — `context-sync rollback` restores `core/` from the project's
  own git history — then log the incident in `memory/flaws/log.md` and
  continue on the restored version. The session proceeds; the flaw
  flows upstream.
