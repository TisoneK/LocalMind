'use client';

/**
 * ActionRow — one tool action as a calm, collapsible row (ZCode-inspired,
 * graphite-dark palette). COLLAPSED BY DEFAULT; click the chevron to expand its
 * body in place. Replaces the dense chip cluster in chat with a scannable
 * column: verb · icon · label · duration/status, expanding into a terminal /
 * diff / output treatment chosen by the tool kind.
 *
 * All color comes from the brand-* tokens (→ the Session-217 semantic anchors),
 * so it re-skins across graphite/iris/warm + light/dark with no changes here.
 */
import { useEffect, useRef, useState } from 'react';
import {
  Brain,
  ChevronDown,
  FileCode,
  FileEdit,
  FilePlus,
  Globe,
  Loader2,
  Search,
  Terminal,
} from 'lucide-react';

import { formatLatency } from '@/lib/localmind/progress';
import type { ToolCall } from '@/types';

type Verb = { word: string; className: string };

function verbFor(name: string): Verb {
  switch (name) {
    case 'edit_file':
    case 'file_edit':
    case 'propose_str_replace':
    case 'apply_proposed_edit':
      return { word: 'edit', className: 'text-brand-amber' };
    case 'file_write':
    case 'propose_write_file':
      return { word: 'create', className: 'text-brand-green' };
    case 'file_read':
    case 'file_task':
    case 'find_path':
      return { word: 'read', className: 'text-brand-blue' };
    case 'shell':
    case 'code_exec':
    case 'process':
      return { word: 'run', className: 'text-brand-purple' };
    case 'web_search':
    case 'grep':
    case 'grep_search':
    case 'system_search':
      return { word: 'search', className: 'text-brand-blue' };
    case 'web_fetch':
      return { word: 'fetch', className: 'text-brand-blue' };
    case 'web_research':
      return { word: 'research', className: 'text-brand-blue' };
    case 'memory_op':
      return { word: 'memory', className: 'text-brand-purple' };
    default:
      return { word: name.replace(/_/g, ' '), className: 'text-brand-green-muted' };
  }
}

function iconFor(name: string, cls: string) {
  const p = { className: `h-3.5 w-3.5 ${cls}` };
  if (name === 'shell' || name === 'code_exec' || name === 'process') return <Terminal {...p} />;
  if (name === 'file_write' || name === 'propose_write_file') return <FilePlus {...p} />;
  if (name === 'edit_file' || name === 'file_edit') return <FileEdit {...p} />;
  if (name.startsWith('web')) return <Globe {...p} />;
  if (name === 'memory_op') return <Brain {...p} />;
  if (name.includes('search') || name === 'grep' || name === 'find_path') return <Search {...p} />;
  return <FileCode {...p} />;
}

const isRunKind = (name: string) => name === 'shell' || name === 'code_exec' || name === 'process';
const looksLikeDiff = (text: string) =>
  /^[+-] /m.test(text) || /^@@ /m.test(text) || /^diff --git/m.test(text);

function ActionBody({ tc }: { tc: ToolCall }) {
  const output = (tc.output || '').trimEnd();
  return (
    <div className="border-t border-brand-border-soft">
      {tc.reasoning?.trim() && (
        <div className="px-3.5 py-2 border-b border-brand-border-soft">
          <div className="text-[10px] uppercase tracking-wider text-brand-green-faint mb-1">Why</div>
          <p className="text-[12px] italic text-brand-green-muted leading-snug whitespace-pre-wrap break-words">
            {tc.reasoning.trim()}
          </p>
        </div>
      )}

      {isRunKind(tc.name) ? (
        <div className="font-mono text-[12px] leading-relaxed bg-brand-bg-deep px-3.5 py-2.5 overflow-x-auto">
          {tc.input && (
            <div className="flex gap-2">
              <span className="text-brand-green shrink-0">❯</span>
              <span className="text-brand-green-soft whitespace-pre-wrap break-all">{tc.input}</span>
            </div>
          )}
          {output && (
            <pre className="mt-1 whitespace-pre-wrap break-words text-brand-green-muted max-h-72 overflow-y-auto">{output}</pre>
          )}
        </div>
      ) : looksLikeDiff(output) ? (
        <div className="font-mono text-[12px] leading-relaxed bg-brand-bg-deep px-3.5 py-2 overflow-x-auto max-h-72 overflow-y-auto">
          {output.split('\n').map((line, i) => {
            const add = line.startsWith('+') && !line.startsWith('+++');
            const del = line.startsWith('-') && !line.startsWith('---');
            const cls = add
              ? 'text-brand-gh-green-soft bg-brand-gh-green-bg border-l-2 border-brand-gh-green'
              : del
                ? 'text-brand-gh-red-soft bg-brand-gh-red-bg border-l-2 border-brand-gh-red'
                : line.startsWith('@@')
                  ? 'text-brand-blue'
                  : 'text-brand-green-muted border-l-2 border-transparent';
            return (
              <div key={i} className={`whitespace-pre px-2 ${cls}`}>
                {line || ' '}
              </div>
            );
          })}
        </div>
      ) : (
        (tc.input || output) && (
          <div className="px-3.5 py-2.5 space-y-1.5">
            {tc.input && (
              <div className="font-mono text-[12px] text-brand-green-soft whitespace-pre-wrap break-words">
                <span className="text-brand-green-faint">$ </span>
                {tc.input}
              </div>
            )}
            {output && (
              <pre className="font-mono text-[12px] text-brand-green-muted whitespace-pre-wrap break-words max-h-72 overflow-y-auto">{output}</pre>
            )}
          </div>
        )
      )}

      {tc.error?.trim() && (
        <div className="px-3.5 py-2 border-t border-brand-border-soft text-[12px] font-mono text-brand-red whitespace-pre-wrap break-words">
          {tc.error.trim()}
        </div>
      )}
    </div>
  );
}

