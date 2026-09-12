# Current Task

**Status:** IDLE — **Session 471 (Kojo / glm-5.3-flash, ZCode local, Windows) COMPLETE (2026-09-12): glm-5.3-flash bankofai stall diagnosed (pre-first-byte provider queue, request shape excluded live), provider-stall watchdog shipped (`e32e08a1`) and live-verified end-to-end (notice@5s, offer@30s, clean recovery), ZCode import map documented, standing Target updated to the resilience + import program.**

**Outcome:** Diagnosis via two live probes (app fast path + differential request shapes, 30 calls total): the owner's 107s silent turn was queue time at bankofai's glm-5.3-flash upstream — not thinking, not the app, not the request shape; the app streams thinking per-delta. Same-session postscript: the free promo flipped to paid (`400 insufficient_user_quota` — S464's documented shape); qwen/hy3/mimo confirmed free. Fix (`e32e08a1`): fast path emits `provider_call_start`/`provider_first_byte`; heartbeat names the stalled provider and escalates past 30s to a switch-model offer, falling through truthfully once bytes arrive — no abort, no adapter change, no extra calls. +4 unit tests, 131 green on touched suites; live trace against a controlled 40s stall on the real server path. Report: `office/reviews/2026-09-12-review-s471.md`.

Feature: none
