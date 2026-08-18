# Peer Collaboration

This directory is the shared coordination surface for multiple agents
working on one issue or project session. It is **opt-in**: when no
collaboration session is declared, the normal single-agent workflow and
`tasks/current.md` lock still apply.

## Goals

- let agents work concurrently without sharing a mutable working tree;
- make overlapping claims and proposed changes visible to every peer;
- let peers compare evidence and agree on the best option before applying
  conflicting changes;
- let an agent report a mistake with its cause and proposed repair, while
  peers agree who should fix it;
- preserve a durable, reviewable trail after agents or sessions disappear.

## Required workspace topology

Each agent gets its own product worktree and branch. Never have two
agents edit the same checkout or push product commits directly to the
shared branch during collaboration.

Coordination events are published to one shared, event-only branch:
`collab/<session-id>/coordination`. This is a shared bulletin board, not a
coordinator: every event is a new file, and a non-fast-forward push is
resolved by rebasing while preserving every event file. Keep a separate
coordination worktree when possible.

```text
project/                              # integration checkout, normally idle
project-agent-a/                      # collab/<session>/<agent-a> (product)
project-agent-b/                      # collab/<session>/<agent-b> (product)
project-collab-session/               # collab/<session>/coordination (events only)
```

Start from a fresh, synchronized base. A typical local setup is:

```bash
git fetch origin
git worktree add ../<project>-<agent-id> \
  -b collab/<session-id>/<agent-id> origin/main
git worktree add ../<project>-collab-<session-id> \
  -b collab/<session-id>/coordination origin/main
```

The first agent publishes the coordination branch; later agents fetch it
and use the same coordination worktree or rebase their event-only branch
onto it. Cloud agents normally get product isolation from separate
clones; they must still publish/fetch the shared coordination ref.

## Event files are immutable

Every coordination event is a new file under `events/`:

```text
collaboration/
├── README.md
└── events/
    └── <event-id>.md
```

Never edit an event after publishing it. If it is wrong, emit a new
`correction` event that references it. One file per event is deliberate:
two agents can publish at the same time without appending to one shared
log and creating an EOF merge conflict. Commit and push event files
separately from product changes using `chore(context):`.

The optional helper creates valid event files atomically:

```bash
sh .context/core/bin/context-collab emit claim \
  --session <session-id> --agent <agent-id> --issue <issue-id> \
  --paths src/auth.py,tests/test_auth.py --body-file /path/to/claim.md
sh .context/core/bin/context-collab status --session <session-id> --issue <issue-id>
sh .context/core/bin/context-collab check --session <session-id> --issue <issue-id>
```

`status` is for live work. `check` is the integration-readiness gate and
fails if metadata or references are invalid, claims overlap, agreements are
incomplete, corrections or handoffs remain unresolved, or releases do not
cite a product commit.

On Windows, use the PowerShell port:

```powershell
pwsh -File .context/core/bin/context-collab.ps1 emit claim `
  --session <session-id> --agent <agent-id> --issue <issue-id> `
  --paths src/auth.py,tests/test_auth.py --body-file C:\path\claim.md
pwsh -File .context/core/bin/context-collab.ps1 status `
  --session <session-id> --issue <issue-id>
pwsh -File .context/core/bin/context-collab.ps1 check `
  --session <session-id> --issue <issue-id>
```

The helpers are conveniences; the event contract is authoritative.

## Event contract

Each event has immutable metadata followed by evidence and reasoning:

```markdown
---
id: <globally-unique-event-id>
type: claim | proposal | assessment | agreement | correction | handoff | release
session: <shared-collaboration-session-id>
agent: <stable-agent-id>
created: <UTC timestamp>
issue: <shared-issue-id>
paths: <comma-separated repo-relative paths, or none>
refs: <comma-separated event IDs or commit SHAs, or none>
option: <proposal option ID, or none>
selected: <selected option ID, or none>
owner: <agent-id responsible for implementation, or none>
participants: <comma-separated agents who agreed, or none>
---

<evidence, reasoning, trade-offs, and next action>
```

`id`, `type`, `session`, `agent`, `created`, and `issue` are required.
`paths` is required for a `claim`; `refs` is required for an
`assessment`, `agreement`, or `correction`. The other fields are required
when relevant to the event type.

### Event meanings and lifecycle

1. **claim** — state the issue, paths or logical scope, intended change,
   current hypothesis, and why the scope is safe to take. Claims are
   advisory, not locks. Re-read the latest events before editing.
2. **proposal** — present one concrete option, evidence, affected paths,
   trade-offs, risks, and how it will be verified. Competing proposals
   are expected.
3. **assessment** — compare the referenced proposals against the same
   criteria: correctness, regression risk, compatibility, simplicity,
   and verification evidence. Recommend one and explain why; include
   dissent if the evidence is inconclusive.
4. **agreement** — record the option peers accepted, the reasoning that
   makes it best, all participants who accepted it, and exactly one
   implementation owner. No agent applies a conflicting proposal before
   this event is visible.
5. **correction** — report a suspected mistake by referencing the claim,
   proposal, agreement, or commit; state the observed symptom, evidence,
   likely root cause, candidate repairs, and suggested owner. A correction
   does not unilaterally reassign work.
6. **handoff** — transfer an agreed scope to another agent, referencing
   the agreement and stating what is complete, pending, and verified.
7. **release** — declare a claim or handoff complete, referencing the
   relevant event and commit(s), with verification results.

### Peer agreement rule

There is no coordinator and no timestamp/priority winner. When options
conflict, each involved agent reads the alternatives, independently checks
the evidence, and records an assessment. Peers converge on the option
with the strongest total case, not the option proposed first. The
agreement event is the authority for implementation and must name the
owner. If evidence remains genuinely tied, record the disagreement in an
assessment, pause the conflicting edit, and ask the user to decide; never
silently choose based on agent ID or arrival time.

For a discovered mistake, the finder proposes the cause and repair in a
`correction`; the original author and/or affected peers assess it; an
`agreement` selects the best repair and owner. The owner then emits a
`release` after re-reading the corrected code and running the relevant
checks.

## Synchronization rules

- Fetch the shared coordination ref before reading collaboration state;
  publish claims and proposals before product edits, then fetch again
  before applying an agreement. If the coordination branch moved, rebase
  and preserve all event files before retrying the push.
- Product commits stay on the agent branch. Event commits stay separate on
  `collab/<session-id>/coordination` and can be merged without combining
  product and memory surfaces.
- A claim is not active after its scope is released or handed off. A peer
  who changes scope emits a new claim rather than editing the old one.
- Non-overlapping scopes may proceed concurrently. Overlapping paths,
  shared interfaces, migrations, lockfiles, and generated files are
  conflicts even when the files differ; negotiate them explicitly.
- At integration time, merge/rebase each product branch into the shared
  branch in dependency order. Never force-push over a peer's work.
- Normal durable files (`tasks/backlog.md`, `plans/decisions.md`, and
  session logs) are updated after the collaboration event trail is
  published. If two agents need the same durable file, one agent owns
  that update or peers merge it after rebasing; do not use those files as
  the live coordination channel.

## Session identity

All agents fixing the same issue at the same or different times reuse the
same `session` and `issue` values. A later agent starts by fetching the
existing events, emits a new claim or handoff, and continues the trail.
Different issues may share a session only when their scopes do not overlap.
Use a stable, non-secret ID; never put credentials or private tokens in an
event body.
