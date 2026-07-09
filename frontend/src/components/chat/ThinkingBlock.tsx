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
    chat: 'text-[#8ab08a]',
    web_search: 'text-[#4a9eff]',
    web_fetch: 'text-[#9b8afb]',
    code_exec: 'text-[#39d353]',
    shell: 'text-[#e8a420]',
    file_task: 'text-[#f5a623]',
    file_write: 'text-[#f5a623]',
    file_edit: 'text-[#f5a623]',
    sysinfo: 'text-[#8ab08a]',
    memory_op: 'text-[#d4a8ff]',
    followup: 'text-[#e8a420]',
  };
  return colors[intent] || 'text-[#8ab08a]';
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
    <div className="mb-2 border border-[#1a2a1a] rounded-md overflow-hidden">
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex items-center gap-2 w-full px-3 py-1.5 bg-[#0a120a] hover:bg-[#111a11] transition-colors text-left"
      >
        <ChevronRight
          className={`h-3 w-3 text-[#8ab08a] transition-transform shrink-0 ${
            !collapsed ? 'rotate-90' : ''
          }`}
        />
        <Brain className={`h-3 w-3 shrink-0 ${stepColor || 'text-[#e8a420]'}`} />
        <span className={`text-[10px] uppercase tracking-wider font-medium ${stepColor || 'text-[#8ab08a]'}`}>
          {stepLabel || 'Thinking'}
        </span>
        {duration !== undefined && duration > 0 && (
          <span className="text-[9px] text-[#e8a420] ml-auto">
            {duration >= 1000 ? `${(duration / 1000).toFixed(1)}s` : `${duration}ms`}
          </span>
        )}
      </button>
      {!collapsed && (
        <div className="px-3 py-2 text-[11px] text-[#8ab08a] whitespace-pre-wrap leading-relaxed border-t border-[#1a2a1a] bg-[#080d08] break-words overflow-hidden">
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
