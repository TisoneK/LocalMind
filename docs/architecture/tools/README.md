# LocalMind — Architecture Reference

This folder is the authoritative source for architectural decisions in LocalMind.
Each document covers one concern. Read them in order if you are new to the codebase.

| File | Covers |
|---|---|
| [01-system-overview.md](01-system-overview.md) | Layer map, request flow, directory structure |
| [02-tool-decomposition.md](02-tool-decomposition.md) | Why monolithic tool files are being split and what replaces them |
| [03-file-handling.md](03-file-handling.md) | Safe-write pattern, scratch space, copy-back, version control behaviour |
| [04-codebase-handling.md](04-codebase-handling.md) | How LocalMind treats user codebases (repo defaults, safe-write for code) |
| [05-decisions.md](05-decisions.md) | Architectural Decision Records — every significant design choice and why |

## Governing principle

Every rule in these documents is either already enforced in code or has a
tracking note pointing to the task that will enforce it. Documentation that
cannot be traced to code is not architecture — it is wishful thinking.
