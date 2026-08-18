# Current Task

**Status:** DONE — Session 290. Thinking-block + acknowledgement persistence
fixed and verifiable; the "Hi hangs in the tool loop" ROOT fix (execute opt-in,
ADR-46) shipped. All pushed. Ollama path NOT live-verified here.

**Shipped:**
- `d161c36` thinking block restores on reopen (history mapping now sets isAgent).
- `5c8d082` ADR-36 acknowledgement persists across reload (new column).
- `368fc4d` (context) recorded model/env-agnostic root-fix preference.
- `035809c` ROOT: execute is opt-in (ADR-46) — the tool loop runs only on an
  explicit parseable `mode:execute`; everything uncertain → bounded DIRECT from
  the model's own output. Direct turns report real usage. Init decision logged.
- `8b167b7` changelog.

**Open next:**
1. B-2026-08-17-2 — user verifies on Windows/Ollama: "Hi" answers in one step;
   READ THE NEW INIT LOG LINE (`[agent.loop] parent initialization mode=... raw=...`)
   to confirm whether the on-box cause was a parse-failure (now → direct) or a
   genuine mode=execute misclassification.
2. B-2026-08-17-3 — constrained JSON for the classify call (model-agnostic),
   GATED on the init log confirming parse-failure is the real cause.
3. B-2026-08-17-4 — restore thinkMs/diffData/candidates on reload.
4. Carried: progressive tool-schema disclosure (ADR-43 Phase 3); B-2026-08-17-1.

**Principle (do not regress):** the tool loop is OPT-IN (ADR-46), never
fail-open. Fix the agent model/env-agnostically — never "for local/weak models"
(that's symptom-fixing; see user/preferences.md).

**Feature:** none
