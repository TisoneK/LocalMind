/**
 * LocalMind React Hooks — v0.6
 * Custom hooks that wrap the LocalMind API client for use in components.
 * Updated to parse the redesigned SSE format from the Python backend.
 *
 * v0.6 fixes:
 * - FIX 1: Filter agent prompt leaks from token stream (planning text, system instructions)
 * - FIX 3: Populate actions panel from live tool_call SSE events (no empty actions)
 * - FIX 5: Stream tokens incrementally to chat — no more static 'Generating response...'
 * - FIX 7: Step-by-step narration updates during agent execution
 *
 * All hooks talk directly to the Python FastAPI backend via localmindClient.
 * No Prisma, no Next.js BFF routes needed.
 */

'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { localmindClient } from '@/lib/localmind/client';
import type {
  ChatMessage,
  Session,
  ActionItem,
  TodoItem,
  FileNode,
  TerminalLine,
  MemoryFact,
  PerformanceMetrics,
  ObservationData,
  ModelOption,
  ToolCall,
  ThinkingStep,
  CompletionSuggestion,
} from '@/types';

// ─── useHealth ─────────────────────────────────────────────────────────

interface HealthState {
  status: 'online' | 'offline' | 'checking';
  version?: string;
  uptime?: number;
}

export function useHealth(intervalMs = 30000) {  // 30s - reduced polling to save data
  const [health, setHealth] = useState<HealthState>({ status: 'checking' });

  useEffect(() => {
    let mounted = true;

    const check = async () => {
      try {
        const res = await localmindClient.getHealth();
        if (mounted) {
          setHealth({
            status: res.status === 'ok' ? 'online' : 'offline',
            version: res.version,
            uptime: res.uptime,
          });
        }
      } catch {
        if (mounted) {
          setHealth({ status: 'offline' });
        }
      }
    };

    check();
    const id = setInterval(check, intervalMs);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, [intervalMs]);

  return health;
}

// ─── useSessions ───────────────────────────────────────────────────────

export function useSessions() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await localmindClient.getSessions();
      // Defensive: ensure sessions is always an array
      setSessions(Array.isArray(data) ? data : []);
    } catch {
      // Keep previous data (which is always [] initially)
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const deleteSession = useCallback(
    async (sessionId: string) => {
      await localmindClient.deleteSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
    },
    []
  );

  return { sessions, loading, refresh, deleteSession };
}

// ─── useChat ───────────────────────────────────────────────────────────

interface TerminalEventData {
  tool: string;
  command: string;
  output: string;
  success: boolean;
  latencyMs: number;
  label?: string;
  toolArgs?: string;
}

interface ChatState {
  messages: ChatMessage[];
  isStreaming: boolean;
  currentIntent?: string;
  currentConfidence?: number;
  activeToolCalls: ToolCall[];
  liveObservation: ObservationData | null;
  lastMetrics: PerformanceMetrics | null;
  send: (message: string, sessionIdOverride?: string, tool?: string) => void;
  abort: () => void;
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  onTerminalEvent?: (event: TerminalEventData) => void;
}

