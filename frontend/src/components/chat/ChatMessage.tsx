'use client';

import React, { useState, useCallback, useMemo } from 'react';
import { User, Bot, Copy, Check, FileEdit, FilePlus, FileMinus } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { ChatMessage as ChatMessageType, FileResult, PendingWrite } from '@/types';
import { ThinkingBlock } from './ThinkingBlock';
import { ToolSteps } from '@/components/chat/ToolSteps';
import { DiffBlock, parseUnifiedDiff, type DiffHunk } from '@/components/shared/DiffBlock';

interface ChatMessageProps {
  message: ChatMessageType;
  /** Whether this message is currently being streamed (affects ThinkingBlock expansion) */
  isStreaming?: boolean;
}

function FileResultChip({ result }: { result: FileResult }) {
  const statusConfig = {
    created: { icon: <FilePlus className="h-3 w-3" />, color: 'text-[#39d353] border-[#39d353]/30 bg-[#39d353]/5' },
    modified: { icon: <FileEdit className="h-3 w-3" />, color: 'text-[#e8a420] border-[#e8a420]/30 bg-[#e8a420]/5' },
    deleted: { icon: <FileMinus className="h-3 w-3" />, color: 'text-[#e05555] border-[#e05555]/30 bg-[#e05555]/5' },
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
    style['pre[class*="language-"]'] = { ...style['pre[class*="language-"]'], background: 'none', margin: 0, padding: 0, fontSize: '12px', lineHeight: '1.6', color: '#d4e8d4' };
    style['code[class*="language-"]'] = { ...style['code[class*="language-"]'], background: 'none', fontSize: '12px', lineHeight: '1.6', color: '#d4e8d4' };
    return style;
  }, []);

  return (
    <div className="rounded-md border border-[#1a2a1a] overflow-hidden mb-2 max-w-full shadow-lg shadow-black/20">
      <div className="flex items-center justify-between px-3 py-1.5 bg-[#0a120a] border-b border-[#1a2a1a]">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[10px] font-mono text-[#8ab08a] uppercase shrink-0">{language || 'text'}</span>
          {filename && <span className="text-[10px] text-[#8ab08a] truncate">— {filename}</span>}
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
              className="flex items-center gap-1 text-[10px] text-[#39d353] hover:text-[#5af75a] transition-colors border border-[#39d353]/20 rounded px-1.5 py-0.5 hover:bg-[#39d353]/5"
              title="Run in terminal"
            >
              <span>▶</span><span>Run</span>
            </button>
          )}
          <button
            onClick={handleCopy}
            className="flex items-center gap-1 text-[10px] text-[#5a7a5a] hover:text-[#8ab08a] transition-colors"
          >
            {copied ? <><Check className="h-3 w-3 text-[#39d353]" /><span className="text-[#39d353]">Copied</span></> : <><Copy className="h-3 w-3" /><span>Copy</span></>}
          </button>
        </div>
      </div>
      <div className="bg-[#080d08] overflow-x-auto max-w-full">
        <div className="flex">
          <div className="shrink-0 border-r border-[#111a11] bg-[#080d08] py-2 pr-3 pl-3 text-right select-none">
            {code.split('\n').map((_, i) => (
              <div key={i} className="text-[11px] font-mono leading-[1.6] text-[#3a5a3a]">{i + 1}</div>
            ))}
          </div>
          <div className="flex-1 py-2 pl-4 pr-4 overflow-x-auto">
            <SyntaxHighlighter
              language={language || 'text'}
              style={customStyle}
              customStyle={{ background: 'none', margin: 0, padding: 0 }}
              codeTagProps={{ style: { fontSize: '12px', lineHeight: '1.6', fontFamily: 'var(--font-geist-mono), "Cascadia Code", "Fira Code", Consolas, monospace', color: '#d4e8d4' } }}
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
function MarkdownPreBlock({ children, ...props }: React.ComponentPropsWithoutRef<'pre'> & { children?: React.ReactNode }) {
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
    style['pre[class*="language-"]'] = { ...style['pre[class*="language-"]'], background: 'none', margin: 0, padding: 0, fontSize: '12px', lineHeight: '1.6', color: '#d4e8d4' };
    style['code[class*="language-"]'] = { ...style['code[class*="language-"]'], background: 'none', fontSize: '12px', lineHeight: '1.6', color: '#d4e8d4' };
    return style;
  }, []);

  // Single-line, no language → render as inline code
  if (!lang && !codeText.includes('\n')) {
    return (
      <code className="font-mono text-[11.5px] bg-[#0a120a] px-[5px] py-[1px] rounded-[3px] text-[#7ddf7d] border border-[#1a2a1a]">
        {codeText}
      </code>
    );
  }

  return (
    <div className="rounded-md border border-[#1a2a1a] overflow-hidden my-2 font-mono max-w-full shadow-lg shadow-black/20">
      <div className="flex items-center justify-between px-3 py-1.5 bg-[#0a120a] border-b border-[#1a2a1a]">
        <span className="text-[10px] font-mono text-[#8ab08a] uppercase tracking-wider shrink-0">
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
              className="text-[10px] font-mono text-[#39d353] hover:text-[#5af75a] border border-[#39d353]/20 rounded px-1.5 py-0.5 cursor-pointer transition-colors hover:bg-[#39d353]/5"
              title="Run in terminal"
            >
              ▶ Run
            </button>
          )}
          <button
            onClick={handleCopy}
            className="flex items-center gap-1 text-[10px] font-mono text-[#5a7a5a] hover:text-[#8ab08a] transition-colors"
          >
            {copied ? <><Check className="h-3 w-3 text-[#39d353]" /><span className="text-[#39d353]">Copied</span></> : <><Copy className="h-3 w-3" /><span>Copy</span></>}
          </button>
        </div>
      </div>
      <div className="bg-[#080d08] overflow-x-auto max-w-full">
        <div className="flex">
          <div className="shrink-0 border-r border-[#111a11] bg-[#080d08] py-2 pr-3 pl-3 text-right select-none">
            {rawCode.split('\n').map((_, i) => (
              <div key={i} className="text-[11px] font-mono leading-[1.6] text-[#3a5a3a]">{i + 1}</div>
            ))}
          </div>
          <div className="flex-1 py-2 pl-4 pr-4 overflow-x-auto">
            <SyntaxHighlighter
              language={lang || 'text'}
              style={customStyle}
              customStyle={{ background: 'none', margin: 0, padding: 0 }}
              codeTagProps={{ style: { fontSize: '12px', lineHeight: '1.6', fontFamily: 'var(--font-geist-mono), "Cascadia Code", "Fira Code", Consolas, monospace', color: '#d4e8d4' } }}
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
      className="font-mono text-[11.5px] bg-[#0a120a] px-[5px] py-[1px] rounded-[3px] text-[#7ddf7d] border border-[#1a2a1a]"
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
      className="text-[#4a9eff] underline decoration-dotted underline-offset-2"
      title={href}
      {...props}
    >
      {children}
    </a>
  );
}

