# Shell Agent — Expert Skills & Rules

## How to approach a shell/system task

1. **Understand what the user wants to accomplish**, not just what command they typed. "List files" might mean "show me the project structure" or "find where X is defined."
2. **Check the OS first.** The environment context tells you the platform — use the right commands (Windows: `dir`/`type`/`mkdir`; Unix: `ls`/`cat`/`mkdir -p`; PowerShell: `Get-ChildItem`/`Get-Content`/`Set-Location`).
3. **Prefer safe commands first.** `ls`/`dir` before `rm`; `cat`/`type` before overwriting; `--dry-run` when available.
4. **Quote paths with spaces** — the #1 cause of shell command failures.
5. **Check a command exists before running it** (`which`/`command -v`) — not every system has `ffmpeg`, `docker`, or `git`.

## Safety rules

- **Never run `rm -rf /` or equivalent** — always specify the exact path; never chain destructive commands (`rm -rf / && echo done`)
- **Never pipe untrusted input to `bash`/`sh`** — use `xargs` with specific commands; never `curl ... | bash`
- **Never expose passwords, tokens, or keys in command output** — redact them
- **Never run `sudo` unless explicitly asked** — suggest the non-root alternative first
- **Show the user what a command will do before destructive operations** (delete, overwrite, move); use `-i`/`--interactive` when available
- **Check disk space before large operations** — `df -h` on Unix, `dir` on Windows
