# Core Changelog

One entry per released core version, newest first. An agent syncing a
project's `.context/core/` from an older version reads every entry
between the two versions — migration notes live here.

Semver: breaking changes to the `.context/` spec or the memory layout
bump MAJOR; new features (roles, pitfalls, templates, schema fields)
bump MINOR; wording and fixes bump PATCH.

---

## 0.8.0 — 2026-08-17

**Explicit lifecycle command gates.** Agents now have mechanical,
project-owned gates instead of relying only on prose instructions.

- **`context-gates` + `context-gates.ps1`:** add `checkpoint`,
  `pre-commit`, `integration`, and `exit` gate commands with consistent
  exit behavior and observable command output.
- **Per-agent-turn checkpoint:** refreshes working-tree and collaboration
  state before the next action, reducing stale-context work.
- **Project command registry:** new `memory/workflows/gates.conf` supports
  explicit commands per lifecycle gate. `mode=hybrid` uses safe conventional
  package.json/Python discovery only when no explicit command is configured;
  `mode=explicit` fails when a required gate has no command.
- **Mandatory transitions:** protocol editions, kickoff, AGENTS digest,
  and schema now require gates before commits, branch integration, and
  session exit. Integration includes `context-collab check` when a
  collaboration session/issue is supplied.

**Migration from 0.7.x:** existing projects remain compatible. New
bootstraps receive `gates.conf`; existing projects can initialize it with
`sh .context/core/bin/context-gates init` or the PowerShell equivalent.

## 0.7.0 — 2026-08-17

**Collaboration integration-readiness checks.** The collaboration helper
now provides a mechanical gate before product branches are integrated.

- **`context-collab check`:** validates required event metadata, event ID
  uniqueness, resolvable same-session/same-issue references, complete agreements,
  selected options, peer participants, owners, active claim overlaps,
  unresolved proposals/assessments/corrections/handoffs, and product
  commit references on releases.
- **PowerShell parity:** `context-collab.ps1 check` delegates to the
  PowerShell validator with the same checks and exit-code contract.
- **Operational split:** `status` remains the live-work view; `check` is
  the integration-readiness gate and fails when the event trail is not
  complete.

**Migration from 0.6.x:** none. Existing event trails remain readable;
projects gain the check helpers on their next core update.

## 0.6.0 — 2026-08-17

**Peer collaboration for concurrent and shared-issue sessions.** The
single-agent workflow remains the default, while agents can now opt into a
shared session/issue and coordinate without a mutable global lock.

- **Isolated workspaces:** collaborating agents use separate clones or git
  worktrees and `collab/<session-id>/<agent-id>` product branches; product
  commits never happen in the same checkout or directly on the shared
  integration branch during collaboration. Events publish to the shared
  event-only `collab/<session-id>/coordination` ref.
- **Immutable event trail:** projects gain `memory/collaboration/`, where
  each claim, proposal, assessment, agreement, correction, handoff, and
  release is a separate event file. Independent files avoid concurrent EOF
  append conflicts and preserve the complete reasoning trail.
- **Evidence-based peer agreement:** overlapping scopes require assessments
  and an agreement selecting the best-supported option and exactly one
  implementation owner. There is no timestamp, priority, or agent-ID
  winner; genuinely tied evidence pauses for the user.
- **Corrections:** an agent can record the observed mistake, evidence, likely
  cause, candidate repairs, and suggested fixer; peers agree on the repair
  and owner before the correction is applied.
- **`core/bin/context-collab` + `context-collab.ps1`:** POSIX and
  PowerShell helpers for atomic event creation and overlap/status inspection.
- **Schema and protocol:** both editions, kickoff, AGENTS digest, README,
  and schema now distinguish single-agent `tasks/current.md` locking from
  collaboration event coordination.

**Migration from 0.5.x:** none required for existing single-agent
projects. New bootstraps receive `memory/collaboration/README.md`; an
existing project that opts in copies that template into
`.context/memory/collaboration/` during its first collaboration session.
Core updates never touch memory. Event files are created only when a
project opts into collaboration.