interface ActionRowsProps {
  toolCalls: ToolCall[];
  /** From a Turn Anatomy segment click: open + scroll the matching row. */
  focusSignal?: { toolId: string; at: number } | null;
}

export function ActionRows({ toolCalls, focusSignal }: ActionRowsProps) {
  const [openIds, setOpenIds] = useState<Set<string>>(() => new Set());
  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({});

  // A timeline segment above was clicked → open that row and scroll to it.
  useEffect(() => {
    const id = focusSignal?.toolId;
    if (!id) return;
    setOpenIds((cur) => (cur.has(id) ? cur : new Set(cur).add(id)));
    const el = rowRefs.current[id];
    el?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
  }, [focusSignal]);

  const toggle = (id: string) =>
    setOpenIds((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="flex flex-col gap-1.5 my-1.5" data-testid="action-rows">
      {toolCalls.map((tc) => {
        const open = openIds.has(tc.id);
        const verb = verbFor(tc.name);
        const label =
          tc.label || tc.name.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
        const running = tc.status === 'running' || tc.status === 'in_progress' || tc.status === 'started';
        const failed = tc.status === 'failed';
        const hasBody = !!(tc.reasoning?.trim() || tc.input || tc.output || tc.error);
        const dur = tc.duration !== undefined ? formatLatency(tc.duration) : '';
        return (
          <div
            key={tc.id}
            ref={(el) => { rowRefs.current[tc.id] = el; }}
            data-tool-row={tc.id}
            className={`rounded-lg border bg-brand-bg-panel-alt overflow-hidden transition-colors ${
              open ? 'border-brand-border-strong' : 'border-brand-border'
            }`}
          >
            <button
              type="button"
              disabled={!hasBody}
              onClick={() => hasBody && toggle(tc.id)}
              aria-expanded={open}
              className={`w-full flex items-center gap-2.5 px-3.5 py-2 text-left ${
                hasBody ? 'cursor-pointer hover:bg-brand-bg-panel' : 'cursor-default'
              }`}
            >
              <span className={`text-[12px] shrink-0 ${verb.className}`}>
                {verb.word.charAt(0).toUpperCase() + verb.word.slice(1)}
              </span>
              {iconFor(tc.name, verb.className)}
              <span className="text-[13px] text-brand-green-soft font-medium truncate">{label}</span>
              <span className="ml-auto flex items-center gap-2.5 shrink-0">
                {failed && (
                  <span className="text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full text-brand-red bg-brand-red/10">
                    failed
                  </span>
                )}
                {running && <Loader2 className="h-3 w-3 animate-spin text-brand-amber" />}
                {dur && <span className="font-mono text-[11px] text-brand-green-faint tabular-nums">{dur}</span>}
                {/* expand/collapse affordance — on the RIGHT, rotates when open */}
                <ChevronDown
                  className={`h-3.5 w-3.5 shrink-0 text-brand-green-faint transition-transform ${
                    open ? 'rotate-180' : ''
                  } ${hasBody ? '' : 'opacity-0'}`}
                />
              </span>
            </button>
            {open && hasBody && <ActionBody tc={tc} />}
          </div>
        );
      })}
    </div>
  );
}
