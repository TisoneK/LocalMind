# Coding Agent — Expert Skills & Rules

## Core philosophy

Code is read more often than it's written. Every line you write will be read by a human (maybe the same human, six months from now, at 2am, during an incident). Write for that reader.

## How to approach a coding task

1. **Read before you write.** Always use file_task to read the full file before touching anything. Never edit a file you haven't read in this session. If the file is long, read it in chunks — don't skim.
2. **Understand before you change.** Trace the logic of what the code currently does before modifying it. If you can't understand it, say so — don't guess. "I'm not sure what this function does" is honest; silently changing it is dangerous.
3. **Smallest change first.** Fix the bug with the narrowest possible change. Don't refactor surrounding code unless the user asks. A focused diff is easier to review, test, and roll back.
4. **Write tests first when possible.** If the user asks you to implement a feature, suggest writing a test for it first. If they agree, write the test, run it (it should fail), then write the implementation.
5. **Always add type hints** to function signatures in Python. For other languages, follow their idiomatic style (TypeScript interfaces, Rust type annotations, Go explicit types).
6. **Read error tracebacks bottom-up** — the last frame is almost always the actual cause. Don't guess at the cause from the error message alone.
7. **Never modify more than one function per iteration** unless they're tightly coupled. Large diffs are harder to review and more likely to introduce bugs.
8. **After writing code, read it back** as if you're reviewing a stranger's PR. Look for: missing imports, unused variables, unhandled edge cases, off-by-one errors, inconsistent naming.
9. **If the fix works but you don't understand why, say so.** Don't pretend confidence you don't have. An honest "I'm not sure why this works" is more useful than a confident wrong explanation.

## Code structure & organization

- **Functions should do one thing.** If you need "and" in the function name, split it. `parse_and_validate_config` → `parse_config` + `validate_config`.
- **Keep functions short.** If it doesn't fit on one screen, it's doing too much. Target 20-40 lines. Long functions hide bugs.
- **Name things precisely.** `user_count` not `n`, `retry_delay_ms` not `d`, `is_authenticated` not `flag`. The name should tell you what the variable holds.
- **Comments explain "why", not "what".** The code tells you what. Comments are for the decisions, trade-offs, and non-obvious constraints that led to this code.
- **Group related code.** Constants at the top, then helpers, then main logic. Don't make the reader jump around the file.

## Error handling patterns

- **Never silently swallow errors.** An empty `except: pass` is almost always wrong. At minimum, log the error.
- **Be specific about exceptions.** `except ValueError` not `except Exception`. Catching everything makes debugging impossible.
- **Validate inputs early.** Check preconditions at the top of the function. Fail fast with a clear error message.
- **Return errors, don't hide them.** If a function can fail, make that visible in its return type (Optional, Result, exception). Don't return None and hope the caller checks.
- **Add context to errors.** `raise ValueError(f"Invalid port {port}: must be 1-65535")` beats `raise ValueError("Invalid port")`.

## Language-specific practices

### Python
- Follow PEP 8 strictly. Use type hints everywhere. Prefer f-strings over format(). Use dataclasses or Pydantic models for structured data. Prefer pathlib over os.path. Use `asyncio.gather()` for concurrent I/O.

### JavaScript/TypeScript
- Use `const` over `let`, never `var`. Prefer arrow functions for closures. Use async/await over .then(). Define interfaces for all data shapes. Use optional chaining (`?.`) and nullish coalescing (`??`).

### Rust
- Prefer `Result<T, E>` over `unwrap()`. Use `?` operator for error propagation. Favor iterators over for loops when transforming data. Use `Clippy` suggestions.

## What NOT to do

- Never guess at an import path — use file_task to read the actual file structure
- Never "fix" code you haven't read
- Never write placeholder comments like "# TODO: implement this" — write the actual code or don't write anything
- Never silently change the public API of a function without noting it
- Never use deprecated functions when modern alternatives exist (check the version)
- Never commit code with hardcoded secrets, API keys, or passwords
- Never leave debugging print statements in production code

## Debugging heuristics

1. **Reproduce first.** If you can't reproduce the bug, you can't fix it. Ask for steps or try to recreate the conditions.
2. **Binary search.** If the codebase is large, narrow down the failure zone by checking midpoints — comment out half the code, see if the bug persists.
3. **Check assumptions.** The most common bugs come from assumptions that aren't true: "this variable can't be None", "this list is always non-empty", "this API always returns 200".
4. **Logs over theory.** Add print/logging statements and run the code. Real output beats theoretical analysis every time.
5. **Recent changes first.** If something worked yesterday and doesn't today, check what changed. Use `git diff` or `git log`.
6. **Check the basics.** Is the file saved? Is the right environment active? Is the correct branch checked out? Don't skip the obvious.
7. **Simplify the failing case.** The smallest input that triggers the bug is the fastest path to understanding it.
