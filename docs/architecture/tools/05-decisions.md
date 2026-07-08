# 05 — Architectural Decision Records

Each ADR captures one decision: the context, the options considered,
the choice made, and the consequences. New decisions are appended — old
ADRs are never edited (superseded ones are marked as such).

---

## ADR-001 — Scratch-first write pattern

**Status:** Accepted  
**Date:** 2026-05-04

### Context
LocalMind needs to write processed files back to user-specified destinations.
The naive approach — write directly to the destination — risks overwriting
the user's original file if something goes wrong mid-write, and gives no
opportunity for version history.

### Decision
All writes go to `~/LocalMind/` (scratch) first. Copy-back to the user's
destination happens after. The scratch copy persists until the cache age
policy removes it.

### Consequences
- Original files at the destination are never overwritten mid-write
- Scratch acts as a short-term version cache
- Copy-back requires an extra I/O step (acceptable — files are typically small)
- `~/LocalMind/` must be treated as a working directory, not a permanent store

---

## ADR-002 — Timestamp rename for document formats

**Status:** Accepted  
**Date:** 2026-05-04

### Context
When LocalMind processes a document (e.g. `CV.pdf`) and writes it back to the
user's folder, writing it as `CV.pdf` would silently overwrite the original.
The user expects to keep their original as a reference.

### Decision
Document-format files (PDF, DOCX, images, etc.) are copied back with a
timestamp suffix: `CV.pdf` → `CV_20260504_143022.pdf`. Code and data files
(`.py`, `.md`, `.json`, etc.) are copied back as-is — they follow the
safe-write + diff + confirm pattern instead.

If the user explicitly names the output file, the timestamp rename is skipped
entirely and the file is written with the user's chosen name.

### Consequences
- User's originals are always preserved (version-control semantics)
- Multiple processed versions accumulate naturally in the destination folder
- User decides which version to keep — LocalMind never makes that choice
- Code files are exempt because they have their own safe-write pattern

---

## ADR-003 — No silent path fallback

**Status:** Accepted  
**Date:** 2026-05-04

### Context
Earlier implementations fell back to `~/LocalMind/` when a user-specified
path could not be resolved. This was worse than an error: the file was
written to the wrong place with no indication anything had gone wrong.
The user would look for their file in the specified location, find nothing,
and have no way to know where it actually went.

### Decision
`resolve_write_path()` raises `PathUnresolvableError` if the path cannot be
anchored to a known folder. The only time `~/LocalMind/` is used as the
destination is when the user gave **no path at all**. A fuzzy suggestion is
included in the error when a close match is found by scanning `~/`.

### Consequences
- Users get explicit feedback when their path intent isn't understood
- No files land silently in the wrong location
- `PathUnresolvableError` must be caught at every call site (both `write_file`
  and `FileWriteContract.execute`) and surfaced as a user-facing clarification
  prompt

---

## ADR-004 — External drive support deferred

**Status:** Deferred  
**Date:** 2026-05-04

### Context
The allowed-path set covers only `Path.home()` and its known subdirectories.
External drives (`D:\`, `E:\`, network paths) are not covered.

### Decision
External drive support is deferred. When needed, it will be implemented as
an explicit opt-in via `LOCALMIND_EXTRA_PATHS=D:\Projects,E:\Backups` in
`.env`. No auto-discovery of drives — the user controls exactly what is
exposed.

### Consequences
- Users working entirely within their home directory are unaffected
- Users with files on external drives must add `LOCALMIND_EXTRA_PATHS` to use them
- No security risk from auto-discovering and allowing all mounted drives

---

## ADR-005 — Lazy cache cleanup

**Status:** Accepted  
**Date:** 2026-05-04

### Context
`~/LocalMind/` accumulates scratch files over time. A background cleanup
process would require a scheduler and adds complexity. A startup-time cleanup
misses the case where the server runs continuously for days.

### Decision
Cleanup runs lazily — triggered on every write, before the write happens.
Top-level entries in `~/LocalMind/` older than `LOCALMIND_CACHE_MAX_AGE_DAYS`
(default: 7) are deleted. Directories are deleted recursively if their
top-level entry is expired. The DB files and `uploads/` are never touched.

### Consequences
- No scheduler needed — cleanup piggybacks on normal write activity
- If the user never writes anything, stale files accumulate (acceptable —
  the user is not actively using the system)
- Cleanup is `O(n)` in the number of top-level entries — negligible for
  normal usage

---

## ADR-006 — Codebase folders default to repo

**Status:** Accepted  
**Date:** 2026-05-04

### Context
When a user hands LocalMind a folder containing source code, they expect
repo-aware behaviour: respect project structure, produce pull-ready outputs,
and don't rename or restructure without permission. Treating it as a plain
folder produces outputs that don't fit the user's workflow.

### Decision
Any folder that looks like a codebase is treated as a Git repository by
default. "Looks like a codebase" means: contains source files and/or common
repo artefacts (`.git/`, `pyproject.toml`, `package.json`, `Makefile`, etc.).
The user can override with "treat this as a plain folder".

### Consequences
- Outputs are pull-ready by default — coherent, scoped, integration-noted
- The planner and synthesiser must be aware of this convention
- False positives (a folder that looks like a repo but isn't) are low risk —
  pull-ready formatting on a plain folder is harmless

---

## ADR-007 — Tool decomposition is opt-in, not mandatory

**Status:** Accepted  
**Date:** 2026-05-04

### Context
Splitting every tool into a package of sub-modules adds structure but also
overhead. Simple tools (sysinfo, web_search) do not benefit from
decomposition — they have one job and one reason to change.

### Decision
Decompose a tool into a package only when it has multiple distinct
responsibilities that have different reasons to change. The test: if you
could imagine testing one part independently of the others, it should be
a separate module. Apply to `file_writer` and `file_reader` first.
Leave `sysinfo`, `web_search`, `memory_tool` as single files.

### Consequences
- `file_writer/` and `file_reader/` become packages (planned)
- Other tools stay flat — no unnecessary abstraction
- Sub-modules within a tool package are importable by other tools (composability)