## 0.5.0 — 2026-07-31

**The session-scoped memory release.** Session history is now self-contained
and disposable — separate from durable project knowledge — preventing
`.context/` bloat while preserving continuity.

- **New `memory/sessions/` module:**
  - `memory/sessions/SUMMARY.md` — compressed session history (~1 line
    per session, prunable). Unlike `agents/sessions.md` (append-only
    forever), entries here may be removed when a session is no longer
    useful. Future agents skim the last ~10 entries at startup for
    compact continuity.
  - `memory/sessions/<date>-N/notes.md` — per-session detailed notes
    (append-only while active, deletable after promotion). Optional — a
    trivial session creates no directory. Holds research, exploration,
    dead ends, and implementation reasoning that would otherwise bloat the
    global logs or the compact summary.
- **Context Promotion (new in Step 17 of both editions):** at session end,
  the agent evaluates session notes and promotes durable facts to their
  persistent domain (`decisions.md`, `backlog.md`, `inefficiencies/log.md`,
  `preferences.md`, `flaws/log.md`). The promotion invariant: **permanent
  context must never depend exclusively on an individual session** — a
  fact that matters beyond the session lives in its domain file, so
  deleting the session directory cannot delete the knowledge.
- **"Session data is disposable" principle:** enshrined in both editions
  (rule 7 of the `.context/` Rules) and in `memory/sessions/README.md`.
  Session directories may be deleted; SUMMARY.md entries pruned; the
  formal registry (`agents/sessions.md`) is the permanent record.
- **Three-layer model:** session detail (disposable) → session summary
  (prunable) → permanent registry (append-only). Together with the
  durable domain files, this gives a clean lifecycle: new information →
  session notes → summary → evaluate durability → promote or discard.
- **Schema:** new `sessions/` entries in `context-schema.md` and
  `context.schema.json`; reading order now includes `SUMMARY.md`.
- **Templates:** `memory/sessions/README.md`, `SUMMARY.md`, and `notes.md`
  added under `core/templates/memory/sessions/`.
- **Migration from 0.4.x:** none required. The `sessions/` directory
  appears on first use; existing memory files are valid as-is. The new
  `Notes:` line in `agents/sessions.md` entries and the `SUMMARY.md`
  append are additive — sessions on 0.4.x cores continue to work,
  upgrading when their project pulls 0.5.0.

## 0.4.0 — 2026-07-30

**The Windows release.** The tool no longer assumes a POSIX shell. Windows
agents run PowerShell, not `sh`, so a `sh`-only `context-sync` failed at
session startup (`verify`/`status`) with no fallback. This adds a
PowerShell port of the session commands.

- **`core/bin/context-sync.ps1` (PowerShell port):** covers the project-mode
  commands an agent hits inside a session — `status`, `verify`, `update`,
  `rollback`, `lock`. Requires PowerShell 5.1+ (`pwsh` or Windows
  PowerShell). Invoke as
  `pwsh -File .context/core/bin/context-sync.ps1 <cmd>`; the `--major`
  update gate is the `-Major` switch. Byte-compatible with the `sh` tool's
  `MANIFEST.sha256` (identical SHA-256 hashes, forward-slash paths), so a
  core verified on one platform verifies on the other.
- **Package-mode commands stay `sh`-only:** `manifest`, `bootstrap`, and
  `harvest` are not ported — the maintainer runs them from a package clone
  on macOS/Linux. The `.ps1` prints a pointer to the `sh` script if asked
  for one of them.
- **Docs:** `sh …/context-sync <cmd>` invocations across the kickoff,
  QUICKSTART, and schema now show the PowerShell equivalent for Windows.
- **Migration from 0.3.x:** none. The port is additive; existing projects
  gain `context-sync.ps1` on their next `update`. macOS/Linux behavior is
  unchanged.

## 0.3.0 — 2026-07-21

