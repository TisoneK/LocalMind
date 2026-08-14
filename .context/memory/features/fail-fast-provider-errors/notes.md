# Notes: fail-fast-provider-errors

The handoff initially described only the adapter fix. Code tracing showed the actual loop defect was two-stage: planning swallowed terminal errors, and `AgentRuntime` swallowed terminal error chunks marked `done=True`. The fix preserves the raw provider string only inside backend `StreamChunk.error`; `chat.py` remains the sole presentation boundary and calls `normalize_error()` exactly as ADR-20/21 require.

A permanent quota 429 also had an extra no-backoff request in the adapter's response-refresh fallback. Returning the buffered response removes that hidden second request. The final transient retry returns its already-read response as well, avoiding a fourth request.
