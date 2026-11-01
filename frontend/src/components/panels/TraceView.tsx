'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { RefreshCw, ChevronDown, ChevronRight, Route } from 'lucide-react';
import {
  localmindClient,
  TraceSummary,
  TurnTrace,
  TraceEventRecord,
} from '@/lib/localmind/client';

/**
 * Turn Trace — the durable per-turn execution record, rendered.
 *
 * The observability brief's central ask: open any conversation, inspect its
 * complete execution trajectory, and explain exactly what happened at every
 * stage. This panel lists the session's retained turn traces (the newest
 * per-turn event streams kept server-side) and renders the selected turn's
 * raw event stream — routing decision, context assembly, model-call
 * boundaries (submit → response → first byte → completed), tool work, gates,
 * replans — straight from the record, not a projection.
 */

/** Events worth highlighting at a glance in the stream. */
const KEY_EVENTS = new Set([
  'path_selected',
  'context_assembly_started',
  'context_assembly_completed',
  'model_call_started',
  'model_call_response',
  'model_call_first_byte',
  'model_call_completed',
  'model_call_failed',
  'model_call_retry',
  'stage_skipped',
  'turn_complete',
  'agent_loop_start',
  'agent_loop_done',
  'safety_blocked',
]);

function fmtTime(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour12: false }) + '.' + String(d.getMilliseconds()).padStart(3, '0');
}

/** One-line human summary of an event's most useful fields. */
function eventSummary(data: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const key of [
    'path',
    'lane',
    'reason',
    'stage',
    'phase',
    'iteration',
    'call_id',
    'provider',
    'model',
    'intent',
    'status',
    'duration_ms',
    'first_byte_at',
    'response_at',
    'submitted_at',
    'elapsed_ms',
    'payload_chars',
    'tool_count',
  ]) {
    if (data[key] !== undefined && data[key] !== '') parts.push(`${key}=${String(data[key])}`);
  }
  const usage = data.usage as Record<string, unknown> | undefined;
  if (usage && typeof usage === 'object') {
    const bits: string[] = [];
    if (usage.prompt_tokens !== undefined) bits.push(`in ${usage.prompt_tokens}`);
    if (usage.completion_tokens !== undefined) bits.push(`out ${usage.completion_tokens}`);
    if (usage.cached_tokens !== undefined) bits.push(`cached ${usage.cached_tokens}`);
    if (bits.length) parts.push(`usage: ${bits.join(' / ')}`);
  }
  return parts.join(' · ');
}

interface TraceViewProps {
  /** The active chat session — traces are per session. */
  sessionId?: string | null;
}

export function TraceView({ sessionId }: TraceViewProps) {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [trace, setTrace] = useState<TurnTrace | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const loadList = useCallback(async () => {
    if (!sessionId) return;
    setError(null);
    try {
      const res = await localmindClient.listTurnTraces(sessionId);
      setTraces(res.traces || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [sessionId]);

  const loadTrace = useCallback(async (turnId: string) => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    setExpanded(new Set());
    try {
      const res = await localmindClient.getTurnTrace(sessionId, turnId);
      setTrace(res);
      // Auto-expand the first few key events so the shape is visible at once.
      const init = new Set<number>();
      for (const evt of res.events) {
        if (KEY_EVENTS.has(evt.type) && init.size < 6) init.add(evt.seq);
      }
      setExpanded(init);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setTrace(null);
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    setTrace(null);
    setSelected(null);
    setTraces([]);
    loadList();
  }, [sessionId, loadList]);

  if (!sessionId) {
    return (
      <div className="p-4 text-[11px] text-brand-green-muted">
        Open a chat to inspect its recorded turn executions.
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full text-[11px]">
      {/* Turn list */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-brand-border">
        <span className="flex items-center gap-1.5 font-medium text-brand-green-soft">
          <Route className="h-3 w-3" /> Turn traces
        </span>
        <button
          onClick={loadList}
          className="p-1 rounded hover:bg-brand-border text-brand-green-muted hover:text-brand-green-soft"
          title="Refresh trace list"
        >
          <RefreshCw className="h-3 w-3" />
        </button>
      </div>
      {error && (
        <div className="px-3 py-2 text-red-400/90 break-words">{error}</div>
      )}
      <div className="max-h-40 overflow-y-auto custom-scrollbar border-b border-brand-border">
        {traces.length === 0 && !error && (
          <div className="px-3 py-2 text-brand-green-muted">
            No recorded traces yet — they persist as turns complete.
          </div>
        )}
        {traces.map((t) => (
          <button
            key={t.turnId}
            onClick={() => {
              setSelected(t.turnId);
              loadTrace(t.turnId);
            }}
            className={`w-full text-left px-3 py-1.5 hover:bg-brand-bg-panel-alt ${
              selected === t.turnId ? 'bg-brand-border/60 text-brand-green-soft' : 'text-brand-green-muted'
            }`}
          >
            <span className="font-mono">{t.turnId}</span>
            <span className="float-right">
              {t.eventCount} events · {fmtTime(t.startedTs)}
            </span>
          </button>
        ))}
      </div>

      {/* Selected turn's event stream */}
      <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
        {loading && <div className="px-3 py-2 text-brand-green-muted">Loading trace…</div>}
        {!loading && !trace && selected === null && (
          <div className="px-3 py-2 text-brand-green-muted">
            Select a turn to inspect its complete execution trajectory.
          </div>
        )}
        {trace && (
          <div className="divide-y divide-brand-border/50">
            {trace.events.map((evt: TraceEventRecord) => {
              const isKey = KEY_EVENTS.has(evt.type);
              const isOpen = expanded.has(evt.seq);
              const summary = eventSummary(evt.data);
              return (
                <div key={evt.seq} className={isKey ? 'bg-brand-bg-panel-alt/40' : ''}>
                  <button
                    onClick={() =>
                      setExpanded((prev) => {
                        const next = new Set(prev);
                        if (next.has(evt.seq)) next.delete(evt.seq);
                        else next.add(evt.seq);
                        return next;
                      })
                    }
                    className="w-full text-left px-3 py-1.5 hover:bg-brand-bg-panel-alt"
                  >
                    <span className="inline-flex items-center gap-1">
                      {isOpen ? (
                        <ChevronDown className="h-3 w-3 text-brand-green-muted" />
                      ) : (
                        <ChevronRight className="h-3 w-3 text-brand-green-muted" />
                      )}
                      <span className="font-mono text-brand-green-muted">#{evt.seq}</span>
                      <span
                        className={`font-medium ${
                          evt.type.startsWith('model_call_failed') || evt.type === 'safety_blocked'
                            ? 'text-red-400/90'
                            : isKey
                              ? 'text-brand-green-soft'
                              : 'text-brand-green-muted'
                        }`}
                      >
                        {evt.type}
                      </span>
                      <span className="text-brand-green-muted">+{evt.ts - trace.startedTs}ms</span>
                    </span>
                    {summary && (
                      <div className="pl-6 text-brand-green-muted truncate">{summary}</div>
                    )}
                  </button>
                  {isOpen && (
                    <pre className="mx-3 mb-2 p-2 rounded bg-brand-bg-panel text-[10px] leading-snug overflow-x-auto custom-scrollbar text-brand-green-soft/90">
                      {JSON.stringify(evt.data, null, 2)}
                    </pre>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
