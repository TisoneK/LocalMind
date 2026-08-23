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
import { classifyClientIntent, localmindClient } from '@/lib/localmind/client';
import { applyTodoCreated, applyTodoUpdated, estimateTokens, isActiveToolStatus } from '@/lib/localmind/progress';
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
  AnomalyData,
  CapabilitiesData,
  ModelError,
  ModelOption,
  ToolCall,
  CompletionSuggestion,
  Objective,
  SessionStats,
  AgentPhase,
  AgentRun,
  AgentRunStatus,
  DiffData,
} from '@/types';

// S296: cap the accumulated per-turn run groups in the Agent Workspace so a
// long session doesn't grow the DOM unbounded (older turns pruned, newest kept).
const MAX_WORKSPACE_TURNS = 10;

// ─── Session stats (stats split — bottom-right corner) ────────────────────
// Per-chat cumulative performance totals. Keyed per hook instance so they
// survive session switches within the app run (switching back to a session
// you already chatted with restores its numbers) but reset on app reload and
// are isolated between test renderHook instances.
const _EMPTY_SESSION_STATS: SessionStats = {
  promptTokens: 0,
  completionTokens: 0,
  latencyMs: 0,
  genTimeMs: 0,
  turnCount: 0,
};

/** Rebuild session totals from loaded history (assistant messages that carry
 *  attached `performance`). Used when no in-memory cache entry exists. */
function _seedSessionStats(history: ChatMessage[]): SessionStats {
  const acc: SessionStats = { ..._EMPTY_SESSION_STATS };
  for (const m of history) {
    if (m.role !== 'assistant' || !m.performance) continue;
    const p = m.performance;
    const completion = p.completionTokens ?? 0;
    const latency = p.latencyMs ?? 0;
    acc.promptTokens += p.promptTokens ?? 0;
    acc.completionTokens += completion;
    acc.latencyMs += latency;
    acc.genTimeMs += p.tokensPerSecond && p.tokensPerSecond > 0 && completion > 0
      ? (completion / p.tokensPerSecond) * 1000
      : latency;
    acc.turnCount += 1;
  }
  return acc;
}

// ─── useCapabilities ────────────────────────────────────────────────────

export function useCapabilities() {
  const [capabilities, setCapabilities] = useState<CapabilitiesData>({ families: [] });

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      const data = await localmindClient.getCapabilities();
      if (mounted) setCapabilities(data);
    };
    load();
    return () => {
      mounted = false;
    };
  }, []);

  return capabilities;
}

// ─── useHealth ─────────────────────────────────────────────────────────

interface HealthState {
  status: 'online' | 'offline' | 'checking';
  version?: string;
  uptime?: number;
  // ADR-52 phase 2 (Session 305): distinct parent-kernel readiness.
  // parent_ready is true when the boot kernel built without a degraded
  // state; parent_degraded_reason carries the warmup failure string.
  // These are distinct from `status` (which aggregates provider +
  // engine + parent) so the UI can show the parent's specific state.
  parentReady?: boolean;
  parentDegradedReason?: string;
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
            parentReady: res.parent_ready,
            parentDegradedReason: res.parent_degraded_reason,
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

  // Poll for session updates every 10s so the sidebar picks up
  // LLM-generated titles that are written ~2-5s after the first message.
  // Without this, the placeholder title ("Morning greeting") stays forever
  // because the sidebar only refreshes on send/delete/new chat.
  useEffect(() => {
    const id = setInterval(refresh, 10000);
    return () => clearInterval(id);
  }, [refresh]);

  const deleteSession = useCallback(
    async (sessionId: string) => {
      await localmindClient.deleteSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
    },
    []
  );

  // Bulk delete for the multi-select chat actions. Deletions run
  // concurrently; a failure on one id does not abort the others. State is
  // updated once, dropping every id that was actually deleted.
  const deleteSessions = useCallback(
    async (sessionIds: string[]): Promise<string[]> => {
      const results = await Promise.allSettled(
        sessionIds.map((id) => localmindClient.deleteSession(id)),
      );
      const deleted = sessionIds.filter((_, i) => results[i].status === 'fulfilled');
      if (deleted.length) {
        const gone = new Set(deleted);
        setSessions((prev) => prev.filter((s) => !gone.has(s.id)));
      }
      return deleted;
    },
    []
  );

  return { sessions, loading, refresh, deleteSession, deleteSessions };
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
  /** B-2026-08-23-18: file diffs captured from edit_file `diff` SSE events,
   *  keyed by absolute path (latest wins) — powers the preview dialog's Diff
   *  mode and the inline DiffBlock in chat. */
  fileDiffs: Record<string, DiffData>;
  isStreaming: boolean;
  currentIntent?: string;
  currentConfidence?: number;
  activeToolCalls: ToolCall[];
  agentRuns: AgentRun[];
  liveObservation: ObservationData | null;
  lastMetrics: PerformanceMetrics | null;
  elapsedMs: number;
  /** Cumulative per-chat totals (B-2026-08-11-5 / stats split): the bottom-
   *  right corner answers "how is this session doing overall" while each
   *  bubble keeps its own per-message line. */
  sessionStats: SessionStats;
  send: (message: string, sessionIdOverride?: string, tool?: string) => void;
  abort: () => void;
  /** B-2026-08-02-5 (A5): inject a user message at the next step boundary
   *  of the in-flight agent turn without aborting it. No-op when idle. */
  steer: (message: string) => void;
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  /** Clears transient per-turn state so a new chat starts from a clean slate
   *  (context-token counter, live metrics, agent-run tree, session stats). */
  resetSession: () => void;
  onTerminalEvent?: (event: TerminalEventData) => void;
}

function updateAgentRun(runs: AgentRun[], runId: string, patch: Partial<AgentRun>): AgentRun[] {
  return runs.map((run) => run.id === runId ? { ...run, ...patch } : run);
}

function attachToolToAgentRun(runs: AgentRun[], rootRunId: string, tool: ToolCall): AgentRun[] {
  const target = tool.runId
    ? runs.find((run) => run.id === tool.runId)
    : tool.agent
      ? [...runs].reverse().find((run) => run.role !== 'parent' && run.name === tool.agent && run.status === 'running')
      : undefined;
  const targetId = (target || runs.find((item) => item.id === rootRunId))?.id;
  if (!targetId) return runs;
  return runs.map((run) => {
    if (run.id !== targetId) return run;
    const existingIndex = run.tools.findIndex((item) => item.id === tool.id);
    const tools = [...run.tools];
    if (existingIndex >= 0) tools[existingIndex] = { ...tools[existingIndex], ...tool };
    else tools.push(tool);
    return { ...run, tools };
  });
}

