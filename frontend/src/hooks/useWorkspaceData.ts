/** Data hooks for the side panels: actions, files, objectives, todos, observability, metrics, models, memory. */

'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { localmindClient } from '@/lib/localmind/client';
import { applyTodoCreated, applyTodoUpdated } from '@/lib/localmind/progress';
import type {
  ActionItem,
  TodoItem,
  FileNode,
  MemoryFact,
  PerformanceMetrics,
  ObservationData,
  ModelOption,
  Objective,
} from '@/types';

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

  // Realtime — while a turn is streaming, poll the backend
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
  // Set once a live plan event has been applied for this chat. A new chat gets its id when
  // the first message is sent, so the saved-tasks fetch below can return (empty) AFTER the
  // plan's live events — it must not wipe them. The end-of-turn refetch reconciles later.
  const liveEventSeen = useRef(false);

  useEffect(() => {
    let mounted = true;
    liveEventSeen.current = false;
    const loadTodos = async () => {
      if (!sessionId) {
        queueMicrotask(() => { if (mounted) { setTodos([]); setLoading(false); } });
        return;
      }
      try {
        const data = await localmindClient.getTodos(sessionId);
        if (mounted && !liveEventSeen.current) setTodos(data);
      } catch {
        // Best-effort: keep whatever is showing; the end-of-turn refetch tries again.
      } finally {
        if (mounted) setLoading(false);
      }
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
      liveEventSeen.current = true;
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
      liveEventSeen.current = true;
      setTodos((prev) => applyTodoUpdated(prev, detail || {}));
    };
    window.addEventListener('localmind:todo-updated', handler);
    window.addEventListener('localmind:todo-completed', handler);
    return () => {
      window.removeEventListener('localmind:todo-updated', handler);
      window.removeEventListener('localmind:todo-completed', handler);
    };
  }, []);

  // Re-sync todos from the DB when the turn ends. The backend
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

  // Listen for todo-cleared events — clear all todos
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
    try { await localmindClient.updateTodo(id, { completed }, sessionId ?? undefined); }
    catch { setTodos((prev) => prev.map((t) => (t.id === id ? { ...t, completed: !completed } : t))); }
  }, [sessionId]);

  const removeTodo = useCallback(async (id: string) => {
    setTodos((prev) => prev.filter((t) => t.id !== id));
    try { await localmindClient.deleteTodo(id, sessionId ?? undefined); } catch { /* */ }
  }, [sessionId]);

  return { todos, loading, addTodo, toggleTodo, removeTodo };
}

// ─── useObservability ──────────────────────────────────────────────────

export function useObservability(sessionId: string | null) {
  // Don't default intent to 'chat' — that masks the empty state.
  // The ObservabilityTab uses hasData = confidence>0 || toolsUsed>0 || latency>0
  // to decide whether to show real data or the "—" placeholder.
  const emptyObs: ObservationData = { intent: '', confidence: 0, toolsUsed: [], memoryHits: 0, contextTokens: 0, latency: 0 };
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
  const [metrics, setMetrics] = useState<PerformanceMetrics>({ tokensPerSecond: 0, latency: 0, totalTokens: 0, promptTokens: 0, completionTokens: 0, cachedTokens: 0, llmCalls: 0 });
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

  // Correct a stored fact. The id changes (it is
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

