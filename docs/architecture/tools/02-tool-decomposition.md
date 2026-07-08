# 02 — Tool Decomposition

## Problem with the current layout

Every tool in `tools/` is a single flat file. This works at small scale but
breaks down as tools grow:

| Problem | Example |
|---|---|
| Hard to test in isolation | `file_writer.py` mixes path resolution, cache cleanup, permission gates, copy-back, and rename logic in one file |
| No reuse between tools | `file_reader.py` and `file_writer.py` duplicate path-handling logic |
| No enforced contracts between LM and execution | A tool can receive any string and interpret it however it likes |
| One broken function breaks the whole tool | A syntax error in cleanup logic prevents any write from happening |

## Target: sub-tool decomposition

Each complex tool becomes a package with focused sub-modules. Simple tools
(sysinfo, web_search) stay as single files — decomposition is not cargo-culting,
it is applied only where there is genuine complexity to separate.

### file_writer decomposition (target state)

```
tools/
  file_writer/
    __init__.py         Public interface — write_file(), FileWriteContract
    path_resolver.py    resolve_write_path(), PathUnresolvableError, _fuzzy_home_match()
    safe_write.py       _do_write(), scratch → copy-back, atomic swap
    cache.py            _cleanup_cache(), age policy, skip-list
    rename.py           _is_document(), _timestamped_name(), _DOCUMENT_EXTS
    permissions.py      Permission gate, pending_write state
```

### code_executor (already decomposed — reference model)

```
tools/
  code_executor/
    __init__.py
    detector.py         Language detection
    runner.py           Entry point
    sandbox.py          Subprocess isolation
```

`code_executor/` already follows this pattern. `file_writer/` and eventually
`file_reader/` should reach the same state.

## Composability

Sub-tool decomposition makes tools callable from other tools without
duplication:

```python
# Before: file_reader.py duplicates path logic from file_writer.py

# After: both import from the same sub-module
from tools.file_writer.path_resolver import resolve_write_path
```

The orchestrator never changes — it still calls `contract.execute(payload)`.
The decomposition is internal to the tool package.

## Migration status

| Tool | Current state | Target state | Tracking |
|---|---|---|---|
| `file_writer.py` | Monolithic file | `file_writer/` package | Planned |
| `file_reader.py` | Monolithic file | `file_reader/` package | Planned |
| `code_executor/` | Package ✅ | No change needed | Done |
| `shell.py` | Single file + Phase 3 contract ✅ | No change needed | Done |
| `web_search.py` | Single file | Single file (complexity doesn't warrant split) | Stable |
| `sysinfo.py` | Single file | Single file | Stable |
| `memory_tool.py` | Single file | Single file | Stable |

## Rule

> Decompose when a single file has more than one reason to change.
> A file that handles I/O, validation, business logic, and cleanup all at once
> has four reasons to change. Split it.
