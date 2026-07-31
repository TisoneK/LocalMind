# Session-Scoped Memory

Session history lives here: self-contained, disposable, and separable
from durable project knowledge. The three layers:

| Layer | Location | Lifetime | Purpose |
|---|---|---|---|
| **Session detail** | `<date>-N/notes.md` | Disposable | Research, dead ends, exploration, reasoning |
| **Session summary** | `SUMMARY.md` | Prunable | Compressed historical continuity (~1 line per session) |
| **Permanent record** | `../agents/sessions.md` | Append-only, forever | Formal registry — one entry proves the session happened |

## Core Principle: Session Data Is Disposable

> **Permanent context must never depend exclusively on an individual
> session.** If Session 47 discovers an architectural decision worth
> keeping, that decision gets promoted into its durable domain
> (`plans/decisions.md`, `tasks/backlog.md`, `inefficiencies/log.md`,
> `user/preferences.md`, `flaws/log.md`). Deleting Session 47 afterwards
> cannot damage the project's institutional knowledge — the durable
> facts were promoted first.

This gives a clean lifecycle:

```
New information
      ↓
Session notes
      ↓
Session summary (SUMMARY.md)
      ↓
Is it durable?
   ↙       ↘
 YES       NO
  ↓         ↓
Promote    Session
to domain  only
  ↓
Survives session deletion
```

## Directory layout

```text
sessions/
├── README.md                      # this file
├── SUMMARY.md                     # compressed history — entries are removable
└── YYYY-MM-DD-N/                  # one directory per session with detail (optional)
    └── notes.md                   # append-only while active; deletable after promotion
```

Sessions directories are **optional** — a trivial session (typo fix,
one-line config change) that produces nothing worth keeping beyond its
summary line creates no directory here. `SUMMARY.md` always gets an
entry for every session, even trivial ones.

## Promotion Rule

At session end, before closing:

> **Does anything in these notes need to survive beyond this session?**

- **NO** — the notes stay here. A future agent can retrieve them
  selectively if the detail is needed.
- **YES** — distill the durable facts and promote them to their proper
  domain (an architectural insight → `plans/decisions.md`, a discovered
  constraint → `inefficiencies/log.md`, a new backlog item →
  `tasks/backlog.md`, a user preference → `user/preferences.md`,
  a protocol friction → `flaws/log.md`). After promotion, the directory
  may be deleted if its raw history is no longer useful.

**The litmus test:** *"Would this fact still matter after the session
closes, to an agent that never reads these notes?"* If yes, it does not
belong only here — promote it.

## Cleanup & Garbage Collection

- **Session directories** can be deleted when no longer useful. The
  permanent record in `agents/sessions.md` proves the session happened;
  promoted facts live in their durable domains.
- **SUMMARY.md entries** can be removed for older sessions — compress
  the key facts into the durable logs first. Never let `SUMMARY.md`
  become another giant history file. A removed summary line MUST have a
  corresponding permanent entry in `agents/sessions.md`.
- **Keep all recent entries** (~last 10 sessions) in `SUMMARY.md` for
  continuity; prune selectively beyond that.
- **Never delete** the permanent `agents/sessions.md` entry or promoted
  durable knowledge.

<!-- The templates for SUMMARY.md and notes.md live in this directory.
In a running project, copy the template comments from
.context/core/templates/memory/sessions/. -->
