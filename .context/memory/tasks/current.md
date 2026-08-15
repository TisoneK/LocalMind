# Current Task

No active task.

The next session must read `.context/kickoff.md` before starting work.

Last: Session 231 (Claude Code / claude-opus-4-8, local) — fixed spaceless
streamed text (thought process + quick replies): `_strip_minimax_tool_calls`
was trimming each streamed delta's edges, eating inter-token spaces. Added a
whitespace-safe stream variant. Corrects Session 230's wrong model-blame
diagnosis (B-2026-08-15-1 closed).
