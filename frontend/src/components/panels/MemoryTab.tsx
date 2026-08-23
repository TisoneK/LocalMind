'use client';

import { useEffect, useMemo, useState } from 'react';
import { Database, TrendingUp, Clock, Trash2, Plus, Search, X, Loader2 } from 'lucide-react';
import { MemoryFact } from '@/types';

interface MemoryTabProps {
  facts: MemoryFact[];
  onDelete?: (id: string) => void;
  /** Persist a manually entered fact via the memory API (POST /api/memory). */
  onStore?: (content: string, source: string) => Promise<void>;
  /** Re-fetch facts (used by the tab's polling while it is visible). */
  onRefresh?: () => Promise<void>;
}

function RelevanceBar({ value }: { value: number }) {
  // Guard against NaN / undefined / null values.
  // Normalize: if value > 1, assume it's already on a 0-100 scale.
  const raw = Number.isFinite(value) ? value : 0;
  const normalized = raw > 1 ? raw / 100 : raw;
  const percentage = Math.round(normalized * 100);
  const color = normalized >= 0.9 ? 'bg-brand-green' : normalized >= 0.8 ? 'bg-brand-amber' : 'bg-brand-green-muted';

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1 bg-brand-border rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${percentage}%` }} />
      </div>
      <span className="text-[9px] text-brand-green-muted font-mono w-8 text-right">{percentage}%</span>
    </div>
  );
}

function formatMemoryTimestamp(ts: string): string {
  if (!ts) return '';
  // If it looks like an epoch timestamp (number or numeric string)
  const num = parseFloat(ts);
  if (!isNaN(num) && num > 1e9) {
    const ms = num > 1e12 ? num : num * 1000;
    const d = new Date(ms);
    if (!isNaN(d.getTime())) {
      const now = new Date();
      if (d.toDateString() === now.toDateString()) {
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      }
      return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    }
  }
  // If it's an ISO string or already formatted, try to parse and reformat
  const d = new Date(ts);
  if (!isNaN(d.getTime())) {
    const now = new Date();
    if (d.toDateString() === now.toDateString()) {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  }
  return ts;
}

export function MemoryTab({ facts, onDelete, onStore, onRefresh }: MemoryTabProps) {
  const safeFacts = facts ?? [];
  const [query, setQuery] = useState('');
  // Manual store affordance (B-2026-08-23-14).
  const [draft, setDraft] = useState('');
  const [storing, setStoring] = useState(false);
  const [storeError, setStoreError] = useState<string | null>(null);

  // Live refresh: while the tab is visible, poll so facts stored by the agent
  // mid-session appear without a manual reload. Polling stops on unmount.
  useEffect(() => {
    if (!onRefresh) return;
    const timer = window.setInterval(() => void onRefresh(), 4000);
    return () => window.clearInterval(timer);
  }, [onRefresh]);

  const avgRelevance = safeFacts.length > 0
    ? Math.round((safeFacts.reduce((a, f) => a + (Number.isFinite(f.relevance) ? f.relevance : 0), 0) / safeFacts.length) * 100)
    : 0;

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return safeFacts;
    return safeFacts.filter(
      (f) => f.content.toLowerCase().includes(q) || f.source.toLowerCase().includes(q)
    );
  }, [safeFacts, query]);

  const handleStore = async () => {
    const content = draft.trim();
    if (!content || !onStore) return;
    setStoring(true);
    setStoreError(null);
    try {
      await onStore(content, 'manual');
      setDraft('');
    } catch {
      setStoreError('Failed to store fact');
    } finally {
      setStoring(false);
    }
  };

  return (
    <div className="space-y-3 p-3">
      {/* Header stats */}
      <div className="grid grid-cols-2 gap-2">
        <div className="bg-brand-bg-code border border-brand-border rounded-md px-2.5 py-2">
          <div className="flex items-center gap-1.5 mb-1">
            <Database className="h-3 w-3 text-brand-green" />
            <span className="text-[9px] text-brand-green-muted uppercase tracking-wider">Facts</span>
          </div>
          <span className="text-lg font-mono text-brand-green-soft font-bold">{safeFacts.length}</span>
        </div>
        <div className="bg-brand-bg-code border border-brand-border rounded-md px-2.5 py-2">
          <div className="flex items-center gap-1.5 mb-1">
            <TrendingUp className="h-3 w-3 text-brand-amber" />
            <span className="text-[9px] text-brand-green-muted uppercase tracking-wider">Avg Rel</span>
          </div>
          <span className="text-lg font-mono text-brand-green-soft font-bold">
            {avgRelevance}%
          </span>
        </div>
      </div>

      {/* Manual store affordance (B-2026-08-23-14) */}
      {onStore && (
        <div className="bg-brand-bg-code border border-brand-border rounded-md p-2" data-testid="memory-store">
          <div className="flex items-center gap-1.5 mb-1.5">
            <Plus className="h-3 w-3 text-brand-green" />
            <span className="text-[10px] uppercase tracking-wider text-brand-green-muted font-medium">
              Store a fact
            </span>
          </div>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="e.g. The user prefers dark mode…"
            rows={2}
            className="w-full p-1.5 rounded border border-brand-border bg-brand-bg-base text-[11px] text-brand-green-soft placeholder:text-brand-green-faint focus:outline-none focus:border-brand-green/40 resize-none"
            data-testid="memory-store-input"
          />
          {storeError && <div className="mt-1 text-[10px] text-brand-red">{storeError}</div>}
          <button
            onClick={handleStore}
            disabled={storing || !draft.trim()}
            className="mt-1.5 w-full flex items-center justify-center gap-1 px-2 py-1 text-[10px] rounded bg-brand-green/10 text-brand-green hover:bg-brand-green/20 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            data-testid="memory-store-button"
          >
            {storing ? <Loader2 className="h-2.5 w-2.5 animate-spin" /> : <Plus className="h-2.5 w-2.5" />}
            {storing ? 'Storing…' : 'Store fact'}
          </button>
        </div>
      )}

      {/* Filter box */}
      {safeFacts.length > 0 && (
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-brand-green-muted" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter facts…"
            className="w-full pl-7 pr-6 py-1 rounded-md border border-brand-border bg-brand-bg-panel text-[11px] text-brand-green-soft placeholder:text-brand-green-faint focus:outline-none focus:border-brand-green/40"
            data-testid="memory-filter"
          />
          {query && (
            <button
              onClick={() => setQuery('')}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 rounded text-brand-green-muted hover:text-brand-green"
              title="Clear filter"
              data-testid="memory-filter-clear"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      )}

      {/* Recent facts */}
      <div>
        <div className="flex items-center gap-1.5 mb-2">
          <Database className="h-3 w-3 text-brand-green" />
          <span className="text-[10px] uppercase tracking-wider text-brand-green-muted font-medium">
            Recent Facts
          </span>
          {query && (
            <span className="text-[9px] text-brand-green-faint ml-auto">
              {filtered.length} / {safeFacts.length}
            </span>
          )}
        </div>
        <div className="space-y-1.5 max-h-72 overflow-y-auto custom-scrollbar">
          {safeFacts.length === 0 ? (
            <div className="px-2.5 py-4 text-center text-[10px] text-brand-green-faint italic" data-testid="memory-empty">
              No facts stored yet — facts the agent remembers will appear here.
            </div>
          ) : filtered.length === 0 ? (
            <div className="px-2.5 py-4 text-center text-[10px] text-brand-green-faint italic" data-testid="memory-filter-empty">
              No facts match “{query.trim()}”
            </div>
          ) : (
            filtered.map((fact) => (
              <div
                key={fact.id}
                className="bg-brand-bg-code border border-brand-border rounded-md px-2.5 py-2 hover:border-brand-border transition-colors"
              >
                <div className="text-[11px] text-brand-green-soft leading-relaxed mb-1.5">
                  {fact.content}
                </div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-[9px] px-1 py-0.5 rounded bg-brand-border text-brand-green-muted">
                      {fact.source}
                    </span>
                    <span className="text-[9px] text-brand-green-muted flex items-center gap-0.5">
                      <Clock className="h-2.5 w-2.5" />
                      {formatMemoryTimestamp(fact.timestamp)}
                    </span>
                  </div>
                  {onDelete && (
                    <button
                      onClick={() => onDelete(fact.id)}
                      className="p-0.5 rounded text-brand-green-muted hover:text-brand-red hover:bg-brand-border transition-colors"
                      title="Delete fact"
                    >
                      <Trash2 className="h-2.5 w-2.5" />
                    </button>
                  )}
                </div>
                <div className="mt-1.5">
                  <RelevanceBar value={fact.relevance} />
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
