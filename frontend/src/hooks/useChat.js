import { useState, useCallback, useRef, useEffect } from 'react'
import { streamChat, newSessionId, fetchHistory } from '../lib/api'

/**
 * useChat — manages all chat state and streaming.
 *
 * Message shape:
 *   { id, role, content, pending, error, file, filePath,
 *     thinking: string,        <- raw thinking text
 *     thinkMs:  number,        <- thinking duration in ms
 *     isAgent:  boolean,       <- true only for agent-loop intents
 *     toolSteps: [{action, input, status}],
 *   }
 *
 * Thinking chunk detection:
 *   The agent loop emits thinking as a single chunk: "*{text}*'\n\n"
 *   We detect it by: chunk starts with "*" AND ends with "*\n" or "*\n\n"
 *   This is deliberately strict to avoid routing real markdown content
 *   (bold text, bullets, search result previews) into the thinking box.
 *
 * isAgent is set to true when the SSE intent event carries an agent intent.
 * ThinkingBlock only renders for agent turns, so chat turns never show a spinner.
 */

// Intents that run through the agent loop and emit thinking chunks
// Intents routed through agent loop (emit *thinking* chunks)
const AGENT_INTENTS = new Set(['memory_op', 'code_exec', 'file_write', 'web_search'])
// Intents that emit thinking_start/thinking_done obs events (direct stream)
const THINKING_INTENTS = new Set(['chat', 'file_task', 'sysinfo', 'shell'])

/** True only for agent thinking chunks emitted by loop.py as *text*\n\n */
function isThinkingChunk(chunk) {
  return (
    chunk.startsWith('*') &&
    /\*\n*$/.test(chunk.trimEnd()) &&
    !chunk.startsWith('**')   // exclude bold **text**
  )
}

/** Strip the wrapping * markers and trailing whitespace */
function extractThinking(chunk) {
  return chunk
    .replace(/^\**/, '')       // leading *
    .replace(/\**\n*$/, '')    // trailing *\n or *\n\n
    .trim()
}

