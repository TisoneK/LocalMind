'use client';

import React, { useState, useCallback, useMemo } from 'react';
import { User, Copy, Check, FileEdit, FilePlus, FileMinus, Activity, RefreshCw } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
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
import { ChatMessage as ChatMessageType, FileResult, PendingWrite } from '@/types';
import { formatLatency } from '@/lib/localmind/progress';
import { repairMarkdown } from '@/lib/markdownRepair';
import { ThinkingBlock } from './ThinkingBlock';
import { ToolSteps } from './ToolSteps';
import { AgentPhases } from './AgentPhases';
import { ErrorMessage } from './ErrorMessage';
import { DiffBlock, type DiffHunk } from '@/components/shared/DiffBlock';

interface ChatMessageProps {
  message: ChatMessageType;
  /** Whether this message is currently being streamed (affects ThinkingBlock expansion) */
  isStreaming?: boolean;
  /** Re-send the user prompt that produced this assistant reply (regenerate).
   *  Only provided for assistant messages that have a preceding user prompt. */
  onRetry?: () => void;
}

function FileResultChip({ result }: { result: FileResult }) {
  const statusConfig = {
    created: { icon: <FilePlus className="h-3 w-3" />, color: 'text-brand-green border-brand-green/30 bg-brand-green/5' },
    modified: { icon: <FileEdit className="h-3 w-3" />, color: 'text-brand-amber border-brand-amber/30 bg-brand-amber/5' },
    deleted: { icon: <FileMinus className="h-3 w-3" />, color: 'text-brand-red border-brand-red/30 bg-brand-red/5' },
  };
  // Defensive: fall back to 'created' if the backend sends an unexpected status
  // (e.g. 'renamed', 'moved'). Previously this would crash with TypeError.
  const config = statusConfig[result.status as keyof typeof statusConfig] ?? statusConfig.created;

  return (
    <div className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-[10px] font-mono ${config.color}`}>
      {config.icon}
      <span>{result.path}</span>
      {result.lines && (
        <span className="text-[9px] opacity-60">+{result.lines}L</span>
      )}
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
          {filename && <span className="text-[10px] text-brand-green-muted truncate">— {filename}</span>}
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

// ── Markdown custom component renderers — themed green-black ─────────────

/** Pre block wrapper — themed header bar with language label + copy button */
function MarkdownPreBlock({ children, ..._props }: React.ComponentPropsWithoutRef<'pre'> & { children?: React.ReactNode }) {
  let lang = '';
  let codeText = '';
  let rawCode = '';

  if (React.isValidElement(children) && (children.props as any)) {
    const codeProps = children.props as any;
    if (codeProps.className) {
      const match = /language-(\w+)/.exec(codeProps.className);
      lang = match ? match[1] : '';
    }
    rawCode = String(codeProps.children || '');
    codeText = rawCode.replace(/\n$/, '');
  } else {
    rawCode = String(children);
    codeText = rawCode.replace(/\n$/, '');
  }

  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(codeText);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  }, [codeText]);

  const customStyle = useMemo(() => {
    const style = { ...vscDarkPlus };
    style['pre[class*="language-"]'] = { ...style['pre[class*="language-"]'], background: 'none', margin: 0, padding: 0, fontSize: '12px', lineHeight: '1.6', color: 'var(--brand-green-soft)' };
    style['code[class*="language-"]'] = { ...style['code[class*="language-"]'], background: 'none', fontSize: '12px', lineHeight: '1.6', color: 'var(--brand-green-soft)' };
    return style;
  }, []);

  // Single-line, no language → render as inline code
  if (!lang && !codeText.includes('\n')) {
    return (
      <code className="font-mono text-[11.5px] bg-brand-bg-code px-[5px] py-[1px] rounded-[3px] text-brand-green-inline border border-brand-border">
        {codeText}
      </code>
    );
  }

  return (
    <div className="rounded-md border border-brand-border overflow-hidden my-2 font-mono max-w-full shadow-lg shadow-black/20">
      <div className="flex items-center justify-between px-3 py-1.5 bg-brand-bg-code border-b border-brand-border">
        <span className="text-[10px] font-mono text-brand-green-muted uppercase tracking-wider shrink-0">
          {lang || 'text'}
        </span>
        <div className="flex items-center gap-2 shrink-0">
          {['python', 'py', 'bash', 'sh', 'shell', 'js', 'javascript', 'ts', 'typescript'].includes(lang) && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                window.dispatchEvent(new CustomEvent('localmind:run-code', {
                  detail: { code: codeText, language: lang }
                }));
                window.dispatchEvent(new CustomEvent('localmind:activate-terminal'));
              }}
              className="text-[10px] font-mono text-brand-green hover:text-brand-green-bright border border-brand-green/20 rounded px-1.5 py-0.5 cursor-pointer transition-colors hover:bg-brand-green/5"
              title="Run in terminal"
            >
              ▶ Run
            </button>
          )}
          <button
            onClick={handleCopy}
            className="flex items-center gap-1 text-[10px] font-mono text-brand-green-faint hover:text-brand-green-muted transition-colors"
          >
            {copied ? <><Check className="h-3 w-3 text-brand-green" /><span className="text-brand-green">Copied</span></> : <><Copy className="h-3 w-3" /><span>Copy</span></>}
          </button>
        </div>
      </div>
      <div className="bg-brand-bg-dark overflow-x-auto max-w-full">
        <div className="flex">
          <div className="shrink-0 border-r border-brand-bg-rail bg-brand-bg-dark py-2 pr-3 pl-3 text-right select-none">
            {rawCode.split('\n').map((_, i) => (
              <div key={i} className="text-[11px] font-mono leading-[1.6] text-brand-green-line">{i + 1}</div>
            ))}
          </div>
          <div className="flex-1 py-2 pl-4 pr-4 overflow-x-auto">
            <SyntaxHighlighter
              language={lang || 'text'}
              style={customStyle}
              customStyle={{ background: 'none', margin: 0, padding: 0 }}
              codeTagProps={{ style: { fontSize: '12px', lineHeight: '1.6', fontFamily: 'var(--font-geist-mono), "Cascadia Code", "Fira Code", Consolas, monospace', color: 'var(--brand-green-soft)' } }}
            >
              {codeText}
            </SyntaxHighlighter>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Inline code styling — themed green-black */
function MarkdownInlineCode({ children, ...props }: React.ComponentPropsWithoutRef<'code'>) {
  return (
    <code
      className="font-mono text-[11.5px] bg-brand-bg-code px-[5px] py-[1px] rounded-[3px] text-brand-green-inline border border-brand-border"
      {...props}
    >
      {children}
    </code>
  );
}

/** Styled link that opens in external browser */
function MarkdownLink({ href, children, ...props }: React.ComponentPropsWithoutRef<'a'>) {
  const handleClick = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    if ((window as any).electronAPI?.openExternal) {
      (window as any).electronAPI.openExternal(href);
    } else {
      window.open(href, '_blank', 'noopener,noreferrer');
    }
  }, [href]);

  return (
    <a
      href={href}
      onClick={handleClick}
      className="text-[brand-blue] underline decoration-dotted underline-offset-2"
      title={href}
      {...props}
    >
      {children}
    </a>
  );
}

/** Styled table */
// Tables render as a polished CARD — rounded, bordered, accent header row, zebra
// striping, hover highlight, tabular figures — so structured answers (weather,
// comparisons, schedules) read as a clean table instead of raw text.
function MarkdownTable({ children, ...props }: React.ComponentPropsWithoutRef<'table'>) {
  return (
    <div className="my-3 overflow-hidden rounded-xl border border-brand-border bg-brand-bg-code/50 shadow-sm">
      <div className="overflow-x-auto">
        <table
          className="w-full border-collapse text-[12px] tabular-nums [&_tbody_tr:nth-child(even)]:bg-brand-bg-base/40 [&_tbody_tr:hover]:bg-brand-green/[0.06] [&_tbody_tr:last-child]:border-b-0"
          {...props}
        >
          {children}
        </table>
      </div>
    </div>
  );
}

function MarkdownTableHead({ children, ...props }: React.ComponentPropsWithoutRef<'thead'>) {
  return (
    <thead className="border-b border-brand-green-table-border bg-gradient-to-b from-brand-green/[0.10] to-brand-green/[0.03]" {...props}>
      {children}
    </thead>
  );
}

function MarkdownTableRow({ children, ...props }: React.ComponentPropsWithoutRef<'tr'>) {
  return (
    <tr className="border-b border-brand-border/60 transition-colors" {...props}>
      {children}
    </tr>
  );
}

function MarkdownTableCell({ isHeader, children, ...props }: React.ComponentPropsWithoutRef<'th' | 'td'> & { isHeader?: boolean }) {
  if (isHeader) {
    return (
      <th className="whitespace-nowrap px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-brand-green" {...props}>
        {children}
      </th>
    );
  }
  return (
    <td className="px-3 py-2 align-middle text-brand-green-soft" {...props}>
      {children}
    </td>
  );
}

/** Styled headings */
function MarkdownHeading({ level, children, ...props }: React.ComponentPropsWithoutRef<'h1'> & { level: number }) {
  const sizes: Record<number, string> = { 1: 'text-base', 2: 'text-sm', 3: 'text-[13px]', 4: 'text-xs' };
  const weights: Record<number, string> = { 1: 'font-[680]', 2: 'font-[640]', 3: 'font-[600]', 4: 'font-[600]' };
  const sz = sizes[level] || 'text-[13px]';
  const fw = weights[level] || 'font-[600]';
  return (
    <div className={`${sz} ${fw} text-brand-green-soft mt-2.5 mb-1 font-sans`}{...props}>
      {children}
    </div>
  );
}

/** Styled unordered list */
function MarkdownUl({ children, ...props }: React.ComponentPropsWithoutRef<'ul'>) {
  return (
    <ul className="my-1 ml-[18px] p-0 list-disc" {...props}>
      {children}
    </ul>
  );
}

/** Styled ordered list */
function MarkdownOl({ children, ...props }: React.ComponentPropsWithoutRef<'ol'>) {
  return (
    <ol className="my-1 ml-[18px] p-0 list-decimal" {...props}>
      {children}
    </ol>
  );
}

/** Styled list item */
function MarkdownLi({ children, ...props }: React.ComponentPropsWithoutRef<'li'>) {
  return (
    <li className="mb-0.5 leading-[1.65] text-brand-green-soft" {...props}>
      {children}
    </li>
  );
}

/** Styled paragraph */
function MarkdownP({ children, ...props }: React.ComponentPropsWithoutRef<'p'>) {
  return (
    <p className="my-0.5 leading-[1.7] text-brand-green-soft" {...props}>
      {children}
    </p>
  );
}

/** Styled blockquote */
function MarkdownBlockquote({ children, ...props }: React.ComponentPropsWithoutRef<'blockquote'>) {
  return (
    <blockquote className="my-1.5 py-1.5 px-3 border-l-2 border-brand-border-soft bg-brand-bg-table text-brand-green-muted rounded-r-[4px]" {...props}>
      {children}
    </blockquote>
  );
}

/** Styled horizontal rule */
function MarkdownHr({ ...props }: React.ComponentPropsWithoutRef<'hr'>) {
  return (
    <hr className="border-none border-t border-brand-border my-1.5" {...props} />
  );
}

/** Styled strong text */
function MarkdownStrong({ children, ...props }: React.ComponentPropsWithoutRef<'strong'>) {
  return <strong className="text-brand-green-soft font-[650]" {...props}>{children}</strong>;
}

/** Styled emphasis text */
function MarkdownEm({ children, ...props }: React.ComponentPropsWithoutRef<'em'>) {
  return <em className="text-brand-green-muted" {...props}>{children}</em>;
}

/** Styled strikethrough (from remark-gfm) */
function MarkdownDel({ children, ...props }: React.ComponentPropsWithoutRef<'del'>) {
  return <del className="text-brand-green-deleted line-through" {...props}>{children}</del>;
}

// ── MarkdownContent — renders markdown via ReactMarkdown ────────────────────

function MarkdownContent({ text }: { text: string }) {
  if (!text) return null;

  // B-2026-08-09-10: the model sometimes emits malformed markdown (unclosed
  // `**`, broken bullet lead-ins). Repair conservatively before render —
  // code fences and inline code are protected inside the pass.
  const repaired = repairMarkdown(text);

  return (
    <div className="text-[12px] text-brand-green-soft leading-relaxed overflow-hidden max-w-full break-words">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Code handling: distinguish inline vs block
          code: ({ node: _node, inline, className, children, ...props }: any) => {
            const match = /language-(\w+)/.exec(className || '');
            // If it has a language class or contains a newline, it's a block code
            if (!inline && (match || String(children).includes('\n'))) {
              return (
                <code className={className} {...props}>
                  {children}
                </code>
              );
            }
            // Inline code
            return <MarkdownInlineCode {...props}>{children}</MarkdownInlineCode>;
          },
          pre: MarkdownPreBlock as any,
          a: MarkdownLink,
          table: MarkdownTable,
          thead: MarkdownTableHead,
          tr: MarkdownTableRow,
          th: ({ children, ...props }: any) => <MarkdownTableCell isHeader {...props}>{children}</MarkdownTableCell>,
          td: ({ children, ...props }: any) => <MarkdownTableCell {...props}>{children}</MarkdownTableCell>,
          h1: ({ children, ...props }: any) => <MarkdownHeading level={1} {...props}>{children}</MarkdownHeading>,
          h2: ({ children, ...props }: any) => <MarkdownHeading level={2} {...props}>{children}</MarkdownHeading>,
          h3: ({ children, ...props }: any) => <MarkdownHeading level={3} {...props}>{children}</MarkdownHeading>,
          h4: ({ children, ...props }: any) => <MarkdownHeading level={4} {...props}>{children}</MarkdownHeading>,
          h5: ({ children, ...props }: any) => <MarkdownHeading level={4} {...props}>{children}</MarkdownHeading>,
          h6: ({ children, ...props }: any) => <MarkdownHeading level={4} {...props}>{children}</MarkdownHeading>,
          ul: MarkdownUl,
          ol: MarkdownOl,
          li: MarkdownLi,
          p: MarkdownP,
          blockquote: MarkdownBlockquote,
          hr: MarkdownHr,
          strong: MarkdownStrong,
          em: MarkdownEm,
          del: MarkdownDel,
        }}
      >
        {repaired}
      </ReactMarkdown>
    </div>
  );
}

// ── MessageMetrics — per-message latency/token line (B-2026-08-09-3 / ADR-13) ──
// Renders a small muted line under each assistant reply, e.g. `39.9s · 0/321 tok`.
// Backward-compatible: messages without `performance` (old history, user turns)
// render exactly as before.
function MessageMetrics({ performance }: { performance: NonNullable<ChatMessageType['performance']> }) {
  const parts: string[] = [];
  if (performance.latencyMs) parts.push(formatLatency(performance.latencyMs));
  const prompt = performance.promptTokens ?? 0;
  const completion = performance.completionTokens ?? 0;
  if (prompt > 0 || completion > 0) {
    parts.push(`${prompt.toLocaleString()}/${completion.toLocaleString()} tok`);
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

export function ChatMessage({ message, isStreaming, onRetry }: ChatMessageProps) {
  const isUser = message.role === 'user';

  // Check if this message has diff data (from edit_file tool results)
  const diffHunks: DiffHunk[] = useMemo(() => {
    if (message.diffData?.hunks) {
      return message.diffData.hunks;
    }
    return [];
  }, [message.diffData]);

  return (
    <div className={`px-4 py-3 overflow-hidden group relative ${isUser ? 'justify-end' : 'justify-start border-l-2 border-l-brand-green/30'}`}>
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

          {/* ADR-36: the Agent's opening acknowledgement — streams as the
              first line of the reply, distinct from the final answer
              (`content`) that follows the tool work. */}
          {!isUser && message.acknowledgement && (
            <div className="text-[12px] text-brand-green-soft leading-relaxed break-words mb-1.5">
              <MarkdownContent text={message.acknowledgement} />
            </div>
          )}

          {/* Thinking block — the model's reasoning, auto-expanded while streaming */}
          {message.thinking && message.isAgent && (
            <ThinkingBlock thinking={message.thinking} thinkMs={message.thinkMs} isStreaming={isStreaming} />
          )}

          {/* Session 181 — F4 Frontend Phase Visibility. Agentic phase strip
              (plan_created, gate_passed, gate_failed_replan, orchestrator_replan_*,
              plan_node_advanced, agent_loop_failure). Renders between the
              thinking block and the tool cards so the user sees the agent's
              decision history — "I planned X → I verified Y → I replanned
              because Z" — the literal difference between a chat-with-tools
              and an agent. */}
          {message.agentPhases && message.agentPhases.length > 0 && (
            <AgentPhases phases={message.agentPhases} isStreaming={isStreaming} />
          )}

          {/* Live agent trace — every tool the agent ran, with verbatim input,
              realtime status (running → done/failed), duration and collapsible
              output. Previously the toolCalls array was populated by the SSE
              handler but never rendered, so the user saw only a spinner and
              then a wall of text — the agent's work was invisible. */}
          {/* ADR-34 B-11: chat shows compact tool chips only — the full
              expandable timeline + per-step code/output cards live in the
              Agent Workspace (the canonical live surface per B-9). This
              removes the duplication where the chat transcript mirrored the
              Actions panel's detailed view. */}
          {message.toolCalls && message.toolCalls.length > 0 && (
            <ToolSteps compact toolCalls={message.toolCalls} isStreaming={isStreaming} />
          )}

          {/* ADR-20: canonical error card — a failed reply renders this
              instead of a raw provider payload. Content is empty on error
              replies (the backend streams no tokens), so the card IS the
              message. Try again re-sends the preceding prompt. */}
          {!isUser && message.error && (
            <ErrorMessage error={message.error} onRetry={onRetry} />
          )}

          {/* Content — rendered as Markdown for assistant, plain for user */}
          {message.content && (
            isUser ? (
              <div className="text-[12px] text-brand-amber-soft leading-relaxed whitespace-pre-wrap break-words overflow-wrap-anywhere">
                {message.content}
              </div>
            ) : (
              <MarkdownContent text={message.content} />
            )
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

          {/* Diff block — rendered when edit_file produces structured diff hunks */}
          {diffHunks.length > 0 && (
            <DiffBlock
              hunks={diffHunks}
              language={message.diffData?.language || ''}
              showActions={true}
              isStreaming={isStreaming}
            />
          )}

          {/* File results */}
          {message.fileResults && message.fileResults.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {message.fileResults.map((fr) => (
                <FileResultChip key={fr.id} result={fr} />
              ))}
            </div>
          )}

          {/* Per-message performance line — only on assistant replies with metrics */}
          {!isUser && message.performance && <MessageMetrics performance={message.performance} />}

          {/* Permission gate for pending writes */}
          {message.pendingWrite && (
            <PermissionGate
              pending={message.pendingWrite}
              onResolved={(_result) => {
                // The gate is self-contained — no parent state update needed.
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
