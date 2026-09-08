# history/ — closed session groups (readable)

This zone holds one file per **recently closed** session group,
`group-<NNN>.md`, produced by `context-history close`. Each file is a
condensed record of that group: its session registry entries and summary
lines, plus the date range and session count.

**Not read at session start.** Agents read the live group in
`.context/memory/`. This zone is for audit and lookback only — a human or an
agent asking "what happened back in group 004?" comes here deliberately.

A group's lifecycle:

```
memory/ (live)  ->  history/ (closed, readable)  ->  archive/ (cold, zipped)  ->  gc
```

`context-history` keeps the most recent `history_keep` groups here (default
3); when the next group closes, the oldest is zipped into `../archive/`.
Nothing durable lives only here — open threads were promoted into the live
`memory/` domain files before the group closed.