export function useChat(
  sessionId: string | null,
  onTerminalEvent?: (event: TerminalEventData) => void
): ChatState {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [currentIntent, setCurrentIntent] = useState<string | undefined>();
  const [currentConfidence, setCurrentConfidence] = useState<number | undefined>();
  const [activeToolCalls, setActiveToolCalls] = useState<ToolCall[]>([]);
  const [liveObservation, setLiveObservation] = useState<ObservationData | null>(null);
  const [lastMetrics, setLastMetrics] = useState<PerformanceMetrics | null>(null);
  const abortRef = useRef<(() => void) | null>(null);

  const prevSessionIdRef = useRef<string | null>(null);
  const isStreamingRef = useRef(false);
  // Track the sessionId we're currently streaming to so the history effect
  // can skip loading — the messages are already in local state.
  // Cleared in onDone/onError so subsequent session switches load correctly.
  const streamingSessionRef = useRef<string | null>(null);

  // Keep refs in sync with state so callbacks can read fresh values
  // without needing them as useCallback dependencies (avoids stale closures).
  useEffect(() => {
    isStreamingRef.current = isStreaming;
  }, [isStreaming]);

  // FIX: Auto-timeout for stuck tool calls. If a tool_call stays in "running"
  // status for more than 60 seconds, mark it as "done" — the backend likely
  // completed without sending a tool_result event. This prevents infinite spinners.
  useEffect(() => {
    const running = activeToolCalls.filter((tc) => tc.status === 'running');
    if (running.length === 0) return;
    const timer = setTimeout(() => {
      setActiveToolCalls((prev) => {
        const hasStuck = prev.some((tc) => tc.status === 'running');
        if (!hasStuck) return prev;
        return prev.map((tc) =>
          tc.status === 'running'
            ? { ...tc, status: 'done' as const, duration: tc.duration || 60000 }
            : tc
        );
      });
    }, 60000);
    return () => clearTimeout(timer);
  }, [activeToolCalls]);

  // Load history only when sessionId changes, not on every isStreaming change.
  // This prevents the race condition where streaming completes and history fetch
  // overwrites the messages that are already in local state.
  // FIX: Also skip if we're currently streaming to this session — this guards
  // against the history fetch from wiping the in-flight messages on first turn.
  // FIX 2: Guard against React StrictMode double-mount: on the second mount
  // (before send() runs), isStreamingRef.current is still false, so we check
  // if the sessionId is fresh (was just set, indicating a send is pending).
  // We skip in that case too to avoid loadHistory() clearing messages.
  useEffect(() => {
    let mounted = true;

    const loadHistory = async () => {
      if (!sessionId) {
        if (mounted) {
          setMessages([]);
          setLiveObservation(null);
          setCurrentIntent(undefined);
          setCurrentConfidence(undefined);
          setActiveToolCalls([]);
        }
        return;
      }
      // Clear stale data from the previous session immediately so the
      // Observe/Actions panels don't show the old session's data while
      // the new history loads.
      if (prevSessionIdRef.current && prevSessionIdRef.current !== sessionId) {
        setLiveObservation(null);
        setCurrentIntent(undefined);
        setCurrentConfidence(undefined);
        setActiveToolCalls([]);
      }
      // Skip if we're actively streaming to this session — the messages
      // are already in local state and the DB may not have them yet.
      if (streamingSessionRef.current === sessionId) {
        return;
      }
      // Skip if the sessionId was just created (handleSend just called
      // setCurrentSessionId but send() hasn't run yet). This catches the
      // StrictMode double-mount.
      if (prevSessionIdRef.current === null && sessionId) {
        return;
      }
      // Skip if we just sent a message to this session — the stream is
      // pending and the in-flight messages are already in state.
      if (prevSessionIdRef.current === sessionId && isStreamingRef.current) {
        return;
      }
      const history = await localmindClient.getSessionHistory(sessionId);
      if (mounted) {
        setMessages(history);
      }
    };

    if (prevSessionIdRef.current !== sessionId) {
      prevSessionIdRef.current = sessionId;
    }

    loadHistory();

    return () => {
      mounted = false;
    };
  }, [sessionId]);

  const send = useCallback(
    (message: string, sessionIdOverride?: string, tool?: string) => {
      // Use the override (passed by handleSend when creating a new session)
      // so we never see sessionId===null on the first message.
      const effectiveSessionId = sessionIdOverride ?? sessionId;
      if (!effectiveSessionId || isStreamingRef.current) return;

      // Track the session being streamed so the history effect skips loading.
      streamingSessionRef.current = effectiveSessionId;

      const userMsg: ChatMessage = {
        id: `user-${Date.now()}`,
        role: 'user',
        content: message,
        timestamp: new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false }),
      };

      const assistantMsg: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: '',
        timestamp: new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false }),
        toolCalls: [],
      };

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setIsStreaming(true);
      setActiveToolCalls([]);
      setLiveObservation(null);

      let currentContent = '';
      let thinkingContent = '';
      let thinkStartTime = 0;
      const toolCalls: ToolCall[] = [];
      const toolsUsedSet = new Set<string>();

      const abortFn = localmindClient.streamChat(
        message,
        effectiveSessionId,
        // onChunk — parse structured SSE events
        (rawData: string) => {
          try {
            const parsed = JSON.parse(rawData);
            const eventType = parsed.type;

            switch (eventType) {
              case 'token': {
                const token = parsed.content || '';
                // FIX 1: Filter leaked agent planning/system prompt text from token stream.
                // The agent loop sometimes emits planning text or system prompt
                // fragments as tokens. These confuse users — they see internal
                // instructions like "UNDERSTANDING:" or "EXECUTION PLAN —".
                // We detect and suppress these leaked fragments.
                if (_isPromptLeak(token)) {
                  break;
                }
                // FIX 5: Stream tokens incrementally — the message content updates
                // in real-time so the user sees each token as it arrives, replacing
                // the static "Generating response..." indicator.
                currentContent += token;
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last && last.role === 'assistant') {
                    updated[updated.length - 1] = { ...last, content: currentContent };
                  }
                  return updated;
                });
                break;
              }

              case 'thinking_start': {
                thinkingContent = '';
                thinkStartTime = Date.now();
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last && last.role === 'assistant') {
                    updated[updated.length - 1] = { ...last, isAgent: true };
                  }
                  return updated;
                });
                break;
              }

              case 'thinking_token': {
                thinkingContent += parsed.thinking || parsed.content || '';
                const thinkMs = thinkStartTime ? Date.now() - thinkStartTime : 0;
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last && last.role === 'assistant') {
                    updated[updated.length - 1] = { ...last, thinking: thinkingContent, thinkMs, isAgent: true };
                  }
                  return updated;
                });
                break;
              }

              case 'thinking_end': {
                if (thinkingContent) {
                  const thinkMs = thinkStartTime ? Date.now() - thinkStartTime : 0;
                  setMessages((prev) => {
                    const updated = [...prev];
                    const last = updated[updated.length - 1];
                    if (last && last.role === 'assistant') {
                      updated[updated.length - 1] = { ...last, thinking: thinkingContent, thinkMs, isAgent: true };
                    }
                    return updated;
                  });
                }
                break;
              }

              case 'tool_call': {
                const tc = parsed.tool_call || parsed;
                // Dispatch event so RightPanel can auto-switch to the Observe tab
                window.dispatchEvent(new CustomEvent('localmind:tool-call-started'));
                // FIX 2: Build human-readable label from tool_args if LLM didn't provide one.
                // This replaces raw tool names like "file_write" with descriptions
                // like "Creating hello world script" in Task Progress.
                const toolLabel = tc.label || _buildToolLabel(tc.name || tc.tool || 'unknown', tc.arguments || tc.input);
                const toolCall: ToolCall = {
                  id: tc.id || `tc-${Date.now()}-${toolCalls.length}`,
                  name: tc.name || tc.tool || 'unknown',
                  label: toolLabel,
                  status: tc.status || 'running',
                  input: _buildToolInputPreview(tc.name || tc.tool || 'unknown', tc.arguments || tc.input),
                  output: tc.output,
                  duration: tc.duration || (tc.latency_ms ? parseInt(tc.latency_ms) : undefined),
                  timestamp: new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false }),
                };
                // Deduplicate by ID: if a tool_call with the same ID already
                // exists, UPDATE it (e.g. status changed from "started" to
                // "done") instead of appending a duplicate entry.
                let existingIdx = toolCalls.findIndex((existing) => existing.id === toolCall.id);
                if (existingIdx !== -1) {
                  toolCalls[existingIdx] = { ...toolCalls[existingIdx], ...toolCall };
                } else if (toolCall.status === 'done' || toolCall.status === 'failed') {
                  // FIX: Fallback dedup — when a "done" event arrives with a
                  // different ID (backend sometimes uses different IDs for
                  // started vs done events), find the RUNNING tool call with
                  // the same NAME and update it. This prevents duplicate
                  // entries where the "running" one stays spinning forever.
                  const runningIdx = toolCalls.findIndex(
                    (existing) => existing.name === toolCall.name && existing.status === 'running'
                  );
                  if (runningIdx !== -1) {
                    toolCalls[runningIdx] = { ...toolCalls[runningIdx], ...toolCall, id: toolCalls[runningIdx].id };
                    existingIdx = runningIdx;
                  } else {
                    toolCalls.push(toolCall);
                    toolsUsedSet.add(toolCall.name);
                  }
                } else {
                  toolCalls.push(toolCall);
                  toolsUsedSet.add(toolCall.name);
                }
                setActiveToolCalls([...toolCalls]);
                setLiveObservation((prev) => ({
                  intent: _toolToIntent(toolCall.name, prev?.intent || currentIntent || 'chat') as any,
                  confidence: prev?.confidence ?? currentConfidence ?? 0,
                  toolsUsed: [...toolsUsedSet],
                  memoryHits: prev?.memoryHits ?? 0,
                  contextTokens: prev?.contextTokens ?? 0,
                  latency: prev?.latency ?? 0,
                }));
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last && last.role === 'assistant') {
                    updated[updated.length - 1] = { ...last, toolCalls: [...toolCalls] };
                  }
                  return updated;
                });
                break;
              }

              case 'tool_result': {
                const tr = parsed.tool_result || parsed;
                const idx = toolCalls.findIndex(
                  (tc) => tc.name === (tr.name || tr.tool) && tc.status === 'running'
                );
                if (idx !== -1) {
                  toolCalls[idx] = {
                    ...toolCalls[idx],
                    status: tr.status || (tr.error ? 'failed' : 'done'),
                    output: tr.output || tr.result || '',
                    duration: tr.duration,
                  };
                } else {
                  const toolCall: ToolCall = {
                    id: tr.id || `tc-${Date.now()}-${toolCalls.length}`,
                    name: tr.name || tr.tool || 'unknown',
                    status: tr.status || 'done',
                    input: '',
                    output: tr.output || tr.result || '',
                    duration: tr.duration,
                  };
                  toolCalls.push(toolCall);
                  toolsUsedSet.add(toolCall.name);
                }
                setActiveToolCalls([...toolCalls]);
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last && last.role === 'assistant') {
                    updated[updated.length - 1] = { ...last, toolCalls: [...toolCalls] };
                  }
                  return updated;
                });
                break;
              }

              case 'intent': {
                setCurrentIntent(parsed.intent);
                if (parsed.confidence) setCurrentConfidence(parsed.confidence);
                setLiveObservation((prev) => ({
                  intent: (parsed.intent || prev?.intent || 'chat') as any,
                  confidence: parsed.confidence ?? prev?.confidence ?? 0,
                  toolsUsed: prev?.toolsUsed ?? [],
                  memoryHits: prev?.memoryHits ?? 0,
                  contextTokens: prev?.contextTokens ?? 0,
                  latency: prev?.latency ?? 0,
                }));
                break;
              }

              case 'obs_event': {
                const obs = parsed.obs_event || parsed;
                if (obs.intent) setCurrentIntent(obs.intent);
                if (obs.confidence) setCurrentConfidence(obs.confidence);
                // Update live observation from obs_event data
                const obsData = obs.data || obs;
                if (obsData) {
                  setLiveObservation((prev) => ({
                    intent: (obsData.intent || obs.intent || prev?.intent || 'chat') as any,
                    confidence: Number(obsData.confidence || obs.confidence || prev?.confidence || 0),
                    toolsUsed: obsData.tools_used ? obsData.tools_used.split(',') : (prev?.toolsUsed ?? []),
                    // Backend sends 'memory_facts' in turn_complete, not 'memory_hits'
                    memoryHits: Number(obsData.memory_facts || obsData.memory_hits || prev?.memoryHits || 0),
                    contextTokens: Number(obsData.tokens_approx || obsData.context_tokens || prev?.contextTokens || 0),
                    latency: Number(obsData.total_latency_ms || obsData.latency_ms || obsData.latency || prev?.latency || 0),
                  }));
                  // FIX: When tool_status=done obs event arrives, mark matching
                  // tool calls as done in the frontend. This fixes the stuck
                  // "Running command" spinner when the top-level intent completes.
                  if (obs.type === 'tool_status' && obsData.status === 'done') {
                    const doneTool = obsData.tool || '';
                    if (doneTool) {
                      setActiveToolCalls((prev) => {
                        const hasRunning = prev.some((tc) => tc.name === doneTool && tc.status === 'running');
                        if (!hasRunning) return prev;
                        return prev.map((tc) =>
                          tc.name === doneTool && tc.status === 'running'
                            ? { ...tc, status: 'done' as const, duration: tc.duration || 0 }
                            : tc
                        );
                      });
                    }
                  }
                  // Extract real-time metrics from turn_complete obs events.
                  // The backend fires turn_complete AFTER record_streaming_complete(),
                  // so tokens_approx and total_latency_ms are accurate. This gives
                  // instant metrics without waiting for the polling interval.
                  if (obs.type === 'turn_complete' || (obsData && obsData.total_latency_ms)) {
                    const _tokens = Number(obsData.tokens_approx || 0);
                    const _promptTokens = Number(obsData.prompt_tokens_approx || obsData.prompt_tokens || 0);
                    const _latency = Number(obsData.total_latency_ms || obsData.latency_ms || 0);
                    if (_tokens > 0 || _latency > 0) {
                      const _elapsed_s = _latency / 1000;
                      // tokens_approx is the RESPONSE (completion) token count.
                      // prompt_tokens_approx is set by the backend when available.
                      // If not provided by backend, estimate prompt tokens from
                      // context_tokens as a rough approximation.
                      const _completionTokens = _tokens;
                      const _estimatedPrompt = _promptTokens > 0
                        ? _promptTokens
                        : Number(obsData.context_tokens || 0) > 0
                          ? Number(obsData.context_tokens)
                          : 0;
                      setLastMetrics({
                        tokensPerSecond: _elapsed_s > 0 ? Math.round(_tokens / _elapsed_s * 100) / 100 : 0,
                        latency: _latency,
                        totalTokens: _tokens + _estimatedPrompt,
                        promptTokens: _estimatedPrompt,
                        completionTokens: _completionTokens,
                      });
                    }
                  }
                }
                break;
              }

              case 'done': {
                // Mark ALL running tool calls as done — the response is complete
                if (toolCalls.length > 0) {
                  const hasRunning = toolCalls.some(tc => tc.status === 'running');
                  if (hasRunning) {
                    for (let i = 0; i < toolCalls.length; i++) {
                      if (toolCalls[i].status === 'running') {
                        toolCalls[i] = { ...toolCalls[i], status: 'done' as const, duration: toolCalls[i].duration || 0 };
                      }
                    }
                    setActiveToolCalls([...toolCalls]);
                  }
                }
                if (parsed.file_path) {
                  setMessages((prev) => {
                    const updated = [...prev];
                    const last = updated[updated.length - 1];
                    if (last && last.role === 'assistant') {
                      const fileResult = {
                        id: `fr-${Date.now()}`,
                        filename: parsed.file_name || '',
                        path: parsed.file_path,
                        status: 'created' as const,
                      };
                      updated[updated.length - 1] = {
                        ...last,
                        fileResults: [...(last.fileResults || []), fileResult],
                      };
                    }
                    return updated;
                  });
                }
                break;
              }

              case 'error': {
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last && last.role === 'assistant' && !last.content) {
                    updated[updated.length - 1] = {
                      ...last,
                      content: `⚠️ ${parsed.error || 'Failed to get a response.'}`,
                    };
                  }
                  return updated;
                });
                break;
              }

              case 'metrics': {
                const m = parsed.metrics || {};
                const _tokens = Number(m.tokens_approx || 0);
                const _promptTokens = Number(m.prompt_tokens_approx || 0);
                const _latency = Number(m.total_latency_ms || 0);
                if (_tokens > 0 || _latency > 0) {
                  const _elapsed_s = _latency / 1000;
                  setLastMetrics({
                    tokensPerSecond: _elapsed_s > 0 ? Math.round(_tokens / _elapsed_s * 100) / 100 : 0,
                    latency: _latency,
                    totalTokens: _tokens + _promptTokens,
                    promptTokens: _promptTokens,
                    completionTokens: _tokens,
                  });
                }
                break;
              }

              case 'terminal_event': {
                const termEvt = parsed.terminal_event || parsed;
                if (onTerminalEvent && termEvt) {
                  onTerminalEvent({
                    tool: termEvt.tool || 'shell',
                    command: termEvt.command || '',
                    output: termEvt.output || '',
                    success: termEvt.success !== false,
                    latencyMs: termEvt.latencyMs || 0,
                    label: termEvt.label || '',
                    toolArgs: termEvt.toolArgs || '',
                  });
                }
                // Also update the active tool call status when terminal completes
                if (termEvt.tool) {
                  const idx = toolCalls.findIndex(
                    (tc) => tc.name === termEvt.tool && tc.status === 'running'
                  );
                  if (idx !== -1) {
                    toolCalls[idx] = {
                      ...toolCalls[idx],
                      status: termEvt.success !== false ? 'done' : 'failed',
                      output: termEvt.output || '',
                      duration: termEvt.latencyMs,
                    };
                    setActiveToolCalls([...toolCalls]);
                    setMessages((prev) => {
                      const updated = [...prev];
                      const last = updated[updated.length - 1];
                      if (last && last.role === 'assistant') {
                        updated[updated.length - 1] = { ...last, toolCalls: [...toolCalls] };
                      }
                      return updated;
                    });
                  }
                }
                break;
              }

              case 'status_update': {
                // v0.10: Real-time progress feedback during tool execution.
                // The backend emits status_update SSE events during long-running
                // operations (e.g., "Searching the web...", "Planning steps...",
                // "Fetching weather data for Cheptais..."). We show these as
                // real-time status text in the message's thinking area so the
                // user isn't staring at a blank "Thinking..." indicator.
                const statusText = parsed.status || '';
                if (statusText) {
                  const statusMs = thinkStartTime ? Date.now() - thinkStartTime : 0;
                  setMessages((prev) => {
                    const updated = [...prev];
                    const last = updated[updated.length - 1];
                    if (last && last.role === 'assistant') {
                      updated[updated.length - 1] = {
                        ...last,
                        thinking: statusText,
                        thinkMs: statusMs,
                        isAgent: true,
                      };
                    }
                    return updated;
                  });
                }
                break;
              }

              default:
                if (parsed.content && !_isPromptLeak(parsed.content)) {
                  currentContent += parsed.content;
                  setMessages((prev) => {
                    const updated = [...prev];
                    const last = updated[updated.length - 1];
                    if (last && last.role === 'assistant') {
                      updated[updated.length - 1] = { ...last, content: currentContent };
                    }
                    return updated;
                  });
                }
            }
          } catch {
            if (rawData && rawData !== "[DONE]" && !_isPromptLeak(rawData)) {
              const trimmedRaw = rawData.trim();
              if (trimmedRaw.startsWith("<invoke") || trimmedRaw.startsWith("</invoke") || trimmedRaw.startsWith("[invoke") || trimmedRaw.startsWith("[/invoke")) {
                return;
              }
              currentContent += rawData;
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last && last.role === "assistant") {
                  updated[updated.length - 1] = { ...last, content: currentContent };
                }
                return updated;
              });
            }
          }
        },
        () => {
          setIsStreaming(false);
          streamingSessionRef.current = null;
          abortRef.current = null;
          // Mark any remaining running tool calls as done.
          // NOTE: Compute the updated list first, then call both setters
          // sequentially. Calling setMessages *inside* the setActiveToolCalls
          // updater is a React anti-pattern that double-fires under StrictMode.
          let didUpdate = false;
          const updatedToolCalls: ToolCall[] = [];
          setActiveToolCalls((prev) => {
            const hasRunning = prev.some((tc) => tc.status === 'running');
            if (!hasRunning) return prev;
            const mapped = prev.map((tc) =>
              tc.status === 'running'
                ? { ...tc, status: 'done' as const, duration: tc.duration || 0 }
                : tc
            );
            updatedToolCalls.push(...mapped);
            didUpdate = true;
            return mapped;
          });
          // Sync the message's toolCalls array too (outside the updater)
          if (didUpdate && updatedToolCalls.length > 0) {
            setMessages((prevMsgs) => {
              const msgs = [...prevMsgs];
              const last = msgs[msgs.length - 1];
              if (last && last.role === 'assistant' && last.toolCalls) {
                const updatedMap = new Map(updatedToolCalls.map(tc => [tc.id, tc]));
                msgs[msgs.length - 1] = {
                  ...last,
                  toolCalls: last.toolCalls.map(tc => updatedMap.get(tc.id) || tc),
                };
              }
              return msgs;
            });
          }
        },
        // onError
        () => {
          setIsStreaming(false);
          streamingSessionRef.current = null;
          abortRef.current = null;
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last && last.role === 'assistant' && !last.content) {
              updated[updated.length - 1] = {
                ...last,
                content: '⚠️ Failed to get a response. Please check that the backend is running.',
              };
            }
            return updated;
          });
        },
        // toolHint — passed as X-LocalMind-Intent header
        tool
      );

      abortRef.current = abortFn;
    },
    [sessionId]  // isStreaming is read via isStreamingRef to avoid stale closures
  );

  const abort = useCallback(() => {
    abortRef.current?.();
    abortRef.current = null;
    streamingSessionRef.current = null;
    setIsStreaming(false);
    // Mark any running tool calls as done on abort
    setActiveToolCalls((prev) => {
      const hasRunning = prev.some((tc) => tc.status === 'running');
      if (!hasRunning) return prev;
      return prev.map((tc) =>
        tc.status === 'running'
          ? { ...tc, status: 'done' as const, duration: tc.duration || 0 }
          : tc
      );
    });
  }, []);

  return { messages, isStreaming, currentIntent, currentConfidence, activeToolCalls, liveObservation, lastMetrics, send, abort, setMessages, onTerminalEvent };
}

