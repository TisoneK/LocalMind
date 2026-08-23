# Current Task

**Status:** IDLE — Session 341 updated the live-testing docs.

## Session 341 outcome — live-testing doc rewritten (bankofai primary, scripts workflow, root-cause method)

- **Task:** Update `.context/memory/system/live-testing.md` per user: **bankofai** (fast + free) is the primary live-test provider; **zai/glm-4.5-flash** is the slower/weaker model. Documented the `scripts/` harnesses — `live_test_cybercafe.py` (repro), `lm_benchmark.py` (52-test suite), `lm_collision_tests.py` (multi-guard), `run_*_detached.sh` — and the root-cause-first debugging rule (cluster failures into root causes, misdiagnosis worse than no diagnosis, fix the mechanism not the symptom).
- **Bookkeeping gap found:** Sessions 332-340 shipped (commits) but were never logged in `agents/sessions.md` (last entry: Session 331); `tasks/current.md` was last updated at "Session 332 complete" (`d7de7cf`). Their evidence lives in `.context/memory/system/test-results-336.md` + `test-catalog.md` + the live-testing.md session log. Note: back-filling is not done — flagged for future sessions per append-only rules.
- **Next:** standing backlog in `tasks/backlog.md`.

**Feature:** none