export function useChat(initialSessionId) {
  const [messages, setMessages]           = useState([])
  const [sessionId, setSessionId]         = useState(initialSessionId || newSessionId())
  const [isStreaming, setIsStreaming]      = useState(false)
  const [error, setError]                 = useState(null)
  const [file, setFile]                   = useState(null)
  const [observabilityData, setObservabilityData] = useState({})

  // FIX: Track the last loaded session ID to prevent the race condition
  // where setCurrentSessionId() triggers a history reload that wipes
  // the currently streaming messages.
  const lastLoadedSessionRef = useRef(null)

  // FIX: Sync internal sessionId when initialSessionId prop changes.
  useEffect(() => {
    if (initialSessionId && initialSessionId !== sessionId) {
      setSessionId(initialSessionId)
      lastLoadedSessionRef.current = null  // Allow history reload for the new session
    }
    // When initialSessionId is null (new chat / deleted chat), generate a fresh ID
    if (initialSessionId === null && sessionId) {
      const newId = newSessionId()
      setSessionId(newId)
      lastLoadedSessionRef.current = null
      setMessages([])
    }
  }, [initialSessionId])

  useEffect(() => {
    if (!initialSessionId) { setMessages([]); lastLoadedSessionRef.current = null; return }

    // FIX: Skip history reload when we're actively streaming.
    // This prevents the race condition where:
    //   1. User sends first message → send() adds userMsg + assistantMsg
    //   2. handleSend() calls setCurrentSessionId(sessionId) → changes initialSessionId
    //   3. This useEffect fires → fetchHistory returns [] (no DB rows yet)
    //   4. setMessages([]) wipes the user message and streaming assistant
    //
    // Also skip if we've already loaded this session's history (prevents
    // redundant reloads when the same sessionId prop is set again).
    // FIX 2: Also skip if sentSessionIdRef matches — this guards against
    // the case where initialSessionId changes to the SAME session we're
    // currently streaming in (shouldn't happen, but be defensive).
    if (isStreaming) return
    if (lastLoadedSessionRef.current === initialSessionId) return
    if (sentSessionIdRef.current === initialSessionId) return  // FIX: skip if we're sending to this session

    let cancelled = false
    fetchHistory(initialSessionId)
      .then((history) => {
        if (cancelled) return
        lastLoadedSessionRef.current = initialSessionId
        setMessages(history.map((msg, index) => ({
          id: index,
          role: msg.role,
          content: msg.content,
          timestamp: msg.timestamp,
          // Preserve rich fields from backend so they survive page reload
          thinking: msg.thinking || '',
          thinkMs: msg.thinkMs || 0,
          isAgent: msg.isAgent || false,
          toolSteps: msg.toolSteps || [],
          file: msg.file || null,
          filePath: msg.filePath || null,
          confirmation: msg.confirmation || null,
          // Preserve tool call / file result data from backend
          toolCalls: msg.toolCalls || null,
          fileResults: msg.fileResults || null,
          pending: false,
          error: false,
        })))
      })
      .catch((err) => {
        if (!cancelled) { console.error('Failed to load history:', err); /* don't wipe on error */ }
      })
    return () => { cancelled = true }
  }, [initialSessionId, isStreaming])  // FIX: added sentSessionIdRef guard above

  const abortRef       = useRef(null)
  const streamingIdRef = useRef(null)
  const thinkStartRef  = useRef(null)

  // FIX: Track the session ID used for the current send operation.
  // Expose this so App.jsx's handleSend can read the ACTUAL session ID
  // (not the stale closure value) when setting currentSessionId.
  const sentSessionIdRef = useRef(null)

  const send = useCallback((text, electronFileInfo) => {
    if (!text.trim() || isStreaming) return

    setError(null)
    setObservabilityData({})

    // Build user message, including Electron file path if present
    const displayFile = file?.name || electronFileInfo?.electronFileName
    const displayPath = file?.webkitRelativePath || file?.name || electronFileInfo?.electronFilePath

    const userMsg = {
      id: Date.now(), role: 'user', content: text,
      file: displayFile, filePath: displayPath, fileSize: file?.size,
    }
    const assistantId = Date.now() + 1
    const assistantMsg = {
      id: assistantId, role: 'assistant', content: '',
      pending: true, thinking: '', thinkMs: 0, isAgent: false, toolSteps: [],
      confirmation: null,  // {path, content, filename} when file_write awaits user approval
    }

    setMessages((prev) => [...prev, userMsg, assistantMsg])
    streamingIdRef.current = assistantId
    thinkStartRef.current  = Date.now()
    sentSessionIdRef.current = sessionId  // FIX: track so App can read fresh value
    setIsStreaming(true)

    const currentFile = file
    setFile(null)

    const abort = streamChat({
      message: text,
      sessionId,
      file: currentFile,
      electronFilePath: electronFileInfo?.electronFilePath || null,

      onThinking: (content) => {
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== streamingIdRef.current) return m
            const nowMs = Date.now() - (thinkStartRef.current || Date.now())
            return { ...m, thinking: (m.thinking || '') + content, thinkMs: nowMs, isAgent: true }
          })
        )
      },

      onToolStatus: ({ tool, label, status }) => {
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== streamingIdRef.current) return m
            const idx = m.toolSteps.findIndex(s => s.action === tool)
            if (idx >= 0) {
              const updated = m.toolSteps.map((s, i) => i === idx ? { ...s, status } : s)
              return { ...m, toolSteps: updated }
            }
            return { ...m, toolSteps: [...m.toolSteps, { action: tool, input: label, status }] }
          })
        )
      },

      onChunk: (chunk) => {
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== streamingIdRef.current) return m

            // ### Action: header → new tool step (agent loop marker)
            if (chunk.includes('### Action:')) {
              const actionName = chunk
                .replace(/[\s\S]*### Action:\s*`?/, '')
                .replace(/`?\n[\s\S]*/, '')
                .trim()
              return {
                ...m,
                toolSteps: [...m.toolSteps, { action: actionName, input: '', status: 'running' }],
              }
            }

            // ### Reasoning header — skip, content follows in next chunks
            if (chunk.startsWith('\n### Reasoning') || chunk === '\n### Reasoning\n') {
              return m
            }

            // Thinking chunk: *{text}*\n\n — strict detection, not loose *-contains
            if (isThinkingChunk(chunk)) {
              const text = extractThinking(chunk)
              const nowMs = Date.now() - (thinkStartRef.current || Date.now())
              return { ...m, thinking: (m.thinking || '') + text, thinkMs: nowMs }
            }

            // Mark last running tool step as done when real content arrives
            const updatedSteps = m.toolSteps.map((s, i) =>
              i === m.toolSteps.length - 1 && s.status === 'running'
                ? { ...s, status: 'done' }
                : s
            )

            return { ...m, content: m.content + chunk, pending: true, toolSteps: updatedSteps }
          })
        )
      },

      onDiff: (diffData) => {
        // Attach structured diff data to the current assistant message
        // so the DiffBlock component can render green/red highlighted diffs.
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== streamingIdRef.current) return m
            return {
              ...m,
              diffData: {
                hunks: diffData.hunks || [],
                language: diffData.language || '',
                filePath: diffData.filePath || '',
                additions: diffData.additions || 0,
                deletions: diffData.deletions || 0,
              },
            }
          })
        )
      },

      onIntent: (intentData) => {
        setObservabilityData(prev => ({
          ...prev,
          intent: intentData.intent,
          confidence: intentData.confidence,
        }))
        // Mark message as agent-mode: true for both agent loop intents
        // AND direct-stream intents that emit thinking_start obs events.
        const isAgent = AGENT_INTENTS.has(intentData.intent) || THINKING_INTENTS.has(intentData.intent)
        setMessages((prev) =>
          prev.map((m) =>
            m.id === streamingIdRef.current ? { ...m, isAgent } : m
          )
        )
      },

      onObsEvent: (event) => {
        // thinking_start/done: set synthetic thinking text for direct-stream turns
        if (event.type === 'thinking_start') {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === streamingIdRef.current
                ? { ...m, thinking: 'Thinking\u2026', isAgent: true }
                : m
            )
          )
          return
        }
        if (event.type === 'thinking_done') {
          // Clear thinking text once response starts streaming
          // (ThinkingBlock will collapse and show duration)
          return
        }
        setObservabilityData(prev => {
          const updated = { ...prev }
          switch (event.type) {
            case 'tool_dispatched':
              updated.toolCalls = [...(prev.toolCalls || []), {
                name: event.data.tool,
                success: event.data.success,
                latency: event.data.latency_ms,
              }]
              break
            case 'memory_retrieved':
              updated.memoryHits = event.data.facts || []
              break
            case 'turn_complete':
              updated.latency = event.data.total_latency_ms
              updated.tokens  = event.data.tokens_approx
              break
          }
          return updated
        })
      },

      onConfirmation: (payload) => {
        // Attach the pending write payload to the assistant message.
        // MessageList renders Accept/Reject buttons when msg.confirmation is set.
        setMessages((prev) =>
          prev.map((m) =>
            m.id === streamingIdRef.current
              ? { ...m, confirmation: payload, pending: false }
              : m
          )
        )
      },

      onError: (err) => {
        setError(err)
        setMessages((prev) =>
          prev.map((m) =>
            m.id === streamingIdRef.current
              ? { ...m, content: `Error: ${err}`, pending: false, error: true }
              : m
          )
        )
      },

      onDone: () => {
        const elapsed = Date.now() - (thinkStartRef.current || Date.now())
        setMessages((prev) =>
          prev.map((m) =>
            m.id === streamingIdRef.current
              ? { ...m, pending: false, thinkMs: m.thinkMs || elapsed }
              : m
          )
        )
        setIsStreaming(false)
        streamingIdRef.current = null
        abortRef.current = null
      },
    })

    abortRef.current = abort
  }, [isStreaming, sessionId, file])

  const reset = useCallback(() => {
    if (abortRef.current) abortRef.current()
    setMessages([])
    const newId = newSessionId()
    setSessionId(newId)
    lastLoadedSessionRef.current = null  // FIX: reset loaded session tracking
    setIsStreaming(false)
    setError(null)
    setFile(null)
    setObservabilityData({})
    return newId
  }, [])

  const cancelStream = useCallback(() => {
    if (abortRef.current) {
      abortRef.current()
      setIsStreaming(false)
      setMessages((prev) =>
        prev.map((m) =>
          m.id === streamingIdRef.current ? { ...m, pending: false } : m
        )
      )
    }
  }, [])

  // Called by Accept/Reject buttons in MessageList.
  // accept=true  → sends "yes" to the engine, which resumes _do_write.
  // accept=false → sends "no" to cancel, clears the confirmation message.
  //
  // FIX: isStreaming is still true when confirmation buttons render (the stream
  // is paused waiting for user input). send() bails if isStreaming===true, so
  // confirmation sends were silently dropped. Fix: clear isStreaming first,
  // then send — the backend will re-stream after receiving the confirmation.
  const confirm = useCallback((messageId, accept) => {
    // Clear the confirmation widget from the message
    setMessages((prev) =>
      prev.map((m) =>
        m.id === messageId ? { ...m, confirmation: null } : m
      )
    )
    // Clear streaming state so send() doesn't bail
    setIsStreaming(false)
    streamingIdRef.current = null
    if (accept) {
      send('yes')
    } else {
      send('no')
    }
  }, [send])

  // FIX: expose clearError so App.jsx can wire ErrorBanner dismiss
  const clearError = useCallback(() => setError(null), [])

  return {
    messages, sessionId, isStreaming, error, file, setFile,
    send, reset, cancelStream, observabilityData, confirm, clearError,
    // FIX: expose ref so App.jsx handleSend reads the current (not stale) session ID
    sentSessionIdRef,
  }
}
