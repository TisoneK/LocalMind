# Session 206 notes

The user clarified that the critical failure was not merely an incomplete web
search. A simple `Hi` was entering the parent agent, spending more than 30
seconds in silent reasoning/tool activity, and making LocalMind feel detached
from the user.

Discovery found that `core/trivial_input.py` already implemented the intended
contract: deterministic social replies with zero LLM calls, plus a direct-chat
path for clearly conversational questions. The request-pipeline migration had
removed the only production caller, so `AgentRuntime` sent every request to
`ParentAgent.run()`.

Restored the boundary inside `AgentRuntime` before memory retrieval, tool
selection, and parent-loop execution. Social inputs do not acquire an adapter
at all. Conversational questions acquire the normal adapter only for direct
chat and never receive tool definitions or parent planning. Both paths retain
history persistence, stage timing, observations, turn completion, and token
accounting. Substantive tasks remain on the single parent-agent execution path.

A regression patches both `core.agent_runtime.get_adapter` and
`ParentAgent.run` to fail if called for `Hi`; it also asserts no tool events and
checks the direct stage statuses. The first run exposed a circular import from
loading `trivial_input` at module import time, so the helper import is lazy at
the runtime boundary. Focused tests then passed.

Product commit: `8aefc51`.
