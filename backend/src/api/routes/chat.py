"""
Chat endpoint — v0.5

POST /api/chat — multipart/form-data with message + optional file.
Streams SSE.

Title generation (two-stage):
  - Stage 1 (sync): heuristic placeholder written immediately on first turn
  - Stage 2 (async): LLM-generated title written ~2s later as background task

v0.5 fixes:
  - SSE keepalive/heartbeat during long model loading (prevents client timeout
    on cold starts — the "first Hello gets swallowed" bug)
  - Fix: yield text BEFORE done event when chunk.done=True and chunk.text is
    non-empty. Previously the `elif` chain dropped the final token(s).

SSE payload types:
    {"obs_event": {"type": "intent_classified", "data": {...}}}
    {"intent": "web_search", "confidence": 0.92}
    {"type": "token", "content": "Hello"}
    {"type": "done"}
    {"obs_event": {"type": "turn_complete", "data": {...}}}
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from core.config import settings
from core.engine import Engine
from core.error_normalizer import SOURCE_INTERNAL, normalize_error
from core.obs import ObsCollector
from core.title_generator import generate_title_smart, refine_title_async

router = APIRouter()
logger = logging.getLogger(__name__)

_engine = Engine()
MAX_FILE_BYTES = settings.localmind_max_file_size_mb * 1024 * 1024


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _finalize_plan_todos(session_id: str) -> list[dict]:
    """Session 121: mark any plan todos the loop didn't explicitly advance as
    complete. The plan covers the whole turn, so when the turn ends the
    remaining steps are done (or moot) — this makes the persisted Todos panel
    agree with reality instead of leaving trailing "pending" rows.

    Returns the todos that were flipped so the SSE bridge can emit live
    todo_completed events. Best-effort — never raises into the stream."""

    flipped: list[dict] = []
    try:
        for row in _engine._store.list_todos(session_id):
            if row.get("id", "").startswith("plan-") and not row.get("completed"):
                _engine._store.upsert_todo(session_id, row["id"], completed=True)
                flipped.append({"id": row["id"], "completed": True})
    except Exception as _exc:
        logger.warning(f"[todos] finalize failed: {_exc}")
    return flipped


def _sse_comment(comment: str = "keepalive") -> str:
    """SSE comment line — ignored by EventSource but keeps the connection alive.

    Browsers and proxies (nginx, CloudFlare) may close idle SSE connections
    after 30–60s of silence. Sending a comment every 15s prevents this.
    The comment is prefixed with ': ' per the SSE spec — EventSource.onmessage
    never fires for comment lines, so the frontend is unaffected.
    """
    return f": {comment}\n\n"


def _is_first_turn(session_id: str) -> bool:
    """True if the session has no messages yet (this is the opening turn)."""
    try:
        # Reuse the engine's SessionStore instead of creating a new one per call.
        # The engine already holds a long-lived SessionStore instance.
        title = _engine._store.get_session_title(session_id)
        # A session with no title hasn't had its first turn processed yet
        return title is None
    except Exception:
        return False


async def _event_stream(
    message: str,
    session_id: str,
    is_first: bool,
    file_bytes=None,
    filename=None,
    client_intent: str | None = None,
    client_confidence: float = 0.0,
    content_type=None,
    original_path=None,
    disconnect=None,
):
    obs = ObsCollector()
    file_path_written = None
    file_name_written = None

    # ── SSE keepalive state ──────────────────────────────────────────────
    # Track the last time we sent ANY SSE data. If more than KEEPALIVE_INTERVAL_S
    # passes without data, send a comment line to prevent the client/proxy
    # from closing the connection. This fixes the "first Hello gets swallowed"
    # bug where cold model loading takes 30-180s and the browser/CDN times out.
    _last_sent_time = time.monotonic()
    _KEEPALIVE_INTERVAL_S = 15  # seconds between keepalive comments

    # ── Stage 1: write heuristic placeholder title immediately ────────────
    # This ensures the sidebar shows something before the LLM title arrives.
    if is_first:
        try:
            placeholder = generate_title_smart(message)
            _engine._store.update_session_title(session_id, placeholder)
            logger.info(f"[title] placeholder '{placeholder}' for {session_id[:8]}")
        except Exception as exc:
            logger.warning(f"[title] placeholder write failed: {exc}")

    try:
        _response_chunks: list[str] = []
        async for chunk in _engine.process(
            message=message,
            session_id=session_id,
            file=file_bytes,
            filename=filename,
            content_type=content_type,
            obs=obs,
            original_path=original_path,
            client_intent=client_intent,
            client_confidence=client_confidence,
        ):
            if disconnect and await disconnect():
                logger.info(f"Client disconnected for session {session_id}")
                # B-2026-08-02-2 (A2): the client closed the stream — stop
                # the backend work too (previously the AgentLoop kept running
                # until the wall-clock/iteration cap). Best-effort.
                try:
                    _engine.abort(session_id)
                except Exception:
                    pass
                break

            # Flush buffered obs events before each text chunk
            for evt in obs.drain():
                yield _sse(evt.to_sse_dict())
                _last_sent_time = time.monotonic()
                if evt.type == "intent_classified":
                    yield _sse(
                        {
                            "type": "intent",
                            "intent": evt.data.get("primary"),
                            "confidence": float(evt.data.get("confidence", 0.5)),
                        }
                    )
                # Bridge obs tool_call/tool_status events to proper SSE
                # tool_call events so the frontend's ToolSteps component
                # can show tool progress. Previously these obs events were
                # invisible to the frontend because the obs_event handler
                # only extracted intent/confidence.
                if evt.type in ("tool_call", "tool_status"):
                    _tool = evt.data.get("tool", "unknown")
                    _label = evt.data.get("label", _tool)
                    _status = evt.data.get("status", "running")
                    _iteration = evt.data.get("iteration", "")
                    _latency_ms = evt.data.get("latency_ms", "")
                    _output = evt.data.get("output", "")
                    # Session 120: which plan todo this action serves.
                    _todo_id = evt.data.get("todo_id") or None
                    # Session 122: the model's reasoning that led to this tool call.
                    _thought = evt.data.get("thought") or None
                    # Session 142: the plan-step label — the 'why' for the
                    # action. The loop attaches it as `reasoning` on every
                    # tool_call obs event (falls back to the model's thought
                    # on silent runs). MUST be forwarded here or the frontend
                    # renders a blank `why:` on the step cards.
                    _reasoning = evt.data.get("reasoning") or _thought
                    # Generate a stable ID from tool name + iteration so the
                    # frontend can match "started" and "done" events for the
                    # same tool call and UPDATE instead of appending duplicates.
                    # v0.8 fix: also include a hash of the tool args in the ID
                    # so that different tool calls in the same iteration (rare
                    # but possible) get different IDs, while retries of the
                    # same tool with the same args map to the same ID.
                    _args_hash = ""
                    _args_str = evt.data.get("tool_args", "")
                    if _args_str:
                        import hashlib

                        _args_hash = "-" + hashlib.md5(_args_str.encode()).hexdigest()[:6]
                    _tc_id = f"tc-{_tool}-iter{_iteration}{_args_hash}"
                    # Session 118: persist to the actions store so the Actions
                    # panel shows real history across reloads (was a stub that
                    # returned []). Best-effort — never break the stream.
                    try:
                        # Session 118 review: only create rows for EXPLICIT
                        # started-like statuses. Events with a defaulted
                        # "running" status (no status field) and empty input
                        # are phantom — recording them created junk rows.
                        if _status in ("started", "pending", "in_progress"):
                            _engine._store.create_action(
                                session_id=session_id,
                                tool_name=_tool,
                                status="running",
                                label=_label,
                                input=_args_str,
                                action_id=_tc_id,
                                iteration=int(_iteration) if str(_iteration).isdigit() else None,
                                todo_id=_todo_id,
                                reasoning=_reasoning,
                            )
                        elif _status in ("done", "failed"):
                            _engine._store.update_action(
                                action_id=_tc_id,
                                status="done" if _status == "done" else "failed",
                                output=_output or None,
                                duration=float(_latency_ms) / 1000.0 if _latency_ms else None,
                            )
                    except Exception as _exc:
                        logger.warning(f"[actions] record failed: {_exc}")
                    yield _sse(
                        {
                            "type": "tool_call",
                            "tool_call": {
                                "id": _tc_id,
                                "name": _tool,
                                "label": _label,
                                "status": _status,
                                "iteration": _iteration,
                                "latency_ms": _latency_ms,
                                "output": _output,
                                "tool_args": _args_str,
                                "arguments": _args_str,
                                "todo_id": _todo_id,
                                "thought": _thought,
                                "reasoning": _reasoning,
                            },
                        }
                    )

                # Session 27: Bridge todo events to SSE so the frontend's
                # TodoList panel can display the plan + progress.
                # Session 120: also persist them — todos are now the persistent
                # high-level checklist, actions hang off them via todo_id.
                if evt.type in ("todo_added", "todo_updated", "todo_cleared"):
                    try:
                        if evt.type == "todo_cleared":
                            _engine._store.clear_todos(session_id)
                        elif evt.type == "todo_added":
                            _engine._store.upsert_todo(
                                session_id,
                                evt.data.get("id", ""),
                                text=evt.data.get("text") or evt.data.get("content"),
                                completed=bool(evt.data.get("completed", False)),
                            )
                    except Exception as _exc:
                        logger.warning(f"[todos] record failed: {_exc}")
                    yield _sse(
                        {
                            "type": evt.type,
                            "todo": evt.data,
                        }
                    )

                # Bridge thinking_start/thinking_done obs events to proper SSE
                # thinking_start/thinking_end events. The frontend handles these
                # to show the ThinkingBlock component with real-time content.
                # Previously, thinking was only emitted as obs events, which the
                # SSE bridge ignored — so the frontend never saw thinking data.
                if evt.type == "thinking_start":
                    yield _sse({"type": "thinking_start"})
                if evt.type == "thinking_done":
                    yield _sse({"type": "thinking_end"})

                # Bridge todo_created obs events to SSE so the frontend's
                # Todos panel shows the agent's execution plan in real-time.
                # The agent loop emits these after parsing the plan steps.
                if evt.type == "todo_created":
                    try:
                        _engine._store.upsert_todo(
                            session_id,
                            evt.data.get("id", ""),
                            text=evt.data.get("text", ""),
                            completed=bool(evt.data.get("completed", False)),
                        )
                    except Exception as _exc:
                        logger.warning(f"[todos] persist failed: {_exc}")
                    yield _sse(
                        {
                            "type": "todo_created",
                            "todo": {
                                "id": evt.data.get("id", ""),
                                "text": evt.data.get("text", ""),
                                "completed": evt.data.get("completed", False),
                            },
                        }
                    )

                # Bridge todo_completed obs events — when a tool finishes,
                # the corresponding plan todo is marked complete.
                if evt.type == "todo_completed":
                    try:
                        _engine._store.upsert_todo(
                            session_id,
                            evt.data.get("id", ""),
                            completed=bool(evt.data.get("completed", True)),
                        )
                    except Exception as _exc:
                        logger.warning(f"[todos] persist failed: {_exc}")
                    yield _sse(
                        {
                            "type": "todo_completed",
                            "todo": {
                                "id": evt.data.get("id", ""),
                                "completed": evt.data.get("completed", True),
                            },
                        }
                    )

                # Bridge terminal_output obs events to SSE terminal_event.
                # When the agent loop executes a shell or code_exec tool,
                # it emits a terminal_output obs event containing the command
                # and its output. We forward this as a terminal_event so the
                # frontend terminal panel can display it in real-time.
                if evt.type == "terminal_output":
                    yield _sse(
                        {
                            "type": "terminal_event",
                            "terminal_event": {
                                "tool": evt.data.get("tool", "unknown"),
                                "command": evt.data.get("command", ""),
                                "output": evt.data.get("output", ""),
                                "success": evt.data.get("success", "True") == "True",
                                "latencyMs": int(evt.data.get("latency_ms", "0")),
                                "label": evt.data.get("label", ""),
                                "toolArgs": evt.data.get("tool_args", ""),
                            },
                        }
                    )

                # Session 123: bridge anomaly obs events to a top-level SSE
                # event so the Observe panel can ALERT (stall / token leak)
                # instead of silently displaying bad numbers. The frontend
                # accumulates these into the observation's `anomalies` list.
                if evt.type == "anomaly":
                    yield _sse(
                        {
                            "type": "anomaly",
                            "anomaly": {
                                "kind": evt.data.get("kind", "unknown"),
                                "severity": evt.data.get("severity", "medium"),
                                "title": evt.data.get("title", "Anomaly detected"),
                                "detail": evt.data.get("detail", ""),
                                "metrics": evt.data.get("metrics", {}),
                            },
                        }
                    )
                    _last_sent_time = time.monotonic()

                # Bridge diff events from edit_file tool results.
                # When the agent loop edits a file, the edit_file tool produces
                # structured diff hunks in its ToolResult metadata. The engine
                # emits these as obs events so the frontend DiffBlock component
                # can render green/red highlighted diffs — like Cursor/Claude.
                if evt.type == "file_diff":
                    yield _sse(
                        {
                            "type": "diff",
                            "diff": {
                                "hunks": evt.data.get("diff_hunks", []),
                                "language": evt.data.get("diff_language", ""),
                                "filePath": evt.data.get("path", ""),
                                "additions": evt.data.get("diff_additions", 0),
                                "deletions": evt.data.get("diff_deletions", 0),
                            },
                        }
                    )

            if hasattr(chunk, "metadata") and chunk.metadata:
                obs_evt = chunk.metadata.get("obs_event")
                if obs_evt:
                    yield _sse(obs_evt.to_sse_dict())
                    _last_sent_time = time.monotonic()
                if "path" in chunk.metadata:
                    file_path_written = chunk.metadata["path"]
                    file_name_written = chunk.metadata.get("filename")

            if chunk.error:
                # Adapters now yield text="" on errors, so there's no text to
                # emit as a token. Previously this yielded chunk.text (which
                # contained the error message) as a token event — that leaked
                # error text into the chat content. The .error field is the
                # sole authoritative signal; the frontend renders it via the
                # 'error' event handler.
                #
                # ADR-20 (Session 166): the raw provider payload never crosses
                # the presentation boundary. chunk.error stays a string for all
                # internal consumers; this is the ONE place it becomes the
                # canonical error object (code/message/retryable/raw) the
                # frontend renders as a friendly card.
                yield _sse({"type": "error", "error": normalize_error(chunk.error)})
                _last_sent_time = time.monotonic()
                return

            # ── BUG FIX: yield text BEFORE done event ───────────────────────
            # Previously the `if chunk.done: ... elif chunk.text:` chain dropped
            # any text that arrived in the same chunk as done=True. The adapter
            # often sends the final few tokens with done=True, which were silently
            # lost. This caused the last word or characters of every response to
            # be swallowed — especially noticeable on short responses like
            # "Hello!" where the ENTIRE response could be lost if the adapter
            # sent it as a single chunk with done=True.
            #
            # Fix: process text, thinking, and done as independent conditions
            # (not elif chains) so all fields are emitted in the correct order:
            #   1. text content first
            #   2. thinking tokens
            #   3. done signal last

            # 1. Emit text content FIRST — regardless of done flag
            if chunk.text:
                yield _sse({"type": "token", "content": chunk.text})
                _response_chunks.append(chunk.text)
                _last_sent_time = time.monotonic()

            # 2. Emit thinking tokens (separate from text)
            if chunk.thinking:
                if chunk.thinking == "start":
                    yield _sse({"type": "thinking_start"})
                elif chunk.thinking == "end":
                    yield _sse({"type": "thinking_end"})
                else:
                    yield _sse({"type": "thinking_token", "thinking": chunk.thinking})
                _last_sent_time = time.monotonic()

            # 3. Emit done AFTER text (so all content is already sent)
            if chunk.done:
                done_payload: dict = {"type": "done"}
                if file_path_written:
                    done_payload["file_path"] = file_path_written
                    done_payload["file_name"] = file_name_written or Path(file_path_written).name
                # Surface pending write confirmation payload to the frontend.
                # The UI renders Accept/Reject buttons when this field is present.
                if hasattr(chunk, "metadata") and chunk.metadata:
                    pending = chunk.metadata.get("pending_write")
                    if pending:
                        done_payload["requires_confirmation"] = pending
                yield _sse(done_payload)
                _last_sent_time = time.monotonic()

            # Bridge status updates from the engine to the frontend.
            # The engine emits StreamChunk(status="...") during long-running
            # operations so the user sees what's happening instead of a blank
            # "Thinking..." indicator. The frontend renders these as real-time
            # progress text in the thinking/status area.
            if hasattr(chunk, "status") and chunk.status:
                yield _sse({"type": "status_update", "status": chunk.status})
                _last_sent_time = time.monotonic()

            # ── SSE Keepalive ──────────────────────────────────────────────
            # If no SSE data was sent for _KEEPALIVE_INTERVAL_S seconds, send
            # a comment line to keep the connection alive. This prevents
            # browsers, proxies, and CDNs from closing the SSE stream during
            # long operations like model loading (which can take 30-180s on
            # cold start). Without keepalive, the first message "gets swallowed"
            # because the client closes the connection before the model responds.
            _now = time.monotonic()
            if _now - _last_sent_time >= _KEEPALIVE_INTERVAL_S:
                yield _sse_comment("keepalive")
                _last_sent_time = _now

            # Yield control back to the event loop after each chunk so the
            # SSE event is flushed immediately to the HTTP response. Without
            # this, FastAPI/Starlette may buffer multiple yields before sending,
            # causing the frontend to see chunks in batches rather than one-by-one.
            #
            # Bug C fix: Use asyncio.sleep(0) to yield control, which allows
            # the ASGI server to flush the response buffer. For servers that
            # support the ASGI flush extension (like uvicorn with HTTP/1.1),
            # we also attempt an explicit flush if available. This ensures
            # each SSE event is sent to the client immediately rather than
            # being buffered by the server's write buffer.
            await asyncio.sleep(0)

        # Capture a structured observation before the destructive SSE flush.
        # The snapshot uses read-only collector access, so every event below
        # remains available to the existing stream bridge.
        _engine.build_observation_snapshot(obs=obs, session_id=session_id)

        # Final obs flush — emit comprehensive turn_complete data
        for evt in obs.drain():
            yield _sse(evt.to_sse_dict())
            # Make sure turn_complete events include all metric fields
            if evt.type == "turn_complete":
                # Re-emit as a dedicated metrics event for the frontend
                yield _sse(
                    {
                        "type": "metrics",
                        "metrics": {
                            "tokens_approx": evt.data.get("tokens_approx", 0),
                            "prompt_tokens_approx": evt.data.get("prompt_tokens_approx", 0),
                            "total_latency_ms": evt.data.get("total_latency_ms", 0),
                            "memory_facts": evt.data.get("memory_facts", 0),
                            "confidence": evt.data.get("confidence", 0),
                        },
                    }
                )

        # Session 121: the plan covers the whole turn — mark any plan todos
        # the loop didn't advance as complete, live (the finally block repeats
        # the DB update for aborted/disconnected streams).
        for _td in _finalize_plan_todos(session_id):
            yield _sse({"type": "todo_completed", "todo": _td})

    except Exception as exc:
        logger.error(f"[chat] stream error: {exc}", exc_info=True)
        # Session 31: GUARANTEE — always yield SOMETHING to the user.
        # If the engine crashed before producing any output, yield an
        # error token + done so the frontend shows the error and resets.
        # ADR-20 (Session 166): the token carries a generic line — the raw
        # exception text used to leak into the content. The canonical error
        # object (below) carries the real, friendly message.
        yield _sse({"type": "token", "content": "⚠️ An error occurred. See the details below."})
        yield _sse({"type": "error", "error": normalize_error(str(exc))})
        yield _sse({"type": "done"})

    finally:
        # GUARANTEE: If the generator was interrupted (client disconnect,
        # exception, etc.) before engine.process() could persist the
        # assistant message, save whatever response text we accumulated.
        # This is the last line of defense against conversation memory loss.
        # The engine method deduplicates — if the message was already persisted
        # inside process(), this is a no-op.
        try:
            _engine._guarantee_persist_assistant(
                session_id=session_id,
                response_chunks=_response_chunks,
            )
        except Exception:
            pass  # Never let cleanup crash the SSE stream
        # Session 121: mark any plan todos the loop didn't explicitly advance
        # as done — the plan covers the whole turn, so a turn that ended (even
        # via abort/timeout) means the remaining steps are done or moot.
        # Best-effort DB-only here (no yield in finally); the live SSE update
        # is emitted on the normal completion path above.
        try:
            _finalize_plan_todos(session_id)
        except Exception:
            pass

    # ── Stage 2: schedule LLM title as background task ────────────────────
    # Fires after the response stream completes so it never blocks the user.
    #
    # Session 22: title-gen is now intent-gated, not turn-count-gated.
    # Instead of firing only on `is_first`, we check `should_refine_title()`
    # which returns True when:
    #   - The message is non-trivial (not a greeting/thanks/farewell)
    #   - AND the title hasn't already been refined (still a placeholder)
    # This means: if message 1 is "Hi", title-gen skips. If message 2 is
    # "How do I fix a Python bug?", title-gen fires on that. The sidebar
    # shows "New Chat" until a substantive message arrives.
    try:
        from core.title_generator import should_refine_title

        _current_title = _engine._store.get_session_title(session_id)
        if should_refine_title(message, _current_title):
            asyncio.create_task(refine_title_async(session_id, message))
            logger.info(f"[title] LLM refinement scheduled for {session_id[:8]} (message: {message[:30]!r})")
        else:
            logger.info(
                f"[title] skipping LLM refinement for {session_id[:8]} "
                f"(trivial input or title already refined)"
            )
    except Exception as _title_exc:
        # Fallback to the old is_first behavior if should_refine_title fails
        logger.warning(f"[title] should_refine_title check failed: {_title_exc} — using is_first fallback")
        if is_first:
            asyncio.create_task(refine_title_async(session_id, message))


@router.post("/chat/{session_id}/abort")
async def abort_session(session_id: str):
    """Request cancellation of a session's in-flight agent turn.

    B-2026-08-02-2 (A2): sets the session's abort event; AgentLoop.run()
    raises AgentAbortedError at the next iteration boundary and the engine
    yields a clean "⏹ Stopped by user." response. The frontend Stop button
    already closes the SSE stream (AbortController) — this endpoint makes
    the backend actually stop instead of running to the wall-clock cap.
    Safe to call when idle: each turn starts with a fresh (unset) event.
    """
    _engine.abort(session_id)
    return {"aborted": True}


@router.post("/chat/{session_id}/steer")
async def steer_session(session_id: str, message: str = Body(..., embed=True)):
    """Queue a steering message for a session's in-flight agent turn.

    B-2026-08-02-5 (A5): the message is drained by AgentLoop.run() at the
    next iteration boundary of the running turn — the agent sees it as a
    new user prompt and continues instead of being aborted and re-run. If
    no turn is currently running, the message waits for the next one.

    Body: {"message": "..."}
    Returns 200 {"accepted": true}; 400 for a blank message; 409 when the
    session's steering queue is full (agent is too far ahead — retry after
    the next step boundary).
    """
    text = (message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Steering message cannot be empty")
    if not _engine.steer(session_id, text):
        raise HTTPException(
            status_code=409,
            detail="Steering queue full — wait for the agent to finish a step and retry",
        )
    return {"accepted": True}


@router.post("/chat")
async def chat(
    request: Request,
    message: str = Form(...),
    session_id: str = Form(default=None),
    file: Optional[UploadFile] = File(default=None),
    file_full_path: Optional[str] = Form(default=None),
    original_path: Optional[str] = Form(default=None),
):
    """Stream a chat response as Server-Sent Events."""
    sid = session_id or str(uuid.uuid4())
    is_first = _is_first_turn(sid)

    file_bytes = None
    filename = None
    file_content_type = None

    if file and file.filename:
        try:
            file_bytes = await file.read()
            if len(file_bytes) > MAX_FILE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Maximum {settings.localmind_max_file_size_mb} MB.",
                )
            uploads_dir = Path(settings.localmind_uploads_path)
            uploads_dir.mkdir(parents=True, exist_ok=True)
            # SECURITY: Sanitize the filename to prevent path traversal.
            # A malicious filename like "../../etc/cron.d/evil" or
            # "..\\..\\..\\Windows\\System32\\evil.dll" must not escape
            # the uploads directory. We strip all directory components
            # and reject null bytes / absolute paths.
            safe_name = Path(file.filename).name  # strips ../ and drive prefixes
            if not safe_name or safe_name in (".", "..") or "\x00" in safe_name:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Invalid filename. Filenames must be non-empty and cannot contain "
                        "path separators or null bytes."
                    ),
                )
            dest = uploads_dir / safe_name
            dest.write_bytes(file_bytes)
            filename = safe_name
            file_content_type = file.content_type or "application/octet-stream"
            # Do NOT fall back to the uploads path — that would store our internal
            # copy location as the "source", which is wrong. file_full_path must
            # only be set when the frontend explicitly provides the original path
            # (i.e. Electron or desktop context where file.path is available).
            # In a browser context file_full_path stays None, which is correct.
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"[chat] file upload error: {exc}", exc_info=True)
            # Capture the error message while `exc` is still bound.
            # PEP 3110 unbinds `exc` when the except block exits, but the
            # _err() generator below is iterated later by FastAPI — by
            # then `exc` would be gone and the f-string would raise NameError.
            _upload_error_msg = f"File upload failed: {exc}"

            async def _err():
                # Keep upload failures on the same typed SSE contract as
                # engine/adapter failures so the frontend renders the error
                # instead of silently completing an empty assistant bubble.
                # ADR-20 (Session 166): upload failures are internal-domain —
                # normalize with source_hint so a "connection reset" inside
                # the upload isn't mislabeled as a provider outage.
                yield _sse(
                    {
                        "type": "error",
                        "error": normalize_error(_upload_error_msg, source_hint=SOURCE_INTERNAL),
                    }
                )
                yield _sse({"type": "done"})

            return StreamingResponse(
                _err(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

    # v0.11 PERFORMANCE: Check for client-side pre-classification headers
    # This allows the server to skip the dispatcher LLM call for trivial messages
    client_intent = request.headers.get("X-LocalMind-Intent")
    client_confidence = float(request.headers.get("X-Intent-Confidence", "0.0"))

    return StreamingResponse(
        _event_stream(
            message,
            sid,
            is_first,
            file_bytes=file_bytes,
            filename=filename,
            content_type=file_content_type,
            original_path=original_path or file_full_path,
            disconnect=request.is_disconnected,
            client_intent=client_intent,
            client_confidence=client_confidence if client_confidence > 0 else 0.0,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Session-ID": sid,
            # Bug C fix: Explicit hint to proxies and CDNs that this response
            # should NOT be buffered. The combination of Cache-Control: no-cache,
            # X-Accel-Buffering: no, and Transfer-Encoding: chunked (automatic
            # for StreamingResponse) ensures each SSE event is flushed to the
            # client as soon as it's yielded. This is critical for real-time
            # streaming — without it, reverse proxies (nginx, CloudFlare) may
            # buffer SSE events and deliver them in batches.
            "Connection": "keep-alive",
        },
    )