/** Styled table */
function MarkdownTable({ children, ...props }: React.ComponentPropsWithoutRef<'table'>) {
  return (
    <div className="overflow-x-auto my-2">
      <table className="border-collapse w-full text-[12px] font-mono" {...props}>
        {children}
      </table>
    </div>
  );
}

function MarkdownTableHead({ children, ...props }: React.ComponentPropsWithoutRef<'thead'>) {
  return (
    <thead className="border-b-2 border-[#27622e]" {...props}>
      {children}
    </thead>
  );
}

function MarkdownTableRow({ children, ...props }: React.ComponentPropsWithoutRef<'tr'>) {
  return (
    <tr className="border-b border-[#1a2a1a]" {...props}>
      {children}
    </tr>
  );
}

function MarkdownTableCell({ isHeader, children, ...props }: React.ComponentPropsWithoutRef<'th' | 'td'> & { isHeader?: boolean }) {
  if (isHeader) {
    return (
      <th className="px-2.5 py-1.5 text-left font-semibold text-[#39d353] text-[11px] tracking-wider uppercase bg-[#0d110d]" {...props}>
        {children}
      </th>
    );
  }
  return (
    <td className="px-2.5 py-1 text-[#d4e8d4]" {...props}>
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
    <div className={`${sz} ${fw} text-[#d4e8d4] mt-2.5 mb-1 font-sans`}{...props}>
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
    <li className="mb-0.5 leading-[1.65] text-[#d4e8d4]" {...props}>
      {children}
    </li>
  );
}

/** Styled paragraph */
function MarkdownP({ children, ...props }: React.ComponentPropsWithoutRef<'p'>) {
  return (
    <p className="my-0.5 leading-[1.7] text-[#d4e8d4]" {...props}>
      {children}
    </p>
  );
}

/** Styled blockquote */
function MarkdownBlockquote({ children, ...props }: React.ComponentPropsWithoutRef<'blockquote'>) {
  return (
    <blockquote className="my-1.5 py-1.5 px-3 border-l-2 border-[#1a3d1a] bg-[#0d110d] text-[#8ab08a] rounded-r-[4px]" {...props}>
      {children}
    </blockquote>
  );
}

/** Styled horizontal rule */
function MarkdownHr({ ...props }: React.ComponentPropsWithoutRef<'hr'>) {
  return (
    <hr className="border-none border-t border-[#1a2a1a] my-1.5" {...props} />
  );
}

/** Styled strong text */
function MarkdownStrong({ children, ...props }: React.ComponentPropsWithoutRef<'strong'>) {
  return <strong className="text-[#d4e8d4] font-[650]" {...props}>{children}</strong>;
}

/** Styled emphasis text */
function MarkdownEm({ children, ...props }: React.ComponentPropsWithoutRef<'em'>) {
  return <em className="text-[#8ab08a]" {...props}>{children}</em>;
}