// ─── Prompt leak detection (FIX 1) ────────────────────────────────────
// Patterns that indicate a leaked system prompt or planning fragment.
// These appear when the agent loop accidentally streams planning text
// or system instructions to the user instead of keeping them internal.
// Map tool names to intent categories for the observation panel
function _toolToIntent(toolName: string, fallback: string = 'chat'): string {
  const map: Record<string, string> = {
    web_search: 'search',
    shell: 'shell',
    code_exec: 'code',
    file_write: 'file',
    file_task: 'file',
    file_read: 'file',
    memory_op: 'memory',
    sysinfo: 'chat',
    edit_file: 'file',
    grep: 'search',
  };
  return map[toolName] || fallback;
}

const _PROMPT_LEAK_PATTERNS = [
  /^EXECUTION PLAN/,              // Planning output header
  /^UNDERSTANDING:/,              // Planning understanding section
  /^STEPS:/,                      // Planning steps section
  /^ARGS_PRECHECK:/,              // Planning args precheck
  /^CRITICAL SAFETY RULES:/,      // System prompt header
  /^TOOL ARGUMENT RULES/,         // System prompt rules
  /^VERIFICATION —/,             // System prompt verification
  /^Current intent:/,            // System prompt context
  /^Max iterations:/,            // System prompt context
  /^You are LocalMind/,          // System prompt identity
  /^Available tools:/,           // System prompt tool list
  /^FILE_WRITE WORKFLOW/,         // Intent template
  /^FILE_EDIT WORKFLOW/,          // Intent template
  /^CODE_EXEC WORKFLOW/,          // Intent template
  /^MEMORY_OP WORKFLOW/,          // Intent template
  /^SHELL TOOL GUIDANCE/,         // Shell guidance
  /^\[TOOL_CALL\]\s*<invoke/,     // Raw tool call: minimax format (first token)
  /^\[TOOL_CALL\]/,              // Raw tool call: bracket tag (streaming leak after first token)
  /^\[tool\s*=>/,                // Raw tool call: old bracket format
  /^<invoke\s+name=/,            // Raw tool call: XML open tag streaming
  /^\s*<\/invoke>\s*<\/minimax:tool_call>/, // Raw tool call: XML close tag streaming
  /^<invoke\s+name=["']tool/,   // Streaming tool call with tool name hint
  /^\[invoke/,                    // Streaming: generic invoke bracket
  /^\[\/invoke/,                   // Streaming: generic /invoke bracket
  /^\(Not entirely sure/,          // v0.5: Uncertainty prefix that models emit
  /^Not entirely sure/,            // v0.5: Uncertainty prefix without parens
  /^PART\s+1/,                     // v0.5: Chat Agent structured output markers
  /^PART\s+2/,                     // v0.5: Chat Agent structured output markers
  /^ACKNOWLEDGE/,                  // v0.5: Chat Agent label
  /^REFORMULATED INSTRUCTION/,     // v0.5: Chat Agent label
];


function _isPromptLeak(token: string): boolean {
  if (!token || token.length < 3) return false;
  const trimmed = token.trim();
  // Check line-start patterns
  if (_PROMPT_LEAK_PATTERNS.some(p => p.test(trimmed))) return true;
  // v0.5: Also filter "(Not entirely sure...)" that appears mid-line
  // (e.g. at the start of a longer token that doesn't start with it)
  if (/\(Not entirely sure[^)]*\)\s*/i.test(trimmed)) return true;
  if (/Not entirely sure[^.]*\.\s*/i.test(trimmed)) return true;
  return false;
}

// ─── Tool label builder (FIX 2) ───────────────────────────────────────
// Builds human-readable labels from tool name + args for Task Progress
// and ToolSteps display. Falls back to a cleaned-up tool name.

const TOOL_LABELS: Record<string, string> = {
  file_write: 'Creating file',
  file_read: 'Reading file',
  file_task: 'Reading file',
  edit_file: 'Editing file',
  code_exec: 'Running code',
  shell: 'Executing command',
  memory_op: 'Memory operation',
  web_search: 'Searching the web',
  sysinfo: 'Getting system info',
};

function _buildToolLabel(toolName: string, args: any): string {
  // Try to extract a descriptive label from structured args
  if (args && typeof args === 'object') {
    const path = args.path || '';
    const command = args.command || '';
    const query = args.query || '';
    const code = (args.code || '').slice(0, 30);
    const operation = args.operation || '';
    switch (toolName) {
      case 'file_write': return path ? `Creating ${path.split(/[\/\\]/).pop()}` : 'Creating file';
      case 'file_task': return path ? `Reading ${path.split(/[\/\\]/).pop()}` : 'Reading file';
      case 'edit_file': return path ? `Editing ${path.split(/[\/\\]/).pop()}` : 'Editing file';
      case 'shell': return command ? `Running: ${command.slice(0, 60)}` : 'Executing command';
      case 'code_exec': return code ? `Executing: ${code}...` : 'Running code';
      case 'web_search': return query ? `Searching: ${query.slice(0, 60)}` : 'Searching the web';
      case 'memory_op': return operation ? `${operation.charAt(0).toUpperCase() + operation.slice(1)} fact` : 'Memory operation';
      case 'sysinfo': return query ? `System: ${query.slice(0, 30)}` : 'Getting system info';
    }
  }
  // If args is a string, try to extract useful info
  if (typeof args === 'string' && args.length > 0) {
    const preview = args.slice(0, 50);
    return `${TOOL_LABELS[toolName] || toolName}: ${preview}`;
  }
  return TOOL_LABELS[toolName] || toolName.replace(/_/g, ' ');
}

function _buildToolInputPreview(toolName: string, args: any): string {
  if (args && typeof args === 'object') {
    switch (toolName) {
      case 'file_write': return args.path || '';
      case 'file_task': return args.path || '';
      case 'edit_file': return args.path || '';
      case 'shell': return args.command || '';
      case 'code_exec': return (args.code || '').slice(0, 80);
      case 'web_search': return args.query || '';
      case 'memory_op': return `${args.operation || ''} ${args.content || ''}`.trim();
      case 'sysinfo': return args.query || '';
    }
  }
  if (typeof args === 'string') return args.slice(0, 80);
  return '';
}

// ─── useActions ────────────────────────────────────────────────────────

export function useActions(sessionId: string | null) {
  const [actions, setActions] = useState<ActionItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const loadActions = async () => {
      if (!sessionId) {
        queueMicrotask(() => { if (mounted) { setActions([]); setLoading(false); } });
        return;
      }
      const data = await localmindClient.getActions(sessionId);
      if (mounted) { setActions(data); setLoading(false); }
    };
    loadActions();
    return () => { mounted = false; };
  }, [sessionId]);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    try { const data = await localmindClient.getActions(sessionId); setActions(data); } catch { /* keep */ }
  }, [sessionId]);

  return { actions, loading, refresh };
}

