'use client';

import React, { useState, useCallback, useMemo } from 'react';
import { User, Copy, Check, FileEdit, FilePlus, FileMinus, Activity, RefreshCw } from 'lucide-react';
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
// Register only the languages LocalMind commonly encounters.
// PrismLight (unlike Prism) only bundles languages you explicitly register,
// cutting the syntax-highlighter bundle from ~787KB to ~150KB.
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python';
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript';
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript';
import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash';
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json';
import yaml from 'react-syntax-highlighter/dist/esm/languages/prism/yaml';
import markdown from 'react-syntax-highlighter/dist/esm/languages/prism/markdown';
import sql from 'react-syntax-highlighter/dist/esm/languages/prism/sql';
import go from 'react-syntax-highlighter/dist/esm/languages/prism/go';
import rust from 'react-syntax-highlighter/dist/esm/languages/prism/rust';
import java from 'react-syntax-highlighter/dist/esm/languages/prism/java';
import css from 'react-syntax-highlighter/dist/esm/languages/prism/css';
import html from 'react-syntax-highlighter/dist/esm/languages/prism/markup';
import shell from 'react-syntax-highlighter/dist/esm/languages/prism/shell-session';

SyntaxHighlighter.registerLanguage('python', python);
SyntaxHighlighter.registerLanguage('py', python);
SyntaxHighlighter.registerLanguage('javascript', javascript);
SyntaxHighlighter.registerLanguage('js', javascript);
SyntaxHighlighter.registerLanguage('typescript', typescript);
SyntaxHighlighter.registerLanguage('ts', typescript);
SyntaxHighlighter.registerLanguage('tsx', typescript);
SyntaxHighlighter.registerLanguage('bash', bash);
SyntaxHighlighter.registerLanguage('sh', bash);
SyntaxHighlighter.registerLanguage('json', json);
SyntaxHighlighter.registerLanguage('yaml', yaml);
SyntaxHighlighter.registerLanguage('yml', yaml);
SyntaxHighlighter.registerLanguage('markdown', markdown);
SyntaxHighlighter.registerLanguage('md', markdown);
SyntaxHighlighter.registerLanguage('sql', sql);
SyntaxHighlighter.registerLanguage('go', go);
SyntaxHighlighter.registerLanguage('rust', rust);
SyntaxHighlighter.registerLanguage('rs', rust);
SyntaxHighlighter.registerLanguage('java', java);
SyntaxHighlighter.registerLanguage('css', css);
SyntaxHighlighter.registerLanguage('html', html);
SyntaxHighlighter.registerLanguage('xml', html);
SyntaxHighlighter.registerLanguage('shell', shell);
SyntaxHighlighter.registerLanguage('shell-session', shell);
import { ChatMessage as ChatMessageType, FileResult, PendingWrite, DiffData, TodoItem } from '@/types';
import { formatLatency, formatTokens } from '@/lib/localmind/progress';
import { MarkdownContent } from '@/components/shared/MarkdownContent';
import { ResponseBlockRenderer } from './ResponseBlockRenderer';
import { TurnView } from './TurnView';
import { stripFallbackErrorText, stripVerificationFooter } from '@/lib/localmind/errorText';
import { ErrorMessage } from './ErrorMessage';
import { DiffBlock, type DiffHunk } from '@/components/shared/DiffBlock';
import { FilePreviewDialog } from './FilePreviewDialog';

interface ChatMessageProps {
  message: ChatMessageType;
  /** Whether this message is currently being streamed (keeps the turn view live) */
  isStreaming?: boolean;
  /** Re-send the user prompt that produced this assistant reply (regenerate).
   *  Only provided for assistant messages that have a preceding user prompt. */
  onRetry?: () => void;
  /** Per-path diff hunks captured this turn (preview Diff mode). */
  fileDiffs?: Record<string, DiffData>;
  /** The session's plan, shown as step progress inside the turn. */
  todos?: TodoItem[];
}

