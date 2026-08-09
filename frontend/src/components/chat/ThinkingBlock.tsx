'use client';

import { useState, useEffect } from 'react';
import { ChevronRight, Brain, Terminal } from 'lucide-react';
import { ThinkingStep } from '@/types';

// v0.13: Dispatch steps replace LLM-generated thinking prose.
// Each step is formatted like: "[Web Search] Search: Nairobi weather"
// eslint-disable-next-line @typescript-eslint/no-unused-vars
interface DispatchStep {
  label: string;   // e.g. "Web Search"
  detail: string; // e.g. "Search: Nairobi weather"
  icon?: string;   // intent name for coloring
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function parseDispatchSteps(text: string): string {
  // If the thinking text is a structured step line, parse and render it.
  // Format: "[Label] Detail text"
  const match = text.match(/^\[(.+?)\]\s*(.+)$/);
  if (match) {
    return `${match[1]}: ${match[2]}`;
  }
  return text;
}

function getIntentColor(intent: string): string {
  const colors: Record<string, string> = {
    chat: 'text-brand-green-muted',
    web_search: 'text-brand-blue',
    web_fetch: 'text-brand-purple',
    code_exec: 'text-brand-green',
    shell: 'text-brand-amber',
    file_task: 'text-brand-amber-warm',
    file_write: 'text-brand-amber-warm',
    file_edit: 'text-brand-amber-warm',
    sysinfo: 'text-brand-green-muted',
    memory_op: 'text-brand-purple-soft',
    followup: 'text-brand-amber',
  };
  return colors[intent] || 'text-brand-green-muted';
}

interface ThinkingBlockProps {
  thinking: ThinkingStep | string;
  thinkMs?: number;
  /** Whether the parent message is still being streamed. When true, the
   *  block starts expanded so the user sees the thinking process in real-time.
   *  Once streaming ends, it auto-collapses to save space. */
  isStreaming?: boolean;
}

export function ThinkingBlock({ thinking, thinkMs, isStreaming }: ThinkingBlockProps) {
  // Start expanded during streaming so thinking content is visible.
  // Collapse automatically when streaming finishes.
  const [collapsed, setCollapsed] = useState(!isStreaming);

  // Auto-collapse when streaming transitions from true → false
  useEffect(() => {
    if (!isStreaming) {
      const timer = setTimeout(() => setCollapsed(true), 1500);
      return () => clearTimeout(timer);
    } else {
      setCollapsed(false);
    }
  }, [isStreaming]);

  const content = typeof thinking === 'string' ? thinking : thinking.content;
  const duration = thinkMs || (typeof thinking === 'object' ? undefined : undefined);

  // v0.13: Parse structured step lines from the thinking stream.
  // A step line looks like: "[Web Search] Search: Nairobi weather"
  const isStep = content.match(/^\[(.+?)\]\s*.+$/);
  const stepLabel = isStep ? isStep[1] : null;
  const stepColor = stepLabel ? getIntentColor(stepLabel.replace(/\s+/g, '_').toLowerCase()) : '';

  return (
    <div className="mb-2 border border-brand-border rounded-md overflow-hidden">
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex items-center gap-2 w-full px-3 py-1.5 bg-brand-bg-code hover:bg-brand-bg-rail transition-colors text-left"
      >
        <ChevronRight
          className={`h-3 w-3 text-brand-green-muted transition-transform shrink-0 ${
            !collapsed ? 'rotate-90' : ''
          }`}
        />
        <Brain className={`h-3 w-3 shrink-0 ${stepColor || 'text-brand-amber'}`} />
        <span className={`text-[10px] uppercase tracking-wider font-medium ${stepColor || 'text-brand-green-muted'}`}>
          {stepLabel || 'Thinking'}
        </span>
        {duration !== undefined && duration > 0 && (
          <span className="text-[9px] text-brand-amber ml-auto">
            {duration >= 1000 ? `${(duration / 1000).toFixed(1)}s` : `${duration}ms`}
          </span>
        )}
      </button>
      {!collapsed && (
        <div className="px-3 py-2 text-[11px] text-brand-green-muted whitespace-pre-wrap leading-relaxed border-t border-brand-border bg-brand-bg-dark break-words overflow-hidden">
          {stepLabel ? (
            <div className="flex items-start gap-2">
              <Terminal className={`h-3 w-3 mt-0.5 shrink-0 ${stepColor}`} />
              <span>{content}</span>
            </div>
          ) : (
            content
          )}
        </div>
      )}
    </div>
  );
}
