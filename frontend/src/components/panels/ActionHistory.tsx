'use client';

import {
  FileEdit,
  FileSearch,
  Search,
  Terminal,
  Brain,
  Globe,
  ChevronDown,
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
  Copy,
  Check,
  Zap,
  ListChecks,
} from 'lucide-react';
import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ActionItem } from '@/types';
import { useEnterMotion } from '@/lib/localmind/motion';
import { formatLatency } from '@/lib/localmind/progress';

function isRunning(status: ActionItem['status']): boolean {
  return status === 'running' || status === 'started' || status === 'in_progress';
}

const isRunKind = (type: ActionItem['type']) => type === 'shell' || type === 'code_exec';
const looksLikeDiff = (text: string) =>
  /^[+-] /m.test(text) || /^@@ /m.test(text) || /^diff --git/m.test(text);

interface ActionHistoryProps {
  actions: ActionItem[];
}

const actionIcons: Record<ActionItem['type'], React.ReactNode> = {
  file_write: <FileEdit className="h-3 w-3" />,
  file_read: <FileSearch className="h-3 w-3" />,
  file_task: <FileSearch className="h-3 w-3" />,
  grep: <Search className="h-3 w-3" />,
  code_exec: <Terminal className="h-3 w-3" />,
  shell: <Terminal className="h-3 w-3" />,
  memory_op: <Brain className="h-3 w-3" />,
  web_search: <Globe className="h-3 w-3" />,
  sysinfo: <Search className="h-3 w-3" />,
};

const actionColors: Record<ActionItem['type'], string> = {
  file_write: 'text-brand-green',
  file_read: 'text-brand-green-muted',
  file_task: 'text-brand-green-muted',
  grep: 'text-brand-amber',
  code_exec: 'text-brand-green',
  shell: 'text-brand-green',
  memory_op: 'text-brand-green-muted',
  web_search: 'text-brand-amber',
  sysinfo: 'text-brand-green-muted',
};

const statusConfig: Record<string, { icon: React.ReactNode; color: string; label: string }> = {
  running: {
    icon: <Loader2 className="h-2.5 w-2.5 animate-spin" />,
    color: 'text-brand-amber',
    label: 'running',
  },
  done: {
    icon: <CheckCircle2 className="h-2.5 w-2.5" />,
    color: 'text-brand-green',
    label: 'done',
  },
  failed: {
    icon: <XCircle className="h-2.5 w-2.5" />,
    color: 'text-brand-red',
    label: 'failed',
  },
  pending: {
    icon: <Clock className="h-2.5 w-2.5" />,
    color: 'text-brand-green-muted',
    label: 'pending',
  },
};

/**
 * Pretty-print tool input when it is JSON. JSON tool args arrive as a compact
 * single-line string; expanding them with 2-space indent + syntax colouring
 * makes the action trace readable instead of a wall of escaped text.
 */
function formatInput(raw: string): { text: string; isJson: boolean } {
  const trimmed = raw.trim();
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      return { text: JSON.stringify(JSON.parse(trimmed), null, 2), isJson: true };
    } catch {
      // Not valid JSON — render verbatim.
    }
  }
  return { text: raw, isJson: false };
}

// Matches, in priority order: a JSON string (+ optional `:` so keys can be
// distinguished from values), a number, a boolean/null literal, a structural
// punctuation char, a whitespace run, and finally any single char.
const JSON_TOKEN_RE =
  /("(?:[^"\\]|\\.)*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|(true|false|null)|([{}[\],:])|(\s+)|(.)/g;