// ─── useFileTree ───────────────────────────────────────────────────────

export function useFileTree(path?: string) {
  const [files, setFiles] = useState<FileNode[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    localmindClient.getFileTree(path).then((data) => { if (mounted) { setFiles(data); setLoading(false); } });
    return () => { mounted = false; };
  }, [path]);

  const refresh = useCallback(async () => {
    try { const data = await localmindClient.getFileTree(path); setFiles(data); } catch { /* keep */ }
  }, [path]);

  return { files, loading, refresh };
}

// ─── useTodos ──────────────────────────────────────────────────────────

export function useTodos(sessionId: string | null) {
  const [todos, setTodos] = useState<TodoItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const loadTodos = async () => {
      if (!sessionId) {
        queueMicrotask(() => { if (mounted) { setTodos([]); setLoading(false); } });
        return;
      }
      const data = await localmindClient.getTodos(sessionId);
      if (mounted) { setTodos(data); setLoading(false); }
    };
    loadTodos();
    return () => { mounted = false; };
  }, [sessionId]);

  const addTodo = useCallback(async (text: string) => {
    if (!sessionId) return;
    try { const newTodo = await localmindClient.createTodo(sessionId, text); setTodos((prev) => [...prev, newTodo]); } catch { /* */ }
  }, [sessionId]);

  const toggleTodo = useCallback(async (id: string, completed: boolean) => {
    setTodos((prev) => prev.map((t) => (t.id === id ? { ...t, completed } : t)));
    try { await localmindClient.updateTodo(id, { completed }); }
    catch { setTodos((prev) => prev.map((t) => (t.id === id ? { ...t, completed: !completed } : t))); }
  }, []);

  const removeTodo = useCallback(async (id: string) => {
    setTodos((prev) => prev.filter((t) => t.id !== id));
    try { await localmindClient.deleteTodo(id); } catch { /* */ }
  }, []);

  return { todos, loading, addTodo, toggleTodo, removeTodo };
}

