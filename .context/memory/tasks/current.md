# Current Task

- **Session:** 195 (2026-08-13, complete)
- **Feature:** adr-8-agent-centric-routing (Phase 4 track 2 — weather signal + tool-call leak defense)
- **Task:** Live transcript bug — "Whats the weather like in Kitengela now?" misrouted to
  CHAT (classifier confidence 0.30) and the model's raw
  `<tool_call>web_search<arg_key>…</arg_key><arg_value>…</arg_value></tool_call>` streamed
  into the bubble. Fix root + defense, per the project's "fix root not symptoms" rule.
- **Done (195):**
  - ROOT: deterministic weather→WEB_SEARCH signal (zero-LLM, realtime_sensitive) with
    guards — file/read phrasing blocked, time words aren't places, casual statements
    ("It's hot in here") need a weather noun or a question form.
  - DEFENSE: bare <tool_call>/arg_key/arg_value format added to the Session 127
    interception (text_tools parse/strip/detect + filters strip incl. partials); DIRECT
    path buffers RAW text for detection so the strip can't hide escalation → misrouted
    requests run the web_search in the agent loop, never leak XML.
  - Full backend **1747 green** (+19), ruff clean; code-review findings all fixed.
- **Next (backlog):** deterministic engine web_search fast-path for weather (Session 193
  file-ops pattern); wire the ambiguous file-ask reply through the deterministic chain;
  then ADR-8 Phase 4 track 1 (task-type classifier) or Phase 2 (build_context → run) —
  both need real-model testing per the flaw log.
