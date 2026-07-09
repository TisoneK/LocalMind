'use client';

import { Database, TrendingUp, Clock, Trash2 } from 'lucide-react';
import { MemoryFact } from '@/types';

interface MemoryTabProps {
  facts: MemoryFact[];
  onDelete?: (id: string) => void;
}

function RelevanceBar({ value }: { value: number }) {
  // Guard against NaN / undefined / null values.
  // Normalize: if value > 1, assume it's already on a 0-100 scale.
  const raw = Number.isFinite(value) ? value : 0;
  const normalized = raw > 1 ? raw / 100 : raw;
  const percentage = Math.round(normalized * 100);
  const color = normalized >= 0.9 ? 'bg-[#39d353]' : normalized >= 0.8 ? 'bg-[#e8a420]' : 'bg-[#8ab08a]';

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1 bg-[#1a2a1a] rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${percentage}%` }} />
      </div>
      <span className="text-[9px] text-[#8ab08a] font-mono w-8 text-right">{percentage}%</span>
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

export function MemoryTab({ facts, onDelete }: MemoryTabProps) {
  // FIX: Guard against division by zero when facts array is empty.
  // Previously, facts.length === 0 caused NaN% in the Avg Rel display
  // because (0 / 0) * 100 = NaN.
  const safeFacts = facts ?? [];
  const avgRelevance = safeFacts.length > 0
    ? Math.round((safeFacts.reduce((a, f) => a + (Number.isFinite(f.relevance) ? f.relevance : 0), 0) / safeFacts.length) * 100)
    : 0;

  return (
    <div className="space-y-3 p-3">
      {/* Header stats */}
      <div className="grid grid-cols-2 gap-2">
        <div className="bg-[#0a120a] border border-[#1a2a1a] rounded-md px-2.5 py-2">
          <div className="flex items-center gap-1.5 mb-1">
            <Database className="h-3 w-3 text-[#39d353]" />
            <span className="text-[9px] text-[#8ab08a] uppercase tracking-wider">Facts</span>
          </div>
          <span className="text-lg font-mono text-[#d4e8d4] font-bold">{safeFacts.length}</span>
        </div>
        <div className="bg-[#0a120a] border border-[#1a2a1a] rounded-md px-2.5 py-2">
          <div className="flex items-center gap-1.5 mb-1">
            <TrendingUp className="h-3 w-3 text-[#e8a420]" />
            <span className="text-[9px] text-[#8ab08a] uppercase tracking-wider">Avg Rel</span>
          </div>
          <span className="text-lg font-mono text-[#d4e8d4] font-bold">
            {avgRelevance}%
          </span>
        </div>
      </div>

      {/* Vector store hits */}
      <div>
        <div className="flex items-center gap-1.5 mb-2">
          <Database className="h-3 w-3 text-[#39d353]" />
          <span className="text-[10px] uppercase tracking-wider text-[#8ab08a] font-medium">
            Recent Facts
          </span>
        </div>
        <div className="space-y-1.5 max-h-72 overflow-y-auto custom-scrollbar">
          {safeFacts.map((fact) => (
            <div
              key={fact.id}
              className="bg-[#0a120a] border border-[#1a2a1a] rounded-md px-2.5 py-2 hover:border-[#1a2a1a] transition-colors"
            >
              <div className="text-[11px] text-[#d4e8d4] leading-relaxed mb-1.5">
                {fact.content}
              </div>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-[9px] px-1 py-0.5 rounded bg-[#1a2a1a] text-[#8ab08a]">
                    {fact.source}
                  </span>
                  <span className="text-[9px] text-[#8ab08a] flex items-center gap-0.5">
                    <Clock className="h-2.5 w-2.5" />
                    {formatMemoryTimestamp(fact.timestamp)}
                  </span>
                </div>
                {onDelete && (
                  <button
                    onClick={() => onDelete(fact.id)}
                    className="p-0.5 rounded text-[#8ab08a] hover:text-[#e05555] hover:bg-[#1a2a1a] transition-colors"
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
          ))}
        </div>
      </div>
    </div>
  );
}