// ─── useTerminal ───────────────────────────────────────────────────────

export function useTerminal(initialSessionId: string = 'default') {
  const [lines, setLines] = useState<TerminalLine[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [sessionId, setSessionId] = useState(initialSessionId);
  const [cwd, setCwd] = useState('~');
  const [history, setHistory] = useState<string[]>([]);

  // Load session info on mount or session change
  useEffect(() => {
    let mounted = true;
    const loadSession = async () => {
      try {
        const info = await localmindClient.getTerminalSessionInfo(sessionId);
        if (mounted) {
          setCwd(info.cwd.replace(/^\/home\/[^/]+/, '~').replace(/^\/Users\/[^/]+/, '~'));
        }
      } catch {
        // Keep defaults
      }
    };
    loadSession();
    return () => { mounted = false; };
  }, [sessionId]);

  // Load command history on session change
  useEffect(() => {
    let mounted = true;
    const loadHistory = async () => {
      try {
        const res = await localmindClient.getTerminalHistory(sessionId, 100);
        if (mounted) {
          setHistory(res.commands);
        }
      } catch {
        // Keep empty
      }
    };
    loadHistory();
    return () => { mounted = false; };
  }, [sessionId]);

  const execute = useCallback(
    async (command: string, commandCwd?: string) => {
      const now = new Date().toLocaleTimeString('en-US', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });

      const cmdLine: TerminalLine = {
        id: `cmd-${Date.now()}`,
        type: 'command',
        content: `$ ${command}`,
        timestamp: now,
      };
      setLines((prev) => [...prev, cmdLine]);
      setIsRunning(true);

      try {
        const result = await localmindClient.executeTerminal(
          command,
          commandCwd,
          sessionId
        );

        const outputTime = new Date().toLocaleTimeString('en-US', {
          hour12: false,
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        });

        // Update cwd from response
        if (result.cwd) {
          setCwd(result.cwd.replace(/^\/home\/[^/]+/, '~').replace(/^\/Users\/[^/]+/, '~'));
        }

        // Add stdout lines
        if (result.stdout) {
          for (const line of result.stdout.split('\n')) {
            setLines((prev) => [
              ...prev,
              {
                id: `out-${Date.now()}-${Math.random()}`,
                type: 'output',
                content: line,
                timestamp: outputTime,
              },
            ]);
          }
        }

        // Add stderr lines
        if (result.stderr) {
          for (const line of result.stderr.split('\n')) {
            setLines((prev) => [
              ...prev,
              {
                id: `err-${Date.now()}-${Math.random()}`,
                type: 'error',
                content: line,
                timestamp: outputTime,
              },
            ]);
          }
        }

        // Add exit code info for non-zero exits
        if (result.exitCode !== 0) {
          setLines((prev) => [
            ...prev,
            {
              id: `info-${Date.now()}`,
              type: 'info',
              content: `Exit code: ${result.exitCode} (${Math.round(result.duration * 1000)}ms)`,
              timestamp: outputTime,
              exitCode: result.exitCode,
              duration: result.duration,
            },
          ]);
        } else if (result.stdout || result.stderr) {
          // Add success indicator for zero-exit with output
          setLines((prev) => [
            ...prev,
            {
              id: `success-${Date.now()}`,
              type: 'success',
              content: `Completed in ${Math.round(result.duration * 1000)}ms`,
              timestamp: outputTime,
              duration: result.duration,
            },
          ]);
        }

        // Update local history
        setHistory((prev) => [...prev, command]);

        return result;
      } catch (err) {
        setLines((prev) => [
          ...prev,
          {
            id: `err-${Date.now()}`,
            type: 'error',
            content: err instanceof Error ? err.message : 'Command execution failed',
            timestamp: now,
          },
        ]);
        throw err;
      } finally {
        setIsRunning(false);
      }
    },
    [sessionId]
  );

  const clear = useCallback(() => {
    setLines([]);
  }, []);

  const changeSession = useCallback((newSessionId: string) => {
    setSessionId(newSessionId);
    setLines([]);
  }, []);

  const tabComplete = useCallback(
    async (partial: string): Promise<CompletionSuggestion[]> => {
      try {
        return await localmindClient.getTerminalCompletions(partial, sessionId);
      } catch {
        return [];
      }
    },
    [sessionId]
  );

  const addToolOutput = useCallback(
    (event: { tool: string; command: string; output: string; success: boolean; latencyMs: number; label?: string; toolArgs?: string }) => {
      const now = new Date().toLocaleTimeString('en-US', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });

      // Determine the tool badge and prefix based on tool type
      const toolBadgeMap: Record<string, { badge: string; prefix: string }> = {
        shell: { badge: 'shell', prefix: '$' },
        code_exec: { badge: 'code', prefix: '>>>' },
        file_task: { badge: 'file', prefix: 'read' },
        file_write: { badge: 'edit', prefix: 'write' },
        edit_file: { badge: 'edit', prefix: 'edit' },
        web_search: { badge: 'search', prefix: 'search' },
        memory_op: { badge: 'memory', prefix: 'mem' },
        sysinfo: { badge: 'system', prefix: 'sys' },
      };
      const toolInfo = toolBadgeMap[event.tool] || { badge: 'tool', prefix: '>' };

      // Add the command/action line with agent marker and tool badge
      const commandDisplay = event.command.length > 100
        ? event.command.substring(0, 100) + '...'
        : event.command;

      setLines((prev) => [
        ...prev,
        {
          id: `sys-${Date.now()}`,
          type: 'system' as const,
          content: `${toolInfo.prefix} ${commandDisplay}`,
          timestamp: now,
          source: 'agent' as const,
          toolName: toolInfo.badge,
          toolLabel: event.label || '',
        },
      ]);

      // Add the output lines
      if (event.output) {
        // For non-shell tools, trim very long output
        const maxOutputLines = ['shell', 'code_exec'].includes(event.tool) ? 100 : 30;
        const outputLines = event.output.split('\n').slice(0, maxOutputLines);
        for (const line of outputLines) {
          setLines((prev) => [
            ...prev,
            {
              id: `tool-out-${Date.now()}-${Math.random()}`,
              type: event.success ? ('output' as const) : ('error' as const),
              content: line,
              timestamp: now,
              source: 'agent' as const,
              toolName: toolInfo.badge,
            },
          ]);
        }
        // Indicate truncated output
        const totalLines = event.output.split('\n').length;
        if (totalLines > maxOutputLines) {
          setLines((prev) => [
            ...prev,
            {
              id: `trunc-${Date.now()}`,
              type: 'info' as const,
              content: `... ${totalLines - maxOutputLines} more lines truncated`,
              timestamp: now,
              source: 'agent' as const,
            },
          ]);
        }
      }

      // Add completion status
      setLines((prev) => [
        ...prev,
        {
          id: `tool-status-${Date.now()}`,
          type: event.success ? ('success' as const) : ('error' as const),
          content: event.success
            ? `Completed in ${event.latencyMs}ms`
            : `Failed (${event.latencyMs}ms)`,
          timestamp: now,
          duration: event.latencyMs,
          source: 'agent' as const,
          toolName: toolInfo.badge,
        },
      ]);
    },
    []
  );

  return {
    lines,
    isRunning,
    execute,
    clear,
    sessionId,
    cwd,
    history,
    changeSession,
    tabComplete,
    addToolOutput,
  };
}

