# Current Task

- **Session:** 169 (2026-08-12)
- **Feature:** adr-21-provider-agnostic-errors
- **Task:** ADR-21 P0 — make the ADR-20 error normalizer genuinely
  provider-agnostic: any model's error JSON envelope (OpenAI, Anthropic,
  Ollama, Zen, Azure, gateways) normalizes into the same canonical card.
- **Done (169):** feature memory (manifest/design/ledger); normalizer —
  `_ERROR_TYPE_RULES` token catalog (~45 tokens), `_walk_error`/`_dig_type`
  envelope walking (error dict, `errors[]`, double-nested, error-as-string,
  top-level code, numeric-code-as-status), type-token-first classification
  (token → status → keywords → generic), provider-shaped generic errors keep
  `source=model_provider`; adapter body truncation `[:200]` → `[:1000]` (3
  openai_compat sites) so long JSON envelopes parse; provider matrix tests
  (OpenAI quota/API-key/context, Anthropic rate-limit/overload/not-found/
  too-large, Ollama string envelopes, Azure string+dict codes, double-
  nested, `errors[]`, unknown-token fallbacks, long-body parse, type-beats-
  status priority). Full backend suite green, ruff clean.
- **Next (170):** deepseek-flash review, live smoke attempt (provider-
  blocked expected), close out + push. Standing pendings unchanged:
  successful-turn live smokes for ADR-19/20/21 when a provider frees up
  (Zen completions still 429); B-2026-08-12-4 (live two-turn UI check);
  ADR-18 P1-P3; ADR-19 P1-P3.