**The harvest release.** Closes the upstream loop the `flaws/` directory
only ever promised: project memory now flows back to the package
mechanically instead of by hand.

- **`context-sync harvest` (package mode):** run from a package clone, it
  reads `fleet.md`, reaches every listed project read-only (a sibling
  clone matched by remote URL, else a shallow clone), and collects three
  signals into `inbox/harvest-<date>.md` for triage — open `flaws/`,
  `Upstream: candidate` inefficiencies, and `[core-defect]` overrides. A
  committed ledger (`inbox/.harvested`) hashes each entry so re-runs never
  re-file it. Never writes to the projects.
- **Fleet registry (`fleet.md`, package root):** `bootstrap` now appends
  each new project's `origin` URL, so the package knows its own
  downstream repos. Append-only; idempotent on the URL.
- **Schema fields for harvest opt-in:**
  - `inefficiencies/log.md` gains an optional `**Upstream:** candidate`
    line — marks protocol-level friction for collection; project-local
    friction stays unmarked and unharvested.
  - `overrides/rules.md` bullets are now tagged `[core-defect]` (a local
    patch to a core bug — harvested) or `[project-local]` (legitimate
    project difference — never harvested). Overrides survive core bumps,
    so an untagged core-defect workaround would otherwise stay stranded
    in one project forever.
- **Migration from 0.2.x:** none required. The two template fields are
  additive and opt-in; existing memory files are valid as-is. Maintainers
  gain `fleet.md` + `inbox/` at the package root (bootstrap creates
  `fleet.md` on first use; back-fill older projects by hand).

## 0.2.0 — 2026-07-14

**The vendored-core release.** The protocol no longer lives in a sibling
clone — it travels inside every project as `.context/core/`, beside the
project's own memory in `.context/memory/`.

- **Two-zone layout:** `.context/core/` (package-owned, read-only,
  version-stamped) + `.context/memory/` (project-owned, writable, never
  synced). Replaces the basename-based structural/data split; `SYNC.md`
  is retired.
- **Memory modules move under `memory/`:** `agents/`, `tasks/`, `plans/`,
  `flaws/`, `inefficiencies/`, `reviews/`, `system/`, `user/`,
  `workflows/`, `secrets/` keep their names and formats — only the path
  prefix changes. `kickoff.md` and `README.md` stay at the `.context/`
  root as the front door and zone map.
- **New memory modules:** `memory/overrides/rules.md` (project-local
  protocol adjustments, read after the edition) and `memory/core.lock`
  (last-known-good core version, written by `context-sync`).
- **Unified schema:** `core/schemas/context-schema.md` (+
  `context.schema.json`) is now the single authority on every memory
  file's format, write mode, ownership, and fact scope — including the
  per-agent-type vs per-project vs per-machine scoping rules that stop
  cross-agent-type contamination.
- **`core/bin/context-sync`:** POSIX-sh tool — `status`, `verify`,
  `update`, `rollback`, `bootstrap`. Startup change detection, checksum
  integrity via `core/MANIFEST.sha256`, git-based rollback to the
  locked version.
- **Weak-agent translation layer:** bootstrap generates a root
  `AGENTS.md` digest (from `core/templates/AGENTS.md`) so agents that
  never read a 900-line edition still learn the zones, the entry point,
  and the binding rules.
- **Cloud sessions need no package access after bootstrap** — the
  protocol is on disk inside the project. Package PATs are a
  bootstrap-only concern.
- **Migration from 0.1.x:** see `MIGRATION.md` in the package repo.
  Summary: create `memory/`, `git mv` the modules into it, vendor
  `core/`, regenerate `kickoff.md`, delete `SYNC.md`.

## 0.1.0 — 2026-07-13 (retroactive)

The sibling-clone era: two protocol editions at the package root,
`context-skeleton/` bootstrapped into projects as a flat `.context/`,
structural-vs-data sync per `SYNC.md`, package cloned beside every
project as `../context`. Never formally released; version assigned
retroactively as the baseline `MIGRATION.md` migrates from.
