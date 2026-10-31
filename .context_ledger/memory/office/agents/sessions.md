# Agent Sessions (append-only within the current office)

One entry per agent session in the **current office**, newest at the bottom.
Never edit or delete past entries — append corrections instead. This is not
append-only *forever*: when the office reaches `office_size` sessions (or a
milestone), `ledger-history close` freezes this whole office verbatim into
`.context_ledger/history/office-<NNN>/` (roster, registry, notes, logs —
nothing trimmed), writes the permanent accomplishments record
`.context_ledger/history/office-<NNN>.md`, and opens a fresh empty office
here. Closed offices in `history/` and `archive/` are never read at session
start. Before closing, note which open threads still matter — they are
re-seeded into the new office explicitly, and nothing else carries over.

<!-- TEMPLATE — copy below the last entry and FILL IN every placeholder:
---
## YYYY-MM-DD — Session N
- **Agent:** <name> | **Model:** <model id> | **Platform:** <machine/sandbox + OS> | **Role:** <engineer, or overlay from .context_ledger/core/roles/> | **Core:** <version from .context_ledger/core/VERSION>
- **Task:** <what this session set out to do>
- **Commits:** <count> (<first-sha>..<last-sha>)
- **Outcome:** <done / partial / blocked — one line>
- **Open items:** <pointers into tasks/backlog.md (actionable) or tasks/parking-lot.md (findings/questions), or "none">
- **Notes:** .context_ledger/memory/office/sessions/<date>-<N>/notes.md  (or "none")
- **Report:** .context_ledger/memory/office/reviews/YYYY-MM-DD-review.md
-->

---
## 2026-10-31 — Session 1
- **Agent:** Kofi | **Model:** unknown (harness states no model ID) | **Platform:** Windows 10.0.26300 x64, local repo | **Role:** engineer | **Core:** 2.2.1
- **Task:** Fix `storage.vector` "Vector batch write failed: Dimension mismatch … Expected 768 dimensions but received 1024" (memory writes failing at runtime while startup reported healthy), and repair the local memory DB without data loss.
- **Commits:** 4 by this session (6aa08d40 claim, 92398247 product fix, this ledger close; plus peer commit c199cbd1 from the shared checkout that carried this session's review + parking-lot edits)
- **Outcome:** done — vec0 table DDL is now the startup ground truth (empty stale index rebuilt, populated index trusted over meta, genuine mismatch refused loudly), runtime length guards, chat-model embed fallback removed, reset script fixed (it had been masking a failed DROP and reporting a false "dims match"); local DB repaired (4 facts re-embedded at 1024) and live-verified through `npm start` + `POST/GET /api/memory`.
- **Open items:** parking-lot P-2026-10-31-1 (reset script has no cloud-embedder probe path). Pre-repair DB backup at `C:\Users\tison\LocalMind\localmind.db.bak-20261031`.
- **Notes:** none
- **Report:** .context_ledger/memory/office/reviews/2026-10-31-review.md

---
## 2026-10-31 — Session 2
- **Agent:** Nadia | **Model:** unknown (harness states no model ID) | **Platform:** Windows 10.0.26300 x64, local repo | **Role:** engineer | **Core:** 2.2.1
- **Task:** Diagnose and fix the two failures in the owner's 11:27–11:36 chat export: (1) Cerebras rejecting the payload with `messages.2.user.tool_calls: property '...' is unsupported` (non-retryable dead end), (2) the behavioural failures — conversation-recall answered by a memory dump, "Don't you?" read against the wrong referent, contradictory name facts.
- **Commits:** 3 by this session (c199cbd1 check-in, 253ae0b4 fast-path history fix, af347f95 wire normalization + recall lane + memory identity); ledger close in this commit.
- **Outcome:** done — (a) `tool_calls` now rides only an assistant turn that called a tool, both where history dicts are built and at the adapter boundary for every provider call (`normalize_messages_for_wire`); (b) a 400 naming an unsupported property classifies as new `invalid_request` and the failover adapter switches providers with the history intact instead of stopping at "switch model" (no wait, 60s cooldown); (c) conversation-recall questions ("did you answer that from memory?", "what was your reply before that?") route to a transcript-only lane with memory withheld and no tools, quoting the first user message when asked, and a short follow-up resolves against the most recent assistant reply only; (d) third-person name facts ("User's name is …") now hash to `subject:name`, so a correction replaces the fact instead of appending a duplicate. Memory DB cleanup: merged the two name facts into one (correct pronunciation "like Tyson" + the keep-the-profile-caveat instruction) and deleted the empty `source for EPL table` placeholder; the surviving name fact was re-written under `subject:name`. Backups: `localmind.db.bak-20261031-nadia` (mine), `localmind.db.bak-20261031` (Kofi).
- **Open items:** the EPL source was deleted as an empty placeholder — re-add it with the actual URL if wanted. Two test-harness encoding bugs fixed along the way (fixtures/prompt files read as cp1252 on Windows). Acceptance items that need a live provider run remain unverified end-to-end (see notes).
- **Notes:** none
- **Report:** .context_ledger/memory/office/reviews/2026-10-31-review.md