function FileResultChip({
  result,
  onPreview,
}: {
  result: FileResult;
  onPreview: (path: string) => void;
}) {
  const statusConfig = {
    created: { icon: <FilePlus className="h-3 w-3" />, color: 'text-brand-green border-brand-green/30 bg-brand-green/5' },
    modified: { icon: <FileEdit className="h-3 w-3" />, color: 'text-brand-amber border-brand-amber/30 bg-brand-amber/5' },
    deleted: { icon: <FileMinus className="h-3 w-3" />, color: 'text-brand-red border-brand-red/30 bg-brand-red/5' },
  };
  // Defensive: fall back to 'created' if the backend sends an unexpected status
  // (e.g. 'renamed', 'moved'). Previously this would crash with TypeError.
  const config = statusConfig[result.status as keyof typeof statusConfig] ?? statusConfig.created;

  return (
    <button
      type="button"
      onClick={() => onPreview(result.path)}
      title={`Click to preview ${result.path}`}
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-[10px] font-mono cursor-pointer hover:brightness-125 active:brightness-110 transition-all ${config.color}`}
    >
      {config.icon}
      <span className="underline decoration-dotted underline-offset-2">{result.path}</span>
      {result.lines && (
        <span className="text-[9px] opacity-60">+{result.lines}L</span>
      )}
    </button>
  );
}

// ── Compact "applied" card — the normal view after Accept ────
// The full colored diff collapses to this one-line summary; the diff itself
// stays reachable via the View-diff toggle (re-opened read-only above/below).
function DiffAppliedCard({
  fileName,
  additions,
  deletions,
  open,
  onToggle,
}: {
  fileName: string;
  additions: number;
  deletions: number;
  open: boolean;
  onToggle: () => void;
}) {
  const shortName = fileName.split('/').pop() || fileName;
  return (
    <div className="flex items-center gap-2 my-2 px-2.5 py-1.5 rounded-lg border border-brand-green/25 bg-brand-green/5">
      <FileEdit className="h-3.5 w-3.5 text-brand-green shrink-0" />
      <span className="text-[11px] font-mono text-brand-green truncate" title={fileName}>
        {shortName}
      </span>
      <span className="text-[10px] font-mono text-brand-green/70 shrink-0">
        +{additions} <span className="text-brand-red/70">−{deletions}</span>
      </span>
      <span className="text-[9px] uppercase tracking-wider text-brand-green/60 shrink-0">
        applied
      </span>
      <button
        type="button"
        onClick={onToggle}
        data-testid="diff-applied-toggle"
        className="ml-auto text-[10px] text-brand-green/80 hover:text-brand-green underline decoration-dotted underline-offset-2 shrink-0"
      >
        {open ? 'Hide diff' : 'View diff'}
      </button>
    </div>
  );
}

// ── Themed code block — matches green-black UI ──────────────────────────────
function CodeBlockComponent({ code, language, filename }: { code: string; language: string; filename?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const isRunnable = ['python', 'py', 'bash', 'sh', 'shell', 'js', 'javascript', 'ts', 'typescript'].includes(language.toLowerCase());

  const customStyle = useMemo(() => {
    const style = { ...vscDarkPlus };
    style['pre[class*="language-"]'] = { ...style['pre[class*="language-"]'], background: 'none', margin: 0, padding: 0, fontSize: '12px', lineHeight: '1.6', color: 'var(--brand-green-soft)' };
    style['code[class*="language-"]'] = { ...style['code[class*="language-"]'], background: 'none', fontSize: '12px', lineHeight: '1.6', color: 'var(--brand-green-soft)' };
    return style;
  }, []);

  return (
    <div className="rounded-md border border-brand-border overflow-hidden mb-2 max-w-full shadow-lg shadow-black/20">
      <div className="flex items-center justify-between px-3 py-1.5 bg-brand-bg-code border-b border-brand-border">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[10px] font-mono text-brand-green-muted uppercase shrink-0">{language || 'text'}</span>
          {filename ? (
            <button
              type="button"
              onClick={() => window.dispatchEvent(new CustomEvent('localmind:open-file-preview', { detail: filename }))}
              className="text-[10px] text-brand-blue hover:text-brand-blue-bright truncate cursor-pointer transition-colors"
              title={`Click to preview ${filename}`}
            >
              — {filename}
            </button>
          ) : null}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {isRunnable && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                window.dispatchEvent(new CustomEvent('localmind:run-code', {
                  detail: { code, language, filename }
                }));
                window.dispatchEvent(new CustomEvent('localmind:activate-terminal'));
              }}
              className="flex items-center gap-1 text-[10px] text-brand-green hover:text-brand-green-bright transition-colors border border-brand-green/20 rounded px-1.5 py-0.5 hover:bg-brand-green/5"
              title="Run in terminal"
            >
              <span>▶</span><span>Run</span>
            </button>
          )}
          <button
            onClick={handleCopy}
            className="flex items-center gap-1 text-[10px] text-brand-green-faint hover:text-brand-green-muted transition-colors"
          >
            {copied ? <><Check className="h-3 w-3 text-brand-green" /><span className="text-brand-green">Copied</span></> : <><Copy className="h-3 w-3" /><span>Copy</span></>}
          </button>
        </div>
      </div>
      <div className="bg-brand-bg-dark overflow-x-auto max-w-full">
        <div className="flex">
          <div className="shrink-0 border-r border-brand-bg-rail bg-brand-bg-dark py-2 pr-3 pl-3 text-right select-none">
            {code.split('\n').map((_, i) => (
              <div key={i} className="text-[11px] font-mono leading-[1.6] text-brand-green-line">{i + 1}</div>
            ))}
          </div>
          <div className="flex-1 py-2 pl-4 pr-4 overflow-x-auto">
            <SyntaxHighlighter
              language={language || 'text'}
              style={customStyle}
              customStyle={{ background: 'none', margin: 0, padding: 0 }}
              codeTagProps={{ style: { fontSize: '12px', lineHeight: '1.6', fontFamily: 'var(--font-geist-mono), "Cascadia Code", "Fira Code", Consolas, monospace', color: 'var(--brand-green-soft)' } }}
            >
              {code}
            </SyntaxHighlighter>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── MessageMetrics — per-message latency/token line ──
// Renders a small muted line under each assistant reply, e.g. `39.9s · 0/321 tok`.
// Backward-compatible: messages without `performance` (old history, user turns)
// render exactly as before.
function MessageMetrics({ performance }: { performance: NonNullable<ChatMessageType['performance']> }) {
  const parts: string[] = [];
  if (performance.latencyMs) parts.push(formatLatency(performance.latencyMs));
  const prompt = performance.promptTokens ?? 0;
  const completion = performance.completionTokens ?? 0;
  if (prompt > 0 || completion > 0) {
    parts.push(`${formatTokens(prompt)}/${formatTokens(completion)} tok`);
  }
  if (performance.tokensPerSecond) parts.push(`${performance.tokensPerSecond} tok/s`);
  if (parts.length === 0) return null;
  return (
    <div
      className="mt-1.5 flex items-center gap-1.5 text-[9px] text-brand-green-faint font-mono select-none"
      title="This reply's performance: latency · prompt/completion tokens · speed"
    >
      <Activity className="h-2.5 w-2.5 opacity-70 shrink-0" />
      <span>{parts.join(' · ')}</span>
    </div>
  );
}

// ── BestOfNSection — the candidate comparison for a best-of-N edit turn ──
// The tool records every candidate it considered (strategy + rationale) and
// which one the selector picked. Persisted with the message so the comparison
// survives reload. Compact by design — the winner line is always visible,
// the full list folds open on demand.
function BestOfNSection({ candidates }: { candidates: NonNullable<ChatMessageType['candidates']> }) {
  const [open, setOpen] = useState(false);
  const winner = candidates.find((c) => c.isWinner);
  if (!winner) return null;
  return (
    <div className="mt-2 rounded-md border border-brand-green/20 bg-brand-green/5 px-3 py-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-1.5 text-[11px] text-brand-green-soft text-left"
      >
        <span className="font-medium">Best of {candidates.length}</span>
        <span className="text-brand-green-muted truncate">
          — applied <strong className="text-brand-green">{winner.strategy}</strong>
        </span>
        <span className="ml-auto text-[9px] text-brand-green-faint shrink-0">
          {open ? 'Hide' : 'Show'} all
        </span>
      </button>
      {open && (
        <ul className="mt-1.5 space-y-1">
          {candidates.map((c) => (
            <li key={c.index} className="text-[10px] leading-snug">
              <span className={c.isWinner ? 'text-brand-green font-medium' : 'text-brand-green-muted'}>
                {c.isWinner ? '✓ ' : '— '}
                {c.strategy}
              </span>
              {c.rationale && (
                <span className="text-brand-green-faint"> — {c.rationale}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── PermissionGate — confirm/deny buttons for pending file writes ──────────

function PermissionGate({ pending, onResolved }: { pending: PendingWrite; onResolved: (result: 'confirmed' | 'denied') => void }) {
  const [status, setStatus] = useState<'pending' | 'writing' | 'done' | 'error' | 'denied'>('pending');

  const handleConfirm = async () => {
    setStatus('writing');
    try {
      const API_BASE = (window as any).__LOCALMIND_API__ || 'http://localhost:8000';
      const res = await fetch(`${API_BASE}/api/confirm-write`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: pending.path, content: pending.content }),
      });
      if (!res.ok) throw new Error(`API error ${res.status}`);
      setStatus('done');
      onResolved('confirmed');
    } catch (_err) {
      setStatus('error');
    }
  };

  const handleDeny = () => {
    setStatus('denied');
    onResolved('denied');
  };

  return (
    <div className="mt-2 rounded-md border border-brand-amber/30 bg-brand-amber/5 px-3 py-2">
      {status === 'pending' && (
        <>
          <div className="text-[11px] text-brand-green-soft mb-1.5">
            Allow LocalMind to write <strong className="text-brand-amber">{pending.filename || 'file'}</strong>?
          </div>
          <div className="font-mono text-[10px] text-brand-green-muted mb-2 break-all">{pending.path}</div>
          <div className="flex gap-2">
            <button
              onClick={handleConfirm}
              className="px-2.5 py-1 text-[11px] font-medium rounded border border-brand-green/30 bg-brand-green/10 text-brand-green hover:bg-brand-green/20 transition-colors"
            >
              ✓ Yes, write it
            </button>
            <button
              onClick={handleDeny}
              className="px-2.5 py-1 text-[11px] font-medium rounded border border-brand-red/30 bg-brand-red/10 text-brand-red hover:bg-brand-red/20 transition-colors"
            >
              ✕ Cancel
            </button>
          </div>
        </>
      )}
      {status === 'writing' && (
        <div className="text-[11px] text-brand-amber animate-pulse">Writing file…</div>
      )}
      {status === 'done' && (
        <div className="text-[11px] text-brand-green">✓ Written successfully</div>
      )}
      {status === 'error' && (
        <div className="text-[11px] text-brand-red">Write failed. Try again or write manually.</div>
      )}
      {status === 'denied' && (
        <div className="text-[11px] text-brand-green-muted">Write cancelled.</div>
      )}
    </div>
  );
}

// Chat mode offered to switch to Agent for an action. Accept
// dispatches a window event (WorkspaceLayout switches mode + resends); Decline
// keeps Chat mode. Self-contained, modeled on PermissionGate.
function SwitchToAgentGate({ message }: { message: string }) {
  const [resolved, setResolved] = useState<null | 'accepted' | 'declined'>(null);
  const accept = () => {
    setResolved('accepted');
    window.dispatchEvent(new CustomEvent('localmind:switch-to-agent', { detail: { message } }));
  };
  return (
    <div className="mt-2 rounded-md border border-blue-400/30 bg-blue-400/5 px-3 py-2">
      {resolved === null && (
        <>
          <div className="text-[11px] text-brand-green-soft mb-2">
            This needs an action. Switch to <strong className="text-blue-400">Agent mode</strong> and do it?
          </div>
          <div className="flex gap-2">
            <button
              onClick={accept}
              className="px-2.5 py-1 text-[11px] font-medium rounded border border-blue-400/30 bg-blue-400/10 text-blue-400 hover:bg-blue-400/20 transition-colors"
            >
              ✓ Switch &amp; do it
            </button>
            <button
              onClick={() => setResolved('declined')}
              className="px-2.5 py-1 text-[11px] font-medium rounded border border-brand-border bg-brand-bg-base text-brand-green-muted hover:text-brand-green-soft transition-colors"
            >
              Stay in Chat
            </button>
          </div>
        </>
      )}
      {resolved === 'accepted' && (
        <div className="text-[11px] text-blue-400 animate-pulse">Switched to Agent mode — running it…</div>
      )}
      {resolved === 'declined' && (
        <div className="text-[11px] text-brand-green-muted">Staying in Chat mode.</div>
      )}
    </div>
  );
}

// ── ChatMessage component ──────────────────────────────────────────────────

// ── MessageActions — hover-reveal copy/retry row (auto-hides) ─────────────
// Standard chat UX: a small action chip floats at the bottom of the message
// and is revealed only while the message is hovered (group-hover), so the
// transcript stays uncluttered. Copy works on both roles; Retry (regenerate
// the response to the preceding prompt) exists only on assistant messages.
function MessageActions({
  isUser,
  content,
  isStreaming,
  onRetry,
}: {
  isUser: boolean;
  content: string;
  isStreaming: boolean;
  onRetry?: () => void;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    if (!content) return;
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard unavailable (e.g. non-secure context) — stay quiet.
    }
  }, [content]);

  return (
    <div
      data-testid="message-actions"
      className={`absolute bottom-1 ${isUser ? 'left-2' : 'right-2'} z-10 flex items-center gap-0.5 rounded-md border border-brand-border bg-brand-bg-code/95 backdrop-blur px-1 py-0.5 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity duration-150 select-none shadow-lg shadow-black/20`}
    >
      <button
        onClick={handleCopy}
        disabled={!content}
        className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] text-brand-green-muted hover:text-brand-green hover:bg-brand-green/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        title={copied ? 'Copied!' : 'Copy message'}
      >
        {copied ? <Check className="h-3 w-3 text-brand-green" /> : <Copy className="h-3 w-3" />}
        <span>{copied ? 'Copied' : 'Copy'}</span>
      </button>
      {!isUser && onRetry && (
        <button
          onClick={onRetry}
          disabled={isStreaming}
          className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] text-brand-green-muted hover:text-brand-green hover:bg-brand-green/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          title={isStreaming ? 'LocalMind is busy' : 'Regenerate this response'}
        >
          <RefreshCw className="h-3 w-3" />
          <span>Retry</span>
        </button>
      )}
    </div>
  );
}

export function ChatMessage({ message, isStreaming, onRetry, fileDiffs, todos }: ChatMessageProps) {
  const isUser = message.role === 'user';

  // Clickable file-result chips open an inline preview dialog
  // (text/code/markdown/office docs parsed server-side, images as data URLs).
  const [previewPath, setPreviewPath] = useState<string | null>(null);

  // Listen for file-preview requests from code block filenames
  // and turn-view file paths (they dispatch localmind:open-file-preview).
  React.useEffect(() => {
    const handler = (e: Event) => {
      const path = (e as CustomEvent<string>).detail;
      if (typeof path === 'string' && path) setPreviewPath(path);
    };
    window.addEventListener('localmind:open-file-preview', handler);
    return () => window.removeEventListener('localmind:open-file-preview', handler);
  }, []);

  // Check if this message has diff data (from edit_file tool results)
  const diffHunks: DiffHunk[] = useMemo(() => {
    if (message.diffData?.hunks) {
      return message.diffData.hunks;
    }
    return [];
  }, [message.diffData]);

  // Accept collapses the full colored diff into a compact
  // "applied" card (the normal view). The full diff stays reachable on
  // demand via the card's View-diff toggle, rendered read-only (no second
  // Accept bar — the change is already acknowledged). Component-local state:
  // the message list is keyed by id, so this survives re-renders for as
  // long as the message is mounted. The diff itself persists with the
  // message, so a reload restores the card — and a reloaded turn's edit is
  // already applied on disk, so it comes back in the collapsed "applied"
  // state rather than re-offering Accept/Reject. `timestampEpoch` is set
  // only by the history-restore path, so it doubles as the restored marker.
  // A file change is already on disk when its diff arrives, so it opens as the compact
  // "applied" card. The old Accept/Reject bar offered a Reject that did nothing.
  const [diffAccepted, setDiffAccepted] = useState(true);
  const [diffReopen, setDiffReopen] = useState(false);

  // The error card already says the reply failed; drop the fallback line that repeats it.
  const shownContent = isUser
    ? message.content
    : stripVerificationFooter(message.error ? stripFallbackErrorText(message.content) : message.content);

  const diffStats = useMemo(() => {
    let additions = 0;
    let deletions = 0;
    for (const h of diffHunks) {
      for (const l of h.lines) {
        if (l.type === 'added') additions += 1;
        else if (l.type === 'removed') deletions += 1;
      }
    }
    return { additions, deletions };
  }, [diffHunks]);

  return (
    <div
      data-message-content-id={message.id}
      className={`px-4 py-3 overflow-hidden group relative ${isUser ? 'justify-end' : 'justify-start border-l-2 border-l-brand-green/30'}`}
    >
      {/* Hover action row — auto-hides, revealed on message hover */}
      <MessageActions isUser={isUser} content={message.content || ''} isStreaming={!!isStreaming} onRetry={onRetry} />
      <div className={`flex items-start gap-3 max-w-full ${isUser ? 'flex-row-reverse' : ''}`}>
        <div className={`flex-1 min-w-0 max-w-full overflow-hidden ${isUser ? 'items-end flex flex-col' : ''}`}>
          {/* Header */}
          <div className={`flex items-center gap-2 mb-1 ${isUser ? 'flex-row-reverse' : ''}`}>
            {/* Avatar for user messages */}
            {isUser && (
              <div
                className="w-6 h-6 rounded flex items-center justify-center shrink-0 mt-0.5 bg-brand-amber/10 text-brand-amber"
              >
                <User className="h-3.5 w-3.5" />
              </div>
            )}
            <span className={`text-[11px] font-medium ${isUser ? 'text-brand-amber' : 'text-brand-green'}`}>
              {isUser ? 'You' : 'LocalMind'}
            </span>
            <span className="text-[9px] text-brand-green-muted">{message.timestamp}</span>
          </div>

          {/* The agent's whole turn — acknowledgement, reasoning, checkpoints,
              tools, parallel batches and sub-agents — as one live activity
              (see TurnView) instead of separate stacked blocks. */}
          {!isUser && (
            <TurnView message={message} todos={todos} isStreaming={isStreaming} />
          )}

          {/* Canonical error card — a failed reply renders this
              instead of a raw provider payload. Content is empty on error
              replies (the backend streams no tokens), so the card IS the
              message. Try again re-sends the preceding prompt. */}
          {!isUser && message.error && (
            <ErrorMessage error={message.error} onRetry={onRetry} />
          )}

          {/* Content — rendered as Markdown for assistant, plain for user */}
          {shownContent && (
            isUser ? (
              <div className="text-[12px] text-brand-amber-soft leading-relaxed whitespace-pre-wrap break-words overflow-wrap-anywhere">
                {shownContent}
              </div>
            ) : (
              <MarkdownContent text={shownContent} />
            )
          )}

          {/* Structured response blocks from Presentation Intelligence.
              When the backend emits response_blocks SSE events, render them natively
              (tables, metrics, diagrams, etc.) instead of forcing everything through Markdown. */}
          {message.responseBlocks && message.responseBlocks.length > 0 && !isStreaming && (
            <ResponseBlockRenderer blocks={message.responseBlocks} />
          )}

          {/* Code blocks (from parsed message.codeBlocks — legacy path) */}
          {message.codeBlocks?.map((block) => (
            <CodeBlockComponent
              key={block.id}
              code={block.code}
              language={block.language}
              filename={block.filename}
            />
          ))}

          {/* Diff block — rendered when edit_file produces structured diff hunks.
              Pending → full diff with Accept/Reject; accepted →
              compact "applied" card (the normal view), with the full diff
              re-openable read-only on demand. */}
          {diffHunks.length > 0 && !diffAccepted && (
            <DiffBlock
              hunks={diffHunks}
              language={message.diffData?.language || ''}
              showActions={true}
              isStreaming={isStreaming}
              onAccept={() => setDiffAccepted(true)}
            />
          )}
          {diffHunks.length > 0 && diffAccepted && (
            <DiffAppliedCard
              fileName={diffHunks[0]?.filePath || message.diffData?.filePath || 'file'}
              additions={diffStats.additions}
              deletions={diffStats.deletions}
              open={diffReopen}
              onToggle={() => setDiffReopen((v) => !v)}
            />
          )}
          {diffHunks.length > 0 && diffAccepted && diffReopen && (
            <DiffBlock
              hunks={diffHunks}
              language={message.diffData?.language || ''}
              showActions={false}
            />
          )}

          {/* File results */}
          {message.fileResults && message.fileResults.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {message.fileResults.map((fr) => (
                <FileResultChip key={fr.id} result={fr} onPreview={setPreviewPath} />
              ))}
            </div>
          )}

          {/* Per-message performance line — only on assistant replies with metrics */}
          {!isUser && message.performance && <MessageMetrics performance={message.performance} />}

          {/* Best of N section — the candidate comparison for a best-of-N edit turn */}
          {message.candidates && <BestOfNSection candidates={message.candidates} />}

          {/* Permission gate for pending writes */}
          {message.pendingWrite && (
            <PermissionGate
              pending={message.pendingWrite}
              onResolved={(_result) => {
                // The gate is self-contained — no parent state update needed.
              }}
            />
          )}
          {message.switchToAgent && (
            <SwitchToAgentGate message={message.switchToAgent.message} />
          )}
        </div>
      </div>

      {/* File preview dialog — opened by clicking a file-result chip */}
      <FilePreviewDialog path={previewPath} onClose={() => setPreviewPath(null)} diffs={fileDiffs} />
    </div>
  );
}
