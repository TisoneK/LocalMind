# Current Task

**Status:** DONE — Session 288: fixed B-2026-08-16-18 (local Ollama models
starved by the 45s per-call timeout). Product commit + context commit.

**What shipped (B-2026-08-16-18):**
- `backend/src/adapters/base.py`: new `slow_provider` property (False) — a
  DISTINCT signal from `thinking_enabled`: slow local providers get the
  generous ADR-41 budgets WITHOUT the Thinker (which stays gated on
  thinking_enabled — an extra sequential consult a slow model can't afford).
- `backend/src/adapters/ollama.py`: `slow_provider` → True.
- `backend/src/core/agent/loop.py`: `_per_call_timeout_for` honors
  `settings.ollama_timeout_chat` for slow providers (floored at the 45s
  generic cap); `_plan_timeout_for` and the wall-clock branch treat
  slow_provider like thinking_enabled (reasoning budgets).
- `backend/src/core/agent/orchestrator.py`: `_orchestrator_timeout_for` scales
  for slow_provider too.
- `backend/src/core/config.py`: `ollama_timeout_chat` default 90 → 180, so the
  loop cap and the adapter's own chat HTTP timeout move together (single knob).

**Verification:**
- 5 new tests (4 unit: per-call honors ollama_timeout_chat + floors at the
  generic cap, plan scales, orchestrator scales == 30.0, OllamaAdapter reports
  slow_provider=True and NOT thinking_enabled; 1 loop-level: with
  MAX_WALL_CLOCK_SECS forced to 0.0, the pre-fix loop breaks at iter 1
  ("wall-clock cap hit after 0.3s") while the slow_provider adapter completes
  with the full answer). 4 of 5 fail on pre-fix code, all pass on new.
- Full backend suite 1896 pass (+5), 4 pre-existing env-gated shell fails;
  ruff clean.

**Open next / notes:**
1. Carried: B-2026-08-16-11 (as-completed streaming for delegate_parallel;
   audit its brittle arg schema), real-app visual checks (todo panel S274;
   narration on a content model), B-9 (create→FILE_WRITE, reasoning-driven),
   Windows re-run of S264.
2. Carried (S285): the other BLOCKED_COMMANDS substring entries (e.g.
   "rm -rf /") are equally blunt — audit/regEx-ify them.
3. Carried (S288): NOT live-verified on the user's Windows/Ollama box — the
   user should retry phi4-mini after this ships; if a single call still
   truncates on very slow hardware, raise `ollama_timeout_chat` (or the
   OLLAMA_TIMEOUT_CHAT env var) further — the loop cap follows it.
4. z.ai/glm-4.5-flash free tier intermittently returns plain-empty final
   streams on multi-step tasks — handled (B-12), but consider retry-on-empty
   for the final synthesis call if it persists.
5. Model testing punch list (S280-287): hy3-free (zen) is the current best;
   DeepSeek strongest when its free tier has headroom. All agent-side bugs the
   comparisons surfaced (B-12/13/14/15/16/17/18) are fixed.

**Feature:** none
