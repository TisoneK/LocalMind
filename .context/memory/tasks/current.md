# Current Task

**Status:** DONE — Session 282: live-verified B-2026-08-16-12 and found + fixed
B-2026-08-16-13 (the real discarded-synthesis bug: chat_with_tools dropped the
answer tail). Product commit + context commit.

**What shipped (B-2026-08-16-13, adapter tail-drop fix):**
- `backend/src/adapters/openai_compat.py`: `chat_with_tools` Phase 1 and Phase
  2b now share ONE line iterator (Phase 2b resumes the same httpx generator).
  The old gate `if not _resp.is_stream_consumed` was ALWAYS False (httpx flips
  that flag at iteration START), so every text answer Phase 1 broke out of
  mid-stream was truncated to ~16 tokens — the real cause of the user's
  "correct synthesis discarded" experience (mid-sentence cut, no error, shipped
  as a successful reply). `_phase1_exhausted` (only set on [DONE]) replaces it.
- Regression test `test_phase2b_streams_full_tail_after_phase1_break` with a
  faithful one-shot fake — fails on old code, passes on new.

**Verification:**
- Full backend suite 1879 pass, 4 pre-existing env-gated shell fails.
- **LIVE-VERIFIED before/after on the SAME task (z.ai/glm-4.5-flash):**
  before = "No, there is not enough free disk space to install a 50" (16
  tokens); after = complete 500-char answer. Evidence in /tmp/lm-281/.
- B-2026-08-16-12 (degraded path) also live-confirmed no-regression in the
  same session (Thinker consult runs on the real path).
- CORRECTED ai-models.md: S252's "glm-4.5-flash free-tier output budget
  truncates at 60-75 chars" was this adapter bug, not a provider limit.

**Open next / notes:**
1. Carried: B-2026-08-16-11 (as-completed streaming for delegate_parallel;
   audit its brittle arg schema), real-app visual checks (todo panel S274;
   narration on a content model), B-9 (create→FILE_WRITE, reasoning-driven),
   Windows re-run of S264.
2. The live-testing harness works on this machine (key in ~/LocalMind/
   settings.json; recipe in .context/memory/system/live-testing.md) — use it
   for future agent/adapter changes instead of assuming no key.

**Feature:** none