/** Styled strikethrough (from remark-gfm) */
function MarkdownDel({ children, ...props }: React.ComponentPropsWithoutRef<'del'>) {
  return <del className="text-[#6a8a6a] line-through" {...props}>{children}</del>;
}

// ── MarkdownContent — renders markdown via ReactMarkdown ────────────────────

function MarkdownContent({ text }: { text: string }) {
  if (!text) return null;

  return (
    <div className="text-[12px] text-[#d4e8d4] leading-relaxed overflow-hidden max-w-full break-words">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Code handling: distinguish inline vs block
          code: ({ node, inline, className, children, ...props }: any) => {
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
        {text}
      </ReactMarkdown>
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
    } catch (err) {
      setStatus('error');
    }
  };

  const handleDeny = () => {
    setStatus('denied');
    onResolved('denied');
  };

  return (
    <div className="mt-2 rounded-md border border-[#e8a420]/30 bg-[#e8a420]/5 px-3 py-2">
      {status === 'pending' && (
        <>
          <div className="text-[11px] text-[#d4e8d4] mb-1.5">
            Allow LocalMind to write <strong className="text-[#e8a420]">{pending.filename || 'file'}</strong>?
          </div>
          <div className="font-mono text-[10px] text-[#8ab08a] mb-2 break-all">{pending.path}</div>
          <div className="flex gap-2">
            <button
              onClick={handleConfirm}
              className="px-2.5 py-1 text-[11px] font-medium rounded border border-[#39d353]/30 bg-[#39d353]/10 text-[#39d353] hover:bg-[#39d353]/20 transition-colors"
            >
              ✓ Yes, write it
            </button>
            <button
              onClick={handleDeny}
              className="px-2.5 py-1 text-[11px] font-medium rounded border border-[#e05555]/30 bg-[#e05555]/10 text-[#e05555] hover:bg-[#e05555]/20 transition-colors"
            >
              ✕ Cancel
            </button>
          </div>
        </>
      )}
      {status === 'writing' && (
        <div className="text-[11px] text-[#e8a420] animate-pulse">Writing file…</div>
      )}
      {status === 'done' && (
        <div className="text-[11px] text-[#39d353]">✓ Written successfully</div>
      )}
      {status === 'error' && (
        <div className="text-[11px] text-[#e05555]">Write failed. Try again or write manually.</div>
      )}
      {status === 'denied' && (
        <div className="text-[11px] text-[#8ab08a]">Write cancelled.</div>
      )}
    </div>
  );
}

// ── ChatMessage component ──────────────────────────────────────────────────

export function ChatMessage({ message, isStreaming }: ChatMessageProps) {
  const isUser = message.role === 'user';

  // Check if this message has diff data (from edit_file tool results)
  const diffHunks: DiffHunk[] = useMemo(() => {
    if (message.diffData?.hunks) {
      return message.diffData.hunks;
    }
    return [];
  }, [message.diffData]);

  return (
    <div className={`px-4 py-3 overflow-hidden ${isUser ? 'justify-end' : 'justify-start border-l-2 border-l-[#39d353]/30'}`}>
      <div className={`flex items-start gap-3 max-w-full ${isUser ? 'flex-row-reverse' : ''}`}>
        <div className={`flex-1 min-w-0 max-w-full overflow-hidden ${isUser ? 'items-end flex flex-col' : ''}`}>
          {/* Header */}
          <div className={`flex items-center gap-2 mb-1 ${isUser ? 'flex-row-reverse' : ''}`}>
            {/* Avatar for user messages */}
            {isUser && (
              <div
                className="w-6 h-6 rounded flex items-center justify-center shrink-0 mt-0.5 bg-[#e8a420]/10 text-[#e8a420]"
              >
                <User className="h-3.5 w-3.5" />
              </div>
            )}
            <span className={`text-[11px] font-medium ${isUser ? 'text-[#e8a420]' : 'text-[#39d353]'}`}>
              {isUser ? 'You' : 'LocalMind'}
            </span>
            <span className="text-[9px] text-[#8ab08a]">{message.timestamp}</span>
          </div>

          {/* Thinking block — includes tool call steps for clean UX */}
          {message.thinking && message.isAgent && (
            <ThinkingBlock thinking={message.thinking} thinkMs={message.thinkMs} isStreaming={isStreaming} />
          )}

          {/* Tool calls — shown INSIDE thinking block context only */}
          {message.toolCalls && message.toolCalls.length > 0 && (
            <div className="mb-2 max-w-full overflow-hidden opacity-70">
              <ToolSteps toolCalls={message.toolCalls} compact />
            </div>
          )}

          {/* Content — rendered as Markdown for assistant, plain for user */}
          {message.content && (
            isUser ? (
              <div className="text-[12px] text-[#f5e0a0] leading-relaxed whitespace-pre-wrap break-words overflow-wrap-anywhere">
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

          {/* Permission gate for pending writes */}
          {message.pendingWrite && (
            <PermissionGate
              pending={message.pendingWrite}
              onResolved={(result) => {
                // The gate is self-contained — no parent state update needed.
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
