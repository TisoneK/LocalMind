# Inefficiency Log (append-only, mandatory)

Every session appends one block — honestly. Friction you absorb silently
is friction the next agent hits blind. "None this session" is valid only
if literally nothing slowed you down.

Most inefficiencies are project-local (an environment quirk, a one-off
cost) and stay here. When one is actually **protocol-level** — the core
workflow itself made you slower and every project would hit it — mark it
`Upstream: candidate`. `ledger-sync harvest` collects those (and open
`flaws/`) into the package for an upstream fix. Unmarked entries are
never harvested.

Append-only, but prunable to cold storage: once an entry is explicitly
marked `RESOLVED` / `superseded` / fixed, move it **verbatim** into
`archive.md` in this directory so startup reads only the live entries.
`ledger-mem prune` reports which entries are archive-eligible; age alone
never makes an entry eligible.

<!-- TEMPLATE — copy below the last entry:
---
## YYYY-MM-DD — <agent> / <model>
- **Problem:** <what went wrong or was slower than it should be>
- **Cost:** <rough time/effort wasted>
- **Cause:** <root cause if known>
- **Workaround / fix:** <what worked, or "unresolved">
- **Prevent next time:** <protocol/context change that would have avoided it>
- **Upstream:** candidate  ← add this line ONLY for protocol-level friction
  worth a core fix; omit entirely for project-local friction.
-->

---
## 2026-09-12 — Amani / glm-5.3-flash (S1) — two shell-command-shape traps during the backlog re-row verification

- **Problem:** (1) Verifying the re-rowed backlog's escaped table cells failed twice: an inline `python -c "...(?<!\\)\|..."` died with `re.error: missing ), unterminated subpattern`, and the same pattern sent through a quoted `<< 'EOF'` heredoc landed on disk mangled (`\\` arrived as `\`) — quoted heredocs should not expand anything. A first `sed 's/\\\\//g'`-based check then reported two CORRECTLY-escaped rows as broken (it ate the escapes before counting) while masking the one row that genuinely had raw pipes. (2) A single ~90-line Bash command carrying THREE heredoc appends got truncated in flight — the second heredoc ran to end-of-input (bash warning "delimited by end-of-file"), silently appending the third command's text into the wrong file and dropping the third append entirely.
- **Cost:** two failed checker runs + one misleading false-flag pass + one file repair (the truncated session entry) ≈ 15 minutes.
- **Cause:** (1) the Bash tool's command string on this Windows box collapses doubled backslashes before heredoc/inline-script content is written — the same family as the `cmd //c` argument mangling (S460) and the `$VAR`-path mangle (S416); any check that strips escapes before counting also cannot distinguish "escaped pipe" from "raw pipe". (2) very long compound commands are not delivered intact.
- **Workaround / fix:** (1) anything containing backslashes — regexes, escaped pipes, Windows paths — goes through the Write tool into a script file, then runs; the checker counts RAW pipes per row (pipe not preceded by a backslash) instead of stripping escapes first; it caught the one genuine defect (regex literals inside B-2026-08-20-8) on the first try. (2) one heredoc append per Bash command; verify each file's tail immediately after appending.
- **Prevent next time:** never verify escaping with a tool that eats the escapes; never bundle multiple heredoc appends into one command on this box; when a heredoc warns "delimited by end-of-file", assume the LAST files in the command are corrupted or missing and check every tail before committing.

---
## 2026-09-14 — Njeri / qwen3.8-flash (S003)

- **Problem:** none this session — a clean sync-only session (core 1.0.6 → 1.1.1 migration + bookkeeping). The only slip was self-inflicted and caught instantly: a sed with the wrong spacing silently no-op'd on one placeholder (re-checked, fixed with a corrected pattern), and the backslash-mangling trap already logged above bit exactly once (a `--body-file C:\...` path) — the logged forward-slash workaround applied first try, zero extra cost.

---
## 2026-09-15 — Zuri / qwen3.8-flash (S004) — the live-test provider switch is a settings-file edit, not an env var

- **Problem:** (1) `LOCALMIND_ADAPTER=zai` on the harness server env did nothing — the server still dialed bankofai (log proved it). The scratch tracehome's `settings.json` pins `adapter`, and it wins over the env var. **This is the S445/S451-logged trap re-hit** (prior instances recorded in `system/ai-models.md` observations, not in this office's log): the lesson was in the registry but not in `live-testing.md`'s harness section, and one failed run went by before the boot log was read. (2) bankofai is QUOTA-EXHAUSTED (`credit insufficient balance: balance=0` — a 400, not a 429): the primary live-test provider is unusable until the owner tops up or re-keys. (3) Minor self-inflicted: one Edit-tool call anchored an `old_string` that spanned the start of the next test block and silently deleted its body — caught by re-reading the file, fixed in one pass.
- **Cost:** one failed live-test run + one settings-inspection cycle + one test-file repair ≈ 10 minutes.
- **Cause:** (1) `system/live-testing.md` says "provider/model is set in the settings file, NOT backend/.env" but the harness scripts also pass `LOCALMIND_ADAPTER` — implying the env var works; it does not override the settings file. (2) account balance, not code. (3) Edit-tool block replacement: anchoring on a test's closing lines + the NEXT test's opening swallows the gap.
- **Workaround / fix:** to switch providers for a live test, edit `scratch/tracehome/settings.json` (`adapter` + `model` fields; keys untouched) — verified working on zai/glm-4.5-flash. When inserting a test before an existing one, anchor `old_string` on the full opening of the target test and re-add it verbatim in `new_string` (done for the repair).
- **Prevent next time:** fixed at the source this session — `system/live-testing.md`'s gotchas now state the settings file beats `LOCALMIND_ADAPTER` (check the boot log's adapter line) and that a bankofai 400 "insufficient balance" is a hard outage, not a rate limit (fall back to zai, do not retry).