function highlightJson(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let last = 0;
  let key = 0;
  let m: RegExpExecArray | null;
  JSON_TOKEN_RE.lastIndex = 0;
  while ((m = JSON_TOKEN_RE.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    let cls = '';
    if (m[1] !== undefined) {
      // Keys carry a trailing colon; string values don't.
      cls = m[2] !== undefined ? 'text-brand-blue' : 'text-brand-amber-warm';
    } else if (m[3] !== undefined) {
      cls = 'text-brand-purple';
    } else if (m[4] !== undefined) {
      cls = 'text-brand-red';
    } else if (m[5] !== undefined) {
      cls = 'text-brand-green-faint';
    }
    nodes.push(
      <span key={key++} className={cls || undefined}>
        {m[0]}
      </span>
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard?.writeText(text).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <button
      type="button"
      onClick={handleCopy}
      className="flex items-center justify-center w-5 h-5 rounded text-brand-green-faint hover:text-brand-green-soft hover:bg-brand-border/60 transition-colors shrink-0"
      title={copied ? 'Copied' : 'Copy'}
    >
      {copied ? <Check className="h-3 w-3 text-brand-green" /> : <Copy className="h-3 w-3" />}
    </button>
  );
}

/**
 * Group actions into "chains" (one chain = one turn's step sequence).
 * The agent loop numbers steps with `iteration` (1, 2, 3…). A chain
 * continues while iteration is non-decreasing (parallel calls share an
 * iteration); a reset or a missing iteration starts a new chain. Order is
 * by iteration so the persisted (newest-first) history renders chronologically.
 */
function groupChains(actions: ActionItem[]): ActionItem[][] {
  const ordered = [...actions].sort((a, b) => {
    const ai = a.iteration ?? Number.MAX_SAFE_INTEGER;
    const bi = b.iteration ?? Number.MAX_SAFE_INTEGER;
    return ai - bi;
  });
  const chains: ActionItem[][] = [];
  let cur: ActionItem[] = [];
  let prevIter: number | null = null;
  for (const act of ordered) {
    const iter = act.iteration ?? null;
    const continues = prevIter !== null && iter !== null && iter >= prevIter;
    if (!continues && cur.length > 0) {
      chains.push(cur);
      cur = [];
    }
    cur.push(act);
    prevIter = iter;
  }
  if (cur.length > 0) chains.push(cur);
  return chains;
}

/**
 * Session 121: group chains under the plan todo they serve (one todo owns
 * many actions). Chains without a todo_id (legacy data) stay ungrouped.
 */
function groupChainsByTodo(chains: ActionItem[][]): { todoId: string | null; chains: ActionItem[][] }[] {
  const groups: { todoId: string | null; chains: ActionItem[][] }[] = [];
  for (const chain of chains) {
    const todoId = chain[0]?.todoId ?? null;
    const last = groups[groups.length - 1];
    if (last && last.todoId === todoId) {
      last.chains.push(chain);
    } else {
      groups.push({ todoId, chains: [chain] });
    }
  }
  return groups;
}

function ActionCard({ action, isMostRecent }: { action: ActionItem; isMostRecent?: boolean }) {
  // Match the Agent Workspace: the MOST-RECENT action card is expanded and only
  // collapses once a newer action arrives (older cards tuck away). Derived every
  // render; a manual click pins an explicit state that overrides the auto behavior.
  const [manualExpanded, setManualExpanded] = useState<boolean | null>(null);
  const expanded = manualExpanded ?? Boolean(isMostRecent);
  const setExpanded = (next: boolean) => setManualExpanded(next);
  const status = statusConfig[action.status] ?? statusConfig.pending;
  const hasBody = Boolean(action.output || action.error);
  const verbatim = action.input || action.detail || '';
  // Expandable when there's anything to reveal — output/error, a verbatim
  // command, OR just the reasoning (the "why:" header line moved into the body,
  // so a reasoning-only action must still open to show its Why block).
  const hasExpandable = Boolean(verbatim || hasBody || action.reasoning?.trim());
  const input = action.input ? formatInput(action.input) : null;
  const running = isRunning(action.status);

  return (
    <div
      className={`rounded border overflow-hidden transition-colors ${
        running
          ? 'border-brand-amber/40 bg-brand-amber/[0.04] shadow-[0_0_0_1px_rgba(240,180,60,0.08)]'
          : 'border-brand-border/60 hover:border-brand-border'
      }`}
    >
      <button
        onClick={() => hasExpandable && setExpanded(!expanded)}
        disabled={!hasExpandable}
        aria-expanded={expanded}
        className={`flex items-center gap-2.5 w-full min-w-0 px-3 py-2 text-left transition-colors ${
          hasExpandable ? 'hover:bg-brand-bg-panel cursor-pointer' : 'cursor-default'
        }`}
      >
        <span className={`shrink-0 ${actionColors[action.type]}`}>{actionIcons[action.type]}</span>
        <span className="flex-1 min-w-0">
          {/* Title — the real action label (e.g. "Running: git status"), with
              a provider badge when the tool reports which engine answered. */}
          <span className="flex items-center gap-1.5 min-w-0">
            <span className="block text-[12.5px] text-brand-green-soft font-medium truncate">
              {action.label}
            </span>
            {action.provider && (
              <span
                className="shrink-0 rounded border border-brand-border bg-brand-bg-code px-1.5 py-px text-[9px] font-mono uppercase tracking-wide text-brand-blue"
                title={`Answered by ${action.provider}`}
              >
                {action.provider}
              </span>
            )}
          </span>
          {/* Verbatim command/args — visible without expanding (reasoning moves
              to the Why block in the body to keep the row calm). */}
          {verbatim && (
            <span
              className="block text-[11px] text-brand-green-faint font-mono truncate mt-0.5"
              title={verbatim}
            >
              {verbatim}
            </span>
          )}
        </span>
        {/* Right cluster: status · duration · time · expand caret. */}
        <span className="ml-auto flex items-center gap-2.5 shrink-0">
          <span className={status.color} title={status.label}>{status.icon}</span>
          {action.duration != null && (
            <span className="text-[10px] font-mono text-brand-green-faint tabular-nums">
              {formatLatency(action.duration * 1000)}
            </span>
          )}
          {action.timestamp && (
            <span className="text-[10px] font-mono text-brand-green-faint whitespace-nowrap">{action.timestamp}</span>
          )}
          {hasExpandable && (
            <ChevronDown
              className={`h-3.5 w-3.5 text-brand-green-faint transition-transform ${expanded ? 'rotate-180' : ''}`}
            />
          )}
        </span>
      </button>

      {expanded && hasExpandable && (
        <div className="border-t border-brand-border-soft bg-brand-bg-dark">
          <div className="px-3 py-2.5 space-y-2 max-h-72 overflow-y-auto custom-scrollbar">
            {action.reasoning?.trim() && (
              <div>
                <div className="text-[10px] uppercase tracking-wider text-brand-amber mb-1">Why</div>
                <p className="text-[11px] italic text-brand-green-soft leading-snug whitespace-pre-wrap break-words">
                  {action.reasoning}
                </p>
              </div>
            )}

            {isRunKind(action.type) ? (
              /* Terminal treatment — command + output as one console block. */
              <div className="rounded-md bg-brand-bg-deep border border-brand-border-soft overflow-hidden">
                <div className="flex items-center justify-between px-2.5 py-1 border-b border-brand-border-soft">
                  <span className="text-[9px] uppercase tracking-wider text-brand-green-faint">terminal</span>
                  {(input?.text || action.output) && (
                    <CopyButton text={[input?.text, action.output].filter(Boolean).join('\n')} />
                  )}
                </div>
                <div className="px-2.5 py-2 font-mono text-[11px] leading-relaxed overflow-x-auto">
                  {input?.text && (
                    <div className="flex gap-2">
                      <span className="text-brand-green shrink-0">❯</span>
                      <span className="text-brand-green-soft whitespace-pre-wrap break-all">{input.text}</span>
                    </div>
                  )}
                  {action.output && (
                    <pre className={`mt-1 whitespace-pre-wrap break-words ${action.status === 'failed' ? 'text-brand-red' : 'text-brand-green-muted'}`}>
                      {action.output}
                    </pre>
                  )}
                </div>
              </div>
            ) : (
              <>
                {input && (
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] uppercase tracking-wider text-brand-green-faint">Input</span>
                      <CopyButton text={input.text} />
                    </div>
                    <pre className="text-[11px] font-mono text-brand-green-soft bg-brand-bg-base rounded px-2.5 py-1.5 whitespace-pre-wrap break-all">
                      {input.isJson ? highlightJson(input.text) : input.text}
                    </pre>
                  </div>
                )}
                {action.output &&
                  (looksLikeDiff(action.output) ? (
                    /* Diff treatment — low-alpha wash + colored gutter edge. */
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[10px] uppercase tracking-wider text-brand-green-faint">Diff</span>
                        <CopyButton text={action.output} />
                      </div>
                      <div className="rounded-md bg-brand-bg-deep border border-brand-border-soft font-mono text-[11px] leading-relaxed overflow-x-auto max-h-72 overflow-y-auto">
                        {action.output.split('\n').map((line, i) => {
                          const add = line.startsWith('+') && !line.startsWith('+++');
                          const del = line.startsWith('-') && !line.startsWith('---');
                          const cls = add
                            ? 'text-brand-gh-green-soft bg-brand-gh-green-bg border-l-2 border-brand-gh-green'
                            : del
                              ? 'text-brand-gh-red-soft bg-brand-gh-red-bg border-l-2 border-brand-gh-red'
                              : line.startsWith('@@')
                                ? 'text-brand-blue border-l-2 border-transparent'
                                : 'text-brand-green-muted border-l-2 border-transparent';
                          return (
                            <div key={i} className={`whitespace-pre px-2.5 ${cls}`}>
                              {line || ' '}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ) : (
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[10px] uppercase tracking-wider text-brand-green-faint">Output</span>
                        <CopyButton text={action.output} />
                      </div>
                      <pre className={`text-[11px] font-mono ${action.status === 'failed' ? 'text-brand-red' : 'text-brand-green'} bg-brand-bg-base rounded px-2.5 py-1.5 whitespace-pre-wrap break-all`}>
                        {action.output}
                      </pre>
                    </div>
                  ))}
              </>
            )}

            {action.error && (
              <div>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] uppercase tracking-wider text-brand-red">Error</span>
                  <CopyButton text={action.error} />
                </div>
                <pre className="text-[11px] font-mono text-brand-red bg-brand-bg-base rounded px-2.5 py-1.5 whitespace-pre-wrap break-all">
                  {action.error}
                </pre>
              </div>
            )}

            {!hasBody && !input && (
              <div className="text-[11px] text-brand-green-faint">
                {action.status === 'running' ? 'Waiting for tool to complete…' : 'No output returned.'}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function ActionHistory({ actions }: ActionHistoryProps) {
  const { reduce: reduceMotion, enter } = useEnterMotion();
  if (actions.length === 0) {
    return (
      <div className="px-2.5 py-4 text-center text-[10px] text-brand-green-muted">
        No actions yet.
      </div>
    );
  }

  const groups = groupChainsByTodo(groupChains(actions));

  // The most-recent action = the very last one rendered (last group → last
  // chain → last action). It stays expanded until a newer action pushes it down.
  const lastGroup = groups[groups.length - 1];
  const lastChain = lastGroup?.chains[lastGroup.chains.length - 1];
  const mostRecentId = lastChain?.[lastChain.length - 1]?.id ?? null;

  const stepLabel = (todoId: string) => {
    const m = todoId.match(/^plan-(\d+)$/);
    return m ? `Step ${Number(m[1]) + 1}` : todoId;
  };

  return (
    <div className="space-y-2 px-1">
      {groups.map((group, gi) => (
        <div key={gi} className="space-y-2">
          {/* Todo header — the plan step this group of actions serves */}
          {group.todoId && (
            <div className="flex items-center gap-1.5 px-0.5 pt-0.5">
              <ListChecks className="h-2.5 w-2.5 text-brand-green" />
              <span className="text-[9px] text-brand-green uppercase tracking-wide font-medium">
                {stepLabel(group.todoId)}
              </span>
              <span className="text-[9px] text-brand-green-faint">
                {group.chains.reduce((n, c) => n + c.length, 0)} action
                {group.chains.reduce((n, c) => n + c.length, 0) === 1 ? '' : 's'}
              </span>
              <span className="h-px flex-1 bg-brand-border/50" />
            </div>
          )}
        {group.chains.map((chain, ci) => (
        <div key={ci}>
          {/* Chain header — the turn's step count + when it ran */}
          <div className="flex items-center gap-1.5 px-0.5 pb-1 pt-0.5">
            <Zap className="h-2.5 w-2.5 text-brand-amber" />
            <span className="text-[9px] text-brand-green-muted uppercase tracking-wide font-medium">
              {chain.length} step{chain.length > 1 ? 's' : ''}
            </span>
            <span className="text-[9px] text-brand-green-faint">
              {chain[0]?.timestamp ?? ''}
            </span>
            <span className="h-px flex-1 bg-brand-border/50" />
          </div>

          {/* Numbered chain — step badge stacked ABOVE the card so the action
              container gets the full panel width (no left rail) */}
          <div>
            <AnimatePresence initial={false}>
              {chain.map((action, i) => {
                const running = isRunning(action.status);
                return (
                  <motion.div
                    key={action.id}
                    {...enter({ x: -6 })}
                    exit={reduceMotion ? undefined : { opacity: 0 }}
                    className="pb-1.5"
                  >
                    <div className="flex items-center px-0.5 pb-1">
                      <span
                        title={`Step ${i + 1}`}
                        className={`h-4 w-4 rounded-full border flex items-center justify-center text-[8px] font-mono shrink-0 ${
                          running
                            ? `border-brand-amber/50 bg-brand-amber/15 text-brand-amber ${reduceMotion ? '' : 'animate-pulse'}`
                            : action.status === 'done'
                              ? 'border-brand-green/40 bg-brand-green/10 text-brand-green'
                              : action.status === 'failed'
                                ? 'border-brand-red/40 bg-brand-red/10 text-brand-red'
                                : 'border-brand-border bg-brand-bg-base text-brand-green-muted'
                        }`}
                      >
                        {i + 1}
                      </span>
                    </div>
                    <ActionCard action={action} isMostRecent={action.id === mostRecentId} />
                  </motion.div>
                );
              })}
            </AnimatePresence>
          </div>
        </div>
        ))}
        </div>
      ))}
    </div>
  );
}
