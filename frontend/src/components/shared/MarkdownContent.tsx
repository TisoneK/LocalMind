'use client';

/**
 * Shared markdown pipeline — the one canonical renderer for model-authored
 * markdown in chat surfaces (assistant answers, the thinking block, the
 * opening acknowledgement).
 *
 * Extracted verbatim from ChatMessage.tsx so every surface formats the
 * model's output identically: conservative markdown repair, GFM, themed
 * green-black components, syntax-highlighted code blocks with per-language
 * tooling.
 */

import React, { useState, useCallback, useMemo } from 'react';
import { Check, Copy } from 'lucide-react';
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
import { repairMarkdown } from '@/lib/markdownRepair';

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
// Models routinely put `<br>` in table cells for multi-line values (GFM tables
// can't hold a real newline). react-markdown (no rehype-raw) leaves it as the
// literal text "<br>", which looks broken. Convert those literals to real line
// breaks — scoped to table cells, and only <br> (no other raw HTML), so it's safe.
function withLineBreaks(children: React.ReactNode): React.ReactNode {
  return React.Children.map(children, (child, i) => {
    if (typeof child === 'string' && /<br\s*\/?>/i.test(child)) {
      const parts = child.split(/<br\s*\/?>/i);
      return parts.flatMap((part, j) => (j === 0 ? [part] : [<br key={`br-${i}-${j}`} />, part]));
    }
    return child;
  });
}

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
        {withLineBreaks(children)}
      </th>
    );
  }
  // A short plain value ("113 Gi", "32%", "26 Gi") must not wrap in a narrow column; long text may.
  const plain = typeof children === 'string' ? children : Array.isArray(children) && children.every((c) => typeof c === 'string') ? children.join('') : '';
  const short = plain.length > 0 && plain.length <= 16;
  return (
    <td className={`px-3 py-2 align-middle text-brand-green-soft ${short ? 'whitespace-nowrap' : ''}`} {...props}>
      {withLineBreaks(children)}
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

export function MarkdownContent({ text }: { text: string }) {
  if (!text) return null;

  // The model sometimes emits malformed markdown (unclosed `**`, broken
  // bullet lead-ins). Repair conservatively before render — code fences and
  // inline code are protected inside the pass.
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