// ─── useObservability ──────────────────────────────────────────────────

export function useObservability(sessionId: string | null) {
  // Don't default intent to 'chat' — that masks the empty state.
  // The ObservabilityTab uses hasData = confidence>0 || toolsUsed>0 || latency>0
  // to decide whether to show real data or the "—" placeholder.
  const emptyObs: ObservationData = { intent: '' as any, confidence: 0, toolsUsed: [], memoryHits: 0, contextTokens: 0, latency: 0 };
  const [observation, setObservation] = useState<ObservationData>(emptyObs);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      if (!sessionId) { queueMicrotask(() => { if (mounted) { setObservation(emptyObs); setLoading(false); } }); return; }
      const data = await localmindClient.getObservability(sessionId);
      if (mounted) { setObservation({ intent: data.intent, confidence: data.confidence, toolsUsed: data.toolsUsed, memoryHits: data.memoryHits, contextTokens: data.contextTokens, latency: data.latency }); setLoading(false); }
    };
    load();
    return () => { mounted = false; };
  }, [sessionId]);

  return { observation, loading };
}

// ─── useMetrics ────────────────────────────────────────────────────────

export function useMetrics(isStreaming?: boolean, intervalMs = 5000) {  // 5s — was 60s, caused dead metrics bar
  const [metrics, setMetrics] = useState<PerformanceMetrics>({ tokensPerSecond: 0, latency: 0, totalTokens: 0, promptTokens: 0, completionTokens: 0 });
  const wasStreamingRef = useRef(false);

  const fetchMetrics = useCallback(async () => {
    try { const data = await localmindClient.getMetrics(); setMetrics(data); } catch { /* keep */ }
  }, []);

  // Poll every intervalMs as a baseline refresh
  useEffect(() => {
    let mounted = true;
    const doFetch = async () => {
      try { const data = await localmindClient.getMetrics(); if (mounted) setMetrics(data); } catch { /* keep */ }
    };
    doFetch();
    const id = setInterval(doFetch, intervalMs);
    return () => { mounted = false; clearInterval(id); };
  }, [intervalMs]);

  // When streaming transitions from true → false, immediately fetch metrics.
  // The backend populates streaming metrics on record_streaming_complete(),
  // which fires right before the SSE done event. Without this immediate
  // fetch, the user sees 0s for up to 5 seconds after a response completes.
  useEffect(() => {
    if (wasStreamingRef.current && !isStreaming) {
      // Small delay to ensure backend has finished writing metrics
      const timer = setTimeout(() => fetchMetrics(), 300);
      wasStreamingRef.current = false;
      return () => clearTimeout(timer);
    }
    if (isStreaming) {
      wasStreamingRef.current = true;
    }
  }, [isStreaming, fetchMetrics]);

  return { metrics, refreshMetrics: fetchMetrics };
}

