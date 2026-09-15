import type { TodoItem, ToolStatus } from '@/types';

export interface RawTodoEvent {
  id?: string;
  text?: string;
  content?: string;
  completed?: boolean;
  status?: TodoItem['status'];
  order?: number;
  sessionId?: string;
  session_id?: string;
  /** Short user-facing label, preferred over content. */
  title?: string;
}

/** Statuses that mean a tool is still executing and should remain active in UI. */
export function isActiveToolStatus(status: ToolStatus | string | undefined): boolean {
  return status === 'running' || status === 'started' || status === 'in_progress' || status === 'pending';
}

/** Normalize backend todo fields into the UI's canonical shape. */
export function normalizeTodoEvent(raw: RawTodoEvent): TodoItem | null {
  // The visible label prefers the short title; the full
  // content stays available for the agent + tooltips.
  const content = raw.content || raw.text || '';
  const title = raw.title || raw.text || '';
  const text = title || content;
  if (!text && !raw.id) return null;

  return {
    id: raw.id || `todo-${Date.now()}`,
    text,
    completed: raw.completed === true || raw.status === 'done',
    ...(raw.title ? { title: raw.title } : {}),
    ...(raw.content && raw.content !== text ? { content: raw.content } : {}),
    ...(raw.status ? { status: raw.status } : {}),
    ...(raw.order !== undefined ? { order: raw.order } : {}),
    ...(raw.sessionId || raw.session_id
      ? { sessionId: raw.sessionId || raw.session_id }
      : {}),
  };
}

/** Add a streamed todo, replacing a same-ID generic fallback when needed. */
export function applyTodoCreated(todos: TodoItem[], raw: RawTodoEvent): TodoItem[] {
  const next = normalizeTodoEvent(raw);
  if (!next) return todos;

  const byId = todos.findIndex((todo) => todo.id === next.id);
  if (byId !== -1) {
    const updated = [...todos];
    updated[byId] = { ...updated[byId], ...next };
    return updated;
  }

  if (todos.some((todo) => todo.text === next.text)) return todos;
  return [...todos, next];
}

/** Apply a streamed status event by stable ID, or by plan order as fallback. */
export function applyTodoUpdated(todos: TodoItem[], raw: RawTodoEvent): TodoItem[] {
  const index = raw.id
    ? todos.findIndex((todo) => todo.id === raw.id)
    : raw.order !== undefined
      ? todos.findIndex((todo) => todo.order === raw.order)
      : -1;
  const fallbackIndex = index === -1 && raw.order !== undefined ? raw.order : index;
  if (fallbackIndex < 0 || fallbackIndex >= todos.length) return todos;

  const updated = [...todos];
  const current = updated[fallbackIndex];
  updated[fallbackIndex] = {
    ...current,
    ...(raw.status ? { status: raw.status } : {}),
    completed: raw.completed === true || raw.status === 'done' || current.completed,
  };
  return updated;
}

/** Conservative live estimate used until the backend sends final token usage. */
export function estimateTokens(text: string): number {
  const trimmed = text.trim();
  return trimmed ? Math.ceil(trimmed.length / 4) : 0;
}

/**
 * Adaptive latency formatting shared by every surface that shows time:
 * <1s → whole ms ("340ms"), ≥1s → seconds ("39.9s"),
 * ≥60s → minutes+seconds ("1m 23s"), ≥1h → hours+minutes ("1h 5m").
 * Natural duration formatting.
 */
export function formatLatency(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return '—';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const totalSec = ms / 1000;
  if (totalSec < 60) return `${totalSec.toFixed(1)}s`;
  const totalMin = totalSec / 60;
  if (totalMin < 60) {
    const m = Math.floor(totalMin);
    const s = Math.round(totalSec - m * 60);
    return s > 0 ? `${m}m ${s}s` : `${m}m`;
  }
  const h = Math.floor(totalMin / 60);
  const m = Math.round(totalMin - h * 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

/**
 * Compact token count formatting: 128000 → "128K", 1500000 → "1.5M".
 * Short-form token display across all UI surfaces.
 */
export function formatTokens(n: number): string {
  if (!Number.isFinite(n) || n < 0) return '—';
  if (n < 1000) return String(n);
  if (n < 1_000_000) {
    const k = n / 1000;
    return k >= 100 ? `${Math.round(k)}K` : `${k.toFixed(1)}K`;
  }
  const m = n / 1_000_000;
  return m >= 100 ? `${Math.round(m)}M` : `${m.toFixed(1)}M`;
}