export function useChat(
  sessionId: string | null,
  onTerminalEvent?: (event: TerminalEventData) => void
): ChatState {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  // B-2026-08-23-18: file diffs captured from edit_file `diff` SSE events,
  // keyed by absolute path (latest wins). Powers the preview dialog's Diff
  // mode and the inline DiffBlock in chat (message.diffData).
  const [fileDiffs, setFileDiffs] = useState<Record<string, DiffData>>({});
  const [isStreaming, setIsStreaming] = useState(false);
  const [currentIntent, setCurrentIntent] = useState<string | undefined>();
  const [currentConfidence, setCurrentConfidence] = useState<number | undefined>();
  const [activeToolCalls, setActiveToolCalls] = useState<ToolCall[]>([]);
  const [agentRuns, setAgentRuns] = useState<AgentRun[]>([]);
  const [liveObservation, setLiveObservation] = useState<ObservationData | null>(null);
  const [lastMetrics, setLastMetrics] = useState<PerformanceMetrics | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [sessionStats, setSessionStats] = useState<SessionStats>({ ..._EMPTY_SESSION_STATS });
  // Mirrors sessionStats for pure, synchronous reads (the accumulation effect
  // computes the next totals from this ref — never from a state updater — so
  // there's no side-effect-in-updater smell and no StrictMode double-invoke
  // risk). Every write goes through applySessionStats() which updates both.
  const sessionStatsRef = useRef<SessionStats>({ ..._EMPTY_SESSION_STATS });
  const applySessionStats = useCallback((next: SessionStats) => {
    sessionStatsRef.current = next;
    setSessionStats(next);
  }, []);
  // Which session the current/next turn belongs to + the turn counter, used by
  // the accumulation effect to (a) ignore late metrics from a switched-away
  // session and (b) REPLACE (not double-count) a same-turn metrics upgrade.
  const turnSessionRef = useRef<string | null>(null);
  const turnCounterRef = useRef(0);
  const lastTurnContributionRef = useRef<{
    turn: number;
    prompt: number;
    completion: number;
    latency: number;
    genMs: number;
  } | null>(null);
  const sessionStatsSeededForRef = useRef<string | null>(null);
  const sessionStatsBySessionRef = useRef<Map<string, SessionStats>>(new Map());
  const streamStartedAtRef = useRef<number | null>(null);
  const abortRef = useRef<(() => void) | null>(null);
  // Session 133: last time ANY SSE payload arrived for the current stream.
  // The old force-reset fired after 120s of STREAMING (wall clock), killing
  // legitimate slow requests (a tool loop chaining 4-7 free-tier model calls
  // at 20-40s/call legitimately runs 80-280s). It now fires only after 120s
  // of SILENCE — a genuinely stuck stream still recovers, a slow-but-active
  // one (tokens/obs/status events every few seconds) is left alone.
  // Initialized 0 (not Date.now() — impure during render): the value is
  // only read by the silence-check interval, which runs solely while
  // isStreaming is true, and send() re-arms it before the stream starts.
  const lastActivityRef = useRef<number>(0);

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

  // Keep a real clock running during the complete request, including dispatcher
  // and tool execution time. Event-driven timestamps alone freeze while a tool
  // is running because no token event may arrive for several seconds.
  useEffect(() => {
    if (!isStreaming || streamStartedAtRef.current === null) return;
    const tick = () => {
      const startedAt = streamStartedAtRef.current;
      if (startedAt !== null) {
        setElapsedMs(Date.now() - startedAt);
      }
    };
    tick();
    const timer = window.setInterval(tick, 250);
    return () => window.clearInterval(timer);
  }, [isStreaming]);

  // B-2026-08-09-3 (ADR-13): when a turn completes with real metrics, attach
  // them to the assistant message that produced them so each reply shows its
  // own latency/token line — not the session-global last-turn values.
  // send() clears lastMetrics at turn start, so the values observed here
  // always belong to the turn that just ended. The effect re-runs if a late
  // metrics event arrives after the done callback, upgrading a live estimate
  // to the exact final numbers.
  useEffect(() => {
    if (isStreaming) return;
    const m = lastMetrics;
    if (!m || (m.latency <= 0 && m.totalTokens <= 0)) return;
    setMessages((prev) => {
      const updated = [...prev];
      const last = updated[updated.length - 1];
      if (last && last.role === 'assistant') {
        updated[updated.length - 1] = {
          ...last,
          performance: {
            latencyMs: m.latency > 0 ? m.latency : undefined,
            promptTokens: m.promptTokens > 0 ? m.promptTokens : undefined,
            completionTokens: m.completionTokens > 0 ? m.completionTokens : undefined,
            tokensPerSecond: m.tokensPerSecond > 0 ? m.tokensPerSecond : undefined,
          },
        };
      }
      return updated;
    });
  }, [isStreaming, lastMetrics, setMessages]);

  // Stats split: accumulate each completed turn into the session totals shown
  // in the bottom-right corner. Runs only when idle (the stream owns timing
  // while active). Guarded so a late metrics upgrade REPLACES — not
  // double-counts — the same turn, late events from a previous session are
  // ignored after a session switch, and an aborted turn that produced NO
  // tokens (pure wall-clock, nothing sent to the model) never counts.
  useEffect(() => {
    if (isStreaming) return;
    if (turnSessionRef.current !== sessionId) return;
    const m = lastMetrics;
    if (!m) return;
    const completion = Math.max(0, m.completionTokens || 0);
    const prompt = Math.max(0, m.promptTokens || 0);
    const latency = Math.max(0, m.latency || 0);
    const hasTokens = completion > 0 || prompt > 0;
    const hasLatency = latency > 0 || (m.totalTokens || 0) > 0;
    if (!hasTokens || !hasLatency) return;
    const genMs = m.tokensPerSecond && m.tokensPerSecond > 0 && completion > 0
      ? (completion / m.tokensPerSecond) * 1000
      : latency;
    const turn = turnCounterRef.current;
    const prevContribution = lastTurnContributionRef.current?.turn === turn
      ? lastTurnContributionRef.current
      : null;
    const prev = sessionStatsRef.current;
    const next: SessionStats = prevContribution
      ? {
          promptTokens: prev.promptTokens - prevContribution.prompt + prompt,
          completionTokens: prev.completionTokens - prevContribution.completion + completion,
          latencyMs: prev.latencyMs - prevContribution.latency + latency,
          genTimeMs: prev.genTimeMs - prevContribution.genMs + genMs,
          turnCount: Math.max(0, prev.turnCount - 1) + 1,
        }
      : {
          promptTokens: prev.promptTokens + prompt,
          completionTokens: prev.completionTokens + completion,
          latencyMs: prev.latencyMs + latency,
          genTimeMs: prev.genTimeMs + genMs,
          turnCount: prev.turnCount + 1,
        };
    applySessionStats(next);
    if (sessionId) sessionStatsBySessionRef.current.set(sessionId, next);
    lastTurnContributionRef.current = { turn, prompt, completion, latency, genMs };
  }, [isStreaming, lastMetrics, sessionId, applySessionStats]);

  // SAFETY: force-reset isStreaming only when the stream is genuinely
  // STALLED — no SSE payload for 120s — not merely long-running. This
  // preserves the "second message hangs forever" protection (a backend
  // hang or stream error goes silent and still recovers) without killing
  // slow-but-working requests: a tool loop chaining several free-tier model
  // calls streams obs/status/token events throughout, so lastActivityRef
  // keeps advancing and the reset never fires.
  useEffect(() => {
    if (!isStreaming) return;
    const id = window.setInterval(() => {
      if (!isStreamingRef.current) return;
      const silenceMs = Date.now() - lastActivityRef.current;
      if (silenceMs > 120000) {
        console.warn(`[useChat] force-resetting isStreaming after ${Math.round(silenceMs / 1000)}s of silence`);
        setIsStreaming(false);
        streamingSessionRef.current = null;
        abortRef.current = null;
        setActiveToolCalls((prev) =>
          prev.map((tc) =>
            isActiveToolStatus(tc.status)
              ? { ...tc, status: 'done' as const, duration: tc.duration || 120000 }
              : tc
          )
        );
      }
    }, 5000);
    return () => window.clearInterval(id);
  }, [isStreaming]);

  // FIX: Auto-timeout for stuck tool calls. If a tool_call stays in "running"
  // status for more than 60 seconds, mark it as "done" — the backend likely
  // completed without sending a tool_result event. This prevents infinite spinners.
  useEffect(() => {
    const running = activeToolCalls.filter((tc) => isActiveToolStatus(tc.status));
    if (running.length === 0) return;
    const timer = setTimeout(() => {
      setActiveToolCalls((prev) => {
        const hasStuck = prev.some((tc) => isActiveToolStatus(tc.status));
        if (!hasStuck) return prev;
        return prev.map((tc) =>
          isActiveToolStatus(tc.status)
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
          setFileDiffs({});
          setLiveObservation(null);
          setCurrentIntent(undefined);
          setCurrentConfidence(undefined);
          setActiveToolCalls([]);
          setAgentRuns([]);
          // B-2026-08-09-3: don't let the previous session's metrics attach
          // to a different session's messages on the next turn.
          setLastMetrics(null);
          // Stats split: new chat / cleared session → fresh counters.
          applySessionStats({ ..._EMPTY_SESSION_STATS });
          sessionStatsSeededForRef.current = null;
          lastTurnContributionRef.current = null;
        }
        return;
      }
      // Clear stale data from the previous session immediately so the
      // Observe/Actions panels don't show the old session's data while
      // the new history loads.
      if (prevSessionIdRef.current !== sessionId) {
        setFileDiffs({});
        setLiveObservation(null);
        setCurrentIntent(undefined);
        setCurrentConfidence(undefined);
        setActiveToolCalls([]);
        setAgentRuns([]);
        // B-2026-08-09-3: clearing lastMetrics on session switch prevents the
        // attach-on-complete effect from stamping the OLD session's turn
        // metrics onto the newly loaded history's last message (review fix).
        setLastMetrics(null);
        // Stats split: switch to the other session's cumulative totals (or
        // fresh zeros if this run never chatted there).
        const cached = sessionStatsBySessionRef.current.get(sessionId);
        applySessionStats(cached ? { ...cached } : { ..._EMPTY_SESSION_STATS });
        if (cached) sessionStatsSeededForRef.current = sessionId;
        lastTurnContributionRef.current = null;
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
        // Session 267: restore the Agent Workspace run tree. The Agents tab
        // shows the most recent turn's tree (each send replaces it), so pick
        // the LAST assistant message that carries one — earlier turns' trees
        // are superseded by the latest turn's work.
        const lastRunTree = [...history]
          .reverse()
          .find((m) => m.role === 'assistant' && Array.isArray(m.agentRuns) && m.agentRuns.length > 0);
        setAgentRuns(lastRunTree?.agentRuns ?? []);
        // Stats split: seed the corner totals once per session — from the
        // in-run per-session totals when this hook instance already chatted
        // there (never overwrite live-accumulated numbers with a stale
        // empty-history seed), else from history's attached metrics.
        if (
          sessionStatsSeededForRef.current !== sessionId &&
          !sessionStatsBySessionRef.current.has(sessionId)
        ) {
          applySessionStats(_seedSessionStats(history));
          sessionStatsSeededForRef.current = sessionId;
        }
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
        // Session 30: immediate acknowledgment — the user sees this
        // instantly instead of a dead "Thinking..." while the pipeline
        // spins up. Updated by status_update events as stages progress.
        statusText: 'Got it — working on your request...',
      };

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setIsStreaming(true);
      streamStartedAtRef.current = Date.now();
      // Stats split: this turn belongs to the effective session and gets a
      // fresh turn number so the accumulation effect can attribute it.
      turnCounterRef.current += 1;
      turnSessionRef.current = effectiveSessionId;
      // Session 133 addendum: re-arm the stall timer at stream START, not
      // component mount. lastActivityRef is only otherwise written on SSE
      // payloads, so if the app sat idle >120s before sending (and the
      // first payload is delayed by a slow model/busy backend), the silence
      // check would be already-past-threshold and kill a working request
      // before its first event arrived.
      lastActivityRef.current = Date.now();
      setElapsedMs(0);
      setLastMetrics(null);
      setActiveToolCalls([]);
      setLiveObservation(null);
      const rootRunId = `parent-${Date.now()}`;
      const runTree: AgentRun[] = [{
        id: rootRunId,
        name: 'parent',
        role: 'parent',
        task: message,
        status: 'running',
        depth: 0,
        startedAt: Date.now(),
        tools: [],
      }];
      // S296 (issue 2): ACCUMULATE per-turn run groups instead of wiping the
      // workspace every turn. Finalize any run still marked running from a
      // prior/interrupted turn, then append this turn's tree. Keep only the
      // most recent MAX_WORKSPACE_TURNS parent turns (+ their descendants) so a
      // long session doesn't grow the DOM unbounded — older turns are pruned.
      setAgentRuns((prev) => {
        const finalized = prev.map((r) =>
          r.status === 'running'
            ? { ...r, status: 'completed' as AgentRunStatus, completedAt: r.completedAt ?? Date.now() }
            : r,
        );
        const combined = [...finalized, ...runTree];
        const rootIds = combined.filter((r) => !r.parentId).map((r) => r.id);
        const keptRoots = new Set(rootIds.slice(-MAX_WORKSPACE_TURNS));
        // Keep a run if its ancestor chain terminates at a kept root.
        const byId = new Map(combined.map((r) => [r.id, r] as const));
        const isKept = (run: AgentRun): boolean => {
          let cur: AgentRun | undefined = run;
          const seen = new Set<string>();
          while (cur && cur.parentId && !seen.has(cur.id)) {
            seen.add(cur.id);
            cur = byId.get(cur.parentId);
          }
          return Boolean(cur && keptRoots.has(cur.id));
        };
        return combined.filter(isKept);
      });

      let currentContent = '';
      let thinkingContent = '';
      let streamedProgressText = '';
      let thinkStartTime = 0;
      const toolCalls: ToolCall[] = [];
      const toolsUsedSet = new Set<string>();

      const abortFn = localmindClient.streamChat(
        message,
        effectiveSessionId,
        // onChunk — parse structured SSE events
        (rawData: string) => {
          // Any SSE payload (token, obs, status, tool) counts as activity.
          lastActivityRef.current = Date.now();
          try {
            const parsed = JSON.parse(rawData);
            // The backend emits structured obs events as {"obs_event": {...}}
            // with NO top-level "type" (obs.py ObsEvent.to_sse_dict). Without
            // this fallback the case 'obs_event' below was dead code — every
            // stage_timing / turn_complete / intent_classified event was
            // silently dropped, so the Observe panel confidence + context
            // tokens stayed "—" (fed only by a stale one-shot poll + the
            // fallback pipeline heuristic + the separately-wrapped metrics
            // event). Route obs payloads to the handler that owns them.
            const eventType = parsed.type ?? (parsed.obs_event ? 'obs_event' : undefined);

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
                streamedProgressText += token;
                const estimatedCompletionTokens = estimateTokens(streamedProgressText);
                const liveElapsed = streamStartedAtRef.current
                  ? Date.now() - streamStartedAtRef.current
                  : 0;
                setLastMetrics((prev) => ({
                  tokensPerSecond: liveElapsed > 0
                    ? Math.round(estimatedCompletionTokens / (liveElapsed / 1000) * 100) / 100
                    : 0,
                  latency: liveElapsed,
                  totalTokens: estimatedCompletionTokens + (prev?.promptTokens || 0),
                  promptTokens: prev?.promptTokens || 0,
                  completionTokens: estimatedCompletionTokens,
                }));
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
                // Session 146: DON'T wipe earlier phases' reasoning. The
                // dispatcher, chat-agent, and agent-loop phases each emit
                // thinking_start; resetting on every one discarded everything
                // streamed before — the pre-tool phase rendered as a silent
                // black-box "SHELL" card. Seed only on the FIRST phase so the
                // full multi-phase reasoning trace accumulates on the message
                // (expanded live while streaming, auto-collapsed after); later
                // phase boundaries insert a separator instead of truncating.
                if (!thinkingContent) {
                  thinkingContent = '';
                  // Don't reset thinkStartTime if already set by a status_update
                  // that arrived before thinking_start.
                  if (!thinkStartTime) thinkStartTime = Date.now();
                } else {
                  thinkingContent += '\n\n';
                }
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
                const thinkingToken = parsed.thinking || parsed.content || '';
                thinkingContent += thinkingToken;
                streamedProgressText += thinkingToken;
                const thinkMs = thinkStartTime ? Date.now() - thinkStartTime : 0;
                const estimatedCompletionTokens = estimateTokens(streamedProgressText);
                const liveElapsed = streamStartedAtRef.current
                  ? Date.now() - streamStartedAtRef.current
                  : 0;
                setLastMetrics((prev) => ({
                  tokensPerSecond: liveElapsed > 0
                    ? Math.round(estimatedCompletionTokens / (liveElapsed / 1000) * 100) / 100
                    : 0,
                  latency: liveElapsed,
                  totalTokens: estimatedCompletionTokens + (prev?.promptTokens || 0),
                  promptTokens: prev?.promptTokens || 0,
                  completionTokens: estimatedCompletionTokens,
                }));
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
                // Focus the left Actions tab only when a tool actually starts.
                // Completed events should update the existing row without
                // stealing focus back from the user's current panel.
                if (isActiveToolStatus(tc.status) || tc.status === 'pending' || tc.status === 'in_progress' || tc.status === 'started') {
                  window.dispatchEvent(new CustomEvent('localmind:tool-call-started', {
                    detail: { tool: tc.name || tc.tool || 'unknown' },
                  }));
                }
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
                  iteration: tc.iteration !== undefined && tc.iteration !== '' ? Number(tc.iteration) : undefined,
                  todoId: tc.todo_id as string | undefined,
                  reasoning: tc.thought || tc.reasoning,
                  agent: tc.agent || undefined,
                  runId: tc.run_id || tc.runId || undefined,
                  provider: tc.provider || undefined,
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
                    (existing) => existing.name === toolCall.name && isActiveToolStatus(existing.status)
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
                setAgentRuns((prev) => attachToolToAgentRun(prev, rootRunId, toolCall));
                setLiveObservation((prev) => ({
                  intent: _toolToIntent(toolCall.name, prev?.intent || currentIntent || 'chat') as any,
                  confidence: prev?.confidence ?? currentConfidence ?? 0,
                  toolsUsed: [...toolsUsedSet],
                  memoryHits: prev?.memoryHits ?? 0,
                  contextTokens: prev?.contextTokens ?? 0,
                  latency: prev?.latency ?? 0,
                  // Preserve accumulated stage timings across tool_call events
                  stageTimings: prev?.stageTimings,
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
                  (tc) => tc.name === (tr.name || tr.tool) && isActiveToolStatus(tc.status)
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
                setAgentRuns((prev) => attachToolToAgentRun(prev, rootRunId, toolCalls[idx !== -1 ? idx : toolCalls.length - 1]));
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
                  // Preserve accumulated stage timings across intent events
                  stageTimings: prev?.stageTimings,
                  anomalies: prev?.anomalies,
                }));
                break;
              }

              case 'anomaly': {
                // Session 123: the backend detected an anomaly on this turn
                // (stall / token leak). Accumulate into the observation so
                // the Observe panel renders alert cards. Dedupe by kind — a
                // re-detected anomaly replaces the earlier one; cap at 5.
                const anomaly = parsed.anomaly;
                if (anomaly && typeof anomaly === 'object' && typeof anomaly.kind === 'string') {
                  setLiveObservation((prev) => {
                    const rest = (prev?.anomalies ?? []).filter(
                      (a) => a.kind !== anomaly.kind
                    );
                    return {
                      intent: prev?.intent ?? ('chat' as any),
                      confidence: prev?.confidence ?? 0,
                      toolsUsed: prev?.toolsUsed ?? [],
                      memoryHits: prev?.memoryHits ?? 0,
                      contextTokens: prev?.contextTokens ?? 0,
                      latency: prev?.latency ?? 0,
                      stageTimings: prev?.stageTimings,
                      anomalies: [anomaly as AnomalyData, ...rest].slice(0, 5),
                    };
                  });
                }
                break;
              }

              // B-2026-08-23-18: edit_file diff events. The backend bridges
              // file_diff obs events to a top-level `diff` SSE event with
              // hunks/language/filePath. Previously unhandled — the events
              // were dropped and message.diffData (and the inline DiffBlock in
              // chat) were dead code. Store per-path (latest wins) for the
              // preview dialog's Diff mode AND attach to the current assistant
              // message so the inline DiffBlock renders.
              case 'diff': {
                const d = parsed.diff;
                if (d && typeof d.filePath === 'string' && Array.isArray(d.hunks)) {
                  const entry: DiffData = {
                    hunks: d.hunks,
                    language: typeof d.language === 'string' ? d.language : '',
                    filePath: d.filePath,
                    additions: typeof d.additions === 'number' ? d.additions : undefined,
                    deletions: typeof d.deletions === 'number' ? d.deletions : undefined,
                  };
                  // Windows-tolerance: normalize the key so the preview's
                  // path lookup matches regardless of backslash/forward slash.
                  const key = d.filePath.split('\\').join('/');
                  setFileDiffs((prev) => ({ ...prev, [key]: entry }));
                  setMessages((prev) => {
                    const updated = [...prev];
                    const last = updated[updated.length - 1];
                    if (last && last.role === 'assistant') {
                      updated[updated.length - 1] = { ...last, diffData: entry };
                    }
                    return updated;
                  });
                }
                break;
              }

              case 'obs_event': {
                const obs = parsed.obs_event || parsed;
                // Session 123: an anomaly may also arrive wrapped as an
                // obs_event (the bridge drains every obs event to SSE). Treat
                // it the same as the top-level 'anomaly' case.
                if (obs.type === 'anomaly') {
                  const obsAnomaly = obs.data || obs;
                  if (obsAnomaly && typeof obsAnomaly === 'object' && typeof obsAnomaly.kind === 'string') {
                    setLiveObservation((prev) => {
                      const rest = (prev?.anomalies ?? []).filter(
                        (a) => a.kind !== obsAnomaly.kind
                      );
                      return {
                        intent: prev?.intent ?? ('chat' as any),
                        confidence: prev?.confidence ?? 0,
                        toolsUsed: prev?.toolsUsed ?? [],
                        memoryHits: prev?.memoryHits ?? 0,
                        contextTokens: prev?.contextTokens ?? 0,
                        latency: prev?.latency ?? 0,
                        stageTimings: prev?.stageTimings,
                        anomalies: [obsAnomaly as AnomalyData, ...rest].slice(0, 5),
                      };
                    });
                  }
                  break;
                }
                // Active-agent lifecycle narration (bootup-telemetry session):
                // attach the initialization / planning / thinker / loop phases
                // to the PARENT run so the Agents tab's active agent node
                // shows the whole turn. The chat phase strip keeps ONLY the
                // Session 181 decision history (plan/gate/orchestrator) — see
                // PHASE_EVENT_TYPES below.
                const RUN_LIFECYCLE_TYPES = new Set([
                  'agent_initialization_start',
                  'agent_initialization_understanding',
                  'agent_initialization_ack',
                  'agent_initialization_done',
                  'agent_planning_done',
                  'agent_thinker_start',
                  'agent_thinker_done',
                  'agent_loop_start',
                  'agent_loop_done',
                ]);
                // The classify call names the turn ("Fetch Weather"); use it as
                // the parent run's heading instead of "Turn N" (rides the
                // existing init event — no extra model call).
                if (obs.type === 'agent_initialization_done') {
                  const title = String((obs.data || obs).title || '').trim();
                  if (title) {
                    setAgentRuns((prev) => updateAgentRun(prev, rootRunId, { title }));
                  }
                }
                if (RUN_LIFECYCLE_TYPES.has(obs.type)) {
                  const runPhase = buildAgentPhase(obs.type, obs.data || obs);
                  if (runPhase) {
                    const phaseAgent = String((obs.data || obs).agent || '');
                    setAgentRuns((prev) => {
                      // Route to the owning run: child lifecycle events carry
                      // an `agent` tag (ChildObsProxy) → the running child of
                      // that name; untagged events → the parent. Mirrors
                      // attachToolToAgentRun's matching.
                      const target = phaseAgent
                        ? [...prev].reverse().find((r) => r.role !== 'parent' && r.name === phaseAgent && r.status === 'running')
                        : prev.find((r) => r.id === rootRunId);
                      if (!target) return prev;
                      // Canonical narrative order — the loop emits some events
                      // out of story order (loop_start before init), so sort
                      // by the same rank the backend uses on persistence.
                      const phases = [...(target.phases || []), runPhase]
                        .sort((a, b) => (LIFECYCLE_PHASE_RANK[a.type] ?? 99) - (LIFECYCLE_PHASE_RANK[b.type] ?? 99));
                      return updateAgentRun(prev, target.id, { phases });
                    });
                  }
                }
                // ADR-36: the acknowledgement is the Agent's opening line —
                // route it to the assistant message's `acknowledgement` field
                // (rendered as the opening line above the thinking block).
                // It is ALSO a run-lifecycle phase (handled above) so the
                // workspace node narrates it.
                // agent_initialization_understanding is intentionally NOT
                // mirrored to the chat message here: it already reaches the
                // user through the thinking_token channel into the message's
                // ThinkingBlock (ADR-36). The run node above narrates it for
                // the Agents tab.
                if (obs.type === 'agent_initialization_ack') {
                  const ackData = obs.data || obs;
                  const ackText = String(ackData.acknowledgement || '').slice(0, 180);
                  if (ackText) {
                    setMessages((prev) => {
                      const updated = [...prev];
                      const last = updated[updated.length - 1];
                      if (last && last.role === 'assistant') {
                        updated[updated.length - 1] = { ...last, acknowledgement: ackText };
                      }
                      return updated;
                    });
                  }
                  break;
                }
                // agent_initialization_understanding is intentionally NOT
                // mirrored to the workspace run here: it already reaches the
                // user through the thinking_token channel into the message's
                // ThinkingBlock (see ADR-36 — the Thinker's assessment lives
                // on the thinking surface, not the workspace).
                // ADR-34 B-8: evidence boundary — tool results are handed to
                // the parent model. Record as an EvidenceEntry on the parent
                // run so the Agent Workspace can show evidence flowing in.
                if (obs.type === 'evidence_to_parent') {
                  const evData = obs.data || obs;
                  const entry = {
                    tool: String(evData.tool || 'unknown'),
                    iteration: Number(evData.iteration || 0),
                    evidenceChars: Number(evData.evidence_chars || 0),
                    failed: Boolean(evData.failed),
                    timestamp: Date.now(),
                  };
                  setAgentRuns((prev) => {
                    const run = prev.find((r) => r.id === rootRunId);
                    if (!run) return prev;
                    const evidence = [...(run.evidence || []), entry];
                    return updateAgentRun(prev, rootRunId, { evidence });
                  });
                  break;
                }
                // ADR-18 P3 (Session 176): delegation streaming — the
                // sub-agent's lifecycle shows as one running tool step
                // ("Delegating to research…") in the Actions panel; the
                // child's own tool_call events (forwarded by the backend,
                // tagged with `agent`) render as their own cards interleaved.
                // The card name is `delegate→<agent>` (NOT plain "delegate")
                // so it can't collide with the parent's own delegate tool
                // step in the name-based done dedup.
                if (obs.type === 'delegation_started' || obs.type === 'delegation_completed') {
                  const obsDel = obs.data || obs;
                  const agentName = String(obsDel.target_agent || 'sub-agent');
                  const delId = `delegation-${obsDel.run_id || agentName}`;
                  const delName = `delegate→${agentName}`;
                  if (obs.type === 'delegation_started') {
                    const childRunId = String(obsDel.run_id || `child-${agentName}-${Date.now()}`);
                    const childTask = String(obsDel.task || '');
                    const childDepth = Number(obsDel.depth || 1);
                    setAgentRuns((prev) => {
                      if (prev.some((run) => run.id === childRunId)) return prev;
                      return [
                        ...prev,
                        {
                          id: childRunId,
                          name: agentName,
                          role: 'child' as const,
                          parentId: rootRunId,
                          task: childTask,
                          status: 'running' as const,
                          depth: childDepth,
                          startedAt: Date.now(),
                          tools: [],
                        },
                      ];
                    });
                    const delCall: ToolCall = {
                      id: delId,
                      name: delName,
                      label: `Delegating to ${agentName}…`,
                      status: 'running' as const,
                      input: String(obsDel.task || ''),
                    };
                    const existsIdx = toolCalls.findIndex((t) => t.id === delId);
                    if (existsIdx !== -1) {
                      toolCalls[existsIdx] = { ...toolCalls[existsIdx], ...delCall };
                    } else {
                      toolCalls.push(delCall);
                    }
                    setActiveToolCalls([...toolCalls]);
                  } else {
                    const childRunId = String(obsDel.run_id || `child-${agentName}`);
                    const childStatus = obsDel.status === 'completed'
                      ? 'completed' as const
                      : obsDel.status === 'timed_out'
                        ? 'timed_out' as const
                        : 'failed' as const;
                    setAgentRuns((prev) => updateAgentRun(prev, childRunId, {
                      status: childStatus,
                      completedAt: Date.now(),
                      error: obsDel.error_type ? String(obsDel.error_type) : undefined,
                    }));
                    const doneStatus = obsDel.status === 'completed' ? 'done' as const : 'failed' as const;
                    const doneIdx = toolCalls.findIndex((t) => t.id === delId);
                    if (doneIdx !== -1) {
                      toolCalls[doneIdx] = {
                        ...toolCalls[doneIdx],
                        status: doneStatus,
                        duration: toolCalls[doneIdx].duration || 0,
                      };
                    } else {
                      toolCalls.push({
                        id: delId,
                        name: delName,
                        label: `Delegated to ${agentName}`,
                        status: doneStatus,
                        input: '',
                      });
                    }
                    setActiveToolCalls([...toolCalls]);
                  }
                  break;
                }
                // Session 115 + 132: the dispatcher used to emit
                // thinking_start/thinking_done with the internal routing
                // placeholder intent="dispatch", which clobbered the real
                // classification in the Observe panel. The OLD guard read
                // obs.intent (top-level) but the intent actually rides in
                // obs.data.intent — so it was dead code and the placeholder
                // still won whenever the dispatcher failed before
                // intent_classified fired. Check BOTH levels, and honor the
                // intent_classified `primary` field. Legitimate intents
                // (chat/file_write/shell) still pass through for paths that
                // skip the ThinkingDispatcher.
                const obsData = obs.data || obs;
                const isPlaceholderIntent =
                  obs.intent === 'dispatch' || obsData.intent === 'dispatch';
                const obsIntent =
                  (obs.type === 'intent_classified' ? obsData.primary : undefined) ||
                  obsData.intent ||
                  obs.intent;
                if (obsIntent && !isPlaceholderIntent) setCurrentIntent(obsIntent);
                if (obsData.confidence && !isPlaceholderIntent) {
                  setCurrentConfidence(Number(obsData.confidence));
                }
                if (obsData) {
                  // ADR-12 (B-2026-08-09-2): the engine's _StageClock emits
                  // stage_timing obs events with real per-stage latency +
                  // authoritative status (done/skipped). Accumulate them so
                  // the Observe pipeline renders truth instead of a guess.
                  if (obs.type === 'stage_timing' && obsData.stage) {
                    setLiveObservation((prev) => ({
                      intent: (prev?.intent || 'chat') as any,
                      confidence: prev?.confidence ?? 0,
                      toolsUsed: prev?.toolsUsed ?? [],
                      memoryHits: prev?.memoryHits ?? 0,
                      contextTokens: prev?.contextTokens ?? 0,
                      latency: prev?.latency ?? 0,
                      stageTimings: {
                        ...(prev?.stageTimings ?? {}),
                        [String(obsData.stage)]: {
                          latencyMs: Number(obsData.latency_ms || 0),
                          status: (obsData.status === 'skipped' || obsData.status === 'running' ? obsData.status : 'done') as any,
                        },
                      },
                      anomalies: prev?.anomalies,
                    }));
                    break;
                  }
                  setLiveObservation((prev) => ({
                    intent: (isPlaceholderIntent
                      ? (prev?.intent || 'chat')
                      : (obsIntent || prev?.intent || 'chat')) as any,
                    confidence: Number(isPlaceholderIntent
                      ? (prev?.confidence || 0)
                      : (obsData.confidence || obs.confidence || prev?.confidence || 0)),
                    // B-2026-08-09-8: an empty tools_used on turn_complete is REAL
                    // (no tools ran this turn) — reset instead of inheriting the
                    // previous turn's tools forever.
                    toolsUsed: obsData.tools_used !== undefined
                      ? (obsData.tools_used ? obsData.tools_used.split(',') : [])
                      : (prev?.toolsUsed ?? []),
                    // Backend sends 'memory_facts' in turn_complete, not 'memory_hits'.
                    // B-2026-08-09-8: a real 0 (fresh session, nothing retrieved)
                    // must not fall through to the previous turn's count.
                    memoryHits: obsData.memory_facts !== undefined
                      ? Number(obsData.memory_facts)
                      : (obsData.memory_hits !== undefined
                        ? Number(obsData.memory_hits)
                        : (prev?.memoryHits ?? 0)),
                    // 'prompt_tokens_approx' is the context/input token count.
                    // 'tokens_approx' is the completion/output token count.
                    // Use prompt_tokens_approx for the Context Tokens display.
                    // Context Tokens = prompt/input tokens ONLY. tokens_approx
                    // is the COMPLETION count and must never masquerade as
                    // context (a fast-path "Hi" would otherwise show its 9
                    // completion tokens as 9 context tokens). When the backend
                    // doesn't report a prompt count for this turn
                    // (trivial/conversational short-circuit), show a truthful
                    // 0 instead of inheriting a stale value.
                    contextTokens: Number(
                      obsData.prompt_tokens_approx !== undefined && Number(obsData.prompt_tokens_approx) > 0
                        ? obsData.prompt_tokens_approx
                        : obsData.context_tokens !== undefined && Number(obsData.context_tokens) > 0
                          ? obsData.context_tokens
                          : 0
                    ),
                    latency: Number(obsData.total_latency_ms || obsData.latency_ms || obsData.latency || prev?.latency || 0),
                    stageTimings: prev?.stageTimings,
                    anomalies: prev?.anomalies,
                  }));
                  // FIX: When tool_status=done obs event arrives, mark matching
                  // tool calls as done in the frontend. This fixes the stuck
                  // "Running command" spinner when the top-level intent completes.
                  if (obs.type === 'tool_status' && obsData.status === 'done') {
                    const doneTool = obsData.tool || '';
                    if (doneTool) {
                      setActiveToolCalls((prev) => {
                        const hasRunning = prev.some((tc) => tc.name === doneTool && isActiveToolStatus(tc.status));
                        if (!hasRunning) return prev;
                        return prev.map((tc) =>
                          tc.name === doneTool && isActiveToolStatus(tc.status)
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
                      setLastMetrics((prev) => {
                        // Some providers report latency before token usage. Keep
                        // the live estimate instead of replacing it with zero.
                        const completionTokens = _completionTokens > 0
                          ? _completionTokens
                          : prev?.completionTokens || 0;
                        const promptTokens = _estimatedPrompt > 0
                          ? _estimatedPrompt
                          : prev?.promptTokens || 0;
                        return {
                          tokensPerSecond: _elapsed_s > 0
                            ? Math.round(completionTokens / _elapsed_s * 100) / 100
                            : prev?.tokensPerSecond || 0,
                          latency: _latency,
                          totalTokens: completionTokens + promptTokens,
                          promptTokens,
                          completionTokens,
                        };
                      });
                    }
                  }
                }

                // Session 181 — F4 Frontend Phase Visibility. Handle the
                // backend obs events that surface the agent's DECISION
                // history. Each appends a phase entry to the LAST assistant
                // message's `agentPhases` array — the strip renders in
                // ChatMessage between the thinking block and tool cards.
                // The lifecycle narration (initialization/planning/thinker/
                // loop) moved to the Agents-tab run node (RUN_LIFECYCLE_TYPES
                // above) — the chat strip keeps the plan/gate/orchestrator
                // set only.
                const PHASE_EVENT_TYPES = new Set([
                  'plan_nodes_created',
                  'plan_node_advanced',
                  'agent_loop_gate_passed',
                  'agent_loop_gate_failed_replan',
                  'orchestrator_replan_start',
                  'orchestrator_replan_done',
                  'orchestrator_replan_failed',
                  'agent_loop_failure',
                ]);
                if (PHASE_EVENT_TYPES.has(obs.type)) {
                  const phase = buildAgentPhase(obs.type, obsData);
                  if (phase) {
                    setMessages((prev) => {
                      // Find the LAST assistant message — that's the one
                      // currently streaming this turn.
                      const lastAssistantIdx = [...prev]
                        .reverse()
                        .findIndex((m) => m.role === 'assistant');
                      if (lastAssistantIdx === -1) return prev;
                      const realIdx = prev.length - 1 - lastAssistantIdx;
                      const target = prev[realIdx];
                      const existingPhases = target.agentPhases ?? [];
                      // Dedupe by phase.id (some events fire once per turn).
                      if (existingPhases.some((p) => p.id === phase.id)) {
                        return prev;
                      }
                      const updated: ChatMessage = {
                        ...target,
                        agentPhases: [...existingPhases, phase],
                      };
                      const next = [...prev];
                      next[realIdx] = updated;
                      return next;
                    });
                  }
                }
                break;
              }

              case 'done': {
                // Mark ALL running tool calls as done — the response is complete
                if (toolCalls.length > 0) {
                  const hasRunning = toolCalls.some(tc => isActiveToolStatus(tc.status));
                  if (hasRunning) {
                    for (let i = 0; i < toolCalls.length; i++) {
                      if (isActiveToolStatus(toolCalls[i].status)) {
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

              // Session 344 Phase 3: structured response blocks from the
              // Presentation Intelligence layer. The backend emits these
              // alongside the text stream so the frontend can render tables,
              // charts, diagrams, and metrics natively.
              case 'response_blocks': {
                const blocks = parsed.blocks;
                if (Array.isArray(blocks) && blocks.length > 0) {
                  setMessages((prev) => {
                    const updated = [...prev];
                    const last = updated[updated.length - 1];
                    if (last && last.role === 'assistant') {
                      updated[updated.length - 1] = {
                        ...last,
                        responseBlocks: blocks,
                      };
                    }
                    return updated;
                  });
                }
                break;
              }

              case 'error': {
                const err = parsed.error;
                if (err && typeof err === 'object' && (err as any).code) {
                  // ADR-20 (Session 167): the backend now emits the canonical
                  // error OBJECT — store it on the message and let the
                  // ErrorMessage card render it. Never stuff it into content
                  // (that's what leaked the raw provider JSON into the chat).
                  setMessages((prev) => {
                    const updated = [...prev];
                    const last = updated[updated.length - 1];
                    if (last && last.role === 'assistant') {
                      updated[updated.length - 1] = {
                        ...last,
                        error: err as ModelError,
                      };
                    }
                    return updated;
                  });
                  break;
                }
                // Legacy path (old backends send a plain string): keep the
                // existing fallback — append ⚠️ text below partial content.
                const errorMsg = `⚠️ ${err || 'Failed to get a response.'}`;
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last && last.role === 'assistant') {
                    // Always surface errors. If partial content was already
                    // streamed, append the error below it so the user can see
                    // both the partial response AND the failure reason.
                    // Previously the guard `!last.content` suppressed errors
                    // when any token had been emitted — including when the
                    // adapter erroneously put error text in the text field.
                    updated[updated.length - 1] = {
                      ...last,
                      content: last.content ? `${last.content}\n\n${errorMsg}` : errorMsg,
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
                  setLastMetrics((prev) => {
                    // Providers may omit token usage on the final metrics event;
                    // preserve the live estimate when that happens.
                    const completionTokens = _tokens > 0
                      ? _tokens
                      : prev?.completionTokens || 0;
                    const promptTokens = _promptTokens > 0
                      ? _promptTokens
                      : prev?.promptTokens || 0;
                    return {
                      tokensPerSecond: _elapsed_s > 0
                        ? Math.round(completionTokens / _elapsed_s * 100) / 100
                        : prev?.tokensPerSecond || 0,
                      latency: _latency,
                      totalTokens: completionTokens + promptTokens,
                      promptTokens,
                      completionTokens,
                    };
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
                    (tc) => tc.name === termEvt.tool && isActiveToolStatus(tc.status)
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
                // Real-time progress feedback during tool execution.
                // Session 29: DON'T overwrite thinking with status text —
                // that caused "Searching the web" to appear in the chat.
                // Instead, set a separate `statusText` field that the UI
                // can show in the status area, not in the thinking block.
                const statusText = parsed.status || '';
                if (statusText) {
                  const liveElapsed = streamStartedAtRef.current
                    ? Date.now() - streamStartedAtRef.current
                    : 0;
                  setElapsedMs(liveElapsed);
                  setLastMetrics((prev) => ({
                    tokensPerSecond: prev?.tokensPerSecond || 0,
                    latency: liveElapsed,
                    totalTokens: prev?.totalTokens || 0,
                    promptTokens: prev?.promptTokens || 0,
                    completionTokens: prev?.completionTokens || 0,
                  }));
                  if (!thinkStartTime) thinkStartTime = Date.now();
                  const statusMs = thinkStartTime ? Date.now() - thinkStartTime : 0;
                  setMessages((prev) => {
                    const updated = [...prev];
                    const last = updated[updated.length - 1];
                    if (last && last.role === 'assistant') {
                      updated[updated.length - 1] = {
                        ...last,
                        statusText: statusText,
                        thinkMs: statusMs,
                        isAgent: true,
                      };
                    }
                    return updated;
                  });
                }
                break;
              }

              case 'todo_created':
              case 'todo_added': {
                // Session 27: the engine emitted a todo from its plan.
                // Dispatch a custom event so the useTodos hook can add
                // it to the todos panel.
                const todo = parsed.todo || {};
                if (todo.content || todo.text) {
                  window.dispatchEvent(new CustomEvent('localmind:todo-created', {
                    detail: {
                      ...todo,
                      text: todo.text || todo.content,
                    },
                  }));
                }
                break;
              }

              case 'todo_completed':
              case 'todo_updated': {
                // Session 27: a todo's status changed (in_progress / done).
                const todo = parsed.todo || {};
                if (todo.id || todo.order !== undefined) {
                  window.dispatchEvent(new CustomEvent('localmind:todo-updated', {
                    detail: todo,
                  }));
                }
                break;
              }

              case 'todo_cleared': {
                // Session 27: clear all todos for this session (new request).
                window.dispatchEvent(new CustomEvent('localmind:todo-cleared'));
                break;
              }

              default:
                if (parsed.content && !_isPromptLeak(parsed.content)) {
                  currentContent += parsed.content;
                  streamedProgressText += parsed.content;
                  const estimatedCompletionTokens = estimateTokens(streamedProgressText);
                  const liveElapsed = streamStartedAtRef.current
                    ? Date.now() - streamStartedAtRef.current
                    : 0;
                  setLastMetrics((prev) => ({
                    tokensPerSecond: liveElapsed > 0
                      ? Math.round(estimatedCompletionTokens / (liveElapsed / 1000) * 100) / 100
                      : 0,
                    latency: liveElapsed,
                    totalTokens: estimatedCompletionTokens + (prev?.promptTokens || 0),
                    promptTokens: prev?.promptTokens || 0,
                    completionTokens: estimatedCompletionTokens,
                  }));
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
              streamedProgressText += rawData;
              const estimatedCompletionTokens = estimateTokens(streamedProgressText);
              const liveElapsed = streamStartedAtRef.current
                ? Date.now() - streamStartedAtRef.current
                : 0;
              setLastMetrics((prev) => ({
                tokensPerSecond: liveElapsed > 0
                  ? Math.round(estimatedCompletionTokens / (liveElapsed / 1000) * 100) / 100
                  : 0,
                latency: liveElapsed,
                totalTokens: estimatedCompletionTokens + (prev?.promptTokens || 0),
                promptTokens: prev?.promptTokens || 0,
                completionTokens: estimatedCompletionTokens,
              }));
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
        // Session 142: dispatched here (stream END — after the backend's
        // post-loop _finalize_plan_todos commits) rather than on the SSE
        // 'done' event, which fires MID-stream before the DB finalize. The
        // backend always finalizes ALL plan todos in its finally block, so
        // this re-sync guarantees the Todos panel agrees with the DB — fixing
        // the persistent "task ran but checkbox stayed unchecked" report.
        () => {
          window.dispatchEvent(new CustomEvent('localmind:todo-refetch'));
          setIsStreaming(false);
          streamStartedAtRef.current = null;
          streamingSessionRef.current = null;
          abortRef.current = null;
          setAgentRuns((prev) => updateAgentRun(prev, rootRunId, {
            status: 'completed',
            completedAt: Date.now(),
          }));
          // Finalize the closure-owned list synchronously, then publish the
          // same snapshot to both the Actions state and assistant message.
          // Reading values populated inside a React state updater here is racy:
          // React may invoke that updater after this callback returns.
          const finalizedToolCalls = toolCalls.map((tc) =>
            isActiveToolStatus(tc.status)
              ? { ...tc, status: 'done' as const, duration: tc.duration || 0 }
              : tc
          );
          const didUpdate = finalizedToolCalls.some(
            (tc, index) => tc.status !== toolCalls[index].status
          );
          if (didUpdate) {
            toolCalls.splice(0, toolCalls.length, ...finalizedToolCalls);
            setActiveToolCalls(finalizedToolCalls);
            setMessages((prevMsgs) => {
              const msgs = [...prevMsgs];
              const last = msgs[msgs.length - 1];
              if (last && last.role === 'assistant' && last.toolCalls) {
                const updatedMap = new Map(finalizedToolCalls.map(tc => [tc.id, tc]));
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
          streamStartedAtRef.current = null;
          streamingSessionRef.current = null;
          abortRef.current = null;
          setAgentRuns((prev) => updateAgentRun(prev, rootRunId, {
            status: 'failed',
            completedAt: Date.now(),
            error: 'The parent agent stream failed.',
          }));
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
        // B-2026-08-09-6 (ADR-11 client half): toolHint is passed as the
        // X-LocalMind-Intent header so the backend can skip the dispatcher.
        // An explicitly-picked tool always wins; otherwise a deterministic
        // classifier hints 'chat' for obvious conversational sends. It never
        // invents a tool intent the user didn't pick.
        tool || classifyClientIntent(message)
      );

      abortRef.current = abortFn;
    },
    [sessionId]  // isStreaming is read via isStreamingRef to avoid stale closures
  );

  const steer = useCallback((message: string) => {
    const text = message.trim();
    const target = streamingSessionRef.current;
    if (!text || !isStreamingRef.current || !target) return;
    void localmindClient.steer(target, text);
  }, []);

  const abort = useCallback(() => {
    // B-2026-08-02-2 (A2): also tell the backend to stop — closing the SSE
    // stream alone left the AgentLoop running until the wall-clock cap.
    const target = streamingSessionRef.current;
    if (target) {
      void localmindClient.abort(target);
    }
    abortRef.current?.();
    abortRef.current = null;
    streamingSessionRef.current = null;
    setIsStreaming(false);
    streamStartedAtRef.current = null;
    setAgentRuns((prev) => prev.map((run) => run.status === 'running'
      ? { ...run, status: 'canceled' as const, completedAt: Date.now() }
      : run
    ));
    // Mark any running tool calls as done on abort
    setActiveToolCalls((prev) => {
      const hasRunning = prev.some((tc) => isActiveToolStatus(tc.status));
      if (!hasRunning) return prev;
      return prev.map((tc) =>
        isActiveToolStatus(tc.status)
          ? { ...tc, status: 'done' as const, duration: tc.duration || 0 }
          : tc
      );
    });
  }, []);

  // New Chat must start from a clean slate: clear the context-token counter
  // (lastMetrics/liveObservation feed it), the live metrics, the agent-run
  // tree, and the cumulative session stats. The session-switch effect can't
  // be relied on here — a client-generated new session ID is not yet known to
  // the backend, so its "clear stale data" branch never fires for it.
  const resetSession = useCallback(() => {
    setLastMetrics(null);
    setLiveObservation(null);
    setElapsedMs(0);
    setCurrentIntent(undefined);
    setCurrentConfidence(undefined);
    setActiveToolCalls([]);
    setAgentRuns([]);
    setFileDiffs({});
    applySessionStats({ ..._EMPTY_SESSION_STATS });
    lastTurnContributionRef.current = null;
    sessionStatsSeededForRef.current = null;
  }, [applySessionStats]);

  return { messages, fileDiffs, isStreaming, currentIntent, currentConfidence, activeToolCalls, agentRuns, liveObservation, lastMetrics, elapsedMs, sessionStats, send, abort, steer, setMessages, resetSession, onTerminalEvent };
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

// Canonical narrative order for the active-agent lifecycle phases (mirrors
// the backend's _LIFECYCLE_PHASE_RANK in agent_workspace.py). The loop emits
// some events out of story order (agent_loop_start fires before init), so
// the run node always reads "getting started → understood → working → done".
const LIFECYCLE_PHASE_RANK: Record<string, number> = {
  initializing: 0,
  understanding: 1,
  acknowledged: 2,
  initialized: 3,
  planned: 4,
  thinking: 5,
  thinking_done: 6,
  working: 7,
  turn_done: 8,
};

// ─── Session 181 — F4 Frontend Phase Visibility ──────────────────────
//
// buildAgentPhase converts a backend obs event into an AgentPhase entry.
// Two consumers: the chat phase strip (plan/gate/orchestrator decision
// history, via PHASE_EVENT_TYPES) and the Agents-tab run node (lifecycle
// narration, via RUN_LIFECYCLE_TYPES — the active-agent phases). Each
// event type carries different payload fields; this helper extracts the
// most informative label + detail for each. Returns null when the event
// payload is missing required fields (defensive — surfaces only render
// entries that have something useful to say).
//
// Exported for direct unit testing (Session 181).
export function buildAgentPhase(
  eventType: string,
  data: any,
): AgentPhase | null {
  const ts = Date.now();
  switch (eventType) {
    // Lifecycle phases (bootup-telemetry session) — narrate the whole turn
    // so the strip is never empty during the longest wait (the parent init
    // call on a slow model). Mirrors the backend build_agent_phases entries.
    case 'agent_initialization_start': {
      return {
        id: `phase-init-start-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'initializing',
        label: 'Getting started — understanding your request',
        timestamp: ts,
      };
    }
    case 'agent_initialization_understanding': {
      const text = String(data?.understanding ?? '').trim();
      if (!text) return null;
      return {
        id: `phase-understanding-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'understanding',
        label: 'Understanding your request',
        detail: text.slice(0, 160),
        timestamp: ts,
      };
    }
    case 'agent_initialization_ack': {
      const text = String(data?.acknowledgement ?? '').trim();
      if (!text) return null;
      return {
        id: `phase-ack-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'acknowledged',
        label: 'Acknowledged',
        detail: text.slice(0, 160),
        timestamp: ts,
      };
    }
    case 'agent_initialization_done': {
      const mode = String(data?.mode ?? '');
      const objective = String(data?.objective ?? '').slice(0, 160);
      return {
        id: `phase-init-done-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'initialized',
        label: mode ? `Understood — ${mode} mode` : 'Understood the request',
        detail: objective || undefined,
        timestamp: ts,
      };
    }
    case 'agent_thinker_start': {
      return {
        id: `phase-thinking-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'thinking',
        label: 'Thinking through the evidence',
        timestamp: ts,
        iteration: data?.iteration !== undefined ? Number(data.iteration) : undefined,
      };
    }
    case 'agent_thinker_done': {
      return {
        id: `phase-think-done-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'thinking_done',
        label: 'Analysis ready',
        timestamp: ts,
        iteration: data?.iteration !== undefined ? Number(data.iteration) : undefined,
      };
    }
    case 'agent_planning_done': {
      return {
        id: `phase-planned-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'planned',
        label: 'Plan ready — proceeding step by step',
        timestamp: ts,
        iteration: data?.iteration !== undefined ? Number(data.iteration) : undefined,
      };
    }
    case 'agent_loop_start': {
      return {
        id: `phase-working-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'working',
        label: 'Working — executing the plan',
        timestamp: ts,
      };
    }
    case 'agent_loop_done': {
      const detailParts: string[] = [];
      if (data?.direct) detailParts.push('answered directly');
      if (data?.clarification) detailParts.push('asked for clarification');
      if (data?.hit_limit) detailParts.push('iteration limit reached');
      const iterations = Number(data?.iterations ?? 0);
      if (iterations > 0) detailParts.push(`${iterations} iterations`);
      return {
        id: `phase-turn-done-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'turn_done',
        label: 'Turn complete',
        detail: detailParts.length ? detailParts.join('; ') : undefined,
        timestamp: ts,
        iteration: data?.iteration !== undefined ? Number(data.iteration) : undefined,
      };
    }
    case 'plan_nodes_created': {
      const count = Number(data?.node_count ?? 0);
      if (!count) return null;
      const ids: string[] = Array.isArray(data?.node_ids) ? data.node_ids : [];
      return {
        id: `phase-plan-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'plan_created',
        label: `Plan built — ${count} step${count === 1 ? '' : 's'}`,
        detail: ids.length ? ids.join(' → ') : undefined,
        timestamp: ts,
      };
    }
    case 'plan_node_advanced': {
      const nodeId = String(data?.node_id ?? '');
      const newStatus = String(data?.new_status ?? '');
      const subgoal = String(data?.subgoal ?? '').slice(0, 100);
      if (!nodeId) return null;
      const statusIcon = newStatus === 'completed' ? '✓' : newStatus === 'failed' ? '✗' : '~';
      return {
        id: `phase-adv-${nodeId}-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'node_advanced',
        label: `${nodeId} ${statusIcon} ${subgoal}`,
        detail: newStatus ? `status: ${newStatus}` : undefined,
        timestamp: ts,
        iteration: data?.iteration !== undefined ? Number(data.iteration) : undefined,
      };
    }
    case 'agent_loop_gate_passed': {
      const intent = String(data?.intent ?? '');
      return {
        id: `phase-gate-pass-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'gate_passed',
        label: intent ? `Verified — ${intent} acceptance gate passed` : 'Verified — acceptance gate passed',
        timestamp: ts,
        iteration: data?.iteration !== undefined ? Number(data.iteration) : undefined,
      };
    }
    case 'agent_loop_gate_failed_replan': {
      const intent = String(data?.intent ?? '');
      const unmet: string[] = Array.isArray(data?.unmet) ? data.unmet : [];
      return {
        id: `phase-gate-fail-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'gate_failed_replan',
        label: intent
          ? `Replanning — ${intent} criteria unmet`
          : 'Replanning — acceptance criteria unmet',
        detail: unmet.length ? `Unmet: ${unmet.slice(0, 3).join('; ')}` : undefined,
        timestamp: ts,
        iteration: data?.iteration !== undefined ? Number(data.iteration) : undefined,
      };
    }
    case 'orchestrator_replan_start': {
      const intent = String(data?.intent ?? '');
      return {
        id: `phase-orch-start-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'orchestrator_replan_start',
        label: intent
          ? `Orchestrator notified — ${intent} failure`
          : 'Orchestrator notified of failure',
        timestamp: ts,
        iteration: data?.iteration !== undefined ? Number(data.iteration) : undefined,
      };
    }
    case 'orchestrator_replan_done': {
      const confidence = Number(data?.confidence ?? 0);
      const intent = String(data?.intent ?? '');
      return {
        id: `phase-orch-done-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'orchestrator_replan_done',
        label: intent
          ? `Orchestrator replanned — ${intent}, confidence ${confidence.toFixed(2)}`
          : `Orchestrator replanned — confidence ${confidence.toFixed(2)}`,
        timestamp: ts,
      };
    }
    case 'orchestrator_replan_failed': {
      const error = String(data?.error ?? '');
      return {
        id: `phase-orch-fail-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'orchestrator_replan_failed',
        label: 'Orchestrator replan failed (non-fatal — using fallback)',
        detail: error ? `Error: ${error.slice(0, 120)}` : undefined,
        timestamp: ts,
      };
    }
    case 'agent_loop_failure': {
      const reason = String(data?.reason ?? data?.failure_type ?? '');
      return {
        id: `phase-fail-${ts}-${Math.random().toString(36).slice(2, 6)}`,
        type: 'agent_loop_failure',
        label: 'Agent loop terminated',
        detail: reason ? `Reason: ${reason.slice(0, 120)}` : undefined,
        timestamp: ts,
      };
    }
    default:
      return null;
  }
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
      case 'file_write': return path ? `Creating ${path.split(/[\\/]/).pop()}` : 'Creating file';
      case 'file_task': return path ? `Reading ${path.split(/[\\/]/).pop()}` : 'Reading file';
      case 'edit_file': return path ? `Editing ${path.split(/[\\/]/).pop()}` : 'Editing file';
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

export function useActions(sessionId: string | null, live = false) {
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

  // Session 118: realtime — while a turn is streaming, poll the backend
  // actions store so newly completed tools appear live in the panel. Gated
  // on `live` (the parent's isStreaming) so we don't re-render the panel
  // every 2.5s when idle (review fix: unconditional polling was wasteful).
  useEffect(() => {
    if (!sessionId || !live) return;
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => window.clearInterval(timer);
  }, [sessionId, refresh, live]);

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

export function useObjectives(sessionId: string | null) {
  const [objectives, setObjectives] = useState<Objective[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!sessionId) {
      setObjectives([]);
      setLoading(false);
      return;
    }
    const data = await localmindClient.getObjectives(sessionId);
    setObjectives(data);
    setLoading(false);
  }, [sessionId]);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      if (!sessionId) {
        if (mounted) {
          setObjectives([]);
          setLoading(false);
        }
        return;
      }
      const data = await localmindClient.getObjectives(sessionId);
      if (mounted) {
        setObjectives(data);
        setLoading(false);
      }
    };
    void load();
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, [sessionId, refresh]);

  const create = useCallback(async (prompt: string) => {
    if (!sessionId) return;
    const created = await localmindClient.createObjective(sessionId, prompt);
    setObjectives((prev) => [created, ...prev]);
  }, [sessionId]);

  const pause = useCallback(async (id: string) => {
    const updated = await localmindClient.pauseObjective(id);
    setObjectives((prev) => prev.map((item) => item.id === id ? updated : item));
  }, []);

  const resume = useCallback(async (id: string) => {
    const updated = await localmindClient.resumeObjective(id);
    setObjectives((prev) => prev.map((item) => item.id === id ? updated : item));
  }, []);

  const cancel = useCallback(async (id: string) => {
    const updated = await localmindClient.cancelObjective(id);
    setObjectives((prev) => prev.map((item) => item.id === id ? updated : item));
  }, []);

  return { objectives, loading, refresh, create, pause, resume, cancel };
}

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

  // Apply agent-created todos immediately. The backend may send either
  // `content` or `text`; the helper normalizes both and replaces a generic
  // same-ID fallback instead of silently dropping the richer task.
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      setTodos((prev) => applyTodoCreated(prev, detail || {}));
    };
    window.addEventListener('localmind:todo-created', handler);
    return () => window.removeEventListener('localmind:todo-created', handler);
  }, []);

  // Apply status transitions through the same stable ID/order contract for
  // both todo_updated and todo_completed events.
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      setTodos((prev) => applyTodoUpdated(prev, detail || {}));
    };
    window.addEventListener('localmind:todo-updated', handler);
    window.addEventListener('localmind:todo-completed', handler);
    return () => {
      window.removeEventListener('localmind:todo-updated', handler);
      window.removeEventListener('localmind:todo-completed', handler);
    };
  }, []);

  // Session 142: re-sync todos from the DB when the turn ends. The backend
  // finalizes ALL plan todos in its SSE-bridge `finally` block, so this
  // refetch makes the panel agree with the DB even when a live
  // todo_completed event was missed (silent tool runs never advance the
  // in-loop cursor — the executed step stayed 'pending' in the UI).
  useEffect(() => {
    const refetch = async () => {
      if (!sessionId) return;
      try {
        const data = await localmindClient.getTodos(sessionId);
        setTodos(data);
      } catch {
        // Best-effort — the live events already cover the common path.
      }
    };
    window.addEventListener('localmind:todo-refetch', refetch);
    return () => window.removeEventListener('localmind:todo-refetch', refetch);
  }, [sessionId]);

  // Session 29: Listen for todo-cleared events — clear all todos
  // when the engine starts a new request.
  useEffect(() => {
    const handler = () => {
      setTodos([]);
    };
    window.addEventListener('localmind:todo-cleared', handler);
    return () => window.removeEventListener('localmind:todo-cleared', handler);
  }, []);

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
      if (mounted) {
        setObservation({
          intent: data.intent,
          confidence: data.confidence,
          toolsUsed: data.toolsUsed,
          memoryHits: data.memoryHits,
          contextTokens: data.contextTokens,
          latency: data.latency,
          observation: data.observation,
          stageTimings: data.stageTimings,
        });
        setLoading(false);
      }
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

  // B-2026-08-23-14 follow-up: correct a stored fact. The id changes (it is
  // derived from the content hash), so re-fetch the whole list on success.
  const editFact = useCallback(async (id: string, content: string) => {
    try {
      await localmindClient.updateMemory(id, content);
      const data = await localmindClient.getMemory();
      setFacts(data);
    } catch { /* keep */ }
  }, []);

  return { facts, loading, refresh, storeFact, deleteFact, editFact };
}