// ─── useModels ─────────────────────────────────────────────────────────

interface ModelsState {
  models: ModelOption[];
  current: string;
  provider: string;
  loading: boolean;
  selectModel: (modelId: string) => Promise<void>;
  refresh: () => Promise<void>;
}

export function useModels(): ModelsState {
  const [models, setModels] = useState<ModelOption[]>([]);
  const [current, setCurrent] = useState('');
  const [provider, setProvider] = useState('');
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await localmindClient.getModels();
      setModels(data.models);
      setCurrent(data.current);
      setProvider(data.provider);
    } catch { /* keep */ } finally { setLoading(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const selectModel = useCallback(async (modelId: string) => {
    try {
      await localmindClient.selectModel(modelId);
      setCurrent(modelId);
      // Refresh models from backend to get updated current model
      const data = await localmindClient.getModels();
      setModels(data.models);
      setCurrent(data.current);
      setProvider(data.provider);
    } catch { /* keep */ }
  }, []);

  return { models, current, provider, loading, selectModel, refresh };
}

// ─── useMemory ─────────────────────────────────────────────────────────

export function useMemory() {
  const [facts, setFacts] = useState<MemoryFact[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try { const data = await localmindClient.getMemory(); setFacts(data); }
    catch { /* keep */ } finally { setLoading(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const storeFact = useCallback(async (content: string, source: string) => {
    try { await localmindClient.storeMemory(content, source); const data = await localmindClient.getMemory(); setFacts(data); } catch { /* */ }
  }, []);

  const deleteFact = useCallback(async (id: string) => {
    try {
      await localmindClient.deleteMemory(id);
      setFacts((prev) => prev.filter((f) => f.id !== id));
    } catch { /* keep */ }
  }, []);

  return { facts, loading, refresh, storeFact, deleteFact };
}
