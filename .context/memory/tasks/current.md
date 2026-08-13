# Current Task

- **Session:** 184 (2026-08-13, in progress)
- **Feature:** adr-22-agent-first-routing
- **Task:** ADR-22 implementation done; smoke testing in progress.
- **Done (184):**
  - ADR-22 written + 3 code changes + test updates.
  - 1573 backend tests pass; ruff clean.
- **Next:** Real-model smoke against DIVERSE prompts across all tool
  categories (file_task, web_search, calculate, find_path, sysinfo,
  shell, code_exec). Capture UI screenshots via Playwright Python
  (agent-browser can't reach localhost from its sandbox — documented
  in inefficiencies/log.md). Verify the agent reasons + acknowledges
  within seconds.
